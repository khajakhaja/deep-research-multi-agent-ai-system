"""Logging configuration with secret redaction.

A single :func:`configure_logging` call sets up console logging that includes
the research id when log records provide one, and a :class:`RedactionFilter`
that scrubs API keys and tokens from log messages before they are emitted.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any, Dict

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key[\"'=:\s]+)([A-Za-z0-9_\-]{8,})"),
    re.compile(r"(?i)(authorization[\"'=:\s]+bearer\s+)([A-Za-z0-9._\-]{8,})"),
    re.compile(r"(sk-[A-Za-z0-9]{10,})"),
    re.compile(r"(tvly-[A-Za-z0-9]{10,})"),
    re.compile(r"(lsv2_[A-Za-z0-9]{10,})"),
    re.compile(r"(?i)(password[\"'=:\s]+)(\S{4,})"),
]

_REDACTED = "***REDACTED***"


def redact(text: str) -> str:
    """Return ``text`` with anything that looks like a secret replaced."""
    if not text:
        return text
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(lambda m: m.group(1) + _REDACTED if m.lastindex else _REDACTED, result)
    return result


class RedactionFilter(logging.Filter):
    """Logging filter that redacts secrets from formatted messages."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D102
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


class _ResearchIdFormatter(logging.Formatter):
    """Formatter that includes the research id when present on the record."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D102
        if not hasattr(record, "research_id"):
            record.research_id = "-"
        return super().format(record)


class _JsonFormatter(logging.Formatter):
    """Minimal JSON formatter for structured production logs."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D102
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        research_id = getattr(record, "research_id", None)
        if research_id:
            payload["research_id"] = research_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """Configure root logging for the application.

    Repeated calls are idempotent.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactionFilter())

    if json_logs:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            _ResearchIdFormatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | rid=%(research_id)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    root.addHandler(handler)

    # Tame noisy third-party loggers.
    for noisy in ("httpx", "httpcore", "urllib3", "openai", "tavily"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger."""
    return logging.getLogger(name)
