FROM python:3.9-slim-bullseye as parent

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

RUN echo "Install base packages" && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libcurl4-openssl-dev \
        libssl-dev \
    && echo "Install binary app dependencies" \
    && apt-get install -y --no-install-recommends \
        libpango1.0-dev \
        libmagickwand-dev \
        imagemagick \
        ghostscript=9.53.3~dfsg-7+deb11u2 \
        poppler-utils=20.09.0-3.1 \
        xfonts-utils \
        gsfonts \
        fonts-freefont-ttf \
    && apt-get -y clean \
    && rm -rf /var/lib/apt/lists/* /tmp/*

COPY docker/Arial.ttf /usr/share/fonts/truetype/msttcorefonts/

WORKDIR /home/vcap/app

COPY requirements.txt policy.xml ./

# Overwrite the default ImageMagick policy which doesn't allow reading or writing PDFs
RUN rm /etc/ImageMagick-6/policy.xml && cp ./policy.xml /etc/ImageMagick-6/policy.xml

##### Test Image ##############################################################

FROM parent as test

# Make sure the app/ directory is there so that "make bootstrap" can create app/version.py
RUN mkdir -p app

COPY Makefile requirements_for_test.txt ./
RUN make bootstrap

# Copy from the real world, one dir up (project root) into the environment's current working directory
# Docker will rebuild from here down every time.
COPY . .

##### Production Image #######################################################

FROM parent as production

RUN useradd celeryuser

RUN \
	echo "Installing python dependencies" \
	&& pip install -r requirements.txt

COPY app app
COPY wsgi.py gunicorn_config.py Makefile run_celery.py ./
COPY scripts/run_app_paas.sh scripts/

# .git folder used only for make generate-version-file but we don't wish to include it in our final production build
COPY .git .git
RUN make generate-version-file
RUN rm -rf .git
