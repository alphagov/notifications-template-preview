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
            }
        ]
    })

    load_config(app)

    assert app.config.get('STATSD_ENABLED') == 1
    assert app.config.get('STATSD_HOST') == "localhost"
    assert app.config.get('STATSD_PORT') == 1000
    assert app.config.get('STATSD_PREFIX') == "this_is_a_test_prefix"
