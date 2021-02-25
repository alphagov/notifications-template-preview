#!/bin/bash
DOCKER_IMAGE_NAME=notifications-template-preview

source environment.sh

docker run -it --rm \
  -e NOTIFY_ENVIRONMENT=development \
  -e STATSD_ENABLED= \
  -e AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-$(aws configure get aws_access_key_id)} \
  -e AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-$(aws configure get aws_secret_access_key)} \
  -e TEMPLATE_PREVIEW_INTERNAL_SECRETS='["my-secret-key"]' \
  -e DANGEROUS_SALT="dev-notify-salt" \
  -e SECRET_KEY="dev-notify-secret-key" \
  -e NOTIFICATION_QUEUE_PREFIX=${NOTIFICATION_QUEUE_PREFIX} \
  -v $(pwd):/home/vcap/app \
  ${DOCKER_ARGS} \
  ${DOCKER_IMAGE_NAME} \
  ${@}
