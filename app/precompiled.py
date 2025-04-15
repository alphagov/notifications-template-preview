import base64
import math
import unicodedata
from io import BytesIO
from itertools import groupby
from operator import itemgetter

import fitz
import sentry_sdk
from flask import Blueprint, current_app, jsonify, request, send_file
from notifications_utils.pdf import is_letter_too_long, pdf_page_count
from notifications_utils.recipient_validation.postal_address import PostalAddress
from pdf2image import convert_from_bytes
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from reportlab.lib.colors import Color, black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app import InvalidRequest, ValidationFailed, auth
from app.embedded_fonts import contains_unembedded_fonts, embed_fonts
from app.preview import png_from_pdf
from app.transformation import (
    convert_pdf_to_cmyk,
    does_pdf_contain_cmyk,
    does_pdf_contain_rgb,
)

A4_WIDTH = 210.0
A4_HEIGHT = 297.0
PT_TO_MM = 1.0 / 72 * 25.4

NOTIFY_TAG_FROM_TOP_OF_PAGE = 1.8
NOTIFY_TAG_FROM_LEFT_OF_PAGE = 1.8
NOTIFY_TAG_BOUNDING_BOX_WIDTH = 15.191
NOTIFY_TAG_BOUNDING_BOX_HEIGHT = 6.149
NOTIFY_TAG_FONT_SIZE = 6
NOTIFY_TAG_LINE_HEIGHT = NOTIFY_TAG_FONT_SIZE * PT_TO_MM
NOTIFY_TAG_TEXT = "NOTIFY"
NOTIFY_TAG_BOUNDING_BOX = fitz.Rect(
    # add on a margin to ensure we capture all text
    0,  # x1
    0,  # y1
    NOTIFY_TAG_BOUNDING_BOX_WIDTH * mm,  # x2
    NOTIFY_TAG_BOUNDING_BOX_HEIGHT * mm,  # y2
)

ADDRESS_FONT_SIZE = 8
ADDRESS_LINE_HEIGHT = ADDRESS_FONT_SIZE + 0.5
FONT = "Arial"
TRUE_TYPE_FONT_FILE = FONT + ".ttf"

BORDER_LEFT_FROM_LEFT_OF_PAGE = 15.0
BORDER_RIGHT_FROM_LEFT_OF_PAGE = A4_WIDTH - 15.0
BORDER_TOP_FROM_TOP_OF_PAGE = 5.0
BORDER_BOTTOM_FROM_TOP_OF_PAGE = A4_HEIGHT - 5.0

BODY_TOP_FROM_TOP_OF_PAGE = 95.00

SERVICE_ADDRESS_LEFT_FROM_LEFT_OF_PAGE = 125.0
SERVICE_ADDRESS_RIGHT_FROM_LEFT_OF_PAGE = BORDER_RIGHT_FROM_LEFT_OF_PAGE
SERVICE_ADDRESS_TOP_FROM_TOP_OF_PAGE = BORDER_TOP_FROM_TOP_OF_PAGE
SERVICE_ADDRESS_BOTTOM_FROM_TOP_OF_PAGE = BODY_TOP_FROM_TOP_OF_PAGE

"""
NOTE: these points are outside of the boundaries specified by DVLA.
This is because we rewrite the address block, and these points say
where we look for the address before we rewrite it.
"""
ADDRESS_LEFT_FROM_LEFT_OF_PAGE = 24.60
ADDRESS_RIGHT_FROM_LEFT_OF_PAGE = 120.0
ADDRESS_TOP_FROM_TOP_OF_PAGE = 39.50
ADDRESS_BOTTOM_FROM_TOP_OF_PAGE = 66.30
ADDRESS_BOUNDING_BOX = fitz.Rect(
    # add on a margin to ensure we capture all text
    (ADDRESS_LEFT_FROM_LEFT_OF_PAGE - 3) * mm,  # x1
    (ADDRESS_TOP_FROM_TOP_OF_PAGE - 3) * mm,  # y1
    (ADDRESS_RIGHT_FROM_LEFT_OF_PAGE + 3) * mm,  # x2
    (ADDRESS_BOTTOM_FROM_TOP_OF_PAGE + 3) * mm,  # y2
)

LOGO_LEFT_FROM_LEFT_OF_PAGE = BORDER_LEFT_FROM_LEFT_OF_PAGE
LOGO_RIGHT_FROM_LEFT_OF_PAGE = SERVICE_ADDRESS_LEFT_FROM_LEFT_OF_PAGE
LOGO_TOP_FROM_TOP_OF_PAGE = BORDER_TOP_FROM_TOP_OF_PAGE
LOGO_BOTTOM_FROM_TOP_OF_PAGE = 30.00

A4_HEIGHT_IN_PTS = A4_HEIGHT * mm

MAX_FILESIZE = 2 * 1024 * 1024  # 2MB
ALLOWED_FILESIZE_INFLATION_PERCENTAGE = 50  # warn if filesize after sanitising has grown by more than 50%

precompiled_blueprint = Blueprint("precompiled_blueprint", __name__)


class NotifyCanvas(canvas.Canvas):
    def __init__(self, colour):
        self.packet = BytesIO()
        super().__init__(self.packet, pagesize=A4)

        self.setStrokeColor(colour)
        self.setFillColor(colour)

    def get_bytes(self):
        self.save()
        self.packet.seek(0)
        return self.packet

    def rect(self, pt1, pt2):
        """
        Draw a rectangle given two points that are two of the corners for it.

        pt1 and pt2 are two-tuples of two values in mm! (As in, you haven't already done "MY_VAL * mm")
        all values are from TOP LEFT of the page

        This function handles:
        * conversion from mm to points
        * conversion to bottom left coordinates
        * just give two x coords and two y coords and it'll figure out which is left vs right side of the rectangle
        """
        left_x = min(pt1[0], pt2[0]) * mm
        right_x = max(pt1[0], pt2[0]) * mm
        top_y = min(pt1[1], pt2[1]) * mm
        bottom_y = max(pt1[1], pt2[1]) * mm

        bottom_y_from_bottom = A4_HEIGHT_IN_PTS - bottom_y

        width = right_x - left_x
        height = bottom_y - top_y
        super().rect(left_x, bottom_y_from_bottom, width, height, fill=True, stroke=False)


class PrecompiledPostalAddress(PostalAddress):
    @property
    def error_code(self):
        if not self:
            return "address-is-empty"

        if not self.has_enough_lines:
            return "not-enough-address-lines"

        if self.has_too_many_lines:
            return "too-many-address-lines"

        if self.has_invalid_country_for_bfpo_address:
            return "has-country-for-bfpo-address"

        if not self.has_valid_last_line:
            if self.allow_international_letters:
                return "not-a-real-uk-postcode-or-country"

            if self.international:
                return "cant-send-international-letters"

            return "not-a-real-uk-postcode"

        if self.has_invalid_characters:
            return "invalid-char-in-address"

        if self.has_no_fixed_abode_address:
            return "no-fixed-abode-address"


@precompiled_blueprint.route("/precompiled/sanitise", methods=["POST"])
@auth.login_required
def sanitise_precompiled_letter():
    encoded_string = request.get_data()
    allow_international_letters = request.args.get("allow_international_letters") == "true"

    if not encoded_string:
        raise InvalidRequest("no-encoded-string")

    is_an_attachment = request.args.get("is_an_attachment") == "true"

    sanitise_json = sanitise_file_contents(
        encoded_string,
        allow_international_letters=allow_international_letters,
        filename=request.args.get("upload_id"),
        is_an_attachment=is_an_attachment,
    )
    status_code = 400 if sanitise_json.get("message") else 200

    return jsonify(sanitise_json), status_code


def _warn_if_filesize_has_grown(*, orig_filesize: int, new_filesize: int, filename: str) -> None:
    orig_kb = orig_filesize / 1024
    new_kb = new_filesize / 1024

    if new_filesize > MAX_FILESIZE:
        current_app.logger.error(
            (
                "template-preview post-sanitise filesize too big: "
                "filename=%s, orig_size=%iKb, new_size=%iKb, over max_filesize=%iMb"
            ),
            filename,
            orig_kb,
            new_kb,
            MAX_FILESIZE / 1024 / 1024,
        )

    elif orig_filesize * (1 + (ALLOWED_FILESIZE_INFLATION_PERCENTAGE / 100)) < new_filesize:
        current_app.logger.warning(
            (
                "template-preview post-sanitise filesize too big: "
                "filename=%s, orig_size=%iKb, new_size=%iKb, pct_bigger=%i%%"
            ),
            filename,
            orig_kb,
            new_kb,
            (new_filesize / orig_filesize - 1) * 100,
        )


def sanitise_file_contents(encoded_string, *, allow_international_letters, filename, is_an_attachment=False):
    """
    Given a PDF, returns a new PDF that has been sanitised and dvla approved 👍

    * makes sure letter meets DVLA's printable boundaries and page dimensions requirements
    * re-writes address block (to ensure it's in arial in the right location)
    * adds NOTIFY tag if not present
    """
    try:
        file_data = BytesIO(encoded_string)

        page_count = pdf_page_count(file_data)
        if is_letter_too_long(page_count):
            message = "letter-too-long"
            raise ValidationFailed(message, page_count=page_count)

        message, invalid_pages = get_invalid_pages_with_message(file_data, is_an_attachment=is_an_attachment)
        if message:
            raise ValidationFailed(message, invalid_pages, page_count=page_count)

        if is_an_attachment:
            file_data = normalise_fonts_and_colours(file_data, filename)
            recipient_address = None
        else:
            file_data, recipient_address = rewrite_pdf(
                file_data,
                page_count=page_count,
                allow_international_letters=allow_international_letters,
                filename=filename,
            )

        raw_file = file_data.read()

        _warn_if_filesize_has_grown(orig_filesize=len(encoded_string), new_filesize=len(raw_file), filename=filename)

        return {
            "recipient_address": recipient_address,
            "page_count": page_count,
            "message": None,
            "invalid_pages": None,
            "file": base64.b64encode(raw_file).decode("utf-8"),
        }
    # PdfReadError usually happens at pdf_page_count, when we first try to read the PDF.
    except (ValidationFailed, PdfReadError) as error:
        current_app.logger.warning(
            "Validation failed for precompiled pdf: %s for file name: %s",
            repr(error),
            filename,
            exc_info=True,
        )

        return {
            "page_count": getattr(error, "page_count", None),
            "recipient_address": None,
            "message": getattr(error, "message", "unable-to-read-the-file"),
            "invalid_pages": getattr(error, "invalid_pages", None),
            "file": None,
        }
    # Anything else is probably a bug but usually infrequent, so pretend it's invalid.
    except Exception as error:
        current_app.logger.exception(
            "Unexpected exception for precompiled pdf: %s for file name: %s",
            repr(error),
            filename,
        )

        return {
            "page_count": None,
            "recipient_address": None,
            "message": "unable-to-read-the-file",
            "invalid_pages": None,
            "file": None,
        }


def rewrite_pdf(file_data, *, page_count, allow_international_letters, filename):
    log_metadata_for_letter(file_data, filename)

    file_data, recipient_address = rewrite_address_block(
        file_data,
        page_count=page_count,
        allow_international_letters=allow_international_letters,
        filename=filename,
    )

    file_data = normalise_fonts_and_colours(file_data, filename)

    # during switchover, DWP and CYSP will still be sending the notify tag. Only add it if it's not already there
    if not is_notify_tag_present(file_data):
        current_app.logger.info("PDF does not contain Notify tag, adding one.")
        file_data = add_notify_tag_to_letter(file_data)
    else:
        current_app.logger.info("PDF already contains Notify tag (%s).", filename)

    return file_data, recipient_address


@sentry_sdk.trace
def normalise_fonts_and_colours(file_data, filename):
    if not does_pdf_contain_cmyk(file_data):
        current_app.logger.info("PDF does not contain CMYK data, converting to CMYK.")
        file_data = convert_pdf_to_cmyk(file_data)

    elif does_pdf_contain_rgb(file_data):
        current_app.logger.info("PDF contains RGB data, converting to CMYK.")
        file_data = convert_pdf_to_cmyk(file_data)

    if unembedded := contains_unembedded_fonts(file_data, filename):
        current_app.logger.info("PDF contains unembedded fonts: %s", ", ".join(unembedded))
        file_data = embed_fonts(file_data)

    return file_data


@precompiled_blueprint.route("/precompiled/overlay.png", methods=["POST"])
@auth.login_required
def overlay_template_png_for_page():
    """
    The admin app calls this multiple times to get pngs of each separate page to show on the front end.

    This endpoint expects a "page_number" param that _must_ be included. It also includes as the HTTP POST body the
    binary data of that individual page of the PDF.
    """
    encoded_string = request.get_data()

    if not encoded_string:
        raise InvalidRequest("no data received in POST")

    file_data = BytesIO(encoded_string)

    is_an_attachment = request.args.get("is_an_attachment", "").lower() == "true"

    if "is_first_page" in request.args and not is_an_attachment:
        is_first_page = request.args.get("is_first_page", "").lower() == "true"
    elif "page_number" in request.args:
        page = int(request.args.get("page_number"))
        is_first_page = page == 1 and not is_an_attachment  # page_number arg is one-indexed
    else:
        raise InvalidRequest(f"page_number or is_first_page must be specified in request params {request.args}")

    return send_file(
        path_or_file=png_from_pdf(
            _colour_no_print_areas_of_single_page_pdf_in_red(file_data, is_first_page=is_first_page),
            # the pdf is only one page, so this is always 1.
            page_number=1,
        ),
        mimetype="image/png",
    )


@precompiled_blueprint.route("/precompiled/overlay.pdf", methods=["POST"])
@auth.login_required
def overlay_template_pdf():
    """
    The api app calls this with a PDF as the POST body, expecting to receive a PDF back with the red overlay applied.

    This endpoint will raise an error if you try and include a page number because it assumes you meant to ask for a png
    in that case.
    """
    encoded_string = request.get_data()

    if not encoded_string:
        raise InvalidRequest("no data received in POST")

    if request.args:
        raise InvalidRequest(f"Did not expect any args but received {request.args}. Did you mean to call overlay.png?")

    pdf = PdfReader(BytesIO(encoded_string))

    for i in range(len(pdf.pages)):
        _colour_no_print_areas_of_page_in_red(pdf.pages[i], is_first_page=(i == 0))

    return send_file(path_or_file=bytesio_from_pdf(pdf), mimetype="application/pdf")


def log_metadata_for_letter(src_pdf, filename):
    """
    The purpose of logging metadata is to build up a picture of the variety of precompiled letters
    we process, which we then use to construct a set of anonymised PDFs to test with. Logging the
    filename means we can trace the Notification in order to contact the service to ask if they can
    produce an examplar version using the same method.
    """

    pdf = PdfReader(src_pdf)
    info = pdf.metadata

    if not info:
        current_app.logger.info('Processing letter "%s" with no document info metadata', filename)
    else:
        current_app.logger.info(
            'Processing letter "%(filename)s" with creator "%(creator)s" and producer "%(producer)s"',
            {"filename": filename, "creator": info.creator, "producer": info.producer},
        )


def add_notify_tag_to_letter(src_pdf):
    """
    Adds the word 'NOTIFY' to the first page of the PDF

    :param PdfReader src_pdf: A File object or an object that supports the standard read and seek methods
    """

    pdf = PdfReader(src_pdf)
    page = pdf.pages[0]
    can = NotifyCanvas(white)
    pdfmetrics.registerFont(TTFont(FONT, TRUE_TYPE_FONT_FILE))
    can.setFont(FONT, NOTIFY_TAG_FONT_SIZE)

    x = NOTIFY_TAG_FROM_LEFT_OF_PAGE * mm

    # Text is drawn from the bottom left of the page, so to draw from the top
    # we need to subtract the height. page.mediabox[3] Media box is an array
    # with the four corners of the page. The third coordinate is the height.
    #
    # Then lets take away the margin and the font size.
    y = float(page.mediabox[3]) - ((NOTIFY_TAG_FROM_TOP_OF_PAGE + NOTIFY_TAG_LINE_HEIGHT) * mm)

    can.drawString(x, y, NOTIFY_TAG_TEXT)

    # move to the beginning of the StringIO buffer
    notify_tag_pdf = PdfReader(can.get_bytes())

    notify_tag_page = notify_tag_pdf.pages[0]
    page.merge_page(notify_tag_page)

    return bytesio_from_pdf(pdf)


@sentry_sdk.trace
def get_invalid_pages_with_message(src_pdf, is_an_attachment=False):
    invalid_pages = _get_pages_with_invalid_orientation_or_size(src_pdf)
    if len(invalid_pages) > 0:
        return "letter-not-a4-portrait-oriented", invalid_pages

    pdf_to_validate = _overlay_printable_areas_with_white(src_pdf, is_an_attachment=is_an_attachment)
    invalid_pages = list(_get_out_of_bounds_pages(pdf_to_validate))
    if len(invalid_pages) > 0:
        return "content-outside-printable-area", invalid_pages

    invalid_pages = _get_pages_with_notify_tag(pdf_to_validate, is_an_attachment=is_an_attachment)
    if len(invalid_pages) > 0:
        # we really dont expect to see many of these so lets log
        current_app.logger.warning("notify tag found on pages %s", invalid_pages)
        return "notify-tag-found-in-content", invalid_pages

    return "", []


def _is_page_A4_portrait(page_height, page_width, rotation):
    if math.isclose(page_height, A4_HEIGHT, abs_tol=2) and math.isclose(page_width, 210, abs_tol=2):
        if rotation in [0, 180, None]:
            return True
    elif math.isclose(page_width, A4_HEIGHT, abs_tol=2) and math.isclose(page_height, 210, abs_tol=2):
        if rotation in [90, 270]:
            return True
    return False


def _get_pages_with_invalid_orientation_or_size(src_pdf):
    pdf = PdfReader(src_pdf)
    invalid_pages = []
    for page_num in range(len(pdf.pages)):
        page = pdf.pages[page_num]

        page_height = float(page.mediabox.height) / mm
        page_width = float(page.mediabox.width) / mm
        rotation = page.get("/Rotate")

        if not _is_page_A4_portrait(page_height, page_width, rotation):
            invalid_pages.append(page_num + 1)
            current_app.logger.warning(
                (
                    "Letter is not A4 portrait size on page %(page)s. "
                    "Rotate: %(rotate)s, height: %(height)smm, width: %(width)smm"
                ),
                {"page": page_num + 1, "rotate": rotation, "height": int(page_height), "width": int(page_width)},
            )
    return invalid_pages


def _overlay_printable_areas_with_white(src_pdf, is_an_attachment=False):
    """
    Overlays the printable areas onto the src PDF, this is so the code can check for a presence of non white in the
    areas outside the printable area.

    Our overlay function draws four areas in white. Logo, address, service address, and the body. Logo is the area
    above the address area. Service address runs from the top right, down the side of the letter to the right of
    the address area.

    This function subtracts/adds 1mm to make every boundary more generous. This is to solve pixel-hunting issues where
    letters fail validation because there's one pixel of the boundary, generally because of anti-aliasing some text.
    This doesn't affect the red overlays we draw when displaying to end users, so people should still layout their PDFs
    based on the published constraints.

    For letter attachments, there is no address page, so we overlay all pages like we would subsequent pages
    of a full letter.

    :param BytesIO src_pdf: A file-like
    :param Boolean is_an_attachment: a parameter that informs if the file-like is a full letter or a letter attachment
    :return BytesIO: New file like containing the overlaid pdf
    """

    pdf = PdfReader(src_pdf)
    page_number = 0

    if not is_an_attachment:
        _overlay_printable_areas_of_address_block_page_with_white(pdf)
        page_number = 1

    # For each subsequent page its just the body of text
    for page_num in range(page_number, len(pdf.pages)):
        page = pdf.pages[page_num]

        can = NotifyCanvas(white)

        # Each page of content
        pt1 = BORDER_LEFT_FROM_LEFT_OF_PAGE - 1, BORDER_TOP_FROM_TOP_OF_PAGE - 1
        pt2 = BORDER_RIGHT_FROM_LEFT_OF_PAGE + 1, BORDER_BOTTOM_FROM_TOP_OF_PAGE + 1
        can.rect(pt1, pt2)

        # move to the beginning of the StringIO buffer
        new_pdf = PdfReader(can.get_bytes())

        page.merge_page(new_pdf.pages[0])

    out = bytesio_from_pdf(pdf)
    # it's a good habit to put things back exactly the way we found them
    src_pdf.seek(0)

    return out


def _overlay_printable_areas_of_address_block_page_with_white(pdf):
    page = pdf.pages[0]
    can = NotifyCanvas(white)

    # Overlay the blanks where the service can print as per the template
    # The first page is more varied because of address blocks etc subsequent pages are more simple

    # Body
    pt1 = BORDER_LEFT_FROM_LEFT_OF_PAGE - 1, BODY_TOP_FROM_TOP_OF_PAGE - 1
    pt2 = BORDER_RIGHT_FROM_LEFT_OF_PAGE + 1, BORDER_BOTTOM_FROM_TOP_OF_PAGE + 1
    can.rect(pt1, pt2)

    # Service address block - the writeable area on the right hand side (up to the top right corner)
    pt1 = (
        SERVICE_ADDRESS_LEFT_FROM_LEFT_OF_PAGE - 1,
        SERVICE_ADDRESS_TOP_FROM_TOP_OF_PAGE - 1,
    )
    pt2 = (
        SERVICE_ADDRESS_RIGHT_FROM_LEFT_OF_PAGE + 1,
        SERVICE_ADDRESS_BOTTOM_FROM_TOP_OF_PAGE + 1,
    )
    can.rect(pt1, pt2)

    # Service Logo Block - the writeable area above the address (only as far across as the address extends)
    pt1 = BORDER_LEFT_FROM_LEFT_OF_PAGE - 1, BORDER_TOP_FROM_TOP_OF_PAGE - 1
    pt2 = LOGO_RIGHT_FROM_LEFT_OF_PAGE + 1, LOGO_BOTTOM_FROM_TOP_OF_PAGE + 1
    can.rect(pt1, pt2)

    # Citizen Address Block - the address window
    pt1 = ADDRESS_LEFT_FROM_LEFT_OF_PAGE - 1, ADDRESS_TOP_FROM_TOP_OF_PAGE - 1
    pt2 = ADDRESS_RIGHT_FROM_LEFT_OF_PAGE + 1, ADDRESS_BOTTOM_FROM_TOP_OF_PAGE + 1
    can.rect(pt1, pt2)

    # move to the beginning of the StringIO buffer
    new_pdf = PdfReader(can.get_bytes())

    page.merge_page(new_pdf.pages[0])


def _colour_no_print_areas_of_single_page_pdf_in_red(src_pdf, is_first_page):
    """
    Overlays the non-printable areas onto the src PDF, this is so users know which parts of they letter fail validation.
    This function expects that src_pdf only represents a single page. It adds red areas (if `is_first_page` is set, then
    it'll add red areas around the address window too) and returns a single page pdf.

    :param BytesIO src_pdf: A file-like representing a single page pdf
    :param bool is_first_page: true if we should overlay the address block red area too.
    """
    try:
        pdf = PdfReader(src_pdf)
    except PdfReadError as e:
        raise InvalidRequest(f"Unable to read the PDF data: {e}") from e

    if len(pdf.pages) != 1:
        # this function is used to render images, which call template-preview separately for each page. This function
        # should be colouring a single page pdf (which might be any individual page of an original precompiled letter)
        raise InvalidRequest("_colour_no_print_areas_of_page_in_red should only be called for a one-page-pdf")

    page = pdf.pages[0]
    _colour_no_print_areas_of_page_in_red(page, is_first_page)

    out = bytesio_from_pdf(pdf)
    # it's a good habit to put things back exactly the way we found them
    src_pdf.seek(0)
    return out


def _colour_no_print_areas_of_page_in_red(page, is_first_page):
    """
    Overlays the non-printable areas onto a single page. It adds red areas (if `is_first_page` is set, then it'll add
    red areas around the address window too) and returns a new page object that you can then merge .

    :param PageObject page: A page, as returned by PdfReader.pages[i]. Note: This is modified by this function.
    :param bool is_first_page: true if we should overlay the address block red area too.
    :return: None. It modifies the page object instead
    """
    red_transparent = Color(100, 0, 0, alpha=0.2)

    # Overlay the areas where the service can't print as per the template
    can = NotifyCanvas(red_transparent)

    # Each page of content
    # left margin:
    pt1 = 0, 0
    pt2 = BORDER_LEFT_FROM_LEFT_OF_PAGE, A4_HEIGHT
    can.rect(pt1, pt2)
    # top margin:
    pt1 = BORDER_LEFT_FROM_LEFT_OF_PAGE, 0
    pt2 = BORDER_RIGHT_FROM_LEFT_OF_PAGE, BORDER_TOP_FROM_TOP_OF_PAGE
    can.rect(pt1, pt2)
    # right margin:
    pt1 = BORDER_RIGHT_FROM_LEFT_OF_PAGE, 0
    pt2 = A4_WIDTH, A4_HEIGHT
    can.rect(pt1, pt2)
    # bottom margin:
    pt1 = BORDER_LEFT_FROM_LEFT_OF_PAGE, BORDER_BOTTOM_FROM_TOP_OF_PAGE
    pt2 = BORDER_RIGHT_FROM_LEFT_OF_PAGE, A4_HEIGHT
    can.rect(pt1, pt2)

    # The first page is more varied because of address blocks etc subsequent pages are more simple
    if is_first_page:
        # left from address block (from logo area all the way to body)
        pt1 = BORDER_LEFT_FROM_LEFT_OF_PAGE, LOGO_BOTTOM_FROM_TOP_OF_PAGE
        pt2 = ADDRESS_LEFT_FROM_LEFT_OF_PAGE, BODY_TOP_FROM_TOP_OF_PAGE
        can.rect(pt1, pt2)

        # directly above address block
        pt1 = ADDRESS_LEFT_FROM_LEFT_OF_PAGE, LOGO_BOTTOM_FROM_TOP_OF_PAGE
        pt2 = ADDRESS_RIGHT_FROM_LEFT_OF_PAGE, ADDRESS_TOP_FROM_TOP_OF_PAGE
        can.rect(pt1, pt2)

        # right from address block (from logo area all the way to body)
        pt1 = ADDRESS_RIGHT_FROM_LEFT_OF_PAGE, LOGO_BOTTOM_FROM_TOP_OF_PAGE
        pt2 = SERVICE_ADDRESS_LEFT_FROM_LEFT_OF_PAGE, BODY_TOP_FROM_TOP_OF_PAGE
        can.rect(pt1, pt2)

        # below address block
        pt1 = ADDRESS_LEFT_FROM_LEFT_OF_PAGE, ADDRESS_BOTTOM_FROM_TOP_OF_PAGE
        pt2 = ADDRESS_RIGHT_FROM_LEFT_OF_PAGE, BODY_TOP_FROM_TOP_OF_PAGE
        can.rect(pt1, pt2)

    # move to the beginning of the StringIO buffer
    new_pdf = PdfReader(can.get_bytes())

    # note that the original page object is modified. I don't know if the original underlying src_pdf buffer is affected
    # but i assume not.
    page.merge_page(new_pdf.pages[0])


def _get_out_of_bounds_pages(src_pdf_bytes):
    """
    Checks each pixel of the image to determine the colour - if any pixel is not white return false
    :param BytesIO src_pdf_bytes: filelike containing PDF from which to take pages.
    :return: iterable containing page numbers (1-indexed)
    :return: False if there is any colour but white, otherwise true
    """
    images = convert_from_bytes(src_pdf_bytes.read())
    src_pdf_bytes.seek(0)

    for i, image in enumerate(images, start=1):
        colours = image.convert("RGB").getcolors()

        if colours is None:
            current_app.logger.warning("Letter has literally zero colours of any description on page %s???", i)
            yield i
            continue

        for colour in colours:
            if str(colour[1]) != "(255, 255, 255)":
                current_app.logger.warning("Letter exceeds boundaries on page %s", i)
                yield i
                break


@sentry_sdk.trace
def rewrite_address_block(pdf, *, page_count, allow_international_letters, filename):
    address = extract_address_block(pdf)
    address.allow_international_letters = allow_international_letters

    if address.error_code:
        raise ValidationFailed(address.error_code, [1], page_count=page_count)

    pdf = redact_precompiled_letter_address_block(pdf)
    pdf = add_address_to_precompiled_letter(pdf, address.normalised)
    return pdf, address.normalised


def _extract_text_from_first_page_of_pdf(pdf, rect):
    """
    Extracts all text within a block on the first page

    :param BytesIO pdf: pdf bytestream from which to extract
    :param rect: rectangle describing the area to extract from
    :return: Any text found
    """
    pdf.seek(0)
    doc = fitz.open("pdf", pdf)
    page = doc[0]
    ret = _extract_text_from_page(page, rect)
    pdf.seek(0)
    return ret


def _extract_text_from_page(page, rect):
    """
    Extracts all text within a block.
    Taken from this script: https://github.com/pymupdf/PyMuPDF-Utilities/blob/master/textboxtract.py
    Which was referenced in the library docs here:
    https://pymupdf.readthedocs.io/en/latest/faq/#how-to-extract-text-from-within-a-rectangle

    words and mywords variables are lists of tuples. Each tuple represents one word from the document,
    and is structured as follows:
    (x1, y1, x2, y2, word value, paragraph number, line number, word position within the line)

    :param fitz.Page page: fitz page object from which to extract
    :param rect: rectangle describing the area to extract from
    :return: Any text found
    """
    words = page.get_text_words()
    mywords = [w for w in words if fitz.Rect(w[:4]).intersects(rect)]

    def _get_address_from_get_textwords():
        return page.get_text(clip=rect).strip()

    mywords.sort(key=itemgetter(-3, -2, -1))
    group = groupby(mywords, key=itemgetter(3))
    extracted_text = []
    for _y2, gwords in group:
        extracted_text.append(" ".join(w[4] for w in gwords))
    extracted_text = "\n".join(extracted_text)

    if rect != NOTIFY_TAG_BOUNDING_BOX and PrecompiledPostalAddress(
        _get_address_from_get_textwords()
    ) != PrecompiledPostalAddress(extracted_text):
        # grouping by paragraph ended up different to grouping by y2. lets just log for now. we might want to swap over
        # in the future but without knowing how much it changes we cant be sure
        current_app.logger.info("Address extraction different between y2 and get_text")

    # normalizing to NFKD replaces characters with compatibility mode equivalents - including replacing
    # ligatures like ﬀ with ff
    return unicodedata.normalize("NFKD", extracted_text)


def extract_address_block(pdf):
    """
    Extracts all text within the text block
    :param BytesIO pdf: pdf bytestream from which to extract
    :return: multi-line address string
    """
    return PrecompiledPostalAddress(_extract_text_from_first_page_of_pdf(pdf, ADDRESS_BOUNDING_BOX))


def is_notify_tag_present(pdf):
    """
    pdf is a file-like object containing at least the first page of a PDF
    """
    return _extract_text_from_first_page_of_pdf(pdf, NOTIFY_TAG_BOUNDING_BOX) == "NOTIFY"


def _get_pages_with_notify_tag(src_pdf_bytes, is_an_attachment=False):
    """
    Looks at all pages (except for page 1 for full letters), and returns any pages that have the NOTIFY tag
    in the top left. DVLA can't process letters with NOTIFY tags on later pages because their software thinks
    it's a marker signifying when a new letter starts. We've seen services attach pages from previous letters
    sent via notify
    """
    src_pdf_bytes.seek(0)
    doc = fitz.open("pdf", src_pdf_bytes)
    starting_page_index = 1
    if is_an_attachment:
        starting_page_index = 0
    if doc.page_count == starting_page_index:
        # if no extra pages we dont need to do anything
        src_pdf_bytes.seek(0)
        return []

    invalid_pages = [
        page.number + 1  # return 1 indexed pages
        for page in doc.pages(start=starting_page_index)
        if _extract_text_from_page(page, NOTIFY_TAG_BOUNDING_BOX) == "NOTIFY"
    ]

    src_pdf_bytes.seek(0)
    return invalid_pages


def redact_precompiled_letter_address_block(pdf):
    pdf.seek(0)  # make sure we're at the beginning
    doc = fitz.open("pdf", pdf)
    first_page = doc[0]

    first_page.add_redact_annot(ADDRESS_BOUNDING_BOX)

    first_page.apply_redactions()
    return BytesIO(doc.tobytes())


def add_address_to_precompiled_letter(pdf, address):
    """
    Given a pdf, blanks out any existing address (adds a white rectangle over existing address),
    and then puts the supplied address in over it.

    :param BytestIO pdf: pdf bytestream from which to extract
    :return: BytesIO new pdf
    """
    old_pdf = PdfReader(pdf)

    can = NotifyCanvas(white)

    # x, y coordinates are from bottom left of page
    bottom_left_corner_x = ADDRESS_LEFT_FROM_LEFT_OF_PAGE * mm
    bottom_left_corner_y = A4_HEIGHT_IN_PTS - (ADDRESS_BOTTOM_FROM_TOP_OF_PAGE * mm)

    # Cover the existing address block with a white rectangle
    pt1 = ADDRESS_LEFT_FROM_LEFT_OF_PAGE, ADDRESS_TOP_FROM_TOP_OF_PAGE
    pt2 = ADDRESS_RIGHT_FROM_LEFT_OF_PAGE, ADDRESS_BOTTOM_FROM_TOP_OF_PAGE
    can.rect(pt1, pt2)

    # start preparing to write address
    pdfmetrics.registerFont(TTFont(FONT, TRUE_TYPE_FONT_FILE))

    # text origin is bottom left of the first character. But we've got multiple lines, and we want to match the
    # bottom left of the bottom line of text to the bottom left of the address block.
    # So calculate the number of additional lines by counting the newlines, and multiply that by the line height
    address_lines_after_first = address.count("\n")
    first_character_of_address = bottom_left_corner_y + (ADDRESS_LINE_HEIGHT * address_lines_after_first)

    textobject = can.beginText()
    textobject.setFillColor(black)
    textobject.setFont(FONT, ADDRESS_FONT_SIZE, leading=ADDRESS_LINE_HEIGHT)
    # push the text up two points (25%) in case the last line (postcode) has any chars with descenders - g, j, p, q, y.
    # we don't want them going out of the address window
    textobject.setRise(2)
    textobject.setTextOrigin(bottom_left_corner_x, first_character_of_address)
    textobject.textLines(address)
    can.drawText(textobject)

    return overlay_first_page_of_pdf_with_new_content(old_pdf, can.get_bytes())


def overlay_first_page_of_pdf_with_new_content(old_pdf_reader, new_page_buffer):
    """
    Does not overwrite old PDF. Instead overlays new content - for example, we call this where new_page_buffer is a
    transparent page that just contains "NOTIFY" in white text. the old content is still there, and NOTIFY is written
    on top of it.

    :param PdfReader old_pdf_reader: a rich pdf object that we want to add content to the first page of
    :param BytesIO new_page_buffer: BytesIO containing the raw bytes for the new content
    """
    # move to the beginning of the buffer and replay it into a pdf writer
    new_page_buffer.seek(0)
    new_pdf = PdfReader(new_page_buffer)
    new_page = new_pdf.pages[0]
    existing_page = old_pdf_reader.pages[0]
    # combines the two pages - overlaying, not overwriting.
    existing_page.merge_page(new_page)

    return bytesio_from_pdf(old_pdf_reader)


def bytesio_from_pdf(pdf):
    """
    :param PdfReader pdf: A rich pdf object
    :returns BytesIO: The raw bytes behind that PDF
    """
    output = PdfWriter()
    output.append_pages_from_reader(pdf)

    pdf_bytes = BytesIO()
    output.write(pdf_bytes)
    pdf_bytes.seek(0)
    return pdf_bytes
