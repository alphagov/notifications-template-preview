ARG BASE_IMAGE=ghcr.io/alphagov/notify/notifications-template-preview:base
FROM python:3.9-slim-bullseye as base

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

RUN echo "Install binary app dependencies" \
    && apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        libpango1.0-dev=1.46.2-3 \
        imagemagick=8:6.9.11.60+dfsg-1.3+deb11u1 \
        ghostscript=9.53.3~dfsg-7+deb11u5 \
        poppler-utils=20.09.0-3.1+deb11u1 \
        gsfonts=1:8.11+urwcyr1.0.7~pre44-4.5 \
        fonts-freefont-ttf=20120503-10 \
        fonts-wqy-zenhei \
        make \
    && apt-get -y clean \
    && rm -rf /var/lib/apt/lists/* /tmp/*

COPY docker/Arial.ttf /usr/share/fonts/truetype/msttcorefonts/

COPY policy.xml .

# Overwrite the default ImageMagick policy which doesn't allow reading or writing PDFs
RUN rm /etc/ImageMagick-6/policy.xml && cp ./policy.xml /etc/ImageMagick-6/policy.xml
WORKDIR /home/vcap/app

# Build/Install python dependencies
FROM ${BASE_IMAGE} AS python_build

COPY requirements.txt .

RUN echo "Install OS dependencies for python app requirements" && apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libcurl4-openssl-dev \
        curl \
        libssl-dev && \
    echo "Installing python requirements" && \
    python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install -r requirements.txt \
    && apt-get -y clean \
    && rm -rf /var/lib/apt/lists/* /tmp/*

#### Shared App Base Image ####################################################
FROM ${BASE_IMAGE} AS app_base

RUN groupadd -r notify && useradd -r -g notify notify && chown -R notify:notify /home/vcap
USER notify

RUN mkdir /home/vcap/logs

COPY --from=python_build --chown=root:root /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY --chown=notify:notify entrypoint.sh .
ENTRYPOINT [ "/home/vcap/app/entrypoint.sh" ]

##### Test Image ##############################################################
FROM app_base as test

USER root
RUN chown -R notify:notify /opt/venv
USER notify

# Make sure the app/ directory is there so that "make bootstrap" can create app/version.py
RUN mkdir -p app

COPY --chown=notify:notify Makefile requirements.txt requirements_for_test.txt ./
RUN make bootstrap

# Copy from the real world, one dir up (project root) into the environment's current working directory
# Docker will rebuild from here down every time.
COPY --chown=notify:notify . .

##### Production Image #######################################################

FROM app_base as production

COPY --chown=notify:notify app app
COPY --chown=notify:notify wsgi.py gunicorn_config.py Makefile run_celery.py ./
COPY --chown=notify:notify scripts/run_app_paas.sh scripts/

# .git folder used only for make generate-version-file but we don't wish to include it in our final production build
COPY --chown=notify:notify .git .git
RUN make generate-version-file
RUN rm -rf .git
