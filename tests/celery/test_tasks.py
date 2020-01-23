from io import BytesIO

from botocore.exceptions import ClientError as BotoClientError
from flask import current_app

from app.celery.tasks import sanitise_and_upload_letter
from tests.pdf_consts import blank_with_address, no_colour


def test_sanitise_and_upload_valid_letter(mocker, client):
    valid_file = BytesIO(blank_with_address)

    mocker.patch('app.celery.tasks.s3download', return_value=valid_file)
    mock_upload = mocker.patch('app.celery.tasks.s3upload')
    mock_celery = mocker.patch('app.celery.tasks.notify_celery.send_task')

    sanitise_and_upload_letter('abc-123', 'filename.pdf')

    mock_upload.assert_called_once_with(
        filedata=mocker.ANY,
        region=current_app.config['AWS_REGION'],
        bucket_name=current_app.config['SANITISED_LETTER_BUCKET_NAME'],
        file_location='filename.pdf',
    )

    encrypted_task_args = current_app.encryption_client.encrypt({'page_count': 1,
                                                                 'message': None,
                                                                 'invalid_pages': None,
                                                                 'validation_status': 'passed',
                                                                 'filename': 'filename.pdf',
                                                                 'notification_id': 'abc-123',
                                                                 'address': 'Bugs Bunny,\nLooney Town\nLT10 0OP'})

    mock_celery.assert_called_once_with(
        args=(encrypted_task_args,),
        name='process-sanitised-letter',
        queue='letter-tasks'
    )


def test_sanitise_invalid_letter(mocker, client):
    file_with_content_in_margins = BytesIO(no_colour)

    mocker.patch('app.celery.tasks.s3download', return_value=file_with_content_in_margins)
    mock_upload = mocker.patch('app.celery.tasks.s3upload')
    mock_celery = mocker.patch('app.celery.tasks.notify_celery.send_task')

    sanitise_and_upload_letter('abc-123', 'filename.pdf')

    encrypted_task_args = current_app.encryption_client.encrypt({'page_count': 2,
                                                                 'message': 'content-outside-printable-area',
                                                                 'invalid_pages': [1, 2],
                                                                 'validation_status': 'failed',
                                                                 'filename': 'filename.pdf',
                                                                 'notification_id': 'abc-123',
                                                                 'address': None})

    assert not mock_upload.called
    mock_celery.assert_called_once_with(
        args=(encrypted_task_args,),
        name='process-sanitised-letter',
        queue='letter-tasks'
    )


def test_sanitise_and_upload_letter_raises_a_boto_error(mocker, client):
    mocker.patch('app.celery.tasks.s3download', side_effect=BotoClientError({}, 'operation-name'))
    mock_upload = mocker.patch('app.celery.tasks.s3upload')
    mock_celery = mocker.patch('app.celery.tasks.notify_celery.send_task')
    mock_logger = mocker.patch('app.celery.tasks.current_app.logger.exception')

    filename = 'filename.pdf'
    notification_id = 'abc-123'

    sanitise_and_upload_letter(notification_id, filename)

    assert not mock_upload.called
    assert not mock_celery.called
    mock_logger.assert_called_once_with(
        'Error downloading {} from scan bucket or uploading to sanitise bucket for notification {}'.format(
            filename, notification_id)
    )
