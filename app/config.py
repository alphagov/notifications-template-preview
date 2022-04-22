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
    NOTIFY_APP_NAME = 'template-preview'
    DANGEROUS_SALT = os.environ.get('DANGEROUS_SALT')
    SECRET_KEY = os.environ.get('SECRET_KEY')

    NOTIFICATION_QUEUE_PREFIX = os.environ.get('NOTIFICATION_QUEUE_PREFIX')

    CELERY = {
        'broker_url': 'sqs://',
        'broker_transport_options': {
            'region': AWS_REGION,
            'visibility_timeout': 310,
            'wait_time_seconds': 20,  # enable long polling, with a wait time of 20 seconds
            'queue_name_prefix': NOTIFICATION_QUEUE_PREFIX,
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
        NOTIFY_LOG_PATH = os.environ.get('NOTIFY_LOG_PATH')

    EXPIRE_CACHE_IN_SECONDS = 600

    if os.environ.get('STATSD_ENABLED') == "1":
        STATSD_ENABLED = True
        STATSD_HOST = os.environ.get('STATSD_HOST')
        STATSD_PORT = 8125
    else:
        STATSD_ENABLED = False


class Production(Config):
    NOTIFY_ENVIRONMENT = 'production'

    LETTERS_SCAN_BUCKET_NAME = 'production-letters-scan'
    LETTER_CACHE_BUCKET_NAME = 'production-template-preview-cache'
    LETTERS_PDF_BUCKET_NAME = 'production-letters-pdf'
    TEST_LETTERS_BUCKET_NAME = 'production-test-letters'
    INVALID_PDF_BUCKET_NAME = 'production-letters-invalid-pdf'
    SANITISED_LETTER_BUCKET_NAME = 'production-letters-sanitise'
    PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME = 'production-letters-precompiled-originals-backup'

    LETTER_LOGO_URL = 'https://static-logos.notifications.service.gov.uk/letters'


class Staging(Config):
    NOTIFY_ENVIRONMENT = 'staging'

    LETTERS_SCAN_BUCKET_NAME = 'staging-letters-scan'
    LETTER_CACHE_BUCKET_NAME = 'staging-template-preview-cache'
    LETTERS_PDF_BUCKET_NAME = 'staging-letters-pdf'
    TEST_LETTERS_BUCKET_NAME = 'staging-test-letters'
    INVALID_PDF_BUCKET_NAME = 'staging-letters-invalid-pdf'
    SANITISED_LETTER_BUCKET_NAME = 'staging-letters-sanitise'
    PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME = 'staging-letters-precompiled-originals-backup'

    LETTER_LOGO_URL = 'https://static-logos.staging-notify.works/letters'


class Preview(Config):
    NOTIFY_ENVIRONMENT = 'preview'

    LETTERS_SCAN_BUCKET_NAME = 'preview-letters-scan'
    LETTER_CACHE_BUCKET_NAME = 'preview-template-preview-cache'
    LETTERS_PDF_BUCKET_NAME = 'preview-letters-pdf'
    TEST_LETTERS_BUCKET_NAME = 'preview-test-letters'
    INVALID_PDF_BUCKET_NAME = 'preview-letters-invalid-pdf'
    SANITISED_LETTER_BUCKET_NAME = 'preview-letters-sanitise'
    PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME = 'preview-letters-precompiled-originals-backup'

    LETTER_LOGO_URL = 'https://static-logos.notify.works/letters'


class Development(Config):
    NOTIFY_ENVIRONMENT = 'development'

    LETTERS_SCAN_BUCKET_NAME = 'development-letters-scan'
    LETTER_CACHE_BUCKET_NAME = 'development-template-preview-cache'
    LETTERS_PDF_BUCKET_NAME = 'development-letters-pdf'
    TEST_LETTERS_BUCKET_NAME = 'development-test-letters'
    INVALID_PDF_BUCKET_NAME = 'development-letters-invalid-pdf'
    SANITISED_LETTER_BUCKET_NAME = 'development-letters-sanitise'
    PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME = 'development-letters-precompiled-originals-backup'

    LETTER_LOGO_URL = 'https://static-logos.notify.tools/letters'


class Test(Development):
    NOTIFY_ENVIRONMENT = 'test'

    LETTERS_SCAN_BUCKET_NAME = 'test-letters-scan'
    LETTER_CACHE_BUCKET_NAME = 'test-template-preview-cache'
    LETTERS_PDF_BUCKET_NAME = 'test-letters-pdf'
    TEST_LETTERS_BUCKET_NAME = 'test-test-letters'
    INVALID_PDF_BUCKET_NAME = 'test-letters-invalid-pdf'
    SANITISED_LETTER_BUCKET_NAME = 'test-letters-sanitise'
    PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME = 'test-letters-precompiled-originals-backup'


configs = {
    'development': Development,
    'test': Test,
    'production': Production,
    'staging': Staging,
    'preview': Preview,
}
