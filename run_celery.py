#!/usr/bin/env python

from app.performance import init_performance_monitoring

init_performance_monitoring()

from app import notify_celery, create_app  # noqa


application = create_app()
application.app_context().push()
