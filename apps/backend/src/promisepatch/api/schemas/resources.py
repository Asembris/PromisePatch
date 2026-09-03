"""The Live Operations read model for resources.

The four ingredient quantities are the engine's own: they come from
``promise_graph.availability`` and are not recomputed here. This module's job is to say which
horizon they were asked about and to pass unknown through as unknown.

Two things are deliberately *not* here. There is no "shortfall" field with a floor of zero: a
negative ``available_by`` is a real number a baker needs to see, and clamping it would hide
the very condition that makes a promise BLOCKED. And there is no engine judgement about
whether a task can run on a piece of equipment -- :class:`EquipmentView` reports the recorded
outages and the status those rows imply, which is a fact, while what to *do* about it stays a
decision the engine makes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from promisepatch.api.schemas.quantity import OptionalQuantityOut

EquipmentStatus = Literal["IN_SERVICE", "OUT_OF_SERVICE"]


class LedgerPosition(BaseModel):
    """Where a resource's stock reading came from, and when.

    On-hand is the sum of an append-only ledger, which is what makes "stale inventory" a
    thing with a timestamp and a sequence number rather than a vague worry. This is that
    provenance: the last posting, and how many there are.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: int
    last_seq: int | None
    last_recorded_at: datetime | None
    last_source_kind: str | None
    last_source_id: str | None


class IngredientView(BaseModel):
    """One ingredient, with the four quantities the engine computes for the given horizon."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    unit: str
    aliases: tuple[str, ...]
    on_hand: OptionalQuantityOut
    expected: OptionalQuantityOut
    reserved: OptionalQuantityOut
    available_by: OptionalQuantityOut
    unknown: bool
    overdue_commitment_line_ids: tuple[str, ...]
    ledger: LedgerPosition


class OutageView(BaseModel):
    """A recorded period during which a piece of equipment is out of service.

    ``ends_at`` is nullable and means open-ended, which is the honest shape for "the deck oven
    is down and nobody has said until when".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    starts_at: datetime
    ends_at: datetime | None


class ScheduledTaskView(BaseModel):
    """A task currently scheduled on this equipment, so a display can see the contention."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    order_line_id: str
    state: str
    scheduled_start: datetime | None
    scheduled_end: datetime | None


class EquipmentView(BaseModel):
    """One piece of equipment: identity, recorded outages, and what is booked on it.

    ``status`` is read from the outage rows alone. It is not the engine's answer to "can this
    task run", which also weighs capacity, plan claims and alternatives, and which stays in
    ``promise_graph.options`` where it belongs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    aliases: tuple[str, ...]
    status: EquipmentStatus
    outages: tuple[OutageView, ...]
    scheduled_tasks: tuple[ScheduledTaskView, ...]
    alternative_equipment_ids: tuple[str, ...]


class ResourcesResponse(BaseModel):
    """Resource state at one explicit horizon.

    ``at`` is in the response because the four quantities mean nothing without it: "available"
    is always "available by some time", and a screen that showed the number without the
    horizon would be inviting the reader to guess which one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: int
    generated_at: datetime
    at: datetime
    ingredients: tuple[IngredientView, ...]
    equipment: tuple[EquipmentView, ...]
