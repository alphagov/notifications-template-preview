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
