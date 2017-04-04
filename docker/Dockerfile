FROM python:3.6-slim

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY

ENV PYTHONUNBUFFERED=1 \
	DEBIAN_FRONTEND=noninteractive \
	GOSU_VERSION=1.10

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
		libffi-dev
		# zip rlwrap python-dev

RUN \
	echo "Install binary dependencies" \
	&& apt-get install -y --no-install-recommends \
		libpango1.0-dev \
		libcairo2-dev \
		libmagickwand-dev \
		ghostscript \
		imagemagick

RUN \
	echo "Clean up" \
	&& rm -rf /var/lib/apt/lists/* /tmp/*

COPY tianon.gpg /tmp/tianon.gpg

RUN \
	echo "Install gosu" \
	&& curl -sSL -o /usr/local/bin/gosu "https://github.com/tianon/gosu/releases/download/$GOSU_VERSION/gosu-$(dpkg --print-architecture)" \
	&& curl -sSL -o /usr/local/bin/gosu.asc "https://github.com/tianon/gosu/releases/download/$GOSU_VERSION/gosu-$(dpkg --print-architecture).asc" \
	&& export GNUPGHOME="$(mktemp -d)" \
	&& gpg --import /tmp/tianon.gpg \
	&& gpg --batch --verify /usr/local/bin/gosu.asc /usr/local/bin/gosu \
	&& rm -r "$GNUPGHOME" /usr/local/bin/gosu.asc \
	&& chmod +x /usr/local/bin/gosu \
	&& gosu nobody true

WORKDIR /var/project

COPY entrypoint.sh /usr/local/bin/docker-entrypoint

ENTRYPOINT ["/usr/local/bin/docker-entrypoint"]
