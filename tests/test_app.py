import copy
import pytest


@pytest.fixture
def revert_config(app):
    old_config = copy.deepcopy(app.config)
    yield
    app.config = old_config
