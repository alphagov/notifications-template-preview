import base64
import io
from io import BytesIO

import PyPDF2
from PyPDF2 import PdfFileWriter, PdfFileReader
from flask import request, abort, send_file, Blueprint, json
from notifications_utils.statsd_decorators import statsd
from pdf2image import convert_from_bytes
from reportlab.lib.colors import white, Color
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app import auth
from app.preview import png_from_pdf

MM_FROM_TOP_OF_PAGE = 4.3
MM_FROM_LEFT_OF_PAGE = 7.4
FONT_SIZE = 6
FONT = "Arial"
TRUE_TYPE_FONT_FILE = FONT + ".ttf"
TAG_TEXT = "NOTIFY"
LINE_SPACING = 1.75

BORDER_FROM_BOTTOM_OF_PAGE = 5.0
BORDER_FROM_TOP_OF_PAGE = 5.0
BORDER_FROM_LEFT_OF_PAGE = 15.0
BORDER_FROM_RIGHT_OF_PAGE = 15.0
BODY_TOP_FROM_TOP_OF_PAGE = 95.00

SERVICE_ADDRESS_FROM_LEFT_OF_PAGE = 120.0
SERVICE_ADDRESS_BOTTOM_FROM_TOP_OF_PAGE = 95.00

ADDRESS_BOTTOM_FROM_LEFT_OF_PAGE = 24.60
ADDRESS_BOTTOM_FROM_TOP_OF_PAGE = 66.30
ADDRESS_TOP_FROM_TOP_OF_PAGE = 39.50

LOGO_BOTTOM_FROM_LEFT_OF_PAGE = 15.00
LOGO_BOTTOM_FROM_TOP_OF_PAGE = 30.00
LOGO_TOP_FROM_TOP_OF_PAGE = 5.00

precompiled_blueprint = Blueprint('precompiled_blueprint', __name__)


@precompiled_blueprint.route("/precompiled/add_tag", methods=['POST'])
@auth.login_required
@statsd(namespace="template_preview")
def add_tag_to_precompiled_letter():
    encoded_string = request.get_data()

    if not encoded_string:
        abort(400)

    file_data = base64.decodebytes(encoded_string)

    return send_file(filename_or_fp=add_notify_tag_to_letter(BytesIO(file_data)), mimetype='application/pdf')


@precompiled_blueprint.route("/precompiled/validate", methods=['POST'])
@auth.login_required
@statsd(namespace="template_preview")
def validate_pdf_document():
    encoded_string = request.get_data()

    if not encoded_string:
        abort(400)

    file_data = base64.decodebytes(encoded_string)

    data = json.dumps({
        'result': validate_document(BytesIO(file_data)),
    })

    return data


@precompiled_blueprint.route("/precompiled/overlay.png", methods=['POST'])
@auth.login_required
@statsd(namespace="template_preview")
def overlay_template():
    encoded_string = request.get_data()

    if not encoded_string:
        abort(400)

    file_data = base64.decodebytes(encoded_string)

    validate = request.args.get('validate') in ['false', '0']

    return send_file(
        filename_or_fp=overlay_template_areas(
            BytesIO(file_data),
            int(request.args.get('page', 1)),
            not validate
        ),
        mimetype='image/png',
    )


def add_notify_tag_to_letter(src_pdf):
    """
    Adds the word 'NOTIFY' to the first page of the PDF

    :param PyPDF2.PdfFileReader src_pdf: A File object or an object that supports the standard read and seek methods
    """

    pdf = PyPDF2.PdfFileReader(src_pdf)
    output = PdfFileWriter()
    page = pdf.getPage(0)
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    pdfmetrics.registerFont(TTFont(FONT, TRUE_TYPE_FONT_FILE))
    can.setFillColorRGB(255, 255, 255)  # white
    can.setFont(FONT, FONT_SIZE)

    from PIL import ImageFont
    font = ImageFont.truetype(TRUE_TYPE_FONT_FILE, FONT_SIZE)
    size = font.getsize('NOTIFY')

    x = MM_FROM_LEFT_OF_PAGE * mm

    # page.mediaBox[3] Media box is an array with the four corners of the page
    # We want height so can use that co-ordinate which is located in [3]
    # The lets take away the margin and the ont size
    # 1.75 for the line spacing
    y = float(page.mediaBox[3]) - (float(MM_FROM_TOP_OF_PAGE * mm + size[1] - LINE_SPACING))

    can.drawString(x, y, TAG_TEXT)
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

    pdf_bytes = io.BytesIO()
    output.write(pdf_bytes)
    pdf_bytes.seek(0)

    return pdf_bytes


def overlay_template_areas(src_pdf, page_number, overlay=True):
    pdf = _add_no_print_areas(src_pdf, overlay=overlay)
    return png_from_pdf(pdf, page_number)


def validate_document(src_pdf):
    pdf_to_validate = _add_no_print_areas(src_pdf)
    return _validate_pdf(PdfFileReader(pdf_to_validate))


def _add_no_print_areas(src_pdf, overlay=False):
    """
    Overlays the printable areas onto the src PDF, this is so the code can check for a presence of non white in the
    areas outside the printable area.

    :param PyPDF2.PdfFileReader src_pdf: A File object or an object that supports the standard read and seek methods
    :param bool overlay: overlay the template as a red opaque block otherwise just block white
    """
    pdf = PyPDF2.PdfFileReader(src_pdf)
    output = PdfFileWriter()
    page = pdf.getPage(0)
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)

    red_transparent = Color(100, 0, 0, alpha=0.2)
    can.setStrokeColor(white)
    can.setFillColor(white)

    if overlay:
        can.setStrokeColor(red_transparent)
        can.setFillColor(red_transparent)
        width = float(page.mediaBox[2]) - ((BORDER_FROM_LEFT_OF_PAGE + BORDER_FROM_RIGHT_OF_PAGE) * mm)
    else:
        width = float(page.mediaBox[2]) - (BORDER_FROM_LEFT_OF_PAGE * mm)

    # Overlay the blanks where the service can print as per the template
    # The first page is more varied because of address blocks etc subsequent pages are more simple

    # Body
    x = BORDER_FROM_LEFT_OF_PAGE * mm
    y = BORDER_FROM_BOTTOM_OF_PAGE * mm

    height = float(page.mediaBox[3]) - ((BODY_TOP_FROM_TOP_OF_PAGE + BORDER_FROM_BOTTOM_OF_PAGE) * mm)
    can.rect(x, y, width, height, fill=True, stroke=False)

    # Service address block
    x = SERVICE_ADDRESS_FROM_LEFT_OF_PAGE * mm
    y = float(page.mediaBox[3]) - (SERVICE_ADDRESS_BOTTOM_FROM_TOP_OF_PAGE * mm)
    if overlay:
        service_address_width = float(page.mediaBox[2]) - ((SERVICE_ADDRESS_FROM_LEFT_OF_PAGE +
                                                            BORDER_FROM_RIGHT_OF_PAGE) * mm)
    else:
        service_address_width = float(page.mediaBox[2]) - (SERVICE_ADDRESS_FROM_LEFT_OF_PAGE * mm)
    height = (SERVICE_ADDRESS_BOTTOM_FROM_TOP_OF_PAGE - BORDER_FROM_TOP_OF_PAGE) * mm
    can.rect(x, y, service_address_width, height, fill=True, stroke=False)

    # Service Logo Block
    x = LOGO_BOTTOM_FROM_LEFT_OF_PAGE * mm
    y = float(page.mediaBox[3]) - (LOGO_BOTTOM_FROM_TOP_OF_PAGE * mm)
    height = (LOGO_BOTTOM_FROM_TOP_OF_PAGE - LOGO_TOP_FROM_TOP_OF_PAGE) * mm
    can.rect(x, y, width, height, fill=True, stroke=False)

    # Citizen Address Block
    x = ADDRESS_BOTTOM_FROM_LEFT_OF_PAGE * mm
    y = float(page.mediaBox[3]) - (ADDRESS_BOTTOM_FROM_TOP_OF_PAGE * mm)

    if overlay:
        address_block_width = float(page.mediaBox[2]) - ((ADDRESS_BOTTOM_FROM_LEFT_OF_PAGE +
                                                          BORDER_FROM_RIGHT_OF_PAGE) * mm)
    else:
        address_block_width = float(page.mediaBox[2]) - (ADDRESS_BOTTOM_FROM_LEFT_OF_PAGE * mm)

    height = (ADDRESS_BOTTOM_FROM_TOP_OF_PAGE - ADDRESS_TOP_FROM_TOP_OF_PAGE) * mm
    can.rect(x, y, address_block_width, height, fill=True, stroke=False)

    can.save()

    # move to the beginning of the StringIO buffer
    packet.seek(0)
    new_pdf = PyPDF2.PdfFileReader(packet)

    page.mergePage(new_pdf.getPage(0))
    output.addPage(page)

    # For each subsequent page its just the body of text
    for page_num in range(1, pdf.numPages):
        page = pdf.getPage(page_num)
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=A4)
        can.setStrokeColor(white)
        can.setFillColor(white)

        if overlay:
            can.setStrokeColor(red_transparent)
            can.setFillColor(red_transparent)

        # Each page of content
        x = BORDER_FROM_LEFT_OF_PAGE * mm
        y = BORDER_FROM_BOTTOM_OF_PAGE * mm
        height = float(page.mediaBox[3]) - ((BORDER_FROM_TOP_OF_PAGE + BORDER_FROM_BOTTOM_OF_PAGE) * mm)
        can.rect(x, y, width, height, fill=True, stroke=False)
        can.save()

        # move to the beginning of the StringIO buffer
        packet.seek(0)
        new_pdf = PyPDF2.PdfFileReader(packet)

        page.mergePage(new_pdf.getPage(0))
        output.addPage(page)

    pdf_bytes = io.BytesIO()
    output.write(pdf_bytes)
    pdf_bytes.seek(0)

    return pdf_bytes


def _validate_pdf(src_pdf):
    """
    Checks each pixel of the image to determine the colour - if any pixel is not white return false
    :param PyPDF2.PdfFileReader src_pdf: PDF from which to take pages.
    :return: False if there is any colour but white, otherwise true
    """

    dst_pdf = PyPDF2.PdfFileWriter()

    pages = src_pdf.numPages

    for page_num in range(0, pages):
        dst_pdf.addPage(src_pdf.getPage(page_num))

    pdf_bytes = io.BytesIO()
    dst_pdf.write(pdf_bytes)
    pdf_bytes.seek(0)

    images = convert_from_bytes(pdf_bytes.read())

    for image in images:
        colours = image.convert('RGB').getcolors()

        if colours is None:
            return False

        for colour in colours:
            if str(colour[1]) != "(255, 255, 255)":
                return False

    return True
