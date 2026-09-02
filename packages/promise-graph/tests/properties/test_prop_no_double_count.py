"""P5 — a physical quantity has exactly one home (ADR-0014).

Under every settlement interleaving, a commitment line's quantity is counted at most once
across on-hand and expected supply. Received goods are never also still expected, and a SHORT
line's shortfall is lost supply rather than pending supply.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from promise_graph.availability import ZERO, apply_exception_facts, expected, on_hand
from promise_graph.model import ExceptionCategory, ReceivedState, ResourceKind
from promise_graph.snapshot import GraphSnapshot
from tests.strategies import World, worlds

pytestmark = pytest.mark.property

HORIZONS = [0, 1, 6, 24, 72]


def contribution_to_on_hand(snapshot: GraphSnapshot, line_id: str) -> Decimal:
    line = snapshot.commitment_lines[line_id]
    if line.received_state is ReceivedState.RECEIVED:
        return line.quantity or ZERO
    if line.received_state is ReceivedState.SHORT:
        return line.received_qty or ZERO
    return ZERO


def contribution_to_expected(
    snapshot: GraphSnapshot, line_id: str, at: object, now: object
) -> Decimal:
    line = snapshot.commitment_lines[line_id]
    if line.received_state is not ReceivedState.EXPECTED:
        return ZERO
    due_at = snapshot.commitments[line.commitment_id].due_at
    if due_at < now or due_at > at:  # type: ignore[operator]
        return ZERO
    return line.quantity or ZERO


@given(worlds(), st.sampled_from(HORIZONS))
def test_a_line_never_contributes_to_both_homes(world: World, hours: int) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    at = world.now + timedelta(hours=hours)
    for line_id in settled.commitment_lines:
        physical = contribution_to_on_hand(settled, line_id)
        pending = contribution_to_expected(settled, line_id, at, world.now)
        assert physical == ZERO or pending == ZERO


@given(worlds(), st.sampled_from(HORIZONS))
def test_no_line_is_counted_more_than_once(world: World, hours: int) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    at = world.now + timedelta(hours=hours)
    for line_id, line in settled.commitment_lines.items():
        total = contribution_to_on_hand(settled, line_id) + contribution_to_expected(
            settled, line_id, at, world.now
        )
        assert total <= (line.quantity or ZERO)


@given(worlds(), st.sampled_from(HORIZONS))
def test_settled_lines_contribute_zero_to_expected(world: World, hours: int) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    at = world.now + timedelta(hours=hours)
    for line_id, line in settled.commitment_lines.items():
        if line.is_settled:
            assert contribution_to_expected(settled, line_id, at, world.now) == ZERO


@given(worlds())
def test_on_hand_moves_by_exactly_the_postings(world: World) -> None:
    result = apply_exception_facts(world.snapshot, world.exception, world.now)
    for resource_id, resource in sorted(world.snapshot.resources.items()):
        if resource.kind is not ResourceKind.INGREDIENT:
            continue
        before = on_hand(world.snapshot, resource_id)
        after = on_hand(result.snapshot, resource_id)
        posted = sum(
            (posting.delta or ZERO)
            for posting in result.postings
            if posting.resource_id == resource_id
        )
        if before is None or after is None:
            continue
        assert after == before + posted


@given(worlds())
def test_re_settling_posts_nothing_further(world: World) -> None:
    """The value-level mirror of the database's exactly-once posting index."""
    first = apply_exception_facts(world.snapshot, world.exception, world.now)
    second = apply_exception_facts(first.snapshot, world.exception, world.now)
    assert second.postings == ()
    assert second.settlements == ()
    for resource_id in sorted(first.snapshot.resources):
        assert on_hand(second.snapshot, resource_id) == on_hand(first.snapshot, resource_id)


@given(worlds(), st.sampled_from(HORIZONS))
def test_supply_never_exceeds_what_was_ever_committed(world: World, hours: int) -> None:
    settled = apply_exception_facts(world.snapshot, world.exception, world.now).snapshot
    at = world.now + timedelta(hours=hours)
    for resource_id, resource in sorted(settled.resources.items()):
        if resource.kind is not ResourceKind.INGREDIENT:
            continue
        opening = on_hand(world.snapshot, resource_id)
        pending = expected(settled, resource_id, at, world.now)
        current = on_hand(settled, resource_id)
        if opening is None or pending is None or current is None:
            continue
        committed = sum(
            (settled.commitment_lines[line_id].quantity or ZERO)
            for line_id in settled.commitment_lines_by_resource.get(resource_id, ())
        )
        assert current + pending <= opening + committed


@given(worlds())
def test_a_not_received_line_posts_nothing(world: World) -> None:
    if world.exception.category is not ExceptionCategory.SUPPLY_NOT_RECEIVED:
        return
    result = apply_exception_facts(world.snapshot, world.exception, world.now)
    not_received = {
        settlement.commitment_line_id
        for settlement in result.settlements
        if settlement.to_state is ReceivedState.NOT_RECEIVED
    }
    posted_lines = {posting.source_id for posting in result.postings}
    assert not_received & posted_lines == set()
