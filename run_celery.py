#!/usr/bin/env python

import notifications_utils.logging.celery as celery_logging

from app.performance import init_performance_monitoring

init_performance_monitoring()

from app import notify_celery, create_app  # noqa


application = create_app()
celery_logging.set_up_logging(application.config)
application.app_context().push()

from celery.signals import worker_process_init
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

@worker_process_init.connect(weak=False)
def init_opentelemetry(*args, **kwargs):
    metrics.set_meter_provider(MeterProvider(metric_readers=[
        PeriodicExportingMetricReader(OTLPMetricExporter()),
        ConsoleMetricExporter(),
    ]))

    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    CeleryInstrumentor().instrument()
