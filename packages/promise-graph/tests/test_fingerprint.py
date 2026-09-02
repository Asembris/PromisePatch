"""Fingerprint scope, canonical JSON determinism, and per-field sensitivity."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from promise_graph.examples import hollow_oak as ho
from promise_graph.fingerprint import (
    TrackScope,
    canonical_json,
    constraint_hash,
    diff,
    fingerprint,
    fingerprint_input,
    scope_for,
)
from promise_graph.model import OrderState, TaskState
from promise_graph.propagation import propagate
from promise_graph.snapshot import GraphSnapshot
from tests.fixtures import settle, settle_and_analyze

Mutation = Callable[[GraphSnapshot], GraphSnapshot]


def scoped(
    snapshot: GraphSnapshot, now: datetime, promise_id: str = ho.PROMISE_B
) -> tuple[GraphSnapshot, TrackScope]:
    exception = ho.raspberry_only(now)
    settled = settle(snapshot, exception, now)
    analysis = settle_and_analyze(snapshot, exception, now)
    scope = scope_for(settled, analysis.impact, analysis.option_sets[promise_id], promise_id)
    return settled, scope


# --------------------------------------------------------------------------- canonical json


def test_canonical_json_is_stable_and_sorted() -> None:
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_canonical_json_normalises_decimal_scale() -> None:
    assert canonical_json(Decimal("2.0")) == canonical_json(Decimal("2.00"))
    assert canonical_json(Decimal("2.400")) == '"2.4"'
    assert canonical_json(Decimal("0.000")) == '"0"'


def test_canonical_json_renders_enums_and_timestamps(anchor: datetime) -> None:
    assert canonical_json(TaskState.SCHEDULED) == '"SCHEDULED"'
    assert canonical_json(anchor) == f'"{anchor.isoformat()}"'


def test_canonical_json_handles_nesting() -> None:
    assert canonical_json([{"x": (1, 2)}]) == '[{"x":[1,2]}]'


# --------------------------------------------------------------------------- scope


def test_scope_covers_the_order_its_lines_tasks_and_relevant_resources(
    anchor: datetime,
) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    settled, scope = scoped(snapshot, anchor)
    assert scope.order_id == ho.ORDER_B
    assert scope.order_line_ids == (ho.LINE_B,)
    assert scope.task_ids == ("task-ol-b",)
    assert ho.RASPBERRIES in scope.resource_ids
    assert ho.STRAWBERRIES in scope.resource_ids
    assert ho.DARK_CHOCOLATE not in scope.resource_ids
    assert settled.as_of >= 0


def test_scope_of_an_equipment_track_includes_the_alternative(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.deck_oven_down(anchor)
    settled = settle(snapshot, exception, anchor)
    analysis = settle_and_analyze(snapshot, exception, anchor)
    scope = scope_for(settled, analysis.impact, analysis.option_sets[ho.PROMISE_A], ho.PROMISE_A)
    assert ho.CONVECTION_OVEN in scope.resource_ids


# --------------------------------------------------------------------------- stability


def test_the_same_state_yields_the_same_hash(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    settled, scope = scoped(snapshot, anchor)
    assert fingerprint(settled, scope).hash == fingerprint(settled, scope).hash


def test_decimal_scale_does_not_move_the_hash(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    settled, scope = scoped(snapshot, anchor)
    before = fingerprint(settled, scope).hash
    reservations = dict(settled.reservations)
    key = f"{ho.LINE_B}:{ho.RASPBERRIES}"
    original = reservations[key].quantity
    assert original is not None
    reservations[key] = reservations[key].model_copy(
        update={"quantity": Decimal(str(original) + "00")}
    )
    assert fingerprint(settled.replace(reservations=reservations), scope).hash == before


def test_constraint_hash_changes_with_provenance(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    before = constraint_hash(snapshot, ho.ORDER_B)
    constraints = dict(snapshot.constraints)
    constraints[ho.CONSTRAINT_B_ASK] = constraints[ho.CONSTRAINT_B_ASK].model_copy(
        update={"recorded_by": "someone-else"}
    )
    assert constraint_hash(snapshot.replace(constraints=constraints), ho.ORDER_B) != before


def test_constraint_hash_of_an_order_without_constraints_is_stable(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    assert constraint_hash(snapshot, ho.ORDER_E) == constraint_hash(snapshot, ho.ORDER_F)


# --------------------------------------------------------------------------- sensitivity


def mutate_order_version(snapshot: GraphSnapshot) -> GraphSnapshot:
    orders = dict(snapshot.orders)
    orders[ho.ORDER_B] = orders[ho.ORDER_B].model_copy(update={"external_version": 99})
    return snapshot.replace(orders=orders)


def mutate_order_state(snapshot: GraphSnapshot) -> GraphSnapshot:
    orders = dict(snapshot.orders)
    orders[ho.ORDER_B] = orders[ho.ORDER_B].model_copy(update={"state": OrderState.AMENDED})
    return snapshot.replace(orders=orders)


def mutate_pinned_version(snapshot: GraphSnapshot) -> GraphSnapshot:
    return snapshot.repin_order_line(ho.LINE_B, ho.RRC_V3)


def mutate_constraints(snapshot: GraphSnapshot) -> GraphSnapshot:
    constraints = dict(snapshot.constraints)
    del constraints[ho.CONSTRAINT_B_ASK]
    return snapshot.replace(constraints=constraints)


def mutate_reservation(snapshot: GraphSnapshot) -> GraphSnapshot:
    reservations = dict(snapshot.reservations)
    key = f"{ho.LINE_B}:{ho.RASPBERRIES}"
    reservations[key] = reservations[key].model_copy(update={"quantity": Decimal("9.9")})
    return snapshot.replace(reservations=reservations)


def mutate_task_state(snapshot: GraphSnapshot) -> GraphSnapshot:
    tasks = dict(snapshot.tasks)
    tasks["task-ol-b"] = tasks["task-ol-b"].model_copy(update={"state": TaskState.HELD})
    return snapshot.replace(tasks=tasks)


def mutate_task_start(snapshot: GraphSnapshot) -> GraphSnapshot:
    tasks = dict(snapshot.tasks)
    start = tasks["task-ol-b"].scheduled_start
    assert start is not None
    tasks["task-ol-b"] = tasks["task-ol-b"].model_copy(
        update={"scheduled_start": start + timedelta(minutes=15)}
    )
    return snapshot.replace(tasks=tasks)


def mutate_task_equipment(snapshot: GraphSnapshot) -> GraphSnapshot:
    tasks = dict(snapshot.tasks)
    tasks["task-ol-b"] = tasks["task-ol-b"].model_copy(update={"equipment_id": ho.CONVECTION_OVEN})
    return snapshot.replace(tasks=tasks)


def mutate_task_hold(snapshot: GraphSnapshot) -> GraphSnapshot:
    tasks = dict(snapshot.tasks)
    tasks["task-ol-b"] = tasks["task-ol-b"].model_copy(update={"held_by_case_id": "case-1"})
    return snapshot.replace(tasks=tasks)


def mutate_scoped_ledger(snapshot: GraphSnapshot) -> GraphSnapshot:
    entry = snapshot.ledger[0].model_copy(
        update={
            "seq": snapshot.next_ledger_seq(),
            "resource_id": ho.STRAWBERRIES,
            "delta": Decimal("1.0"),
            "source_id": "fixture:extra-strawberries",
        }
    )
    return snapshot.append_ledger([entry])


def mutate_scoped_commitment_line(snapshot: GraphSnapshot) -> GraphSnapshot:
    commitment = snapshot.commitments[ho.VP_TOMORROW]
    lines = tuple(
        line.model_copy(update={"quantity": Decimal("99.0")})
        if line.resource_id == ho.RASPBERRIES
        else line
        for line in commitment.lines
    )
    commitments = dict(snapshot.commitments)
    commitments[ho.VP_TOMORROW] = commitment.model_copy(update={"lines": lines})
    return snapshot.replace(commitments=commitments)


RELEVANT: list[Mutation] = [
    mutate_order_version,
    mutate_order_state,
    mutate_pinned_version,
    mutate_constraints,
    mutate_reservation,
    mutate_task_state,
    mutate_task_start,
    mutate_task_equipment,
    mutate_task_hold,
    mutate_scoped_ledger,
    mutate_scoped_commitment_line,
]


@pytest.mark.parametrize("mutation", RELEVANT, ids=[f.__name__ for f in RELEVANT])
def test_relevant_changes_move_the_fingerprint(mutation: Mutation, anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    settled, scope = scoped(snapshot, anchor)
    before = fingerprint(settled, scope)
    after = fingerprint(mutation(settled), scope)
    assert after.hash != before.hash
    assert diff(before.input, after.input) != ()


def mutate_unrelated_order(snapshot: GraphSnapshot) -> GraphSnapshot:
    orders = dict(snapshot.orders)
    orders[ho.ORDER_F] = orders[ho.ORDER_F].model_copy(update={"external_version": 42})
    return snapshot.replace(orders=orders)


def mutate_unrelated_resource_ledger(snapshot: GraphSnapshot) -> GraphSnapshot:
    entry = snapshot.ledger[0].model_copy(
        update={
            "seq": snapshot.next_ledger_seq(),
            "resource_id": ho.DARK_CHOCOLATE,
            "delta": Decimal("5.0"),
            "source_id": "fixture:extra-chocolate",
        }
    )
    return snapshot.append_ledger([entry])


def mutate_customer_name(snapshot: GraphSnapshot) -> GraphSnapshot:
    customers = dict(snapshot.customers)
    customers["cus-tomas"] = customers["cus-tomas"].model_copy(update={"name": "T. Lindqvist"})
    return snapshot.replace(customers=customers)


def mutate_as_of(snapshot: GraphSnapshot) -> GraphSnapshot:
    return snapshot.replace(as_of=snapshot.as_of + 1000)


def mutate_unrelated_constraints(snapshot: GraphSnapshot) -> GraphSnapshot:
    constraints = dict(snapshot.constraints)
    del constraints[ho.CONSTRAINT_D_ASK]
    return snapshot.replace(constraints=constraints)


IRRELEVANT: list[Mutation] = [
    mutate_unrelated_order,
    mutate_unrelated_resource_ledger,
    mutate_customer_name,
    mutate_as_of,
    mutate_unrelated_constraints,
]


@pytest.mark.parametrize("mutation", IRRELEVANT, ids=[f.__name__ for f in IRRELEVANT])
def test_irrelevant_changes_leave_the_fingerprint_alone(
    mutation: Mutation, anchor: datetime
) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    settled, scope = scoped(snapshot, anchor)
    before = fingerprint(settled, scope)
    after = fingerprint(mutation(settled), scope)
    assert after.hash == before.hash
    assert diff(before.input, after.input) == ()


def test_diff_names_the_changed_field(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    settled, scope = scoped(snapshot, anchor)
    changes = diff(
        fingerprint_input(settled, scope), fingerprint_input(mutate_order_version(settled), scope)
    )
    assert [change.field for change in changes] == ["order_external_version"]
    assert changes[0].before == "1"
    assert changes[0].after == "99"


def test_fingerprint_input_reports_the_ledger_position(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    settled, scope = scoped(snapshot, anchor)
    payload = fingerprint_input(settled, scope)
    resources = {row[0]: row[1] for row in payload.resources}
    assert resources[ho.STRAWBERRIES] > 0
    assert payload.pinned_versions == ((ho.LINE_B, ho.RRC_V2),)


def test_propagation_is_not_needed_to_fingerprint_an_untouched_order(
    anchor: datetime,
) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    impact = propagate(settled, exception, anchor)
    analysis = settle_and_analyze(snapshot, exception, anchor)
    scope = scope_for(settled, impact, analysis.option_sets[ho.PROMISE_F], ho.PROMISE_F)
    assert scope.order_id == ho.ORDER_F
    assert fingerprint(settled, scope).hash
