#!/usr/bin/env python

from app import notify_celery, create_app  # noqa


application = create_app()
application.app_context().push()
