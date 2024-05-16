ARG BASE_IMAGE=ghcr.io/alphagov/notify/notifications-template-preview:base
FROM python:3.11-slim-bullseye as base

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

COPY --chmod=0755 docker/choom-wrap-pkgs.sh /usr/local/bin/choom-wrap-pkgs

RUN echo "Install binary app dependencies" \
    && apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        libcurl4 \
        curl \
        libpango1.0-dev=1.46.2-3 \
        imagemagick=8:6.9.11.60+dfsg-1.3+deb11u3 \
        libgs9-common=9.53.3~dfsg-7+deb11u6 \
        libgs9=9.53.3~dfsg-7+deb11u6 \
        ghostscript=9.53.3~dfsg-7+deb11u6 \
        poppler-utils=20.09.0-3.1+deb11u1 \
        gsfonts=1:8.11+urwcyr1.0.7~pre44-4.5 \
        fonts-freefont-ttf=20120503-10 \
        fonts-wqy-zenhei \
        make \
    && choom-wrap-pkgs 150 imagemagick-6.q16 ghostscript poppler-utils \
    && apt-get -y clean \
    && rm -rf /var/lib/apt/lists/* /tmp/*

COPY docker/Arial.ttf /usr/share/fonts/truetype/msttcorefonts/

COPY policy.xml .

# Overwrite the default ImageMagick policy which doesn't allow reading or writing PDFs
RUN rm /etc/ImageMagick-6/policy.xml && cp ./policy.xml /etc/ImageMagick-6/policy.xml
WORKDIR /home/vcap/app

##### Python Build Image #####################################################
FROM ${BASE_IMAGE} AS python_build

RUN echo "Install OS dependencies for python app requirements" && apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libcurl4-openssl-dev \
        libssl-dev \
    && apt-get -y clean \
    && rm -rf /var/lib/apt/lists/* /tmp/*

COPY requirements.txt .

RUN echo "Installing python requirements" && \
    python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install -r requirements.txt

COPY . .
RUN make generate-version-file  # This file gets copied across

##### Production Image #######################################################
FROM ${BASE_IMAGE} as production

RUN groupadd -r notify && useradd -r -g notify notify && chown -R notify:notify /home/vcap
USER notify

RUN mkdir /home/vcap/logs

COPY --from=python_build --chown=root:root /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY --chown=notify:notify app app
COPY --chown=notify:notify entrypoint.sh wsgi.py gunicorn_config.py Makefile run_celery.py ./
COPY --from=python_build --chown=notify:notify /home/vcap/app/app/version.py app/version.py

ENTRYPOINT [ "/home/vcap/app/entrypoint.sh" ]

##### Test Image ##############################################################
FROM production as test

USER root
RUN echo "Install OS dependencies for test build" && apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
      sudo \
      git \
      libcurl4-openssl-dev \
      libssl-dev \
    && apt-get -y clean \
    && rm -rf /var/lib/apt/lists/* /tmp/*
RUN usermod -aG sudo notify
RUN echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
USER notify

ENV HOME=/home/vcap

# Make sure the app/ directory is there so that "make bootstrap" can create app/version.py
RUN mkdir -p app

# Copying to overwrite is faster than RUN chown notify:notify ...
COPY --from=python_build --chown=notify:notify /opt/venv /opt/venv

# Install dev/test requirements
COPY --chown=notify:notify requirements.txt requirements_for_test.txt ./
RUN make bootstrap

# Copy from the real world, one dir up (project root) into the environment's current working directory
# Docker will rebuild from here down every time.
COPY --chown=notify:notify . .
