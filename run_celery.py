#!/usr/bin/env python

import os

import notifications_utils.logging.celery as celery_logging
from celery.signals import worker_process_init
from notifications_utils.semconv import set_service_instance_id
from opentelemetry.instrumentation import auto_instrumentation

from app.performance import init_performance_monitoring

init_performance_monitoring()

from app import notify_celery, create_app  # noqa


application = create_app()
celery_logging.set_up_logging(application.config)


@worker_process_init.connect
def init_worker(**_) -> None:
    if os.environ.get("OTEL_SERVICE_NAME") is not None:
        set_service_instance_id()
        auto_instrumentation.initialize()
