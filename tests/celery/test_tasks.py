import base64
from io import BytesIO
from unittest.mock import call

import boto3
import pytest
from botocore.exceptions import ClientError as BotoClientError
from celery.exceptions import Retry
from flask import current_app
from moto import mock_s3

import app.celery.tasks
from app import QueueNames
from app.celery.tasks import (
    _remove_folder_from_filename,
    copy_redaction_failed_pdf,
    create_pdf_for_templated_letter,
    recreate_pdf_for_precompiled_letter,
    sanitise_and_upload_letter,
)
from app.weasyprint_hack import WeasyprintError
from tests.pdf_consts import bad_postcode, blank_with_address, no_colour


def test_sanitise_and_upload_valid_letter(mocker, client):
    valid_file = BytesIO(blank_with_address)

    mocker.patch('app.celery.tasks.s3download', return_value=valid_file)
    mock_upload = mocker.patch('app.celery.tasks.s3upload')
    mock_celery = mocker.patch('app.celery.tasks.notify_celery.send_task')
    mock_redact_address = mocker.patch('app.celery.tasks.copy_redaction_failed_pdf')
    mock_backup_original = mocker.patch('app.celery.tasks.copy_s3_object')

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

    mock_backup_original.assert_called_once_with(
        current_app.config['LETTERS_SCAN_BUCKET_NAME'], 'filename.pdf',
        current_app.config['PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME'], 'abc-123.pdf'
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
def test_copy_redaction_failed_pdf(client):
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
        metadata=None
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


def test_create_pdf_for_templated_letter_when_letter_is_too_long(
    mocker, client, data_for_create_pdf_for_templated_letter_task
):
    # create a pdf for templated letter using data from API, upload the pdf to the final S3 bucket,
    # and send data back to API so that it can update notification status and billable units.
    mock_upload = mocker.patch('app.celery.tasks.s3upload')
    mock_celery = mocker.patch('app.celery.tasks.notify_celery.send_task')
    mock_logger = mocker.patch('app.celery.tasks.current_app.logger.info')
    mock_logger_exception = mocker.patch('app.celery.tasks.current_app.logger.exception')
    mocker.patch('app.celery.tasks.get_page_count', return_value=11)

    data_for_create_pdf_for_templated_letter_task["logo_filename"] = 'hm-government'
    data_for_create_pdf_for_templated_letter_task["key_type"] = 'normal'

    encrypted_data = current_app.encryption_client.encrypt(data_for_create_pdf_for_templated_letter_task)

    create_pdf_for_templated_letter(encrypted_data)
    mock_upload.assert_called_once_with(
        filedata=mocker.ANY,
        region=current_app.config['AWS_REGION'],
        bucket_name=current_app.config['INVALID_PDF_BUCKET_NAME'],
        file_location='MY_LETTER.PDF',
        metadata={'validation_status': 'failed', 'message': 'letter-too-long', 'page_count': '11'}
    )

    mock_celery.assert_called_once_with(
        kwargs={
            "notification_id": 'abc-123',
            "page_count": 11
        },
        name='update-validation-failed-for-templated-letter',
        queue='letter-tasks'
    )
    mock_logger.assert_has_calls([
        call("Creating a pdf for notification with id abc-123"),
        call(f"Uploaded letters PDF MY_LETTER.PDF to {current_app.config['INVALID_PDF_BUCKET_NAME']} "
             f"for notification id abc-123")
    ])
    mock_logger_exception.assert_not_called()


def test_create_pdf_for_templated_letter_html_error(
    mocker,
    data_for_create_pdf_for_templated_letter_task,
    client
):
    encrypted_data = current_app.encryption_client.encrypt(data_for_create_pdf_for_templated_letter_task)

    weasyprint_html = mocker.Mock()
    expected_exc = WeasyprintError()
    weasyprint_html.write_pdf.side_effect = expected_exc

    mocker.patch('app.celery.tasks.HTML', mocker.Mock(return_value=weasyprint_html))
    mock_retry = mocker.patch('app.celery.tasks.create_pdf_for_templated_letter.retry', side_effect=Retry)

    with pytest.raises(Retry):
        create_pdf_for_templated_letter(encrypted_data)

    mock_retry.assert_called_once_with(exc=expected_exc, queue=QueueNames.SANITISE_LETTERS)


@mock_s3
def test_recreate_pdf_for_precompiled_letter(mocker, client):
    # create backup S3 bucket and an S3 bucket for the final letters that will be sent to DVLA
    conn = boto3.resource('s3', region_name=current_app.config['AWS_REGION'])
    backup_bucket = conn.create_bucket(
        Bucket=current_app.config['PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME'],
        CreateBucketConfiguration={'LocationConstraint': 'eu-west-1'}
    )
    final_letters_bucket = conn.create_bucket(
        Bucket=current_app.config['LETTERS_PDF_BUCKET_NAME'],
        CreateBucketConfiguration={'LocationConstraint': 'eu-west-1'}
    )

    # put a valid PDF in the backup S3 bucket
    valid_file = BytesIO(blank_with_address)
    s3 = boto3.client('s3', region_name='eu-west-1')
    s3.put_object(
        Bucket=current_app.config['PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME'],
        Key='1234-abcd.pdf',
        Body=valid_file.read()
    )

    sanitise_spy = mocker.spy(app.celery.tasks, 'sanitise_file_contents')

    recreate_pdf_for_precompiled_letter('1234-abcd', '2021-10-10/NOTIFY.REF.D.2.C.202110101330.PDF', True)

    # backup PDF still exists in the backup bucket
    assert [o.key for o in backup_bucket.objects.all()] == ['1234-abcd.pdf']
    # the final letters bucket contains the recreated PDF
    assert [o.key for o in final_letters_bucket.objects.all()] == ['2021-10-10/NOTIFY.REF.D.2.C.202110101330.PDF']

    # Check that the file in the final letters bucket has been through the `sanitise_file_contents` function
    sanitised_file_contents = conn.Object(
        current_app.config['LETTERS_PDF_BUCKET_NAME'],
        '2021-10-10/NOTIFY.REF.D.2.C.202110101330.PDF'
    ).get()['Body'].read()
    assert base64.b64decode(sanitise_spy.spy_return['file'].encode()) == sanitised_file_contents


@mock_s3
def test_recreate_pdf_for_precompiled_letter_with_s3_error(mocker, client):
    # create the backup S3 bucket, which is empty so will cause an error when attempting to download the file
    conn = boto3.resource('s3', region_name=current_app.config['AWS_REGION'])
    conn.create_bucket(
        Bucket=current_app.config['PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME'],
        CreateBucketConfiguration={'LocationConstraint': 'eu-west-1'}
    )

    mock_logger_exception = mocker.patch('app.celery.tasks.current_app.logger.exception')

    recreate_pdf_for_precompiled_letter('1234-abcd', '2021-10-10/NOTIFY.REF.D.2.C.202110101330.PDF', True)

    mock_logger_exception.assert_called_once_with(
        "Error downloading file from backup bucket or uploading to letters-pdf bucket for notification 1234-abcd"
    )


@mock_s3
def test_recreate_pdf_for_precompiled_letter_that_fails_validation(mocker, client):
    # create backup S3 bucket and an S3 bucket for the final letters that will be sent to DVLA
    conn = boto3.resource('s3', region_name=current_app.config['AWS_REGION'])
    backup_bucket = conn.create_bucket(
        Bucket=current_app.config['PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME'],
        CreateBucketConfiguration={'LocationConstraint': 'eu-west-1'}
    )
    final_letters_bucket = conn.create_bucket(
        Bucket=current_app.config['LETTERS_PDF_BUCKET_NAME'],
        CreateBucketConfiguration={'LocationConstraint': 'eu-west-1'}
    )

    # put an invalid PDF in the backup S3 bucket so that it fails sanitisation
    invalid_file = BytesIO(bad_postcode)
    s3 = boto3.client('s3', region_name='eu-west-1')
    s3.put_object(
        Bucket=current_app.config['PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME'],
        Key='1234-abcd.pdf',
        Body=invalid_file.read()
    )

    mock_logger_error = mocker.patch('app.celery.tasks.current_app.logger.error')

    recreate_pdf_for_precompiled_letter('1234-abcd', '2021-10-10/NOTIFY.REF.D.2.C.202110101330.PDF', True)

    # the original file has not been copied or moved
    assert [o.key for o in backup_bucket.objects.all()] == ['1234-abcd.pdf']
    assert len([x for x in final_letters_bucket.objects.all()]) == 0

    mock_logger_error.assert_called_once_with("Notification failed resanitisation: 1234-abcd")


@pytest.mark.parametrize("filename, expected_filename",
                         [('2018-01-13/NOTIFY.ABCDEF1234567890.PDF',
                           'NOTIFY.ABCDEF1234567890.PDF'),
                          ('NOTIFY.ABCDEF1234567890.PDF',
                           'NOTIFY.ABCDEF1234567890.PDF'),
                          ])
def test_remove_folder_from_filename(filename, expected_filename):
    actual_filename = _remove_folder_from_filename(filename)
    assert actual_filename == expected_filename
