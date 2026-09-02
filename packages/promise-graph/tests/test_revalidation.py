"""The ten revalidation checks, each falsifiable in isolation."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from promise_graph.fingerprint import constraint_hash, fingerprint, scope_for
from promise_graph.model import (
    ApprovalDecisionKind,
    ApprovalDecisionRecord,
    ApprovalRequestRecord,
    OrderState,
    ParserKind,
    TaskState,
)
from promise_graph.options import approval_deadline
from promise_graph.revalidation import RevalidationOutcome, revalidate
from promise_graph.snapshot import GraphSnapshot
from tests.fixtures import hollow_oak as ho
from tests.fixtures import settle, settle_and_analyze


def prepared(
    anchor: datetime,
) -> tuple[GraphSnapshot, ApprovalRequestRecord, ApprovalDecisionRecord]:
    """Track B, waiting on Tomas, exactly as the case engine would have parked it."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    analysis = settle_and_analyze(snapshot, exception, anchor)
    option = analysis.option_sets[ho.PROMISE_B].valid[0]
    scope = scope_for(settled, analysis.impact, analysis.option_sets[ho.PROMISE_B], ho.PROMISE_B)
    task = settled.task_of_line(ho.LINE_B)
    assert task is not None and task.scheduled_start is not None
    request = ApprovalRequestRecord(
        id="req-b",
        track_id="trk-b",
        promise_id=ho.PROMISE_B,
        order_id=ho.ORDER_B,
        order_line_id=ho.LINE_B,
        option_id=option.id,
        candidate_version_id=option.to_version_id,
        substitute_resource_id=option.substitute_resource_id,
        required_substitute_quantity=option.required_quantity,
        customer_channel="tg:1002",
        sent_at=anchor,
        deadline=approval_deadline(anchor, task.scheduled_start),
        captured_fingerprint=fingerprint(settled, scope).hash,
        captured_order_version=settled.orders[ho.ORDER_B].external_version,
        captured_recipe_version_id=ho.RRC_V2,
        captured_constraint_hash=constraint_hash(settled, ho.ORDER_B),
    )
    decision = ApprovalDecisionRecord(
        request_id=request.id,
        decision=ApprovalDecisionKind.APPROVE,
        parser=ParserKind.LITERAL,
        sender_identity="tg:1002",
        provider_message_id="tg-msg-1",
        raw_text="YES",
        received_at=anchor + timedelta(minutes=30),
    )
    return settled, request, decision


def test_all_ten_checks_pass_on_an_untouched_world(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    result = revalidate(
        snapshot,
        request,
        decision,
        anchor + timedelta(minutes=30),
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert result.outcome is RevalidationOutcome.PROCEED
    assert len(result.checks) == 10
    assert result.failed == ()
    assert [check.index for check in result.checks] == list(range(1, 11))
    assert all(check.expected and check.actual for check in result.checks)


def test_check_1_track_or_case_not_waiting(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    result = revalidate(
        snapshot,
        request,
        decision,
        anchor,
        track_is_waiting_for_customer=False,
        case_is_waiting=True,
    )
    assert result.outcome is RevalidationOutcome.NOOP
    assert result.failed[0].index == 1


def test_check_2_order_version_moved(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    orders = dict(snapshot.orders)
    orders[ho.ORDER_B] = orders[ho.ORDER_B].model_copy(update={"external_version": 7})
    result = revalidate(
        snapshot.replace(orders=orders),
        request,
        decision,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert result.outcome is RevalidationOutcome.STALE
    assert result.failed[0].index == 2


def test_check_2_order_cancelled(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    orders = dict(snapshot.orders)
    orders[ho.ORDER_B] = orders[ho.ORDER_B].model_copy(update={"state": OrderState.CANCELLED})
    result = revalidate(
        snapshot.replace(orders=orders),
        request,
        decision,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert result.outcome is RevalidationOutcome.STALE


def test_check_3_pinned_version_moved(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    result = revalidate(
        snapshot.repin_order_line(ho.LINE_B, ho.RRC_V3),
        request,
        decision,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert result.outcome is RevalidationOutcome.STALE
    assert result.failed[0].index == 3


def test_check_4_constraint_snapshot_moved(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    constraints = dict(snapshot.constraints)
    del constraints[ho.CONSTRAINT_B_ASK]
    result = revalidate(
        snapshot.replace(constraints=constraints),
        request,
        decision,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert result.outcome is RevalidationOutcome.STALE
    assert result.failed[0].index == 4


def test_check_5_substitute_no_longer_available(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    ledger = tuple(entry for entry in snapshot.ledger if entry.resource_id != ho.STRAWBERRIES)
    result = revalidate(
        snapshot.replace(ledger=ledger),
        request,
        decision,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert result.outcome is RevalidationOutcome.STALE
    assert result.failed[0].index == 5


def test_check_5_is_not_applicable_without_a_substitute(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    without = request.model_copy(
        update={"substitute_resource_id": None, "required_substitute_quantity": None}
    )
    result = revalidate(
        snapshot,
        without,
        decision,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert result.checks[4].passed
    assert result.checks[4].expected == "not applicable"


def test_check_5_fails_when_the_task_start_is_unknown(anchor: datetime) -> None:
    from tests.fixtures.adversarial import with_unknown_task_start

    snapshot, request, decision = prepared(anchor)
    result = revalidate(
        with_unknown_task_start(snapshot, "task-ol-b"),
        request,
        decision,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert not result.checks[4].passed
    assert result.outcome is RevalidationOutcome.STALE


def test_check_6_task_already_started(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    tasks = dict(snapshot.tasks)
    tasks["task-ol-b"] = tasks["task-ol-b"].model_copy(update={"state": TaskState.STARTED})
    result = revalidate(
        snapshot.replace(tasks=tasks),
        request,
        decision,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert result.outcome is RevalidationOutcome.STALE
    assert result.failed[0].index == 6


def test_check_6_now_is_past_the_task_start(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    task = snapshot.task_of_line(ho.LINE_B)
    assert task is not None and task.scheduled_start is not None
    late = task.scheduled_start + timedelta(minutes=1)
    generous = request.model_copy(update={"deadline": late + timedelta(hours=1)})
    result = revalidate(
        snapshot,
        generous,
        decision,
        late,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert result.outcome is RevalidationOutcome.STALE
    assert result.failed[0].index == 6


def test_check_7_deadline_passed(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    result = revalidate(
        snapshot,
        request,
        decision,
        request.deadline + timedelta(seconds=1),
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert result.outcome is RevalidationOutcome.EXPIRED
    assert result.failed[0].index == 7


def test_check_8_wrong_sender(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    impostor = decision.model_copy(update={"sender_identity": "tg:9999"})
    result = revalidate(
        snapshot,
        request,
        impostor,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert result.outcome is RevalidationOutcome.UNAUTHORIZED
    assert result.failed[0].index == 8


def test_check_9_non_literal_parser_is_never_a_decision(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    apparent = decision.model_copy(update={"parser": ParserKind.LLM})
    result = revalidate(
        snapshot,
        request,
        apparent,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert result.outcome is RevalidationOutcome.NOOP
    assert result.failed[0].index == 9


def test_check_10_already_decided(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    result = revalidate(
        snapshot,
        request.model_copy(update={"decided": True}),
        decision,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert result.outcome is RevalidationOutcome.NOOP
    assert result.failed[0].index == 10


def test_a_missing_decision_fails_the_identity_and_parser_checks(anchor: datetime) -> None:
    snapshot, request, _ = prepared(anchor)
    result = revalidate(
        snapshot,
        request,
        None,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    assert [check.index for check in result.failed] == [8, 9]
    assert result.outcome is RevalidationOutcome.UNAUTHORIZED


def test_the_lowest_numbered_failure_decides_the_outcome(anchor: datetime) -> None:
    """Expired *and* stale at once resolves to STALE, because check 2 comes first."""
    snapshot, request, decision = prepared(anchor)
    orders = dict(snapshot.orders)
    orders[ho.ORDER_B] = orders[ho.ORDER_B].model_copy(update={"external_version": 7})
    result = revalidate(
        snapshot.replace(orders=orders),
        request,
        decision,
        request.deadline + timedelta(hours=1),
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    failed = {check.index for check in result.failed}
    assert {2, 7} <= failed
    assert result.outcome is RevalidationOutcome.STALE


def test_every_check_reports_the_values_it_compared(anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    result = revalidate(
        snapshot,
        request,
        decision,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    for check in result.checks:
        assert check.name
        assert check.expected != ""
        assert check.actual != ""


def test_recovered_claims_are_subtracted_from_the_substitute(anchor: datetime) -> None:
    """A's already-recovered share is counted before B's approval is honoured."""
    from promise_graph.availability import Claim

    snapshot, request, decision = prepared(anchor)
    task = snapshot.task_of_line(ho.LINE_A)
    assert task is not None and task.scheduled_start is not None
    hogging = Claim(
        id="recovered:a",
        resource_id=ho.STRAWBERRIES,
        quantity=Decimal("7.0"),
        start=task.scheduled_start,
        order_external_id="EXT-A",
        order_line_id=ho.LINE_A,
        is_candidate=True,
    )
    result = revalidate(
        snapshot,
        request,
        decision,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
        recovered_claims=(hogging,),
    )
    assert result.failed[0].index == 5
    assert result.outcome is RevalidationOutcome.STALE


@pytest.mark.parametrize("index", list(range(1, 11)))
def test_each_check_has_a_distinct_index_and_name(index: int, anchor: datetime) -> None:
    snapshot, request, decision = prepared(anchor)
    result = revalidate(
        snapshot,
        request,
        decision,
        anchor,
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    matching = [check for check in result.checks if check.index == index]
    assert len(matching) == 1
