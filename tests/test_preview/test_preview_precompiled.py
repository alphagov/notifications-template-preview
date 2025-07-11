from base64 import b64encode
from hashlib import sha1
from io import BytesIO

import pytest
from flask import url_for

from tests.pdf_consts import blank_with_address, multi_page_pdf, not_pdf, valid_letter


@pytest.mark.parametrize("filetype", ["pdf", "png"])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Token not-the-actual-token"}])
def test_preview_rejects_if_not_authenticated(client, filetype, headers):
    resp = client.post(
        url_for("preview_blueprint.view_precompiled_letter", filetype=filetype),
        headers=headers,
    )
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "page_number, expected_response_code",
    [
        (1, 200),
        (2, 400),
    ],
)
def test_precompiled_valid_letter_get_image_by_page(
    client,
    auth_header,
    page_number,
    expected_response_code,
    mocker,
):
    response = client.post(
        url_for("preview_blueprint.view_precompiled_letter", page=page_number),
        data=b64encode(valid_letter),
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == expected_response_code


def test_precompiled_pdf_defaults_first_page_when_no_request_args(
    client,
    auth_header,
    mocker,
):
    mocked_png_from_pdf = mocker.patch(
        "app.preview.png_from_pdf",
        return_value=BytesIO(b"\x00"),
    )

    response = client.post(
        url_for("preview_blueprint.view_precompiled_letter"),
        data=b64encode(valid_letter),
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 200
    assert mocked_png_from_pdf.call_args[1]["page_number"] == 1


def test_precompiled_pdf_caches_png_to_s3(
    app,
    client,
    auth_header,
    mocker,
    mocked_cache_get,
    mocked_cache_set,
):
    response = client.post(
        url_for("preview_blueprint.view_precompiled_letter"),
        data=b64encode(valid_letter),
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/png"
    assert response.get_data().startswith(b"\x89PNG")
    mocked_cache_get.assert_called_once_with(
        "test-template-preview-cache",
        "pngs/a05cba9753a790829240e6ed667b2e73ae29e3ab.png",
    )
    mocked_cache_set.call_args[0][0].seek(0)
    assert mocked_cache_set.call_args[0][0].read() == response.get_data()
    assert mocked_cache_set.call_args[0][1] == "eu-west-1"
    assert mocked_cache_set.call_args[0][2] == "test-template-preview-cache"
    assert mocked_cache_set.call_args[0][3] == "pngs/a05cba9753a790829240e6ed667b2e73ae29e3ab.png"


@pytest.mark.parametrize(
    "pdf_file, expected_cache_key",
    (
        (valid_letter, "pngs/a05cba9753a790829240e6ed667b2e73ae29e3ab.png"),
        (blank_with_address, "pngs/9d5a4cc2ca568c227a550d1a73931afe8ff81d5a.png"),
    ),
    ids=[
        "valid_letter",
        "blank_with_address",
    ],
)
def test_precompiled_pdf_returns_png_from_cache(
    app,
    client,
    auth_header,
    mocked_cache_get,
    mocked_cache_set,
    pdf_file,
    expected_cache_key,
):
    mocked_cache_get.side_effect = None
    mocked_cache_get.return_value = BytesIO(b"\x00")

    response = client.post(
        url_for("preview_blueprint.view_precompiled_letter"),
        data=b64encode(pdf_file),
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/png"
    assert response.get_data() == b"\x00"
    mocked_cache_get.assert_called_once_with(
        "test-template-preview-cache",
        expected_cache_key,
    )
    assert mocked_cache_set.call_args_list == []


def test_precompiled_pdf_caches_entire_contents_of_page(
    app,
    client,
    auth_header,
    mocked_cache_get,
    mocker,
):
    mock_sha1 = mocker.patch("app.sha1", wraps=sha1)

    client.post(
        url_for("preview_blueprint.view_precompiled_letter"),
        data=b64encode(valid_letter),
        headers={"Content-type": "application/json", **auth_header},
    )

    data_to_be_hashed = mock_sha1.call_args_list[0][0][0]

    assert data_to_be_hashed.startswith(b"b'\\x80\\x04")  # Some pickled PDF
    assert data_to_be_hashed.endswith(b"False")  # The hide_notify argument

    assert len(valid_letter) == 23_218
    assert len(data_to_be_hashed) > len(valid_letter)  # Pickled PDF should take up more space


@pytest.mark.parametrize(
    "hide_notify_arg,called_hide_notify_tag",
    [
        ("true", True),
        ("", False),
    ],
)
def test_precompiled_valid_letter_get_image_by_page_hides_notify_tag(
    client,
    auth_header,
    hide_notify_arg,
    called_hide_notify_tag,
    mocker,
):
    mocked_hide_notify = mocker.patch("app.preview.hide_notify_tag")
    client.post(
        url_for(
            "preview_blueprint.view_precompiled_letter",
            page=1,
            hide_notify=hide_notify_arg,
        ),
        data=b64encode(valid_letter),
        headers={"Content-type": "application/json", **auth_header},
    )

    assert mocked_hide_notify.called == called_hide_notify_tag


@pytest.mark.parametrize(
    "page_number, expected_response_code",
    [
        (1, 200),
        (10, 200),
        (11, 400),
    ],
)
def test_precompiled_multi_page_pdf_get_image_by_page(
    client,
    auth_header,
    page_number,
    expected_response_code,
):
    response = client.post(
        url_for("preview_blueprint.view_precompiled_letter", page=page_number),
        data=b64encode(multi_page_pdf),
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == expected_response_code


def test_precompiled_no_data_get_image_by_page_raises_400(
    client,
    auth_header,
):
    response = client.post(
        url_for("preview_blueprint.view_precompiled_letter", page=1),
        data=None,
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 400


def test_precompiled_not_pdf_get_image_by_page_raises_400(
    client,
    auth_header,
):
    response = client.post(
        url_for("preview_blueprint.view_precompiled_letter", page=1),
        data=b64encode(not_pdf),
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 400
