ARG BASE_IMAGE=ghcr.io/alphagov/notify/notifications-template-preview:base
FROM python:3.9-slim-bullseye as parent

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

RUN echo "Install base packages" && apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libcurl4-openssl-dev \
        libssl-dev \
    && echo "Install binary app dependencies" \
    && apt-get install -y --no-install-recommends \
        libpango1.0-dev=1.46.2-3 \
        libmagickwand-dev=8:6.9.11.60+dfsg-1.3 \
        imagemagick=8:6.9.11.60+dfsg-1.3 \
        ghostscript=9.53.3~dfsg-7+deb11u2 \
        poppler-utils=20.09.0-3.1 \
        gsfonts=1:8.11+urwcyr1.0.7~pre44-4.5 \
        fonts-freefont-ttf=20120503-10 \
    && apt-get -y clean \
    && rm -rf /var/lib/apt/lists/* /tmp/*

COPY docker/Arial.ttf /usr/share/fonts/truetype/msttcorefonts/

WORKDIR /home/vcap/app

COPY policy.xml ./

# Overwrite the default ImageMagick policy which doesn't allow reading or writing PDFs
RUN rm /etc/ImageMagick-6/policy.xml && cp ./policy.xml /etc/ImageMagick-6/policy.xml

COPY requirements.txt .

RUN \
	echo "Installing python dependencies" \
	&& pip install -r requirements.txt

##### Test Image ##############################################################

FROM ${BASE_IMAGE} as test

# Make sure the app/ directory is there so that "make bootstrap" can create app/version.py
RUN mkdir -p app

COPY Makefile requirements_for_test.txt ./
RUN make bootstrap

# Copy from the real world, one dir up (project root) into the environment's current working directory
# Docker will rebuild from here down every time.
COPY . .

##### Production Image #######################################################

FROM ${BASE_IMAGE} as production

RUN useradd celeryuser

COPY app app
COPY wsgi.py gunicorn_config.py Makefile run_celery.py ./
COPY scripts/run_app_paas.sh scripts/

# .git folder used only for make generate-version-file but we don't wish to include it in our final production build
COPY .git .git
RUN make generate-version-file
RUN rm -rf .git
