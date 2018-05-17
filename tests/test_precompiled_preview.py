from io import BytesIO
from flask import url_for
import pytest

from tests.pdf_consts import one_page_pdf, multi_page_pdf, not_pdf


@pytest.mark.parametrize('filetype', ['pdf', 'png'])
@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Token not-the-actual-token'}])
def test_preview_rejects_if_not_authenticated(client, filetype, headers):
    resp = client.post(
        url_for('preview_blueprint.view_precompiled_letter', filetype=filetype),
        data={},
        headers=headers
    )
    assert resp.status_code == 401


@pytest.mark.parametrize('page_number, expected_response_code', [
    (1, 200),
    (2, 400),
])
def test_precompiled_one_page_pdf_get_image_by_page(
    client,
    auth_header,
    page_number,
    expected_response_code,
    mocker,
):
    response = client.post(
        url_for('preview_blueprint.view_precompiled_letter', page=page_number),
        data=one_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == expected_response_code


def test_precompiled_pdf_defaults_first_page_when_no_request_args(
    client,
    auth_header,
    mocker,
):
    mocked_png_from_pdf = mocker.patch(
        'app.preview.png_from_pdf',
        return_value=BytesIO(b'\x00'),
    )

    response = client.post(
        url_for('preview_blueprint.view_precompiled_letter'),
        data=one_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    assert mocked_png_from_pdf.call_args[1]['page_number'] == 1


def test_precompiled_pdf_caches_png_to_s3(
    app,
    client,
    auth_header,
    mocker,
    mocked_cache_get,
    mocked_cache_set,
):
    response = client.post(
        url_for('preview_blueprint.view_precompiled_letter'),
        data=one_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'image/png'
    assert response.get_data().startswith(b'\x89PNG')
    mocked_cache_get.assert_called_once_with(
        'sandbox-template-preview-cache',
        'c96858ed34197dead089a9512acac7cb206e734b.png'
    )
    mocked_cache_set.call_args[0][0].seek(0)
    assert mocked_cache_set.call_args[0][0].read() == response.get_data()
    assert mocked_cache_set.call_args[0][1] == 'eu-west-1'
    assert mocked_cache_set.call_args[0][2] == 'sandbox-template-preview-cache'
    assert mocked_cache_set.call_args[0][3] == 'c96858ed34197dead089a9512acac7cb206e734b.png'


def test_precompiled_pdf_returns_png_from_cache(
    app,
    client,
    auth_header,
    mocked_cache_get,
    mocked_cache_set,
):
    mocked_cache_get.side_effect = None
    mocked_cache_get.return_value = BytesIO(b'\x00')

    response = client.post(
        url_for('preview_blueprint.view_precompiled_letter'),
        data=one_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'image/png'
    assert response.get_data() == b'\x00'
    mocked_cache_get.assert_called_once_with(
        'sandbox-template-preview-cache',
        'c96858ed34197dead089a9512acac7cb206e734b.png'
    )
    assert mocked_cache_set.call_args_list == []


@pytest.mark.parametrize('hide_notify_arg,called_hide_notify_tag', [
    ('true', True),
    ('', False),
])
def test_precompiled_one_page_pdf_get_image_by_page_hides_notify_tag(
    client,
    auth_header,
    hide_notify_arg,
    called_hide_notify_tag,
    mocker,
):
    mocked_hide_notify = mocker.patch('app.preview.hide_notify_tag')
    client.post(
        url_for(
            'preview_blueprint.view_precompiled_letter',
            page=1,
            hide_notify=hide_notify_arg
        ),
        data=one_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert mocked_hide_notify.called == called_hide_notify_tag


def test_precompiled_cmyk_colourspace_calls_transform_colorspace(
    client,
    auth_header,
    mocker,
):
    mocker.patch('wand.image.Image.colorspace', 'cmyk')
    mock_transform = mocker.patch('wand.image.Image.transform_colorspace')

    client.post(
        url_for('preview_blueprint.view_precompiled_letter', page=1),
        data=one_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    mock_transform.assert_called_with('cmyk')


def test_precompiled_rgb_colourspace_does_not_call_transform_colorspace(
    client,
    auth_header,
    mocker,
):
    mocker.patch('wand.image.Image.colorspace', 'rgb')
    mock_transform = mocker.patch('wand.image.Image.transform_colorspace')

    client.post(
        url_for('preview_blueprint.view_precompiled_letter', page=1),
        data=one_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert not mock_transform.called


@pytest.mark.parametrize('page_number, expected_response_code', [
    (1, 200),
    (10, 200),
    (11, 400),
])
def test_precompiled_multi_page_pdf_get_image_by_page(
    client,
    auth_header,
    page_number,
    expected_response_code,
):
    response = client.post(
        url_for('preview_blueprint.view_precompiled_letter', page=page_number),
        data=multi_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == expected_response_code


def test_precompiled_no_data_get_image_by_page_raises_400(
    client,
    auth_header,
):
    response = client.post(
        url_for('preview_blueprint.view_precompiled_letter', page=1),
        data=None,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 400


def test_precompiled_not_pdf_get_image_by_page_raises_400(
    client,
    auth_header,
):
    response = client.post(
        url_for('preview_blueprint.view_precompiled_letter', page=1),
        data=not_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 400
