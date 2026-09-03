"""A loaded snapshot in, the Live Operations resource panel out.

The numbers are the engine's. :func:`promise_graph.availability.available_by` returns on-hand,
expected, reserved, available-by and the overdue commitment lines in one call, and this module
passes all five through unchanged -- including ``None``. That last part is the whole reason
this is a thin composition rather than a query: an absent quantity is *unknown*, the engine
fails closed on unknown, and a read model that helpfully turned it into ``0`` would present a
promise as satisfiable that the engine refuses to call satisfiable.

Negative values pass through too. ``available_by`` below zero is a shortfall, it is exactly
what makes a promise BLOCKED, and clamping it to zero on the way to a screen would hide the
condition the screen exists to show.

The default horizon is the last due time in the order book. "Available" is always "available
by some moment", and the moment that matters to a bakery at seven in the morning is the end of
the day's promises, not the current instant -- at which nothing has been delivered yet and
every expected figure would read zero. The chosen horizon is returned in the response, and a
caller may name its own.
"""

from __future__ import annotations

from datetime import datetime

from promise_graph.availability import available_by
from promise_graph.model import ResourceKind
from promise_graph.snapshot import GraphSnapshot
from promisepatch.api.schemas.resources import (
    EquipmentStatus,
    EquipmentView,
    IngredientView,
    LedgerPosition,
    OutageView,
    ResourcesResponse,
    ScheduledTaskView,
)


def default_horizon(snapshot: GraphSnapshot, *, now: datetime) -> datetime:
    """The end of the current order book, or ``now`` if there is no order book.

    Derived from the promises that exist rather than picked as a duration: a fixed "next 24
    hours" would be a policy nobody authored, and would quietly change what every number on
    the screen means whenever the bakery's rhythm changed.
    """
    due_times = [promise.due_at for promise in snapshot.promises.values()]
    if not due_times:
        return now
    return max(max(due_times), now)


def build(
    snapshot: GraphSnapshot, *, at: datetime, now: datetime, generated_at: datetime
) -> ResourcesResponse:
    """Assemble the resource panel for one explicit horizon."""
    ingredients = [
        _ingredient(snapshot, resource_id=resource_id, at=at, now=now)
        for resource_id, resource in snapshot.resources.items()
        if resource.kind is ResourceKind.INGREDIENT
    ]
    equipment = [
        _equipment(snapshot, resource_id=resource_id, at=now)
        for resource_id, resource in snapshot.resources.items()
        if resource.kind is ResourceKind.EQUIPMENT
    ]
    ingredients.sort(key=lambda view: view.id)
    equipment.sort(key=lambda view: view.id)
    return ResourcesResponse(
        as_of=snapshot.as_of,
        generated_at=generated_at,
        at=at,
        ingredients=tuple(ingredients),
        equipment=tuple(equipment),
    )


def _ingredient(
    snapshot: GraphSnapshot, *, resource_id: str, at: datetime, now: datetime
) -> IngredientView:
    resource = snapshot.resources[resource_id]
    view = available_by(snapshot, resource_id, at, now)
    return IngredientView(
        id=resource.id,
        name=resource.name,
        unit=resource.unit,
        aliases=tuple(resource.aliases),
        on_hand=view.on_hand,
        expected=view.expected,
        reserved=view.reserved,
        available_by=view.available_by,
        unknown=view.unknown,
        overdue_commitment_line_ids=tuple(view.overdue_line_ids),
        ledger=_ledger(snapshot, resource_id),
    )


def _ledger(snapshot: GraphSnapshot, resource_id: str) -> LedgerPosition:
    """Where this resource's stock reading came from.

    The ledger is append-only and read in sequence order, so the last entry is the most recent
    posting. An ingredient with no postings is reported as zero entries and no last posting,
    which is not the same claim as "none in stock" and is not dressed up as one.
    """
    entries = snapshot.ledger_by_resource.get(resource_id, ())
    if not entries:
        return LedgerPosition(
            entries=0,
            last_seq=None,
            last_recorded_at=None,
            last_source_kind=None,
            last_source_id=None,
        )
    last = max(entries, key=lambda entry: entry.seq)
    return LedgerPosition(
        entries=len(entries),
        last_seq=last.seq,
        last_recorded_at=last.recorded_at,
        last_source_kind=str(last.source_kind),
        last_source_id=last.source_id,
    )


def _status(snapshot: GraphSnapshot, resource_id: str, at: datetime) -> EquipmentStatus:
    """Whether a recorded outage covers ``at``.

    The interval is half-open, ``[starts_at, ends_at)``, and an absent ``ends_at`` is
    open-ended -- the same convention ``promise_graph.options`` applies when it rejects an
    equipment option that overlaps an outage. This is a reading of the outage rows, not the
    engine's answer to whether a task can run: that also weighs capacity, other bookings and
    alternatives, and it stays in the engine.
    """
    for outage in snapshot.outages_by_equipment.get(resource_id, ()):
        covers = outage.starts_at <= at and (outage.ends_at is None or at < outage.ends_at)
        if covers:
            return "OUT_OF_SERVICE"
    return "IN_SERVICE"


def _equipment(snapshot: GraphSnapshot, *, resource_id: str, at: datetime) -> EquipmentView:
    resource = snapshot.resources[resource_id]
    outages = snapshot.outages_by_equipment.get(resource_id, ())
    task_ids = snapshot.tasks_by_equipment.get(resource_id, ())
    return EquipmentView(
        id=resource.id,
        name=resource.name,
        aliases=tuple(resource.aliases),
        status=_status(snapshot, resource_id, at),
        outages=tuple(
            OutageView(id=outage.id, starts_at=outage.starts_at, ends_at=outage.ends_at)
            for outage in sorted(outages, key=lambda item: (item.starts_at, item.id))
        ),
        scheduled_tasks=tuple(
            _scheduled(snapshot, task_id)
            for task_id in sorted(
                task_ids, key=lambda item: (snapshot.tasks[item].scheduled_start or at, item)
            )
        ),
        alternative_equipment_ids=tuple(snapshot.alternatives_by_equipment.get(resource_id, ())),
    )


def _scheduled(snapshot: GraphSnapshot, task_id: str) -> ScheduledTaskView:
    task = snapshot.tasks[task_id]
    return ScheduledTaskView(
        id=task.id,
        order_line_id=task.order_line_id,
        state=str(task.state),
        scheduled_start=task.scheduled_start,
        scheduled_end=task.scheduled_end,
    )
