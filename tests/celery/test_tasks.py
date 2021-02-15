import pytest
import werkzeug.exceptions

from io import BytesIO

import boto3
from botocore.exceptions import ClientError as BotoClientError
from flask import current_app
from moto import mock_s3
from unittest.mock import call
from celery.exceptions import Retry

from app import QueueNames
from app.celery.tasks import copy_redaction_failed_pdf, create_pdf_for_templated_letter, sanitise_and_upload_letter
from tests.pdf_consts import bad_postcode, blank_with_address, no_colour, repeated_address_block


def test_sanitise_and_upload_valid_letter(mocker, client):
    valid_file = BytesIO(blank_with_address)

    mocker.patch('app.celery.tasks.s3download', return_value=valid_file)
    mock_upload = mocker.patch('app.celery.tasks.s3upload')
    mock_celery = mocker.patch('app.celery.tasks.notify_celery.send_task')
    mock_redact_address = mocker.patch('app.celery.tasks.copy_redaction_failed_pdf')

    sanitise_and_upload_letter('abc-123', 'filename.pdf')

    mock_upload.assert_called_once_with(
        filedata=mocker.ANY,
        region=current_app.config['AWS_REGION'],
        bucket_name=current_app.config['SANITISED_LETTER_BUCKET_NAME'],
        file_location='filename.pdf',
    )

    encrypted_task_args = current_app.encryption_client.encrypt({
        'page_count': 1,
        'message': None,
        'invalid_pages': None,
        'validation_status': 'passed',
        'filename': 'filename.pdf',
        'notification_id': 'abc-123',
        'address': 'Queen Elizabeth\nBuckingham Palace\nLondon\nSW1 1AA'
    })

    mock_celery.assert_called_once_with(
        args=(encrypted_task_args,),
        name='process-sanitised-letter',
        queue='letter-tasks'
    )
    assert not mock_redact_address.called


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


@pytest.mark.parametrize('extra_args, expected_error', (
    ({}, 'not-a-real-uk-postcode'),
    ({'allow_international_letters': False}, 'not-a-real-uk-postcode'),
    ({'allow_international_letters': True}, 'not-a-real-uk-postcode-or-country'),
))
def test_sanitise_international_letters(
    mocker,
    client,
    extra_args,
    expected_error,
):
    mocker.patch('app.celery.tasks.s3download', return_value=BytesIO(bad_postcode))
    mock_upload = mocker.patch('app.celery.tasks.s3upload')
    mock_celery = mocker.patch('app.celery.tasks.notify_celery.send_task')

    sanitise_and_upload_letter('abc-123', 'filename.pdf', **extra_args)

    encrypted_task_args = current_app.encryption_client.encrypt({
        'page_count': 1,
        'message': expected_error,
        'invalid_pages': [1],
        'validation_status': 'failed',
        'filename': 'filename.pdf',
        'notification_id': 'abc-123',
        'address': None,
    })

    assert not mock_upload.called
    mock_celery.assert_called_once_with(
        args=(encrypted_task_args,),
        name='process-sanitised-letter',
        queue='letter-tasks'
    )


def test_sanitise_letter_which_fails_redaction(mocker, client):
    letter = BytesIO(repeated_address_block)

    mocker.patch('app.celery.tasks.s3download', return_value=letter)
    mock_redact_address = mocker.patch('app.celery.tasks.copy_redaction_failed_pdf')
    mock_upload = mocker.patch('app.celery.tasks.s3upload')
    mock_celery = mocker.patch('app.celery.tasks.notify_celery.send_task')

    sanitise_and_upload_letter('abc-123', 'filename.pdf')

    sanitisation_data = {
        'page_count': 1,
        'message': None,
        'invalid_pages': None,
        'validation_status': 'passed',
        'filename': 'filename.pdf',
        'notification_id': 'abc-123',
        'address': 'Queen Elizabeth\nBuckingham Palace\nLondon\nSW1 1AA',
    }
    encrypted_task_args = current_app.encryption_client.encrypt(sanitisation_data)

    mock_redact_address.assert_called_once_with('filename.pdf')
    assert mock_upload.called
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


@mock_s3
def test_copy_redaction_failed_pdf():
    filename = 'my_dodgy_letter.pdf'
    conn = boto3.resource('s3', region_name=current_app.config['AWS_REGION'])
    bucket = conn.create_bucket(
        Bucket=current_app.config['LETTERS_SCAN_BUCKET_NAME'],
        CreateBucketConfiguration={'LocationConstraint': 'eu-west-1'}
    )
    s3 = boto3.client('s3', region_name=current_app.config['AWS_REGION'])
    s3.put_object(Bucket=current_app.config['LETTERS_SCAN_BUCKET_NAME'], Key=filename, Body=b'pdf_content')

    copy_redaction_failed_pdf(filename)

    assert 'REDACTION_FAILURE/' + filename in [o.key for o in bucket.objects.all()]
    assert filename in [o.key for o in bucket.objects.all()]


@pytest.mark.parametrize("logo_filename", ['hm-government', None])
@pytest.mark.parametrize("key_type,bucket_name", [
    ("test", 'TEST_LETTERS_BUCKET_NAME'), ("normal", 'LETTERS_PDF_BUCKET_NAME')
])
def test_create_pdf_for_templated_letter_happy_path(
    mocker, client, data_for_create_pdf_for_templated_letter_task, key_type, bucket_name, logo_filename
):
    # create a pdf for templated letter using data from API, upload the pdf to the final S3 bucket,
    # and send data back to API so that it can update notification status and billable units.
    mock_upload = mocker.patch('app.celery.tasks.s3upload')
    mock_celery = mocker.patch('app.celery.tasks.notify_celery.send_task')
    mock_logger = mocker.patch('app.celery.tasks.current_app.logger.info')
    mock_logger_exception = mocker.patch('app.celery.tasks.current_app.logger.exception')

    data_for_create_pdf_for_templated_letter_task["logo_filename"] = logo_filename
    data_for_create_pdf_for_templated_letter_task["key_type"] = key_type

    encrypted_data = current_app.encryption_client.encrypt(data_for_create_pdf_for_templated_letter_task)

    create_pdf_for_templated_letter(encrypted_data)

    mock_upload.assert_called_once_with(
        filedata=mocker.ANY,
        region=current_app.config['AWS_REGION'],
        bucket_name=current_app.config[bucket_name],
        file_location='MY_LETTER.PDF',
    )

    mock_celery.assert_called_once_with(
        kwargs={
            "notification_id": 'abc-123',
            "page_count": 1
        },
        name='update-billable-units-for-letter',
        queue='letter-tasks'
    )
    mock_logger.assert_has_calls([
        call("Creating a pdf for notification with id abc-123"),
        call(f"Uploaded letters PDF MY_LETTER.PDF to {current_app.config[bucket_name]} for notification id abc-123")
    ])
    mock_logger_exception.assert_not_called()


def test_create_pdf_for_templated_letter_boto_error(mocker, client, data_for_create_pdf_for_templated_letter_task):
    # handle boto error while uploading file
    mocker.patch('app.celery.tasks.s3upload', side_effect=BotoClientError({}, 'operation-name'))
    mock_celery = mocker.patch('app.celery.tasks.notify_celery.send_task')
    mock_logger = mocker.patch('app.celery.tasks.current_app.logger.info')
    mock_logger_exception = mocker.patch('app.celery.tasks.current_app.logger.exception')

    encrypted_data = current_app.encryption_client.encrypt(data_for_create_pdf_for_templated_letter_task)

    create_pdf_for_templated_letter(encrypted_data)

    assert not mock_celery.called
    mock_logger.assert_called_once_with("Creating a pdf for notification with id abc-123")
    mock_logger_exception.assert_called_once_with(
        "Error uploading MY_LETTER.PDF to pdf bucket for notification abc-123"
    )


def test_create_pdf_for_templated_letter_html_error(
    mocker,
    data_for_create_pdf_for_templated_letter_task
):
    encrypted_data = current_app.encryption_client.encrypt(data_for_create_pdf_for_templated_letter_task)

    weasyprint_html = mocker.Mock()
    expected_exc = werkzeug.exceptions.BadGateway()
    weasyprint_html.write_pdf.side_effect = expected_exc

    mocker.patch('app.celery.tasks.HTML', mocker.Mock(return_value=weasyprint_html))
    mock_retry = mocker.patch('app.celery.tasks.create_pdf_for_templated_letter.retry', side_effect=Retry)

    with pytest.raises(Retry):
        create_pdf_for_templated_letter(encrypted_data)

    mock_retry.assert_called_once_with(exc=expected_exc, queue=QueueNames.SANITISE_LETTERS)
