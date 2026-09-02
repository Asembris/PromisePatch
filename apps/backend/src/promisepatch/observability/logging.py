"""structlog configuration.

Logs are JSON in every environment, because the only consumers that matter are CloudWatch and
``jq``. Two conventions are established here and relied on by every later phase:

* a ``correlation_id`` is bound per request into a context variable, so every log line a
  request causes carries it without threading an argument through the call stack;
* logs are **not** the audit trail. They may be sampled, dropped or rotated. The authoritative
  business record is the append-only ledger in PostgreSQL, and nothing may infer from a log
  line that a governed write happened.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from promisepatch.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure structlog and the standard-library root logger. Idempotent."""
    level = logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def bind_correlation_id(correlation_id: str) -> None:
    """Bind a correlation id for the current context (one request, one task)."""
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
