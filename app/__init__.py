import binascii
import json
import os
from contextlib import suppress
from hashlib import sha1

import PyPDF2
from flask import Flask, jsonify
from flask_httpauth import HTTPTokenAuth
from kombu import Exchange, Queue
from notifications_utils import logging as utils_logging
from notifications_utils import request_helper
from notifications_utils.clients.encryption.encryption_client import Encryption
from notifications_utils.clients.statsd.statsd_client import StatsdClient
from notifications_utils.s3 import S3ObjectNotFound, s3download, s3upload

from app import weasyprint_hack
from app.celery.celery import NotifyCelery

notify_celery = NotifyCelery()


def load_config(application):
    application.config['AWS_REGION'] = 'eu-west-1'
    application.config['TEMPLATE_PREVIEW_INTERNAL_SECRETS'] = json.loads(
        os.environ.get('TEMPLATE_PREVIEW_INTERNAL_SECRETS', '[]')
    )
    application.config['NOTIFY_ENVIRONMENT'] = os.environ['NOTIFY_ENVIRONMENT']
    application.config['NOTIFY_APP_NAME'] = 'template-preview'
    application.config['DANGEROUS_SALT'] = os.environ['DANGEROUS_SALT']
    application.config['SECRET_KEY'] = os.environ['SECRET_KEY']

    application.config['celery'] = {
        'broker_url': 'sqs://',
        'broker_transport_options': {
            'region': application.config['AWS_REGION'],
            'visibility_timeout': 310,
            'queue_name_prefix': queue_prefix[application.config['NOTIFY_ENVIRONMENT']],
            'wait_time_seconds': 20  # enable long polling, with a wait time of 20 seconds
        },
        'timezone': 'Europe/London',
        'worker_max_memory_per_child': 50,
        'imports': ['app.celery.tasks'],
        'task_queues': [
            Queue(QueueNames.SANITISE_LETTERS, Exchange('default'), routing_key=QueueNames.SANITISE_LETTERS)
        ],
    }

    # if we use .get() for cases that it is not setup
    # it will still create the config key with None value causing
    # logging initialization in utils to fail
    if 'NOTIFY_LOG_PATH' in os.environ:
        application.config['NOTIFY_LOG_PATH'] = os.environ['NOTIFY_LOG_PATH']

    application.config['EXPIRE_CACHE_IN_SECONDS'] = 600

    if os.environ['STATSD_ENABLED'] == "1":
        application.config['STATSD_ENABLED'] = True
        application.config['STATSD_HOST'] = os.environ['STATSD_HOST']
        application.config['STATSD_PORT'] = 8125
    else:
        application.config['STATSD_ENABLED'] = False

    application.config['LETTERS_SCAN_BUCKET_NAME'] = (
        '{}-letters-scan'.format(
            application.config['NOTIFY_ENVIRONMENT']
        )
    )
    application.config['LETTER_CACHE_BUCKET_NAME'] = (
        '{}-template-preview-cache'.format(
            application.config['NOTIFY_ENVIRONMENT']
        )
    )

    application.config['LETTERS_PDF_BUCKET_NAME'] = (
        '{}-letters-pdf'.format(
            application.config['NOTIFY_ENVIRONMENT']
        )
    )

    application.config['TEST_LETTERS_BUCKET_NAME'] = (
        '{}-test-letters'.format(
            application.config['NOTIFY_ENVIRONMENT']
        )
    )

    application.config['SANITISED_LETTER_BUCKET_NAME'] = (
        '{}-letters-sanitise'.format(
            application.config['NOTIFY_ENVIRONMENT']
        )
    )

    application.config['PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME'] = (
        '{}-letters-precompiled-originals-backup'.format(
            application.config['NOTIFY_ENVIRONMENT']
        )
    )

    application.config['LETTER_LOGO_URL'] = 'https://static-logos.{}/letters'.format({
        'test': 'notify.tools',
        'development': 'notify.tools',
        'preview': 'notify.works',
        'staging': 'staging-notify.works',
        'production': 'notifications.service.gov.uk'
    }[application.config['NOTIFY_ENVIRONMENT']])


def create_app():
    application = Flask(__name__)

    init_app(application)

    load_config(application)

    from app.precompiled import precompiled_blueprint
    from app.preview import preview_blueprint
    from app.status import status_blueprint
    application.register_blueprint(status_blueprint)
    application.register_blueprint(preview_blueprint)
    application.register_blueprint(precompiled_blueprint)

    application.statsd_client = StatsdClient()
    application.statsd_client.init_app(application)
    application.encryption_client = Encryption()
    application.encryption_client.init_app(application)
    utils_logging.init_app(application, application.statsd_client)
    weasyprint_hack.init_app(application)
    request_helper.init_app(application)
    notify_celery.init_app(application)

    application.cache = init_cache(application)

    @auth.verify_token
    def verify_token(token):
        return token in application.config['TEMPLATE_PREVIEW_INTERNAL_SECRETS']

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
                        application.config['LETTER_CACHE_BUCKET_NAME'],
                        cache_key,
                    )

                data = original_function()

                s3upload(
                    data,
                    application.config['AWS_REGION'],
                    application.config['LETTER_CACHE_BUCKET_NAME'],
                    cache_key,
                )

                data.seek(0)
                return data

            return new_function

        return wrapper

    return cache


def init_app(app):
    @app.errorhandler(InvalidRequest)
    def invalid_request(error):
        app.logger.warning(error.message)
        return jsonify(result='error', message=error.message or ""), error.code

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
            return jsonify(result='error', message=str(error)), 500

    @app.errorhandler(404)
    def page_not_found(e):
        msg = e.description or "Not found"
        return jsonify(result='error', message=msg), 404

    @app.errorhandler(PyPDF2.utils.PdfReadError)
    def handle_base64_error(e):
        msg = "Unable to read the PDF data: {}".format(e)
        app.logger.warning(msg)
        return jsonify(message=msg), 400

    @app.errorhandler(binascii.Error)
    def handle_binascii_error(e):
        msg = "Unable to decode the PDF data: {}".format(e)
        app.logger.warning(msg)
        return jsonify(message=msg), 400


class InvalidRequest(Exception):
    def __init__(self, message, code=400):
        self.message = message
        self.code = code


class ValidationFailed(Exception):
    def __init__(self, message, invalid_pages=None, page_count=None, code=400):
        self.message = message
        self.invalid_pages = invalid_pages
        self.code = code
        self.page_count = page_count


class QueueNames:
    LETTERS = 'letter-tasks'
    SANITISE_LETTERS = 'sanitise-letter-tasks'


class TaskNames:
    PROCESS_SANITISED_LETTER = 'process-sanitised-letter'
    UPDATE_BILLABLE_UNITS_FOR_LETTER = 'update-billable-units-for-letter'


queue_prefix = {
    'test': 'test',
    'development': os.environ.get('NOTIFICATION_QUEUE_PREFIX', 'development'),
    'preview': 'preview',
    'staging': 'staging',
    'production': 'live',
}
