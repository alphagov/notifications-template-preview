import importlib
import os

import pytest

from app import config


def cf_conf():
    os.environ['SECRET_KEY'] = 'abc'


@pytest.fixture
def reload_config(os_environ):
    # Needs to be set again due to os_environ
    os.environ['NOTIFY_ENVIRONMENT'] = 'test'

    yield
    importlib.reload(config)


def test_load_cloudfoundry_config_if_available(reload_config, mocker):
    os.environ['SECRET_KEY'] = 'env'
    os.environ['VCAP_APPLICATION'] = 'some json blob'

    cf_extract = mocker.patch(
        'app.cloudfoundry_config.extract_cloudfoundry_config',
        side_effect=cf_conf
    )

    # reload config so that its module level code (ie: all of it) is re-instantiated
    importlib.reload(config)
    assert cf_extract.called

    assert os.environ['SECRET_KEY'] == 'abc'
    assert config.Config.SECRET_KEY == 'abc'


def test_load_config_if_cloudfoundry_not_available(reload_config, mocker):
    os.environ['SECRET_KEY'] = 'env'
    os.environ.pop('VCAP_SERVICES', None)

    cf_extract = mocker.patch(
        'app.cloudfoundry_config.extract_cloudfoundry_config',
        side_effect=cf_conf
    )

    # reload config so that its module level code (ie: all of it) is re-instantiated
    importlib.reload(config)
    assert not cf_extract.called

    assert os.environ['SECRET_KEY'] == 'env'
    assert config.Config.SECRET_KEY == 'env'
