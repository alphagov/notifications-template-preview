FROM python:3.13-slim-bullseye AS base

COPY --from=ghcr.io/astral-sh/uv:0.5.30 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive
ENV UV_CACHE_DIR='/tmp/uv-cache/'
ENV UV_COMPILE_BYTECODE=1
ENV VIRTUAL_ENV="/opt/venv"

COPY --chmod=0755 docker/choom-wrap-pkgs.sh /usr/local/bin/choom-wrap-pkgs

RUN echo "Install binary app dependencies" \
    && apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        libcurl4 \
        curl \
        libpango1.0-dev=1.56.3-1 \
        imagemagick=8:7.1.1.43+dfsg1-1+deb13u1 \
        ghostscript=10.05.1~dfsg-1 \
        poppler-utils=25.03.0-5 \
        fonts-urw-base35=20200910-8 \
        fonts-freefont-ttf=20211204+svn4273-2 \
        fonts-wqy-zenhei \
        make \
    && choom-wrap-pkgs 150 imagemagick-6.q16 ghostscript poppler-utils \
    && apt-get -y clean \
    && rm -rf /var/lib/apt/lists/* /tmp/*

COPY docker/Arial.ttf /usr/share/fonts/truetype/msttcorefonts/

COPY policy.xml .

# Overwrite the default ImageMagick policy which doesn't allow reading or writing PDFs
RUN rm /etc/ImageMagick-7/policy.xml && cp ./policy.xml /etc/ImageMagick-7/policy.xml
WORKDIR /home/vcap/app

##### Python Build Image #####################################################
FROM base AS python_build

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
    uv pip sync --python /opt/venv/bin/python requirements.txt

COPY . .
RUN make generate-version-file  # This file gets copied across

##### Production Image #######################################################
FROM base AS production

RUN groupadd -r notify && useradd -r -g notify notify && chown -R notify:notify /home/vcap
USER notify

RUN mkdir /home/vcap/logs

COPY --from=python_build --chown=root:root /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY --chown=notify:notify app app
COPY --chown=notify:notify entrypoint.sh wsgi.py gunicorn_config.py Makefile run_celery.py ./
COPY --from=python_build --chown=notify:notify /home/vcap/app/app/version.py app/version.py

RUN python -m compileall .

ENTRYPOINT [ "/home/vcap/app/entrypoint.sh" ]

##### Test Image ##############################################################
FROM production AS test

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
COPY --chown=notify:notify requirements_for_test.txt ./
RUN make bootstrap

# Copy from the real world, one dir up (project root) into the environment's current working directory
# Docker will rebuild from here down every time.
COPY --chown=notify:notify . .
