from io import BytesIO

from botocore.response import StreamingBody
from flask import current_app
from notifications_utils.s3 import s3download


def get_attachment_pdf(service_id, attachment_id) -> bytes:
    return s3download(
        current_app.config["LETTER_ATTACHMENT_BUCKET_NAME"],
        f"service-{service_id}/{attachment_id}.pdf",
    ).read()


def add_attachment_to_letter(service_id, templated_letter_pdf: StreamingBody, attachment_object: dict) -> BytesIO:
    from app.precompiled import stitch_pdfs

    attachment_pdf = get_attachment_pdf(service_id, attachment_object["id"])

    # templated letters are cached in s3, where a StreamingBody is returned which does not have a seek function,
    # so we need to read the `bytes` and then wrap that in a `BytesIO` as a buffer
    stitched_pdf = stitch_pdfs(
        first_pdf=BytesIO(templated_letter_pdf.read()),
        second_pdf=BytesIO(attachment_pdf),
    )

    return stitched_pdf
