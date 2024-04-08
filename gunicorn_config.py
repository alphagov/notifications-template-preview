from notifications_utils.gunicorn_defaults import set_gunicorn_defaults

set_gunicorn_defaults(globals())


workers = 5
timeout = 120

max_requests = 10
