import base64
import math
from io import BytesIO
import app.pdf_redactor as pdf_redactor
import re
import fitz

from operator import itemgetter
from itertools import groupby

from PIL import ImageFont
from PyPDF2 import PdfFileWriter, PdfFileReader
from flask import request, abort, send_file, Blueprint, jsonify, current_app
from notifications_utils.statsd_decorators import statsd
from pdf2image import convert_from_bytes
from reportlab.lib.colors import white, black, Color
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app import auth, InvalidRequest, ValidationFailed
from app.preview import png_from_pdf, pngs_from_pdf
from app.transformation import convert_pdf_to_cmyk, does_pdf_contain_cmyk, does_pdf_contain_rgb

from notifications_utils.pdf import is_letter_too_long, pdf_page_count


NOTIFY_TAG_FROM_TOP_OF_PAGE = 4.3
NOTIFY_TAG_FROM_LEFT_OF_PAGE = 7.4
NOTIFY_TAG_FONT_SIZE = 6
NOTIFY_TAG_TEXT = "NOTIFY"
NOTIFY_TAG_LINE_SPACING = 1.75
ADDRESS_FONT_SIZE = 8
ADDRESS_LINE_HEIGHT = ADDRESS_FONT_SIZE + 0.5
FONT = "Arial"
TRUE_TYPE_FONT_FILE = FONT + ".ttf"

BORDER_FROM_BOTTOM_OF_PAGE = 5.0
BORDER_FROM_TOP_OF_PAGE = 5.0
BORDER_FROM_LEFT_OF_PAGE = 15.0
BORDER_FROM_RIGHT_OF_PAGE = 15.0
BODY_TOP_FROM_TOP_OF_PAGE = 95.00

SERVICE_ADDRESS_LEFT_FROM_LEFT_OF_PAGE = 125.0
SERVICE_ADDRESS_BOTTOM_FROM_TOP_OF_PAGE = 95.00

ADDRESS_TOP_FROM_TOP_OF_PAGE = 39.50
ADDRESS_LEFT_FROM_LEFT_OF_PAGE = 24.60
ADDRESS_BOTTOM_FROM_TOP_OF_PAGE = 66.30
ADDRESS_RIGHT_FROM_LEFT_OF_PAGE = 120.0

ADDRESS_HEIGHT = ADDRESS_BOTTOM_FROM_TOP_OF_PAGE - ADDRESS_TOP_FROM_TOP_OF_PAGE
ADDRESS_WIDTH = ADDRESS_RIGHT_FROM_LEFT_OF_PAGE - ADDRESS_LEFT_FROM_LEFT_OF_PAGE

LOGO_LEFT_FROM_LEFT_OF_PAGE = 15.00
LOGO_RIGHT_FROM_LEFT_OF_PAGE = SERVICE_ADDRESS_LEFT_FROM_LEFT_OF_PAGE
LOGO_BOTTOM_FROM_TOP_OF_PAGE = 30.00
LOGO_TOP_FROM_TOP_OF_PAGE = 5.00

LOGO_HEIGHT = LOGO_BOTTOM_FROM_TOP_OF_PAGE - LOGO_TOP_FROM_TOP_OF_PAGE
LOGO_WIDTH = LOGO_RIGHT_FROM_LEFT_OF_PAGE - LOGO_LEFT_FROM_LEFT_OF_PAGE

A4_WIDTH = 210 * mm
A4_HEIGHT = 297 * mm

precompiled_blueprint = Blueprint('precompiled_blueprint', __name__)


@precompiled_blueprint.route('/precompiled/sanitise', methods=['POST'])
@auth.login_required
@statsd(namespace='template_preview')
def sanitise_precompiled_letter():
    encoded_string = request.get_data()

    if not encoded_string:
        raise InvalidRequest('no-encoded-string')

    sanitise_json = sanitise_file_contents(encoded_string)
    status_code = 400 if sanitise_json.get('message') else 200

    return jsonify(sanitise_json), status_code


def sanitise_file_contents(encoded_string):
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

        file_data, recipient_address, redaction_failed_message = rewrite_address_block(file_data)

        if not does_pdf_contain_cmyk(encoded_string) or does_pdf_contain_rgb(encoded_string):
            file_data = BytesIO(convert_pdf_to_cmyk(file_data.read()))

        # during switchover, DWP and CYSP will still be sending the notify tag. Only add it if it's not already there
        if not is_notify_tag_present(file_data):
            file_data = add_notify_tag_to_letter(file_data)

        return {
            "recipient_address": recipient_address,
            "page_count": page_count,
            "message": None,
            "invalid_pages": None,
            "redaction_failed_message": redaction_failed_message,
            "file": base64.b64encode(file_data.read()).decode('utf-8')
        }
    except Exception as error:
        if isinstance(error, ValidationFailed):
            current_app.logger.warning('Validation Failed for precompiled pdf: {}'.format(repr(error)))
        else:
            current_app.logger.exception('Unhandled exception with precompiled pdf: {}'.format(repr(error)))

        return {
            "page_count": getattr(error, 'page_count', None),
            "recipient_address": None,
            "message": getattr(error, 'message', 'unable-to-read-the-file'),
            "invalid_pages": getattr(error, 'invalid_pages', None),
            "file": None
        }


@precompiled_blueprint.route("/precompiled/add_tag", methods=['POST'])
@auth.login_required
@statsd(namespace="template_preview")
def add_tag_to_precompiled_letter():
    encoded_string = request.get_data()

    if not encoded_string:
        abort(400)

    file_data = BytesIO(encoded_string)

    return send_file(filename_or_fp=add_notify_tag_to_letter(file_data), mimetype='application/pdf')


# DEPRECATED
@precompiled_blueprint.route("/precompiled/validate", methods=['POST'])
@auth.login_required
@statsd(namespace="template_preview")
def validate_pdf_document():
    encoded_string = request.get_data()
    generate_preview_pngs = request.args.get('include_preview') in ['true', 'True', '1']

    if not encoded_string:
        abort(400)

    message, invalid_pages = get_invalid_pages_with_message(BytesIO(encoded_string))
    data = {
        'result': bool(not message)
    }

    if not generate_preview_pngs:
        return jsonify(data)

    if message:
        data['message'] = message
        data['invalid_pages'] = invalid_pages
        pages = overlay_template_areas(BytesIO(encoded_string), overlay=True)

    else:
        data['message'] = 'Your PDF passed the layout check'
        file_data, address, redaction_failed_message = rewrite_address_block(BytesIO(encoded_string))
        pages = pngs_from_pdf(file_data)

    data['pages'] = [
        base64.b64encode(page.read()).decode('ascii') for page in pages
    ]

    return jsonify(data)


@precompiled_blueprint.route("/precompiled/overlay.<file_type>", methods=['POST'])
@auth.login_required
@statsd(namespace="template_preview")
def overlay_template(file_type):
    encoded_string = request.get_data()

    if not encoded_string:
        abort(400)

    file_data = BytesIO(encoded_string)

    if file_type == 'png':
        return send_file(
            filename_or_fp=png_from_pdf(
                _colour_no_print_areas(file_data, page_number=int(request.args.get('page_number', 1))),
                int(request.args.get('page', 1))
            ),
            mimetype='image/png',
        )
    else:
        return send_file(
            filename_or_fp=_colour_no_print_areas(
                file_data,
            ),
            mimetype='application/pdf',
        )


def add_notify_tag_to_letter(src_pdf):
    """
    Adds the word 'NOTIFY' to the first page of the PDF

    :param PdfFileReader src_pdf: A File object or an object that supports the standard read and seek methods
    """

    pdf = PdfFileReader(src_pdf)
    output = PdfFileWriter()
    page = pdf.getPage(0)
    packet = BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    pdfmetrics.registerFont(TTFont(FONT, TRUE_TYPE_FONT_FILE))
    can.setFillColorRGB(255, 255, 255)  # white
    can.setFont(FONT, NOTIFY_TAG_FONT_SIZE)

    font = ImageFont.truetype(TRUE_TYPE_FONT_FILE, NOTIFY_TAG_FONT_SIZE)
    line_width, line_height = font.getsize('NOTIFY')

    center_of_left_margin = (BORDER_FROM_LEFT_OF_PAGE * mm) / 2
    half_width_of_notify_tag = line_width / 2
    x = center_of_left_margin - half_width_of_notify_tag

    # page.mediaBox[3] Media box is an array with the four corners of the page
    # We want height so can use that co-ordinate which is located in [3]
    # The lets take away the margin and the ont size
    # 1.75 for the line spacing
    y = float(page.mediaBox[3]) - (float(NOTIFY_TAG_FROM_TOP_OF_PAGE * mm + line_height - NOTIFY_TAG_LINE_SPACING))

    can.drawString(x, y, NOTIFY_TAG_TEXT)
    can.save()

    # move to the beginning of the StringIO buffer
    packet.seek(0)
    new_pdf = PdfFileReader(packet)

    new_page = new_pdf.getPage(0)
    new_page.mergePage(page)
    output.addPage(new_page)

    # add the rest of the document to the new doc. NOTIFY only appears on the first page
    for page_num in range(1, pdf.numPages):
        output.addPage(pdf.getPage(page_num))

    pdf_bytes = BytesIO()
    output.write(pdf_bytes)
    pdf_bytes.seek(0)

    return pdf_bytes


def overlay_template_areas(src_pdf, page_number=None, overlay=True):
    pdf = _overlay_printable_areas(src_pdf, overlay=overlay)
    if page_number is None:
        return pngs_from_pdf(pdf)
    return png_from_pdf(pdf, page_number)


def get_invalid_pages_with_message(src_pdf):
    message = ""
    invalid_pages = []
    invalid_pages = _get_pages_with_invalid_orientation_or_size(src_pdf)
    if len(invalid_pages) > 0:
        message = "letter-not-a4-portrait-oriented"
    else:
        pdf_to_validate = _overlay_printable_areas(src_pdf)
        invalid_pages = list(_get_out_of_bounds_pages(PdfFileReader(pdf_to_validate)))
        if len(invalid_pages) > 0:
            message = 'content-outside-printable-area'

    return message, invalid_pages


def _is_page_A4_portrait(page_height, page_width, rotation):
    if math.isclose(page_height, 297, abs_tol=2) and math.isclose(page_width, 210, abs_tol=2):
        if rotation in [0, 180, None]:
            return True
    elif math.isclose(page_width, 297, abs_tol=2) and math.isclose(page_height, 210, abs_tol=2):
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


def _overlay_printable_areas(src_pdf, overlay=False):
    """
    Overlays the printable areas onto the src PDF, this is so the code can check for a presence of non white in the
    areas outside the printable area.

    :param BytesIO src_pdf: A file-like
    :param bool overlay: overlay the template as a red opaque block otherwise just block white
    """

    pdf = PdfFileReader(src_pdf)
    output = PdfFileWriter()
    page = pdf.getPage(0)
    packet = BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)

    page_height = float(page.mediaBox.getHeight())
    page_width = float(page.mediaBox.getWidth())

    red_transparent = Color(100, 0, 0, alpha=0.2)

    colour = red_transparent if overlay else white

    can.setStrokeColor(colour)
    can.setFillColor(colour)

    width = page_width - (BORDER_FROM_LEFT_OF_PAGE * mm + BORDER_FROM_RIGHT_OF_PAGE * mm)

    # Overlay the blanks where the service can print as per the template
    # The first page is more varied because of address blocks etc subsequent pages are more simple

    # Body
    x = BORDER_FROM_LEFT_OF_PAGE * mm
    y = BORDER_FROM_BOTTOM_OF_PAGE * mm

    height = page_height - ((BODY_TOP_FROM_TOP_OF_PAGE + BORDER_FROM_BOTTOM_OF_PAGE) * mm)
    can.rect(x, y, width, height, fill=True, stroke=False)

    # Service address block
    x = SERVICE_ADDRESS_LEFT_FROM_LEFT_OF_PAGE * mm
    y = page_height - (SERVICE_ADDRESS_BOTTOM_FROM_TOP_OF_PAGE * mm)

    service_address_width = page_width - (SERVICE_ADDRESS_LEFT_FROM_LEFT_OF_PAGE * mm + BORDER_FROM_RIGHT_OF_PAGE * mm)

    height = (SERVICE_ADDRESS_BOTTOM_FROM_TOP_OF_PAGE - BORDER_FROM_TOP_OF_PAGE) * mm
    can.rect(x, y, service_address_width, height, fill=True, stroke=False)

    # Service Logo Block
    x = LOGO_LEFT_FROM_LEFT_OF_PAGE * mm
    y = page_height - (LOGO_BOTTOM_FROM_TOP_OF_PAGE * mm)

    can.rect(x, y, LOGO_WIDTH * mm, LOGO_HEIGHT * mm, fill=True, stroke=False)

    # Citizen Address Block
    x = ADDRESS_LEFT_FROM_LEFT_OF_PAGE * mm
    y = page_height - (ADDRESS_BOTTOM_FROM_TOP_OF_PAGE * mm)

    address_block_width = ADDRESS_WIDTH * mm

    height = (ADDRESS_BOTTOM_FROM_TOP_OF_PAGE - ADDRESS_TOP_FROM_TOP_OF_PAGE) * mm
    can.rect(x, y, address_block_width, height, fill=True, stroke=False)

    can.save()

    # move to the beginning of the StringIO buffer
    packet.seek(0)
    new_pdf = PdfFileReader(packet)

    page.mergePage(new_pdf.getPage(0))
    output.addPage(page)

    # For each subsequent page its just the body of text
    for page_num in range(1, pdf.numPages):
        page = pdf.getPage(page_num)

        page_height = float(page.mediaBox.getHeight())
        page_width = float(page.mediaBox.getWidth())

        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=A4)

        can.setStrokeColor(colour)
        can.setFillColor(colour)

        # Each page of content
        x = BORDER_FROM_LEFT_OF_PAGE * mm
        y = BORDER_FROM_BOTTOM_OF_PAGE * mm
        height = page_height - ((BORDER_FROM_TOP_OF_PAGE + BORDER_FROM_BOTTOM_OF_PAGE) * mm)
        width = page_width - (BORDER_FROM_LEFT_OF_PAGE * mm + BORDER_FROM_RIGHT_OF_PAGE * mm)
        can.rect(x, y, width, height, fill=True, stroke=False)
        can.save()

        # move to the beginning of the StringIO buffer
        packet.seek(0)
        new_pdf = PdfFileReader(packet)

        page.mergePage(new_pdf.getPage(0))
        output.addPage(page)

    pdf_bytes = BytesIO()
    output.write(pdf_bytes)
    pdf_bytes.seek(0)

    # it's a good habit to put things back exactly the way we found them
    src_pdf.seek(0)

    return pdf_bytes


def _colour_no_print_areas(src_pdf, page_number=1):
    """
    Overlays the non-printable areas onto the src PDF, this is so users know which parts of they letter fail validation.

    :param BytesIO src_pdf: A file-like
    """
    pdf = PdfFileReader(src_pdf)
    output = PdfFileWriter()

    page = pdf.getPage(0)
    packet = BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)

    page_height = float(page.mediaBox.getHeight())
    page_width = float(page.mediaBox.getWidth())

    colour = Color(100, 0, 0, alpha=0.2)  # red transparent
    can.setStrokeColor(colour)
    can.setFillColor(colour)

    # Overlay the areas where the service can't print as per the template
    # The first page is more varied because of address blocks etc subsequent pages are more simple

    # Margins
    left = BORDER_FROM_LEFT_OF_PAGE * mm
    bottom = BORDER_FROM_BOTTOM_OF_PAGE * mm
    right = BORDER_FROM_RIGHT_OF_PAGE * mm
    top = BORDER_FROM_TOP_OF_PAGE * mm
    # left margin:
    can.rect(0, 0, left, page_height, fill=True, stroke=False)
    # top margin:
    can.rect(left, page_height - top, page_width - (2 * right), page_height, fill=True, stroke=False)
    # right margin:
    can.rect(page_width - right, 0, page_width, page_height, fill=True, stroke=False)
    # bottom margin:
    can.rect(left, 0, page_width - (2 * right), bottom, fill=True, stroke=False)

    if page_number == 1:
        # Body
        body_top = BODY_TOP_FROM_TOP_OF_PAGE * mm
        # Service address
        service_left = SERVICE_ADDRESS_LEFT_FROM_LEFT_OF_PAGE * mm
        # Citizen's address
        address_bottom = ADDRESS_BOTTOM_FROM_TOP_OF_PAGE * mm
        address_top = ADDRESS_TOP_FROM_TOP_OF_PAGE * mm
        address_left = ADDRESS_LEFT_FROM_LEFT_OF_PAGE * mm
        address_right = ADDRESS_RIGHT_FROM_LEFT_OF_PAGE * mm
        # Logo
        logo_bottom = LOGO_BOTTOM_FROM_TOP_OF_PAGE * mm

        # left from address block
        can.rect(
            left, page_height - address_bottom, address_left - left,
            address_bottom - address_top, fill=True, stroke=False
        )
        # above address block
        can.rect(
            left, page_height - address_top, service_left - left, address_top - logo_bottom, fill=True, stroke=False
        )
        # right from address block
        can.rect(
            address_right, page_height - address_bottom, service_left - address_right, address_bottom - address_top,
            fill=True, stroke=False
        )
        # below address block
        can.rect(left, page_height - body_top, service_left - left, body_top - address_bottom, fill=True, stroke=False)
    can.save()

    # move to the beginning of the StringIO buffer
    packet.seek(0)
    new_pdf = PdfFileReader(packet)

    page.mergePage(new_pdf.getPage(0))
    output.addPage(page)
    # For each subsequent page its just the body of text
    for page_num in range(1, pdf.numPages):
        page = pdf.getPage(page_num)

        page_height = float(page.mediaBox.getHeight())
        page_width = float(page.mediaBox.getWidth())

        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=A4)

        can.setStrokeColor(colour)
        can.setFillColor(colour)

        # Each page of content
        # left margin:
        can.rect(0, 0, left, page_height, fill=True, stroke=False)
        # top margin:
        can.rect(left, page_height - top, page_width - (2 * right), page_height, fill=True, stroke=False)
        # right margin:
        can.rect(page_width - right, 0, page_width, page_height, fill=True, stroke=False)
        # bottom margin:
        can.rect(left, 0, page_width - (2 * right), bottom, fill=True, stroke=False)
        can.save()

        # move to the beginning of the StringIO buffer
        packet.seek(0)
        new_pdf = PdfFileReader(packet)

        page.mergePage(new_pdf.getPage(0))
        output.addPage(page)

    pdf_bytes = BytesIO()
    output.write(pdf_bytes)
    pdf_bytes.seek(0)

    # it's a good habit to put things back exactly the way we found them
    src_pdf.seek(0)
    return pdf_bytes


def _get_out_of_bounds_pages(src_pdf):
    """
    Checks each pixel of the image to determine the colour - if any pixel is not white return false
    :param PdfFileReader src_pdf: PDF from which to take pages.
    :return: iterable containing page numbers (1-indexed)
    :return: False if there is any colour but white, otherwise true
    """

    dst_pdf = PdfFileWriter()

    pages = src_pdf.numPages

    for page_num in range(0, pages):
        dst_pdf.addPage(src_pdf.getPage(page_num))

    pdf_bytes = BytesIO()
    dst_pdf.write(pdf_bytes)
    pdf_bytes.seek(0)

    images = convert_from_bytes(pdf_bytes.read())

    for i, image in enumerate(images, start=1):
        colours = image.convert('RGB').getcolors()

        if colours is None:
            current_app.logger.error('Letter has literally zero colours of any description on page {}???'.format(i))
            yield i
            continue

        for colour in colours:
            if str(colour[1]) != "(255, 255, 255)":
                current_app.logger.warning('Letter exceeds boundaries on page {}'.format(i))
                yield i
                break


def escape_special_characters_for_regex(string):
    special_characters = ["[", "^", "$", ".", "|", "?", "*", "+", "(", ")"]
    for character in special_characters:
        string = string.replace(character, r"\{}".format(character))
    return string


def handle_irregular_whitespace_characters(string):
    handle_irregular_newlines = string.replace("\n", r"\s*")
    also_handle_irregular_spacing = handle_irregular_newlines.replace(" ", r"\s*")
    return also_handle_irregular_spacing


def turn_extracted_address_into_a_flexible_regex(string):
    string = escape_special_characters_for_regex(string)
    return handle_irregular_whitespace_characters(string)


def rewrite_address_block(pdf):
    address = extract_address_block(pdf)
    address_regex = turn_extracted_address_into_a_flexible_regex(address)

    pdf, message = redact_precompiled_letter_address_block(pdf, address_regex)
    pdf = BytesIO(pdf)
    pdf = add_address_to_precompiled_letter(pdf, address)

    return pdf, address, message


def _extract_text_from_pdf(pdf, *, x1, y1, x2, y2):
    """
    Extracts all text within a block.
    Taken from this script: https://github.com/pymupdf/PyMuPDF-Utilities/blob/master/textboxtract.py
    Which was referenced in the library docs here:
    https://pymupdf.readthedocs.io/en/latest/faq/#how-to-extract-text-from-within-a-rectangle

    words and mywords variables are lists of tuples. Each tuple represents one word from the document,
    and is structured as follows:
    (x1, y1, x2, y2, word value, paragraph number, line number, word position within the line)

    :param BytesIO pdf: pdf bytestream from which to extract
    :param x1: horizontal location parameter for top left corner of rectangle in mm
    :param y1: vertical location parameter for top left corner of rectangle in mm
    :param x2: horizontal location parameter for bottom right corner of rectangle in mm
    :param y2: vertical location parameter for bottom right corner of rectangle in mm
    :return: multi-line address string
    """
    pdf.seek(0)
    doc = fitz.open("pdf", pdf)
    page = doc[0]
    rect = fitz.Rect(x1, y1, x2, y2)
    words = page.getTextWords()
    mywords = [w for w in words if fitz.Rect(w[:4]).intersects(rect)]
    mywords.sort(key=itemgetter(-3, -2, -1))
    group = groupby(mywords, key=itemgetter(3))
    extracted_text = []
    for y1, gwords in group:
        extracted_text.append(" ".join(w[4] for w in gwords))
    pdf.seek(0)
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
    return _extract_text_from_pdf(
        pdf,
        x1=x1 * mm, y1=y1 * mm,
        x2=x2 * mm, y2=y2 * mm
    )


def is_notify_tag_present(pdf):
    """
    pdf is a file-like object containing at least the first page of a PDF
    """
    font = ImageFont.truetype(TRUE_TYPE_FONT_FILE, NOTIFY_TAG_FONT_SIZE)
    line_width, line_height = font.getsize('NOTIFY')

    # add on a fairly chunky margin to be generous to rounding errors
    x1 = NOTIFY_TAG_FROM_LEFT_OF_PAGE - 5
    y1 = NOTIFY_TAG_FROM_TOP_OF_PAGE - 3
    # font.getsize returns values in points, we need to get back into mm
    x2 = NOTIFY_TAG_FROM_LEFT_OF_PAGE + (line_width / mm) + 5
    y2 = NOTIFY_TAG_FROM_TOP_OF_PAGE + (line_height / mm) + 3

    return _extract_text_from_pdf(
        pdf,
        x1=x1 * mm,
        y1=y1 * mm,
        x2=x2 * mm,
        y2=y2 * mm
    ) == 'NOTIFY'


def redact_precompiled_letter_address_block(pdf, address_regex):
    options = pdf_redactor.RedactorOptions()

    options.content_filters = []
    options.content_filters.append((
        re.compile(address_regex),
        lambda m: " "
    ))
    options.input_stream = pdf
    options.output_stream = BytesIO()

    message = pdf_redactor.redactor(options)

    options.output_stream.seek(0)
    return options.output_stream.read(), message


def add_address_to_precompiled_letter(pdf, address):
    """
    Given a pdf, blanks out any existing address (adds a white rectangle over existing address),
    and then puts the supplied address in over it.

    :param BytestIO pdf: pdf bytestream from which to extract
    :return: BytesIO new pdf
    """
    new_page_buffer = BytesIO()
    old_pdf = PdfFileReader(pdf)

    can = canvas.Canvas(new_page_buffer, pagesize=A4)

    # x, y coordinates are from bottom left of page
    bottom_left_corner_x = ADDRESS_LEFT_FROM_LEFT_OF_PAGE * mm
    bottom_left_corner_y = A4_HEIGHT - (ADDRESS_BOTTOM_FROM_TOP_OF_PAGE * mm)

    # Cover the existing address block with a white rectangle
    can.setFillColor(white)
    can.rect(
        x=bottom_left_corner_x,
        y=bottom_left_corner_y,
        width=ADDRESS_WIDTH * mm,
        height=ADDRESS_HEIGHT * mm,
        fill=True,
        stroke=False
    )

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

    can.save()

    return replace_first_page_of_pdf(old_pdf, new_page_buffer)


def replace_first_page_of_pdf(old_pdf, new_page_buffer):
    # move to the beginning of the buffer and replay it into a pdf writer
    new_page_buffer.seek(0)
    new_pdf = PdfFileReader(new_page_buffer)
    output = PdfFileWriter()
    new_page = new_pdf.getPage(0)
    existing_page = old_pdf.getPage(0)

    existing_page.mergePage(new_page)
    output.addPage(existing_page)

    # add the rest of the document to the new doc, we only change the address on the first page
    for page_num in range(1, old_pdf.numPages):
        output.addPage(old_pdf.getPage(page_num))

    new_pdf_buffer = BytesIO()
    output.write(new_pdf_buffer)
    new_pdf_buffer.seek(0)

    return new_pdf_buffer
