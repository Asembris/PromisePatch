"""structlog configuration.

Logs are JSON in every environment, because the only consumers that matter are CloudWatch and
``jq``. Two conventions are established here and relied on by every later phase:

* a ``correlation_id`` is bound per request into a context variable, so every log line a
  request causes carries it without threading an argument through the call stack;
* logs are **not** the audit trail. They may be sampled, dropped or rotated. The authoritative
  business record is the append-only ledger in PostgreSQL, and nothing may infer from a log
  line that a governed write happened.

**No log line carries a customer approval link.** The link's token is a possession credential:
whoever holds it can answer the request it opens, and its payload also carries the customer's
channel address (ADR-0021). It reaches this process in two forms -- the page at ``/?approve=``
and the API at ``/api/customer/approval/`` -- and uvicorn's access log wrote both verbatim to
CloudWatch. So every line this module configures is redacted *after* it is rendered, not field
by field before: a request line, a structured event, a traceback and a ``repr`` fallback all pass
the same pattern, and a log call added later cannot forget to. See
``docs/phase7-approval-log-privacy-repair.md``.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any, Final

import structlog

from promisepatch.config import Settings

REDACTED: Final = "REDACTED"
"""What an approval token is replaced with. The same word the TLS proxy writes in its place."""

APPROVAL_LINK: Final = re.compile(r"(approve=|approval/)[^?&#\s\"'\\]+|v1\.[\w-]{20,}\.[\w-]{20,}")
"""Both forms a link takes in a URL, and the bare token wherever else it might appear.

The first alternative keeps its prefix, so a redacted line still says which route was asked for;
it stops at a query delimiter, whitespace, a quote or a backslash, so a token inside a JSON
string or before an escape is removed without eating the character that ends it. The second is
the token's own shape -- ``v1``, a payload and a signature, each far longer than twenty
characters -- so a token logged outside a URL is caught too, while a version string such as
``v1.2.3`` is not. Declared here rather than imported from ``domain.customer_link``, which this
layer may not depend on; ``test_log_redaction.py`` asserts it against the real link and route.
"""

TRANSPORT_LOGGERS: Final = ("", "uvicorn", "uvicorn.access")
"""The standard-library loggers whose handlers write this process's lines.

The root, and uvicorn's two -- ``uvicorn.access`` holds the request line and does not propagate,
and ``uvicorn.error`` propagates into ``uvicorn``'s handler. uvicorn installs these before it
imports the application, so by the time :func:`configure_logging` runs they exist to be wrapped.
"""


def redact_approval_links(text: str) -> str:
    """``text`` with every approval token replaced. Everything else is returned untouched."""
    return APPROVAL_LINK.sub(lambda match: f"{match.group(1) or ''}{REDACTED}", text)


class _RedactingFormatter(logging.Formatter):
    """A handler's own formatter, with its finished line passed through the redaction.

    Wrapping the formatter rather than filtering the record is what makes this complete: the
    message, its arguments, an exception's traceback and a stack are all rendered by the time
    ``format`` returns, so none of them can carry a token past it.
    """

    def __init__(self, inner: logging.Formatter | None) -> None:
        super().__init__()
        self.inner = inner or logging.Formatter()

    def format(self, record: logging.LogRecord) -> str:
        return redact_approval_links(self.inner.format(record))


def _redact_rendered(_: Any, __: str, rendered: str) -> str:
    """The last structlog processor: the rendered JSON line, redacted."""
    return redact_approval_links(rendered)


def _install_redaction() -> None:
    """Wrap every transport handler's formatter once. Wrapping twice would be harmless but noisy."""
    for name in TRANSPORT_LOGGERS:
        for handler in logging.getLogger(name).handlers:
            if not isinstance(handler.formatter, _RedactingFormatter):
                handler.setFormatter(_RedactingFormatter(handler.formatter))


def configure_logging(settings: Settings) -> None:
    """Configure structlog and the standard-library root logger. Idempotent."""
    level = logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    _install_redaction()
    # A handler that cannot write reports it through ``Handler.handleError``, which prints the
    # record's raw arguments and the exception in flight straight to stderr -- past every
    # formatter, so past the redaction. The standard library's own production setting is to
    # print nothing; a lost log line is the lesser harm next to a credential in the one that
    # replaces it.
    logging.raiseExceptions = False

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
        _redact_rendered,
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
