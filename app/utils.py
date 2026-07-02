from base64 import b64decode, b64encode
from contextlib import contextmanager
from enum import StrEnum, auto
from functools import lru_cache
from io import BytesIO

import dateutil.parser
import sentry_sdk
from flask import current_app
from notifications_utils.s3 import s3download
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError


@sentry_sdk.trace
def stitch_pdfs(first_pdf: BytesIO, second_pdf: BytesIO) -> BytesIO:
    output = PdfWriter()
    output.append_pages_from_reader(PdfReader(first_pdf))
    output.append_pages_from_reader(PdfReader(second_pdf))

    pdf_bytes = BytesIO()
    output.write(pdf_bytes)
    pdf_bytes.seek(0)
    return pdf_bytes


class PDFPurpose(StrEnum):
    PREVIEW = auto()
    PRINT = auto()


def caching_s3download(bucket_name, filename) -> BytesIO:
    cached = _cached_s3_download(bucket_name, filename)
    return BytesIO(b64decode(cached))


@lru_cache(maxsize=2_000)
def _cached_s3_download(bucket_name, filename):
    return b64encode(s3download(bucket_name, filename).read())


def get_transient_letter_file_location(service_id, upload_id):
    return f"service-{service_id}/{upload_id}.pdf"


def get_datetime_from_json(request_json):
    return dateutil.parser.parse(request_json["date"]) if request_json.get("date") else None


PDF_LIBRARY_ERRORS = (PdfReadError,)


@contextmanager
def log_pdf_library_error(action_name="pdf_processing"):
    try:
        yield
    except PDF_LIBRARY_ERRORS as e:
        current_app.logger.exception("PDF library error '%s': %s", action_name, e, extra={"pdf_action": action_name})
        raise
