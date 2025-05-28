import json
import os

from kombu import Exchange, Queue


class QueueNames:
    LETTERS = "letter-tasks"
    SANITISE_LETTERS = "sanitise-letter-tasks"


class TaskNames:
    PROCESS_SANITISED_LETTER = "process-sanitised-letter"
    UPDATE_BILLABLE_UNITS_FOR_LETTER = "update-billable-units-for-letter"
    UPDATE_VALIDATION_FAILED_FOR_TEMPLATED_LETTER = "update-validation-failed-for-templated-letter"


class Config:
    AWS_REGION = "eu-west-1"
    TEMPLATE_PREVIEW_INTERNAL_SECRETS = json.loads(os.environ.get("TEMPLATE_PREVIEW_INTERNAL_SECRETS", "[]"))
    NOTIFY_APP_NAME = "template-preview"
    DANGEROUS_SALT = os.environ.get("DANGEROUS_SALT")
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # Celery log levels
    CELERY_WORKER_LOG_LEVEL = os.getenv("CELERY_WORKER_LOG_LEVEL", "CRITICAL").upper()
    CELERY_BEAT_LOG_LEVEL = os.getenv("CELERY_BEAT_LOG_LEVEL", "INFO").upper()

    NOTIFICATION_QUEUE_PREFIX = os.environ.get("NOTIFICATION_QUEUE_PREFIX")

    CELERY = {
        "broker_url": "https://sqs.eu-west-1.amazonaws.com",
        "broker_transport": "sqs",
        "broker_transport_options": {
            "region": AWS_REGION,
            "visibility_timeout": 310,
            "wait_time_seconds": 20,  # enable long polling, with a wait time of 20 seconds
            "queue_name_prefix": NOTIFICATION_QUEUE_PREFIX,
            "is_secure": True,
        },
        "timezone": "Europe/London",
        "worker_max_memory_per_child": 50,
        "imports": ["app.celery.tasks"],
        "task_queues": [
            Queue(
                QueueNames.SANITISE_LETTERS,
                Exchange("default"),
                routing_key=QueueNames.SANITISE_LETTERS,
            )
        ],
    }

    NOTIFY_REQUEST_LOG_LEVEL = os.getenv("NOTIFY_REQUEST_LOG_LEVEL", "INFO")

    STATSD_ENABLED = True
    STATSD_HOST = os.environ.get("STATSD_HOST")
    STATSD_PORT = 8125

    NOTIFY_ENVIRONMENT = os.environ.get("NOTIFY_ENVIRONMENT")
    LETTERS_SCAN_BUCKET_NAME = os.environ.get("LETTERS_SCAN_BUCKET_NAME")
    LETTER_CACHE_BUCKET_NAME = os.environ.get("LETTER_CACHE_BUCKET_NAME")
    LETTERS_PDF_BUCKET_NAME = os.environ.get("LETTERS_PDF_BUCKET_NAME")
    TEST_LETTERS_BUCKET_NAME = os.environ.get("TEST_LETTERS_BUCKET_NAME")
    INVALID_PDF_BUCKET_NAME = os.environ.get("INVALID_PDF_BUCKET_NAME")
    SANITISED_LETTER_BUCKET_NAME = os.environ.get("SANITISED_LETTER_BUCKET_NAME")
    PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME = os.environ.get("PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME")
    LETTER_ATTACHMENT_BUCKET_NAME = os.environ.get("LETTER_ATTACHMENT_BUCKET_NAME")
    LETTER_LOGO_URL = os.environ.get("LETTER_LOGO_URL")


class Development(Config):
    SERVER_NAME = os.getenv("SERVER_NAME")
    NOTIFY_ENVIRONMENT = "development"

    CELERY_WORKER_LOG_LEVEL = "INFO"

    STATSD_ENABLED = False

    LETTERS_SCAN_BUCKET_NAME = "development-letters-scan"
    LETTER_CACHE_BUCKET_NAME = "development-template-preview-cache"
    LETTERS_PDF_BUCKET_NAME = "development-letters-pdf"
    TEST_LETTERS_BUCKET_NAME = "development-test-letters"
    INVALID_PDF_BUCKET_NAME = "development-letters-invalid-pdf"
    SANITISED_LETTER_BUCKET_NAME = "development-letters-sanitise"
    PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME = "development-letters-precompiled-originals-backup"
    LETTER_ATTACHMENT_BUCKET_NAME = "development-letter-attachments"

    LETTER_LOGO_URL = "https://static-logos.notify.tools/letters"


class Test(Development):
    NOTIFY_ENVIRONMENT = "test"

    CELERY_WORKER_LOG_LEVEL = "INFO"

    LETTERS_SCAN_BUCKET_NAME = "test-letters-scan"
    LETTER_CACHE_BUCKET_NAME = "test-template-preview-cache"
    LETTERS_PDF_BUCKET_NAME = "test-letters-pdf"
    TEST_LETTERS_BUCKET_NAME = "test-test-letters"
    INVALID_PDF_BUCKET_NAME = "test-letters-invalid-pdf"
    SANITISED_LETTER_BUCKET_NAME = "test-letters-sanitise"
    PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME = "test-letters-precompiled-originals-backup"
    LETTER_ATTACHMENT_BUCKET_NAME = "test-letter-attachments"


configs = {
    "development": Development,
    "test": Test,
}
