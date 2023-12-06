from os import getpid

from celery.signals import worker_process_init
from flask import current_app


@worker_process_init.connect
def set_oom_score_adj(**kwargs):
    base_ctx = {
        # avoid collision with LogRecord's `process`.
        "process_": os.getpid(),
    }
    current_app.logger.info(
        "Starting worker process with pid %(process_)s",
        base_ctx,
        extra=base_ctx,
    )

    adj = current_app.config["WORKER_PROCESS_OOM_SCORE_ADJ"]
    if adj:
        try:
            with open("/proc/self/oom_score_adj", "wb") as f:
                f.write(str(adj).encode("ascii"))
        except Exception as e:
            ctx = {
                **base_ctx,
                "exc": str(e),
            }
            current_app.logger.warning(
                "Failed to set oom_score_adj in pid %(process_)s initialization: %(exc)s",
                ctx,
                extra=ctx,
            )
            # don't propagate exception - we don't want our nonsense to cause real problems
