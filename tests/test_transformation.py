from flask_weasyprint import HTML

from app.transformation import convert_pdf_to_cmyk


def test_convert_to_cmyk_pdf_first_line_in_header_correct(client):
    html = HTML(string=str('<html></html>'))
    pdf = html.write_pdf()

    data = convert_pdf_to_cmyk(pdf)
    assert data[:9] == b'%PDF-1.7\n'
