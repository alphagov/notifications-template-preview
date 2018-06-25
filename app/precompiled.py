import base64
import io
from io import BytesIO

import PyPDF2
import binascii
from PyPDF2 import PdfFileWriter, PdfFileReader
from PyPDF2.utils import PdfReadError
from flask import request, abort, send_file, current_app, Blueprint, json
from notifications_utils.statsd_decorators import statsd
from pdf2image import convert_from_bytes
from reportlab.lib.colors import white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app import auth

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
    try:
        encoded_string = request.get_data()

        if not encoded_string:
            abort(400)

        file_data = base64.decodebytes(encoded_string)

        data = json.dumps({
            'result': validate_document(BytesIO(file_data)),
        })

        return data

    # catch malformed base64
    except binascii.Error as e:
        current_app.logger.warn("Unable to decode the PDF data", str(e))
        abort(400)

    # catch invalid pdfs
    except PdfReadError as e:
        current_app.logger.warn("Failed to read PDF", str(e))
        abort(400)

    except Exception as e:
        current_app.logger.error(str(e))
        raise e


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

    page_num = 1

    # add the rest of the document to the new doc. NOTIFY only appears on the first page
    while page_num < pdf.numPages:
        output.addPage(pdf.getPage(page_num))
        page_num = page_num + 1

    pdf_bytes = io.BytesIO()
    output.write(pdf_bytes)
    pdf_bytes.seek(0)

    return pdf_bytes


def validate_document(src_pdf):
    pdf_to_validate = _add_no_print_areas(src_pdf)
    return _validate_pdf(PdfFileReader(pdf_to_validate))


def _add_no_print_areas(src_pdf):
    """
    Overlays the printable areas onto the src PDF, this is so the code can check for a presence of non white in the
    areas outside the printable area.

    :param PyPDF2.PdfFileReader src_pdf: A File object or an object that supports the standard read and seek methods
    """
    pdf = PyPDF2.PdfFileReader(src_pdf)
    output = PdfFileWriter()
    page = pdf.getPage(0)
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    can.setStrokeColor(white)
    can.setFillColor(white)

    # Overlay the blacks where the service can print as per the template
    # The first page is more varied because of address blocks etc subsequent pages are more simple

    # Body
    x = BORDER_FROM_LEFT_OF_PAGE * mm
    y = BORDER_FROM_BOTTOM_OF_PAGE * mm
    width = float(page.mediaBox[2]) - ((BORDER_FROM_LEFT_OF_PAGE + BORDER_FROM_RIGHT_OF_PAGE) * mm)
    height = float(page.mediaBox[3]) - ((BODY_TOP_FROM_TOP_OF_PAGE + BORDER_FROM_BOTTOM_OF_PAGE) * mm)
    can.rect(x, y, width, height, fill=True)

    # Service address block
    x = SERVICE_ADDRESS_FROM_LEFT_OF_PAGE * mm
    y = float(page.mediaBox[3]) - (SERVICE_ADDRESS_BOTTOM_FROM_TOP_OF_PAGE * mm)
    width = float(page.mediaBox[2]) - ((SERVICE_ADDRESS_FROM_LEFT_OF_PAGE + BORDER_FROM_RIGHT_OF_PAGE) * mm)
    height = (SERVICE_ADDRESS_BOTTOM_FROM_TOP_OF_PAGE - BORDER_FROM_TOP_OF_PAGE) * mm
    can.rect(x, y, width, height, fill=True)

    # Citizen Address Block
    x = ADDRESS_BOTTOM_FROM_LEFT_OF_PAGE * mm
    y = float(page.mediaBox[3]) - (ADDRESS_BOTTOM_FROM_TOP_OF_PAGE * mm)
    width = float(page.mediaBox[2]) - ((ADDRESS_BOTTOM_FROM_LEFT_OF_PAGE + BORDER_FROM_RIGHT_OF_PAGE) * mm)
    height = (ADDRESS_BOTTOM_FROM_TOP_OF_PAGE - ADDRESS_TOP_FROM_TOP_OF_PAGE) * mm
    can.rect(x, y, width, height, fill=True)

    # Service Logo Block
    x = LOGO_BOTTOM_FROM_LEFT_OF_PAGE * mm
    y = float(page.mediaBox[3]) - (LOGO_BOTTOM_FROM_TOP_OF_PAGE * mm)
    width = float(page.mediaBox[2]) - ((LOGO_BOTTOM_FROM_LEFT_OF_PAGE + BORDER_FROM_RIGHT_OF_PAGE) * mm)
    height = (LOGO_BOTTOM_FROM_TOP_OF_PAGE - LOGO_TOP_FROM_TOP_OF_PAGE) * mm
    can.rect(x, y, width, height, fill=True)

    can.save()

    # move to the beginning of the StringIO buffer
    packet.seek(0)
    new_pdf = PyPDF2.PdfFileReader(packet)

    page.mergePage(new_pdf.getPage(0))
    output.addPage(page)

    page_num = 1

    # For each subsequent page its just the body of text
    while page_num < pdf.numPages:
        page = pdf.getPage(page_num)
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=A4)
        can.setStrokeColor(white)
        can.setFillColor(white)

        # Each page of content
        x = BORDER_FROM_LEFT_OF_PAGE * mm
        y = BORDER_FROM_BOTTOM_OF_PAGE * mm
        width = float(page.mediaBox[2]) - ((BORDER_FROM_LEFT_OF_PAGE + BORDER_FROM_RIGHT_OF_PAGE) * mm)
        height = float(page.mediaBox[3]) - ((BORDER_FROM_TOP_OF_PAGE + BORDER_FROM_BOTTOM_OF_PAGE) * mm)
        can.rect(x, y, width, height, fill=True)
        can.save()

        # move to the beginning of the StringIO buffer
        packet.seek(0)
        new_pdf = PyPDF2.PdfFileReader(packet)

        page.mergePage(new_pdf.getPage(0))
        output.addPage(page)

        page_num = page_num + 1

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

    page_num = 0

    # For each subsequent page its just the body of text
    while page_num < src_pdf.numPages:
        dst_pdf.addPage(src_pdf.getPage(page_num))
        page_num = page_num + 1

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
