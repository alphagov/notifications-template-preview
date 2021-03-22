FROM python:3.6-slim-buster as parent

ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

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
        libcurl4-openssl-dev \
        libssl-dev \
        fonts-freefont-ttf \
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

COPY requirements.txt policy.xml ./

# Overwrite the default ImageMagick policy which doesn't allow reading or writing PDFs
RUN rm /etc/ImageMagick-6/policy.xml && cp ./policy.xml /etc/ImageMagick-6/policy.xml

##### Test Image ##############################################################

FROM parent as test

COPY requirements_for_test.txt .

RUN \
	echo "Installing python dependencies" \
	&& pip install -r requirements_for_test.txt

# Copy from the real world, one dir up (project root) into the environment's current working directory
# Docker will rebuild from here down every time.
COPY . .

RUN make _generate-version-file

##### Production Image #######################################################

FROM parent as production

RUN useradd celeryuser

RUN \
	echo "Installing python dependencies" \
	&& pip install -r requirements.txt

COPY app app
COPY wsgi.py gunicorn_config.py Makefile run_celery.py ./
COPY scripts/run_app_paas.sh scripts/

# .git folder used only for make _generate-version-file but we don't wish to include it in our final production build
COPY .git .git
RUN make _generate-version-file
RUN rm -rf .git
