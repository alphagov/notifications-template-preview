import importlib
import os

import pytest

from app import config


@pytest.fixture
def reload_config(os_environ):
    # Needs to be set again due to os_environ
    os.environ['NOTIFY_ENVIRONMENT'] = 'test'

    yield
    importlib.reload(config)


def test_load_config(reload_config):
    os.environ['SECRET_KEY'] = 'env'
    importlib.reload(config)

    assert os.environ['SECRET_KEY'] == 'env'
    assert config.Config.SECRET_KEY == 'env'
