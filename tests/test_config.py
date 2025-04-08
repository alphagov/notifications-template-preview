import importlib
import os

import pytest

from app import config
from app.config import QueueNames


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
    os.environ["SECRET_KEY"] = "env"
    importlib.reload(config)

    assert os.environ["SECRET_KEY"] == "env"
    assert config.Config.SECRET_KEY == "env"


def test_predefined_queues():
    prefix = "test-prefix-"
    aws_region = "eu-west-1"
    aws_account_id = "123456789012"

    class_queues = [
        value for key, value in vars(QueueNames).items() if not key.startswith("_") and isinstance(value, str)
    ]
    predefined_queues = QueueNames.predefined_queues(prefix, aws_region, aws_account_id)

    assert len(predefined_queues) == len(class_queues)

    for queue_name in class_queues:
        full_queue_name = f"{prefix}{queue_name}"
        assert full_queue_name in predefined_queues
        assert (
            predefined_queues[full_queue_name]["url"]
            == f"https://sqs.{aws_region}.amazonaws.com/{aws_account_id}/{full_queue_name}"
        )
