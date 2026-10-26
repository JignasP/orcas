"""JSON logs with a request/run correlation ID."""

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone


correlation_id = contextvars.ContextVar("correlation_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        body = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id.get() or getattr(record, "correlation_id", ""),
        }
        if record.exc_info:
            body["exception"] = self.formatException(record.exc_info)
        return json.dumps(body, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
