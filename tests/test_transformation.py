import pytest
import cv2
import numpy
from flask_weasyprint import HTML

from app.transformation import convert_pdf_to_cmyk
from app.preview import png_from_pdf

from tests.pdf_consts import rgb_image_pdf
from tests.pdf_consts import cmyk_image_pdf


def test_convert_to_cmyk_pdf_first_line_in_header_correct(client):
    html = HTML(string=str('<html></html>'))
    pdf = html.write_pdf()

    data = convert_pdf_to_cmyk(pdf)
    assert data[:9] == b'%PDF-1.7\n'


def test_subprocess_fails(client, mocker):
    mock_popen = mocker.patch('subprocess.Popen')
    mock_popen.return_value.returncode = 1
    mock_popen.return_value.communicate.return_value = ('Failed', 'There was an error')

    with pytest.raises(Exception) as excinfo:
        html = HTML(string=str('<html></html>'))
        pdf = html.write_pdf()
        convert_pdf_to_cmyk(pdf)
        assert 'ghostscript process failed with return code: 1' in str(excinfo.value)


def test_convert_to_cmyk_pdf_on_cmyk(client):
    input_as_png = png_from_pdf(cmyk_image_pdf, 1)
    data = convert_pdf_to_cmyk(cmyk_image_pdf)
    result_as_png = png_from_pdf(data, 1)
    with open('tests/test_pdfs/input_as_png.png', 'wb') as f:
        f.write(input_as_png.read())

    with open('tests/test_pdfs/result_as_png.png', 'wb') as f:
        f.write(result_as_png.read())
    pass


def test_convert_to_cmyk_pdf_on_rgb(client):
    input_as_png = png_from_pdf(rgb_image_pdf, 1)
    data = convert_pdf_to_cmyk(rgb_image_pdf)
    result_as_png = png_from_pdf(data, 1)
    with open('tests/test_pdfs/rgb_input_as_png.png', 'wb') as f:
        f.write(input_as_png.read())

    with open('tests/test_pdfs/rgb_result_as_png.png', 'wb') as f:
        f.write(result_as_png.read())
    pass


def test_convert_to_cmyk_results_same_from_rgb_and_from_cmyk(client):
    from_rgb_data = convert_pdf_to_cmyk(rgb_image_pdf)
    from_cmyk_data = convert_pdf_to_cmyk(cmyk_image_pdf)
    rgb_result_as_png = png_from_pdf(from_rgb_data, 1)
    cmyk_result_as_png = png_from_pdf(from_cmyk_data, 1)

    with open('tests/test_pdfs/result_from_rgb.png', 'wb') as f:
        f.write(rgb_result_as_png.read())

    with open('tests/test_pdfs/result_from_cmyk.png', 'wb') as f:
        f.write(cmyk_result_as_png.read())

    a = cv2.imread('tests/test_pdfs/result_from_rgb.png')
    b = cv2.imread('tests/test_pdfs/result_from_cmyk.png')
    difference = cv2.subtract(a, b)
    assert not numpy.any(difference)
