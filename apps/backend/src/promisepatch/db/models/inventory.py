"""The append-only physical inventory ledger.

On-hand quantity is the sum of this ledger, never a mutable counter. That gives every stock
figure a sequence number and a time, which is what lets the evidence screen say *when* a
number was last true instead of asserting it timelessly.

``uq_inventory_ledger_source`` is the exactly-once guarantee for physical postings, and it is
the reason a replayed settlement cannot inflate supply: receiving the same commitment line
twice is a unique-violation, not a second delivery. One physical quantity has one home — a
settled line's outcome lives in on-hand and contributes nothing further to expected supply.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from promise_graph.model import LedgerSourceKind
from promisepatch.db.base import Base
from promisepatch.db.types import Quantity, Timestamp, enum_check, members


class InventoryLedgerEntry(Base):
    """One physical posting. ``delta`` is signed, and null means the quantity is unknown."""

    __tablename__ = "inventory_ledger"
    __table_args__ = (
        enum_check("source_kind", members(LedgerSourceKind), name="source_kind"),
        UniqueConstraint("source_kind", "source_id", name="uq_inventory_ledger_source"),
        Index("ix_inventory_ledger_resource_seq", "resource_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), nullable=False)
    delta: Mapped[Decimal | None] = mapped_column(Quantity, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
