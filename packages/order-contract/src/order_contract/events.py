"""What the order system says when one of its orders changes.

The order system is the system of record. PromisePatch keeps a mirror of it and learns about
every ordinary change from one of these events, so the envelope has to carry enough to update
that mirror deterministically -- and deliberately no more.

Three decisions shape it.

**A snapshot, not a diff.** ``order`` is the whole authoritative state of the order *after* the
change, and ``previous_version`` says what it was before. A consumer can therefore apply the
event without having applied every earlier one, and can tell at a glance whether it did: an
event whose ``previous_version`` is the mirror's current version is the next one in the line.

**One logical change, one ``event_id``.** The id belongs to the mutation, not to the delivery
attempt, so a webhook redelivered five times presents the identical id five times and the
receiver's own uniqueness constraint collapses them. Minting a fresh id per attempt would make
at-least-once transport indistinguishable from five real changes.

**Identities, never internals.** Lines name a catalogue item; nothing here exposes a row id, a
table or a database. The receiver owns the translation from a catalogue item to whatever it
calls the same thing, and an item it cannot translate is a data problem it must refuse rather
than guess at.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION: Final = 1
"""The version of every message in this package.

One number for the whole contract rather than one per message: the two travel together, a
receiver that can read one can read the other, and a mismatch is refused at the edge instead
of being discovered halfway through applying a change.
"""

EVENT_ORDER_UPDATED: Final = "order.updated"
EVENT_ORDER_CANCELLED: Final = "order.cancelled"

OrderEventType = Literal["order.updated", "order.cancelled"]
OrderStateName = Literal["ACCEPTED", "AMENDED", "CANCELLED", "FULFILLED"]


class Message(BaseModel):
    """Shared shape: immutable, and closed to fields nobody declared.

    ``extra="forbid"`` is the load-bearing half. A sender that adds a field a receiver does not
    understand is a change to the contract, and it should fail at the edge with a readable
    error rather than be silently dropped on the way to a decision about somebody's order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class ChannelRef(Message):
    """Where this customer would be asked for approval. Carried, never acted on here."""

    kind: str
    address: str


class CustomerRef(Message):
    external_id: str
    name: str
    approval_channel: ChannelRef


class OrderLineRef(Message):
    """One line of the order, as the order system holds it."""

    external_line_id: str
    external_item_id: str
    """The catalogue identity of what was ordered. The receiver maps it; it never invents it."""
    quantity: int = Field(gt=0)
    note: str = ""


class OrderSnapshot(Message):
    """The authoritative state of one order at one version."""

    external_id: str
    version: int = Field(gt=0)
    state: OrderStateName
    customer: CustomerRef
    due_at: datetime
    lines: tuple[OrderLineRef, ...]

    @model_validator(mode="after")
    def _check_lines(self) -> OrderSnapshot:
        if len({line.external_line_id for line in self.lines}) != len(self.lines):
            raise ValueError("duplicate external_line_id in one order")
        return self


class CommandRef(Message):
    """The amendment that caused this change, when one did.

    Present on an event the order system raised because PromisePatch asked it to, absent on one
    an operator made. It is what lets a receiver recognise the echo of its own amendment
    instead of reading it as an unrelated change somebody else made.
    """

    idempotency_key: str
    provider_ref: str


class OrderEvent(Message):
    """One committed change to one order, addressed to whoever mirrors it."""

    schema_version: int = SCHEMA_VERSION
    event_id: UUID
    type: OrderEventType
    occurred_at: datetime
    previous_version: int | None = None
    changed_line_ids: tuple[str, ...] = ()
    order: OrderSnapshot
    command: CommandRef | None = None

    @model_validator(mode="after")
    def _check_versions(self) -> OrderEvent:
        if self.previous_version is not None and self.previous_version >= self.order.version:
            raise ValueError("previous_version must be lower than the order's version")
        known = {line.external_line_id for line in self.order.lines}
        unknown = sorted(set(self.changed_line_ids) - known)
        if unknown:
            raise ValueError(f"changed_line_ids names lines the order does not have: {unknown}")
        return self


__all__ = [
    "EVENT_ORDER_CANCELLED",
    "EVENT_ORDER_UPDATED",
    "SCHEMA_VERSION",
    "ChannelRef",
    "CommandRef",
    "CustomerRef",
    "Message",
    "OrderEvent",
    "OrderEventType",
    "OrderLineRef",
    "OrderSnapshot",
    "OrderStateName",
]
