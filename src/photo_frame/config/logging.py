"""Structured-enough logging that never emits secrets."""

from __future__ import annotations

import logging
import re

_SECRET_PATTERNS = (
    re.compile(r"(x-api-key['\"]?\s*[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(api[_-]?key['\"]?\s*[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(password['\"]?\s*[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(authorization['\"]?\s*[:=]\s*)\S+", re.IGNORECASE),
)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = message
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub(r"\1[redacted]", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level.upper(),
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    else:
        root.setLevel(level.upper())
    filt = RedactingFilter()
    for handler in root.handlers:
        if not any(isinstance(existing, RedactingFilter) for existing in handler.filters):
            handler.addFilter(filt)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
