"""The order mirror, its constraint snapshots, and the promises derived from it.

The external order system is the system of record. These tables are a versioned mirror:
ordinary customer changes arrive as events and are applied here, and PromisePatch writes back
only as a governed recovery amendment. There is no order editor, and no endpoint will ever
create one.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from promise_graph.model import Classification, ConstraintKind, OrderState
from promisepatch.db.base import Base
from promisepatch.db.types import CHANNEL_KINDS, TRACK_STATES, Timestamp, enum_check, members


class Customer(Base):
    """Identity and the channel an approval must arrive on. Nothing else.

    Deliberately not a CRM record: there are no preferences and no customer-level constraints,
    because every consent rule is snapshotted onto the accepted order instead. That is what
    makes the order snapshot the single authority on what may be substituted.
    """

    __tablename__ = "customers"
    __table_args__ = (
        enum_check("approval_channel_kind", CHANNEL_KINDS, name="approval_channel_kind"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    approval_channel_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    approval_channel_address: Mapped[str] = mapped_column(Text, nullable=False)


class Order(Base):
    """A mirrored order. ``external_version`` is the order system's own monotonic counter."""

    __tablename__ = "orders"
    __table_args__ = (
        enum_check("state", members(OrderState), name="state"),
        CheckConstraint("external_version > 0", name="external_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    external_version: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), nullable=False)
    due_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    mirror_source_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)


class OrderLine(Base):
    """One item, pinned to exactly one recipe version.

    A recovery re-points this column at another version that a human already authored; it
    never edits the version it currently names.
    """

    __tablename__ = "order_lines"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    recipe_version_id: Mapped[str] = mapped_column(ForeignKey("recipe_versions.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    customization_note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")


class OrderLineMapping(Base):
    """External catalogue item to recipe version.

    PromisePatch owns this mapping; the order system is never asked to model ingredients. An
    unmapped item is a data problem for the owner to fix, never a guess.
    """

    __tablename__ = "order_line_mappings"

    external_item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    recipe_version_id: Mapped[str] = mapped_column(ForeignKey("recipe_versions.id"), nullable=False)


class OrderConstraint(Base):
    """A consent or safety rule snapshotted onto one accepted order.

    Provenance is mandatory, and the shape check refuses a malformed rule outright. Both are
    safety properties rather than tidiness: an unattributable constraint cannot justify a
    substitution to a customer, and a pre-approval missing its substitute resource would be a
    rule nobody can evaluate. The engine treats an order with no usable constraint snapshot as
    ``NO_SUBSTITUTION``, so a rule that fails to store fails closed rather than open.
    """

    __tablename__ = "order_constraints"
    __table_args__ = (
        enum_check("kind", members(ConstraintKind), name="kind"),
        CheckConstraint("btrim(recorded_by) <> ''", name="provenance_required"),
        CheckConstraint(
            "(kind = 'PREAPPROVED_ALTERNATIVE'"
            " AND resource_id IS NOT NULL AND substitute_resource_id IS NOT NULL)"
            " OR (kind = 'EXCLUDE_RESOURCE'"
            " AND resource_id IS NOT NULL AND substitute_resource_id IS NULL)"
            " OR (kind IN ('NO_SUBSTITUTION', 'ASK_BEFORE_VISIBLE_CHANGE')"
            " AND resource_id IS NULL AND substitute_resource_id IS NULL)",
            name="constraint_shape",
        ),
        Index("ix_order_constraints_order", "order_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(ForeignKey("resources.id"), nullable=True)
    substitute_resource_id: Mapped[str | None] = mapped_column(
        ForeignKey("resources.id"), nullable=True
    )
    recorded_by: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)


class Promise(Base):
    """The unit of impact: one per accepted order.

    The ``current_*`` columns are a read model maintained by case transitions, not an input to
    any decision. They stay null until a case touches the promise, which is the correct state
    for an order book with no open exception.
    """

    __tablename__ = "promises"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_promises_order_id"),
        enum_check(
            "current_classification", members(Classification), name="current_classification"
        ),
        enum_check("current_track_state", TRACK_STATES, name="current_track_state"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    due_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    current_classification: Mapped[str | None] = mapped_column(String(24), nullable=True)
    current_track_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    current_case_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    current_track_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
