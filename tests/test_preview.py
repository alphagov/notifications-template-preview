import json
import os
from unittest.mock import patch, Mock

from flask import url_for
import pytest

from app import LOGOS
from app.preview import get_logo
from werkzeug.exceptions import BadRequest


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


@pytest.fixture
def print_letter_template(client, auth_header, preview_post_body):
    """
    Makes a post to the view_letter_template endpoint
    usage examples:

    resp = post()
    resp = post('pdf')
    resp = post('pdf', json={...})
    resp = post('pdf', headers={...})
    """
    return lambda data=preview_post_body, headers=auth_header: (
        client.post(
            url_for('preview_blueprint.print_letter_template'),
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


@pytest.mark.parametrize('filetype, sentence_count, page_number, expected_response_code', [
    ('png', 10, 1, 200),
    ('pdf', 10, 1, 400),
    ('png', 10, 2, 400),
    ('png', 50, 2, 200),
    ('png', 50, 3, 400),
])
def test_get_image_by_page(
    client,
    auth_header,
    filetype,
    sentence_count,
    page_number,
    expected_response_code
):
    response = client.post(
        url_for('preview_blueprint.view_letter_template', filetype=filetype, page=page_number),
        data=json.dumps({
            'letter_contact_block': '123',
            'template': {
                'subject': 'letter subject',
                'content': (
                    'All work and no play makes Jack a dull boy. ' * sentence_count
                ),
            },
            'values': {},
            'dvla_org_id': '001',
        }),
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )
    assert response.status_code == expected_response_code


def test_letter_template_constructed_properly(preview_post_body, view_letter_template):
    with patch('app.preview.LetterPreviewTemplate', __str__=Mock(return_value='foo')) as mock_template:
        resp = view_letter_template()
        assert resp.status_code == 200

    mock_template.assert_called_once_with(
        preview_post_body['template'],
        values=preview_post_body['values'],
        contact_block=preview_post_body['letter_contact_block'],
        admin_base_url='http://localhost:6013',
        logo_file_name='hm-government.png',
    )


def test_invalid_filetype_404s(view_letter_template):
    resp = view_letter_template(filetype='foo')
    assert resp.status_code == 404


@pytest.mark.parametrize('missing_item', {
    'letter_contact_block', 'values', 'template', 'dvla_org_id'
})
def test_missing_field_400s(view_letter_template, preview_post_body, missing_item):
    preview_post_body.pop(missing_item)

    resp = view_letter_template(data=preview_post_body)

    assert resp.status_code == 400


def test_bad_org_id_400s(view_letter_template, preview_post_body):

    preview_post_body.update({'dvla_org_id': '404'})

    resp = view_letter_template(data=preview_post_body)

    assert resp.status_code == 400


@pytest.mark.parametrize('blank_item', ['letter_contact_block', 'values'])
def test_blank_fields_okay(view_letter_template, preview_post_body, blank_item):
    preview_post_body[blank_item] = None

    with patch('app.preview.LetterPreviewTemplate', __str__=Mock(return_value='foo')) as mock_template:
        resp = view_letter_template(data=preview_post_body)

    assert resp.status_code == 200
    assert mock_template.called is True


@pytest.mark.parametrize('sentence_count, expected_pages', [
    (10, 1),
    (50, 2),
])
def test_page_count(
    client,
    auth_header,
    sentence_count,
    expected_pages
):
    response = client.post(
        url_for('preview_blueprint.page_count'),
        data=json.dumps({
            'letter_contact_block': '123',
            'template': {
                'subject': 'letter subject',
                'content': (
                    'All work and no play makes Jack a dull boy. ' * sentence_count
                ),
            },
            'values': {},
            'dvla_org_id': '001',
        }),
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True)) == {'count': expected_pages}


def test_print_letter_returns_200(print_letter_template):
    resp = print_letter_template()

    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/pdf'
    assert resp.headers['X-pdf-page-count'] == '1'
    assert len(resp.get_data()) > 0


@pytest.mark.parametrize('dvla_org_id, expected_filename', [
    ('001', 'hm-government.png'),
    ('002', 'opg.png'),
    ('003', 'dwp.png'),
    ('004', 'geo.png'),
    ('005', 'ch.png'),
    ('500', 'hm-land-registry.png'),
    pytest.mark.xfail((500, 'strings_only.png'), raises=BadRequest),
    pytest.mark.xfail(('999', 'doesnt_exist.png'), raises=BadRequest),
])
def test_getting_logos(client, dvla_org_id, expected_filename):
    assert get_logo(dvla_org_id).rgb == expected_filename


@pytest.mark.parametrize('logo', LOGOS.values())
def test_that_logo_files_exist(logo):
    for filename in (
        logo.rgb, logo.cmyk
    ):
        assert os.path.isfile(
            os.path.join(
                os.path.dirname(os.path.realpath(__file__)),
                '..',
                'static', 'images', 'letter-template',
                filename
            )
        )
