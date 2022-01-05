import base64
import math
import re
from io import BytesIO
from itertools import groupby
from operator import itemgetter

import fitz
from flask import Blueprint, current_app, jsonify, request, send_file
from notifications_utils.pdf import is_letter_too_long, pdf_page_count
from notifications_utils.postal_address import PostalAddress
from pdf2image import convert_from_bytes
from PIL import ImageFont
from PyPDF2 import PdfFileReader, PdfFileWriter
from PyPDF2.utils import PdfReadError
from reportlab.lib.colors import Color, black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

import app.pdf_redactor as pdf_redactor
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

NOTIFY_TAG_FROM_TOP_OF_PAGE = 4.3
NOTIFY_TAG_FROM_LEFT_OF_PAGE = 7.4
NOTIFY_TAG_FONT_SIZE = 6
NOTIFY_TAG_TEXT = "NOTIFY"
NOTIFY_TAG_LINE_SPACING = 1.75
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

ADDRESS_LEFT_FROM_LEFT_OF_PAGE = 24.60
ADDRESS_RIGHT_FROM_LEFT_OF_PAGE = 120.0
ADDRESS_TOP_FROM_TOP_OF_PAGE = 40.00
ADDRESS_BOTTOM_FROM_TOP_OF_PAGE = 66.20

LOGO_LEFT_FROM_LEFT_OF_PAGE = BORDER_LEFT_FROM_LEFT_OF_PAGE
LOGO_RIGHT_FROM_LEFT_OF_PAGE = SERVICE_ADDRESS_LEFT_FROM_LEFT_OF_PAGE
LOGO_TOP_FROM_TOP_OF_PAGE = BORDER_TOP_FROM_TOP_OF_PAGE
LOGO_BOTTOM_FROM_TOP_OF_PAGE = 30.00

A4_HEIGHT_IN_PTS = A4_HEIGHT * mm

precompiled_blueprint = Blueprint('precompiled_blueprint', __name__)


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

        if not self.has_valid_last_line:

            if self.allow_international_letters:
                return "not-a-real-uk-postcode-or-country"

            if self.international:
                return "cant-send-international-letters"

            return "not-a-real-uk-postcode"

        if self.has_invalid_characters:
            return "invalid-char-in-address"

    @property
    def as_regex(self):
        string = escape_special_characters_for_regex(self.raw_address)
        return handle_irregular_whitespace_characters(string)


@precompiled_blueprint.route('/precompiled/sanitise', methods=['POST'])
@auth.login_required
def sanitise_precompiled_letter():
    encoded_string = request.get_data()
    allow_international_letters = (
        request.args.get('allow_international_letters') == 'true'
    )

    if not encoded_string:
        raise InvalidRequest('no-encoded-string')

    sanitise_json = sanitise_file_contents(
        encoded_string,
        allow_international_letters=allow_international_letters,
        filename=request.args.get('upload_id'),
    )
    status_code = 400 if sanitise_json.get('message') else 200

    return jsonify(sanitise_json), status_code


def sanitise_file_contents(encoded_string, *, allow_international_letters, filename):
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

        message, invalid_pages = get_invalid_pages_with_message(file_data)
        if message:
            raise ValidationFailed(message, invalid_pages, page_count=page_count)

        file_data, recipient_address, redaction_failed_message = rewrite_pdf(
            file_data,
            page_count=page_count,
            allow_international_letters=allow_international_letters,
            filename=filename
        )

        return {
            "recipient_address": recipient_address,
            "page_count": page_count,
            "message": None,
            "invalid_pages": None,
            "redaction_failed_message": redaction_failed_message,
            "file": base64.b64encode(file_data.read()).decode('utf-8')
        }
    # PdfReadError usually happens at pdf_page_count, when we first try to read the PDF.
    except (ValidationFailed, PdfReadError) as error:
        current_app.logger.warning(
            f'Validation failed for precompiled pdf: {repr(error)} for file name: {filename}',
            exc_info=True
        )

        return {
            "page_count": getattr(error, 'page_count', None),
            "recipient_address": None,
            "message": getattr(error, 'message', 'unable-to-read-the-file'),
            "invalid_pages": getattr(error, 'invalid_pages', None),
            "file": None
        }
    # Anything else is probably a bug but usually infrequent, so pretend it's invalid.
    except Exception as error:
        current_app.logger.error(
            f'Unexpected exception for precompiled pdf: {repr(error)} for file name: {filename}'
        )

        return {
            "page_count": None,
            "recipient_address": None,
            "message": 'unable-to-read-the-file',
            "invalid_pages": None,
            "file": None
        }


def rewrite_pdf(file_data, *, page_count, allow_international_letters, filename):
    log_metadata_for_letter(file_data, filename)

    file_data, recipient_address, redaction_failed_message = rewrite_address_block(
        file_data,
        page_count=page_count,
        allow_international_letters=allow_international_letters,
    )

    if not does_pdf_contain_cmyk(file_data):
        current_app.logger.info('PDF does not contain CMYK data, converting to CMYK.')
        file_data = convert_pdf_to_cmyk(file_data)

    elif does_pdf_contain_rgb(file_data):
        current_app.logger.info('PDF contains RGB data, converting to CMYK.')
        file_data = convert_pdf_to_cmyk(file_data)

    if unembedded := contains_unembedded_fonts(file_data, filename):
        current_app.logger.info(f'PDF contains unembedded fonts: {unembedded}')
        file_data = embed_fonts(file_data)

    # during switchover, DWP and CYSP will still be sending the notify tag. Only add it if it's not already there
    if not is_notify_tag_present(file_data):
        current_app.logger.info('PDF does not contain Notify tag, adding one.')
        file_data = add_notify_tag_to_letter(file_data)
    else:
        current_app.logger.info(f'PDF already contains Notify tag ({filename}).')

    return file_data, recipient_address, redaction_failed_message


@precompiled_blueprint.route("/precompiled/overlay.png", methods=['POST'])
@auth.login_required
def overlay_template_png_for_page():
    """
    The admin app calls this multiple times to get pngs of each separate page to show on the front end.

    This endpoint expects a "page_number" param that _must_ be included. It also includes as the HTTP POST body the
    binary data of that individual page of the PDF.
    """
    encoded_string = request.get_data()

    if not encoded_string:
        raise InvalidRequest('no data received in POST')

    file_data = BytesIO(encoded_string)

    if 'is_first_page' in request.args:
        is_first_page = request.args.get('is_first_page', '').lower() == 'true'
    elif 'page_number' in request.args:
        page = int(request.args.get('page_number'))
        is_first_page = page == 1  # page_number arg is one-indexed
    else:
        raise InvalidRequest(f'page_number or is_first_page must be specified in request params {request.args}')

    return send_file(
        path_or_file=png_from_pdf(
            _colour_no_print_areas_of_single_page_pdf_in_red(file_data, is_first_page=is_first_page),
            # the pdf is only one page, so this is always 1.
            page_number=1
        ),
        mimetype='image/png',
    )


@precompiled_blueprint.route("/precompiled/overlay.pdf", methods=['POST'])
@auth.login_required
def overlay_template_pdf():
    """
    The api app calls this with a PDF as the POST body, expecting to receive a PDF back with the red overlay applied.

    This endpoint will raise an error if you try and include a page number because it assumes you meant to ask for a png
    in that case.
    """
    encoded_string = request.get_data()

    if not encoded_string:
        raise InvalidRequest('no data received in POST')

    if request.args:
        raise InvalidRequest(f'Did not expect any args but received {request.args}. Did you mean to call overlay.png?')

    pdf = PdfFileReader(BytesIO(encoded_string))

    for i in range(pdf.numPages):
        _colour_no_print_areas_of_page_in_red(pdf.getPage(i), is_first_page=(i == 0))

    return send_file(path_or_file=bytesio_from_pdf(pdf), mimetype='application/pdf')


def log_metadata_for_letter(src_pdf, filename):
    """
    The purpose of logging metadata is to build up a picture of the variety of precompiled letters
    we process, which we then use to construct a set of anonymised PDFs to test with. Logging the
    filename means we can trace the Notification in order to contact the service to ask if they can
    produce an examplar version using the same method.
    """

    pdf = PdfFileReader(src_pdf)
    info = pdf.getDocumentInfo()

    if not info:
        current_app.logger.info(
            f'Processing letter "{filename}" with no document info metadata'
        )
    else:
        current_app.logger.info(
            f'Processing letter "{filename}" with creator "{info.creator}" and producer "{info.producer}"'
        )


def add_notify_tag_to_letter(src_pdf):
    """
    Adds the word 'NOTIFY' to the first page of the PDF

    :param PdfFileReader src_pdf: A File object or an object that supports the standard read and seek methods
    """

    pdf = PdfFileReader(src_pdf)
    page = pdf.getPage(0)
    can = NotifyCanvas(white)
    pdfmetrics.registerFont(TTFont(FONT, TRUE_TYPE_FONT_FILE))
    can.setFont(FONT, NOTIFY_TAG_FONT_SIZE)

    font = ImageFont.truetype(TRUE_TYPE_FONT_FILE, NOTIFY_TAG_FONT_SIZE)
    line_width, line_height = font.getsize('NOTIFY')

    center_of_left_margin = (BORDER_LEFT_FROM_LEFT_OF_PAGE * mm) / 2
    half_width_of_notify_tag = line_width / 2
    x = center_of_left_margin - half_width_of_notify_tag

    # page.mediaBox[3] Media box is an array with the four corners of the page
    # We want height so can use that co-ordinate which is located in [3]
    # The lets take away the margin and the ont size
    # 1.75 for the line spacing
    y = float(page.mediaBox[3]) - (float(NOTIFY_TAG_FROM_TOP_OF_PAGE * mm + line_height - NOTIFY_TAG_LINE_SPACING))

    can.drawString(x, y, NOTIFY_TAG_TEXT)

    # move to the beginning of the StringIO buffer
    notify_tag_pdf = PdfFileReader(can.get_bytes())

    notify_tag_page = notify_tag_pdf.getPage(0)
    page.mergePage(notify_tag_page)

    return bytesio_from_pdf(pdf)


def get_invalid_pages_with_message(src_pdf):
    invalid_pages = _get_pages_with_invalid_orientation_or_size(src_pdf)
    if len(invalid_pages) > 0:
        return "letter-not-a4-portrait-oriented", invalid_pages

    pdf_to_validate = _overlay_printable_areas_with_white(src_pdf)
    invalid_pages = list(_get_out_of_bounds_pages(pdf_to_validate))
    if len(invalid_pages) > 0:
        return 'content-outside-printable-area', invalid_pages

    invalid_pages = _get_pages_with_notify_tag(pdf_to_validate)
    if len(invalid_pages) > 0:
        # we really dont expect to see many of these so lets log
        current_app.logger.warning(f'notify tag found on pages {invalid_pages}')
        return 'notify-tag-found-in-content', invalid_pages

    return '', []


def _is_page_A4_portrait(page_height, page_width, rotation):
    if math.isclose(page_height, A4_HEIGHT, abs_tol=2) and math.isclose(page_width, 210, abs_tol=2):
        if rotation in [0, 180, None]:
            return True
    elif math.isclose(page_width, A4_HEIGHT, abs_tol=2) and math.isclose(page_height, 210, abs_tol=2):
        if rotation in [90, 270]:
            return True
    return False


def _get_pages_with_invalid_orientation_or_size(src_pdf):
    pdf = PdfFileReader(src_pdf)
    invalid_pages = []
    for page_num in range(0, pdf.numPages):
        page = pdf.getPage(page_num)

        page_height = float(page.mediaBox.getHeight()) / mm
        page_width = float(page.mediaBox.getWidth()) / mm
        rotation = page.get('/Rotate')

        if not _is_page_A4_portrait(page_height, page_width, rotation):
            invalid_pages.append(page_num + 1)
            current_app.logger.warning(
                "Letter is not A4 portrait size on page {}. Rotate: {}, height: {}mm, width: {}mm".format(
                    page_num + 1, rotation, int(page_height), int(page_width)
                )
            )
    return invalid_pages


def _overlay_printable_areas_with_white(src_pdf):
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

    :param BytesIO src_pdf: A file-like
    :return BytesIO: New file like containing the overlaid pdf
    """

    pdf = PdfFileReader(src_pdf)
    page = pdf.getPage(0)
    can = NotifyCanvas(white)

    # Overlay the blanks where the service can print as per the template
    # The first page is more varied because of address blocks etc subsequent pages are more simple

    # Body
    pt1 = BORDER_LEFT_FROM_LEFT_OF_PAGE - 1, BODY_TOP_FROM_TOP_OF_PAGE - 1
    pt2 = BORDER_RIGHT_FROM_LEFT_OF_PAGE + 1, BORDER_BOTTOM_FROM_TOP_OF_PAGE + 1
    can.rect(pt1, pt2)

    # Service address block - the writeable area on the right hand side (up to the top right corner)
    pt1 = SERVICE_ADDRESS_LEFT_FROM_LEFT_OF_PAGE - 1, SERVICE_ADDRESS_TOP_FROM_TOP_OF_PAGE - 1
    pt2 = SERVICE_ADDRESS_RIGHT_FROM_LEFT_OF_PAGE + 1, SERVICE_ADDRESS_BOTTOM_FROM_TOP_OF_PAGE + 1
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
    new_pdf = PdfFileReader(can.get_bytes())

    page.mergePage(new_pdf.getPage(0))

    # For each subsequent page its just the body of text
    for page_num in range(1, pdf.numPages):
        page = pdf.getPage(page_num)

        can = NotifyCanvas(white)

        # Each page of content
        pt1 = BORDER_LEFT_FROM_LEFT_OF_PAGE - 1, BORDER_TOP_FROM_TOP_OF_PAGE - 1
        pt2 = BORDER_RIGHT_FROM_LEFT_OF_PAGE + 1, BORDER_BOTTOM_FROM_TOP_OF_PAGE + 1
        can.rect(pt1, pt2)

        # move to the beginning of the StringIO buffer
        new_pdf = PdfFileReader(can.get_bytes())

        page.mergePage(new_pdf.getPage(0))

    out = bytesio_from_pdf(pdf)
    # it's a good habit to put things back exactly the way we found them
    src_pdf.seek(0)

    return out


def _colour_no_print_areas_of_single_page_pdf_in_red(src_pdf, is_first_page):
    """
    Overlays the non-printable areas onto the src PDF, this is so users know which parts of they letter fail validation.
    This function expects that src_pdf only represents a single page. It adds red areas (if `is_first_page` is set, then
    it'll add red areas around the address window too) and returns a single page pdf.

    :param BytesIO src_pdf: A file-like representing a single page pdf
    :param bool is_first_page: true if we should overlay the address block red area too.
    """
    pdf = PdfFileReader(src_pdf)

    if pdf.numPages != 1:
        # this function is used to render images, which call template-preview separately for each page. This function
        # should be colouring a single page pdf (which might be any individual page of an original precompiled letter)
        raise InvalidRequest('_colour_no_print_areas_of_page_in_red should only be called for a one-page-pdf')

    page = pdf.getPage(0)
    _colour_no_print_areas_of_page_in_red(page, is_first_page)

    out = bytesio_from_pdf(pdf)
    # it's a good habit to put things back exactly the way we found them
    src_pdf.seek(0)
    return out


def _colour_no_print_areas_of_page_in_red(page, is_first_page):
    """
    Overlays the non-printable areas onto a single page. It adds red areas (if `is_first_page` is set, then it'll add
    red areas around the address window too) and returns a new page object that you can then merge .

    :param PageObject page: A page, as returned by PdfFileReader.getPage. Note: This is modified by this function.
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
    new_pdf = PdfFileReader(can.get_bytes())

    # note that the original page object is modified. I don't know if the original underlying src_pdf buffer is affected
    # but i assume not.
    page.mergePage(new_pdf.getPage(0))


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
        colours = image.convert('RGB').getcolors()

        if colours is None:
            current_app.logger.warning('Letter has literally zero colours of any description on page {}???'.format(i))
            yield i
            continue

        for colour in colours:
            if str(colour[1]) != "(255, 255, 255)":
                current_app.logger.warning('Letter exceeds boundaries on page {}'.format(i))
                yield i
                break


def escape_special_characters_for_regex(string):
    # those characters perform functions in regex expressions and have to be escaped. Double backslash has to be checked
    # for first before other special characters, because we add backslashes in front of special characters.
    special_characters = ["\\", "[", "{", "^", "$", ".", "|", "?", "*", "+", "(", ")"]
    for character in special_characters:
        string = string.replace(character, r"\{}".format(character))

    return string


def handle_irregular_whitespace_characters(string):
    handle_irregular_newlines = string.replace("\n", r"\s*")
    also_handle_irregular_spacing = handle_irregular_newlines.replace(" ", r"\s*")
    return also_handle_irregular_spacing


def rewrite_address_block(pdf, *, page_count, allow_international_letters):
    address = extract_address_block(pdf)
    address.allow_international_letters = allow_international_letters

    if address.error_code:
        raise ValidationFailed(address.error_code, [1], page_count=page_count)

    try:
        pdf = redact_precompiled_letter_address_block(pdf, address.as_regex)
        pdf = add_address_to_precompiled_letter(pdf, address.normalised)
        return pdf, address.normalised, None
    except pdf_redactor.RedactionException as e:
        current_app.logger.warning(f'Could not redact address block for letter: "{e}" ')
        pdf.seek(0)
        return pdf, address.raw_address, str(e)


def _extract_text_from_first_page_of_pdf(pdf, *, x1, y1, x2, y2):
    """
    Extracts all text within a block on the first page

    :param BytesIO pdf: pdf bytestream from which to extract
    :param x1: horizontal location parameter for top left corner of rectangle in mm
    :param y1: vertical location parameter for top left corner of rectangle in mm
    :param x2: horizontal location parameter for bottom right corner of rectangle in mm
    :param y2: vertical location parameter for bottom right corner of rectangle in mm
    :return: Any text found
    """
    pdf.seek(0)
    doc = fitz.open("pdf", pdf)
    page = doc[0]
    ret = _extract_text_from_page(page, x1=x1, y1=y1, x2=x2, y2=y2)
    pdf.seek(0)
    return ret


def _extract_text_from_page(page, *, x1, y1, x2, y2):
    """
    Extracts all text within a block.
    Taken from this script: https://github.com/pymupdf/PyMuPDF-Utilities/blob/master/textboxtract.py
    Which was referenced in the library docs here:
    https://pymupdf.readthedocs.io/en/latest/faq/#how-to-extract-text-from-within-a-rectangle

    words and mywords variables are lists of tuples. Each tuple represents one word from the document,
    and is structured as follows:
    (x1, y1, x2, y2, word value, paragraph number, line number, word position within the line)

    :param fitz.Page page: fitz page object from which to extract
    :param x1: horizontal location parameter for top left corner of rectangle in mm
    :param y1: vertical location parameter for top left corner of rectangle in mm
    :param x2: horizontal location parameter for bottom right corner of rectangle in mm
    :param y2: vertical location parameter for bottom right corner of rectangle in mm
    :return: Any text found
    """
    rect = fitz.Rect(x1, y1, x2, y2)
    words = page.get_text_words()
    mywords = [w for w in words if fitz.Rect(w[:4]).intersects(rect)]
    mywords.sort(key=itemgetter(-3, -2, -1))
    group = groupby(mywords, key=itemgetter(3))
    extracted_text = []
    for _y1, gwords in group:
        extracted_text.append(" ".join(w[4] for w in gwords))
    return "\n".join(extracted_text)


def extract_address_block(pdf):
    """
    Extracts all text within the text block
    :param BytesIO pdf: pdf bytestream from which to extract
    :return: multi-line address string
    """
    # add on a margin to ensure we capture all text
    x1 = ADDRESS_LEFT_FROM_LEFT_OF_PAGE - 3
    y1 = ADDRESS_TOP_FROM_TOP_OF_PAGE - 3
    x2 = ADDRESS_RIGHT_FROM_LEFT_OF_PAGE + 3
    y2 = ADDRESS_BOTTOM_FROM_TOP_OF_PAGE + 3
    return PrecompiledPostalAddress(_extract_text_from_first_page_of_pdf(
        pdf,
        x1=x1 * mm, y1=y1 * mm,
        x2=x2 * mm, y2=y2 * mm
    ))


def _get_notify_tag_bounding_box():
    """
    Return x1, y1, x2, y2 in mm for the boundary of the NOTIFY tag in the top left, plus a healthy margin to help read
    """
    font = ImageFont.truetype(TRUE_TYPE_FONT_FILE, NOTIFY_TAG_FONT_SIZE)
    line_width, line_height = font.getsize('NOTIFY')

    # add on a fairly chunky margin to be generous to rounding errors
    x1 = NOTIFY_TAG_FROM_LEFT_OF_PAGE - 5
    y1 = NOTIFY_TAG_FROM_TOP_OF_PAGE - 3
    # font.getsize returns values in points, we need to get back into mm
    x2 = NOTIFY_TAG_FROM_LEFT_OF_PAGE + (line_width / mm) + 5
    y2 = NOTIFY_TAG_FROM_TOP_OF_PAGE + (line_height / mm) + 3
    return x1, y1, x2, y2


def is_notify_tag_present(pdf):
    """
    pdf is a file-like object containing at least the first page of a PDF
    """
    x1, y1, x2, y2 = _get_notify_tag_bounding_box()

    return _extract_text_from_first_page_of_pdf(
        pdf,
        x1=x1 * mm,
        y1=y1 * mm,
        x2=x2 * mm,
        y2=y2 * mm
    ) == 'NOTIFY'


def _get_pages_with_notify_tag(src_pdf_bytes):
    """
    Looks at all pages except for page 1, and returns any pages that have the NOTIFY tag in the top left. DVLA can't
    process letters with NOTIFY tags on later pages because their software thinks it's a marker signifying when a new
    letter starts. We've seen services attach pages from previous letters sent via notify
    """
    src_pdf_bytes.seek(0)
    doc = fitz.open("pdf", src_pdf_bytes)
    if doc.pageCount == 1:
        # if no extra pages we dont need to do anything
        src_pdf_bytes.seek(0)
        return []
    x1, y1, x2, y2 = _get_notify_tag_bounding_box()

    invalid_pages = [
        page.number + 1  # return 1 indexed pages
        for page in doc.pages(start=1)
        if _extract_text_from_page(
            page,
            x1=x1 * mm, y1=y1 * mm,
            x2=x2 * mm, y2=y2 * mm
        ) == 'NOTIFY'
    ]

    src_pdf_bytes.seek(0)
    return invalid_pages


def redact_precompiled_letter_address_block(pdf, address_regex):
    options = pdf_redactor.RedactorOptions()

    options.content_filters = []
    options.content_filters.append((
        re.compile(address_regex),
        lambda m: " "
    ))
    options.input_stream = get_first_page_of_pdf(pdf)
    options.output_stream = BytesIO()

    pdf_redactor.redactor(options)

    options.output_stream.seek(0)

    return replace_first_page_of_pdf_with_new_content(pdf, options.output_stream)


def add_address_to_precompiled_letter(pdf, address):
    """
    Given a pdf, blanks out any existing address (adds a white rectangle over existing address),
    and then puts the supplied address in over it.

    :param BytestIO pdf: pdf bytestream from which to extract
    :return: BytesIO new pdf
    """
    old_pdf = PdfFileReader(pdf)

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
    address_lines_after_first = address.count('\n')
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

    :param PdfFileReader old_pdf_reader: a rich pdf object that we want to add content to the first page of
    :param BytesIO new_page_buffer: BytesIO containing the raw bytes for the new content
    """
    # move to the beginning of the buffer and replay it into a pdf writer
    new_page_buffer.seek(0)
    new_pdf = PdfFileReader(new_page_buffer)
    new_page = new_pdf.getPage(0)
    existing_page = old_pdf_reader.getPage(0)
    # combines the two pages - overlaying, not overwriting.
    existing_page.mergePage(new_page)

    return bytesio_from_pdf(old_pdf_reader)


def replace_first_page_of_pdf_with_new_content(old_pdf_buffer, new_page_buffer):
    """
    Removeso old PDF's page 1, and replaces that with new_page_buffer.

    :param BytesIO old_pdf_buffer: BytesIO containing raw bytes of pdf that we want to discard the first page from
    :param BytesIO new_page_buffer: BytesIO containing the raw bytes for a new page
    """
    old_pdf_reader = PdfFileReader(old_pdf_buffer)
    new_first_page = PdfFileReader(new_page_buffer)

    new_pdf_writer = PdfFileWriter()
    new_pdf_writer.addPage(new_first_page.getPage(0))
    for i in range(1, old_pdf_reader.numPages):
        # page index 1, up to the end of the old pdf.
        new_pdf_writer.addPage(old_pdf_reader.getPage(i))

    pdf_bytes = BytesIO()
    new_pdf_writer.write(pdf_bytes)
    pdf_bytes.seek(0)
    return pdf_bytes


def bytesio_from_pdf(pdf):
    """
    :param PdfFileReader pdf: A rich pdf object
    :returns BytesIO: The raw bytes behind that PDF
    """
    output = PdfFileWriter()
    output.appendPagesFromReader(pdf)

    pdf_bytes = BytesIO()
    output.write(pdf_bytes)
    pdf_bytes.seek(0)
    return pdf_bytes


def get_first_page_of_pdf(pdf_buffer):
    """
    :param BytesIO pdf_buffer: bytes of a pdf to extract first page from
    :return BytesIO: returns bytes of just the first page on its own
    """
    original_pdf = PdfFileReader(pdf_buffer)
    first_page = original_pdf.getPage(0)
    first_page_as_pdf = PdfFileWriter()
    first_page_as_pdf.addPage(first_page)
    first_page = BytesIO()
    first_page_as_pdf.write(first_page)
    first_page.seek(0)
    # put things back how we found them
    pdf_buffer.seek(0)
    return first_page
