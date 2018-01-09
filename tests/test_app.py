import json
import os
import copy

import pytest

from app import load_config


@pytest.fixture
def revert_config(app):
    old_config = copy.deepcopy(app.config)
    yield
    app.config = old_config


def test_config_is_loaded(app, revert_config):
    assert app.config['API_KEY'] == 'my-secret-key'

    os.environ['VCAP_SERVICES'] = json.dumps({
        "user-provided": [
            {
                "credentials": {
                    "api_host": "some domain",
                    "api_key": "some secret key"
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

    load_config(app)

    assert app.config['API_KEY'] == 'some secret key'


def test_statds_enabled(app, revert_config):

    os.environ['STATSD_ENABLED'] = "1"

    os.environ['VCAP_SERVICES'] = json.dumps({
        "user-provided": [
            {
                "credentials": {
                    "api_host": "some domain",
                    "api_key": "some secret key"
                },
                "label": "user-provided",
                "name": "notify-template-preview",
                "syslog_drain_url": "",
                "tags": [],
                "volume_mounts": []
            },
            {
                "credentials": {
                    "statsd_prefix": "this_is_a_test_prefix"
                },
                "instance_name": "hosted-graphite",
                "label": "user-provided",
                "name": "hosted-graphite",
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

    load_config(app)

    assert app.config.get('STATSD_ENABLED')
    assert app.config.get('STATSD_HOST') == "statsd.hostedgraphite.com"
    assert app.config.get('STATSD_PORT') == 8125
    assert app.config.get('NOTIFY_ENVIRONMENT') == "preview"
    assert app.config.get('NOTIFY_APP_NAME') == "template-preview"
