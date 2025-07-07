import base64
import logging
from io import BytesIO

import boto3
import pytest
from botocore.exceptions import ClientError as BotoClientError
from celery.exceptions import Retry
from flask import current_app
from moto import mock_s3
from pypdf import PdfReader

import app.celery.tasks
from app.celery.tasks import (
    _create_pdf_for_letter,
    _remove_folder_from_filename,
    create_pdf_for_templated_letter,
    recreate_pdf_for_precompiled_letter,
    sanitise_and_upload_letter,
)
from app.config import QueueNames
from app.weasyprint_hack import WeasyprintError
from tests.pdf_consts import bad_postcode, blank_with_address, multi_page_pdf, no_colour


def test_sanitise_and_upload_valid_letter(mocker, client):
    valid_file = BytesIO(blank_with_address)

    mocker.patch("app.celery.tasks.s3download", return_value=valid_file)
    mock_upload = mocker.patch("app.celery.tasks.s3upload")
    mock_celery = mocker.patch("app.celery.tasks.notify_celery.send_task")
    mock_backup_original = mocker.patch("app.celery.tasks.copy_s3_object")

    sanitise_and_upload_letter("abc-123", "filename.pdf")

    mock_upload.assert_called_once_with(
        filedata=mocker.ANY,
        region=current_app.config["AWS_REGION"],
        bucket_name=current_app.config["SANITISED_LETTER_BUCKET_NAME"],
        file_location="filename.pdf",
    )

    encoded_task_args = current_app.signing_client.encode(
        {
            "page_count": 1,
            "message": None,
            "invalid_pages": None,
            "validation_status": "passed",
            "filename": "filename.pdf",
            "notification_id": "abc-123",
            "address": "Queen Elizabeth\nBuckingham Palace\nLondon\nSW1 1AA",
        }
    )

    mock_celery.assert_called_once_with(
        args=(encoded_task_args,),
        name="process-sanitised-letter",
        queue="letter-tasks",
    )

    mock_backup_original.assert_called_once_with(
        current_app.config["LETTERS_SCAN_BUCKET_NAME"],
        "filename.pdf",
        current_app.config["PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME"],
        "abc-123.pdf",
    )


def test_sanitise_invalid_letter(mocker, client):
    file_with_content_in_margins = BytesIO(no_colour)

    mocker.patch("app.celery.tasks.s3download", return_value=file_with_content_in_margins)
    mock_upload = mocker.patch("app.celery.tasks.s3upload")
    mock_celery = mocker.patch("app.celery.tasks.notify_celery.send_task")

    sanitise_and_upload_letter("abc-123", "filename.pdf")

    encoded_task_args = current_app.signing_client.encode(
        {
            "page_count": 2,
            "message": "content-outside-printable-area",
            "invalid_pages": [1, 2],
            "validation_status": "failed",
            "filename": "filename.pdf",
            "notification_id": "abc-123",
            "address": None,
        }
    )

    assert not mock_upload.called
    mock_celery.assert_called_once_with(
        args=(encoded_task_args,),
        name="process-sanitised-letter",
        queue="letter-tasks",
    )


@pytest.mark.parametrize(
    "extra_args, expected_error",
    (
        ({}, "not-a-real-uk-postcode"),
        ({"allow_international_letters": False}, "not-a-real-uk-postcode"),
        ({"allow_international_letters": True}, "not-a-real-uk-postcode-or-country"),
    ),
)
def test_sanitise_international_letters(
    mocker,
    client,
    extra_args,
    expected_error,
):
    mocker.patch("app.celery.tasks.s3download", return_value=BytesIO(bad_postcode))
    mock_upload = mocker.patch("app.celery.tasks.s3upload")
    mock_celery = mocker.patch("app.celery.tasks.notify_celery.send_task")

    sanitise_and_upload_letter("abc-123", "filename.pdf", **extra_args)

    encoded_task_args = current_app.signing_client.encode(
        {
            "page_count": 1,
            "message": expected_error,
            "invalid_pages": [1],
            "validation_status": "failed",
            "filename": "filename.pdf",
            "notification_id": "abc-123",
            "address": None,
        }
    )

    assert not mock_upload.called
    mock_celery.assert_called_once_with(
        args=(encoded_task_args,),
        name="process-sanitised-letter",
        queue="letter-tasks",
    )


def test_sanitise_and_upload_letter_raises_a_boto_error(mocker, client, caplog):
    mocker.patch("app.celery.tasks.s3download", side_effect=BotoClientError({}, "operation-name"))
    mock_upload = mocker.patch("app.celery.tasks.s3upload")
    mock_celery = mocker.patch("app.celery.tasks.notify_celery.send_task")

    filename = "filename.pdf"
    notification_id = "abc-123"

    with caplog.at_level(logging.ERROR):
        sanitise_and_upload_letter(notification_id, filename)

    assert not mock_upload.called
    assert not mock_celery.called

    assert (
        "Error downloading filename.pdf from scan bucket or uploading to sanitise bucket for notification abc-123"
        in caplog.messages
    )


@pytest.mark.parametrize("logo_filename", ["hm-government", None])
@pytest.mark.parametrize(
    "key_type,bucket_name",
    [("test", "TEST_LETTERS_BUCKET_NAME"), ("normal", "LETTERS_PDF_BUCKET_NAME")],
)
def test_create_pdf_for_templated_letter_happy_path(
    mocker,
    client,
    data_for_create_pdf_for_templated_letter_task,
    key_type,
    bucket_name,
    logo_filename,
    caplog,
):
    # create a pdf for templated letter using data from API, upload the pdf to the final S3 bucket,
    # and send data back to API so that it can update notification status and billable units.
    mock_upload = mocker.patch("app.celery.tasks.s3upload")
    mock_celery = mocker.patch("app.celery.tasks.notify_celery.send_task")

    data_for_create_pdf_for_templated_letter_task["logo_filename"] = logo_filename
    data_for_create_pdf_for_templated_letter_task["key_type"] = key_type

    encoded_data = current_app.signing_client.encode(data_for_create_pdf_for_templated_letter_task)

    with caplog.at_level(logging.INFO):
        create_pdf_for_templated_letter(encoded_data)

    mock_upload.assert_called_once_with(
        filedata=mocker.ANY,
        region=current_app.config["AWS_REGION"],
        bucket_name=current_app.config[bucket_name],
        file_location="MY_LETTER.PDF",
        metadata=None,
    )

    mock_celery.assert_called_once_with(
        kwargs={"notification_id": "abc-123", "page_count": 1},
        name="update-billable-units-for-letter",
        queue="letter-tasks",
    )
    assert "Creating a pdf for notification with id abc-123" in caplog.messages
    assert (
        f"Uploaded letters PDF MY_LETTER.PDF to {current_app.config[bucket_name]} for notification id abc-123"
        in caplog.messages
    )

    assert not any(r.levelname == "ERROR" for r in caplog.records)
    assert "NOTIFY" in PdfReader(mock_upload.call_args_list[0][1]["filedata"]).pages[0].extract_text()


def test_create_pdf_for_templated_letter_includes_welsh_pages_if_provided(
    mocker,
    client,
    caplog,
    welsh_data_for_create_pdf_for_templated_letter_task,
):
    # create a pdf for templated letter using data from API, upload the pdf to the final S3 bucket,
    # and send data back to API so that it can update notification status and billable units.
    mock_upload = mocker.patch("app.celery.tasks.s3upload")
    mock_celery = mocker.patch("app.celery.tasks.notify_celery.send_task")
    mock_create_pdf = mocker.patch("app.celery.tasks._create_pdf_for_letter", wraps=_create_pdf_for_letter)

    encoded_data = current_app.signing_client.encode(welsh_data_for_create_pdf_for_templated_letter_task)

    with caplog.at_level(logging.INFO):
        create_pdf_for_templated_letter(encoded_data)

    mock_upload.assert_called_once_with(
        filedata=mocker.ANY,
        region=current_app.config["AWS_REGION"],
        bucket_name=current_app.config["LETTERS_PDF_BUCKET_NAME"],
        file_location="MY_LETTER.PDF",
        metadata=None,
    )

    mock_celery.assert_called_once_with(
        kwargs={"notification_id": "abc-123", "page_count": 2},
        name="update-billable-units-for-letter",
        queue="letter-tasks",
    )
    assert "Creating a pdf for notification with id abc-123" in caplog.messages
    assert (
        f"Uploaded letters PDF MY_LETTER.PDF to {current_app.config['LETTERS_PDF_BUCKET_NAME']} for "
        "notification id abc-123" in caplog.messages
    )

    assert mock_create_pdf.call_args_list == [
        mocker.call(mocker.ANY, mocker.ANY, language="welsh", includes_first_page=True),
        mocker.call(mocker.ANY, mocker.ANY, language="english", includes_first_page=False),
    ]

    assert not any(r.levelname == "ERROR" for r in caplog.records)


def test_create_pdf_for_templated_letter_adds_letter_attachment_if_provided(
    mocker,
    client,
    data_for_create_pdf_for_templated_letter_task,
):
    # create a pdf for templated letter using data from API, upload the pdf to the final S3 bucket,
    # and send data back to API so that it can update notification status and billable units.
    mock_upload = mocker.patch("app.celery.tasks.s3upload")
    mock_celery = mocker.patch("app.celery.tasks.notify_celery.send_task")
    mock_convert_pdf_to_cmyk = mocker.patch("app.templated.convert_pdf_to_cmyk")
    mock_add_attachment = mocker.patch(
        "app.templated.add_attachment_to_letter",
        return_value=BytesIO(multi_page_pdf),
    )

    data_for_create_pdf_for_templated_letter_task["template"]["letter_attachment"] = {"page_count": 1, "id": "5678"}

    encoded_data = current_app.signing_client.encode(data_for_create_pdf_for_templated_letter_task)

    create_pdf_for_templated_letter(encoded_data)

    mock_add_attachment.assert_called_once_with(
        service_id="1234",
        templated_letter_pdf=mock_convert_pdf_to_cmyk.return_value,
        attachment_object=data_for_create_pdf_for_templated_letter_task["template"]["letter_attachment"],
    )

    assert mock_upload.call_args.kwargs["filedata"] == mock_add_attachment.return_value
    # make sure we're recalculating the page count from the return value of add_attachment
    # rather than just adding the letter_attachment["page_count"] value or anything
    # (multi_page_pdf is 10 pages long)
    assert mock_celery.call_args.kwargs["kwargs"]["page_count"] == 10
    assert mock_celery.call_args.kwargs["name"] == "update-billable-units-for-letter"


def test_create_pdf_for_templated_letter_errors_if_attachment_pushes_over_page_count(
    mocker,
    client,
    data_for_create_pdf_for_templated_letter_task,
):
    # try stitching a 10 page attachment to a 1 page template
    mocker.patch("app.letter_attachments.get_attachment_pdf", return_value=BytesIO(multi_page_pdf))
    mock_upload = mocker.patch("app.celery.tasks.s3upload")
    mock_celery = mocker.patch("app.celery.tasks.notify_celery.send_task")

    data_for_create_pdf_for_templated_letter_task["template"]["letter_attachment"] = {"page_count": 10, "id": "5678"}

    encoded_data = current_app.signing_client.encode(data_for_create_pdf_for_templated_letter_task)

    create_pdf_for_templated_letter(encoded_data)

    assert mock_upload.call_args.kwargs["bucket_name"] == current_app.config["INVALID_PDF_BUCKET_NAME"]
    assert mock_upload.call_args.kwargs["metadata"] == {
        "validation_status": "failed",
        "message": "letter-too-long",
        "page_count": "11",
    }
    assert mock_celery.call_args.kwargs["name"] == "update-validation-failed-for-templated-letter"


def test_create_pdf_for_templated_letter_boto_error(
    mocker, client, data_for_create_pdf_for_templated_letter_task, caplog
):
    # handle boto error while uploading file
    mocker.patch("app.celery.tasks.s3upload", side_effect=BotoClientError({}, "operation-name"))
    mock_celery = mocker.patch("app.celery.tasks.notify_celery.send_task")

    encoded_data = current_app.signing_client.encode(data_for_create_pdf_for_templated_letter_task)

    with caplog.at_level(logging.INFO):
        create_pdf_for_templated_letter(encoded_data)

    assert not mock_celery.called

    assert "Creating a pdf for notification with id abc-123" in caplog.messages
    assert "Error uploading MY_LETTER.PDF to pdf bucket for notification abc-123" in caplog.messages


def test_create_pdf_for_templated_letter_when_letter_is_too_long(
    mocker, client, data_for_create_pdf_for_templated_letter_task, caplog
):
    # create a pdf for templated letter using data from API, upload the pdf to the final S3 bucket,
    # and send data back to API so that it can update notification status and billable units.
    mock_upload = mocker.patch("app.celery.tasks.s3upload")
    mock_celery = mocker.patch("app.celery.tasks.notify_celery.send_task")
    mocker.patch("app.celery.tasks.get_page_count_for_pdf", return_value=11)

    data_for_create_pdf_for_templated_letter_task["logo_filename"] = "hm-government"
    data_for_create_pdf_for_templated_letter_task["key_type"] = "normal"

    encoded_data = current_app.signing_client.encode(data_for_create_pdf_for_templated_letter_task)

    with caplog.at_level(logging.INFO):
        create_pdf_for_templated_letter(encoded_data)

    mock_upload.assert_called_once_with(
        filedata=mocker.ANY,
        region=current_app.config["AWS_REGION"],
        bucket_name=current_app.config["INVALID_PDF_BUCKET_NAME"],
        file_location="MY_LETTER.PDF",
        metadata={
            "validation_status": "failed",
            "message": "letter-too-long",
            "page_count": "11",
        },
    )

    mock_celery.assert_called_once_with(
        kwargs={"notification_id": "abc-123", "page_count": 11},
        name="update-validation-failed-for-templated-letter",
        queue="letter-tasks",
    )
    assert "Creating a pdf for notification with id abc-123" in caplog.messages
    assert (
        f"Uploaded letters PDF MY_LETTER.PDF to {current_app.config['INVALID_PDF_BUCKET_NAME']} "
        "for notification id abc-123"
    ) in caplog.messages
    assert not any(r.levelname == "ERROR" for r in caplog.records)


def test_create_pdf_for_templated_letter_html_error(mocker, data_for_create_pdf_for_templated_letter_task, client):
    encoded_data = current_app.signing_client.encode(data_for_create_pdf_for_templated_letter_task)

    weasyprint_html = mocker.Mock()
    expected_exc = WeasyprintError()
    weasyprint_html.write_pdf.side_effect = expected_exc

    mocker.patch("app.celery.tasks.HTML", mocker.Mock(return_value=weasyprint_html))
    mock_retry = mocker.patch("app.celery.tasks.create_pdf_for_templated_letter.retry", side_effect=Retry)

    with pytest.raises(Retry):
        create_pdf_for_templated_letter(encoded_data)

    mock_retry.assert_called_once_with(exc=expected_exc, queue=QueueNames.SANITISE_LETTERS)


@mock_s3
def test_recreate_pdf_for_precompiled_letter(mocker, client):
    # create backup S3 bucket and an S3 bucket for the final letters that will be sent to DVLA
    conn = boto3.resource("s3", region_name=current_app.config["AWS_REGION"])
    backup_bucket = conn.create_bucket(
        Bucket=current_app.config["PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME"],
        CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
    )
    final_letters_bucket = conn.create_bucket(
        Bucket=current_app.config["LETTERS_PDF_BUCKET_NAME"],
        CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
    )

    # put a valid PDF in the backup S3 bucket
    valid_file = BytesIO(blank_with_address)
    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.put_object(
        Bucket=current_app.config["PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME"],
        Key="1234-abcd.pdf",
        Body=valid_file.read(),
    )

    sanitise_spy = mocker.spy(app.celery.tasks, "sanitise_file_contents")

    recreate_pdf_for_precompiled_letter("1234-abcd", "2021-10-10/NOTIFY.REF.D.2.C.202110101330.PDF", True)

    # backup PDF still exists in the backup bucket
    assert [o.key for o in backup_bucket.objects.all()] == ["1234-abcd.pdf"]
    # the final letters bucket contains the recreated PDF
    assert [o.key for o in final_letters_bucket.objects.all()] == ["2021-10-10/NOTIFY.REF.D.2.C.202110101330.PDF"]

    # Check that the file in the final letters bucket has been through the `sanitise_file_contents` function
    sanitised_file_contents = (
        conn.Object(
            current_app.config["LETTERS_PDF_BUCKET_NAME"],
            "2021-10-10/NOTIFY.REF.D.2.C.202110101330.PDF",
        )
        .get()["Body"]
        .read()
    )
    assert base64.b64decode(sanitise_spy.spy_return["file"].encode()) == sanitised_file_contents


@mock_s3
def test_recreate_pdf_for_precompiled_letter_with_s3_error(client, caplog):
    # create the backup S3 bucket, which is empty so will cause an error when attempting to download the file
    conn = boto3.resource("s3", region_name=current_app.config["AWS_REGION"])
    conn.create_bucket(
        Bucket=current_app.config["PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME"],
        CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
    )

    with caplog.at_level(logging.ERROR):
        recreate_pdf_for_precompiled_letter("1234-abcd", "2021-10-10/NOTIFY.REF.D.2.C.202110101330.PDF", True)

    assert (
        "Error downloading file from backup bucket or uploading to letters-pdf bucket for notification 1234-abcd"
        in caplog.messages
    )


@mock_s3
def test_recreate_pdf_for_precompiled_letter_that_fails_validation(client, caplog):
    # create backup S3 bucket and an S3 bucket for the final letters that will be sent to DVLA
    conn = boto3.resource("s3", region_name=current_app.config["AWS_REGION"])
    backup_bucket = conn.create_bucket(
        Bucket=current_app.config["PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME"],
        CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
    )
    final_letters_bucket = conn.create_bucket(
        Bucket=current_app.config["LETTERS_PDF_BUCKET_NAME"],
        CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
    )

    # put an invalid PDF in the backup S3 bucket so that it fails sanitisation
    invalid_file = BytesIO(bad_postcode)
    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.put_object(
        Bucket=current_app.config["PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME"],
        Key="1234-abcd.pdf",
        Body=invalid_file.read(),
    )

    with caplog.at_level(logging.ERROR):
        recreate_pdf_for_precompiled_letter("1234-abcd", "2021-10-10/NOTIFY.REF.D.2.C.202110101330.PDF", True)

    # the original file has not been copied or moved
    assert [o.key for o in backup_bucket.objects.all()] == ["1234-abcd.pdf"]
    assert len(list(final_letters_bucket.objects.all())) == 0

    assert "Notification failed resanitisation: 1234-abcd" in caplog.messages


@pytest.mark.parametrize(
    "filename, expected_filename",
    [
        ("2018-01-13/NOTIFY.ABCDEF1234567890.PDF", "NOTIFY.ABCDEF1234567890.PDF"),
        ("NOTIFY.ABCDEF1234567890.PDF", "NOTIFY.ABCDEF1234567890.PDF"),
    ],
)
def test_remove_folder_from_filename(filename, expected_filename):
    actual_filename = _remove_folder_from_filename(filename)
    assert actual_filename == expected_filename


@pytest.mark.parametrize("includes_first_page", (True, False))
def test_create_pdf_for_letter_notify_tagging(client, includes_first_page):
    pdf = _create_pdf_for_letter(
        task=None,
        letter_details={
            "template": {"template_type": "letter", "subject": "subject", "content": "content"},
            "values": {},
            "letter_contact_block": "",
            "logo_filename": "",
        },
        language="english",
        includes_first_page=includes_first_page,
    )

    assert ("NOTIFY" in PdfReader(pdf).pages[0].extract_text()) is includes_first_page
