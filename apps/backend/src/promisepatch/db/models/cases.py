"""Exceptions, attested physical facts, cases, tracks, options and the consent record.

Nothing in this slice writes these tables; the state machine that walks them arrives with the
case engine. What lands now is the shape and, more importantly, the constraints that make the
frozen invariants structural: one live track per promise, one decision per approval request,
and a consent decision that only the literal parser can produce.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from promise_graph.model import (
    ApprovalRequestState,
    Classification,
    ExceptionCategory,
    OptionKind,
    ParserKind,
    RuleId,
)
from promisepatch.db.base import Base
from promisepatch.db.types import (
    CASE_STATES,
    TERMINAL_TRACK_STATES,
    TRACK_STATES,
    Quantity,
    Timestamp,
    enum_check,
    members,
)

_LIVE_TRACK_PREDICATE = "state NOT IN ({})".format(
    ", ".join(f"'{state}'" for state in TERMINAL_TRACK_STATES)
)


class PhysicalException(Base):
    """The interpreted, worker-attested exception.

    ``raw_utterance`` is provenance only. No decision reads it, which is what makes "the system
    never branches on what was said" a structural fact rather than a coding convention.
    """

    __tablename__ = "exceptions"
    __table_args__ = (enum_check("category", members(ExceptionCategory), name="category"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    commitment_id: Mapped[str | None] = mapped_column(
        ForeignKey("supplier_commitments.id"), nullable=True
    )
    scope_line_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    resource_id: Mapped[str | None] = mapped_column(ForeignKey("resources.id"), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Quantity, nullable=True)
    outage_until: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    raw_utterance: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    reported_by: Mapped[str] = mapped_column(String(64), nullable=False)
    reported_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)


class ExceptionFact(Base):
    """One physical fact a worker attested, with what it changed.

    Physical facts answer "what is true in the kitchen" and are recorded under their own
    authority. Declining or retracting a recovery plan never reverses one; only a later
    correcting attestation does, and it is stored as its own row citing the one it supersedes.
    That is why this table is append-only rather than editable.
    """

    __tablename__ = "exception_facts"
    __table_args__ = (Index("ix_exception_facts_exception", "exception_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    exception_id: Mapped[UUID] = mapped_column(
        ForeignKey("exceptions.id", ondelete="CASCADE"), nullable=False
    )
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    posted_ledger_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    supersedes_fact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("exception_facts.id"), nullable=True
    )
    attested_by: Mapped[str] = mapped_column(String(64), nullable=False)
    attested_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)


class Case(Base):
    """The durable workflow instance for one exception."""

    __tablename__ = "cases"
    __table_args__ = (
        enum_check("state", CASE_STATES, name="state"),
        Index("ix_cases_state_updated", "state", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    exception_id: Mapped[UUID | None] = mapped_column(ForeignKey("exceptions.id"), nullable=True)
    opened_by: Mapped[str] = mapped_column(String(64), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    needs_owner_attention: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)


class Track(Base):
    """One promise's impact and recovery inside a case.

    ``ix_tracks_one_live_per_promise`` is the invariant that a promise is never being recovered
    by two cases at once: a second case reaching the same promise must link to the live track
    instead of opening a competing one. Expressing it as a partial unique index means the race
    is lost in the database, not in whichever process happened to check first.
    """

    __tablename__ = "tracks"
    __table_args__ = (
        enum_check("state", TRACK_STATES, name="state"),
        enum_check("classification", members(Classification), name="classification"),
        enum_check("rule_id", members(RuleId), name="rule_id"),
        Index(
            "ix_tracks_one_live_per_promise",
            "promise_id",
            unique=True,
            postgresql_where=text(_LIVE_TRACK_PREDICATE),
        ),
        Index("ix_tracks_case", "case_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
    )
    promise_id: Mapped[str] = mapped_column(ForeignKey("promises.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    classification: Mapped[str | None] = mapped_column(String(24), nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason_detail: Mapped[str | None] = mapped_column(String(48), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chosen_option_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    approval_request_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    linked_track_id: Mapped[UUID | None] = mapped_column(ForeignKey("tracks.id"), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    deadline_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class TrackPath(Base):
    """One traversed dependency path, kept as evidence.

    Stored with its quantification so the evidence screen can distinguish "reachable but
    covered" from "no path at all" — a distinction that is the difference between a promise
    the exception could have threatened and one it never touched.
    """

    __tablename__ = "track_paths"
    __table_args__ = (Index("ix_track_paths_track", "track_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    track_id: Mapped[UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    nodes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    role: Mapped[str | None] = mapped_column(String(24), nullable=True)
    quantification: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class TrackWatch(Base):
    """Which entities a track's outcome depends on, so only affected tracks are revalidated."""

    __tablename__ = "track_watch"
    __table_args__ = (Index("ix_track_watch_entity", "entity_type", "entity_id"),)

    track_id: Mapped[UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    entity_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(128), primary_key=True)


class RecoveryOption(Base):
    """A concrete, validated change.

    A substitution always names a recipe version that already exists — the foreign key makes
    that structural, so no runtime component can invent, derive or synthesize a version and
    then apply it to somebody's order.
    """

    __tablename__ = "recovery_options"
    __table_args__ = (
        enum_check("kind", members(OptionKind), name="kind"),
        enum_check("approval_rule", members(RuleId), name="approval_rule"),
        CheckConstraint(
            "required_quantity IS NULL OR required_quantity >= 0", name="quantity_non_negative"
        ),
        Index("ix_recovery_options_track", "track_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    track_id: Mapped[UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    order_line_id: Mapped[str | None] = mapped_column(ForeignKey("order_lines.id"), nullable=True)
    from_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("recipe_versions.id"), nullable=True
    )
    to_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("recipe_versions.id"), nullable=True
    )
    from_equipment_id: Mapped[str | None] = mapped_column(ForeignKey("resources.id"), nullable=True)
    to_equipment_id: Mapped[str | None] = mapped_column(ForeignKey("resources.id"), nullable=True)
    affected_resource_id: Mapped[str | None] = mapped_column(
        ForeignKey("resources.id"), nullable=True
    )
    substitute_resource_id: Mapped[str | None] = mapped_column(
        ForeignKey("resources.id"), nullable=True
    )
    required_quantity: Mapped[Decimal | None] = mapped_column(Quantity, nullable=True)
    visible_change: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    approval_rule: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cited_constraint_ids: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    policy_id: Mapped[str | None] = mapped_column(
        ForeignKey("substitution_policies.id"), nullable=True
    )
    task_start: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)


class ApprovalRequest(Base):
    """What was asked of a customer, and the state of the world it was asked against.

    The captured columns are the binding: an approval authorises this change to this order
    version under these constraints, and drift in any of them invalidates it before any write.
    """

    __tablename__ = "approval_requests"
    __table_args__ = (
        enum_check("state", members(ApprovalRequestState), name="state"),
        CheckConstraint("deadline > sent_at", name="deadline_after_send"),
        Index("ix_approval_requests_track", "track_id"),
        Index("ix_approval_requests_state_deadline", "state", "deadline"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    track_id: Mapped[UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False
    )
    promise_id: Mapped[str] = mapped_column(ForeignKey("promises.id"), nullable=False)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), nullable=False)
    order_line_id: Mapped[str] = mapped_column(ForeignKey("order_lines.id"), nullable=False)
    option_id: Mapped[UUID] = mapped_column(ForeignKey("recovery_options.id"), nullable=False)
    option_code: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_channel: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    deadline: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    captured_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_order_version: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_recipe_version_id: Mapped[str] = mapped_column(
        ForeignKey("recipe_versions.id"), nullable=False
    )
    captured_constraint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    decided: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    provider_ref: Mapped[str | None] = mapped_column(Text, nullable=True)


class InboundReply(Base):
    """A customer's raw reply, stored as data.

    ``apparent_intent`` is a model's non-authoritative reading and is deliberately kept in a
    separate column from any decision: it can trigger one confirmation prompt and nothing else.
    The text itself is never interpreted as an instruction.
    """

    __tablename__ = "inbound_replies"
    __table_args__ = (
        UniqueConstraint("provider_message_id", name="uq_inbound_replies_provider_message_id"),
        Index("ix_inbound_replies_request", "request_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    request_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=True
    )
    provider_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    sender_identity: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    apparent_intent: Mapped[str | None] = mapped_column(String(24), nullable=True)
    received_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)


class ApprovalDecision(Base):
    """The authoritative answer to one approval request.

    Two constraints carry the entire consent model. ``ck_approval_decisions_parser`` permits
    only ``LITERAL``: a decision produced by any reading of free text is not a row this
    database will accept, so "the model never produces a consent decision" is enforced rather
    than reviewed. ``uq_approval_decisions_request_id`` allows exactly one decision per
    request, which is what makes a redelivered callback a no-op instead of a second consent.
    """

    __tablename__ = "approval_decisions"
    __table_args__ = (
        CheckConstraint(f"parser = '{ParserKind.LITERAL.value}'", name="parser"),
        CheckConstraint("decision IN ('APPROVE', 'DECLINE')", name="decision"),
        UniqueConstraint("request_id", name="uq_approval_decisions_request_id"),
        UniqueConstraint("provider_message_id", name="uq_approval_decisions_provider_message_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    parser: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_identity: Mapped[str] = mapped_column(Text, nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    received_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
