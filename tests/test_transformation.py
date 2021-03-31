from io import BytesIO

import pytest
from PyPDF2 import PdfFileReader
from reportlab.lib.units import mm
from weasyprint import HTML

from app.precompiled import _is_page_A4_portrait
from app.transformation import (
    convert_pdf_to_cmyk,
    does_pdf_contain_cmyk,
    does_pdf_contain_rgb,
)
from tests.pdf_consts import (
    cmyk_and_rgb_images_in_one_pdf,
    cmyk_image_pdf,
    multi_page_pdf,
    portrait_rotated_page,
    rgb_image_pdf,
)


@pytest.mark.parametrize('pdf', [
    HTML(string=str('<html></html>')).write_pdf(),
    multi_page_pdf
], ids=['templated', 'precompiled'])
def test_convert_pdf_to_cmyk_outputs_valid_pdf(pdf):
    data = convert_pdf_to_cmyk(BytesIO(pdf))
    assert data.read(9) == b'%PDF-1.7\n'


def test_subprocess_fails(client, mocker):
    mock_popen = mocker.patch('subprocess.Popen')
    mock_popen.return_value.returncode = 1
    mock_popen.return_value.communicate.return_value = ('Failed', 'There was an error')

    with pytest.raises(Exception) as excinfo:
        html = HTML(string=str('<html></html>'))
        pdf = BytesIO(html.write_pdf())
        convert_pdf_to_cmyk(pdf)
        assert 'ghostscript process failed with return code: 1' in str(excinfo.value)


def test_convert_pdf_to_cmyk_does_not_rotate_pages():
    file_with_rotated_text = BytesIO(portrait_rotated_page)

    transformed_pdf = PdfFileReader(
        convert_pdf_to_cmyk(file_with_rotated_text)
    )
    page = transformed_pdf.getPage(0)

    page_height = float(page.mediaBox.getHeight()) / mm
    page_width = float(page.mediaBox.getWidth()) / mm
    rotation = page.get('/Rotate')

    assert rotation is None
    assert _is_page_A4_portrait(page_height, page_width, rotation) is True


@pytest.mark.parametrize("data,result", [
    (cmyk_image_pdf, True),
    (rgb_image_pdf, False),
    (cmyk_and_rgb_images_in_one_pdf, True)
], ids=['cmyk_image_pdf', 'rgb_image_pdf', 'cmyk_and_rgb_images_in_one_pdf'])
def test_does_pdf_contain_cmyk(client, data, result):
    assert does_pdf_contain_cmyk(BytesIO(data)) == result


@pytest.mark.parametrize("data,result", [
    (rgb_image_pdf, True),
    (cmyk_image_pdf, False),
    (cmyk_and_rgb_images_in_one_pdf, True)
])
def test_does_pdf_contain_rgb(client, data, result):
    assert does_pdf_contain_rgb(BytesIO(data)) == result
