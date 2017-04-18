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
