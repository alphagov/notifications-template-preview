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
        return_value={
            'filename_or_fp': b'\x00',
            'mimetype': 'image/png'
        }
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


@pytest.mark.parametrize('page_number, called_hide_notify_tag', [
    (1, True),
    (2, False),
])
def test_precompiled_one_page_pdf_get_image_by_page_hides_notify_tag(
    client,
    auth_header,
    page_number,
    called_hide_notify_tag,
    mocker,
):
    mocked_hide_notify = mocker.patch('app.preview.hide_notify_tag')
    client.post(
        url_for('preview_blueprint.view_precompiled_letter', page=page_number),
        data=one_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert mocked_hide_notify.called == called_hide_notify_tag


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
