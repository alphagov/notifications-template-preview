#!/bin/bash
DOCKER_IMAGE_NAME=notifications-template-preview

source environment.sh

docker run -it --rm \
  -e NOTIFY_ENVIRONMENT=development \
  -e FLASK_DEBUG=1 \
  -e STATSD_ENABLED= \
  -e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-$(aws configure get aws_access_key_id)} \
  -e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-$(aws configure get aws_secret_access_key)} \
  -e TEMPLATE_PREVIEW_INTERNAL_SECRETS='["my-secret-key"]' \
  -e DANGEROUS_SALT="dev-notify-salt" \
  -e SECRET_KEY="dev-notify-secret-key" \
  -e NOTIFICATION_QUEUE_PREFIX=${NOTIFICATION_QUEUE_PREFIX} \
  -e SENTRY_ENABLED=${SENTRY_ENABLED:-0} \
  -e SENTRY_DSN=${SENTRY_DSN:-} \
  -e SENTRY_ERRORS_SAMPLE_RATE=${SENTRY_ERRORS_SAMPLE_RATE:-} \
  -e SENTRY_TRACES_SAMPLE_RATE=${SENTRY_TRACES_SAMPLE_RATE:-} \
  -v $(pwd):/home/vcap/app \
  ${DOCKER_ARGS} \
  ${DOCKER_IMAGE_NAME} \
  ${@}
