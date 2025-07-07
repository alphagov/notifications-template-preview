from io import BytesIO

import sentry_sdk
from flask import current_app

from app.utils import caching_s3download, stitch_pdfs


@sentry_sdk.trace
def get_attachment_pdf(service_id, attachment_id) -> BytesIO:
    return caching_s3download(
        current_app.config["LETTER_ATTACHMENT_BUCKET_NAME"],
        f"service-{service_id}/{attachment_id}.pdf",
    )


def add_attachment_to_letter(service_id, templated_letter_pdf: BytesIO, attachment_object: dict) -> BytesIO:
    attachment_pdf = get_attachment_pdf(service_id, attachment_object["id"])

    stitched_pdf = stitch_pdfs(
        first_pdf=templated_letter_pdf,
        second_pdf=attachment_pdf,
    )

    return stitched_pdf
