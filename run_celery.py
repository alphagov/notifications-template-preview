#!/usr/bin/env python

import os

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration

from app import create_app, notify_celery  # noqa

if 'SENTRY_DSN' in os.environ:
    sentry_sdk.init(
        dsn=os.environ['SENTRY_DSN'],
        integrations=[CeleryIntegration()],
        environment=os.environ['NOTIFY_ENVIRONMENT'],
        attach_stacktrace=True,
        traces_sample_rate=0.00005  # avoid exceeding rate limits in Production
    )

application = create_app()
application.app_context().push()
