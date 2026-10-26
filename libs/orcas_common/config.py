"""Small environment-backed configuration shared by the gateway and worker."""

import os


def database_url() -> str:
    value = os.getenv("DATABASE_URL", "")
    if not value:
        raise RuntimeError("DATABASE_URL must be set for persistent runs")
    return value


def celery_broker_url() -> str:
    return os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")


def celery_result_backend() -> str:
    return os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
