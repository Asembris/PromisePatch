"""Infrastructure of the durable engine: events, steps, timers, inbox, outbox, conversations.

These tables exist so that restart safety is a property of the database rather than of any
running process. Nothing in this slice writes them; the transitions that do arrive with the
case engine. The schema lands now so the audited-write boundary can be installed once, over
every governed table, instead of being retrofitted table by table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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


class DomainEvent(Base):
    """The append-only sequence spine.

    ``seq`` is the single global order every consumer checkpoints against, and the value the
    graph snapshot is stamped with so a reader can say exactly how current its view was.
    ``entity_refs`` names what changed, which is how a later slice recomputes only the tracks
    that were actually watching a touched entity. Like the audit ledger, it holds no foreign
    key into the domain: the record of what happened outlives the rows it happened to.
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
    than re-running it: a step that already committed cannot be enqueued a second time.
    """

    __tablename__ = "case_steps"
    __table_args__ = (
        enum_check("state", STEP_STATES, name="state"),
        UniqueConstraint("case_id", "step_key", name="uq_case_steps_case_step_key"),
        Index("ix_case_steps_state_next_attempt", "state", "next_attempt_at"),
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


class Timer(Base):
    """A deadline that survives a restart, because it is a row rather than a scheduled task."""

    __tablename__ = "timers"
    __table_args__ = (
        Index("ix_timers_due_unfired", "due_at", postgresql_where=text("fired_at IS NULL")),
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
    """

    __tablename__ = "outbox_messages"
    __table_args__ = (
        enum_check("state", OUTBOX_STATES, name="state"),
        UniqueConstraint("idempotency_key", name="uq_outbox_messages_idempotency_key"),
        Index("ix_outbox_messages_state_next_attempt", "state", "next_attempt_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    provider_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_in_tx_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


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
