import base64
from io import BytesIO

import boto3
import sentry_sdk
from botocore.exceptions import ClientError as BotoClientError
from flask import current_app
from flask_weasyprint import HTML
from notifications_utils import LETTER_MAX_PAGE_COUNT
from notifications_utils.s3 import s3download, s3upload
from notifications_utils.template import LetterPrintTemplate

from app import notify_celery
from app.config import QueueNames, TaskNames
from app.letter_attachments import add_attachment_to_letter
from app.precompiled import sanitise_file_contents
from app.preview import get_page_count
from app.transformation import convert_pdf_to_cmyk
from app.weasyprint_hack import WeasyprintError


@notify_celery.task(name="sanitise-and-upload-letter")
def sanitise_and_upload_letter(notification_id, filename, allow_international_letters=False):
    current_app.logger.info("Sanitising notification with id %s", notification_id)

    try:
        pdf_content = s3download(current_app.config["LETTERS_SCAN_BUCKET_NAME"], filename).read()
        sanitisation_details = sanitise_file_contents(
            pdf_content,
            allow_international_letters=allow_international_letters,
            filename=filename,
        )

        # Only files that have failed sanitisation have 'message' in the sanitisation_details dict
        if sanitisation_details.get("message"):
            validation_status = "failed"
        else:
            validation_status = "passed"
            file_data = base64.b64decode(sanitisation_details["file"].encode())

            # If the file already exists in S3, it will be overwritten
            s3upload(
                filedata=file_data,
                region=current_app.config["AWS_REGION"],
                bucket_name=current_app.config["SANITISED_LETTER_BUCKET_NAME"],
                file_location=filename,
            )
            # upload a backup copy of the original PDF that will be held in the bucket for a week
            copy_s3_object(
                current_app.config["LETTERS_SCAN_BUCKET_NAME"],
                filename,
                current_app.config["PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME"],
                f"{notification_id}.pdf",
            )

        current_app.logger.info(
            "Notification %(status)s sanitisation: %(id)s", dict(status=validation_status, id=notification_id)
        )

    except BotoClientError:
        current_app.logger.exception(
            "Error downloading %s from scan bucket or uploading to sanitise bucket for notification %s",
            filename,
            notification_id,
        )
        return

    sanitise_data = {
        "page_count": sanitisation_details["page_count"],
        "message": sanitisation_details["message"],
        "invalid_pages": sanitisation_details["invalid_pages"],
        "validation_status": validation_status,
        "filename": filename,
        "notification_id": notification_id,
        "address": sanitisation_details["recipient_address"],
    }
    encrypted_data = current_app.encryption_client.encrypt(sanitise_data)

    notify_celery.send_task(
        name=TaskNames.PROCESS_SANITISED_LETTER,
        args=(encrypted_data,),
        queue=QueueNames.LETTERS,
    )


def copy_s3_object(source_bucket, source_filename, target_bucket, target_filename, metadata=None):
    s3 = boto3.resource("s3")
    copy_source = {"Bucket": source_bucket, "Key": source_filename}

    target_bucket = s3.Bucket(target_bucket)
    obj = target_bucket.Object(target_filename)

    # Tags are copied across but the expiration time is reset in the destination bucket
    # e.g. if a file has 5 days left to expire on a ONE_WEEK retention in the source bucket,
    # in the destination bucket the expiration time will be reset to 7 days left to expire
    put_args = {"ServerSideEncryption": "AES256"}
    if metadata:
        put_args["Metadata"] = metadata
        put_args["MetadataDirective"] = "REPLACE"
    obj.copy(copy_source, ExtraArgs=put_args)

    current_app.logger.info(
        "Copied PDF letter: %(source_bucket)s/%(source_filename)s to %(target_bucket)s/%(target_filename)s",
        dict(
            source_bucket=source_bucket,
            source_filename=source_filename,
            target_bucket=target_bucket,
            target_filename=target_filename,
        ),
    )


@notify_celery.task(
    bind=True,
    name="create-pdf-for-templated-letter",
    max_retries=3,
    default_retry_delay=180,
)
def create_pdf_for_templated_letter(self, encrypted_letter_data):
    letter_details = current_app.encryption_client.decrypt(encrypted_letter_data)
    current_app.logger.info("Creating a pdf for notification with id %s", letter_details["notification_id"])
    logo_filename = f'{letter_details["logo_filename"]}.svg' if letter_details["logo_filename"] else None

    template = LetterPrintTemplate(
        letter_details["template"],
        values=letter_details["values"] or None,
        contact_block=letter_details["letter_contact_block"],
        # letter assets are hosted on s3
        admin_base_url=current_app.config["LETTER_LOGO_URL"],
        logo_file_name=logo_filename,
    )
    with current_app.test_request_context(""):
        html = HTML(string=str(template))

    try:
        with sentry_sdk.start_span(op="function", description="weasyprint.HTML.write_pdf"):
            pdf = BytesIO(html.write_pdf())
    except WeasyprintError as exc:
        self.retry(exc=exc, queue=QueueNames.SANITISE_LETTERS)

    cmyk_pdf = convert_pdf_to_cmyk(pdf)

    if letter_attachment := letter_details["template"].get("letter_attachment"):
        cmyk_pdf = add_attachment_to_letter(
            service_id=letter_details["template"]["service"],
            templated_letter_pdf=cmyk_pdf,
            attachment_object=letter_attachment,
        )

    page_count = get_page_count(cmyk_pdf.read())
    cmyk_pdf.seek(0)
    try:
        # If the file already exists in S3, it will be overwritten
        metadata = None
        task_name = TaskNames.UPDATE_BILLABLE_UNITS_FOR_LETTER
        filename = letter_details["letter_filename"]
        if page_count > LETTER_MAX_PAGE_COUNT:
            bucket_name = current_app.config["INVALID_PDF_BUCKET_NAME"]
            task_name = TaskNames.UPDATE_VALIDATION_FAILED_FOR_TEMPLATED_LETTER
            filename = _remove_folder_from_filename(letter_details["letter_filename"])
            metadata = {
                "validation_status": "failed",
                "message": "letter-too-long",
                "page_count": str(page_count),
            }
        elif letter_details["key_type"] == "test":
            bucket_name = current_app.config["TEST_LETTERS_BUCKET_NAME"]
        else:
            bucket_name = current_app.config["LETTERS_PDF_BUCKET_NAME"]

        s3upload(
            filedata=cmyk_pdf,
            region=current_app.config["AWS_REGION"],
            bucket_name=bucket_name,
            file_location=filename,
            metadata=metadata,
        )

        current_app.logger.info(
            "Uploaded letters PDF %(filename)s to %(bucket_name)s for notification id %(id)s",
            dict(
                filename=letter_details["letter_filename"],
                bucket_name=bucket_name,
                id=letter_details["notification_id"],
            ),
        )

    except BotoClientError:
        current_app.logger.exception(
            "Error uploading %(filename)s to pdf bucket for notification %(id)s",
            dict(filename=letter_details["letter_filename"], id=letter_details["notification_id"]),
        )
        return

    notify_celery.send_task(
        name=task_name,
        kwargs={
            "notification_id": letter_details["notification_id"],
            "page_count": page_count,
        },
        queue=QueueNames.LETTERS,
    )


def _remove_folder_from_filename(filename):
    # filename looks like '2018-01-13/NOTIFY.ABCDEF1234567890.D.2.C.20180113120000.PDF'
    # or NOTIFY.ABCDEF1234567890.D.2.C.20180113120000.PDF if created from test key
    filename_parts = filename.split("/")
    index = 1 if len(filename_parts) > 1 else 0
    return filename_parts[index]


@notify_celery.task(name="recreate-pdf-for-precompiled-letter")
def recreate_pdf_for_precompiled_letter(notification_id, file_location, allow_international_letters):
    """
    This task takes the details of a PDF letter which we want to recreate as its arguments.
    It gets the backup version of the PDF letter from the backup bucket, sanitises it and moves the
    sanitised version to the final letters bucket.
    This task is only intended to be used for letters which were valid when previously sanitised.
    """
    current_app.logger.info("Re-sanitising and uploading PDF for notification with id %s", notification_id)

    try:
        pdf_content = s3download(
            current_app.config["PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME"],
            f"{notification_id}.pdf",
        ).read()

        sanitisation_details = sanitise_file_contents(
            pdf_content,
            allow_international_letters=allow_international_letters,
            filename=file_location,
        )

        # Only files that have failed sanitisation have 'message' in the sanitisation_details dict
        if sanitisation_details.get("message"):
            # The file previously passed sanitisation, so we need to manually investigate why it's now failing
            current_app.logger.error("Notification failed resanitisation: %s", notification_id)
            return

        file_data = base64.b64decode(sanitisation_details["file"].encode())

        # Upload the sanitised back-up file to S3, where it will overwrite the existing letter
        # in the final letters-pdf bucket.
        s3upload(
            filedata=file_data,
            region=current_app.config["AWS_REGION"],
            bucket_name=current_app.config["LETTERS_PDF_BUCKET_NAME"],
            file_location=file_location,
        )

        current_app.logger.info("Notification passed resanitisation: %s", notification_id)

    except BotoClientError:
        current_app.logger.exception(
            "Error downloading file from backup bucket or uploading to letters-pdf bucket for notification %s",
            notification_id,
        )
        return
