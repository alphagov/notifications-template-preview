from io import BytesIO


def test_logo(mocker, app, client, auth_header):
    response = client.get('/hm-government.svg.png', headers={'Content-type': 'application/json', **auth_header})

    with open('tests/test_pdfs/hm-government.png', 'rb') as f:
        expected_file = f.read()

    assert response.get_data() == BytesIO(expected_file).getvalue()
