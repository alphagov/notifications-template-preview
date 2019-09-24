import base64
import io
import re
import json
import logging
import uuid
from io import BytesIO
from unittest.mock import MagicMock, ANY

import PyPDF2
import pytest
from flask import url_for
from pdfrw import PdfReader
from reportlab.lib.colors import white, black, grey
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfgen.canvas import Canvas

from app.precompiled import (
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
    a3_size,
    a5_size,
    address_block_repeated_on_second_page,
    address_margin,
    blank_page,
    example_dwp_pdf,
    multi_page_pdf,
    no_colour,
    not_pdf,
    one_page_pdf,
    landscape_oriented_page,
    landscape_rotated_page,
    portrait_rotated_page,
    repeated_address_block
)


@pytest.fixture(autouse=True)
def _client(client):
    # every test should have a client instantiated so that log messages don't crash
    pass


def test_precompiled_validation_endpoint_blank_pdf(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document'),
        data=blank_page,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    json_data = json.loads(response.get_data())
    assert json_data['result'] is True


def test_precompiled_validation_endpoint_one_page_pdf(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document'),
        data=one_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    json_data = json.loads(response.get_data())
    assert json_data['result'] is False
    # we don't return messages if they haven't asked for the preview
    assert 'message' not in json_data


def test_precompiled_validation_with_preview_calls_overlay_if_pdf_out_of_bounds(client, auth_header, mocker):

    mocker.patch('app.precompiled.overlay_template_areas', return_value=[BytesIO(b"I'm a png")])

    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document', include_preview='1'),
        data=one_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    json_data = json.loads(response.get_data())
    assert json_data['result'] is False
    assert json_data['message'] == 'Content in this PDF is outside the printable area on page 1'
    assert json_data['pages'] == ['SSdtIGEgcG5n']


def test_precompiled_validation_with_preview_returns_invalid_pages_message_if_content_in_address_margin(
    client,
    auth_header,
    mocker,
):
    mocker.patch('app.precompiled.overlay_template_areas')

    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document', include_preview='1'),
        data=address_margin,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    json_data = json.loads(response.get_data())
    assert json_data['result'] is False
    assert json_data['message'] == 'Content in this PDF is outside the printable area on page 1'


def test_precompiled_validation_with_preview_handles_valid_pdf(client, auth_header, mocker):

    overlay_template_areas = mocker.patch('app.precompiled.overlay_template_areas')
    rewrite_address_block = mocker.patch(
        'app.precompiled.rewrite_address_block', return_value=(BytesIO(b"address block changed"), "WC1 1AA", None)
    )
    mocker.patch('app.precompiled.pngs_from_pdf', return_value=[BytesIO(b"I'm a png")])
    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document', include_preview='1'),
        data=blank_page,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    json_data = json.loads(response.get_data())

    assert json_data['result'] is True
    assert not overlay_template_areas.called
    rewrite_address_block.assert_called_once()
    assert json_data['pages'] == ['SSdtIGEgcG5n']


def test_precompiled_validation_with_preview_returns_multiple_pages_for_multipage_pdf(client, auth_header):
    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document', include_preview='1'),
        data=multi_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    json_data = json.loads(response.get_data())
    assert json_data['result'] is True
    assert len(json_data['pages']) == 10


def test_precompiled_validation_with_preview_flow_no_mocking(client, auth_header):
    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document', include_preview='1'),
        data=one_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    json_data = json.loads(response.get_data())
    assert json_data['result'] is False
    assert len(json_data['pages']) == 1


def test_precompiled_validation_with_preview_throws_error_if_file_is_not_a_pdf(client, auth_header):
    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document', include_preview='1'),
        data=b"I am not a pdf",
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 400
    json_data = json.loads(response.get_data())
    assert json_data['message'] == 'Unable to read the PDF data: Could not read malformed PDF file'


def test_precompiled_validation_endpoint_no_colour_pdf(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document'),
        data=no_colour,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    json_data = json.loads(response.get_data())
    assert json_data['result'] is False


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

    can = Canvas(None)
    # mock_canvas = mocker.patch.object(can, 'drawString')

    can.drawString = MagicMock(return_value=3)

    can.mock_canvas = mocker.patch('app.precompiled.canvas.Canvas', return_value=can)

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


@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Token not-the-actual-token'}])
def test_precompiled_rejects_if_not_authenticated(client, headers):
    resp = client.post(
        url_for('precompiled_blueprint.add_tag_to_precompiled_letter'),
        data={},
        headers=headers
    )
    assert resp.status_code == 401


def test_precompiled_no_data_page_raises_400(
    client,
    auth_header,
):
    response = client.post(
        url_for('precompiled_blueprint.add_tag_to_precompiled_letter'),
        data=None,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 400


def test_precompiled_endpoint_incorrect_data(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.add_tag_to_precompiled_letter'),
        data=json.dumps({
            'letter_contact_block': '123',
            'template': {
                'id': str(uuid.uuid4()),
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

    assert response.status_code == 400


def test_precompiled_endpoint_incorrect_pdf(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.add_tag_to_precompiled_letter'),
        data=not_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 400


def test_precompiled_endpoint(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.add_tag_to_precompiled_letter'),
        data=multi_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200


def test_get_invalid_pages_blank_page():
    packet = io.BytesIO()
    cv = canvas.Canvas(packet, pagesize=A4)
    cv.setStrokeColor(white)
    cv.setFillColor(white)
    cv.rect(0, 0, 1000, 1000, stroke=1, fill=1)
    cv.save()
    packet.seek(0)

    assert get_invalid_pages_with_message(packet) == ""


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

    assert get_invalid_pages_with_message(packet) == 'Content in this PDF is outside the printable area on page 1'


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

    assert get_invalid_pages_with_message(packet) == 'Content in this PDF is outside the printable area on page 1'


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

    assert get_invalid_pages_with_message(packet) == ""


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
        assert get_invalid_pages_with_message(packet) == 'Content in this PDF is outside the printable area on page 2'
    else:
        assert get_invalid_pages_with_message(packet) == ''


@pytest.mark.parametrize('x, y, page, expected_message', [
    (0, 0, 1, 'Content in this PDF is outside the printable area on page 1'),
    (200, 200, 1, ''),
    (590, 830, 1, 'Content in this PDF is outside the printable area on page 1'),
    (0, 200, 1, 'Content in this PDF is outside the printable area on page 1'),
    (0, 830, 1, 'Content in this PDF is outside the printable area on page 1'),
    (200, 0, 1, 'Content in this PDF is outside the printable area on page 1'),
    (590, 0, 1, 'Content in this PDF is outside the printable area on page 1'),
    (590, 200, 1, 'Content in this PDF is outside the printable area on page 1'),
    # under the citizen address block:
    (24.6 * mm, (297 - 90) * mm, 1, 'Content in this PDF is outside the printable area on page 1'),
    (24.6 * mm, (297 - 90) * mm, 2, ''),  # Same place on page 2 should be ok
    (24.6 * mm, (297 - 39) * mm, 1, 'Content in this PDF is outside the printable area on page 1'),  # under the logo
    (24.6 * mm, (297 - 39) * mm, 2, ''),  # Same place on page 2 should be ok
    (0, 0, 2, 'Content in this PDF is outside the printable area on page 2'),
    (200, 200, 2, ''),
    (590, 830, 2, 'Content in this PDF is outside the printable area on page 2'),
    (0, 200, 2, 'Content in this PDF is outside the printable area on page 2'),
    (0, 830, 2, 'Content in this PDF is outside the printable area on page 2'),
    (200, 0, 2, 'Content in this PDF is outside the printable area on page 2'),
    (590, 0, 2, 'Content in this PDF is outside the printable area on page 2'),
    (590, 200, 2, 'Content in this PDF is outside the printable area on page 2'),
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

    assert get_invalid_pages_with_message(packet) == 'Content in this PDF is outside the printable area on page 1'


@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Token not-the-actual-token'}])
def test_precompiled_validation_rejects_if_not_authenticated(client, headers):
    resp = client.post(
        url_for('precompiled_blueprint.add_tag_to_precompiled_letter'),
        data={},
        headers=headers
    )
    assert resp.status_code == 401


def test_precompiled_validation_no_data_page_raises_400(
    client,
    auth_header,
):
    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document'),
        data=None,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 400


def test_precompiled_validation_endpoint_incorrect_data(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document'),
        data=json.dumps({
            'letter_contact_block': '123',
            'template': {
                'id': str(uuid.uuid4()),
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

    assert response.status_code == 400


def test_precompiled_validation_endpoint_incorrect_pdf(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document'),
        data=not_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 400


@pytest.mark.parametrize('pdf_file, page_no', [(landscape_rotated_page, 1), (landscape_oriented_page, 2)])
def test_precompiled_validation_endpoint_fails_landscape_orientation_pages(
    client, auth_header, mocker, pdf_file, page_no
):
    mocker.patch('app.precompiled.overlay_template_areas')

    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document', include_preview='1'),
        data=pdf_file,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    json_data = json.loads(response.get_data())
    assert json_data['result'] is False
    assert json_data['message'] == 'Your letter is not A4 portrait size on page {}'.format(page_no)


@pytest.mark.parametrize('pdf_file', [portrait_rotated_page, multi_page_pdf])
def test_precompiled_validation_endpoint_passes_portrait_orientation_pages(client, auth_header, mocker, pdf_file):
    mocker.patch('app.precompiled.overlay_template_areas')

    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document', include_preview='1'),
        data=pdf_file,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    json_data = json.loads(response.get_data())
    assert json_data['result'] is True


@pytest.mark.parametrize('pdf_file,height,width,page_no,rotate', [
    (landscape_oriented_page, 210, 297, 2, 0), (a3_size, 420, 297, 1, None), (a5_size, 210, 148, 1, None)
])
def test_result_and_log_message_for_wrong_size_or_orientation_page(
    client, auth_header, mocker, caplog, pdf_file, height, width, page_no, rotate
):
    caplog.set_level(logging.WARNING)

    mocker.patch('app.precompiled.overlay_template_areas')

    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document'),
        data=pdf_file,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
    json_data = json.loads(response.get_data())
    assert json_data['result'] is False

    expected_message = [(
        'flask.app',
        logging.WARNING,
        'Letter is not A4 portrait size on page {}. Rotate: {}, height: {}mm, width: {}mm'.format(
            page_no, rotate, height, width
        )
    )]
    assert caplog.record_tuples == expected_message


def test_log_message_not_triggered_for_valid_pages(
    client, auth_header, mocker, caplog
):
    caplog.set_level(logging.WARNING)

    mocker.patch('app.precompiled.overlay_template_areas')

    response = client.post(
        url_for('precompiled_blueprint.validate_pdf_document'),
        data=multi_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )
    assert response.status_code == 200
    json_data = json.loads(response.get_data())
    assert json_data['result'] is True

    assert caplog.record_tuples == []


def test_overlay_endpoint_not_encoded(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.overlay_template', file_type="png"),
        data=None,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 400


def test_overlay_endpoint_incorrect_data(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.overlay_template', file_type="png"),
        data=json.dumps({
            'letter_contact_block': '123',
            'template': {
                'id': str(uuid.uuid4()),
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

    assert response.status_code == 400


def test_overlay_blank_page(client, auth_header, mocker):

    mocker.patch(
        'app.preview.png_from_pdf',
        return_value=BytesIO(b'\x00'),
    )

    response = client.post(
        url_for('precompiled_blueprint.overlay_template', page=1, file_type="png"),
        data=blank_page,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200


@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Token not-the-actual-token'}])
def test_overlay_endpoint_rejects_if_not_authenticated(client, headers):
    resp = client.post(
        url_for('precompiled_blueprint.overlay_template', file_type="png"),
        data={},
        headers=headers
    )
    assert resp.status_code == 401


def test_overlay_endpoint_multi_page_pdf(client, auth_header):
    resp = client.post(
        url_for('precompiled_blueprint.overlay_template', page=2, file_type="png"),
        data=multi_page_pdf,
        headers=auth_header
    )
    assert resp.status_code == 200


def test_overlay_endpoint_multi_page_pdf_as_pdf(client, auth_header, mocker):
    resp = client.post(
        url_for('precompiled_blueprint.overlay_template', invert=1, file_type="pdf"),
        data=multi_page_pdf,
        headers=auth_header
    )
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-1.3")


def test_overlay_endpoint_not_pdf(client, auth_header):
    resp = client.post(
        url_for('precompiled_blueprint.overlay_template', file_type="png"),
        data=not_pdf,
        headers=auth_header
    )
    assert resp.status_code == 400


def test_precompiled_sanitise_pdf_without_notify_tag(client, auth_header):
    assert not is_notify_tag_present(BytesIO(blank_page))

    response = client.post(
        url_for('precompiled_blueprint.sanitise_precompiled_letter'),
        data=blank_page,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )
    assert response.status_code == 200
    json_data = json.loads(response.get_data())
    assert json_data == {
        "message": None, "file": ANY, "page_count": 1, "recipient_address": "",
        'redaction_failed_message': 'More than one match for address block during redaction procedure'
    }

    pdf = BytesIO(base64.b64decode(json_data["file"].encode()))
    assert is_notify_tag_present(pdf)
    assert extract_address_block(pdf) == ''


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
        "message": 'Content in this PDF is outside the printable area on pages 1 and 2',
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
        "message": 'Content in this PDF is outside the printable area on page 1',
        "file": None
    }


@pytest.mark.xfail(strict=True, reason='Will be fixed with https://www.pivotaltracker.com/story/show/158625803')
def test_precompiled_sanitise_pdf_with_existing_notify_tag(client, auth_header):
    response = client.post(
        url_for('precompiled_blueprint.sanitise_precompiled_letter'),
        data=example_dwp_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200

    pdf = BytesIO(response.get_data())

    assert is_notify_tag_present(pdf)
    # can't check address block replacement as the old text is still there - just hidden under a white block.
    # The pdftotext tool doesn't handle this well, and smashes the two addresses together


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


def test_rewrite_address_block_end_to_end(mocker):
    mock_escape = mocker.patch(
        "app.precompiled.escape_special_characters_for_regex",
        return_value='MR J DOE\n13 TEST LANE\nTESTINGTON\nTE57 1NG'
    )
    new_pdf, address, message = rewrite_address_block(BytesIO(example_dwp_pdf))
    assert not message
    assert extract_address_block(new_pdf) == 'MR J DOE\n13 TEST LANE\nTESTINGTON\nTE57 1NG'
    mock_escape.assert_called_once()


def test_extract_address_block():
    assert extract_address_block(BytesIO(example_dwp_pdf)) == '\n'.join([
        'MR J DOE',
        '13 TEST LANE',
        'TESTINGTON',
        'TE57 1NG',
    ])


def test_add_address_to_precompiled_letter_puts_address_on_page():
    address = '\n'.join([
        'MR J DOE',
        '13 TEST LANE',
        'TESTINGTON',
        'TE57 1NG',
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
