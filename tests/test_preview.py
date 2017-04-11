import json
from unittest.mock import patch, Mock

from flask import url_for
import pytest


@pytest.fixture
def view_letter_template(client, auth_header, preview_post_body):
    """
    Makes a post to the view_letter_template endpoint
    usage examples:

    resp = post()
    resp = post('pdf')
    resp = post('pdf', json={...})
    resp = post('pdf', headers={...})
    """
    return lambda filetype='pdf', data=preview_post_body, headers=auth_header: (
        client.post(
            url_for('preview_blueprint.view_letter_template', filetype=filetype),
            data=json.dumps(data),
            headers={
                'Content-type': 'application/json',
                **headers
            }
        )
    )


@pytest.mark.parametrize('filetype', ['pdf', 'png'])
@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Token not-the-actual-token'}])
def test_preview_rejects_if_not_authenticated(client, filetype, headers):
    resp = client.post(
        url_for('preview_blueprint.view_letter_template', filetype=filetype),
        data={},
        headers=headers
    )
    assert resp.status_code == 401


@pytest.mark.parametrize('filetype, mimetype', [
    ('pdf', 'application/pdf'),
    ('png', 'image/png')
])
def test_return_headers_match_filetype(view_letter_template, filetype, mimetype):
    resp = view_letter_template(filetype)

    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == mimetype


def test_letter_template_constructed_properly(preview_post_body, view_letter_template):
    with patch('app.preview.LetterPreviewTemplate', __str__=Mock(return_value='foo')) as mock_template:
        resp = view_letter_template()
        assert resp.status_code == 200

    mock_template.assert_called_once_with(
        preview_post_body['template'],
        values=preview_post_body['values'],
        contact_block=preview_post_body['letter_contact_block'],
        admin_base_url='http://localhost:6013'
    )
