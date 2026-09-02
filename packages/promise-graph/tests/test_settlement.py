"""Commitment settlement: the exactly-once posting rule of ADR-0014.

These tests assert the worked example of the architecture's section 9.4 number for number,
because the whole demo's second take depends on it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from promise_graph.availability import (
    apply_exception_facts,
    expected,
    on_hand,
)
from promise_graph.model import (
    ExceptionCategory,
    LedgerSourceKind,
    PhysicalException,
    ReceivedState,
)
from tests.fixtures import hollow_oak as ho


def test_raspberry_only_settles_two_lines_and_posts_once(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    result = apply_exception_facts(snapshot, ho.raspberry_only(anchor), anchor)

    settled = {s.commitment_line_id: s.to_state for s in result.settlements}
    assert settled == {
        ho.VP_TODAY_RASPBERRY: ReceivedState.NOT_RECEIVED,
        ho.VP_TODAY_STRAWBERRY: ReceivedState.RECEIVED,
    }
    assert [(p.resource_id, p.delta) for p in result.postings] == [
        (ho.STRAWBERRIES, Decimal("6.0"))
    ]
    assert all(p.source_kind is LedgerSourceKind.COMMITMENT_RECEIPT for p in result.postings)


def test_the_worked_example_numbers(anchor: datetime) -> None:
    """on_hand(rasp)=0.3, expected(rasp)=0; on_hand(straw)=8.0, expected(straw)=0."""
    settled = apply_exception_facts(
        ho.hollow_oak(anchor), ho.raspberry_only(anchor), anchor
    ).snapshot
    today = anchor + timedelta(hours=10)
    assert on_hand(settled, ho.RASPBERRIES) == Decimal("0.3")
    assert expected(settled, ho.RASPBERRIES, today, anchor) == Decimal("0")
    assert on_hand(settled, ho.STRAWBERRIES) == Decimal("8.0")
    assert expected(settled, ho.STRAWBERRIES, today, anchor) == Decimal("0")


def test_whole_delivery_leaves_the_strawberries_on_the_shelf(anchor: datetime) -> None:
    result = apply_exception_facts(ho.hollow_oak(anchor), ho.whole_delivery(anchor), anchor)
    assert result.postings == ()
    assert {s.to_state for s in result.settlements} == {ReceivedState.NOT_RECEIVED}
    assert on_hand(result.snapshot, ho.STRAWBERRIES) == Decimal("2.0")


def test_received_supply_is_never_also_expected(anchor: datetime) -> None:
    settled = apply_exception_facts(
        ho.hollow_oak(anchor), ho.raspberry_only(anchor), anchor
    ).snapshot
    horizon = anchor + timedelta(days=3)
    line = settled.commitment_lines[ho.VP_TODAY_STRAWBERRY]
    assert line.received_state is ReceivedState.RECEIVED
    assert expected(settled, ho.STRAWBERRIES, horizon, anchor) == Decimal("0")
    assert on_hand(settled, ho.STRAWBERRIES) == Decimal("8.0")


def test_a_short_line_posts_what_arrived_and_loses_the_rest(anchor: datetime) -> None:
    exception = PhysicalException(
        id="exc-short",
        category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
        commitment_id=ho.VP_TODAY,
        scope_line_ids=(ho.VP_TODAY_RASPBERRY,),
        quantity=Decimal("1.5"),
        reported_by="maya",
        reported_at=anchor,
    )
    result = apply_exception_facts(ho.hollow_oak(anchor), exception, anchor)
    line = result.snapshot.commitment_lines[ho.VP_TODAY_RASPBERRY]
    assert line.received_state is ReceivedState.SHORT
    assert line.received_qty == Decimal("1.5")
    assert on_hand(result.snapshot, ho.RASPBERRIES) == Decimal("1.8")
    assert expected(result.snapshot, ho.RASPBERRIES, anchor + timedelta(hours=5), anchor) == (
        Decimal("0")
    )


def test_settlement_is_idempotent(anchor: datetime) -> None:
    """A replayed transition posts nothing further, exactly as the database index enforces."""
    first = apply_exception_facts(ho.hollow_oak(anchor), ho.raspberry_only(anchor), anchor)
    second = apply_exception_facts(first.snapshot, ho.raspberry_only(anchor), anchor)
    assert second.postings == ()
    assert second.settlements == ()
    assert second.snapshot == first.snapshot


def test_settlement_is_deterministic(anchor: datetime) -> None:
    a = apply_exception_facts(ho.hollow_oak(anchor), ho.raspberry_only(anchor), anchor)
    b = apply_exception_facts(ho.hollow_oak(anchor), ho.raspberry_only(anchor), anchor)
    assert a.postings == b.postings
    assert a.settlements == b.settlements
    assert a.snapshot == b.snapshot


def test_stock_unusable_posts_a_negative_delta(anchor: datetime) -> None:
    result = apply_exception_facts(ho.hollow_oak(anchor), ho.cream_unusable(anchor), anchor)
    assert len(result.postings) == 1
    posting = result.postings[0]
    assert posting.resource_id == ho.HEAVY_CREAM
    assert posting.delta == Decimal("-100.0")
    assert posting.source_kind is LedgerSourceKind.EXCEPTION_FACT
    assert on_hand(result.snapshot, ho.HEAVY_CREAM) == Decimal("0")


def test_stock_unusable_with_a_partial_quantity(anchor: datetime) -> None:
    exception = PhysicalException(
        id="exc-partial-cream",
        category=ExceptionCategory.STOCK_UNUSABLE,
        resource_id=ho.HEAVY_CREAM,
        quantity=Decimal("40.0"),
        reported_by="maya",
        reported_at=anchor,
    )
    result = apply_exception_facts(ho.hollow_oak(anchor), exception, anchor)
    assert on_hand(result.snapshot, ho.HEAVY_CREAM) == Decimal("60.0")


def test_stock_unusable_is_idempotent(anchor: datetime) -> None:
    first = apply_exception_facts(ho.hollow_oak(anchor), ho.cream_unusable(anchor), anchor)
    second = apply_exception_facts(first.snapshot, ho.cream_unusable(anchor), anchor)
    assert second.postings == ()
    assert second.snapshot is first.snapshot


def test_stock_unusable_of_an_unknown_amount_fails_closed(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    ledger = tuple(
        entry.model_copy(update={"delta": None}) if entry.resource_id == ho.HEAVY_CREAM else entry
        for entry in snapshot.ledger
    )
    result = apply_exception_facts(
        snapshot.replace(ledger=ledger), ho.cream_unusable(anchor), anchor
    )
    assert result.postings[0].delta is None
    assert on_hand(result.snapshot, ho.HEAVY_CREAM) is None


def test_equipment_exception_records_an_outage_and_posts_nothing(anchor: datetime) -> None:
    result = apply_exception_facts(ho.hollow_oak(anchor), ho.deck_oven_down(anchor), anchor)
    assert result.postings == ()
    assert result.outage is not None
    assert result.outage.equipment_id == ho.DECK_OVEN
    assert result.outage.starts_at == anchor
    assert result.snapshot.outages_by_equipment[ho.DECK_OVEN][0] == result.outage


def test_equipment_exception_is_idempotent(anchor: datetime) -> None:
    first = apply_exception_facts(ho.hollow_oak(anchor), ho.deck_oven_down(anchor), anchor)
    second = apply_exception_facts(first.snapshot, ho.deck_oven_down(anchor), anchor)
    assert second.outage is None
    assert second.snapshot is first.snapshot


def test_already_settled_lines_are_left_alone(anchor: datetime) -> None:
    """A second, differently scoped exception cannot re-settle a line in place."""
    once = apply_exception_facts(ho.hollow_oak(anchor), ho.raspberry_only(anchor), anchor).snapshot
    again = apply_exception_facts(once, ho.whole_delivery(anchor), anchor)
    assert again.settlements == ()
    assert once.commitment_lines[ho.VP_TODAY_STRAWBERRY].received_state is (ReceivedState.RECEIVED)
