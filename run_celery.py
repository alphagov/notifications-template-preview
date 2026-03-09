#!/usr/bin/env python

import notifications_utils.logging.celery as celery_logging

from app.performance import init_performance_monitoring

init_performance_monitoring()

from app import notify_celery, create_app  # noqa


application = create_app()
celery_logging.set_up_logging(application.config)
