import os

from notifications_utils.gunicorn.defaults import set_gunicorn_defaults

set_gunicorn_defaults(globals())


workers = 5
timeout = int(os.getenv("HTTP_SERVE_TIMEOUT_SECONDS", 30))

max_requests = 10
