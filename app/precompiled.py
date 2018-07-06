import base64
import io
from io import BytesIO

import PyPDF2
from PyPDF2 import PdfFileWriter, PdfFileReader
from flask import request, abort, send_file, Blueprint
from notifications_utils.statsd_decorators import statsd
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

precompiled_blueprint = Blueprint('precompiled_blueprint', __name__)


@precompiled_blueprint.route("/precompiled", methods=['POST'])
@auth.login_required
@statsd(namespace="template_preview")
def add_tag_to_precompiled_letter():
    encoded_string = request.get_data()

    if not encoded_string:
        abort(400)

    file_data = base64.decodebytes(encoded_string)

    return send_file(filename_or_fp=add_notify_tag_to_letter(BytesIO(file_data)), mimetype='application/pdf')


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
