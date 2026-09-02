"""Scheduled work, the stock it claims, and equipment outages."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from promise_graph.model import TaskState
from promisepatch.db.base import Base
from promisepatch.db.types import Quantity, Timestamp, enum_check, members


class ProductionTask(Base):
    """The work that fulfils one order line.

    ``order_line_id`` is unique because the engine indexes tasks by line one-to-one; a second
    task on the same line would be silently dropped when that index is built, so the database
    refuses it. ``scheduled_start`` is nullable on purpose — an unknown start is a real state
    that the engine must see and fail closed on, not an error to reject at write time.
    """

    __tablename__ = "production_tasks"
    __table_args__ = (
        enum_check("state", members(TaskState), name="state"),
        UniqueConstraint("order_line_id", name="uq_production_tasks_order_line_id"),
        CheckConstraint(
            "scheduled_end IS NULL OR scheduled_start IS NULL OR scheduled_end >= scheduled_start",
            name="schedule_ordered",
        ),
        Index("ix_production_tasks_equipment_start", "equipment_id", "scheduled_start"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_line_id: Mapped[str] = mapped_column(
        ForeignKey("order_lines.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    scheduled_start: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    equipment_id: Mapped[str | None] = mapped_column(ForeignKey("resources.id"), nullable=True)
    held_by_case_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class Reservation(Base):
    """One order line's claim on one resource, derived from its pinned version.

    Stored rather than recomputed on read: the identity of a reservation is part of the
    fingerprint a waiting approval is bound to, so it has to be a fact with a lifetime.
    """

    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("quantity IS NULL OR quantity >= 0", name="quantity_non_negative"),
        UniqueConstraint("order_line_id", "resource_id", name="uq_reservations_line_resource"),
        Index("ix_reservations_resource", "resource_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    order_line_id: Mapped[str] = mapped_column(
        ForeignKey("order_lines.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Quantity, nullable=True)
    source_recipe_version_id: Mapped[str] = mapped_column(
        ForeignKey("recipe_versions.id"), nullable=False
    )


class EquipmentOutage(Base):
    """A window in which a piece of equipment is unavailable. Open-ended while unresolved."""

    __tablename__ = "equipment_outages"
    __table_args__ = (
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="window_ordered"),
        Index("ix_equipment_outages_equipment", "equipment_id", "starts_at"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    equipment_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
