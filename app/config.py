import json
import os

from kombu import Exchange, Queue


class QueueNames:
    LETTERS = "letter-tasks"
    SANITISE_LETTERS = "sanitise-letter-tasks"

    @staticmethod
    def all_queues():
        return [
            QueueNames.LETTERS,
            QueueNames.SANITISE_LETTERS,
        ]

    @staticmethod
    def predefined_queues(prefix, aws_region, aws_account_id):
        return {
            f"{prefix}{queue}": {"url": f"https://sqs.{aws_region}.amazonaws.com/{aws_account_id}/{prefix}{queue}"}
            for queue in QueueNames.all_queues()
        }


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

    NOTIFICATION_QUEUE_PREFIX = os.environ.get("NOTIFICATION_QUEUE_PREFIX")

    AWS_ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID", "123456789012")
    CELERY = {
        "broker_url": "https://sqs.eu-west-1.amazonaws.com",
        "broker_transport": "sqs",
        "broker_transport_options": {
            "region": AWS_REGION,
            "wait_time_seconds": 20,  # enable long polling, with a wait time of 20 seconds
            "queue_name_prefix": NOTIFICATION_QUEUE_PREFIX,
            "is_secure": True,
            "predefined_queues": QueueNames.predefined_queues(NOTIFICATION_QUEUE_PREFIX, AWS_REGION, AWS_ACCOUNT_ID),
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

    CELERY = {
        **Config.CELERY,
        "broker_transport_options": {
            key: value for key, value in Config.CELERY["broker_transport_options"].items() if key != "predefined_queues"
        },
    }


class Test(Development):
    NOTIFY_ENVIRONMENT = "test"

    LETTERS_SCAN_BUCKET_NAME = "test-letters-scan"
    LETTER_CACHE_BUCKET_NAME = "test-template-preview-cache"
    LETTERS_PDF_BUCKET_NAME = "test-letters-pdf"
    TEST_LETTERS_BUCKET_NAME = "test-test-letters"
    INVALID_PDF_BUCKET_NAME = "test-letters-invalid-pdf"
    SANITISED_LETTER_BUCKET_NAME = "test-letters-sanitise"
    PRECOMPILED_ORIGINALS_BACKUP_LETTER_BUCKET_NAME = "test-letters-precompiled-originals-backup"
    LETTER_ATTACHMENT_BUCKET_NAME = "test-letter-attachments"
    CELERY = {
        **Config.CELERY,
        "broker_transport_options": {
            key: value for key, value in Config.CELERY["broker_transport_options"].items() if key != "predefined_queues"
        },
    }


configs = {
    "development": Development,
    "test": Test,
}
