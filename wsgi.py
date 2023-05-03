from app.performance import init_performance_monitoring

init_performance_monitoring()

import os  # noqa

from app import create_app  # noqa

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

application = create_app()

if __name__ == "__main__":
    application.run()
