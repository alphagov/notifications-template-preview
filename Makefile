.DEFAULT_GOAL := help
SHELL := /bin/bash
DATE = $(shell date +%Y-%m-%dT%H:%M:%S)

APP_VERSION_FILE = app/version.py

GIT_COMMIT ?= $(shell git rev-parse HEAD)

NOTIFY_CREDENTIALS ?= ~/.notify-credentials

CF_APP ?= notify-template-preview
CF_MANIFEST_TEMPLATE_PATH ?= manifest$(subst notify-template-preview,,${CF_APP}).yml.j2
CF_MANIFEST_PATH ?= /tmp/manifest.yml

CF_API ?= api.cloud.service.gov.uk
CF_ORG ?= govuk-notify
CF_SPACE ?= development

DOCKER_IMAGE = ghcr.io/alphagov/notify/notifications-template-preview
DOCKER_IMAGE_TAG = $(shell git describe --always --dirty)
DOCKER_IMAGE_NAME = ${DOCKER_IMAGE}:${DOCKER_IMAGE_TAG}

PORT ?= 6013

.PHONY: help
help:
	@cat $(MAKEFILE_LIST) | grep -E '^[a-zA-Z_-]+:.*?## .*$$' | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

# ---- LOCAL FUNCTIONS ---- #
# should only call these from inside docker or this makefile

.PHONY: freeze-requirements
freeze-requirements: ## create static requirements.txt
	pip install --upgrade pip-tools
	pip-compile requirements.in

.PHONY: generate-version-file
generate-version-file:
	@echo -e "__commit__ = \"${GIT_COMMIT}\"\n__time__ = \"${DATE}\"" > ${APP_VERSION_FILE}

.PHONY: bootstrap
bootstrap:
	mkdir -p log # manually create directory to avoid permission issues
	pip install -r requirements_for_test.txt

# ---- DOCKER COMMANDS ---- #

.PHONY: bootstrap
bootstrap-with-docker: ## Setup environment to run app commands
	docker build -f docker/Dockerfile --target test -t notifications-template-preview .

.PHONY: run-flask-with-docker
run-flask-with-docker: ## Run flask in Docker container
	export DOCKER_ARGS="-p ${PORT}:${PORT}" && \
		./scripts/run_with_docker.sh flask run --host=0.0.0.0 -p ${PORT}

.PHONY: run-celery-with-docker
run-celery-with-docker: ## Run celery in Docker container
	$(if ${NOTIFICATION_QUEUE_PREFIX},,$(error Must specify NOTIFICATION_QUEUE_PREFIX))
	./scripts/run_with_docker.sh celery -A run_celery.notify_celery worker --loglevel=INFO

.PHONY: test
test: ## Run tests (used by Concourse)
	flake8 .
	isort --check-only ./app ./tests
	pytest --maxfail=10

.PHONY: test-with-docker
test-with-docker: ## Run tests in Docker container
	./scripts/run_with_docker.sh make test

.PHONY: upload-to-docker-registry
upload-to-docker-registry: ## Upload the current version of the docker image to Docker registry
	$(if ${DOCKER_USER_NAME},,$(error Must specify DOCKER_USER_NAME))
	$(if ${CF_DOCKER_PASSWORD},,$(error Must specify CF_DOCKER_PASSWORD))
	@docker login ${DOCKER_IMAGE} -u ${DOCKER_USER_NAME} -p ${CF_DOCKER_PASSWORD}
	docker buildx build --platform linux/amd64 --push -f docker/Dockerfile -t ${DOCKER_IMAGE_NAME} .

# ---- PAAS COMMANDS ---- #

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

	@jinja2 --strict ${CF_MANIFEST_TEMPLATE_PATH} \
	    -D environment=${CF_SPACE} --format=yaml \
	    <(${DECRYPT_CMD} ${NOTIFY_CREDENTIALS}/credentials/${CF_SPACE}/paas/environment-variables.gpg) 2>&1

.PHONY: cf-deploy
cf-deploy: ## Deploys the app to Cloud Foundry
	$(if ${CF_SPACE},,$(error Must specify CF_SPACE))
	$(if ${CF_APP},,$(error Must specify CF_APP))
	cf target -o ${CF_ORG} -s ${CF_SPACE}
	@cf app --guid ${CF_APP} || exit 1

	# cancel any existing deploys to ensure we can apply manifest (if a deploy is in progress you'll see ScaleDisabledDuringDeployment)
	make -s generate-manifest > ${CF_MANIFEST_PATH}
	cf cancel-deployment ${CF_APP} || true

	# fails after 10 mins if deploy doesn't work
	CF_STARTUP_TIMEOUT=10 cf push ${CF_APP} --strategy=rolling -f ${CF_MANIFEST_PATH} --docker-image ${DOCKER_IMAGE_NAME} --docker-username ${DOCKER_USER_NAME}
	rm -f ${CF_MANIFEST_PATH}

.PHONY: cf-rollback
cf-rollback: ## Rollbacks the app to the previous release
	$(if ${CF_APP},,$(error Must specify CF_APP))
	cf cancel-deployment ${CF_APP}
	rm -f ${CF_MANIFEST_PATH}
