import base64

from botocore.exceptions import ClientError as BotoClientError
from flask import current_app
from notifications_utils.s3 import s3download, s3upload
from notifications_utils.statsd_decorators import statsd

from app import notify_celery, TaskNames, QueueNames
from app.precompiled import sanitise_file_contents


@notify_celery.task(name='sanitise-and-upload-letter')
@statsd(namespace='template-preview')
def sanitise_and_upload_letter(notification_id, filename):
    current_app.logger.info('Sanitising notification with id {}'.format(notification_id))

    try:
        pdf_content = s3download(current_app.config['LETTERS_SCAN_BUCKET_NAME'], filename).read()
        sanitisation_details = sanitise_file_contents(pdf_content)

        # Only files that have failed sanitisation have 'message' in the sanitisation_details dict
        if sanitisation_details.get('message'):
            validation_status = 'failed'
        else:
            validation_status = 'passed'
            file_data = base64.b64decode(sanitisation_details['file'].encode())

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

    notify_celery.send_task(
        name=TaskNames.PROCESS_SANITISED_LETTER,
        kwargs={
            'page_count': sanitisation_details['page_count'],
            'message': sanitisation_details['message'],
            'invalid_pages': sanitisation_details['invalid_pages'],
            'validation_status': validation_status,
            'filename': filename,
            'notification_id': notification_id,
        },
        queue=QueueNames.LETTERS
    )
