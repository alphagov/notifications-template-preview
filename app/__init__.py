import os

from contextlib import suppress
from hashlib import sha1

import PyPDF2
import binascii

from app.transformation import Logo

from flask import Flask, jsonify
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
    '009': Logo('hmpo'),
    '500': Logo('hm-land-registry'),
    '501': Logo('ea'),
    '502': Logo('wra'),
    '503': Logo('eryc'),
    '504': Logo('rother'),
    '505': Logo('cadw'),
    '506': Logo('twfrs'),
    '507': Logo('thames-valley-police'),
    '508': Logo('ofgem'),
    '509': Logo('hackney'),
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
        application.config['STATSD_PREFIX'] = application.config['NOTIFY_ENVIRONMENT']
    else:
        application.config['STATSD_ENABLED'] = False

    application.config['S3_REGION'] = 'eu-west-1'
    application.config['S3_LETTER_CACHE_BUCKET'] = (
        '{}-template-preview-cache'.format(
            application.config['NOTIFY_ENVIRONMENT']
        )
    )

    application.config['LETTER_LOGO_URL'] = 'https://static-logos.{}/letters'.format({
        # not called `development` in template preview for some reason
        'sandbox': 'notify.tools',
        'preview': 'notify.works',
        'staging': 'staging-notify.works',
        'production': 'notifications.service.gov.uk'
    }[application.config['NOTIFY_ENVIRONMENT']])


def create_app():
    application = Flask(__name__)

    init_app(application)

    load_config(application)

    from app.preview import preview_blueprint
    from app.status import status_blueprint
    from app.precompiled import precompiled_blueprint
    application.register_blueprint(status_blueprint)
    application.register_blueprint(preview_blueprint)
    application.register_blueprint(precompiled_blueprint)

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

    def cache(*args, folder=None, extension='file'):

        cache_key = '{}/{}.{}'.format(
            folder,
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


def init_app(app):

    @app.errorhandler(Exception)
    def exception(error):
        app.logger.exception(error)

        if hasattr(error, 'message'):
            # error.code is set for our exception types.
            return jsonify(result='error', message=error.message or ""), error.code or 500
        elif hasattr(error, 'code'):
            # error.code is set for our exception types.
            return jsonify(result='error'), error.code or 500
        else:
            # error.code is set for our exception types.
            return jsonify(result='error'), 500

    @app.errorhandler(PyPDF2.utils.PdfReadError)
    def handle_base64_error(e):
        msg = "Unable to read the PDF data: {}".format(e)
        app.logger.warn(msg)
        return jsonify(message=msg), 400

    @app.errorhandler(binascii.Error)
    def handle_binascii_error(e):
        msg = "Unable to decode the PDF data: {}".format(e)
        app.logger.warn(msg)
        return jsonify(message=msg), 400
