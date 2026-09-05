"""Infrastructure of the durable engine: events, steps, timers, inbox, outbox, conversations.

These tables exist so that restart safety is a property of the database rather than of any
running process: a worker that dies holds nothing, because everything it was doing is a row.

Three primitives here carry the whole restart story, and each is enforced by the database
rather than by a convention a future writer has to remember:

* a **lease** (``lease_owner``, ``lease_expires_at``) says which worker owns a unit of work and
  until when, so a dead process becomes an expired claim rather than a stuck row;
* ``attempts`` is the **fencing token**. The claim increments it, so a stalled worker's
  completion names an attempt that no longer exists and matches no row;
* **uniqueness** decides the races that matter -- one step per ``(case_id, step_key)``, one
  live timer per subject, one effect per idempotency key -- so a duplicate is a no-op in
  PostgreSQL rather than a second real-world consequence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from promisepatch.db.base import Base
from promisepatch.db.types import (
    CONVERSATION_PHASES,
    INBOX_STATES,
    OUTBOX_STATES,
    STEP_STATES,
    Timestamp,
    enum_check,
)

_IN_FLIGHT_LEASE = (
    "state <> 'IN_FLIGHT' OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)"
)
"""Executing means owned, by somebody, until a stated instant. Written once for both leases."""


class DomainEvent(Base):
    """The append-only sequence spine.

    ``seq`` is the single global order every consumer checkpoints against, and the value the
    graph snapshot is stamped with so a reader can say exactly how current its view was.
    ``entity_refs`` names what changed, which is how a later slice recomputes only the tracks
    that were actually watching a touched entity. Like the audit ledger, it holds no foreign
    key into the domain: the record of what happened outlives the rows it happened to.

    **``seq`` is commit-ordered, and not by this column.** The mapped default draws a value
    that a ``BEFORE INSERT`` trigger then discards and redraws while holding a transaction
    advisory lock, which is what makes ``seq(e1) < seq(e2) ⇒ commit(e1) < commit(e2)`` true for
    committed rows. Appending an event is therefore the last lock a transaction may take; see
    :func:`promisepatch.db.events.append_event`. The default stays because a row inserted with
    no trigger must fail loudly rather than arrive with a null key, and it is why the committed
    numbers have gaps.
    """

    __tablename__ = "domain_events"
    __table_args__ = (Index("ix_domain_events_type_seq", "type", "seq"),)

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    case_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    entity_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    correlation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        Timestamp, nullable=False, server_default=func.now()
    )


class CaseStep(Base):
    """One idempotent unit of execution within a case.

    ``(case_id, step_key)`` is unique so that resuming after a crash re-enters the plan rather
    than re-running it: a step that already committed cannot be enqueued a second time, and a
    successor a retried transition proposes twice is refused by the database.

    ``attempts`` is the fencing token as well as the retry counter. A claim moves the row to
    ``IN_FLIGHT`` and increments it in one statement, so ``(state, lease_owner, attempts)``
    identifies exactly one claim: a worker that stalled past its lease and woke up to find the
    step reclaimed matches no row, and writes nothing. A second version column would say the
    same thing twice and could disagree with itself.
    """

    __tablename__ = "case_steps"
    __table_args__ = (
        enum_check("state", STEP_STATES, name="state"),
        # A negative attempt count would make the fencing token meaningless and the backoff
        # ladder index out of range; neither should be reachable by any statement at all.
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        # An IN_FLIGHT row with no lease could never be reclaimed: nothing would say when its
        # owner's claim ran out, so a crash there would strand the step for good.
        CheckConstraint(_IN_FLIGHT_LEASE, name="in_flight_lease"),
        UniqueConstraint("case_id", "step_key", name="uq_case_steps_case_step_key"),
        Index("ix_case_steps_state_next_attempt", "state", "next_attempt_at"),
        # The reclaim path: expired leases only, so the sweep never walks live or settled rows.
        Index(
            "ix_case_steps_lease_expires_at",
            "lease_expires_at",
            postgresql_where=text("state = 'IN_FLIGHT'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    case_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    track_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    step_key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        Timestamp, nullable=False, server_default=func.now()
    )


class Timer(Base):
    """A deadline that survives a restart, because it is a row rather than a scheduled task.

    ``ix_timers_live_subject`` is what makes arming idempotent: at most one *unfired* timer per
    ``(kind, subject_type, subject_id)``, so a transition that re-arms a deadline it already
    armed produces one wake-up rather than two. The index is partial on purpose -- once a timer
    has fired it stops constraining anything, and the same semantic deadline may be armed again
    for the next round.
    """

    __tablename__ = "timers"
    __table_args__ = (
        Index("ix_timers_due_unfired", "due_at", postgresql_where=text("fired_at IS NULL")),
        Index(
            "ix_timers_live_subject",
            "kind",
            "subject_type",
            "subject_id",
            unique=True,
            postgresql_where=text("fired_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    due_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    fired_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)


class InboxEvent(Base):
    """Every inbound webhook or queue record, stored before anything is done with it.

    ``(source, provider_event_id)`` is unique, which is the whole of the duplicate-delivery
    story: a provider that retries an update produces a unique-violation and a no-op, not a
    second decision. Processing always reads the stored row, never the live request.
    """

    __tablename__ = "inbox_events"
    __table_args__ = (
        enum_check("state", INBOX_STATES, name="state"),
        UniqueConstraint("source", "provider_event_id", name="uq_inbox_events_source_event"),
        Index("ix_inbox_events_state_received", "state", "received_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_headers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    normalized: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class OutboxMessage(Base):
    """An outbound effect, enqueued in the same transaction as the state change that caused it.

    The idempotency key is derived from server-side ids and is unique, so a retry after an
    uncertain delivery cannot become a second amendment.

    **The guarantee this table provides is at-least-once dispatch under a stable key.** A
    process that dies between the provider accepting a call and the acknowledgement committing
    will send again, with the identical ``idempotency_key``; whether that becomes one effect or
    two in the outside world is the provider's to decide, not ours to claim.
    """

    __tablename__ = "outbox_messages"
    __table_args__ = (
        enum_check("state", OUTBOX_STATES, name="state"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint(_IN_FLIGHT_LEASE, name="in_flight_lease"),
        UniqueConstraint("idempotency_key", name="uq_outbox_messages_idempotency_key"),
        Index("ix_outbox_messages_state_next_attempt", "state", "next_attempt_at"),
        Index(
            "ix_outbox_messages_lease_expires_at",
            "lease_expires_at",
            postgresql_where=text("state = 'IN_FLIGHT'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """What the provider reported it did, when it had something to report.

    A reference says an effect was accepted; this says what the acceptance *was* -- for an
    order amendment, the version the order system is now at and the variant it put on the line.
    A recovery is later required to see that reflected in the mirror before it may complete, so
    the statement has to be durable rather than something the dispatcher remembers.
    """
    created_in_tx_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        Timestamp, nullable=False, server_default=func.now()
    )


class Conversation(Base):
    """One voice or console conversation. Phase gating lives in the engine, not in the session.

    Keeping the phase here rather than in a transport session is what lets a conversation end
    while the case it opened lives on for hours.
    """

    __tablename__ = "conversations"
    __table_args__ = (enum_check("phase", CONVERSATION_PHASES, name="phase"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    case_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    clarifications_asked: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
