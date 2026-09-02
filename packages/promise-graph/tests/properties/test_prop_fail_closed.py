"""P4 — fail closed: unknown or conflicting state can only make an outcome more cautious."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from promise_graph.availability import apply_exception_facts
from promise_graph.classification import analyze
from promise_graph.model import (
    SEVERITY_ORDER,
    Classification,
    ConstraintKind,
    CustomerConstraint,
    ReasonDetail,
    ResourceKind,
    RuleId,
)
from promise_graph.snapshot import GraphSnapshot
from tests.strategies import World, worlds

pytestmark = pytest.mark.property


def ingredients(snapshot: GraphSnapshot) -> list[str]:
    return sorted(
        resource_id
        for resource_id, resource in snapshot.resources.items()
        if resource.kind is ResourceKind.INGREDIENT
    )


def blind_on_hand(snapshot: GraphSnapshot, resource_id: str) -> GraphSnapshot:
    ledger = tuple(
        entry.model_copy(update={"delta": None}) if entry.resource_id == resource_id else entry
        for entry in snapshot.ledger
    )
    return snapshot.replace(ledger=ledger)


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_an_unknown_quantity_never_lowers_severity(world: World, pick: int) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    available = ingredients(settled)
    resource_id = available[pick % len(available)]

    before = analyze(settled, world.exception, world.now)
    after = analyze(blind_on_hand(settled, resource_id), world.exception, world.now)
    for promise_id, result in before.classifications.items():
        assert (
            SEVERITY_ORDER[after.classification_of(promise_id)]
            >= SEVERITY_ORDER[result.classification]
        )


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_a_promise_with_an_unknown_line_is_blocked(world: World, pick: int) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    available = ingredients(settled)
    blinded = blind_on_hand(settled, available[pick % len(available)])
    analysis = analyze(blinded, world.exception, world.now)
    for line_id in analysis.impact.unknown_line_ids:
        promise_id = blinded.promise_of_line(line_id)
        assert promise_id is not None
        result = analysis.classifications[promise_id]
        assert result.classification is Classification.BLOCKED
        assert result.rule_id is RuleId.R_UNKNOWN


@given(worlds())
def test_removing_a_constraint_snapshot_never_unblocks(world: World) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    stripped = settled.replace(constraints={})
    before = analyze(settled, world.exception, world.now)
    after = analyze(stripped, world.exception, world.now)
    for promise_id, result in before.classifications.items():
        assert (
            SEVERITY_ORDER[after.classification_of(promise_id)]
            >= SEVERITY_ORDER[result.classification]
        )
    if after.impact.equipment_origin:
        return  # constraints do not govern equipment reassignment
    for promise_id in after.impact.affected_promise_ids:
        assert after.classification_of(promise_id) is Classification.BLOCKED


@given(worlds())
def test_an_affected_promise_without_constraints_is_never_recoverable(world: World) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    analysis = analyze(settled, world.exception, world.now)
    for promise_id in analysis.impact.affected_promise_ids:
        order_id = settled.promises[promise_id].order_id
        if settled.constraints_for_order(order_id):
            continue
        if analysis.impact.equipment_origin:
            continue  # constraints do not govern equipment reassignment
        result = analysis.classifications[promise_id]
        assert result.classification is Classification.BLOCKED
        assert result.reason_detail is ReasonDetail.NO_CONSTRAINT_SNAPSHOT


@given(worlds())
def test_a_conflicting_constraint_pair_always_blocks(world: World) -> None:
    """A pre-approval that names an excluded resource is never resolved in our favour."""
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    analysis = analyze(settled, world.exception, world.now)
    if not analysis.impact.affected_promise_ids or analysis.impact.equipment_origin:
        return
    promise_id = sorted(analysis.impact.affected_promise_ids)[0]
    order_id = settled.promises[promise_id].order_id
    resource_id = ingredients(settled)[0]
    constraints = dict(settled.constraints)
    recorded_at = settled.promises[promise_id].due_at
    constraints["cn-conflict-pre"] = CustomerConstraint(
        id="cn-conflict-pre",
        order_id=order_id,
        kind=ConstraintKind.PREAPPROVED_ALTERNATIVE,
        resource_id=resource_id,
        substitute_resource_id=resource_id,
        recorded_by="jo",
        recorded_at=recorded_at,
    )
    constraints["cn-conflict-exc"] = CustomerConstraint(
        id="cn-conflict-exc",
        order_id=order_id,
        kind=ConstraintKind.EXCLUDE_RESOURCE,
        resource_id=resource_id,
        recorded_by="jo",
        recorded_at=recorded_at,
    )
    conflicted = analyze(settled.replace(constraints=constraints), world.exception, world.now)
    result = conflicted.classifications[promise_id]
    assert result.classification is Classification.BLOCKED
    assert result.rule_id is RuleId.R_CONFLICT
    # The generated order may already carry its own conflicting pair; ours must be cited too.
    assert {"cn-conflict-pre", "cn-conflict-exc"} <= set(result.cited_constraint_ids)


@given(worlds())
def test_no_affected_promise_is_ever_silently_unaffected(world: World) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    analysis = analyze(settled, world.exception, world.now)
    for promise_id in analysis.impact.affected_promise_ids:
        assert analysis.classification_of(promise_id) is not Classification.UNAFFECTED
