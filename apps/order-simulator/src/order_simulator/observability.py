"""Structured logging for the simulator, with the fields an operator actually needs.

Deliberately small: this application has one job and a handful of events worth recording. Every
line carries the order, the version, the event and the attempt, because when a demo goes wrong
the question is always "which mutation, at which version, and did its webhook get there".

No secret is ever a field here. The webhook secret is held in a
:class:`~pydantic.SecretStr` and is passed straight into the signature, so there is no
formatting path it could reach.
"""

from __future__ import annotations

import logging
import sys
from typing import Any


class _Logger:
    """A thin structured wrapper over :mod:`logging`, so the app needs no logging dependency."""

    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    def _emit(self, level: int, event: str, **fields: Any) -> None:
        rendered = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
        self._log.log(level, "%s %s", event, rendered)

    def info(self, event: str, **fields: Any) -> None:
        self._emit(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit(logging.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit(logging.ERROR, event, **fields)


def get_logger(name: str) -> _Logger:
    return _Logger(name)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
