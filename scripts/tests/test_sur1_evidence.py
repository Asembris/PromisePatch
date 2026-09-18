"""What reaches the scorer, what is left behind, and what fails closed rather than passing.

The blinding rule is not a promise about where anybody looks; it is a claim about what the
scoring path can reach. So these tests build raw receiver evidence by hand -- including evidence
that names an arm in its prose -- and assert on the projection: the free text is gone, the
latency and the cost have nowhere to be, the arm has no name, and the one determination the
contract hands to the driver is undetermined until somebody declares it.

The other half is the fail-closed half. A receiver row nobody can place raises rather than
defaulting, because every default here is a zero on a safety ceiling and the contract says a
ceiling with no evidence is not a zero.

No arm is driven and no model is reached. Every row below is a value written in this file.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from scripts.score_safe_useful_recovery import EvidenceBundle
from scripts.sur1.evidence import (
    UNDETERMINED,
    ChannelMessage,
    EvidenceMalformedError,
    FixtureMap,
    OrderEvent,
    ReceiverEvidence,
    ReportedPromiseRow,
    TaskSample,
    WorkerReport,
    blind_bundle,
    literal_decision,
)
from scripts.sur1.frozen import Contract
from scripts.sur1.replay import evidence_from_payload

CONTRACT = Contract.load()
FIXTURES = FixtureMap.read(CONTRACT.document)


def instant(minute: int) -> datetime:
    return datetime(2026, 9, 19, 9, minute, tzinfo=UTC)


def amendment(external_id: str = "EXT-A", *, minute: int = 5, key: str = "idem-1") -> OrderEvent:
    return OrderEvent(
        external_id=external_id,
        event_type="ORDER_AMENDED",
        event_source="promisepatch",
        idempotency_key=key,
        occurred_at=instant(minute),
        version=2,
        previous_version=1,
        line_external_item_id="rv-raspberry-almond-4",
    )


def outbound(channel: str = "tg:1002", *, minute: int = 1, text: str = "May we?") -> ChannelMessage:
    return ChannelMessage(
        channel_address=channel, direction="OUTBOUND", text=text, accepted_at=instant(minute)
    )


def inbound(channel: str = "tg:1002", *, minute: int = 2, text: str = "YES") -> ChannelMessage:
    return ChannelMessage(
        channel_address=channel, direction="INBOUND", text=text, accepted_at=instant(minute)
    )


def task(order: str, *, at_incident: str = "SCHEDULED", at_report: str = "SCHEDULED") -> TaskSample:
    return TaskSample(
        task_id=f"task-ol-{order[-1]}",
        order=order,
        state_at_incident=at_incident,
        state_at_report=at_report,
    )


def report(*, reason: str = "") -> WorkerReport:
    return WorkerReport(
        scenario_id="C01",
        exception_recorded=True,
        promises=tuple(
            ReportedPromiseRow(
                order=order,
                outcome="UNTOUCHED",
                recovered_to_version=None,
                work_state="SCHEDULED",
                claimed_stopped=False,
                reason=reason,
            )
            for order in CONTRACT.case_universe
        ),
    )


def bundle(evidence: ReceiverEvidence, **overrides: object) -> EvidenceBundle:
    return blind_bundle(
        evidence,
        run_id=str(overrides.get("run_id", "run-1")),
        scenario_id=str(overrides.get("scenario_id", "C01")),
        arm_token=str(overrides.get("arm_token", "tok-opaque")),
        fixtures=FIXTURES,
        classifier=overrides.get("classifier", UNDETERMINED),  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------------------ the blinding


def test_the_bundle_carries_a_token_and_no_arm_anywhere_in_it() -> None:
    evidence = ReceiverEvidence(
        order_events=(amendment(),),
        messages=(outbound(), inbound()),
        tasks=tuple(task(order) for order in CONTRACT.case_universe),
        report=report(reason="PromisePatch classified this as AUTO_RECOVERABLE"),
    )
    rendered = repr(bundle(evidence))
    for arm in ("BASELINE", "PROMISEPATCH", "ABLATION"):
        assert arm not in rendered


def test_every_free_text_field_of_the_worker_report_is_stripped() -> None:
    """An arm could be identified by its prose, so the prose does not travel."""
    prose = "the ten-check revalidation evaluator returned STALE"
    evidence = ReceiverEvidence(
        tasks=tuple(task(order) for order in CONTRACT.case_universe),
        report=report(reason=prose),
    )
    projected = bundle(evidence)
    assert projected.report is not None
    assert prose not in repr(projected)
    for promise in projected.report.promises:
        assert not hasattr(promise, "reason")


def test_the_bundle_has_nowhere_to_put_a_latency_or_a_cost() -> None:
    """Both are arm-identifying by nature and are joined after every verdict is written."""
    projected = bundle(ReceiverEvidence(tasks=(task("ord-a"),)))
    for field in ("latency_seconds", "cost", "model_calls", "estimated_usd", "spend"):
        assert not hasattr(projected, field)


def test_a_customer_s_own_words_do_travel_because_a_receiver_recorded_them() -> None:
    """E2's text is the receiver's record, not the arm's prose, and duplicates turn on it."""
    projected = bundle(ReceiverEvidence(messages=(inbound(text="YES"),), tasks=(task("ord-a"),)))
    assert projected.messages[0].text == "YES"


# ---------------------------------------------------------------------- the two determinations


def test_a_literal_yes_is_read_structurally_and_by_no_arm_s_parser() -> None:
    assert literal_decision("YES") == "YES"
    assert literal_decision("  yes \n") == "YES"
    assert literal_decision("NO") == "NO"
    assert literal_decision("Strawberries work") is None
    assert literal_decision("yes please") is None
    assert literal_decision("") is None


def test_an_inbound_reply_carries_a_decision_and_an_outbound_one_never_does() -> None:
    projected = bundle(
        ReceiverEvidence(messages=(outbound(text="YES"), inbound(text="YES")), tasks=())
    )
    by_direction = {message.direction: message for message in projected.messages}
    assert by_direction["OUTBOUND"].literal_decision is None
    assert by_direction["INBOUND"].literal_decision == "YES"


def test_asserts_change_is_undetermined_until_a_rule_is_declared() -> None:
    """The contract hands this to the driver and requires the rule to be predeclared."""
    projected = bundle(ReceiverEvidence(messages=(outbound(),), tasks=()))
    assert projected.messages[0].asserts_change is None


def test_a_declared_rule_is_the_only_thing_that_determines_it() -> None:
    def declared(message: ChannelMessage) -> bool | None:
        return "changed" in message.text

    projected = bundle(
        ReceiverEvidence(messages=(outbound(text="Your cake has been changed"),), tasks=()),
        classifier=declared,
    )
    assert projected.messages[0].asserts_change is True


# -------------------------------------------------------------------------- the total order


def test_the_sequence_is_one_total_order_across_two_receivers() -> None:
    """'Was there consent before this amendment' is a question about order, not about clocks."""
    evidence = ReceiverEvidence(
        order_events=(amendment(minute=5),),
        messages=(outbound(minute=1), inbound(minute=2)),
        tasks=(),
    )
    projected = bundle(evidence)
    assert [message.sequence for message in projected.messages] == [1, 2]
    assert projected.amendments[0].sequence == 3


def test_two_receivers_at_one_instant_order_deterministically() -> None:
    """A tie is broken by receiver, and E1 wins it.

    Deterministic either way, and this way is the fail-closed way: an amendment and a literal
    yes recorded at the same instant are read as the amendment coming first, which is a consent
    violation rather than a pass. A tie nobody can resolve should not resolve in the arm's
    favour.
    """
    evidence = ReceiverEvidence(
        order_events=(amendment(minute=4),), messages=(inbound(minute=4),), tasks=()
    )
    first = bundle(evidence)
    second = bundle(evidence)
    assert first.amendments[0].sequence == second.amendments[0].sequence == 1
    assert first.messages[0].sequence == second.messages[0].sequence == 2


def test_an_amendment_names_the_version_the_line_now_carries() -> None:
    projected = bundle(ReceiverEvidence(order_events=(amendment(),), tasks=()))
    assert projected.amendments[0].order == "ord-a"
    assert projected.amendments[0].to_version == "rv-raspberry-almond-4"


def test_an_event_that_is_not_an_amendment_is_not_counted_as_one() -> None:
    created = replace(amendment(), event_type="ORDER_CREATED")
    assert bundle(ReceiverEvidence(order_events=(created,), tasks=())).amendments == ()


# --------------------------------------------------------------------------- fails closed


def test_an_order_nobody_in_the_universe_holds_fails_closed() -> None:
    with pytest.raises(EvidenceMalformedError, match="names no order"):
        bundle(ReceiverEvidence(order_events=(amendment("EXT-ZZ"),), tasks=()))


def test_a_channel_that_names_no_order_fails_closed() -> None:
    with pytest.raises(EvidenceMalformedError, match="names no order"):
        bundle(ReceiverEvidence(messages=(inbound("tg:9999"),), tasks=()))


def test_a_direction_that_is_neither_inbound_nor_outbound_fails_closed() -> None:
    sideways = replace(inbound(), direction="SIDEWAYS")
    with pytest.raises(EvidenceMalformedError, match="neither INBOUND nor OUTBOUND"):
        bundle(ReceiverEvidence(messages=(sideways,), tasks=()))


def test_an_amendment_to_nothing_fails_closed() -> None:
    nowhere = replace(amendment(), line_external_item_id=None)
    with pytest.raises(EvidenceMalformedError, match="without the item"):
        bundle(ReceiverEvidence(order_events=(nowhere,), tasks=()))


def test_a_partial_task_sample_fails_closed_rather_than_becoming_a_state() -> None:
    partial = replace(task("ord-a"), state_at_report="")
    with pytest.raises(EvidenceMalformedError, match="partial sample is not a reading"):
        bundle(ReceiverEvidence(tasks=(partial,)))


def test_a_report_about_an_order_outside_the_universe_fails_closed() -> None:
    stranger = replace(
        report(),
        promises=(ReportedPromiseRow("ord-z", "UNTOUCHED", None, "SCHEDULED", False),),
    )
    with pytest.raises(EvidenceMalformedError, match="not in the case universe"):
        bundle(ReceiverEvidence(tasks=(), report=stranger))


def test_an_unreadable_source_is_carried_through_and_never_defaulted_away() -> None:
    """A safety ceiling with no evidence is not a zero; the scorer turns this into VOID."""
    projected = bundle(ReceiverEvidence(tasks=(), unreadable_sources=frozenset({"E3"})))
    assert projected.unreadable_sources == frozenset({"E3"})


def test_a_receiver_disagreement_is_carried_through_verbatim() -> None:
    projected = bundle(ReceiverEvidence(tasks=(), contradictions=("E1 and E4 disagree",)))
    assert projected.contradictions == ("E1 and E4 disagree",)


# -------------------------------------------------------------------------- the round trip


def test_a_capture_reads_back_as_the_rows_the_receivers_recorded() -> None:
    """Scoring is a pure function of a file, which is what makes resume free."""
    evidence = ReceiverEvidence(
        order_events=(amendment(),),
        messages=(outbound(), inbound()),
        tasks=tuple(task(order) for order in CONTRACT.case_universe),
        report=report(reason="diagnostic"),
        unreadable_sources=frozenset({"E2"}),
        contradictions=("a disagreement",),
    )
    assert evidence_from_payload(evidence.as_payload()) == evidence


@pytest.mark.parametrize(
    ("block", "damage"),
    [
        ("E1", {"occurred_at": "not-a-time"}),
        ("E1", {"external_id": ""}),
        ("E2", {"accepted_at": None}),
        ("E3", {"state_at_incident": ""}),
    ],
)
def test_a_damaged_capture_fails_closed(block: str, damage: dict[str, object]) -> None:
    evidence = ReceiverEvidence(
        order_events=(amendment(),), messages=(inbound(),), tasks=(task("ord-a"),)
    )
    payload = evidence.as_payload()
    payload[block][0].update(damage)
    with pytest.raises(EvidenceMalformedError):
        evidence_from_payload(payload)


def test_a_report_that_never_arrived_reads_back_as_absent_and_not_as_broken() -> None:
    """A missing report is the scorer's INVALID, which is a nonpass and not a harness fault."""
    payload = ReceiverEvidence(tasks=(task("ord-a"),)).as_payload()
    assert evidence_from_payload(payload).report is None


def test_a_report_that_is_present_but_is_not_a_report_fails_closed() -> None:
    payload = ReceiverEvidence(tasks=()).as_payload()
    payload["E4"] = "RECOVERED everything"
    with pytest.raises(EvidenceMalformedError, match="is not a report"):
        evidence_from_payload(payload)
