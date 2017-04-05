FROM python:3.6-slim

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY

ENV PYTHONUNBUFFERED=1 \
	DEBIAN_FRONTEND=noninteractive

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
	&& apt-get install -y --no-install-recommends \
		libpango1.0-dev \
		libcairo2-dev \
		libmagickwand-dev \
		ghostscript \
		imagemagick

RUN \
	echo "Clean up" \
	&& rm -rf /var/lib/apt/lists/* /tmp/*

WORKDIR /var/project

# Copy from the real world, one dir up (project root) into the environment's current working directory (var/proj)
COPY . .

RUN \
	echo "Installing python dependencies" \
	&& pwd \
	&& ls -la \
	&& make dependencies generate-version-file

EXPOSE 6013
