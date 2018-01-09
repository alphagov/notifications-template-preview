import json
import os

import pytest

from app import create_app


@pytest.fixture(scope='session')
def app():

    os.environ['STATSD_ENABLED'] = "0"

    os.environ['VCAP_SERVICES'] = json.dumps({
        "user-provided": [
            {
                "credentials": {
                    "api_host": "some domain",
                    "api_key": "my-secret-key"
                },
                "label": "user-provided",
                "name": "notify-template-preview",
                "syslog_drain_url": "",
                "tags": [],
                "volume_mounts": []
            },
            {
                "credentials": {
                    "aws_access_key_id": "access_key",
                    "aws_secret_access_key": "secret_key",
                    "sqs_queue_prefix": "preview"
                },
                "label": "user-provided",
                "name": "notify-aws",
                "syslog_drain_url": "",
                "tags": [],
                "volume_mounts": []
            }
        ]
    })
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
            'subject': 'letter subject',
            'content': 'letter content with ((placeholder))',
        },
        'values': {'placeholder': 'abc'},
        'dvla_org_id': '001',
    }


@pytest.fixture
def auth_header():
    return {'Authorization': 'Token my-secret-key'}
