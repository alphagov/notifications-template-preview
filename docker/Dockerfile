FROM python:3.6-slim-stretch as parent

ARG http_proxy
ARG https_proxy
ARG NO_PROXY

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

RUN ([ -z "$http_proxy" ] || echo "Acquire::http::Proxy \"${http_proxy}\";" > /etc/apt/apt.conf.d/99HttpProxy)
RUN echo "Install base packages" && apt-get update \
    && apt-get install -y --no-install-recommends \
        apt-transport-https \
        make \
        cmake \
        curl \
        git \
        build-essential \
        libffi-dev \
        wget \
        cabextract \
        jq \
        procps \
    && echo "Install binary app dependencies" \
    && apt-get install -y --no-install-recommends \
        libpango1.0-dev \
        libmagickwand-dev \
        imagemagick \
        xfonts-utils \
        gsfonts \
        libcairo2=1.14.8-1 \
    && apt-get -y clean \
    && rm -rf /var/lib/apt/lists/* /tmp/*

# Compile a specified version of ghostscript
ARG GS_VERSION=9.21
RUN wget https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs$(echo $GS_VERSION | tr -d '.' )/ghostscript-${GS_VERSION}.tar.gz \
    && tar xvf ghostscript-${GS_VERSION}.tar.gz \
    && cd ghostscript-${GS_VERSION} && ./configure && make install \
    && cd .. && rm -rf ghostscript-*

ARG POPPLER_VERSION=0.69.0
RUN wget https://poppler.freedesktop.org/poppler-${POPPLER_VERSION}.tar.xz \
    && tar xvf poppler-${POPPLER_VERSION}.tar.xz \
    && cd poppler-${POPPLER_VERSION} && mkdir build && cd build \
    && cmake .. -DCMAKE_INSTALL_PREFIX=/usr && make && make install \
    && cd ../.. && rm -rf poppler-*


COPY docker/Arial.ttf /usr/share/fonts/truetype/msttcorefonts/

WORKDIR /home/vcap/app

# these are declared statically here so that they're cached by the docker image - if we run after the `COPY` command
# they won't be cached so it'll re-download every time. But these don't involve the filesystem
COPY requirements.txt .

##### Test Image ##############################################################

FROM parent as test

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
