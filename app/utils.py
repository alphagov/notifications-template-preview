from io import BytesIO

from pypdf import PdfReader, PdfWriter


def stitch_pdfs(first_pdf: BytesIO, second_pdf: BytesIO) -> BytesIO:
    output = PdfWriter()
    output.append_pages_from_reader(PdfReader(first_pdf))
    output.append_pages_from_reader(PdfReader(second_pdf))

    pdf_bytes = BytesIO()
    output.write(pdf_bytes)
    pdf_bytes.seek(0)
    return pdf_bytes
