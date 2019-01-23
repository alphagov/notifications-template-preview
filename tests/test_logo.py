from io import BytesIO


def test_logo(client, auth_header):
    response = client.get('/hm-government.svg.png', headers={'Content-type': 'application/json', **auth_header})

    with open('tests/test_pdfs/hm-government.png', 'rb') as f:
        expected_file = f.read()

    assert response.get_data() == BytesIO(expected_file).getvalue()


def test_logo_returns_404_if_logo_does_not_exist(client, auth_header):
    response = client.get('/does-not-exist.svg.png', headers={'Content-type': 'application/json', **auth_header})

    assert response.status_code == 404
