import importlib
import os

import pytest

from app import config


@pytest.fixture
def os_environ():
    old_env = os.environ.copy()
    yield

    os.environ.clear()
    for k, v in old_env.items():
        os.environ[k] = v


@pytest.fixture
def reload_config(os_environ):
    yield
    importlib.reload(config)


def test_load_config(reload_config):
    os.environ['SECRET_KEY'] = 'env'
    importlib.reload(config)

    assert os.environ['SECRET_KEY'] == 'env'
    assert config.Config.SECRET_KEY == 'env'
