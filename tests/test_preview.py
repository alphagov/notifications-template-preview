import json
import uuid
from io import BytesIO
from unittest.mock import Mock, patch

import pytest
from flask import current_app, url_for
from flask_weasyprint import HTML
from freezegun import freeze_time
from notifications_utils.s3 import S3ObjectNotFound

from app.preview import get_html
from tests.conftest import s3_response_body, set_config
from tests.pdf_consts import cmyk_and_rgb_images_in_one_pdf, multi_page_pdf, valid_letter


@pytest.fixture
def view_letter_template(client, auth_header, view_letter_template_request_data):
    """
    Makes a post to the view_letter_template endpoint
    usage examples:

    resp = post()
    resp = post('pdf')
    resp = post('pdf', json={...})
    resp = post('pdf', headers={...})
    """
    return lambda filetype="pdf", data=view_letter_template_request_data, headers=auth_header: (
        client.post(
            url_for("preview_blueprint.view_letter_template", filetype=filetype),
            data=json.dumps(data),
            headers={"Content-type": "application/json", **headers},
        )
    )


@pytest.fixture
def view_letter_attachment(client, auth_header, view_letter_template_request_data):
    """
    Makes a post to the view_letter_attachment_preview endpoint
    usage examples:

    resp = post()
    resp = post(json={...})
    resp = post(headers={...})
    """
    return lambda data=view_letter_template_request_data, headers=auth_header: (
        client.post(
            url_for("preview_blueprint.view_letter_attachment_preview"),
            data=json.dumps(data),
            headers={"Content-type": "application/json", **headers},
        )
    )


@pytest.mark.parametrize("filetype", ["pdf", "png"])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Token not-the-actual-token"}])
def test_preview_rejects_if_not_authenticated(client, filetype, headers):
    resp = client.post(
        url_for("preview_blueprint.view_letter_template", filetype=filetype),
        data={},
        headers=headers,
    )
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Token my-secret-key"},
        {"Authorization": "Token my-secret-key2"},
    ],
)
def test_preview_accepts_either_api_key(client, view_letter_template_request_data, headers):
    resp = client.post(
        url_for("preview_blueprint.view_letter_template", filetype="pdf"),
        data=json.dumps(view_letter_template_request_data),
        headers={"Content-type": "application/json", **headers},
    )
    assert resp.status_code == 200


@pytest.mark.parametrize("filetype, mimetype", [("pdf", "application/pdf"), ("png", "image/png")])
def test_return_headers_match_filetype(view_letter_template, filetype, mimetype):
    resp = view_letter_template(filetype)

    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == mimetype


@freeze_time("2012-12-12")
def test_get_pdf_caches_with_correct_keys(
    app,
    mocker,
    view_letter_template,
    mocked_cache_get,
    mocked_cache_set,
):
    expected_cache_key = "templated/d0a9992bafc3669a8104aec93d89e4bc7dca4cb1.pdf"
    resp = view_letter_template(filetype="pdf")

    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "application/pdf"
    assert resp.get_data().startswith(b"%PDF-1.7")
    mocked_cache_get.assert_called_once_with("test-template-preview-cache", expected_cache_key)
    assert mocked_cache_set.call_count == 1
    mocked_cache_set.call_args[0][0].seek(0)
    assert mocked_cache_set.call_args[0][0].read() == resp.get_data()
    assert mocked_cache_set.call_args[0][1] == "eu-west-1"
    assert mocked_cache_set.call_args[0][2] == "test-template-preview-cache"
    assert mocked_cache_set.call_args[0][3] == expected_cache_key


@freeze_time("2012-12-12")
def test_get_png_caches_with_correct_keys(
    app,
    mocker,
    view_letter_template,
    mocked_cache_get,
    mocked_cache_set,
):
    expected_cache_key = "templated/cfa8aaad30c73e8c98fcf09a29ac6523a624fe00.page01.png"
    resp = view_letter_template(filetype="png")

    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "image/png"
    assert resp.get_data().startswith(b"\x89PNG")

    assert mocked_cache_get.call_count == 2
    assert mocked_cache_get.call_args_list[1][0][0] == "test-template-preview-cache"
    assert mocked_cache_get.call_args_list[1][0][1] == expected_cache_key
    assert mocked_cache_set.call_count == 2
    mocked_cache_set.call_args_list[1][0][0].seek(0)
    assert mocked_cache_set.call_args_list[1][0][0].read() == resp.get_data()
    assert mocked_cache_set.call_args_list[1][0][1] == "eu-west-1"
    assert mocked_cache_set.call_args_list[1][0][2] == "test-template-preview-cache"
    assert mocked_cache_set.call_args_list[1][0][3] == expected_cache_key


@pytest.mark.parametrize(
    "cache_get_returns, number_of_cache_get_calls, number_of_cache_set_calls",
    [
        # neither pdf nor png for letter found in cache
        (
            [S3ObjectNotFound({}, ""), S3ObjectNotFound({}, ""), S3ObjectNotFound({}, "")],
            2,
            2,
        ),
        # pdf not in cache, but png cached
        (
            [S3ObjectNotFound({}, ""), s3_response_body()],
            2,
            1,
        ),
        # pdf cached, but png not cached
        (
            # first cache_get call to get pdf, second to get png, if png not in cache
            # call get_pdf again to create png from pdf
            [s3_response_body(valid_letter), S3ObjectNotFound({}, ""), s3_response_body(valid_letter)],
            2,
            1,
        ),
        # both pdf and png found in cache
        (
            [s3_response_body(), s3_response_body()],
            2,
            0,
        ),
    ],
)
def test_view_letter_template_png_hits_cache_correct_number_of_times(
    app,
    mocker,
    view_letter_template,
    mocked_cache_get,
    mocked_cache_set,
    cache_get_returns,
    number_of_cache_get_calls,
    number_of_cache_set_calls,
):
    mocked_cache_get.side_effect = cache_get_returns

    mocker.patch("app.preview.get_page_count_for_pdf", return_value=2)

    response = view_letter_template(filetype="png")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/png"
    assert mocked_cache_get.call_count == number_of_cache_get_calls
    assert mocked_cache_set.call_count == number_of_cache_set_calls


@pytest.mark.parametrize(
    "cache_get_returns, number_of_cache_get_calls, number_of_cache_set_calls",
    [
        # neither pdfs nor png for letter found in cache
        (
            [
                S3ObjectNotFound({}, ""),
                S3ObjectNotFound({}, ""),
                S3ObjectNotFound({}, ""),
            ],
            3,
            3,
        ),
        # pdfs not in cache, but png cached
        (
            [S3ObjectNotFound({}, ""), S3ObjectNotFound({}, ""), s3_response_body()],
            3,
            2,
        ),
        # pdfs cached, but png not cached
        (
            # first cache_get call to get pdf, second to get png, if png not in cache
            # call get_pdf again to create png from pdf
            [
                s3_response_body(valid_letter),
                s3_response_body(valid_letter),
                S3ObjectNotFound({}, ""),
            ],
            3,
            1,
        ),
        # both pdfs and png found in cache
        (
            [s3_response_body(valid_letter), s3_response_body(valid_letter), s3_response_body()],
            3,
            0,
        ),
    ],
)
def test_view_letter_template_png_hits_cache_correct_number_of_times_for_a_bilingual_template(
    app,
    mocker,
    view_letter_template,
    view_letter_template_request_data_bilingual,
    mocked_cache_get,
    mocked_cache_set,
    cache_get_returns,
    number_of_cache_get_calls,
    number_of_cache_set_calls,
):
    mocked_cache_get.side_effect = cache_get_returns

    mocker.patch("app.preview.get_page_count_for_pdf", return_value=2)

    response = view_letter_template(filetype="png", data=view_letter_template_request_data_bilingual)

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/png"
    assert mocked_cache_get.call_count == number_of_cache_get_calls
    assert mocked_cache_set.call_count == number_of_cache_set_calls


@pytest.mark.parametrize(
    "attachment_cache,number_of_cache_get_calls,number_of_cache_set_calls",
    [
        # attachment not cached
        (S3ObjectNotFound({}, ""), 2, 1),
        # attachment is cached
        (s3_response_body(), 2, 0),
    ],
)
def test_view_letter_template_png_with_attachment_hits_cache_correct_number_of_times(
    client,
    mocker,
    auth_header,
    mocked_cache_get,
    mocked_cache_set,
    attachment_cache,
    number_of_cache_get_calls,
    number_of_cache_set_calls,
):
    mocked_cache_get.side_effect = [s3_response_body(), attachment_cache]

    mocker.patch("app.preview.add_attachment_to_letter", return_value=multi_page_pdf)

    response = client.post(
        url_for(
            "preview_blueprint.view_letter_template",
            filetype="png",
            page=2,
        ),
        data=json.dumps(
            {
                "letter_contact_block": "123",
                "template": {
                    "id": str(uuid.uuid4()),
                    "template_type": "letter",
                    "subject": "letter subject",
                    "content": "All work and no play makes Jack a dull boy. ",
                    "version": 1,
                    "letter_attachment": {"page_count": 1, "id": "1234"},
                    "service": "5678",
                },
                "values": {},
                "filename": "hm-government",
            }
        ),
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/png"
    assert mocked_cache_get.call_count == number_of_cache_get_calls
    assert mocked_cache_set.call_count == number_of_cache_set_calls


@pytest.mark.parametrize(
    "filetype, sentence_count, page_number, expected_response_code",
    [
        ("pdf", 10, 1, 400),
    ],
)
def test_view_letter_template_fails_with_page_arg(
    client,
    auth_header,
    filetype,
    sentence_count,
    page_number,
    expected_response_code,
    mocker,
):
    mocked_hide_notify = mocker.patch("app.preview.hide_notify_tag")
    response = client.post(
        url_for(
            "preview_blueprint.view_letter_template",
            filetype=filetype,
            page=page_number,
        ),
        data=json.dumps(
            {
                "letter_contact_block": "123",
                "template": {
                    "id": str(uuid.uuid4()),
                    "template_type": "letter",
                    "subject": "letter subject",
                    "content": ("All work and no play makes Jack a dull boy. " * sentence_count),
                    "version": 1,
                },
                "values": {},
                "filename": "hm-government",
            }
        ),
        headers={"Content-type": "application/json", **auth_header},
    )
    assert response.status_code == expected_response_code
    assert not mocked_hide_notify.called


@pytest.mark.parametrize(
    "filetype, sentence_count, page_number, expected_response_code",
    [
        ("png", 10, 1, 200),
        ("png", 10, 2, 400),
        ("png", 50, 2, 200),
        ("png", 50, 3, 400),
    ],
)
def test_view_letter_template_png_route_gets_png_for_page(
    client,
    auth_header,
    filetype,
    sentence_count,
    page_number,
    expected_response_code,
    mocker,
):
    mocked_hide_notify = mocker.patch("app.preview.hide_notify_tag")
    response = client.post(
        url_for(
            "preview_blueprint.view_letter_template",
            filetype=filetype,
            page=page_number,
        ),
        data=json.dumps(
            {
                "letter_contact_block": "123",
                "template": {
                    "id": str(uuid.uuid4()),
                    "template_type": "letter",
                    "subject": "letter subject",
                    "content": ("All work and no play makes Jack a dull boy. " * sentence_count),
                    "version": 1,
                },
                "values": {},
                "filename": "hm-government",
            }
        ),
        headers={"Content-type": "application/json", **auth_header},
    )
    assert response.status_code == expected_response_code
    assert not mocked_hide_notify.called


def test_view_letter_template_for_letter_attachment(
    client,
    auth_header,
    mocker,
):
    mocked_hide_notify = mocker.patch("app.preview.hide_notify_tag")
    mock_s3download_attachment_file = mocker.patch(
        "app.letter_attachments.s3download", return_value=BytesIO(valid_letter)
    )
    response = client.post(
        url_for(
            "preview_blueprint.view_letter_template",
            filetype="png",
            page=2,
        ),
        data=json.dumps(
            {
                "letter_contact_block": "123",
                "template": {
                    "id": str(uuid.uuid4()),
                    "template_type": "letter",
                    "subject": "letter subject",
                    "content": ("All work and no play makes Jack a dull boy. "),
                    "version": 1,
                    "letter_attachment": {"page_count": 1, "id": "1234"},
                    "service": "5678",
                },
                "values": {},
                "filename": "hm-government",
            }
        ),
        headers={"Content-type": "application/json", **auth_header},
    )
    assert response.status_code == 200
    assert not mocked_hide_notify.called
    assert mock_s3download_attachment_file.called_once_with(
        current_app.config["LETTER_ATTACHMENT_BUCKET_NAME"], "service-5678/1234.pdf"
    )
    assert response.mimetype == "image/png"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Token not-the-actual-token"}])
def test_view_letter_attachment_preview_rejects_if_not_authenticated(client, headers):
    resp = client.post(
        url_for("preview_blueprint.view_letter_attachment_preview"),
        data={},
        headers=headers,
    )
    assert resp.status_code == 401


def test_preview_for_letter_attachment(
    client,
    auth_header,
    mocker,
):
    mock_s3download_attachment_file = mocker.patch(
        "app.letter_attachments.s3download", return_value=BytesIO(valid_letter)
    )
    response = client.post(
        url_for(
            "preview_blueprint.view_letter_attachment_preview",
            page=1,
        ),
        data=json.dumps(
            {
                "service_id": "123",
                "letter_attachment_id": str(uuid.uuid4()),
            }
        ),
        headers={"Content-type": "application/json", **auth_header},
    )
    assert response.status_code == 200
    assert mock_s3download_attachment_file.called_once_with(
        current_app.config["LETTER_ATTACHMENT_BUCKET_NAME"], "service-5678/1234.pdf"
    )
    assert response.mimetype == "image/png"


@pytest.mark.parametrize("letter_attachment, requested_page", [(None, 2), ({"page_count": 1, "id": "1234"}, 3)])
def test_view_letter_attachment_preview_when_requested_page_out_of_range(
    client, auth_header, mocker, letter_attachment, requested_page
):
    mock_s3download_attachment_file = mocker.patch(
        "app.letter_attachments.s3download", return_value=BytesIO(valid_letter)
    )
    response = client.post(
        url_for(
            "preview_blueprint.view_letter_attachment_preview",
            page=requested_page,
        ),
        data=json.dumps(
            {
                "service_id": "123",
                "letter_attachment_id": str(uuid.uuid4()),
            }
        ),
        headers={"Content-type": "application/json", **auth_header},
    )
    assert response.status_code == 400
    assert response.json["message"] == f"400 Bad Request: Letter attachment does not have a page {requested_page}"
    assert mock_s3download_attachment_file.called_once


@pytest.mark.parametrize("letter_attachment, requested_page", [(None, 2), ({"page_count": 1, "id": "1234"}, 3)])
def test_view_letter_template_when_requested_page_out_of_range(
    client, auth_header, mocker, letter_attachment, requested_page
):
    mocker.patch("app.preview.hide_notify_tag")
    mocker.patch("app.preview.add_attachment_to_letter", return_value=cmyk_and_rgb_images_in_one_pdf)  # 2-page PDF
    response = client.post(
        url_for(
            "preview_blueprint.view_letter_template",
            filetype="png",
            page=requested_page,
        ),
        data=json.dumps(
            {
                "letter_contact_block": "123",
                "template": {
                    "id": str(uuid.uuid4()),
                    "template_type": "letter",
                    "subject": "letter subject",
                    "content": ("All work and no play makes Jack a dull boy. "),
                    "version": 1,
                    "letter_attachment": letter_attachment,
                    "service": "5678",
                },
                "values": {},
                "filename": "hm-government",
            }
        ),
        headers={"Content-type": "application/json", **auth_header},
    )
    assert response.status_code == 400
    assert response.json["message"] == f"400 Bad Request: Letter does not have a page {requested_page}"


def test_letter_template_constructed_properly(view_letter_template_request_data, view_letter_template):
    with patch("app.preview.LetterPreviewTemplate", __str__=Mock(return_value="foo")) as mock_template:
        resp = view_letter_template()
        assert resp.status_code == 200

    mock_template.assert_called_once_with(
        view_letter_template_request_data["template"],
        values=view_letter_template_request_data["values"],
        contact_block=view_letter_template_request_data["letter_contact_block"],
        admin_base_url="https://static-logos.notify.tools/letters",
        logo_file_name="hm-government.svg",
        date=None,
        language="english",
    )


def test_view_letter_template_pdf_adds_attachment(mocker, view_letter_template_request_data, view_letter_template):
    mock_get_pdf = mocker.patch("app.preview.get_pdf", return_value=BytesIO(b"templated letter pdf"))
    mock_add_attachment_to_letter = mocker.patch(
        "app.preview.add_attachment_to_letter", return_value=BytesIO(b"combined pdf")
    )

    view_letter_template_request_data["template"]["letter_attachment"] = {"page_count": 1, "id": "5678"}

    resp = view_letter_template(filetype="pdf", data=view_letter_template_request_data)

    assert resp.status_code == 200
    assert resp.get_data() == b"combined pdf"
    mock_add_attachment_to_letter.assert_called_once_with(
        service_id="1234",
        templated_letter_pdf=mock_get_pdf.return_value,
        attachment_object={"page_count": 1, "id": "5678"},
    )


@freeze_time("2023-11-09")
def test_view_letter_template_pdf_for_bilingual_template(
    mocker, view_letter_template_request_data_bilingual, view_letter_template
):
    mock_get_pdf = mocker.patch(
        "app.preview.get_pdf", side_effect=[BytesIO(b"templated letter pdf"), BytesIO(b"Welsh templated letter pdf")]
    )

    mocker.patch("app.preview.stitch_pdfs", return_value=BytesIO(b"Welsh then English templated letter pdf"))

    response = view_letter_template(filetype="pdf", data=view_letter_template_request_data_bilingual)

    assert response.status_code == 200

    assert response.get_data() == b"Welsh then English templated letter pdf"

    assert mock_get_pdf.call_count == 2
    assert "November" in mock_get_pdf.call_args_list[0].args[0].__str__()
    assert "Tachwedd" in mock_get_pdf.call_args_list[1].args[0].__str__()


def test_invalid_filetype_404s(view_letter_template):
    resp = view_letter_template(filetype="foo")
    assert resp.status_code == 404


@pytest.mark.parametrize("missing_item", ("letter_contact_block", "values", "template", "filename"))
def test_missing_field_400s(view_letter_template, view_letter_template_request_data, missing_item):
    view_letter_template_request_data.pop(missing_item)

    resp = view_letter_template(data=view_letter_template_request_data)

    assert resp.status_code == 400


@pytest.mark.parametrize("blank_item", ["letter_contact_block", "values"])
def test_blank_fields_okay(view_letter_template, view_letter_template_request_data, blank_item):
    view_letter_template_request_data[blank_item] = None

    with patch("app.preview.LetterPreviewTemplate", __str__=Mock(return_value="foo")) as mock_template:
        resp = view_letter_template(data=view_letter_template_request_data)

    assert resp.status_code == 200
    assert mock_template.called is True


def test_date_can_be_passed(view_letter_template, view_letter_template_request_data):
    view_letter_template_request_data["date"] = "2012-12-12T00:00:00"

    with patch("app.preview.HTML", wraps=HTML) as mock_html:
        resp = view_letter_template(data=view_letter_template_request_data)

    assert resp.status_code == 200
    assert "12 December 2012" in mock_html.call_args_list[0][1]["string"]


@pytest.mark.parametrize(
    "sentence_count, welsh_subject, welsh_content, letter_attachment, expected_pages",
    [
        (10, None, None, None, 1),  # short letter with no frills
        (50, None, None, None, 2),  # longer letter
        (10, None, None, {"page_count": 5}, 6),  # letter with attachment
        (10, "Da iawn", "Cathod yn neis", None, 2),  # bilingual letter
        (10, "Da iawn", "Cathod yn neis", {"page_count": 1}, 3),  # bilingual letter with attachment
    ],
)
def test_POST_page_count(
    client, auth_header, sentence_count, welsh_subject, welsh_content, letter_attachment, expected_pages
):
    response = client.post(
        url_for("preview_blueprint.page_count"),
        data=json.dumps(
            {
                "letter_contact_block": "123",
                "template": {
                    "id": str(uuid.uuid4()),
                    "template_type": "letter",
                    "subject": "letter subject",
                    "content": ("All work and no play makes Jack a dull boy. " * sentence_count),
                    "letter_welsh_content": welsh_content,
                    "letter_welsh_subject": welsh_subject,
                    "letter_languages": "welsh_then_english" if welsh_subject else "english",
                    "version": 1,
                    "letter_attachment": letter_attachment,
                },
                "values": {},
                "filename": "hm-government",
            }
        ),
        headers={"Content-type": "application/json", **auth_header},
    )
    assert response.status_code == 200

    attachment_page_count = letter_attachment["page_count"] if letter_attachment else 0
    welsh_template_page_count = 1 if welsh_subject else 0

    assert json.loads(response.get_data(as_text=True)) == {
        "count": expected_pages,
        "attachment_page_count": attachment_page_count,
        "welsh_page_count": welsh_template_page_count,
    }


@freeze_time("2012-12-12")
def test_page_count_from_cache(client, auth_header, mocker, mocked_cache_get):
    mocked_cache_get.side_effect = [s3_response_body(multi_page_pdf)]
    mocker.patch(
        "app.preview.HTML",
        side_effect=AssertionError("Uncached method shouldn’t be called"),
    )
    response = client.post(
        url_for("preview_blueprint.page_count"),
        data=json.dumps(
            {
                "letter_contact_block": "123",
                "template": {
                    "id": str(uuid.uuid4()),
                    "template_type": "letter",
                    "subject": "letter subject",
                    "content": " letter content",
                    "letter_attachment": None,
                },
                "values": {},
                "filename": "hm-government",
            }
        ),
        headers={"Content-type": "application/json", **auth_header},
    )
    assert mocked_cache_get.call_args[0][0] == "test-template-preview-cache"
    assert mocked_cache_get.call_args[0][1] == "templated/03ba71054b80b0ffc758d3b228784d1bfb8c0ca3.pdf"
    assert response.status_code == 200
    assert json.loads(response.get_data(as_text=True)) == {
        "count": 10,
        "attachment_page_count": 0,
        "welsh_page_count": 0,
    }


def test_returns_500_if_logo_not_found(app, view_letter_template):
    with set_config(app, "LETTER_LOGO_URL", "https://not-a-real-website/"):
        response = view_letter_template()

    assert response.status_code == 500


@pytest.mark.parametrize(
    "logo, is_svg_expected",
    [
        ("hm-government", True),
        (None, False),
    ],
)
def test_get_html(logo, is_svg_expected, view_letter_template_request_data, client):
    image_tag = '<img src="https://static-logos.notify.tools/letters'  # just see if any logo is in the letter at all
    view_letter_template_request_data["filename"] = logo

    output_html = get_html(view_letter_template_request_data)
    assert (image_tag in output_html) is is_svg_expected
