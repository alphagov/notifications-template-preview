import time

from celery import Celery, Task


class NotifyCelery(Celery):

    def init_app(self, app):
        # this task is nested so that it has access to the original flask application - when celery restarts processes,
        # it doesn't appear to execute the whole import process again, and as such, flask.current_app no longer has
        # a context, and throws a RuntimeError. So we need to create an app context from scratch each time.
        class NotifyTask(Task):
            abstract = True
            start = None

            def on_success(self, retval, task_id, args, kwargs):
                elapsed_time = time.time() - self.start
                app.logger.info(
                    "Celery task {task_name} took {time}".format(
                        task_name=self.name, time="{0:.4f}".format(elapsed_time)
                    )
                )

            def on_failure(self, exc, task_id, args, kwargs, einfo):
                # ensure task will log exceptions to correct handlers
                with app.app_context():
                    app.logger.exception('Celery task {} failed'.format(self.name))
                    super().on_failure(exc, task_id, args, kwargs, einfo)

            def __call__(self, *args, **kwargs):
                # ensure task has flask context to access config, logger, etc
                with app.app_context():
                    return super().__call__(*args, **kwargs)

        super().__init__(
            app.import_name,
            broker=app.config['celery']['broker_url'],
            task_cls=NotifyTask,
        )

        self.conf.update(app.config['celery'])
