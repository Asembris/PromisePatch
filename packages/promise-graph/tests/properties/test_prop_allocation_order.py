"""P3 — determinism: results depend on the schedule, never on input order."""

from __future__ import annotations

import pytest
from hypothesis import given

from promise_graph.availability import allocate, apply_exception_facts
from promise_graph.classification import analyze
from promise_graph.model import ResourceKind
from tests.strategies import World, rebuild, worlds

pytestmark = pytest.mark.property


@given(worlds())
def test_input_order_does_not_change_the_snapshot(world: World) -> None:
    assert rebuild(world.snapshot, reverse=True) == rebuild(world.snapshot)


@given(worlds())
def test_input_order_does_not_change_settlement(world: World) -> None:
    forward = apply_exception_facts(world.snapshot, world.exception, world.now)
    reverse = apply_exception_facts(
        rebuild(world.snapshot, reverse=True), world.exception, world.now
    )
    assert forward.postings == reverse.postings
    assert forward.settlements == reverse.settlements


@given(worlds())
def test_input_order_does_not_change_allocation(world: World) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    reversed_snapshot = rebuild(settled, reverse=True)
    for resource_id, resource in sorted(settled.resources.items()):
        if resource.kind is not ResourceKind.INGREDIENT:
            continue
        forward = allocate(settled, resource_id, world.now)
        reverse = allocate(reversed_snapshot, resource_id, world.now)
        assert forward == reverse


@given(worlds())
def test_input_order_does_not_change_the_analysis(world: World) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    forward = analyze(settled, world.exception, world.now)
    reverse = analyze(rebuild(settled, reverse=True), world.exception, world.now)
    assert forward.classifications == reverse.classifications
    assert forward.option_sets == reverse.option_sets
    assert forward.impact.paths_by_promise == reverse.impact.paths_by_promise


@given(worlds())
def test_allocation_follows_the_schedule(world: World) -> None:
    """Claims are served strictly by (task start, order external id, claim id)."""
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    for resource_id, resource in sorted(settled.resources.items()):
        if resource.kind is not ResourceKind.INGREDIENT:
            continue
        result = allocate(settled, resource_id, world.now)
        if result.unknown:
            continue
        starts = [allocation.start for allocation in result.allocations]
        assert starts == sorted(starts)


@given(worlds())
def test_repeated_analysis_is_identical(world: World) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    first = analyze(settled, world.exception, world.now)
    second = analyze(settled, world.exception, world.now)
    assert first.classifications == second.classifications
    assert first.option_sets == second.option_sets
