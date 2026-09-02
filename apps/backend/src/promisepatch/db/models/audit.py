"""The authoritative business audit ledger.

Traces and logs may be sampled, rotated or lost; this table may not. Every consequential write
names the actor who caused it, the authority that permitted it, the rule that justified it and
the before/after values, so "why did the system change this customer's order" is answerable
from stored facts rather than from someone's memory of a conversation.

Two structural decisions matter more than they look:

* **``case_id`` and ``track_id`` carry no foreign key.** The ledger must outlive the rows it
  describes. A cascade from a deleted case — or a fixture reset that empties the domain
  tables — must never be able to reach the record of what was done and by whom.
* **``xid`` records the transaction that wrote the row**, so the audited-write trigger in the
  next slice can require that a governed write and its audit row share a transaction, rather
  than merely that some audit row exists somewhere.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Index, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from promisepatch.db.base import Base
from promisepatch.db.types import ACTOR_KINDS, AUTHORITIES, XID8, Timestamp, enum_check


class AuditEvent(Base):
    """One append-only entry. Updates and deletes are refused by trigger and by privilege."""

    __tablename__ = "audit_events"
    __table_args__ = (
        enum_check("actor_kind", ACTOR_KINDS, name="actor_kind"),
        enum_check("authority", AUTHORITIES, name="authority"),
        Index("ix_audit_events_case_seq", "case_id", "seq"),
        Index("ix_audit_events_xid", "xid"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, unique=True)
    xid: Mapped[str] = mapped_column(
        XID8(), nullable=False, server_default=func.pg_current_xact_id()
    )
    case_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    track_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authority: Mapped[str] = mapped_column(String(24), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    correlation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        Timestamp, nullable=False, server_default=func.now()
    )
