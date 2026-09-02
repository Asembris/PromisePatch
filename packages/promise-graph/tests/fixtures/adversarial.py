"""Engineering fixtures: the cases that are meant to break the engine, not to demo it.

Each builder is a pure transformation of the Hollow Oak snapshot that isolates exactly one
rule, so a failure names the rule rather than the fixture.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from promise_graph.examples.hollow_oak import (
    AUTHOR,
    BLUEBERRIES,
    CONSTRAINT_B_ASK,
    ORDER_A,
    ORDER_B,
    PROMISE_A,
    PROMISE_B,
    RASPBERRIES,
    STRAWBERRIES,
    VP_TODAY,
    VP_TOMORROW,
)
from promise_graph.model import (
    ConstraintKind,
    CustomerConstraint,
    InventoryLedgerEntry,
    LedgerSourceKind,
    OrderId,
)
from promise_graph.snapshot import GraphSnapshot

CONSTRAINT_A_EXCLUDE_STRAWBERRIES = "cn-a-exclude-strawberries"
CONSTRAINT_B_EXCLUDE_STRAWBERRIES = "cn-b-exclude-strawberries"
CONSTRAINT_B_EXCLUDE_BLUEBERRIES = "cn-b-exclude-blueberries"


def with_allocation_contention(snapshot: GraphSnapshot) -> GraphSnapshot:
    """Drop today's strawberry delivery and leave 2.5 kg on hand: A wins, B runs out.

    A needs 2.4 kg and starts first, so it takes its share; B needs 2.2 kg and only 0.1 kg
    remains. Which one wins is decided by task start, never by identity.
    """
    commitment = snapshot.commitments[VP_TODAY]
    trimmed = commitment.model_copy(
        update={
            "lines": tuple(line for line in commitment.lines if line.resource_id != STRAWBERRIES)
        }
    )
    commitments = dict(snapshot.commitments)
    commitments[VP_TODAY] = trimmed
    return _set_on_hand(snapshot.replace(commitments=commitments), STRAWBERRIES, Decimal("2.5"))


def with_swapped_task_starts(snapshot: GraphSnapshot) -> GraphSnapshot:
    """Swap A's and B's production windows. Allocation priority must follow, not the ids."""
    tasks = dict(snapshot.tasks)
    task_a = tasks["task-ol-a"]
    task_b = tasks["task-ol-b"]
    tasks["task-ol-a"] = task_a.model_copy(
        update={
            "scheduled_start": task_b.scheduled_start,
            "scheduled_end": task_b.scheduled_end,
        }
    )
    tasks["task-ol-b"] = task_b.model_copy(
        update={
            "scheduled_start": task_a.scheduled_start,
            "scheduled_end": task_a.scheduled_end,
        }
    )
    return snapshot.replace(tasks=tasks)


def with_conflicting_constraints(snapshot: GraphSnapshot) -> GraphSnapshot:
    """A pre-approval that names an excluded resource. Humans fix the data; we fail closed."""
    return _add_constraint(
        snapshot,
        CustomerConstraint(
            id=CONSTRAINT_A_EXCLUDE_STRAWBERRIES,
            order_id=ORDER_A,
            kind=ConstraintKind.EXCLUDE_RESOURCE,
            resource_id=STRAWBERRIES,
            recorded_by=AUTHOR,
            recorded_at=snapshot.promises[PROMISE_A].due_at,
        ),
    )


def with_excluded_substitute(snapshot: GraphSnapshot) -> GraphSnapshot:
    """B excludes the substitute outright, with no pre-approval to conflict with."""
    return _add_constraint(
        snapshot,
        CustomerConstraint(
            id=CONSTRAINT_B_EXCLUDE_STRAWBERRIES,
            order_id=ORDER_B,
            kind=ConstraintKind.EXCLUDE_RESOURCE,
            resource_id=STRAWBERRIES,
            recorded_by=AUTHOR,
            recorded_at=snapshot.promises[PROMISE_B].due_at,
        ),
    )


def with_visible_change_and_no_ask(snapshot: GraphSnapshot) -> GraphSnapshot:
    """B keeps a constraint snapshot but drops ASK: a visible change is still not pre-approved."""
    constraints = {
        constraint_id: constraint
        for constraint_id, constraint in snapshot.constraints.items()
        if constraint_id != CONSTRAINT_B_ASK
    }
    constraints[CONSTRAINT_B_EXCLUDE_BLUEBERRIES] = CustomerConstraint(
        id=CONSTRAINT_B_EXCLUDE_BLUEBERRIES,
        order_id=ORDER_B,
        kind=ConstraintKind.EXCLUDE_RESOURCE,
        resource_id=BLUEBERRIES,
        recorded_by=AUTHOR,
        recorded_at=snapshot.promises[PROMISE_B].due_at,
    )
    return snapshot.replace(constraints=constraints)


def without_constraints(snapshot: GraphSnapshot, order_id: OrderId) -> GraphSnapshot:
    """Remove an order's constraint snapshot: closed-world unknown, which fails closed."""
    constraints = {
        constraint_id: constraint
        for constraint_id, constraint in snapshot.constraints.items()
        if constraint.order_id != order_id
    }
    return snapshot.replace(constraints=constraints)


def with_unknown_raspberry_quantity(snapshot: GraphSnapshot) -> GraphSnapshot:
    """An unknown expected quantity makes availability incomputable for everyone downstream."""
    commitment = snapshot.commitments[VP_TOMORROW]
    lines = tuple(
        line.model_copy(update={"quantity": None}) if line.resource_id == RASPBERRIES else line
        for line in commitment.lines
    )
    commitments = dict(snapshot.commitments)
    commitments[VP_TOMORROW] = commitment.model_copy(update={"lines": lines})
    return snapshot.replace(commitments=commitments)


def with_unknown_task_start(snapshot: GraphSnapshot, task_id: str) -> GraphSnapshot:
    """An unknown production start makes allocation order undefined, so nothing is assumed."""
    tasks = dict(snapshot.tasks)
    tasks[task_id] = tasks[task_id].model_copy(update={"scheduled_start": None})
    return snapshot.replace(tasks=tasks)


def with_ample_raspberries(snapshot: GraphSnapshot) -> GraphSnapshot:
    """Enough raspberries on hand that the shortfall is covered: reachable, but unaffected."""
    return _set_on_hand(snapshot, RASPBERRIES, Decimal("50.0"))


def _add_constraint(snapshot: GraphSnapshot, constraint: CustomerConstraint) -> GraphSnapshot:
    constraints = dict(snapshot.constraints)
    constraints[constraint.id] = constraint
    return snapshot.replace(constraints=constraints)


def _set_on_hand(snapshot: GraphSnapshot, resource_id: str, quantity: Decimal) -> GraphSnapshot:
    """Replace a resource's fixture ledger rows with a single posting of ``quantity``."""
    kept = tuple(entry for entry in snapshot.ledger if entry.resource_id != resource_id)
    recorded_at: datetime = snapshot.promises[PROMISE_A].due_at - timedelta(days=1)
    entry = InventoryLedgerEntry(
        seq=max((item.seq for item in snapshot.ledger), default=0) + 1,
        resource_id=resource_id,
        delta=quantity,
        source_kind=LedgerSourceKind.FIXTURE,
        source_id=f"fixture:{resource_id}:adversarial",
        recorded_at=recorded_at,
    )
    return snapshot.replace(ledger=(*kept, entry))
