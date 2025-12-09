#!/usr/bin/env bash

set -eu

CONCURRENCY=${CONCURRENCY:-4}

case "$@" in
  web)
    exec gunicorn --error-logfile - -c /home/vcap/app/gunicorn_config.py wsgi
    ;;
  web-local)
    exec flask run --host=0.0.0.0 -p $PORT
    ;;
  worker)
    exec opentelemetry-instrument \
      --metrics_exporter console,otlp \
      --traces_exporter console,otlp \
      celery --quiet -A run_celery.notify_celery worker --concurrency="$CONCURRENCY"
    ;;
  *)
    echo "Running custom command"
    exec $@
    ;;
esac
