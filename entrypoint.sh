#!/usr/bin/env bash

set -eu

case "$@" in
  web)
    gunicorn --error-logfile - -c /home/vcap/app/gunicorn_config.py wsgi
    ;;
  web-local)
    flask run --host=0.0.0.0 -p $PORT
    ;;
  worker)
    celery -A run_celery.notify_celery worker --loglevel=INFO --concurrency=4 --uid=`id -u celeryuser`
    ;;
  *)
    echo "Running custom command"
    $@
    ;;
esac
