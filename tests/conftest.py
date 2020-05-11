import os
from contextlib import contextmanager

import pytest
from notifications_utils.s3 import S3ObjectNotFound

from app import create_app


@pytest.fixture(scope='session')
def app():
    os.environ['TEMPLATE_PREVIEW_INTERNAL_SECRETS'] = '["my-secret-key", "my-secret-key2"]'
    yield create_app()


@pytest.fixture(autouse=True, scope='session')
def client(app):
    # every test should have a client instantiated so that log messages don't crash
    app.config['TESTING'] = True

    with app.test_request_context(), app.test_client() as client:
        yield client


@pytest.fixture
def preview_post_body():
    return {
        'letter_contact_block': '123',
        'template': {
            'id': 1,
            'template_type': 'letter',
            'subject': 'letter subject',
            'content': 'letter content with ((placeholder))',
            "updated_at": "2017-08-01",
            'version': 1
        },
        'values': {'placeholder': 'abc'},
        'filename': 'hm-government',
    }


@pytest.fixture
def data_for_create_pdf_for_templated_letter_task():
    return {
        'letter_contact_block': '123',
        'template': {
            'id': 1,
            'template_type': 'letter',
            'subject': 'letter subject',
            'content': 'letter content with ((placeholder))',
            "updated_at": "2017-08-01",
            'version': 1
        },
        'values': {'placeholder': 'abc'},
        'logo_filename': None,
        'letter_filename': 'MY_LETTER.PDF',
        "notification_id": 'abc-123',
        'key_type': "normal"
    }


@pytest.fixture
def auth_header():
    return {'Authorization': 'Token my-secret-key'}


@pytest.fixture(autouse=True)
def mocked_cache_get(mocker):
    return mocker.patch('app.s3download', side_effect=S3ObjectNotFound({}, ''))


@pytest.fixture(autouse=True)
def mocked_cache_set(mocker):
    return mocker.patch('app.s3upload')


@contextmanager
def set_config(app, name, value):
    old_val = app.config.get(name)
    app.config[name] = value
    yield
    app.config[name] = old_val
