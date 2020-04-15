.DEFAULT_GOAL := help
SHELL := /bin/bash
DATE = $(shell date +%Y-%m-%dT%H:%M:%S)

APP_VERSION_FILE = app/version.py

GIT_COMMIT ?= $(shell git rev-parse HEAD)

TEMPLATE_PREVIEW_INTERNAL_SECRETS ?= '["my-secret-key"]'

DOCKER_CONTAINER_PREFIX = ${USER}-notifications-template-preview-manual

NOTIFY_CREDENTIALS ?= ~/.notify-credentials

NOTIFY_APP_NAME ?= notify-template-preview
CF_APP ?= notify-template-preview
CF_MANIFEST_FILE ?= manifest$(subst notify-template-preview,,${CF_APP}).yml.j2

DANGEROUS_SALT ?= "dev-notify-salt"
SECRET_KEY ?= "dev-notify-secret-key"

CF_API ?= api.cloud.service.gov.uk
CF_ORG ?= govuk-notify
CF_SPACE ?= development

DOCKER_IMAGE = govuknotify/notifications-template-preview
DOCKER_IMAGE_TAG = $(shell git describe --always --dirty)
DOCKER_IMAGE_NAME = ${DOCKER_IMAGE}:${DOCKER_IMAGE_TAG}

PORT ?= 6013

.PHONY: help
help:
	@cat $(MAKEFILE_LIST) | grep -E '^[a-zA-Z_-]+:.*?## .*$$' | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.PHONY: preview
preview: ## Set environment to preview
	$(eval export CF_SPACE=preview)
	@true

.PHONY: staging
staging: ## Set environment to staging
	$(eval export CF_SPACE=staging)
	@true

.PHONY: production
production: ## Set environment to production
	$(eval export CF_SPACE=production)
	@true

# ---- LOCAL FUNCTIONS ---- #
# should only call these from inside docker or this makefile

.PHONY: _generate-version-file
_generate-version-file:
	@echo -e "__commit__ = \"${GIT_COMMIT}\"\n__time__ = \"${DATE}\"" > ${APP_VERSION_FILE}

.PHONY: _run
_run:
	# since we're inside docker container, assume the dependencies are already run
	./scripts/run_app.sh ${PORT}

.PHONY: _run-celery
_run-celery:
	# since we're inside docker container, assume the dependencies are already run
	./scripts/run_celery.sh

.PHONY: _test
_test:
	# since we're inside docker container, assume the dependencies are already run
	./scripts/run_tests.sh

.PHONY: _single_test
_single_test:
	pytest -k ${test_name}

define run_docker_container
	docker run -it --rm \
		--name "${DOCKER_CONTAINER_PREFIX}-${1}" \
		-e NOTIFY_APP_NAME=${NOTIFY_APP_NAME} \
		-e GIT_COMMIT=${GIT_COMMIT} \
		-e TEMPLATE_PREVIEW_INTERNAL_SECRETS=${TEMPLATE_PREVIEW_INTERNAL_SECRETS} \
		-e STATSD_ENABLED= \
		-e NOTIFY_ENVIRONMENT=${CF_SPACE} \
		-e AWS_ACCESS_KEY_ID=$${AWS_ACCESS_KEY_ID:-$$(aws configure get aws_access_key_id)} \
		-e AWS_SECRET_ACCESS_KEY=$${AWS_SECRET_ACCESS_KEY:-$$(aws configure get aws_secret_access_key)} \
		-e DANGEROUS_SALT=${DANGEROUS_SALT} \
		-e SECRET_KEY=${SECRET_KEY} \
		-e NOTIFICATION_QUEUE_PREFIX=${NOTIFICATION_QUEUE_PREFIX} \
		${3} \
		${DOCKER_IMAGE_NAME} \
		${2}
endef


# ---- DOCKER COMMANDS ---- #

.PHONY: run-with-docker
run-with-docker: prepare-docker-build-image ## Build inside a Docker container
	$(call run_docker_container,build, make _run, -p ${PORT}:${PORT})

.PHONY: run-celery-with-docker
run-celery-with-docker: prepare-docker-build-image ## Build Celery app inside a Docker container
	$(if ${NOTIFICATION_QUEUE_PREFIX},,$(error Must specify NOTIFICATION_QUEUE_PREFIX))
	$(call run_docker_container,celery-build, make _run-celery)

.PHONY: bash-with-docker
bash-with-docker: prepare-docker-test-build-image ## Build inside a Docker container
	$(call run_docker_container,build, bash)

.PHONY: test-with-docker
test-with-docker: prepare-docker-test-build-image ## Run tests inside a Docker container
	$(call run_docker_container,test, make _test)

.PHONY: single-test-with-docker
single-test-with-docker: prepare-docker-test-build-image ## Run single test inside a Docker container, make single-test-with-docker test_name=<test name>
	$(call run_docker_container,test, make _single_test test_name=${test_name})

.PHONY: clean-docker-containers
clean-docker-containers: ## Clean up any remaining docker containers
	docker rm -f $(shell docker ps -q -f "name=${DOCKER_CONTAINER_PREFIX}") 2> /dev/null || true

.PHONY: upload-to-dockerhub
upload-to-dockerhub: prepare-docker-build-image ## Upload the current version of the docker image to dockerhub
	$(if ${DOCKERHUB_USERNAME},,$(error Must specify DOCKERHUB_USERNAME))
	$(if ${DOCKERHUB_PASSWORD},,$(error Must specify DOCKERHUB_PASSWORD))
	@docker login -u ${DOCKERHUB_USERNAME} -p ${DOCKERHUB_PASSWORD}
	docker push ${DOCKER_IMAGE_NAME}

.PHONY: prepare-docker-build-image
prepare-docker-build-image: ## Build docker image
	docker build -f docker/Dockerfile \
		-t ${DOCKER_IMAGE_NAME} \
		.

.PHONY: prepare-docker-test-build-image
prepare-docker-test-build-image: ## Build docker image
	docker build -f docker/Dockerfile \
		--target test \
		-t ${DOCKER_IMAGE_NAME} \
		.

# ---- PAAS COMMANDS ---- #

.PHONY: cf-login
cf-login: ## Log in to Cloud Foundry
	$(if ${CF_USERNAME},,$(error Must specify CF_USERNAME))
	$(if ${CF_PASSWORD},,$(error Must specify CF_PASSWORD))
	$(if ${CF_SPACE},,$(error Must specify CF_SPACE))
	@echo "Logging in to Cloud Foundry on ${CF_API}"
	@cf login -a "${CF_API}" -u ${CF_USERNAME} -p "${CF_PASSWORD}" -o "${CF_ORG}" -s "${CF_SPACE}"

.PHONY: generate-manifest
generate-manifest:
	$(if ${CF_SPACE},,$(error Must specify CF_SPACE))
	$(if $(shell which gpg2), $(eval export GPG=gpg2), $(eval export GPG=gpg))
	$(if ${GPG_PASSPHRASE_TXT}, $(eval export DECRYPT_CMD=echo -n $$$${GPG_PASSPHRASE_TXT} | ${GPG} --quiet --batch --passphrase-fd 0 --pinentry-mode loopback -d), $(eval export DECRYPT_CMD=${GPG} --quiet --batch -d))

	@jinja2 --strict ${CF_MANIFEST_FILE} \
	    -D environment=${CF_SPACE} --format=yaml \
	    <(${DECRYPT_CMD} ${NOTIFY_CREDENTIALS}/credentials/${CF_SPACE}/paas/environment-variables.gpg) 2>&1

.PHONY: cf-deploy
cf-deploy: ## Deploys the app to Cloud Foundry
	$(if ${CF_SPACE},,$(error Must specify CF_SPACE))
	$(if ${CF_APP},,$(error Must specify CF_APP))
	cf target -o ${CF_ORG} -s ${CF_SPACE}
	@cf app --guid ${CF_APP} || exit 1

	# cancel any existing deploys to ensure we can apply manifest (if a deploy is in progress you'll see ScaleDisabledDuringDeployment)
	cf v3-cancel-zdt-push ${CF_APP} || true

	cf v3-apply-manifest ${CF_APP} -f <(make -s generate-manifest)
	CF_STARTUP_TIMEOUT=10 cf v3-zdt-push ${CF_APP} --docker-image ${DOCKER_IMAGE_NAME} --wait-for-deploy-complete  # fails after 10 mins if deploy doesn't work

.PHONY: cf-rollback
cf-rollback: ## Rollbacks the app to the previous release
	$(if ${CF_APP},,$(error Must specify CF_APP))
	cf v3-cancel-zdt-push ${CF_APP}
