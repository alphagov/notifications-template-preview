import json
import uuid
from io import BytesIO
from unittest.mock import Mock, patch

import pytest
from flask import url_for
from flask_weasyprint import HTML
from freezegun import freeze_time
from notifications_utils.s3 import S3ObjectNotFound

from app.preview import get_html
from tests.conftest import set_config
from tests.pdf_consts import multi_page_pdf, valid_letter


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


class NonIterableIO():
    """
    Mimics the behaviour of the IO object that a call to Boto returns
    """

    def __init__(self, data):
        self.data = data

    def read(self, *args, **kwargs):
        return BytesIO(self.data).read(*args, **kwargs)


@pytest.mark.parametrize('filetype', ['pdf', 'png'])
@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Token not-the-actual-token'}])
def test_preview_rejects_if_not_authenticated(client, filetype, headers):
    resp = client.post(
        url_for('preview_blueprint.view_letter_template', filetype=filetype),
        data={},
        headers=headers
    )
    assert resp.status_code == 401


@pytest.mark.parametrize('headers', [
    {'Authorization': 'Token my-secret-key'},
    {'Authorization': 'Token my-secret-key2'}
])
def test_preview_accepts_either_api_key(client, preview_post_body, headers):
    resp = client.post(
        url_for('preview_blueprint.view_letter_template', filetype="pdf"),
        data=json.dumps(preview_post_body),
        headers={
            'Content-type': 'application/json',
            **headers
        }
    )
    assert resp.status_code == 200


@pytest.mark.parametrize('filetype, mimetype', [
    ('pdf', 'application/pdf'),
    ('png', 'image/png')
])
def test_return_headers_match_filetype(view_letter_template, filetype, mimetype):
    resp = view_letter_template(filetype)

    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == mimetype


@freeze_time('2012-12-12')
def test_get_pdf_caches_with_correct_keys(
    app,
    mocker,
    view_letter_template,
    mocked_cache_get,
    mocked_cache_set,
):
    expected_cache_key = 'templated/3ae434857323e58ba2961b84c8b2cb823ebf332f.pdf'
    resp = view_letter_template(filetype='pdf')

    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/pdf'
    assert resp.get_data().startswith(b'%PDF-1.5')
    mocked_cache_get.assert_called_once_with(
        'test-template-preview-cache',
        expected_cache_key
    )
    assert mocked_cache_set.call_count == 1
    mocked_cache_set.call_args[0][0].seek(0)
    assert mocked_cache_set.call_args[0][0].read() == resp.get_data()
    assert mocked_cache_set.call_args[0][1] == 'eu-west-1'
    assert mocked_cache_set.call_args[0][2] == 'test-template-preview-cache'
    assert mocked_cache_set.call_args[0][3] == expected_cache_key


@freeze_time('2012-12-12')
def test_get_png_caches_with_correct_keys(
    app,
    mocker,
    view_letter_template,
    mocked_cache_get,
    mocked_cache_set,
):
    expected_cache_key = 'templated/3ae434857323e58ba2961b84c8b2cb823ebf332f.page01.png'
    resp = view_letter_template(filetype='png')

    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'image/png'
    assert resp.get_data().startswith(b'\x89PNG')
    assert mocked_cache_get.call_count == 2
    assert mocked_cache_get.call_args_list[0][0][0] == 'test-template-preview-cache'
    assert mocked_cache_get.call_args_list[0][0][1] == expected_cache_key
    assert mocked_cache_set.call_count == 2
    mocked_cache_set.call_args_list[1][0][0].seek(0)
    assert mocked_cache_set.call_args_list[1][0][0].read() == resp.get_data()
    assert mocked_cache_set.call_args_list[1][0][1] == 'eu-west-1'
    assert mocked_cache_set.call_args_list[1][0][2] == 'test-template-preview-cache'
    assert mocked_cache_set.call_args_list[1][0][3] == expected_cache_key


@pytest.mark.parametrize('side_effects, number_of_cache_get_calls, number_of_cache_set_calls', [
    (
        [S3ObjectNotFound({}, ''), S3ObjectNotFound({}, '')],
        2,
        2,
    ),
    (
        [NonIterableIO(b'\x00'), S3ObjectNotFound({}, '')],
        1,
        0,
    ),
    (
        [S3ObjectNotFound({}, ''), NonIterableIO(valid_letter)],
        2,
        1,
    ),
    (
        [NonIterableIO(b'\x00'), NonIterableIO(b'\x00')],
        1,
        0,
    ),
])
def test_get_png_hits_cache_correct_number_of_times(
    app,
    mocker,
    view_letter_template,
    mocked_cache_get,
    mocked_cache_set,
    side_effects,
    number_of_cache_get_calls,
    number_of_cache_set_calls,
):

    mocked_cache_get.side_effect = side_effects

    resp = view_letter_template(filetype='png')

    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'image/png'
    assert mocked_cache_get.call_count == number_of_cache_get_calls
    assert mocked_cache_set.call_count == number_of_cache_set_calls


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
    expected_response_code,
    mocker,
):
    mocked_hide_notify = mocker.patch('app.preview.hide_notify_tag')
    response = client.post(
        url_for('preview_blueprint.view_letter_template', filetype=filetype, page=page_number),
        data=json.dumps({
            'letter_contact_block': '123',
            'template': {
                'id': str(uuid.uuid4()),
                'template_type': 'letter',
                'subject': 'letter subject',
                'content': (
                    'All work and no play makes Jack a dull boy. ' * sentence_count
                ),
                'version': 1
            },
            'values': {},
            'filename': 'hm-government',
        }),
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )
    assert response.status_code == expected_response_code
    assert not mocked_hide_notify.called


def test_letter_template_constructed_properly(preview_post_body, view_letter_template):
    with patch('app.preview.LetterPreviewTemplate', __str__=Mock(return_value='foo')) as mock_template:
        resp = view_letter_template()
        assert resp.status_code == 200

    mock_template.assert_called_once_with(
        preview_post_body['template'],
        values=preview_post_body['values'],
        contact_block=preview_post_body['letter_contact_block'],
        admin_base_url='https://static-logos.notify.tools/letters',
        logo_file_name='hm-government.svg',
        date=None,
    )


def test_invalid_filetype_404s(view_letter_template):
    resp = view_letter_template(filetype='foo')
    assert resp.status_code == 404


@pytest.mark.parametrize('missing_item', {
    'letter_contact_block', 'values', 'template', 'filename'
})
def test_missing_field_400s(view_letter_template, preview_post_body, missing_item):
    preview_post_body.pop(missing_item)

    resp = view_letter_template(data=preview_post_body)

    assert resp.status_code == 400


@pytest.mark.parametrize('blank_item', ['letter_contact_block', 'values'])
def test_blank_fields_okay(view_letter_template, preview_post_body, blank_item):
    preview_post_body[blank_item] = None

    with patch('app.preview.LetterPreviewTemplate', __str__=Mock(return_value='foo')) as mock_template:
        resp = view_letter_template(data=preview_post_body)

    assert resp.status_code == 200
    assert mock_template.called is True


def test_date_can_be_passed(view_letter_template, preview_post_body):

    preview_post_body['date'] = '2012-12-12T00:00:00'

    with patch('app.preview.HTML', wraps=HTML) as mock_html:
        resp = view_letter_template(data=preview_post_body)

    assert resp.status_code == 200
    assert '12 December 2012' in mock_html.call_args_list[0][1]['string']


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
                'id': str(uuid.uuid4()),
                'template_type': 'letter',
                'subject': 'letter subject',
                'content': (
                    'All work and no play makes Jack a dull boy. ' * sentence_count
                ),
                'version': 1
            },
            'values': {},
            'filename': 'hm-government',
        }),
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True)) == {'count': expected_pages}


@freeze_time('2012-12-12')
def test_page_count_from_cache(
    client,
    auth_header,
    mocker,
    mocked_cache_get
):
    mocked_cache_get.side_effect = [
        NonIterableIO(multi_page_pdf),
    ]
    mocker.patch(
        'app.preview.HTML',
        side_effect=AssertionError('Uncached method shouldn’t be called'),
    )
    response = client.post(
        url_for('preview_blueprint.page_count'),
        data=json.dumps({
            'letter_contact_block': '123',
            'template': {
                'id': str(uuid.uuid4()),
                'template_type': 'letter',
                'subject': 'letter subject',
                'content': ' letter content',
            },
            'values': {},
            'filename': 'hm-government',
        }),
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )
    assert mocked_cache_get.call_args[0][0] == 'test-template-preview-cache'
    assert mocked_cache_get.call_args[0][1] == 'templated/fc41fdf78b76f99dbddca1aed3f660a033fe1101.pdf'
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True)) == {'count': 10}


@pytest.mark.parametrize('logo', ['hm-government', None])
def test_print_letter_returns_200(logo, print_letter_template, preview_post_body):
    preview_post_body['filename'] = logo
    resp = print_letter_template(data=preview_post_body)

    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/pdf'
    assert resp.headers['X-pdf-page-count'] == '1'
    assert resp.get_data().startswith(b'%PDF-1.')


def test_returns_500_if_logo_not_found(app, view_letter_template):
    with set_config(app, 'LETTER_LOGO_URL', 'https://not-a-real-website/'):
        response = view_letter_template()

    assert response.status_code == 500


@pytest.mark.parametrize('logo, is_svg_expected', [
    ('hm-government', True),
    (None, False),
])
def test_get_html(logo, is_svg_expected, preview_post_body):
    image_tag = '<img src="https://static-logos.notify.tools/letters'  # just see if any logo is in the letter at all
    preview_post_body['filename'] = logo

    output_html = get_html(preview_post_body)
    assert (image_tag in output_html) is is_svg_expected
