FROM python:3.6-slim as parent

ARG http_proxy
ARG https_proxy
ARG NO_PROXY

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

RUN \
	echo "Install base packages" \
	&& ([ -z "$http_proxy" ] || echo "Acquire::http::Proxy \"${http_proxy}\";" > /etc/apt/apt.conf.d/99HttpProxy) \
	&& apt-get update \
	&& apt-get install -y --no-install-recommends \
		apt-transport-https \
		make \
		curl \
		git \
		build-essential \
		libffi-dev \
		jq

RUN \
	echo "Install binary app dependencies" \
	&& apt-get update \
	&& apt-get install -y --no-install-recommends \
		libpango1.0-dev \
		libmagickwand-dev \
		imagemagick \
		gsfonts

RUN echo "Install libcairo2 from stretch" \
	&& echo 'APT::Default-Release "jessie";' > /etc/apt/apt.conf \
	&& mv /etc/apt/sources.list /etc/apt/sources.list.d/jessie.list \
	&& echo "deb http://deb.debian.org/debian stretch main" \
		> /etc/apt/sources.list.d/stretch.list

RUN \
 	echo "installing a couple of bits from stretch" \
	&& apt-get -y update \
	&& apt-get -t stretch install -y \
	  libcairo2=1.14.8-1 \
	  ghostscript
RUN apt-get -y clean

RUN \
	echo "Clean up" \
	&& rm -rf /var/lib/apt/lists/* /tmp/*


##### Test Image ##############################################################

FROM parent as test

WORKDIR /home/vcap/app

# these are declared statically here so that they're cached by the docker image - if we run after the `COPY` command
# they won't be cached so it'll re-download every time. But these don't involve the filesystem
COPY requirements.txt .
COPY requirements-dev.txt .

RUN \
	echo "Installing python dependencies" \
	&& pip install -r requirements-dev.txt

# Copy from the real world, one dir up (project root) into the environment's current working directory
# Docker will rebuild from here down every time.
COPY . .

ARG CI_NAME
ARG CI_BUILD_NUMBER
ARG CI_BUILD_URL
ENV CI_NAME=$CI_NAME
ENV CI_BUILD_NUMBER=$CI_BUILD_NUMBER
ENV CI_BUILD_URL=$CI_BUILD_URL

RUN make _generate-version-file

EXPOSE 6013

##### Production Image #######################################################

FROM parent as production

WORKDIR /home/vcap/app

# these are declared statically here so that they're cached by the docker image - if we run after the `COPY` command
# they won't be cached so it'll re-download every time. But these don't involve the filesystem
COPY requirements.txt .

RUN \
	echo "Installing python dependencies" \
	&& pip install -r requirements.txt

COPY app app
COPY wsgi.py gunicorn_config.py Makefile ./
COPY scripts/run_app_paas.sh scripts/run_app.sh scripts/

ARG CI_NAME
ARG CI_BUILD_NUMBER
ARG CI_BUILD_URL
ENV CI_NAME=$CI_NAME
ENV CI_BUILD_NUMBER=$CI_BUILD_NUMBER
ENV CI_BUILD_URL=$CI_BUILD_URL

RUN make _generate-version-file

EXPOSE 6013