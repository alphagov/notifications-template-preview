import base64
import io
import re
import logging
from io import BytesIO
from unittest.mock import MagicMock, ANY, call

import PyPDF2
import pytest
from flask import url_for
from pdfrw import PdfReader
from reportlab.lib.colors import white, black, grey
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from app.precompiled import (
    NotifyCanvas,
    add_address_to_precompiled_letter,
    add_notify_tag_to_letter,
    escape_special_characters_for_regex,
    extract_address_block,
    get_invalid_pages_with_message,
    handle_irregular_whitespace_characters,
    is_notify_tag_present,
    redact_precompiled_letter_address_block,
    rewrite_address_block
)

from tests.pdf_consts import (
    blank_with_address,
    not_pdf,
    a3_size,
    a5_size,
    landscape_oriented_page,
    landscape_rotated_page,
    address_block_repeated_on_second_page,
    address_margin,
    no_colour,
    example_dwp_pdf,
    repeated_address_block,
    multi_page_pdf,
    blank_page,
    portrait_rotated_page,
    valid_letter,
)


@pytest.mark.parametrize('endpoint, kwargs', [
    ('precompiled_blueprint.sanitise_precompiled_letter', {}),
    ('precompiled_blueprint.overlay_template_png_for_page', {'is_first_page': 'true'}),
    ('precompiled_blueprint.overlay_template_pdf', {}),
])
@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Token not-the-actual-token'}])
def test_endpoints_rejects_if_not_authenticated(client, headers, endpoint, kwargs):
    resp = client.post(
        url_for(endpoint, **kwargs),
        data={},
        headers=headers
    )
    assert resp.status_code == 401


def test_add_notify_tag_to_letter(mocker):
    pdf_original = PyPDF2.PdfFileReader(BytesIO(multi_page_pdf))

    assert 'NOTIFY' not in pdf_original.getPage(0).extractText()

    pdf_page = add_notify_tag_to_letter(BytesIO(multi_page_pdf))

    pdf_new = PyPDF2.PdfFileReader(BytesIO(pdf_page.read()))

    assert pdf_new.numPages == pdf_original.numPages
    assert pdf_new.getPage(0).extractText() != pdf_original.getPage(0).extractText()
    assert 'NOTIFY' in pdf_new.getPage(0).extractText()
    assert pdf_new.getPage(1).extractText() == pdf_original.getPage(1).extractText()
    assert pdf_new.getPage(2).extractText() == pdf_original.getPage(2).extractText()
    assert pdf_new.getPage(3).extractText() == pdf_original.getPage(3).extractText()


def test_add_notify_tag_to_letter_correct_margins(mocker):
    pdf_original = PyPDF2.PdfFileReader(BytesIO(multi_page_pdf))

    can = NotifyCanvas(white)
    can.drawString = MagicMock(return_value=3)

    mocker.patch('app.precompiled.NotifyCanvas', return_value=can)

    # It fails because we are mocking but by that time the drawString method has been called so just carry on
    try:
        add_notify_tag_to_letter(BytesIO(multi_page_pdf))
    except Exception:
        pass

    mm_from_top_of_the_page = 4.3
    mm_from_left_of_page = 3.44

    x = mm_from_left_of_page * mm

    # page.mediaBox[3] Media box is an array with the four corners of the page
    # We want height so can use that co-ordinate which is located in [3]
    # The lets take away the margin and the ont size
    y = float(pdf_original.getPage(0).mediaBox[3]) - (float(mm_from_top_of_the_page * mm + 6 - 1.75))

    assert len(can.drawString.call_args_list) == 1
    positional_args = can.drawString.call_args[0]
    assert len(positional_args) == 3
    assert positional_args[0] == pytest.approx(x, 0.01)
    assert positional_args[1] == y
    assert positional_args[2] == "NOTIFY"


def test_get_invalid_pages_blank_page():
    packet = io.BytesIO()
    cv = canvas.Canvas(packet, pagesize=A4)
    cv.setStrokeColor(white)
    cv.setFillColor(white)
    cv.rect(0, 0, 1000, 1000, stroke=1, fill=1)
    cv.save()
    packet.seek(0)

    assert get_invalid_pages_with_message(packet) == ("", [])


def test_get_invalid_pages_black_bottom_corner():
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

    assert get_invalid_pages_with_message(packet) == ('content-outside-printable-area', [1])


def test_get_invalid_pages_grey_bottom_corner():
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

    assert get_invalid_pages_with_message(packet) == ('content-outside-printable-area', [1])


def test_get_invalid_pages_blank_multi_page():
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


@pytest.mark.parametrize('x, y, expected_failed', [
    # four corners
    (0, 0, True), (0, 830, True), (590, 0, True), (590, 830, True),
    # middle of page
    (200, 400, False),
    # middle of right margin is not okay
    (590, 400, True),
    # middle of left margin is not okay
    (0, 400, True)
])
def test_get_invalid_pages_second_page(x, y, expected_failed):
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
        assert get_invalid_pages_with_message(packet) == ('content-outside-printable-area', [2])
    else:
        assert get_invalid_pages_with_message(packet) == ('', [])


@pytest.mark.parametrize('x, y, page, expected_message', [
    (0, 0, 1, ('content-outside-printable-area', [1])),
    (200, 200, 1, ('', [])),
    (590, 830, 1, ('content-outside-printable-area', [1])),
    (0, 200, 1, ('content-outside-printable-area', [1])),
    (0, 830, 1, ('content-outside-printable-area', [1])),
    (200, 0, 1, ('content-outside-printable-area', [1])),
    (590, 0, 1, ('content-outside-printable-area', [1])),
    (590, 200, 1, ('content-outside-printable-area', [1])),
    # under the citizen address block:
    (24.6 * mm, (297 - 90) * mm, 1, ('content-outside-printable-area', [1])),
    (24.6 * mm, (297 - 90) * mm, 2, ('', [])),  # Same place on page 2 should be ok
    (24.6 * mm, (297 - 39) * mm, 1, ('content-outside-printable-area', [1])),  # under the logo
    (24.6 * mm, (297 - 39) * mm, 2, ('', [])),  # Same place on page 2 should be ok
    (0, 0, 2, ('content-outside-printable-area', [2])),
    (200, 200, 2, ('', [])),
    (590, 830, 2, ('content-outside-printable-area', [2])),
    (0, 200, 2, ('content-outside-printable-area', [2])),
    (0, 830, 2, ('content-outside-printable-area', [2])),
    (200, 0, 2, ('content-outside-printable-area', [2])),
    (590, 0, 2, ('content-outside-printable-area', [2])),
    (590, 200, 2, ('content-outside-printable-area', [2])),
])
def test_get_invalid_pages_black_text(x, y, page, expected_message):
    packet = io.BytesIO()
    cv = canvas.Canvas(packet, pagesize=A4)
    cv.setStrokeColor(white)
    cv.setFillColor(white)
    cv.rect(0, 0, 1000, 1000, stroke=1, fill=1)

    if page > 1:
        cv.showPage()

    cv.setStrokeColor(black)
    cv.setFillColor(black)
    cv.setFont('Arial', 6)
    cv.drawString(x, y, 'This is a test string used to detect non white on a page')

    cv.save()
    packet.seek(0)
    assert get_invalid_pages_with_message(packet) == expected_message


def test_get_invalid_pages_address_margin():
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

    assert get_invalid_pages_with_message(packet) == ('content-outside-printable-area', [1])


@pytest.mark.parametrize('pdf', [
    a3_size, a5_size, landscape_oriented_page, landscape_rotated_page
], ids=['a3_size', 'a5_size', 'landscape_oriented_page', 'landscape_rotated_page']
)
def test_get_invalid_pages_not_a4_oriented(pdf):
    message, invalid_pages = get_invalid_pages_with_message(BytesIO(pdf))
    assert message == 'letter-not-a4-portrait-oriented'
    assert invalid_pages == [1]


def test_get_invalid_pages_is_ok_with_landscape_pages_that_are_rotated():
    # the page is orientated landscape but rotated 90º - all the text is sideways but it's still portrait
    message, invalid_pages = get_invalid_pages_with_message(BytesIO(portrait_rotated_page))
    assert message == ''
    assert invalid_pages == []


def test_overlay_template_png_for_page_not_encoded(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.overlay_template_png_for_page', is_first_page='true'),
        data=None,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 400


@pytest.mark.parametrize(['params', 'expected_first_page'], [
    ({'page_number': '1'}, True),
    ({'page_number': '2'}, False),
    ({'is_first_page': 'true'}, True),
    ({'is_first_page': 'anything_else'}, False),
    ({'is_first_page': ''}, False),
    ({'page_number': 1, 'is_first_page': 'true'}, True),  # is_first_page takes priority
])
def test_overlay_template_png_for_page_checks_if_first_page(client, auth_header, mocker, params, expected_first_page):

    mock_png_from_pdf = mocker.patch('app.precompiled.png_from_pdf', return_value=BytesIO(b'\x00'))
    mock_colour = mocker.patch('app.precompiled._colour_no_print_areas_of_single_page_pdf_in_red')

    response = client.post(
        url_for('precompiled_blueprint.overlay_template_png_for_page', **params),
        data=b'1234',
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    mock_colour.assert_called_once_with(ANY, is_first_page=expected_first_page)
    mock_png_from_pdf.assert_called_once_with(mock_colour.return_value, page_number=1)


def test_overlay_template_png_for_page_errors_if_not_a_pdf(client, auth_header):
    resp = client.post(
        url_for('precompiled_blueprint.overlay_template_png_for_page', is_first_page='true'),
        data=not_pdf,
        headers=auth_header
    )
    assert resp.status_code == 400


def test_overlay_template_png_for_page_errors_if_multi_page_pdf(client, auth_header):
    resp = client.post(
        url_for('precompiled_blueprint.overlay_template_png_for_page', is_first_page='true'),
        data=multi_page_pdf,
        headers=auth_header
    )
    assert resp.status_code == 400


def test_overlay_template_pdf_errors_if_no_content(client, auth_header):
    resp = client.post(
        url_for('precompiled_blueprint.overlay_template_pdf'),
        headers=auth_header
    )
    assert resp.status_code == 400
    assert resp.json['message'] == 'no data received in POST'


def test_overlay_template_pdf_errors_if_request_args_provided(client, auth_header):
    resp = client.post(
        url_for('precompiled_blueprint.overlay_template_pdf', is_first_page=True),
        data=b'1234',
        headers=auth_header
    )
    assert resp.status_code == 400
    assert 'Did not expect any args' in resp.json['message']


def test_overlay_template_pdf_colours_pages_in_red(client, auth_header, mocker):
    mock_colour = mocker.patch('app.precompiled._colour_no_print_areas_of_page_in_red')
    resp = client.post(
        url_for('precompiled_blueprint.overlay_template_pdf'),
        data=multi_page_pdf,
        headers=auth_header
    )
    assert resp.status_code == 200

    assert mock_colour.call_args_list == [call(ANY, is_first_page=True)] + [call(ANY, is_first_page=False)] * 9


def test_precompiled_sanitise_pdf_without_notify_tag(client, auth_header):
    assert not is_notify_tag_present(BytesIO(blank_with_address))

    response = client.post(
        url_for('precompiled_blueprint.sanitise_precompiled_letter'),
        data=blank_with_address,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )
    assert response.status_code == 200
    assert response.json == {
        "message": None,
        "file": ANY,
        "page_count": 1,
        "recipient_address": "Bugs Bunny,\nLooney Town\nLT10 0OP",
        "invalid_pages": None,
        'redaction_failed_message': None
    }

    pdf = BytesIO(base64.b64decode(response.json["file"].encode()))
    assert is_notify_tag_present(pdf)
    assert extract_address_block(pdf) == "Bugs Bunny,\nLooney Town\nLT10 0OP"


def test_precompiled_sanitise_pdf_with_colour_outside_boundaries_returns_400(client, auth_header):
    response = client.post(
        url_for('precompiled_blueprint.sanitise_precompiled_letter'),
        data=no_colour,
        headers={'Content-type': 'application/json', **auth_header}
    )

    assert response.status_code == 400
    assert response.json == {
        "page_count": 2,
        "recipient_address": None,
        "message": 'content-outside-printable-area',
        "invalid_pages": [1, 2],
        "file": None
    }


def test_precompiled_sanitise_pdf_with_colour_in_address_margin_returns_400(client, auth_header, mocker):
    response = client.post(
        url_for('precompiled_blueprint.sanitise_precompiled_letter'),
        data=address_margin,
        headers={'Content-type': 'application/json', **auth_header}
    )

    assert response.status_code == 400
    assert response.json == {
        "page_count": 1,
        "recipient_address": None,
        "message": 'content-outside-printable-area',
        "invalid_pages": [1],
        "file": None
    }


def test_precompiled_sanitise_pdf_that_is_too_long_returns_400(client, auth_header, mocker):
    mocker.patch('app.precompiled.pdf_page_count', return_value=11)
    mocker.patch('app.precompiled.is_letter_too_long', return_value=True)
    response = client.post(
        url_for('precompiled_blueprint.sanitise_precompiled_letter'),
        data=address_margin,
        headers={'Content-type': 'application/json', **auth_header}
    )

    assert response.status_code == 400
    assert response.json == {
        "page_count": 11,
        "recipient_address": None,
        "message": "letter-too-long",
        "invalid_pages": None,
        "file": None
    }


def test_precompiled_sanitise_pdf_that_with_an_unknown_error_raised_returns_400(client, auth_header, mocker):
    mocker.patch('app.precompiled.get_invalid_pages_with_message', side_effect=Exception())

    response = client.post(
        url_for('precompiled_blueprint.sanitise_precompiled_letter'),
        data=address_margin,
        headers={'Content-type': 'application/json', **auth_header}
    )

    assert response.status_code == 400
    assert response.json == {
        "page_count": None,
        "recipient_address": None,
        "message": 'unable-to-read-the-file',
        "invalid_pages": None,
        "file": None
    }


def test_precompiled_for_letter_missing_address_returns_400(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.sanitise_precompiled_letter'),
        data=blank_page,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 400
    assert response.json == {
        "page_count": 1,
        "recipient_address": None,
        "message": 'address-is-empty',
        "invalid_pages": [1],
        "file": None
    }


def test_is_notify_tag_present_finds_notify_tag():
    assert is_notify_tag_present(BytesIO(example_dwp_pdf)) is True


def test_is_notify_tag_present():
    assert is_notify_tag_present(BytesIO(blank_page)) is False


def test_is_notify_tag_calls_extract_with_wider_numbers(mocker):
    mock_extract = mocker.patch('app.precompiled._extract_text_from_pdf')
    pdf = MagicMock()

    is_notify_tag_present(pdf)

    mock_extract.assert_called_once_with(
        ANY,
        x1=pytest.approx(6.8031496),
        y1=pytest.approx(3.685039),
        x2=pytest.approx(58.149606),
        y2=pytest.approx(26.692913),
    )


@pytest.mark.parametrize(['pdf_data', 'address_snippet'], [
    (example_dwp_pdf, 'testington'),
    (valid_letter, 'fakington')
], ids=['example_dwp_pdf', 'valid_letter'])
def test_rewrite_address_block_end_to_end(mocker, pdf_data, address_snippet):
    new_pdf, address, message = rewrite_address_block(BytesIO(pdf_data))
    assert not message
    assert address == extract_address_block(new_pdf)
    assert address_snippet in address.lower()


def test_extract_address_block():
    assert extract_address_block(BytesIO(example_dwp_pdf)) == '\n'.join([
        'MR J DOE',
        '13 TEST LANE',
        'TESTINGTON',
        'TE57 1NG',
    ])


def test_add_address_to_precompiled_letter_puts_address_on_page():
    address = '\n'.join([
        'Bugs Bunny,',
        'Looney Town',
        'LT10 0OP',
    ])
    ret = add_address_to_precompiled_letter(BytesIO(blank_page), address)
    assert extract_address_block(ret) == address


def test_redact_precompiled_letter_address_block_redacts_address_block():
    address = extract_address_block(BytesIO(example_dwp_pdf))
    address_regex = address.replace("\n", "")
    assert address_regex == 'MR J DOE13 TEST LANETESTINGTONTE57 1NG'
    new_pdf, message = redact_precompiled_letter_address_block(BytesIO(example_dwp_pdf), address_regex)
    assert not message
    assert extract_address_block(BytesIO(new_pdf)) == ""


def test_redact_precompiled_letter_address_block_address_repeated_on_2nd_page():
    address = extract_address_block(BytesIO(address_block_repeated_on_second_page))
    address_regex = address.replace("\n", "")
    expected = 'PEA NUTTPEANUT BUTTER JELLY COURTTOAST WHARFALL DAY TREAT STREETTASTY TOWNSNACKSHIRETT7 PBJ'
    assert address_regex == expected

    new_pdf, message = redact_precompiled_letter_address_block(
        BytesIO(address_block_repeated_on_second_page), address_regex
    )
    assert not message
    assert extract_address_block(BytesIO(new_pdf)) == ""

    document = PdfReader(BytesIO(new_pdf))
    assert len(document.pages) == 2


def test_redact_precompiled_letter_address_block_sends_log_message_if_no_matches(caplog):

    caplog.set_level(logging.WARNING)
    address_regex = 'MR J DOE13 UNMATCHED LANETESTINGTONTE57 1NG'
    new_pdf, message = redact_precompiled_letter_address_block(BytesIO(example_dwp_pdf), address_regex)
    assert message == "No matches for address block during redaction procedure"
    expected_message = [(
        'flask.app',
        logging.WARNING,
        "No matches for address block during redaction procedure"
    )]
    assert caplog.record_tuples == expected_message
    assert extract_address_block(BytesIO(new_pdf)) == 'MR J DOE\n13 TEST LANE\nTESTINGTON\nTE57 1NG'


def test_redact_precompiled_letter_address_block_sends_log_message_if_multiple_matches(caplog):

    caplog.set_level(logging.WARNING)
    address_regex = 'PEA NUTT4 JELLY COURTPEANUT BUTTER JELLY WHARFTOAST STREETALLDAYSNACKSHIRESNACKISTANSN1 PBJ'
    new_pdf, message = redact_precompiled_letter_address_block(BytesIO(repeated_address_block), address_regex)
    assert message == "More than one match for address block during redaction procedure"
    expected_message = [(
        'flask.app',
        logging.WARNING,
        "More than one match for address block during redaction procedure"
    )]
    assert caplog.record_tuples == expected_message
    exp_mes = 'PEA NUTT\n4 JELLY COURT\nPEANUT BUTTER JELLY WHARF\nTOAST STREET\nALLDAYSNACKSHIRE\nSNACKISTAN\nSN1 PBJ'
    assert extract_address_block(BytesIO(new_pdf)) == exp_mes


def test_escape_special_characters_for_regex_matches_string():
    string = 'PEA NUTT + MIKO JELLY4 JELLY COURT (PEANUT BUTTER JELLY WHARF)TOAST STR.ALLDAYSNACKSHIRESNACKISTANSN1 PBJ'
    escaped_string = escape_special_characters_for_regex(string)
    regex = re.compile(escaped_string)
    assert regex.findall(string)


@pytest.mark.parametrize("irregular_address", [
    'MR J DOE 13 TEST LANETESTINGTONTE57 1NG',
    'MR J  DOE13 TEST LANETESTINGTONTE57 1NG',
    'MR J DOE13 TEST LANETESTINGTON  TE57 1NG',
    'MR J DOE13 TEST LANETESTINGTONTE57 1NG',
])
def test_handle_irregular_whitespace_characters(irregular_address):
    extracted_address = 'MR J DOE\n13 TEST LANE\nTESTINGTON\nTE57 1NG'
    regex_ready = handle_irregular_whitespace_characters(extracted_address)
    regex = re.compile(regex_ready)
    assert regex.findall(irregular_address)
