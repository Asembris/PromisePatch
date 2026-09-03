"""Persisted state in, the Live Operations promise list out.

This module composes; it does not decide. Every field it emits is either a stored value or a
value the engine already computed, and the one piece of arrangement it performs -- the order
of the list -- is stated explicitly rather than left to whatever the database returned.

**Ordering is ``(due_at, external_id)``.** Due time is what a baker reads the screen for.
The external order id breaks ties, because two promises genuinely can fall due at the same
minute and a list that reordered itself between two identical requests would make every
screenshot, test and demo take unreproducible. Sorting on the *external* id rather than the
internal one keeps the order stable against a re-mirror that changes internal ids.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promise_graph.model import CustomerConstraint, ProductionTask
from promise_graph.snapshot import GraphSnapshot
from promisepatch.api.schemas.promises import (
    ConstraintView,
    CustomerView,
    OrderLineView,
    ProductionTaskView,
    PromisesResponse,
    PromiseView,
    RecipeVersionView,
    ReservationView,
)
from promisepatch.db import models


async def track_pointers(session: AsyncSession) -> dict[str, dict[str, str | None]]:
    """The persisted case pointers for every promise, keyed by promise id.

    Read from the ``promises`` read model rather than derived: these columns are maintained by
    case transitions, and recomputing them here would mean this endpoint had an opinion about
    a case's state that the case engine had not committed to.

    Read in the same repeatable-read transaction as the snapshot, so the classification shown
    beside a promise belongs to the same instant as the graph it is shown with.
    """
    table = models.Promise.__table__
    result = await session.execute(
        select(
            table.c.id,
            table.c.current_classification,
            table.c.current_track_state,
            table.c.current_case_id,
            table.c.current_track_id,
        )
    )
    return {
        row["id"]: {
            "classification": row["current_classification"],
            "track_state": row["current_track_state"],
            "case_id": None if row["current_case_id"] is None else str(row["current_case_id"]),
            "track_id": None if row["current_track_id"] is None else str(row["current_track_id"]),
        }
        for row in result.mappings()
    }


def build(
    snapshot: GraphSnapshot,
    *,
    pointers: dict[str, dict[str, str | None]],
    generated_at: datetime,
) -> PromisesResponse:
    """Assemble the promise list from a loaded snapshot and the persisted case pointers."""
    views = [
        _promise(snapshot, promise_id=promise_id, pointers=pointers)
        for promise_id in snapshot.promises
    ]
    views.sort(key=lambda view: (view.due_at, view.external_id))
    return PromisesResponse(
        as_of=snapshot.as_of,
        generated_at=generated_at,
        promises=tuple(views),
    )


def _promise(
    snapshot: GraphSnapshot,
    *,
    promise_id: str,
    pointers: dict[str, dict[str, str | None]],
) -> PromiseView:
    promise = snapshot.promises[promise_id]
    order = snapshot.orders[promise.order_id]
    customer = snapshot.customers[order.customer_id]
    pointer = pointers.get(promise_id, {})
    return PromiseView(
        id=promise.id,
        due_at=promise.due_at,
        order_id=order.id,
        external_id=order.external_id,
        external_version=order.external_version,
        order_state=str(order.state),
        order_due_at=order.due_at,
        customer=CustomerView(id=customer.id, name=customer.name),
        constraints=tuple(
            _constraint(constraint) for constraint in snapshot.constraints_for_order(order.id)
        ),
        lines=tuple(_line(snapshot, line.id) for line in order.lines),
        classification=pointer.get("classification"),
        track_state=pointer.get("track_state"),
        case_id=pointer.get("case_id"),
        track_id=pointer.get("track_id"),
    )


def _constraint(constraint: CustomerConstraint) -> ConstraintView:
    return ConstraintView(
        id=constraint.id,
        kind=str(constraint.kind),
        resource_id=constraint.resource_id,
        substitute_resource_id=constraint.substitute_resource_id,
        recorded_by=constraint.recorded_by,
        recorded_at=constraint.recorded_at,
    )


def _line(snapshot: GraphSnapshot, order_line_id: str) -> OrderLineView:
    line = snapshot.order_lines[order_line_id]
    version = snapshot.versions[line.recipe_version_id]
    recipe = snapshot.recipes[version.recipe_id]
    task = snapshot.task_of_line(order_line_id)
    reservation_ids = snapshot.reservations_by_order_line.get(order_line_id, ())
    return OrderLineView(
        id=line.id,
        quantity=line.quantity,
        customization_note=line.customization_note,
        recipe_version=RecipeVersionView(
            id=version.id,
            recipe_id=recipe.id,
            recipe_name=recipe.name,
            version_no=version.version_no,
            authored_by=version.authored_by,
            authored_at=version.authored_at,
        ),
        task=None if task is None else _task(snapshot, task),
        reservations=tuple(
            _reservation(snapshot, reservation_id) for reservation_id in reservation_ids
        ),
    )


def _task(snapshot: GraphSnapshot, task: ProductionTask) -> ProductionTaskView:
    equipment_id = task.equipment_id
    equipment = snapshot.resources.get(equipment_id) if equipment_id else None
    return ProductionTaskView(
        id=task.id,
        state=str(task.state),
        scheduled_start=task.scheduled_start,
        scheduled_end=task.scheduled_end,
        equipment_id=equipment_id,
        equipment_name=None if equipment is None else equipment.name,
        held_by_case_id=task.held_by_case_id,
    )


def _reservation(snapshot: GraphSnapshot, reservation_id: str) -> ReservationView:
    reservation = snapshot.reservations[reservation_id]
    resource = snapshot.resources[reservation.resource_id]
    return ReservationView(
        id=reservation.id,
        resource_id=reservation.resource_id,
        resource_name=resource.name,
        quantity=reservation.quantity,
        source_recipe_version_id=reservation.source_recipe_version_id,
    )
