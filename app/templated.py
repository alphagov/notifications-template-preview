from collections.abc import Callable
from io import BytesIO

from app.letter_attachments import add_attachment_to_letter
from app.transformation import convert_pdf_to_cmyk
from app.utils import PDFPurpose, stitch_pdfs


def generate_templated_pdf(
    letter_details, create_pdf_lambda: Callable[[dict, str, bool], BytesIO], purpose: PDFPurpose
):
    # todo: remove `.get()` when all celery tasks are sending this key
    if letter_details["template"].get("letter_languages") == "welsh_then_english":
        welsh_pdf = create_pdf_lambda(letter_details, language="welsh", includes_first_page=True)
        english_pdf = create_pdf_lambda(letter_details, language="english", includes_first_page=False)

        pdf = stitch_pdfs(
            first_pdf=welsh_pdf,
            second_pdf=english_pdf,
        )
    else:
        pdf = create_pdf_lambda(letter_details, language="english", includes_first_page=True)

    if purpose == PDFPurpose.PRINT:
        pdf = convert_pdf_to_cmyk(pdf)
        pdf.seek(0)

    # Letter attachments are passed through `/precompiled/sanitise` endpoint, so already in CMYK.
    if letter_attachment := letter_details["template"].get("letter_attachment"):
        pdf = add_attachment_to_letter(
            service_id=letter_details["template"]["service"],
            templated_letter_pdf=pdf,
            attachment_object=letter_attachment,
        )
    return pdf
