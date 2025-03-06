from gunicorn_config import max_requests, timeout, workers


def test_gunicorn_config():
    assert max_requests == 10
    assert timeout == 30
    assert workers == 5
