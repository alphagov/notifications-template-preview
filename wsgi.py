import os

from app import create_app  # noqa

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

application = create_app()
