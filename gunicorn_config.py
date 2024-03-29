import os
import sys
import traceback

workers = 5
timeout = 120
errorlog = "/home/vcap/logs/gunicorn_error.log"
bind = "0.0.0.0:{}".format(os.getenv("PORT"))

max_requests = 10


def on_starting(server):
    server.log.info("Starting Notifications template preview")


def worker_abort(worker):
    worker.log.info("worker received ABORT %s", worker.pid)
    for _thread_id, stack in sys._current_frames().items():
        worker.log.error("".join(traceback.format_stack(stack)))


def on_exit(server):
    server.log.info("Stopping Notifications template preview")


def worker_int(worker):
    worker.log.info("worker: received SIGINT %s", worker.pid)
