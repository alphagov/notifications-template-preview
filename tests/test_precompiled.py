import base64
import io
import json
import uuid
from io import BytesIO
from unittest.mock import MagicMock, ANY

import PyPDF2
import pytest
from flask import url_for
from reportlab.lib.colors import white, black, grey
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfgen.canvas import Canvas

from app.precompiled import (
    add_notify_tag_to_letter,
    is_notify_tag_present,
    validate_document,
    extract_address_block,
    add_address_to_precompiled_letter
)

from tests.pdf_consts import (
    blank_page,
    example_dwp_pdf,
    multi_page_pdf,
    no_colour,
    not_pdf,
    one_page_pdf,
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
    file_data = base64.b64decode(multi_page_pdf)
    pdf_original = PyPDF2.PdfFileReader(BytesIO(file_data))

    assert 'NOTIFY' not in pdf_original.getPage(0).extractText()

    pdf_page = add_notify_tag_to_letter(BytesIO(file_data))

    pdf_new = PyPDF2.PdfFileReader(BytesIO(pdf_page.read()))

    assert pdf_new.numPages == pdf_original.numPages
    assert pdf_new.getPage(0).extractText() != pdf_original.getPage(0).extractText()
    assert 'NOTIFY' in pdf_new.getPage(0).extractText()
    assert pdf_new.getPage(1).extractText() == pdf_original.getPage(1).extractText()
    assert pdf_new.getPage(2).extractText() == pdf_original.getPage(2).extractText()
    assert pdf_new.getPage(3).extractText() == pdf_original.getPage(3).extractText()


def test_add_notify_tag_to_letter_correct_margins(mocker):
    file_data = base64.b64decode(multi_page_pdf)
    pdf_original = PyPDF2.PdfFileReader(BytesIO(file_data))

    can = Canvas(None)
    # mock_canvas = mocker.patch.object(can, 'drawString')

    can.drawString = MagicMock(return_value=3)

    can.mock_canvas = mocker.patch('app.precompiled.canvas.Canvas', return_value=can)

    file_data = base64.b64decode(multi_page_pdf)

    # It fails because we are mocking but by that time the drawString method has been called so just carry on
    try:
        add_notify_tag_to_letter(BytesIO(file_data))
    except Exception:
        pass

    mm_from_top_of_the_page = 4.3
    mm_from_left_of_page = 7.4

    x = mm_from_left_of_page * mm

    # page.mediaBox[3] Media box is an array with the four corners of the page
    # We want height so can use that co-ordinate which is located in [3]
    # The lets take away the margin and the ont size
    y = float(pdf_original.getPage(0).mediaBox[3]) - (float(mm_from_top_of_the_page * mm + 6 - 1.75))

    can.drawString.assert_called_once()
    can.drawString.assert_called_with(x, y, "NOTIFY")


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
            'dvla_org_id': '001',
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


def test_validate_document_blank_page():
    packet = io.BytesIO()
    cv = canvas.Canvas(packet, pagesize=A4)
    cv.setStrokeColor(white)
    cv.setFillColor(white)
    cv.rect(0, 0, 1000, 1000, stroke=1, fill=1)
    cv.save()
    packet.seek(0)

    assert validate_document(packet)


def test_validate_document_black_bottom_corner():
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

    assert validate_document(packet) is False


def test_validate_document_grey_bottom_corner():
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

    assert validate_document(packet) is False


def test_validate_document_blank_multi_page():
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

    assert validate_document(packet)


def test_validate_document_black_bottom_corner_second_page():
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
    cv.rect(0, 0, 10, 10, stroke=1, fill=1)
    cv.save()
    packet.seek(0)

    assert validate_document(packet) is False


@pytest.mark.parametrize('x, y, page, result', [
    (0, 0, 1, False),
    (200, 200, 1, True),
    (590, 830, 1, False),
    (0, 200, 1, False),
    (0, 830, 1, False),
    (200, 0, 1, False),
    (590, 0, 1, False),
    (590, 200, 1, True),
    (24.6 * mm, (297 - 90) * mm, 1, False),  # under the citizen address block
    (24.6 * mm, (297 - 90) * mm, 2, True),  # Same place on page 2 should be ok
    (24.6 * mm, (297 - 39) * mm, 1, False),  # under the logo
    (24.6 * mm, (297 - 39) * mm, 2, True),  # Same place on page 2 should be ok
    (0, 0, 2, False),
    (200, 200, 2, True),
    (590, 830, 2, False),
    (0, 200, 2, False),
    (0, 830, 2, False),
    (200, 0, 2, False),
    (590, 0, 2, False),
    (590, 200, 2, True),
])
def test_validate_document_black_text(x, y, page, result):
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

    assert validate_document(packet) is result


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
            'dvla_org_id': '001',
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


def test_overlay_endpoint_not_encoded(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.overlay_template'),
        data=None,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 400


def test_overlay_endpoint_incorrect_data(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.overlay_template'),
        data=json.dumps({
            'letter_contact_block': '123',
            'template': {
                'id': str(uuid.uuid4()),
                'subject': 'letter subject',
                'content': ' letter content',
            },
            'values': {},
            'dvla_org_id': '001',
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
        url_for('precompiled_blueprint.overlay_template', page=1),
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
        url_for('precompiled_blueprint.overlay_template'),
        data={},
        headers=headers
    )
    assert resp.status_code == 401


def test_overlay_endpoint_multi_page_pdf(client, auth_header):
    resp = client.post(
        url_for('precompiled_blueprint.overlay_template', page=2),
        data=multi_page_pdf,
        headers=auth_header
    )
    assert resp.status_code == 200


def test_overlay_endpoint_not_pdf(client, auth_header):
    resp = client.post(
        url_for('precompiled_blueprint.overlay_template'),
        data=not_pdf,
        headers=auth_header
    )
    assert resp.status_code == 400


def test_precompiled_sanitise_one_page_pdf(client, auth_header):
    assert not is_notify_tag_present(BytesIO(base64.b64decode(one_page_pdf)))

    response = client.post(
        url_for('precompiled_blueprint.sanitise_precompiled_letter'),
        data=one_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200

    pdf = BytesIO(response.get_data())
    assert is_notify_tag_present(pdf)
    # the extract process picks up the fake barcode we've put in. When we use this in the wild we won't pick up any
    # extra things, because services aren't allowed to put anything in that area
    assert {x for x in extract_address_block(pdf).split('\n')} == {'000_000_0000000_000000_0000_00000', 'TEST'}


def test_precompiled_sanitise_one_page_pdf_with_existing_notify_tag(client, auth_header):
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
    # the address block replacement simply overlays the address - so `pdftotext` or any other static analysis tools will
    # see the lines twice. So lets just compare sets of lines.
    assert {x for x in extract_address_block(pdf).split('\n')} == {
        'MR J DOE',
        '13 TEST LANE',
        'TESTINGTON',
        'TE57 1NG',
    }


def test_is_notify_tag_present_finds_notify_tag():
    assert is_notify_tag_present(BytesIO(base64.b64decode(example_dwp_pdf))) is True


def test_is_notify_tag_present():
    assert is_notify_tag_present(BytesIO(base64.b64decode(one_page_pdf))) is False


def test_is_notify_tag_calls_extract_with_wider_numbers(mocker):
    mock_extract = mocker.patch('app.precompiled._extract_text_from_pdf')
    pdf = MagicMock()

    is_notify_tag_present(pdf)

    mock_extract.assert_called_once_with(
        ANY,
        x=pytest.approx(2.4),
        y=pytest.approx(1.3),
        width=pytest.approx(18.11388),
        height=pytest.approx(8.11666),
    )


def test_extract_address_block():
    assert extract_address_block(BytesIO(base64.b64decode(example_dwp_pdf))) == '\n'.join([
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
    ret = add_address_to_precompiled_letter(BytesIO(base64.b64decode(blank_page)), address)

    assert extract_address_block(ret) == address
