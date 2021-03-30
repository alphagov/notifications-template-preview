import logging

from weasyprint.logger import LOGGER as weasyprint_logs


class WeasyprintError(Exception):
    pass


def init_app(application):

    def evil_error(msg, *args, **kwargs):
        if msg.startswith('Failed to load image'):
            raise WeasyprintError(msg % tuple(args))
        else:
            return weasyprint_logs.log(logging.ERROR, msg, *args, **kwargs)

    weasyprint_logs.error = evil_error
