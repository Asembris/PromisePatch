"""Staff identity, web sessions and the operator's fixture bookkeeping."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from promisepatch.db.base import Base
from promisepatch.db.types import WORKER_ROLES, Timestamp, enum_check


class Worker(Base):
    """A member of bakery staff. Two rows exist: the baker and the owner.

    Every governed write is attributed to one of these ids, which is what makes the audit
    ledger answer "who authorised this" rather than "something did this".
    """

    __tablename__ = "workers"
    __table_args__ = (enum_check("role", WORKER_ROLES, name="role"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)


class Session(Base):
    """A logged-in browser session. Server-side so that logout genuinely revokes."""

    __tablename__ = "sessions"
    __table_args__ = (
        Index(
            "ix_sessions_worker_active",
            "worker_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("workers.id", ondelete="CASCADE"), nullable=False
    )
    csrf_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)


class FixtureState(Base):
    """One row describing the demo fixture currently loaded.

    ``anchor_at`` is the instant every fixture offset was measured from. Keeping it means the
    stored graph can be rebuilt in memory at the identical anchor and compared, which is how a
    later slice proves the database round trip changed no decision.
    """

    __tablename__ = "fixture_state"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    anchor_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    fixture_name: Mapped[str] = mapped_column(Text, nullable=False)
    fixture_digest: Mapped[str] = mapped_column(String(64), nullable=False)
