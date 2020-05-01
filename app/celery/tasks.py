import base64

from botocore.exceptions import ClientError as BotoClientError
from flask import current_app
from notifications_utils.s3 import s3download, s3upload
from notifications_utils.statsd_decorators import statsd
import boto3

from app import notify_celery, TaskNames, QueueNames
from app.precompiled import sanitise_file_contents


@notify_celery.task(name='sanitise-and-upload-letter')
@statsd(namespace='template-preview')
def sanitise_and_upload_letter(notification_id, filename, allow_international_letters=False):
    current_app.logger.info('Sanitising notification with id {}'.format(notification_id))

    try:
        pdf_content = s3download(current_app.config['LETTERS_SCAN_BUCKET_NAME'], filename).read()
        sanitisation_details = sanitise_file_contents(
            pdf_content,
            allow_international_letters=allow_international_letters,
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
    s3 = boto3.resource('s3')
    scan_bucket_name = current_app.config['LETTERS_SCAN_BUCKET_NAME']
    scan_bucket = s3.Bucket(scan_bucket_name)
    copy_source = {'Bucket': scan_bucket_name, 'Key': source_filename}

    target_filename = f'REDACTION_FAILURE/{source_filename}'

    obj = scan_bucket.Object(target_filename)

    # Tags are copied across but the expiration time is reset in the destination bucket
    # e.g. if a file has 5 days left to expire on a ONE_WEEK retention in the source bucket,
    # in the destination bucket the expiration time will be reset to 7 days left to expire
    obj.copy(copy_source, ExtraArgs={'ServerSideEncryption': 'AES256'})
