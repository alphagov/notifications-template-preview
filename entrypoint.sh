#!/usr/bin/env bash

set -eu

case "$@" in
  web)
    exec gunicorn --error-logfile - -c /home/vcap/app/gunicorn_config.py wsgi
    ;;
  web-local)
    exec flask run --host=0.0.0.0 -p $PORT
    ;;
  worker)
    exec celery --quiet -A run_celery.notify_celery worker --logfile=/dev/null --concurrency=4
    ;;
  *)
    echo "Running custom command"
    exec $@
    ;;
esac
