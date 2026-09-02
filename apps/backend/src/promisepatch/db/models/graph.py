"""PromisePatch-owned graph nodes: resources, supply, recipes and substitution policy.

Edges are foreign keys with role columns, not rows in a generic edge table. The traversal
reads exactly the same rows the state transitions write, so the graph cannot drift from the
state it describes.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from promise_graph.model import ReceivedState, RecipeLineRole, ResourceKind
from promisepatch.db.base import Base
from promisepatch.db.types import Quantity, Timestamp, enum_check, members


class Resource(Base):
    """An ingredient or a piece of equipment. One table, so both failure kinds traverse alike."""

    __tablename__ = "resources"
    __table_args__ = (enum_check("kind", members(ResourceKind), name="kind"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unit")


class ResourceAlias(Base):
    """Spoken names for a resource. Interpretation vocabulary, never a decision input."""

    __tablename__ = "resource_aliases"

    resource_id: Mapped[str] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    alias: Mapped[str] = mapped_column(Text, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class SupplierCommitment(Base):
    __tablename__ = "supplier_commitments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    due_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)


class CommitmentLine(Base):
    """One expected resource line, and the settlement that closed it.

    A line is open (``EXPECTED``) or settled. The checks below are the database's copy of the
    engine's own validator, so an impossible settlement cannot be stored even by a writer that
    bypasses the engine: a ``SHORT`` line must say how much actually arrived, every other state
    must not, and a settlement time exists exactly when the line is settled.
    """

    __tablename__ = "commitment_lines"
    __table_args__ = (
        enum_check("received_state", members(ReceivedState), name="received_state"),
        CheckConstraint("quantity IS NULL OR quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("received_qty IS NULL OR received_qty >= 0", name="received_non_negative"),
        CheckConstraint(
            "(received_state = 'SHORT' AND received_qty IS NOT NULL)"
            " OR (received_state <> 'SHORT' AND received_qty IS NULL)",
            name="settlement_shape",
        ),
        CheckConstraint(
            "(received_state = 'EXPECTED' AND settled_at IS NULL)"
            " OR (received_state <> 'EXPECTED' AND settled_at IS NOT NULL)",
            name="settled_at_matches_state",
        ),
        Index("ix_commitment_lines_resource_state", "resource_id", "received_state"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    commitment_id: Mapped[str] = mapped_column(
        ForeignKey("supplier_commitments.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Quantity, nullable=True)
    received_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="EXPECTED"
    )
    received_qty: Mapped[Decimal | None] = mapped_column(Quantity, nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(Timestamp, nullable=True)
    attested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class RecipeVersion(Base):
    """A human-authored bill of resources. Insert-only; the trigger arrives with the audit slice.

    ``authored_by`` may not be blank: a version with no author cannot be shown as evidence for
    a substitution, and the recovery model rests on every candidate having been written by a
    person before any exception occurred.
    """

    __tablename__ = "recipe_versions"
    __table_args__ = (
        UniqueConstraint("recipe_id", "version_no", name="uq_recipe_versions_recipe_version"),
        CheckConstraint("version_no > 0", name="version_no_positive"),
        CheckConstraint("btrim(authored_by) <> ''", name="authorship_required"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    recipe_id: Mapped[str] = mapped_column(ForeignKey("recipes.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    authored_by: Mapped[str] = mapped_column(String(64), nullable=False)
    authored_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)


class RecipeVersionLine(Base):
    """One resource a version needs, and the role it plays in the finished product.

    The role distinguishes a filling swap nobody sees from a change to the visible decoration,
    which is the difference between recovering automatically and having to ask the customer.
    """

    __tablename__ = "recipe_version_lines"
    __table_args__ = (
        enum_check("role", members(RecipeLineRole), name="role"),
        CheckConstraint("qty_per_unit IS NULL OR qty_per_unit >= 0", name="qty_non_negative"),
    )

    version_id: Mapped[str] = mapped_column(
        ForeignKey("recipe_versions.id", ondelete="CASCADE"), primary_key=True
    )
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(24), primary_key=True)
    qty_per_unit: Mapped[Decimal | None] = mapped_column(Quantity, nullable=True)


class RecipeVersionEquipment(Base):
    __tablename__ = "recipe_version_equipment"

    version_id: Mapped[str] = mapped_column(
        ForeignKey("recipe_versions.id", ondelete="CASCADE"), primary_key=True
    )
    equipment_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), primary_key=True)


class SubstitutionPolicy(Base):
    """Bakery-authored map from a failure to a variant version that already exists.

    The unique key mirrors the index the engine builds in memory. Two policy rows for one
    ``(resource, role, source version)`` would silently drop one when that map is built, so
    the database refuses to hold the ambiguity at all.
    """

    __tablename__ = "substitution_policies"
    __table_args__ = (
        enum_check("role", members(RecipeLineRole), name="role"),
        UniqueConstraint(
            "affected_resource_id",
            "role",
            "source_version_id",
            name="uq_substitution_policies_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    affected_resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    source_version_id: Mapped[str] = mapped_column(ForeignKey("recipe_versions.id"), nullable=False)
    candidate_version_id: Mapped[str] = mapped_column(
        ForeignKey("recipe_versions.id"), nullable=False
    )
    substitute_resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), nullable=False)
    visible_change: Mapped[bool] = mapped_column(Boolean, nullable=False)


class EquipmentAlternative(Base):
    __tablename__ = "equipment_alternatives"
    __table_args__ = (
        CheckConstraint("equipment_id <> alternative_equipment_id", name="distinct_equipment"),
        UniqueConstraint(
            "equipment_id", "alternative_equipment_id", name="uq_equipment_alternatives_pair"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    equipment_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), nullable=False)
    alternative_equipment_id: Mapped[str] = mapped_column(
        ForeignKey("resources.id"), nullable=False
    )
