FROM python:3.6-slim

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

RUN \
	echo "Install base packages" \
	&& ([ -z "$HTTP_PROXY" ] || echo "Acquire::http::Proxy \"${HTTP_PROXY}\";" > /etc/apt/apt.conf.d/99HttpProxy) \
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
		ghostscript \
		imagemagick \
		gsfonts

RUN echo "Install libcairo2 from stretch" \
	&& echo 'APT::Default-Release "jessie";' > /etc/apt/apt.conf \
	&& mv /etc/apt/sources.list /etc/apt/sources.list.d/jessie.list \
	&& echo "deb http://deb.debian.org/debian stretch main" \
		> /etc/apt/sources.list.d/stretch.list

RUN apt-get -y update
RUN apt-get -t stretch install -y libcairo2=1.14.8-1
RUN apt-get -y clean

RUN \
	echo "Clean up" \
	&& rm -rf /var/lib/apt/lists/* /tmp/*

# these are declared statically here so that they're cached by the docker image - if we run after the `COPY` command
# they won't be cached so it'll re-download every time. But these don't involve the filesystem
RUN \
	echo "Installing python dependencies" \
	&& pip install \
		Flask==0.12.1 \
		Flask-WeasyPrint==0.5 \
		Flask-HTTPAuth==3.2.2 \
		html5lib==1.0b10 \
		wand==0.4.4 \
		git+https://github.com/alphagov/notifications-utils.git@20.0.2#egg=notifications-utils==20.0.2 \
		gunicorn \
		"awscli>=1.11,<1.12" \
		"awscli-cwlogs>=1.4,<1.5" \
		jsonschema==2.6.0

WORKDIR /var/project

# Copy from the real world, one dir up (project root) into the environment's current working directory
# Docker will rebuild from here down every time.
COPY . .

ARG CI_NAME
ARG CI_BUILD_NUMBER
ARG CI_BUILD_URL
ENV CI_NAME=$CI_NAME
ENV CI_BUILD_NUMBER=$CI_BUILD_NUMBER
ENV CI_BUILD_URL=$CI_BUILD_URL

# now we re-install the requirements from the requirements.txt file. If we've diverged from what we declared above,
# we'll catch that here, and should update above. But this command will be quick.
RUN \
	echo "Reinstalling python dependencies - if any python dependencies are installed fresh here, update the docker file!" \
	&& make _dependencies _generate-version-file

EXPOSE 6013
