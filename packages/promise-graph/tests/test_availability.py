"""The four temporal quantities and the deterministic allocator."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from promise_graph.availability import (
    Claim,
    allocate,
    available_by,
    expected,
    on_hand,
    open_commitment_lines,
    overdue_commitment_line_ids,
    reserved,
    supply,
)
from promise_graph.examples import hollow_oak as ho
from promise_graph.model import ReceivedState, TaskState
from promise_graph.snapshot import LineSettlement


def test_on_hand_sums_the_ledger(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    assert on_hand(snapshot, ho.RASPBERRIES) == Decimal("0.300")
    assert on_hand(snapshot, ho.STRAWBERRIES) == Decimal("2.000")


def test_on_hand_is_unknown_when_any_delta_is(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    ledger = tuple(
        entry.model_copy(update={"delta": None}) if entry.resource_id == ho.RASPBERRIES else entry
        for entry in snapshot.ledger
    )
    assert on_hand(snapshot.replace(ledger=ledger), ho.RASPBERRIES) is None


def test_on_hand_of_an_unknown_resource_is_zero(anchor: datetime) -> None:
    assert on_hand(ho.hollow_oak(anchor), ho.DECK_OVEN) == Decimal("0")


def test_expected_counts_only_open_lines_due_by_the_reference_time(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    before_today = anchor + timedelta(minutes=30)
    after_today = anchor + timedelta(hours=2)
    after_tomorrow = anchor + timedelta(hours=24)
    assert expected(snapshot, ho.RASPBERRIES, before_today, anchor) == Decimal("0")
    assert expected(snapshot, ho.RASPBERRIES, after_today, anchor) == Decimal("4.0")
    assert expected(snapshot, ho.RASPBERRIES, after_tomorrow, anchor) == Decimal("7.0")


def test_a_delivery_due_tomorrow_cannot_serve_a_task_today(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    task = snapshot.task_of_line(ho.LINE_A)
    assert task is not None and task.scheduled_start is not None
    assert expected(snapshot, ho.RASPBERRIES, task.scheduled_start, anchor) == Decimal("4.0")


def test_settled_lines_contribute_zero_to_expected(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    horizon = anchor + timedelta(hours=24)
    for state, received in (
        (ReceivedState.RECEIVED, None),
        (ReceivedState.NOT_RECEIVED, None),
        (ReceivedState.SHORT, Decimal("1.0")),
    ):
        settled = snapshot.settle_commitment_lines(
            [
                LineSettlement(
                    commitment_line_id=ho.VP_TODAY_RASPBERRY,
                    to_state=state,
                    received_qty=received,
                    settled_at=anchor,
                    attested_by="maya",
                )
            ]
        )
        assert expected(settled, ho.RASPBERRIES, horizon, anchor) == Decimal("3.0")


def test_expected_is_unknown_when_a_line_quantity_is(anchor: datetime) -> None:
    from tests.fixtures.adversarial import with_unknown_raspberry_quantity

    snapshot = with_unknown_raspberry_quantity(ho.hollow_oak(anchor))
    assert expected(snapshot, ho.RASPBERRIES, anchor + timedelta(hours=24), anchor) is None


def test_overdue_open_lines_contribute_zero_and_are_flagged(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    later = anchor + timedelta(hours=3)
    assert overdue_commitment_line_ids(snapshot, ho.RASPBERRIES, later) == (ho.VP_TODAY_RASPBERRY,)
    assert expected(snapshot, ho.RASPBERRIES, later + timedelta(hours=24), later) == Decimal("3.0")


def test_open_commitment_lines_are_ordered_by_due_time(anchor: datetime) -> None:
    lines = open_commitment_lines(ho.hollow_oak(anchor), ho.RASPBERRIES)
    assert [line.id for line in lines] == [
        ho.VP_TODAY_RASPBERRY,
        "cl-vp-tomorrow-raspberries",
    ]


def test_reserved_counts_claims_up_to_the_reference_time(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    task_a = snapshot.task_of_line(ho.LINE_A)
    assert task_a is not None and task_a.scheduled_start is not None
    assert reserved(snapshot, ho.RASPBERRIES, task_a.scheduled_start) == Decimal("2.4")
    assert reserved(snapshot, ho.RASPBERRIES, anchor + timedelta(days=2)) == Decimal("9.1")


def test_reserved_is_unknown_when_a_task_start_is(anchor: datetime) -> None:
    from tests.fixtures.adversarial import with_unknown_task_start

    snapshot = with_unknown_task_start(ho.hollow_oak(anchor), "task-ol-a")
    assert reserved(snapshot, ho.RASPBERRIES, anchor + timedelta(days=2)) is None


def test_supply_and_available_by(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    at = anchor + timedelta(hours=5)
    assert supply(snapshot, ho.RASPBERRIES, at, anchor) == Decimal("4.3")
    view = available_by(snapshot, ho.RASPBERRIES, at, anchor)
    assert view.on_hand == Decimal("0.3")
    assert view.expected == Decimal("4.0")
    assert view.reserved == Decimal("2.4")
    assert view.available_by == Decimal("1.9")
    assert view.as_of == snapshot.as_of
    assert not view.unknown


def test_available_by_is_unknown_when_supply_is(anchor: datetime) -> None:
    from tests.fixtures.adversarial import with_unknown_raspberry_quantity

    snapshot = with_unknown_raspberry_quantity(ho.hollow_oak(anchor))
    view = available_by(snapshot, ho.RASPBERRIES, anchor + timedelta(days=2), anchor)
    assert view.unknown
    assert supply(snapshot, ho.RASPBERRIES, anchor + timedelta(days=2), anchor) is None


def test_allocation_is_ordered_by_task_start(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    result = allocate(snapshot, ho.RASPBERRIES, anchor)
    assert not result.unknown
    assert [a.order_line_id for a in result.allocations] == [
        ho.LINE_A,
        ho.LINE_B,
        ho.LINE_C,
        ho.LINE_D,
    ]


def test_allocation_releases_expected_supply_as_starts_pass(anchor: datetime) -> None:
    """A's window opens after today's delivery, so its 4.0 kg is available to A but not before."""
    snapshot = ho.hollow_oak(anchor)
    result = allocate(snapshot, ho.RASPBERRIES, anchor)
    allocation_a = result.for_claim(f"{ho.LINE_A}:{ho.RASPBERRIES}")
    assert allocation_a is not None
    assert allocation_a.available_before_start == Decimal("4.3")
    assert allocation_a.satisfied


def test_partial_take_is_conservative(anchor: datetime) -> None:
    """A claim that cannot be met still consumes what it took."""
    snapshot = ho.hollow_oak(anchor)
    settled = snapshot.settle_commitment_lines(
        [
            LineSettlement(
                commitment_line_id=ho.VP_TODAY_RASPBERRY,
                to_state=ReceivedState.NOT_RECEIVED,
                received_qty=None,
                settled_at=anchor,
                attested_by="maya",
            )
        ]
    )
    result = allocate(settled, ho.RASPBERRIES, anchor)
    allocation_a = result.for_claim(f"{ho.LINE_A}:{ho.RASPBERRIES}")
    allocation_b = result.for_claim(f"{ho.LINE_B}:{ho.RASPBERRIES}")
    assert allocation_a is not None and allocation_b is not None
    assert not allocation_a.satisfied
    assert allocation_a.take == Decimal("0.3")
    assert allocation_a.shortfall == Decimal("2.1")
    assert allocation_b.available_before_start == Decimal("0")
    assert allocation_b.take == Decimal("0")


def test_allocation_is_unknown_when_a_start_is_missing(anchor: datetime) -> None:
    from tests.fixtures.adversarial import with_unknown_task_start

    snapshot = with_unknown_task_start(ho.hollow_oak(anchor), "task-ol-a")
    result = allocate(snapshot, ho.RASPBERRIES, anchor)
    assert result.unknown
    assert result.allocations == ()


def test_allocation_is_unknown_when_an_expected_quantity_is_missing(anchor: datetime) -> None:
    from tests.fixtures.adversarial import with_unknown_raspberry_quantity

    snapshot = with_unknown_raspberry_quantity(ho.hollow_oak(anchor))
    assert allocate(snapshot, ho.RASPBERRIES, anchor).unknown


def test_extra_claims_join_the_same_ordering(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    task_a = snapshot.task_of_line(ho.LINE_A)
    assert task_a is not None and task_a.scheduled_start is not None
    claim = Claim(
        id="candidate",
        resource_id=ho.STRAWBERRIES,
        quantity=Decimal("2.4"),
        start=task_a.scheduled_start,
        order_external_id="EXT-A",
        order_line_id=ho.LINE_A,
        is_candidate=True,
    )
    result = allocate(snapshot, ho.STRAWBERRIES, anchor, extra_claims=(claim,))
    allocation = result.for_claim("candidate")
    assert allocation is not None
    assert allocation.satisfied
    assert allocation.available_before_start == Decimal("8.0")


def test_extra_claims_for_other_resources_are_ignored(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    claim = Claim(
        id="elsewhere",
        resource_id=ho.BLUEBERRIES,
        quantity=Decimal("1"),
        start=anchor,
        order_external_id="EXT-Z",
    )
    result = allocate(snapshot, ho.STRAWBERRIES, anchor, extra_claims=(claim,))
    assert result.for_claim("elsewhere") is None


def test_done_tasks_no_longer_consume(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    tasks = dict(snapshot.tasks)
    tasks["task-ol-a"] = tasks["task-ol-a"].model_copy(update={"state": TaskState.DONE})
    result = allocate(snapshot.replace(tasks=tasks), ho.RASPBERRIES, anchor)
    assert result.for_claim(f"{ho.LINE_A}:{ho.RASPBERRIES}") is None


def test_ties_on_start_are_broken_by_order_then_claim_id(anchor: datetime) -> None:
    snapshot = ho.hollow_oak(anchor)
    task_a = snapshot.task_of_line(ho.LINE_A)
    assert task_a is not None and task_a.scheduled_start is not None
    tasks = dict(snapshot.tasks)
    tasks["task-ol-b"] = tasks["task-ol-b"].model_copy(
        update={"scheduled_start": task_a.scheduled_start}
    )
    result = allocate(snapshot.replace(tasks=tasks), ho.RASPBERRIES, anchor)
    assert [a.order_line_id for a in result.allocations][:2] == [ho.LINE_A, ho.LINE_B]
