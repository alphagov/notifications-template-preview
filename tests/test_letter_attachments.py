from app.letter_attachments import add_attachment_to_letter
from app.preview import get_page_count_for_pdf
from tests.conftest import s3_response_body
from tests.pdf_consts import blank_page, valid_letter


def test_add_attachment_to_letter(mocker):
    mock_get_attachment = mocker.patch("app.letter_attachments.get_attachment_pdf", return_value=blank_page)
    response = add_attachment_to_letter("1234", (s3_response_body(valid_letter)), {"page_count": 1, "id": "5678"})

    mock_get_attachment.assert_called_once_with("1234", "5678")

    assert get_page_count_for_pdf(response.read()) == 2
