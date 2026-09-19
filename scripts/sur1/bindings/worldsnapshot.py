"""The canonical world snapshot: what a scenario's starting state is, before any arm acts.

A comparative benchmark rests on a claim nobody can check by reading prose: *all three arms
started from the same world*. This module makes that claim checkable. It renders one scenario's
prepared world as a canonical payload and hashes it, so "the same world" is an equality between
two hex strings rather than a reading of two setups.

**Arm-independent by construction.** Nothing here takes an arm, a token, a budget or a model.
The snapshot is taken from the program's projected world -- the pure fold of its steps over a
clean ``hollow_oak()`` -- and there is no parameter by which two arms could be given two
snapshots.

**Anchor-independent by construction.** Every instant is rendered as a whole number of seconds
from the fixture anchor rather than as a timestamp. The fixture is relative-time by design and a
run prepared at nine in the morning is the same world as one prepared at noon; a digest that
disagreed with that would be measuring the clock. Two independent setups of the same scenario at
different anchors therefore produce the same digest, which is the property the freeze needs.

**What it holds and why that list.** The order book with its external versions and pinned items;
the recipe, resource and promise relationships an arm has to traverse; the recorded customer
constraints and the channel each customer is reachable on; attested stock and the ledger that
attested it; every production task's state; the stipulated customer replies that are due but not
yet delivered; and the scenario's own external changes. That is the observable starting state --
everything an arm could read before it acts, and nothing about what it should do.

**What it deliberately does not hold.** No expected disposition, no authorised version, no effect
ceiling and no scorer vocabulary. It is built from a
:class:`~scripts.sur1.bindings.programs.ScenarioProgram`, which was itself built through
:class:`~scripts.sur1.bindings.programs.StipulatedFacts`, so there is no object in this call
chain on which a correct answer exists to be read.

**Nothing here has been taken against a live stack.** The snapshot is computed from the pure
fixture; reading one back out of a prepared database is a separate question and is not done here.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from promise_graph.examples import hollow_oak
from promise_graph.snapshot import GraphSnapshot
from scripts.sur1.bindings.programs import ScenarioProgram, sha

SNAPSHOT_SCHEMA_VERSION: Final = "1"
"""Bumped whenever the shape below changes, which moves every digest and the program-set hash.

That is the intended consequence: a snapshot schema that changed quietly would let two runs
compare digests that were never computed the same way.
"""


def offset(moment: datetime | None, *, anchor: datetime) -> int | None:
    """One instant as whole seconds from the anchor. ``None`` stays ``None``.

    Whole seconds rather than a float, because a float's repr is a property of the arithmetic
    that produced it and two equal instants must render to the same characters.
    """
    if moment is None:
        return None
    return round((moment - anchor).total_seconds())


def quantity(value: Decimal | None) -> str | None:
    """A quantity as its own decimal text, or ``None`` for an unknown one.

    Never a float. ``2.0`` and ``2.00`` are the same quantity and must render the same, so the
    value is normalised before it is written down.
    """
    if value is None:
        return None
    normalised = value.normalize()
    return format(normalised, "f")


def snapshot_of(
    program: ScenarioProgram, *, anchor: datetime = hollow_oak.ANCHOR
) -> dict[str, Any]:
    """The canonical starting state of one prepared scenario."""
    world = program.world(anchor=anchor)
    return {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "scenario": program.scenario_id,
        "fixture": "promise_graph.examples.hollow_oak",
        "orders": _orders(world, anchor=anchor),
        "customers": _customers(world),
        "constraints": _constraints(world),
        "promises": _promises(world, anchor=anchor),
        "tasks": _tasks(world, anchor=anchor),
        "recipe_versions": _versions(world),
        "substitution_policies": _policies(world),
        "commitments": _commitments(world, anchor=anchor),
        "reservations": _reservations(world),
        "on_hand": _on_hand(world),
        "ledger": _ledger(world, anchor=anchor),
        "external_changes": _external_changes(program),
        "replies_due": _replies_due(program),
        "armed_events": [event.describes() for event in program.armed],
    }


def digest_of(program: ScenarioProgram, *, anchor: datetime = hollow_oak.ANCHOR) -> str:
    """The identity of one scenario's starting world."""
    return sha(snapshot_of(program, anchor=anchor))


def digests(programs: Mapping[str, ScenarioProgram]) -> dict[str, str]:
    """Every scenario's starting-world digest, by identifier."""
    return {scenario_id: digest_of(program) for scenario_id, program in sorted(programs.items())}


# ------------------------------------------------------------------------------- the parts


def _orders(world: GraphSnapshot, *, anchor: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": order.id,
            "external_id": order.external_id,
            "external_version": order.external_version,
            "state": str(order.state),
            "customer": order.customer_id,
            "due_at_offset_s": offset(order.due_at, anchor=anchor),
            "lines": [
                {
                    "id": line.id,
                    "recipe_version": line.recipe_version_id,
                    "quantity": line.quantity,
                }
                for line in sorted(order.lines, key=lambda line: line.id)
            ],
        }
        for order in sorted(world.orders.values(), key=lambda order: order.id)
    ]


def _customers(world: GraphSnapshot) -> list[dict[str, Any]]:
    return [
        {"id": customer.id, "approval_channel": customer.approval_channel}
        for customer in sorted(world.customers.values(), key=lambda customer: customer.id)
    ]


def _constraints(world: GraphSnapshot) -> list[dict[str, Any]]:
    return [
        {
            "id": constraint.id,
            "order": constraint.order_id,
            "kind": str(constraint.kind),
            "resource": constraint.resource_id,
            "substitute_resource": constraint.substitute_resource_id,
        }
        for constraint in sorted(world.constraints.values(), key=lambda entry: entry.id)
    ]


def _promises(world: GraphSnapshot, *, anchor: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": promise.id,
            "order": promise.order_id,
            "due_at_offset_s": offset(promise.due_at, anchor=anchor),
        }
        for promise in sorted(world.promises.values(), key=lambda promise: promise.id)
    ]


def _tasks(world: GraphSnapshot, *, anchor: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": task.id,
            "order_line": task.order_line_id,
            "state": str(task.state),
            "held_by": task.held_by_case_id,
            "scheduled_start_offset_s": offset(task.scheduled_start, anchor=anchor),
            "scheduled_end_offset_s": offset(task.scheduled_end, anchor=anchor),
            "equipment": task.equipment_id,
        }
        for task in sorted(world.tasks.values(), key=lambda task: task.id)
    ]


def _versions(world: GraphSnapshot) -> list[dict[str, Any]]:
    return [
        {
            "id": version.id,
            "recipe": version.recipe_id,
            "version_no": version.version_no,
            "equipment": sorted(version.equipment_ids),
            "lines": [
                {
                    "resource": line.resource_id,
                    "role": str(line.role),
                    "qty_per_unit": quantity(line.qty_per_unit),
                }
                for line in sorted(version.lines, key=lambda line: (line.resource_id, line.role))
            ],
        }
        for version in sorted(world.versions.values(), key=lambda version: version.id)
    ]


def _policies(world: GraphSnapshot) -> list[dict[str, Any]]:
    return [
        {
            "id": policy.id,
            "affected_resource": policy.affected_resource_id,
            "role": str(policy.role),
            "source_version": policy.source_version_id,
            "candidate_version": policy.candidate_version_id,
            "substitute_resource": policy.substitute_resource_id,
            "visible_change": policy.visible_change,
        }
        for policy in sorted(world.policies.values(), key=lambda policy: policy.id)
    ]


def _commitments(world: GraphSnapshot, *, anchor: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": commitment.id,
            "supplier": commitment.supplier_id,
            "due_at_offset_s": offset(commitment.due_at, anchor=anchor),
            "lines": [
                {
                    "id": line.id,
                    "resource": line.resource_id,
                    "quantity": quantity(line.quantity),
                    "received_state": str(line.received_state),
                    "received_qty": quantity(line.received_qty),
                    "settled_at_offset_s": offset(line.settled_at, anchor=anchor),
                    "attested_by": line.attested_by,
                }
                for line in sorted(commitment.lines, key=lambda line: line.id)
            ],
        }
        for commitment in sorted(world.commitments.values(), key=lambda entry: entry.id)
    ]


def _reservations(world: GraphSnapshot) -> list[dict[str, Any]]:
    return [
        {
            "id": reservation.id,
            "order_line": reservation.order_line_id,
            "resource": reservation.resource_id,
            "quantity": quantity(reservation.quantity),
            "source_recipe_version": reservation.source_recipe_version_id,
        }
        for reservation in sorted(world.reservations.values(), key=lambda entry: entry.id)
    ]


def _on_hand(world: GraphSnapshot) -> dict[str, str | None]:
    """Attested on-hand quantity per resource, summed from the ledger and never from a total.

    A resource with any unknown posting is reported unknown rather than as the sum of the rest:
    an unknown quantity is not a zero and is not a smaller number, and the engine fails closed
    on it for the same reason.
    """
    totals: dict[str, str | None] = {}
    for resource_id, entries in sorted(world.ledger_by_resource.items()):
        if any(entry.delta is None for entry in entries):
            totals[resource_id] = None
            continue
        totals[resource_id] = quantity(
            sum((entry.delta or Decimal("0") for entry in entries), Decimal("0"))
        )
    return totals


def _ledger(world: GraphSnapshot, *, anchor: datetime) -> list[dict[str, Any]]:
    """Every posting in sequence order, because the order is what the sum is made of."""
    return [
        {
            "seq": entry.seq,
            "resource": entry.resource_id,
            "delta": quantity(entry.delta),
            "source_kind": str(entry.source_kind),
            "source_id": entry.source_id,
            "recorded_at_offset_s": offset(entry.recorded_at, anchor=anchor),
        }
        for entry in sorted(world.ledger, key=lambda entry: entry.seq)
    ]


def _external_changes(program: ScenarioProgram) -> list[dict[str, Any]]:
    """The scenario's own pre-incident edits, named as the external events they are.

    Read off the program's steps rather than diffed out of the world: an edit that produced no
    visible difference would still be an event the order system committed, and rule ``B6`` turns
    on who committed it rather than on what it changed.
    """
    from scripts.sur1.bindings.programs import ExternalRepin

    return [
        {
            "order": step.order_id,
            "line": step.line_id,
            "to_version": step.to_version_id,
            "committed_by": "the external order system",
        }
        for step in program.steps
        if isinstance(step, ExternalRepin)
    ]


def _replies_due(program: ScenarioProgram) -> list[dict[str, Any]]:
    """The stipulated replies that exist before any arm acts and have not been delivered.

    They are *due*, not present. A reply written into the starting state would be a customer
    answering a question nobody asked, so what the snapshot records is that the world owes this
    message once an ask reaches that channel, and how many times the provider will deliver it.
    """
    from scripts.sur1.bindings.programs import ScriptedReply

    return [
        {
            "order": event.order,
            "channel": event.channel,
            "text": event.text,
            "deliveries": event.deliveries,
            "delivered": False,
        }
        for event in program.armed
        if isinstance(event, ScriptedReply)
    ]


__all__ = [
    "SNAPSHOT_SCHEMA_VERSION",
    "digest_of",
    "digests",
    "offset",
    "quantity",
    "snapshot_of",
]
