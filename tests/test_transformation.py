import pytest
from flask_weasyprint import HTML

from app.transformation import convert_pdf_to_cmyk


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
