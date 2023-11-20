import os
from functools import partial


def sentry_sampler(sampling_context, sample_rate: float = 0.0):
    if sampling_context["parent_sampled"]:
        return 1

    return sample_rate


def init_performance_monitoring():
    environment = os.getenv("NOTIFY_ENVIRONMENT").lower()
    not_production = environment in {"development", "preview", "staging"}
    sentry_enabled = bool(int(os.getenv("SENTRY_ENABLED", "0")))
    sentry_dsn = os.getenv("SENTRY_DSN")

    if environment and sentry_enabled and sentry_dsn:
        import sentry_sdk

        error_sample_rate = float(os.getenv("SENTRY_ERRORS_SAMPLE_RATE", 0.0))
        trace_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", 0.0))

        # Profiles sample rate is relative to trace_sample_rate, so if this is set to 0.1,
        # 10% of traced requests will be profiled.
        profiles_sample_rate = float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", 0.0))

        send_pii = True if not_production else False
        send_request_bodies = "medium" if not_production else "never"

        traces_sampler = partial(sentry_sampler, sample_rate=trace_sample_rate)

        try:
            from app.version import __git_commit__

            release = __git_commit__
        except ImportError:
            release = None

        sentry_sdk.init(
            dsn=sentry_dsn,
            environment=environment,
            sample_rate=error_sample_rate,
            send_default_pii=send_pii,
            max_request_body_size=send_request_bodies,
            traces_sampler=traces_sampler,
            profiles_sample_rate=profiles_sample_rate,
            release=release,
        )
