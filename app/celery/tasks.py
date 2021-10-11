import base64
from io import BytesIO

import boto3
from botocore.exceptions import ClientError as BotoClientError
from flask import current_app
from flask_weasyprint import HTML
from notifications_utils.s3 import s3download, s3upload
from notifications_utils.template import LetterPrintTemplate

from app import QueueNames, TaskNames, notify_celery
from app.precompiled import sanitise_file_contents
from app.preview import get_page_count
from app.transformation import convert_pdf_to_cmyk
from app.weasyprint_hack import WeasyprintError


@notify_celery.task(name='sanitise-and-upload-letter')
def sanitise_and_upload_letter(notification_id, filename, allow_international_letters=False):
    current_app.logger.info('Sanitising notification with id {}'.format(notification_id))

    try:
        pdf_content = s3download(current_app.config['LETTERS_SCAN_BUCKET_NAME'], filename).read()
        sanitisation_details = sanitise_file_contents(
            pdf_content,
            allow_international_letters=allow_international_letters,
            filename=filename
        )

        # Only files that have failed sanitisation have 'message' in the sanitisation_details dict
        if sanitisation_details.get('message'):
            validation_status = 'failed'
        else:
            validation_status = 'passed'
            file_data = base64.b64decode(sanitisation_details['file'].encode())

            redaction_failed_message = sanitisation_details.get('redaction_failed_message')
            if redaction_failed_message:
                current_app.logger.info(f'{redaction_failed_message} for file {filename}')
                copy_redaction_failed_pdf(filename)

            # If the file already exists in S3, it will be overwritten
            s3upload(
                filedata=file_data,
                region=current_app.config['AWS_REGION'],
                bucket_name=current_app.config['SANITISED_LETTER_BUCKET_NAME'],
                file_location=filename,
            )
            # upload a backup copy of the original PDF that will be held in the bucket for a week
            copy_s3_object(
                current_app.config['LETTERS_SCAN_BUCKET_NAME'], filename,
                current_app.config['PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME'], f'{notification_id}.pdf'
            )

        current_app.logger.info('Notification {} sanitisation: {}'.format(validation_status, notification_id))

    except BotoClientError:
        current_app.logger.exception(
            "Error downloading {} from scan bucket or uploading to sanitise bucket for notification {}".format(
                filename, notification_id
            )
        )
        return

    sanitise_data = {
        'page_count': sanitisation_details['page_count'],
        'message': sanitisation_details['message'],
        'invalid_pages': sanitisation_details['invalid_pages'],
        'validation_status': validation_status,
        'filename': filename,
        'notification_id': notification_id,
        'address': sanitisation_details['recipient_address']
    }
    encrypted_data = current_app.encryption_client.encrypt(sanitise_data)

    notify_celery.send_task(
        name=TaskNames.PROCESS_SANITISED_LETTER,
        args=(encrypted_data,),
        queue=QueueNames.LETTERS
    )


def copy_redaction_failed_pdf(source_filename):
    '''
    Copies the original version of a PDF which has failed redaction into a subfolder of the letter scan bucket
    '''
    scan_bucket_name = current_app.config['LETTERS_SCAN_BUCKET_NAME']
    target_filename = f'REDACTION_FAILURE/{source_filename}'
    copy_s3_object(
        scan_bucket_name, source_filename, scan_bucket_name, target_filename, metadata=None
    )


def copy_s3_object(source_bucket, source_filename, target_bucket, target_filename, metadata=None):
    s3 = boto3.resource('s3')
    copy_source = {'Bucket': source_bucket, 'Key': source_filename}

    target_bucket = s3.Bucket(target_bucket)
    obj = target_bucket.Object(target_filename)

    # Tags are copied across but the expiration time is reset in the destination bucket
    # e.g. if a file has 5 days left to expire on a ONE_WEEK retention in the source bucket,
    # in the destination bucket the expiration time will be reset to 7 days left to expire
    put_args = {'ServerSideEncryption': 'AES256'}
    if metadata:
        put_args['Metadata'] = metadata
        put_args["MetadataDirective"] = "REPLACE"
    obj.copy(copy_source, ExtraArgs=put_args)

    current_app.logger.info("Copied PDF letter: {}/{} to {}/{}".format(
        source_bucket, source_filename, target_bucket, target_filename))


@notify_celery.task(bind=True, name='create-pdf-for-templated-letter', max_retries=3, default_retry_delay=180)
def create_pdf_for_templated_letter(self, encrypted_letter_data):
    letter_details = current_app.encryption_client.decrypt(encrypted_letter_data)
    current_app.logger.info(f"Creating a pdf for notification with id {letter_details['notification_id']}")
    logo_filename = f'{letter_details["logo_filename"]}.svg' if letter_details['logo_filename'] else None

    template = LetterPrintTemplate(
        letter_details['template'],
        values=letter_details['values'] or None,
        contact_block=letter_details['letter_contact_block'],
        # letter assets are hosted on s3
        admin_base_url=current_app.config['LETTER_LOGO_URL'],
        logo_file_name=logo_filename,
    )
    with current_app.test_request_context(''):
        html = HTML(string=str(template))

    try:
        pdf = BytesIO(html.write_pdf())
    except WeasyprintError as exc:
        self.retry(exc=exc, queue=QueueNames.SANITISE_LETTERS)

    cmyk_pdf = convert_pdf_to_cmyk(pdf)
    page_count = get_page_count(cmyk_pdf.read())
    cmyk_pdf.seek(0)

    try:
        # If the file already exists in S3, it will be overwritten
        if letter_details["key_type"] == "test":
            bucket_name = current_app.config['TEST_LETTERS_BUCKET_NAME']
        else:
            bucket_name = current_app.config['LETTERS_PDF_BUCKET_NAME']
        s3upload(
            filedata=cmyk_pdf,
            region=current_app.config['AWS_REGION'],
            bucket_name=bucket_name,
            file_location=letter_details["letter_filename"],
        )

        current_app.logger.info(
            f"Uploaded letters PDF {letter_details['letter_filename']} to {bucket_name} for "
            f"notification id {letter_details['notification_id']}"
        )

    except BotoClientError:
        current_app.logger.exception(
            f"Error uploading {letter_details['letter_filename']} to pdf bucket "
            f"for notification {letter_details['notification_id']}"
        )
        return

    notify_celery.send_task(
        name=TaskNames.UPDATE_BILLABLE_UNITS_FOR_LETTER,
        kwargs={
            "notification_id": letter_details["notification_id"],
            "page_count": page_count,
        },
        queue=QueueNames.LETTERS
    )
