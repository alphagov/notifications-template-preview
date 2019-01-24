import json
from io import BytesIO
from unittest.mock import Mock


def test_logo(client, auth_header, mocker):

    with open('tests/test_pdfs/hm-government.svg', 'rb') as f:
        file = f.read()

    resp = Mock(content=file, status_code=200)
    request_mock = mocker.patch('app.logo.requests.get', return_value=resp)

    response = client.get('/hm-government.svg.png', headers={'Content-type': 'application/json', **auth_header})

    with open('tests/test_pdfs/hm-government.png', 'rb') as f:
        expected_file = f.read()
    assert request_mock.called
    assert response.get_data() == BytesIO(expected_file).getvalue()


def test_logo_returns_404_if_logo_does_not_exist(client, auth_header, mocker):
    resp = Mock(status_code=404)
    request_mock = mocker.patch('app.logo.requests.get', return_value=resp)

    response = client.get('/does-not-exist.svg.png', headers={'Content-type': 'application/json', **auth_header})
    assert request_mock.called
    assert response.status_code == 404


def test_logo_returns_500_when_not_a_valid_svg_file(client, auth_header, mocker):
    with open('tests/test_pdfs/invalid-svg-file.svg', 'rb') as f:
        file = f.read()
    resp = Mock(contents=file, status_code=200)
    request_mock = mocker.patch('app.logo.requests.get', return_value=resp)

    response = client.get('/invalid-svg-file.svg.png', headers={'Content-type': 'application/json', **auth_header})
    assert request_mock.called
    assert response.status_code == 500
    assert json.loads(response.get_data(as_text=True))['result'] == "error"
