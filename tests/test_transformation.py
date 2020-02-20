import pytest
from flask_weasyprint import HTML

from app.transformation import convert_pdf_to_cmyk, does_pdf_contain_cmyk, does_pdf_contain_rgb

from tests.pdf_consts import rgb_image_pdf, cmyk_image_pdf, cmyk_and_rgb_images_in_one_pdf, multi_page_pdf


def test_convert_to_cmyk_pdf_first_line_in_header_correct(client):
    html = HTML(string=str('<html></html>'))
    pdf = html.write_pdf()

    data = convert_pdf_to_cmyk(pdf)
    assert data[:9] == b'%PDF-1.7\n'


def test_convert_to_cmyk_pdf_works_with_precompiled_pdf(client, auth_header):
    assert multi_page_pdf.startswith(b'%PDF-1.2')

    data = convert_pdf_to_cmyk(multi_page_pdf)

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


@pytest.mark.parametrize("data,result", [
    (cmyk_image_pdf, True),
    (rgb_image_pdf, False),
    (cmyk_and_rgb_images_in_one_pdf, True)
])
def test_does_pdf_contain_cmyk(client, data, result):
    assert does_pdf_contain_cmyk(data) == result


@pytest.mark.parametrize("data,result", [
    (rgb_image_pdf, True),
    (cmyk_image_pdf, False),
    (cmyk_and_rgb_images_in_one_pdf, True)
])
def test_does_pdf_contain_rgb(client, data, result):
    assert does_pdf_contain_rgb(data) == result
