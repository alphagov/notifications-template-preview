import os

from contextlib import suppress
from hashlib import sha1

from app.transformation import Logo

from flask import Flask
from flask_httpauth import HTTPTokenAuth

from notifications_utils import logging
from notifications_utils.clients.statsd.statsd_client import StatsdClient
from notifications_utils.s3 import s3upload, s3download, S3ObjectNotFound

from app import version  # noqa


LOGOS = {
    '001': Logo('hm-government'),
    '002': Logo('opg'),
    '003': Logo('dwp'),
    '004': Logo('geo'),
    '005': Logo('ch'),
    '006': Logo('dwp-welsh'),
    '007': Logo('dept-for-communities'),
    '008': Logo('mmo'),
    '500': Logo('hm-land-registry'),
    '501': Logo('ea'),
    '502': Logo('wra'),
    '503': Logo('eryc'),
    '504': Logo('rother'),
    '505': Logo('cadw'),
    '506': Logo('twfrs'),
    '507': Logo('thames-valley-police'),
}


def load_config(application):
    application.config['API_KEY'] = os.environ['TEMPLATE_PREVIEW_API_KEY']
    application.config['LOGOS'] = LOGOS
    application.config['NOTIFY_ENVIRONMENT'] = os.environ['NOTIFY_ENVIRONMENT']
    application.config['NOTIFY_APP_NAME'] = 'template-preview'

    # if we use .get() for cases that it is not setup
    # it will still create the config key with None value causing
    # logging initialization in utils to fail
    if 'NOTIFY_LOG_PATH' in os.environ:
        application.config['NOTIFY_LOG_PATH'] = os.environ['NOTIFY_LOG_PATH']

    application.config['EXPIRE_CACHE_IN_SECONDS'] = 600

    if os.environ['STATSD_ENABLED'] == "1":
        application.config['STATSD_ENABLED'] = True
        application.config['STATSD_HOST'] = "statsd.hostedgraphite.com"
        application.config['STATSD_PORT'] = 8125
        application.config['STATSD_PREFIX'] = os.environ['STATSD_PREFIX']
    else:
        application.config['STATSD_ENABLED'] = False

    application.config['S3_REGION'] = 'eu-west-1'
    application.config['S3_LETTER_CACHE_BUCKET'] = (
        '{}-template-preview-cache'.format(
            application.config['NOTIFY_ENVIRONMENT']
        )
    )


def create_app():
    application = Flask(
        __name__,
        static_url_path='/static',
        static_folder='../static'
    )

    load_config(application)

    from app.preview import preview_blueprint
    from app.status import status_blueprint
    application.register_blueprint(status_blueprint)
    application.register_blueprint(preview_blueprint)

    application.statsd_client = StatsdClient()
    application.statsd_client.init_app(application)
    logging.init_app(application, application.statsd_client)

    application.cache = init_cache(application)

    @auth.verify_token
    def verify_token(token):
        return token == application.config['API_KEY']

    return application


auth = HTTPTokenAuth(scheme='Token')


def init_cache(application):

    def cache(*args, extension='file'):

        cache_key = '{}.{}'.format(
            sha1(''.join(str(arg) for arg in args).encode('utf-8')).hexdigest(),
            extension,
        )

        def wrapper(original_function):

            def new_function():

                with suppress(S3ObjectNotFound):
                    return s3download(
                        application.config['S3_LETTER_CACHE_BUCKET'],
                        cache_key,
                    )

                data = original_function()

                s3upload(
                    data,
                    application.config['S3_REGION'],
                    application.config['S3_LETTER_CACHE_BUCKET'],
                    cache_key,
                )

                data.seek(0)
                return data

            return new_function

        return wrapper

    return cache
