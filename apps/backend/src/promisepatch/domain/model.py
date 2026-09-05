"""What a step is asked, and what it may answer. No I/O, no clock, no database.

A handler receives a :class:`StepContext` -- everything the transaction has already read, under
lock -- and returns a :class:`StepOutcome` describing what should be persisted. It performs
none of it. That split is what makes "what does this step do" answerable without a database and
"did it commit atomically" answerable without reasoning about workflow semantics.

The directives are deliberately declarative. A handler says *arm this deadline* rather than
inserting a timer row, so the persistence layer can decide the lock order, the idempotency
strategy and the transaction the whole set commits in -- decisions a handler is in no position
to make and would eventually make inconsistently.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

# --------------------------------------------------------------------------------- vocabulary


class StepKind(StrEnum):
    """The synthetic handlers this slice proves the infrastructure with.

    Not PromisePatch's real work. Each one exists to drive a persistence boundary to its edge:
    a successor, a deadline, an external effect, a retry, a terminal failure, a guard that
    reads case state. The real exception semantics arrive on top of the same machinery.
    """

    NOOP = "NOOP"
    CHAIN = "CHAIN"
    ARM_TIMER = "ARM_TIMER"
    TIMER_WAKEUP = "TIMER_WAKEUP"
    EMIT_EFFECT = "EMIT_EFFECT"
    FAIL_RETRYABLE = "FAIL_RETRYABLE"
    FAIL_TERMINAL = "FAIL_TERMINAL"
    SKIP_IF_TERMINAL = "SKIP_IF_TERMINAL"


class Disposition(StrEnum):
    """What should become of the step that just ran.

    The values are the ``case_steps.state`` vocabulary itself, so a disposition is written
    straight to the column with no lookup table in between -- and a member the database would
    refuse is a failing test rather than a check violation at three in the morning.
    """

    DONE = "DONE"
    SKIPPED = "SKIPPED"
    RETRYING = "RETRYING"
    FAILED = "FAILED"


class StepResult(StrEnum):
    """What actually happened to a claimed step, as the worker reports it.

    Wider than :class:`Disposition` because two of these are not outcomes of the work at all.
    ``LEASE_LOST`` and ``STALE`` are what a worker discovers when it re-reads its own claim
    under lock and finds that the world moved on while it was away; both write nothing.
    """

    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    FAILED = "FAILED"
    LEASE_LOST = "LEASE_LOST"
    """Another worker owns this step now: the lease expired and was reclaimed."""
    STALE = "STALE"
    """The step is no longer in flight at all. Somebody already settled it."""


TERMINAL_CASE_STATES: Final[frozenset[str]] = frozenset({"RESOLVED", "CANCELLED"})
"""Case states after which no further step should do anything.

Restated here rather than imported: this module may not reach into the persistence layer, and
the vocabulary it mirrors lives beside SQLAlchemy. A test asserts the two still agree.
"""

# ------------------------------------------------------------------------------- event names

EVENT_STEP_COMPLETED: Final = "workflow.step.completed"
EVENT_STEP_SKIPPED: Final = "workflow.step.skipped"
EVENT_STEP_FAILED: Final = "workflow.step.failed"
EVENT_TIMER_FIRED: Final = "workflow.timer.fired"
EVENT_EFFECT_DELIVERED: Final = "workflow.effect.delivered"
EVENT_EFFECT_FAILED: Final = "workflow.effect.failed"
EVENT_INBOX_PROCESSED: Final = "workflow.inbox.processed"
EVENT_INBOX_FAILED: Final = "workflow.inbox.failed"

AUDIT_STEP_EXECUTED: Final = "WORKFLOW_STEP_EXECUTED"
AUDIT_STEP_FAILED: Final = "WORKFLOW_STEP_FAILED"
AUDIT_EFFECT_FAILED: Final = "WORKFLOW_EFFECT_FAILED"
"""Audit types for the three transitions that touch a governed table.

A worker acts under ``authority = NONE``: no policy and no consent permitted a step to run,
the engine simply reached it. Recording that honestly is better than dressing infrastructure
bookkeeping up as a decision somebody made.
"""

WAKEUP_TIMER_KIND: Final = "WORKFLOW_WAKEUP"
FAKE_EFFECT_KIND: Final = "FAKE_EFFECT"
EFFECT_ORDER_AMEND: Final = "ORDER_AMEND"
"""The §13.3 outbox kind for a governed recovery amendment pushed at the order system.

Named here, beside the other effect vocabulary, because three parties have to agree on the
string: the transition that enqueues it, the dispatcher that routes it and the adapter that
sends it. The adapter is deliberately unable to import the transition -- it may not reach a
database -- so the shared word has to live somewhere neither of them owns.
"""
CASE_SUBJECT: Final = "CASE"

EFFECT_CASE_ID: Final = "case_id"
EFFECT_TRACK_ID: Final = "track_id"
"""The two payload keys an outbound effect is indexed by, wherever it came from.

Named here rather than in whichever module writes them, because the dispatcher, the evidence
read model and the transition that enqueued the effect all have to agree on them, and three
string literals in three files agree only until somebody edits one.
"""

# --------------------------------------------------------------------------------- directives


@dataclass(frozen=True, slots=True)
class CreateStep:
    """Enqueue a successor. ``step_key`` is unique per case, so proposing it twice is a no-op.

    ``kind`` is a :class:`StepKind` or a plain string, because not every unit of work is one of
    the synthetic handlers this enum names: intake steps need the graph to decide and are
    dispatched by name instead. The column is ``VARCHAR(64)`` either way, and a stored kind
    nothing can execute fails loudly rather than being skipped.
    """

    step_key: str
    kind: StepKind | str


@dataclass(frozen=True, slots=True)
class ArmTimer:
    """Arm a deadline, relative to the instant the transaction read from the database.

    A delay rather than an absolute time, because the handler is not allowed to know what time
    it is; the transaction tells it, once, and every derived instant is measured from that.
    """

    kind: str
    subject_type: str
    subject_id: str
    delay: timedelta


@dataclass(frozen=True, slots=True)
class CancelTimer:
    """Drop an unfired deadline, because the transition being made has made it obsolete."""

    kind: str
    subject_type: str
    subject_id: str


@dataclass(frozen=True, slots=True)
class EmitEffect:
    """Enqueue an outbound effect in the same transaction as the decision that caused it.

    ``idempotency_key`` is derived from server-side identifiers and is unique across the whole
    outbox, so a redelivery after an uncertain send carries the same key rather than becoming a
    second effect.
    """

    kind: str
    payload: Mapping[str, Any]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class AppendEvent:
    """One further event the transition wants on the spine, after its own.

    A step transition always announces itself (``workflow.step.completed``); a transition that
    also changed something a person cares about -- a physical fact recorded, a question asked --
    says so in its own words here. Appended in order, immediately after the step's event and
    inside the same transaction, so the two can never be separated by a crash.
    """

    type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    entity_refs: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class CaseChange:
    """What the transition does to the case row. ``version`` is always bumped; this is the rest."""

    state: str | None = None
    needs_owner_attention: bool | None = None


# ---------------------------------------------------------------------------- input and output


@dataclass(frozen=True, slots=True)
class StepContext:
    """Everything the execution transaction has already read, under lock.

    ``case_state`` and ``now`` are passed in rather than fetched, which is what keeps a handler
    deterministic: run it twice with the same context and it decides the same thing, whatever
    the clock and the database have done in between.
    """

    step_id: UUID
    case_id: UUID
    step_key: str
    kind: StepKind
    attempts: int
    case_state: str
    now: datetime

    @property
    def case_is_terminal(self) -> bool:
        return self.case_state in TERMINAL_CASE_STATES


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """A description of what to persist. The handler persists none of it."""

    disposition: Disposition
    event_type: str
    case_change: CaseChange = CaseChange()
    successors: tuple[CreateStep, ...] = ()
    timers: tuple[ArmTimer, ...] = ()
    cancellations: tuple[CancelTimer, ...] = ()
    effects: tuple[EmitEffect, ...] = ()
    events: tuple[AppendEvent, ...] = ()
    result: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def is_failure(self) -> bool:
        return self.disposition in (Disposition.RETRYING, Disposition.FAILED)


@dataclass(frozen=True, slots=True)
class InboundOutcome:
    """What a source handler made of one stored inbound record.

    ``normalized`` is the shape the rest of the system reads; the raw provider material stays on
    the inbox row and is never consulted again by a decision.
    """

    state: str
    normalized: Mapping[str, Any] | None = None
    case_id: UUID | None = None
    step_key: str | None = None
    step_kind: StepKind | str | None = None
    """The work this record makes runnable, if any.

    A plain string as well as a :class:`StepKind`, for the same reason
    :class:`CreateStep` accepts one: a customer's reply is executed by a step that reads rows to
    decide, which is dispatched by name rather than by one of the synthetic handlers.
    """

    error: str | None = None


class DeliveryStatus(StrEnum):
    """What a provider said, reduced to the three answers the dispatcher can act on."""

    DELIVERED = "DELIVERED"
    RETRYABLE = "RETRYABLE"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """One adapter call's result. ``provider_ref`` is the provider's own identifier for it."""

    status: DeliveryStatus
    provider_ref: str | None = None
    error: str | None = None
    result: Mapping[str, Any] | None = None
    """What the provider reported it did, for a provider that is a system of record.

    Absent for one that is not. That absence is meaningful rather than incidental: an effect
    whose provider made no authoritative statement has nothing for PromisePatch to later
    verify, and one that did must be verified before the work it belongs to may claim to be
    finished.
    """
