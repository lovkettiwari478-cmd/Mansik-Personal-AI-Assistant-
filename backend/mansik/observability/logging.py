"""Structured JSON logging.

Never log secrets (API keys, passwords, session tokens, message bodies by
default). Every log line carries a request_id when inside a request context.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
execution_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("execution_id", default="-")

_REDACT_KEYS = {"password", "api_key", "token", "secret", "authorization", "cookie"}


def _redact(obj):
    if isinstance(obj, dict):
        return {
            k: ("<redacted>" if any(r in k.lower() for r in _REDACT_KEYS) else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_redact(v) for v in obj]
    return obj


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "execution_id": execution_id_var.get(),
        }
        extra = getattr(record, "extra_data", None)
        if extra:
            payload["data"] = _redact(extra)
        if record.exc_info and record.exc_info[0]:
            payload["exception"] = self.formatException(record.exc_info)[-2000:]
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.handlers = [handler]
    # Quiet noisy libraries (they still go through the JSON handler).
    for name in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log(logger: logging.Logger, level: str, message: str, **data) -> None:
    logger.log(getattr(logging, level.upper()), message, extra={"extra_data": data})
