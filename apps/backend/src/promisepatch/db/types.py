"""Column types and the vocabularies the database checks against.

Two conventions here are load-bearing rather than stylistic:

* **Quantities are ``NUMERIC(14,3)`` and never a float.** The engine refuses to construct a
  quantity from a float because allocation order, shortfall arithmetic and fingerprints must
  be reproducible; a ``double precision`` column would reintroduce exactly what the engine
  rejects, one layer down.
* **Timestamps are always ``TIMESTAMPTZ``.** A naive timestamp cannot round-trip into the
  engine at all: its records reject any datetime without a timezone.

Closed vocabularies are stored as ``TEXT`` with a ``CHECK``, not as PostgreSQL ``ENUM``
types. A new member is then an ordinary migration rather than an ``ALTER TYPE`` that cannot
run inside a transaction, and the permitted values are readable in ``psql`` without a lookup.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Numeric
from sqlalchemy.types import UserDefinedType

QUANTITY_PRECISION = 14
QUANTITY_SCALE = 3
"""Matches ``promise_graph.model.QUANTITY_EXPONENT``: three decimal places, exactly."""

Quantity = Numeric(QUANTITY_PRECISION, QUANTITY_SCALE, asdecimal=True)
Timestamp = DateTime(timezone=True)

QuantityType = Decimal
TimestampType = datetime


class XID8(UserDefinedType[str]):
    """PostgreSQL ``xid8``: a transaction id that does not wrap around.

    Recorded on the audit ledger so a later slice can prove an audit row was written by the
    *same* transaction as the governed write it authorises. ``txid_current()`` is deliberately
    not used: its 32-bit counter wraps, and a wrapped id would eventually make two unrelated
    transactions indistinguishable.
    """

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "xid8"


def enum_check(column: str, values: tuple[str, ...], *, name: str) -> CheckConstraint:
    """A ``CHECK`` restricting a column to a closed set of values."""
    rendered = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({rendered})", name=name)


def members(enum_cls: type[StrEnum]) -> tuple[str, ...]:
    """The values of an engine vocabulary, in declaration order.

    Deriving the ``CHECK`` from the engine's own enum is what keeps the two ends honest: a
    value the database accepts but the engine cannot parse — or the reverse — becomes a
    failing test rather than a row nobody can load.
    """
    return tuple(member.value for member in enum_cls)


CASE_STATES: tuple[str, ...] = (
    "RECEIVED",
    "INTERPRETING",
    "CLARIFYING",
    "NEEDS_HUMAN_INTERPRETATION",
    "ANALYZED",
    "PLANNED",
    "EXECUTING",
    "WAITING",
    "REVALIDATING",
    "RECONCILING",
    "RESOLVED",
    "CANCELLED",
)
"""The frozen case states. The transition table that walks them is a later slice."""

REPORT_KINDS: tuple[str, ...] = ("REPORT", "CLARIFICATION_ANSWER", "CORRECTION")
"""Why a worker spoke, which decides what their words are permitted to mean.

Mirrors :class:`promisepatch.domain.observation.ReportKind`; a test asserts the two agree.
"""

CLARIFICATION_SLOTS: tuple[str, ...] = ("COMMITMENT", "SCOPE")
"""The parts of a binding that can be materially ambiguous, per the frozen triggers."""

TRACK_STATES: tuple[str, ...] = (
    "PENDING",
    "UNAFFECTED",
    "WAITING_FOR_CUSTOMER",
    "APPLYING",
    "RECOVERED",
    "ESCALATED",
    "WITHDRAWN",
    "STALE",
    "LINKED",
)

TERMINAL_TRACK_STATES: tuple[str, ...] = (
    "UNAFFECTED",
    "RECOVERED",
    "ESCALATED",
    "WITHDRAWN",
    "LINKED",
)
"""States in which a track no longer holds its promise, so another case may claim it."""

ACTOR_KINDS: tuple[str, ...] = ("WORKER", "OWNER", "CUSTOMER", "SYSTEM", "LLM")
AUTHORITIES: tuple[str, ...] = ("POLICY", "CONSTRAINT", "HUMAN_APPROVAL", "NONE")
WORKER_ROLES: tuple[str, ...] = ("baker", "owner", "observer")
"""What a member of staff may be, and therefore what the domain may admit them to.

``observer`` is a principal that can be shown a case and can change nothing. It is a *role*
rather than a scope on a session because the refusal then belongs to the domain: every write
gates on :func:`promisepatch.domain.intake.require_permitted`, which admits the worker who
opened a case or an owner and knows nothing about observers, so a write route added later with
no observer check still refuses one. A session-level scope would put the refusal in whichever
transport remembered to look for it.
"""
CHANNEL_KINDS: tuple[str, ...] = ("telegram", "whatsapp", "console")
STEP_STATES: tuple[str, ...] = ("PENDING", "IN_FLIGHT", "RETRYING", "DONE", "FAILED", "SKIPPED")
INBOX_STATES: tuple[str, ...] = ("RECEIVED", "PROCESSED", "FAILED", "IGNORED")
OUTBOX_STATES: tuple[str, ...] = ("PENDING", "IN_FLIGHT", "DELIVERED", "FAILED")
CONVERSATION_PHASES: tuple[str, ...] = (
    "IDLE",
    "CASE_OPEN_CLARIFYING",
    "CASE_OPEN_PLANNED",
)
