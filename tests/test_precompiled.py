import base64
import io
import logging
from io import BytesIO
from unittest.mock import ANY, MagicMock, call

import fitz
import pypdf
import pytest
from flask import url_for
from pypdf.errors import PdfReadError
from reportlab.lib.colors import black, grey, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.precompiled import (
    NotifyCanvas,
    _warn_if_filesize_has_grown,
    add_address_to_precompiled_letter,
    add_notify_tag_to_letter,
    extract_address_block,
    get_invalid_pages_with_message,
    is_notify_tag_present,
    log_metadata_for_letter,
    redact_precompiled_letter_address_block,
    rewrite_address_block,
)
from tests.pdf_consts import (
    a3_size,
    a5_size,
    address_block_repeated_on_second_page,
    address_margin,
    address_with_unusual_coordinates,
    already_has_notify_tag,
    bad_postcode,
    blank_page,
    blank_with_2_line_address,
    blank_with_8_line_address,
    blank_with_address,
    example_dwp_pdf,
    hackney_sample,
    international_bfpo,
    invalid_address_character,
    landscape_oriented_page,
    landscape_rotated_page,
    multi_page_pdf,
    no_colour,
    no_fixed_abode,
    no_resources_on_last_page,
    non_uk_address,
    not_pdf,
    notify_tag_on_first_page,
    notify_tags_on_page_2_and_4,
    pdf_with_no_metadata,
    portrait_rotated_page,
    repeated_address_block,
    valid_letter,
)


@pytest.mark.parametrize(
    "endpoint, kwargs",
    [
        ("precompiled_blueprint.sanitise_precompiled_letter", {}),
        (
            "precompiled_blueprint.overlay_template_png_for_page",
            {"is_first_page": "true"},
        ),
        ("precompiled_blueprint.overlay_template_pdf", {}),
    ],
)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Token not-the-actual-token"}])
def test_endpoints_rejects_if_not_authenticated(client, headers, endpoint, kwargs):
    resp = client.post(url_for(endpoint, **kwargs), data={}, headers=headers)
    assert resp.status_code == 401


def test_add_notify_tag_to_letter(mocker):
    pdf_original = pypdf.PdfReader(BytesIO(multi_page_pdf))

    assert "NOTIFY" not in pdf_original.pages[0].extract_text()

    pdf_page = add_notify_tag_to_letter(BytesIO(multi_page_pdf))

    pdf_new = pypdf.PdfReader(BytesIO(pdf_page.read()))

    assert len(pdf_new.pages) == len(pdf_original.pages)
    assert pdf_new.pages[0].extract_text() != pdf_original.pages[0].extract_text()
    assert "NOTIFY" in pdf_new.pages[0].extract_text()
    assert pdf_new.pages[1].extract_text() == pdf_original.pages[1].extract_text()
    assert pdf_new.pages[2].extract_text() == pdf_original.pages[2].extract_text()
    assert pdf_new.pages[3].extract_text() == pdf_original.pages[3].extract_text()


def test_add_notify_tag_to_letter_correct_margins(mocker):
    pdf_original = pypdf.PdfReader(BytesIO(multi_page_pdf))

    can = NotifyCanvas(white)
    can.drawString = MagicMock(return_value=3)

    mocker.patch("app.precompiled.NotifyCanvas", return_value=can)

    # It fails because we are mocking but by that time the drawString method has been called so just carry on
    try:
        add_notify_tag_to_letter(BytesIO(multi_page_pdf))
    except Exception:
        pass

    mm_from_top_of_the_page = 1.8
    mm_from_left_of_page = 1.8
    font_size = 6

    x = mm_from_left_of_page * mm

    y = float(pdf_original.pages[0].mediabox[3]) - (float(mm_from_top_of_the_page * mm + font_size))

    assert len(can.drawString.call_args_list) == 1
    positional_args = can.drawString.call_args[0]
    assert len(positional_args) == 3
    assert positional_args[0] == pytest.approx(x, 0.01)  # cope with rounding error
    assert positional_args[1] == y
    assert positional_args[2] == "NOTIFY"


def test_get_invalid_pages_blank_page(client):
    packet = io.BytesIO()
    cv = canvas.Canvas(packet, pagesize=A4)
    cv.setStrokeColor(white)
    cv.setFillColor(white)
    cv.rect(0, 0, 1000, 1000, stroke=1, fill=1)
    cv.save()
    packet.seek(0)

    assert get_invalid_pages_with_message(packet) == ("", [])


def test_get_invalid_pages_black_bottom_corner(client):
    packet = io.BytesIO()
    cv = canvas.Canvas(packet, pagesize=A4)
    cv.setStrokeColor(white)
    cv.setFillColor(white)
    cv.rect(0, 0, 1000, 1000, stroke=1, fill=1)
    cv.setStrokeColor(black)
    cv.setFillColor(black)
    cv.rect(0, 0, 10, 10, stroke=1, fill=1)
    cv.save()
    packet.seek(0)

    assert get_invalid_pages_with_message(packet) == (
        "content-outside-printable-area",
        [1],
    )


def test_get_invalid_pages_grey_bottom_corner(client):
    packet = io.BytesIO()
    cv = canvas.Canvas(packet, pagesize=A4)
    cv.setStrokeColor(white)
    cv.setFillColor(white)
    cv.rect(0, 0, 1000, 1000, stroke=1, fill=1)
    cv.setStrokeColor(grey)
    cv.setFillColor(grey)
    cv.rect(0, 0, 10, 10, stroke=1, fill=1)
    cv.save()
    packet.seek(0)

    assert get_invalid_pages_with_message(packet) == (
        "content-outside-printable-area",
        [1],
    )


def test_get_invalid_pages_blank_multi_page(client):
    packet = io.BytesIO()
    cv = canvas.Canvas(packet, pagesize=A4)
    cv.setStrokeColor(white)
    cv.setFillColor(white)
    cv.rect(0, 0, 1000, 1000, stroke=1, fill=1)
    cv.showPage()
    cv.setStrokeColor(white)
    cv.setFillColor(white)
    cv.rect(0, 0, 1000, 1000, stroke=1, fill=1)
    cv.save()
    packet.seek(0)

    assert get_invalid_pages_with_message(packet) == ("", [])


@pytest.mark.parametrize(
    "x, y, expected_failed",
    [
        # four corners
        (0, 0, True),
        (0, 830, True),
        (590, 0, True),
        (590, 830, True),
        # middle of page
        (200, 400, False),
        # middle of right margin is not okay
        (590, 400, True),
        # middle of left margin is not okay
        (0, 400, True),
    ],
)
def test_get_invalid_pages_second_page(x, y, expected_failed, client):
    packet = io.BytesIO()
    cv = canvas.Canvas(packet, pagesize=A4)
    cv.setStrokeColor(white)
    cv.setFillColor(white)
    cv.rect(0, 0, 1000, 1000, stroke=1, fill=1)
    cv.showPage()
    cv.setStrokeColor(white)
    cv.setFillColor(white)
    cv.rect(0, 0, 1000, 1000, stroke=1, fill=1)
    cv.setStrokeColor(black)
    cv.setFillColor(black)

    cv.rect(x, y, 5, 5, stroke=1, fill=1)

    cv.save()
    packet.seek(0)

    if expected_failed:
        assert get_invalid_pages_with_message(packet) == (
            "content-outside-printable-area",
            [2],
        )
    else:
        assert get_invalid_pages_with_message(packet) == ("", [])


@pytest.mark.parametrize(
    "x, y, page, expected_message",
    [
        (0, 0, 1, ("content-outside-printable-area", [1])),
        (200, 200, 1, ("", [])),
        (590, 830, 1, ("content-outside-printable-area", [1])),
        (0, 200, 1, ("content-outside-printable-area", [1])),
        (0, 830, 1, ("content-outside-printable-area", [1])),
        (200, 0, 1, ("content-outside-printable-area", [1])),
        (590, 0, 1, ("content-outside-printable-area", [1])),
        (590, 200, 1, ("content-outside-printable-area", [1])),
        # under the citizen address block:
        (24.6 * mm, (297 - 90) * mm, 1, ("content-outside-printable-area", [1])),
        (24.6 * mm, (297 - 90) * mm, 2, ("", [])),  # Same place on page 2 should be ok
        (
            24.6 * mm,
            (297 - 39) * mm,
            1,
            ("content-outside-printable-area", [1]),
        ),  # under the logo
        (24.6 * mm, (297 - 39) * mm, 2, ("", [])),  # Same place on page 2 should be ok
        (0, 0, 2, ("content-outside-printable-area", [2])),
        (200, 200, 2, ("", [])),
        (590, 830, 2, ("content-outside-printable-area", [2])),
        (0, 200, 2, ("content-outside-printable-area", [2])),
        (0, 830, 2, ("content-outside-printable-area", [2])),
        (200, 0, 2, ("content-outside-printable-area", [2])),
        (590, 0, 2, ("content-outside-printable-area", [2])),
        (590, 200, 2, ("content-outside-printable-area", [2])),
    ],
)
def test_get_invalid_pages_black_text(client, x, y, page, expected_message):
    packet = io.BytesIO()
    cv = canvas.Canvas(packet, pagesize=A4)
    cv.setStrokeColor(white)
    cv.setFillColor(white)
    cv.rect(0, 0, 1000, 1000, stroke=1, fill=1)

    if page > 1:
        cv.showPage()

    cv.setStrokeColor(black)
    cv.setFillColor(black)
    cv.drawString(x, y, "This is a test string used to detect non white on a page")

    cv.save()
    packet.seek(0)
    assert get_invalid_pages_with_message(packet) == expected_message


def test_get_invalid_pages_address_margin(client):
    packet = io.BytesIO()
    cv = canvas.Canvas(packet, pagesize=A4)
    cv.setStrokeColor(white)
    cv.setFillColor(white)
    cv.rect(0, 0, 1000, 1000, stroke=1, fill=1)

    cv.setStrokeColor(black)
    cv.setFillColor(black)

    # This rectangle is the address margin, but 1 mm smaller on each side to account for aliasing
    cv.rect(121 * mm, 203 * mm, 4 * mm, 64 * mm, stroke=1, fill=1)

    cv.save()
    packet.seek(0)

    assert get_invalid_pages_with_message(packet) == (
        "content-outside-printable-area",
        [1],
    )


@pytest.mark.parametrize(
    "pdf",
    [a3_size, a5_size, landscape_oriented_page, landscape_rotated_page],
    ids=["a3_size", "a5_size", "landscape_oriented_page", "landscape_rotated_page"],
)
def test_get_invalid_pages_not_a4_oriented(pdf, client):
    message, invalid_pages = get_invalid_pages_with_message(BytesIO(pdf))
    assert message == "letter-not-a4-portrait-oriented"
    assert invalid_pages == [1]


def test_get_invalid_pages_is_ok_with_landscape_pages_that_are_rotated(client):
    # the page is orientated landscape but rotated 90º - all the text is sideways but it's still portrait
    message, invalid_pages = get_invalid_pages_with_message(BytesIO(portrait_rotated_page))
    assert message == ""
    assert invalid_pages == []


def test_get_invalid_pages_ignores_notify_tags_on_page_1(client):
    message, invalid_pages = get_invalid_pages_with_message(BytesIO(already_has_notify_tag))
    assert message == ""
    assert invalid_pages == []


def test_get_invalid_pages_rejects_later_pages_with_notify_tags(client):
    message, invalid_pages = get_invalid_pages_with_message(BytesIO(notify_tags_on_page_2_and_4))
    assert message == "notify-tag-found-in-content"
    assert invalid_pages == [2, 4]


def test_overlay_template_png_for_page_not_encoded(client, auth_header):
    response = client.post(
        url_for("precompiled_blueprint.overlay_template_png_for_page", is_first_page="true"),
        data=None,
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    ["params", "expected_first_page"],
    [
        ({"page_number": "1"}, True),
        ({"page_number": "2"}, False),
        ({"is_first_page": "true"}, True),
        ({"is_first_page": "anything_else"}, False),
        ({"is_first_page": ""}, False),
        ({"page_number": 1, "is_first_page": "true"}, True),  # is_first_page takes priority
        ({"page_number": "1", "is_an_attachment": True}, False),  # attachment doesn't mandate address block
    ],
)
def test_overlay_template_png_for_page_checks_if_first_page(client, auth_header, mocker, params, expected_first_page):
    mock_png_from_pdf = mocker.patch("app.precompiled.png_from_pdf", return_value=BytesIO(b"\x00"))
    mock_colour = mocker.patch("app.precompiled._colour_no_print_areas_of_single_page_pdf_in_red")

    response = client.post(
        url_for("precompiled_blueprint.overlay_template_png_for_page", **params),
        data=b"1234",
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 200
    mock_colour.assert_called_once_with(ANY, is_first_page=expected_first_page)
    mock_png_from_pdf.assert_called_once_with(mock_colour.return_value, page_number=1)


def test_overlay_template_png_for_page_errors_if_not_a_pdf(client, auth_header):
    resp = client.post(
        url_for("precompiled_blueprint.overlay_template_png_for_page", is_first_page="true"),
        data=not_pdf,
        headers=auth_header,
    )
    assert resp.status_code == 400


def test_overlay_template_png_for_page_errors_if_multi_page_pdf(client, auth_header):
    resp = client.post(
        url_for("precompiled_blueprint.overlay_template_png_for_page", is_first_page="true"),
        data=multi_page_pdf,
        headers=auth_header,
    )
    assert resp.status_code == 400


def test_overlay_template_pdf_errors_if_no_content(client, auth_header):
    resp = client.post(url_for("precompiled_blueprint.overlay_template_pdf"), headers=auth_header)
    assert resp.status_code == 400
    assert resp.json["message"] == "no data received in POST"


def test_overlay_template_pdf_errors_if_request_args_provided(client, auth_header):
    resp = client.post(
        url_for("precompiled_blueprint.overlay_template_pdf", is_first_page=True),
        data=b"1234",
        headers=auth_header,
    )
    assert resp.status_code == 400
    assert "Did not expect any args" in resp.json["message"]


def test_overlay_template_pdf_colours_pages_in_red(client, auth_header, mocker):
    mock_colour = mocker.patch("app.precompiled._colour_no_print_areas_of_page_in_red")
    resp = client.post(
        url_for("precompiled_blueprint.overlay_template_pdf"),
        data=multi_page_pdf,
        headers=auth_header,
    )
    assert resp.status_code == 200

    assert mock_colour.call_args_list == [call(ANY, is_first_page=True)] + [call(ANY, is_first_page=False)] * 9


def test_precompiled_sanitise_pdf_without_notify_tag(client, auth_header):
    assert not is_notify_tag_present(BytesIO(blank_with_address))

    response = client.post(
        url_for("precompiled_blueprint.sanitise_precompiled_letter"),
        data=blank_with_address,
        headers={"Content-type": "application/json", **auth_header},
    )
    assert response.status_code == 200
    assert response.json == {
        "message": None,
        "file": ANY,
        "page_count": 1,
        "recipient_address": "Queen Elizabeth\nBuckingham Palace\nLondon\nSW1 1AA",
        "invalid_pages": None,
    }

    pdf = BytesIO(base64.b64decode(response.json["file"].encode()))
    assert is_notify_tag_present(pdf)
    assert extract_address_block(pdf).normalised == ("Queen Elizabeth\nBuckingham Palace\nLondon\nSW1 1AA")


def test_precompiled_sanitise_pdf_for_an_attachment(client, auth_header, mocker):
    response = client.post(
        url_for("precompiled_blueprint.sanitise_precompiled_letter") + "?is_an_attachment=true",
        data=blank_with_address,
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 200
    assert response.json == {
        "message": None,
        "file": ANY,
        "page_count": 1,
        "recipient_address": None,
        "invalid_pages": None,
    }

    pdf = BytesIO(base64.b64decode(response.json["file"].encode()))
    assert not is_notify_tag_present(pdf)


def test_precompiled_sanitise_pdf_with_notify_tag(client, auth_header):
    assert is_notify_tag_present(BytesIO(notify_tag_on_first_page))

    response = client.post(
        url_for("precompiled_blueprint.sanitise_precompiled_letter"),
        data=notify_tag_on_first_page,
        headers={"Content-type": "application/json", **auth_header},
    )
    assert response.status_code == 200
    assert response.json == {
        "message": None,
        "file": ANY,
        "page_count": 1,
        "recipient_address": "Queen Elizabeth\nBuckingham Palace\nLondon\nSW1 1AA",
        "invalid_pages": None,
    }

    pdf = BytesIO(base64.b64decode(response.json["file"].encode()))
    assert is_notify_tag_present(pdf)


@pytest.mark.parametrize(
    "query_string",
    (
        "",
        "?is_an_attachment=true",
    ),
)
def test_precompiled_sanitise_pdf_with_colour_outside_boundaries_returns_400(client, auth_header, query_string):
    response = client.post(
        url_for("precompiled_blueprint.sanitise_precompiled_letter") + query_string,
        data=no_colour,
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 400
    assert response.json == {
        "page_count": 2,
        "recipient_address": None,
        "message": "content-outside-printable-area",
        "invalid_pages": [1, 2],
        "file": None,
    }


def test_precompiled_sanitise_pdf_with_colour_in_address_margin_returns_400(client, auth_header, mocker):
    response = client.post(
        url_for("precompiled_blueprint.sanitise_precompiled_letter"),
        data=address_margin,
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 400
    assert response.json == {
        "page_count": 1,
        "recipient_address": None,
        "message": "content-outside-printable-area",
        "invalid_pages": [1],
        "file": None,
    }


def test_precompiled_sanitise_pdf_with_colour_in_address_margin_ok_for_attachments(client, auth_header, mocker):
    response = client.post(
        url_for("precompiled_blueprint.sanitise_precompiled_letter") + "?is_an_attachment=true",
        data=address_margin,
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 200
    assert response.json == {
        "message": None,
        "file": ANY,
        "page_count": 1,
        "recipient_address": None,
        "invalid_pages": None,
    }


@pytest.mark.parametrize(
    "is_an_attachment",
    (
        "",
        "?is_an_attachment=true",
    ),
)
def test_precompiled_sanitise_pdf_that_is_too_long_returns_400(client, auth_header, mocker, is_an_attachment):
    mocker.patch("app.precompiled.pdf_page_count", return_value=11)
    mocker.patch("app.precompiled.is_letter_too_long", return_value=True)
    response = client.post(
        url_for("precompiled_blueprint.sanitise_precompiled_letter") + is_an_attachment,
        data=address_margin,
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 400
    assert response.json == {
        "page_count": 11,
        "recipient_address": None,
        "message": "letter-too-long",
        "invalid_pages": None,
        "file": None,
    }


@pytest.mark.parametrize(
    "is_an_attachment",
    (
        "",
        "?is_an_attachment=true",
    ),
)
@pytest.mark.parametrize("exception", [KeyError("/Resources"), PdfReadError("error"), Exception()])
def test_precompiled_sanitise_pdf_that_with_an_unknown_error_raised_returns_400(
    client, auth_header, mocker, exception, is_an_attachment
):
    mocker.patch("app.precompiled.get_invalid_pages_with_message", side_effect=exception)

    response = client.post(
        url_for("precompiled_blueprint.sanitise_precompiled_letter") + is_an_attachment,
        data=address_margin,
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 400
    assert response.json == {
        "page_count": None,
        "recipient_address": None,
        "message": "unable-to-read-the-file",
        "invalid_pages": None,
        "file": None,
    }


def test_sanitise_precompiled_letter_with_missing_address_returns_400(client, auth_header):
    response = client.post(
        url_for("precompiled_blueprint.sanitise_precompiled_letter"),
        data=blank_page,
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 400
    assert response.json == {
        "page_count": 1,
        "recipient_address": None,
        "message": "address-is-empty",
        "invalid_pages": [1],
        "file": None,
    }


@pytest.mark.parametrize("file", (blank_page, bad_postcode))
def test_sanitise_precompiled_letter_with_missing_or_wrong_address_ok_for_an_attachment(client, auth_header, file):
    response = client.post(
        url_for("precompiled_blueprint.sanitise_precompiled_letter") + "?is_an_attachment=true",
        data=file,
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 200
    assert response.json == {
        "message": None,
        "file": ANY,
        "page_count": 1,
        "recipient_address": None,
        "invalid_pages": None,
    }


@pytest.mark.parametrize(
    "file, allow_international, expected_error_message",
    (
        (bad_postcode, "", "not-a-real-uk-postcode"),
        (bad_postcode, "true", "not-a-real-uk-postcode-or-country"),
        (non_uk_address, "", "cant-send-international-letters"),
        (blank_with_2_line_address, "", "not-enough-address-lines"),
        (blank_with_8_line_address, "", "too-many-address-lines"),
        (invalid_address_character, "", "invalid-char-in-address"),
        (no_fixed_abode, "", "no-fixed-abode-address"),
        (international_bfpo, "", "has-country-for-bfpo-address"),
    ),
)
def test_sanitise_precompiled_letter_with_bad_address_returns_400(
    client,
    auth_header,
    file,
    allow_international,
    expected_error_message,
):
    response = client.post(
        url_for(
            "precompiled_blueprint.sanitise_precompiled_letter",
            allow_international_letters=allow_international,
        ),
        data=file,
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.status_code == 400
    assert response.json == {
        "page_count": 1,
        "recipient_address": None,
        "message": expected_error_message,
        "invalid_pages": [1],
        "file": None,
    }


@pytest.mark.parametrize(
    "file",
    [
        valid_letter,
        pdf_with_no_metadata,
    ],
    ids=["valid_letter", "pdf_with_no_metadata"],
)
def test_log_metadata_for_letter(
    client,
    file,
    mocker,
):
    logger = mocker.patch("app.precompiled.current_app.logger.info")
    log_metadata_for_letter(BytesIO(file), "filename")
    assert logger.called


def test_is_notify_tag_present_finds_notify_tag():
    assert is_notify_tag_present(BytesIO(notify_tag_on_first_page)) is True


def test_is_notify_tag_present():
    assert is_notify_tag_present(BytesIO(blank_page)) is False


def test_is_notify_tag_calls_extract_with_wider_numbers(mocker):
    mock_extract = mocker.patch("app.precompiled._extract_text_from_first_page_of_pdf")
    pdf = MagicMock()

    is_notify_tag_present(pdf)

    mock_extract.assert_called_once_with(pdf, fitz.Rect(0.0, 0.0, 15.191 * mm, 6.149 * mm))


@pytest.mark.parametrize(
    ["pdf_data", "address_snippet"],
    [(example_dwp_pdf, "testington"), (valid_letter, "buckingham palace")],
    ids=["example_dwp_pdf", "valid_letter"],
)
def test_rewrite_address_block_end_to_end(pdf_data, address_snippet):
    new_pdf, address = rewrite_address_block(
        BytesIO(pdf_data),
        page_count=1,
        allow_international_letters=False,
        filename="file",
    )
    assert address == extract_address_block(new_pdf).raw_address
    assert address_snippet in address.lower()


def test_extract_address_block():
    assert extract_address_block(BytesIO(example_dwp_pdf)).raw_address == "\n".join(
        [
            "MR J DOE",
            "13 TEST LANE",
            "TESTINGTON",
            "TS7 1NG",
        ]
    )


def test_extract_address_block_handles_address_with_ligatures_in_different_fonts(client, caplog):
    # we've seen some cases where addresses can sometimes be split into too many lines - this test is incorrect
    # in that "quick maffs defied" should be on one line, but we're documenting this before fixing so we can understand
    # impacts on other addresses before fixing the algorithm
    assert extract_address_block(BytesIO(address_with_unusual_coordinates)).raw_address == "\n".join(
        [
            "First line",
            # these three _should_ be on the same line
            "quick",
            "maffs",  # note that the ﬀ ligature here has been converted into two f characters
            "defied",
            "SE1 1AA",
        ]
    )
    # at least make sure we're logging this for now
    assert "Address extraction different between y2 and get_text" in caplog.messages


def test_add_address_to_precompiled_letter_puts_address_on_page():
    address = "\n".join(
        [
            "Queen Elizabeth,",
            "Buckingham Palace",
            "London",
            "SW1 1AA",
        ]
    )
    ret = add_address_to_precompiled_letter(BytesIO(blank_page), address)
    assert extract_address_block(ret).raw_address == address


@pytest.mark.parametrize(
    "pdf,expected_address",
    [
        pytest.param(
            example_dwp_pdf,
            "MR J DOE13 TEST LANETESTINGTONTS7 1NG",
            id="example_dwp_pdf",
        ),
        pytest.param(
            hackney_sample,
            "se alvindgky n egutnceyshktvrai1 Hillman StreetLondonE8 1DY",
            id="hackney_sample",
        ),
    ],
)
def test_redact_precompiled_letter_address_block_redacts_address_block(pdf, expected_address):
    address = extract_address_block(BytesIO(pdf))
    raw_address = address.raw_address.replace("\n", "")
    assert raw_address == expected_address
    new_pdf = redact_precompiled_letter_address_block(BytesIO(example_dwp_pdf))
    assert extract_address_block(new_pdf).raw_address == ""


def test_redact_address_block_preserves_addresses_elsewhere_on_page():
    address = extract_address_block(BytesIO(repeated_address_block))
    assert address.raw_address != ""  # check something is there before we redact

    new_pdf = redact_precompiled_letter_address_block(
        BytesIO(repeated_address_block),
    )
    assert extract_address_block(new_pdf).raw_address == ""

    doc = fitz.open("pdf", new_pdf)
    new_page_text = doc[0].get_text()
    assert address.raw_address in new_page_text


def test_redact_precompiled_letter_address_block_only_touches_first_page():
    address = extract_address_block(BytesIO(address_block_repeated_on_second_page))
    assert address.raw_address != ""  # check something is there before we redact

    doc = fitz.open("pdf", address_block_repeated_on_second_page)
    second_page_text = doc[1].get_text()

    new_pdf = redact_precompiled_letter_address_block(
        BytesIO(address_block_repeated_on_second_page),
    )
    assert extract_address_block(new_pdf).raw_address == ""

    doc = fitz.open("pdf", new_pdf)
    new_second_page_text = doc[1].get_text()

    assert len(doc) == 2
    assert new_second_page_text == second_page_text


def test_sanitise_file_contents_on_pdf_with_no_resources_on_one_of_the_pages_content_outside_bounds(
    client, auth_header
):
    """
    This tests to make sure that pypdf doesn't raise a KeyError when sanitising a PDF that is missing /Resources
    on one of the pages. Resources should be inferrer from one of the parent/previous pages in this case.

    The PDF under test was provided by one of our services when they encountered the error. Ideally the PDF would
    be valid and return a successful response, but some test that this returns a correct response is at least better
    than this call raising an error/500."""
    response = client.post(
        "/precompiled/sanitise",
        data=no_resources_on_last_page,
        headers={"Content-type": "application/json", **auth_header},
    )

    assert response.json == {
        "recipient_address": None,
        "page_count": 3,
        "message": "content-outside-printable-area",
        "invalid_pages": [1],
        "file": None,
    }


@pytest.mark.parametrize(
    "orig_filesize, new_filesize, expected_lvl, expected_msg",
    [
        (1_000_000, 1_200_000, None, None),
        (
            1_024_000,
            1_638_400,
            logging.WARNING,
            (
                "template-preview post-sanitise filesize too big: filename=foo.pdf, "
                "orig_size=1000KiB, new_size=1600KiB, pct_bigger=60%"
            ),
        ),
        (
            1_024_000,
            2_150_400,
            logging.ERROR,
            (
                "template-preview post-sanitise filesize too big: filename=foo.pdf, "
                "orig_size=1000KiB, new_size=2100KiB, over max_filesize=2MiB"
            ),
        ),
        (
            1_843_200,
            2_150_400,
            logging.ERROR,
            (
                "template-preview post-sanitise filesize too big: filename=foo.pdf, "
                "orig_size=1800KiB, new_size=2100KiB, over max_filesize=2MiB"
            ),
        ),
    ],
)
def test_warn_if_filesize_has_grown(client, caplog, orig_filesize, new_filesize, expected_lvl, expected_msg):
    with caplog.at_level(logging.INFO):
        _warn_if_filesize_has_grown(orig_filesize=orig_filesize, new_filesize=new_filesize, filename="foo.pdf")

    if not expected_msg:
        assert caplog.records == []
    else:
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == expected_lvl
        assert caplog.records[0].message == expected_msg
