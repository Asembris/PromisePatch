"""P1 — selectivity: what cannot be reached is never touched."""

from __future__ import annotations

import pytest
from hypothesis import given

from promise_graph.availability import apply_exception_facts
from promise_graph.classification import analyze
from promise_graph.model import Classification, ReasonDetail, RuleId
from tests.strategies import World, worlds

pytestmark = pytest.mark.property


@given(worlds())
def test_unreachable_promises_are_unaffected(world: World) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    analysis = analyze(settled, world.exception, world.now)
    for promise_id in analysis.impact.unreachable_promise_ids:
        result = analysis.classifications[promise_id]
        assert result.classification is Classification.UNAFFECTED
        assert result.rule_id is RuleId.R_UNREACH
        assert result.reason_detail is ReasonDetail.NOT_REACHABLE


@given(worlds())
def test_unreachable_promises_carry_no_options_no_paths_no_citations(world: World) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    analysis = analyze(settled, world.exception, world.now)
    for promise_id in analysis.impact.unreachable_promise_ids:
        option_set = analysis.option_sets[promise_id]
        assert option_set.valid == ()
        assert option_set.rejected == ()
        assert promise_id not in analysis.impact.paths_by_promise
        assert analysis.classifications[promise_id].cited_constraint_ids == ()
        assert analysis.classifications[promise_id].chosen_option_id is None


@given(worlds())
def test_reached_and_unreached_partition_every_promise(world: World) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    impact = analyze(settled, world.exception, world.now).impact
    assert impact.reached_promise_ids | impact.unreachable_promise_ids == frozenset(
        settled.promises
    )
    assert impact.reached_promise_ids & impact.unreachable_promise_ids == frozenset()
    assert impact.affected_promise_ids | impact.covered_promise_ids == impact.reached_promise_ids
    assert impact.affected_promise_ids & impact.covered_promise_ids == frozenset()


@given(worlds())
def test_only_affected_promises_can_be_non_unaffected(world: World) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    analysis = analyze(settled, world.exception, world.now)
    for promise_id, result in analysis.classifications.items():
        if result.classification is not Classification.UNAFFECTED:
            assert promise_id in analysis.impact.affected_promise_ids
