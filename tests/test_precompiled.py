import base64
import json
import uuid
from io import BytesIO
from unittest.mock import MagicMock

import PyPDF2
import pytest
from flask import url_for
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from app.precompiled import add_notify_tag_to_letter
from tests.pdf_consts import multi_page_pdf, not_pdf


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


def test_precompiled_endpoint_(client, auth_header):

    response = client.post(
        url_for('precompiled_blueprint.add_tag_to_precompiled_letter'),
        data=multi_page_pdf,
        headers={
            'Content-type': 'application/json',
            **auth_header
        }
    )

    assert response.status_code == 200
