import json
import os

from kombu import Exchange, Queue


class QueueNames:
    LETTERS = 'letter-tasks'
    SANITISE_LETTERS = 'sanitise-letter-tasks'


class TaskNames:
    PROCESS_SANITISED_LETTER = 'process-sanitised-letter'
    UPDATE_BILLABLE_UNITS_FOR_LETTER = 'update-billable-units-for-letter'
    UPDATE_VALIDATION_FAILED_FOR_TEMPLATED_LETTER = 'update-validation-failed-for-templated-letter'


class Config:
    AWS_REGION = 'eu-west-1'
    TEMPLATE_PREVIEW_INTERNAL_SECRETS = json.loads(
        os.environ.get('TEMPLATE_PREVIEW_INTERNAL_SECRETS', '[]')
    )
    NOTIFY_ENVIRONMENT = os.environ['NOTIFY_ENVIRONMENT']
    NOTIFY_APP_NAME = 'template-preview'
    DANGEROUS_SALT = os.environ['DANGEROUS_SALT']
    SECRET_KEY = os.environ['SECRET_KEY']

    CELERY = {
        'broker_url': 'sqs://',
        'broker_transport_options': {
            'region': AWS_REGION,
            'visibility_timeout': 310,
            'wait_time_seconds': 20,  # enable long polling, with a wait time of 20 seconds
            'queue_name_prefix': ({
                'test': 'test',
                'development': os.environ.get('NOTIFICATION_QUEUE_PREFIX', 'development'),
                'preview': 'preview',
                'staging': 'staging',
                'production': 'live',
            }[NOTIFY_ENVIRONMENT]),
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
        NOTIFY_LOG_PATH = os.environ['NOTIFY_LOG_PATH']

    EXPIRE_CACHE_IN_SECONDS = 600

    if os.environ['STATSD_ENABLED'] == "1":
        STATSD_ENABLED = True
        STATSD_HOST = os.environ['STATSD_HOST']
        STATSD_PORT = 8125
    else:
        STATSD_ENABLED = False

    LETTERS_SCAN_BUCKET_NAME = f'{NOTIFY_ENVIRONMENT}-letters-scan'
    LETTER_CACHE_BUCKET_NAME = f'{NOTIFY_ENVIRONMENT}-template-preview-cache'
    LETTERS_PDF_BUCKET_NAME = f'{NOTIFY_ENVIRONMENT}-letters-pdf'
    TEST_LETTERS_BUCKET_NAME = f'{NOTIFY_ENVIRONMENT}-test-letters'
    INVALID_PDF_BUCKET_NAME = f'{NOTIFY_ENVIRONMENT}-letters-invalid-pdf'
    SANITISED_LETTER_BUCKET_NAME = f'{NOTIFY_ENVIRONMENT}-letters-sanitise'
    PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME = f'{NOTIFY_ENVIRONMENT}-letters-precompiled-originals-backup'

    LETTER_LOGO_URL = 'https://static-logos.{}/letters'.format({
        'test': 'notify.tools',
        'development': 'notify.tools',
        'preview': 'notify.works',
        'staging': 'staging-notify.works',
        'production': 'notifications.service.gov.uk'
    }[NOTIFY_ENVIRONMENT])
