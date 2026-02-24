#!/usr/bin/env python

import notifications_utils.logging.celery as celery_logging

from app.performance import init_performance_monitoring

init_performance_monitoring()

from celery.signals import worker_init, worker_process_init  # noqa

from app import create_app, notify_celery  # noqa

application = create_app()
celery_logging.set_up_logging(application.config)


sigabrt_handler = None


def on_worker_process_init(*args, **kwargs):
    import ctypes
    import json
    from datetime import datetime
    from os import getpid
    from signal import SIGABRT
    from traceback import format_stack

    libc_globals = ctypes.CDLL(None)

    global sigabrt_handler  # ensure we retain a reference to the handler because ctypes won't

    @ctypes.CFUNCTYPE(None, ctypes.c_int)
    def sigabrt_handler(sig):
        # the actual logging subsystem is almost certainly not safe to use from a signal handler due to
        # the funny way celery reconfigures it to redirect logs to the parent process, so here mimic
        # a real log entry so we can have some basic diagnostics when we get a SIGABRT. this is still
        # rather nasty as there isn't anything to prevent this log message interleaving or being
        # interleaved by other log entries, but locking is against the rules in a signal handler.
        pid = getpid()
        stderr = open(2, "w")  # sys.stderr is hijacked by celery and redirected to the logging subsystem
        json_log = json.dumps(
            {
                "time": datetime.now().isoformat(),
                "message": f"Process {pid} received SIGABRT",
                "process_": pid,
                "exc_info": "".join(format_stack()),
            },
        )
        stderr.write(f"\n{json_log}\n")
        stderr.flush()

    # the python signal module doesn't quite work properly with SIGABRT, so force-install a raw handler by
    # directly calling the libc signal function
    # https://discuss.python.org/t/how-can-i-handle-sigabrt-from-third-party-c-code-std-abort-call/22078/2
    libc_globals.signal(SIGABRT, sigabrt_handler)


@worker_init.connect
def on_worker_init(*args, **kwargs):
    worker_process_init.connect(on_worker_process_init)
