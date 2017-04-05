.DEFAULT_GOAL := help
SHELL := /bin/bash
DATE = $(shell date +%Y-%m-%d:%H:%M:%S)

APP_VERSION_FILE = app/version.py

GIT_BRANCH ?= $(shell git symbolic-ref --short HEAD 2> /dev/null || echo "detached")
GIT_COMMIT ?= $(shell git rev-parse HEAD 2> /dev/null || echo "")

DOCKER_IMAGE_TAG := $(shell cat docker/VERSION)
DOCKER_BUILDER_IMAGE_NAME = govuknotify/notifications-template-preview:${DOCKER_IMAGE_TAG}
DOCKER_TTY ?= $(if ${JENKINS_HOME},,t)

BUILD_TAG ?= notifications-template-preview-manual
BUILD_NUMBER ?= 0
DEPLOY_BUILD_NUMBER ?= ${BUILD_NUMBER}
BUILD_URL ?=

DOCKER_CONTAINER_PREFIX = ${USER}-${BUILD_TAG}

NOTIFY_CREDENTIALS?=~/.notify-credentials

CF_API ?= api.cloud.service.gov.uk
CF_ORG ?= govuk-notify
# CF_SPACE ?= ${DEPLOY_ENV}
CF_SPACE = sandbox
CF_HOME ?= ${HOME}
$(eval export CF_HOME)

.PHONY: help
help:
	@cat $(MAKEFILE_LIST) | grep -E '^[a-zA-Z_-]+:.*?## .*$$' | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.PHONY: venv
venv:
	$(if ${VIRTUAL_ENV},,python -m venv venv)

.PHONY: sandbox
sandbox: ## Set environment to sandbox
	$(eval export DEPLOY_ENV=sandbox)
	$(eval export DNS_NAME="cloudapps.digital")
	@true

.PHONY: preview
preview: ## Set environment to preview
	$(eval export DEPLOY_ENV=preview)
	$(eval export DNS_NAME="notify.works")
	@true

.PHONY: staging
staging: ## Set environment to staging
	$(eval export DEPLOY_ENV=staging)
	$(eval export DNS_NAME="staging-notify.works")
	@true

.PHONY: production
production: ## Set environment to production
	$(eval export DEPLOY_ENV=production)
	$(eval export DNS_NAME="notifications.service.gov.uk")
	@true

.PHONY: dependencies
dependencies: venv ## Install build dependencies
	. venv/bin/activate && pip install -r requirements_for_test.txt

.PHONY: generate-version-file
generate-version-file: ## Generates the app version file
	@echo -e "__commit__ = \"${GIT_COMMIT}\"\n__time__ = \"${DATE}\"\n__jenkins_job_number__ = \"${BUILD_NUMBER}\"\n__jenkins_job_url__ = \"${BUILD_URL}\"" > ${APP_VERSION_FILE}

.PHONY: run
run: dependencies generate-version-file ## Run server
	./scripts/run_app.sh

.PHONY: build
build: dependencies generate-version-file ## Build project
	. venv/bin/activate && pip wheel --wheel-dir=wheelhouse -r requirements.txt

.PHONY: test
test: venv ## Run tests
	./scripts/run_tests.sh

.PHONY: prepare-docker-build-image
prepare-docker-build-image: ## Prepare the Docker builder image
	make -C docker build

define run_docker_container
	docker run -i${DOCKER_TTY} --rm \
		--name "${DOCKER_CONTAINER_PREFIX}-${1}" \
		-v "`pwd`:/var/project" \
		-p "6013:6013" \
		-e UID=$(shell id -u) \
		-e GID=$(shell id -g) \
		-e GIT_COMMIT=${GIT_COMMIT} \
		-e BUILD_NUMBER=${BUILD_NUMBER} \
		-e BUILD_URL=${BUILD_URL} \
		-e http_proxy="${HTTP_PROXY}" \
		-e HTTP_PROXY="${HTTP_PROXY}" \
		-e https_proxy="${HTTPS_PROXY}" \
		-e HTTPS_PROXY="${HTTPS_PROXY}" \
		-e NO_PROXY="${NO_PROXY}" \
		-e CF_API="${CF_API}" \
		-e CF_USERNAME="${CF_USERNAME}" \
		-e CF_PASSWORD="${CF_PASSWORD}" \
		-e CF_ORG="${CF_ORG}" \
		-e CF_SPACE="${CF_SPACE}" \
		${DOCKER_BUILDER_IMAGE_NAME} \
		${2}
endef

.PHONY: build-with-docker
build-with-docker: prepare-docker-build-image ## Build inside a Docker container
	$(call run_docker_container,build,gosu hostuser make build)

.PHONY: run-with-docker
run-with-docker: prepare-docker-build-image ## Build inside a Docker container
	$(call run_docker_container,build,gosu hostuser make run)

.PHONY: cf-build-with-docker
cf-build-with-docker: prepare-docker-build-image ## Build inside a Docker container
	$(call run_docker_container,build,gosu hostuser make cf-build)

.PHONY: test-with-docker
test-with-docker: prepare-docker-build-image ## Run tests inside a Docker container
	$(call run_docker_container,test,gosu hostuser make test)

.PHONY: clean-docker-containers
clean-docker-containers: ## Clean up any remaining docker containers
	docker rm -f $(shell docker ps -q -f "name=${DOCKER_CONTAINER_PREFIX}") 2> /dev/null || true

.PHONY: clean
clean:
	rm -rf cache target venv .coverage wheelhouse

.PHONY: upload-paas-artifact ## Upload the deploy artifact for PaaS
upload-paas-artifact:
	@docker login -u govuknotify -p '$(shell PASSWORD_STORE_DIR=${NOTIFY_CREDENTIALS} pass show credentials/dockerhub/password)'
	docker push govuknotify/notifications-template-preview

.PHONY: cf-login
cf-login: ## Log in to Cloud Foundry
	$(if ${CF_USERNAME},,$(error Must specify CF_USERNAME))
	$(if ${CF_PASSWORD},,$(error Must specify CF_PASSWORD))
	$(if ${CF_SPACE},,$(error Must specify CF_SPACE))
	@echo "Logging in to Cloud Foundry on ${CF_API}"
	@cf login -a "${CF_API}" -u ${CF_USERNAME} -p "${CF_PASSWORD}" -o "${CF_ORG}" -s "${CF_SPACE}"

.PHONY: cf-deploy
cf-deploy: ## Deploys the app to Cloud Foundry
	$(if ${CF_SPACE},,$(error Must specify CF_SPACE))
	@cf app --guid notify-template-preview || exit 1
	cf rename notify-template-preview notify-template-preview-rollback
	cf push notify-template-preview --docker-image ${DOCKER_BUILDER_IMAGE_NAME}
	cf scale -i $$(cf curl /v2/apps/$$(cf app --guid notify-template-preview-rollback) | jq -r ".entity.instances" 2>/dev/null || echo "1") notify-template-preview
	cf stop notify-template-preview-rollback
	cf delete -f notify-template-preview-rollback

.PHONY: cf-rollback
cf-rollback: ## Rollbacks the app to the previous release
	@cf app --guid notify-template-preview-rollback || exit 1
	@[ $$(cf curl /v2/apps/`cf app --guid notify-template-preview-rollback` | jq -r ".entity.state") = "STARTED" ] || (echo "Error: rollback is not possible because notify-template-preview-rollback is not in a started state" && exit 1)
	cf delete -f notify-template-preview || true
	cf rename notify-template-preview-rollback notify-template-preview
