from contextlib import contextmanager
from io import BytesIO

import pytest
from botocore.response import StreamingBody
from notifications_utils.s3 import S3ObjectNotFound

from app import create_app


@pytest.fixture(scope="session")
def app():
    yield create_app()


@pytest.fixture
def client(app):
    # every test should have a client instantiated so that log messages don't crash
    app.config["TESTING"] = True

    with app.test_request_context(), app.test_client() as client:
        yield client


@pytest.fixture
def view_letter_template_request_data():
    return {
        "letter_contact_block": "123",
        "template": {
            "id": 1,
            "template_type": "letter",
            "subject": "letter subject",
            "content": "letter content with ((placeholder))",
            "updated_at": "2017-08-01",
            "version": 1,
            "service": "1234",
        },
        "values": {"placeholder": "abc"},
        "filename": "hm-government",
    }


@pytest.fixture
def view_letter_template_request_data_bilingual():
    return {
        "letter_contact_block": "123",
        "template": {
            "id": 1,
            "template_type": "letter",
            "subject": "letter subject",
            "content": "letter content with ((placeholder))",
            "updated_at": "2017-08-01",
            "version": 1,
            "service": "1234",
            "letter_languages": "welsh_then_english",
            "letter_welsh_subject": "Cais stondin beic newydd",
            "letter_welsh_content": "Mae eich cais wedi'i dderbyn.",
        },
        "values": {"placeholder": "abc"},
        "filename": "hm-government",
    }


@pytest.fixture
def data_for_create_pdf_for_templated_letter_task():
    return {
        "letter_contact_block": "123",
        "template": {
            "id": 1,
            "template_type": "letter",
            "letter_languages": "english",
            "subject": "letter subject",
            "content": "letter content with ((placeholder))",
            "letter_welsh_subject": None,
            "letter_welsh_content": None,
            "updated_at": "2017-08-01",
            "version": 1,
            "service": "1234",
        },
        "values": {"placeholder": "abc"},
        "logo_filename": None,
        "letter_filename": "MY_LETTER.PDF",
        "notification_id": "abc-123",
        "key_type": "normal",
    }


@pytest.fixture
def welsh_data_for_create_pdf_for_templated_letter_task():
    return {
        "letter_contact_block": "123",
        "template": {
            "id": 1,
            "template_type": "letter",
            "letter_languages": "welsh_then_english",
            "subject": "letter subject",
            "content": "letter content with ((placeholder))",
            "letter_welsh_subject": "a Welsh subject",
            "letter_welsh_content": "a Welsh body",
            "updated_at": "2017-08-01",
            "version": 1,
            "service": "1234",
        },
        "values": {"placeholder": "abc"},
        "logo_filename": None,
        "letter_filename": "MY_LETTER.PDF",
        "notification_id": "abc-123",
        "key_type": "normal",
    }


@pytest.fixture
def auth_header():
    return {"Authorization": "Token my-secret-key"}


@pytest.fixture(autouse=True)
def mocked_cache_get(mocker):
    return mocker.patch("app.caching_s3download", side_effect=S3ObjectNotFound({}, ""))


@pytest.fixture(autouse=True)
def mocked_cache_set(mocker):
    return mocker.patch("app.s3upload")


@contextmanager
def set_config(app, name, value):
    old_val = app.config.get(name)
    app.config[name] = value
    yield
    app.config[name] = old_val


def s3_response_body(data: bytes = b"\x00"):
    return StreamingBody(BytesIO(data), len(data))


def cache_response_body(data: bytes = b"\x00"):
    return BytesIO(s3_response_body(data).read())
