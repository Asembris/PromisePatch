"""P2 — monotonicity: adding usable supply never makes an outcome worse.

Stated precisely, because the naive global form is **false** and knowing why matters:

Giving an earlier track its recovery legitimately consumes the substitute. If extra supply is
just enough to let the highest-priority track validate, that track now commits a claim it did
not commit before, and a lower-priority track can lose the substitute it would otherwise have
had. That is the frozen allocation-priority rule of spec invariant 11.4.5 working correctly,
not a monotonicity violation, so the property is asserted where it genuinely holds:

* **allocation** — no claim's take ever decreases, and satisfied never flips to unsatisfied;
* **impact** — the affected set only shrinks, so no promise is newly threatened;
* **classification** — the promise that was highest-priority-affected never gets worse, since
  nothing can outrank it for the substitute.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from promise_graph.availability import allocate, apply_exception_facts
from promise_graph.classification import analyze
from promise_graph.model import SEVERITY_ORDER, Classification, ResourceKind
from promise_graph.snapshot import GraphSnapshot
from tests.strategies import World, add_on_hand, worlds

pytestmark = pytest.mark.property

EXTRA = Decimal("25.0")


def ingredients(world: World) -> list[str]:
    return sorted(
        resource_id
        for resource_id, resource in world.snapshot.resources.items()
        if resource.kind is ResourceKind.INGREDIENT
    )


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_added_supply_never_reduces_an_allocation(world: World, pick: int) -> None:
    available = ingredients(world)
    resource_id = available[pick % len(available)]
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    before = allocate(settled, resource_id, world.now)
    after = allocate(add_on_hand(settled, resource_id, EXTRA), resource_id, world.now)
    if before.unknown or after.unknown:
        return
    by_claim = {allocation.claim_id: allocation for allocation in before.allocations}
    for allocation in after.allocations:
        earlier = by_claim[allocation.claim_id]
        assert allocation.take >= earlier.take
        assert allocation.available_before_start >= earlier.available_before_start
        assert allocation.satisfied or not earlier.satisfied


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_added_supply_only_shrinks_the_affected_set(world: World, pick: int) -> None:
    available = ingredients(world)
    resource_id = available[pick % len(available)]
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    richer = add_on_hand(settled, resource_id, EXTRA)

    before = analyze(settled, world.exception, world.now).impact
    after = analyze(richer, world.exception, world.now).impact

    assert after.reached_promise_ids == before.reached_promise_ids
    assert after.affected_promise_ids <= before.affected_promise_ids
    assert after.unsatisfied_line_ids <= before.unsatisfied_line_ids


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_the_highest_priority_track_never_gets_worse(world: World, pick: int) -> None:
    available = ingredients(world)
    resource_id = available[pick % len(available)]
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    richer = add_on_hand(settled, resource_id, EXTRA)

    before = analyze(settled, world.exception, world.now)
    if not before.impact.affected_promise_ids:
        return
    first = _highest_priority(settled, before.impact.affected_promise_ids)
    after = analyze(richer, world.exception, world.now)

    assert (
        SEVERITY_ORDER[after.classification_of(first)]
        <= SEVERITY_ORDER[before.classification_of(first)]
    )


@given(worlds(), st.integers(min_value=0, max_value=3))
def test_unaffected_promises_stay_unaffected_when_supply_grows(world: World, pick: int) -> None:
    available = ingredients(world)
    resource_id = available[pick % len(available)]
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    richer = add_on_hand(settled, resource_id, EXTRA)

    before = analyze(settled, world.exception, world.now)
    after = analyze(richer, world.exception, world.now)
    for promise_id, result in before.classifications.items():
        if result.classification is Classification.UNAFFECTED:
            assert after.classification_of(promise_id) is Classification.UNAFFECTED


def _highest_priority(snapshot: GraphSnapshot, promise_ids: frozenset[str]) -> str:
    """The affected promise the allocator serves first: earliest task start wins."""
    keyed: list[tuple[str, str, str]] = []
    for promise_id in promise_ids:
        order = snapshot.orders[snapshot.promises[promise_id].order_id]
        starts = [
            task.scheduled_start.isoformat()
            for line in order.lines
            if (task := snapshot.task_of_line(line.id)) is not None
            and task.scheduled_start is not None
        ]
        keyed.append((min(starts) if starts else "", order.external_id, promise_id))
    return sorted(keyed)[0][2]
