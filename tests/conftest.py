import os

import pytest

from notifications_utils.s3 import S3ObjectNotFound

from app import create_app


@pytest.fixture(scope='session')
def app():
    os.environ['TEMPLATE_PREVIEW_API_KEY'] = "my-secret-key"
    yield create_app()


@pytest.fixture
def client(app):
    with app.test_request_context(), app.test_client() as client:
        yield client


@pytest.fixture
def preview_post_body():
    return {
        'letter_contact_block': '123',
        'template': {
            'id': 1,
            'subject': 'letter subject',
            'content': 'letter content with ((placeholder))',
            "updated_at": "2017-08-01",
            'version': 1
        },
        'values': {'placeholder': 'abc'},
        'dvla_org_id': '001',
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
