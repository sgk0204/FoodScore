"""Structured JSON logging with request/scan correlation (guide §13).

Never log passwords, tokens or image bytes. User ids are hashed before logging.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from typing import Any

import structlog

_REDACT_KEYS = {"password", "token", "access_token", "refresh_token", "authorization", "image"}


def _redact(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict):
        if key.lower() in _REDACT_KEYS:
            event_dict[key] = "[redacted]"
    return event_dict


def hash_id(value: object) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def configure_logging(level: str = "INFO", *, json: bool = True) -> None:
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[*processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=level.upper(), stream=sys.stdout, format="%(message)s")


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
