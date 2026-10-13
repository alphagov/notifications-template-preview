import os

from notifications_utils.gunicorn.defaults import set_gunicorn_defaults

set_gunicorn_defaults(globals())


workers = 5
worker_class = "notifications_utils.gunicorn.eventlet.OtelAwareEventletWorker"
timeout = int(os.getenv("HTTP_SERVE_TIMEOUT_SECONDS", 30))

max_requests = 10
