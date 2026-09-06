"""Logging configuration.

Logs go to stderr and to a rotating file under the data directory. Secrets are
never logged: the redacting filter scrubs anything that looks like an API key.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{8,})", re.IGNORECASE
)


class RedactingFilter(logging.Filter):
    """Scrub credential-shaped substrings from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _SECRET_PATTERN.sub("[REDACTED]", record.msg)
        if record.args:
            record.args = tuple(
                _SECRET_PATTERN.sub("[REDACTED]", a) if isinstance(a, str) else a
                for a in (record.args if isinstance(record.args, tuple) else (record.args,))
            )
        return True


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)-24s %(message)s", "%H:%M:%S")

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    stream.addFilter(RedactingFilter())
    root.addHandler(stream)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        fileh = logging.handlers.RotatingFileHandler(
            log_dir / "encarta.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        fileh.setFormatter(fmt)
        fileh.addFilter(RedactingFilter())
        root.addHandler(fileh)
