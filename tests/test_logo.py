from io import BytesIO

import requests_mock


def test_logo(mocker, client, auth_header):
    with open('tests/test_pdfs/hm-government.svg', 'rb') as f:
        file = f.read()

    with requests_mock.Mocker() as request_mock:
        request_mock.get('/{}/static/images/letter-template/hm-government.svg',
                         body=file,
                         status_code=200)

    response = client.get('/hm-government.svg.png', headers={'Content-type': 'application/json', **auth_header})

    with open('tests/test_pdfs/hm-government.png', 'rb') as f:
        expected_file = f.read()

    assert response.get_data() == BytesIO(expected_file).getvalue()
