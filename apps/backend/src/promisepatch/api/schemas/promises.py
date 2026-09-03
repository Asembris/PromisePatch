"""The Live Operations read model for customer promises.

Every model here is a deliberate projection rather than a serialised row, and two of the
choices are load-bearing:

* :class:`CustomerView` carries a name and an id and **not** the approval channel. The
  channel is a real person's Telegram chat id; it is what the consent protocol authenticates a
  reply against, and it has no business on an operations screen. ``extra="forbid"`` means a
  column added to ``customers`` later cannot start being served by accident.
* Quantities are strings (see ``api.schemas.quantity``) and ``None`` means unknown.

The classification and track pointers are read from the persisted ``promises`` read model, not
recomputed here. They are ``None`` for a promise no case has ever touched, which is the
correct state for an order book with no open exception -- not "UNAFFECTED", which is a
decision the engine makes about a specific exception.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from promisepatch.api.schemas.quantity import OptionalQuantityOut


class CustomerView(BaseModel):
    """Display identity only. The approval channel is deliberately absent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str


class ConstraintView(BaseModel):
    """A consent or safety rule snapshotted onto the order, with its provenance.

    ``recorded_by`` and ``recorded_at`` are part of the contract rather than metadata: a
    constraint nobody can attribute cannot justify a substitution to a customer, so the screen
    that shows the rule shows who recorded it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: str
    resource_id: str | None
    substitute_resource_id: str | None
    recorded_by: str
    recorded_at: datetime


class ReservationView(BaseModel):
    """A claim on a resource, derived from an order line and the version it is pinned to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    resource_id: str
    resource_name: str
    quantity: OptionalQuantityOut
    source_recipe_version_id: str


class ProductionTaskView(BaseModel):
    """The task that will make one order line, and the equipment it is scheduled on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    state: str
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    equipment_id: str | None
    equipment_name: str | None
    held_by_case_id: str | None


class RecipeVersionView(BaseModel):
    """The pinned version, and the recipe it is a version of.

    ``version_no`` and the authorship are shown because the point of pinning is that a human
    authored this exact version: a recovery re-points a line at another authored version and
    never derives one, and the screen should make the difference visible.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    recipe_id: str
    recipe_name: str
    version_no: int
    authored_by: str
    authored_at: datetime


class OrderLineView(BaseModel):
    """One item on the order: what it is, how many, how it is being made, what it holds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    quantity: int
    customization_note: str
    recipe_version: RecipeVersionView
    task: ProductionTaskView | None
    reservations: tuple[ReservationView, ...]


class PromiseView(BaseModel):
    """One customer promise, with everything Live Operations shows about it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    due_at: datetime
    order_id: str
    external_id: str
    external_version: int
    order_state: str
    order_due_at: datetime
    customer: CustomerView
    constraints: tuple[ConstraintView, ...]
    lines: tuple[OrderLineView, ...]
    classification: str | None
    track_state: str | None
    case_id: str | None
    track_id: str | None


class PromisesResponse(BaseModel):
    """The order book, in a deterministic order, stamped with how current it is.

    ``as_of`` is the highest ``domain_events`` sequence the read transaction could see. It is
    the honest answer to "how current is this", and the value a later slice will compare a
    plan's fingerprint against.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: int
    generated_at: datetime
    promises: tuple[PromiseView, ...]
