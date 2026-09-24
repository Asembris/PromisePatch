"""A silent sibling does not cost an answered promise its window (ADR-0025).

Proof C's world, exactly as ADR-0023's tests build it: ``with_charlotte_variant`` authored in
advance and C's constraint set to ask, so the canonical report asks two customers -- Tomas about B
and the Okafor-Reyes wedding about C. The fixture's own schedule gives the two unequal windows: B's
deadline, and B's production start an hour after it, both fall hours before C's deadline.

Before ADR-0025 one case state gated every track's revalidation on the slowest customer.
``WAITING -> REVALIDATING`` happened only once *no* request was open, so Tomas's literal yes was
consumable for three hours and was not looked at until C's window closed -- by which time B's start
had passed, the round refused the yes as stale, and B was re-planned behind its own start with no
amendment ever made.

Every workflow row below is written by the product. The test levers are the world, the order in
which the customers answer, the claim order of two steps the product creates together, and the
step runner's clock -- moved by a fixed offset, never by a row.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from _intake_support import TOMAS_CHANNEL, Intake
from _intake_support import physical as physical
from test_execution_freshness import database_time, move_clock, until
from test_two_track_reask import OKAFOR_CHANNEL, amendments, asked_twice, asks

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import ApprovalRequestState
from promisepatch.domain import analysis, approvals, cases, recovery, steps, timers
from promisepatch.domain.adapters import FakeEffectAdapter, ProviderBehaviour

pytestmark = pytest.mark.integration

A, B, C, D, E, F = (
    ho.PROMISE_A,
    ho.PROMISE_B,
    ho.PROMISE_C,
    ho.PROMISE_D,
    ho.PROMISE_E,
    ho.PROMISE_F,
)


# ------------------------------------------------------------------------------------ driving


async def b_answered_c_silent(intake: Intake) -> tuple[UUID, Any, Any, Any, Any]:
    """Both asked, the unequal windows asserted from the fixture, and Tomas's yes drained."""
    case_id, b, c = await asked_twice(intake)
    b_request = await intake.request_for(b.id)
    c_request = await intake.request_for(c.id)
    b_start = (await intake.task_of_line(ho.LINE_B)).scheduled_start
    # The shape of the defect: B's window, and B's production start after it, both close hours
    # before C's customer could still answer.
    assert b_request.deadline < b_start < c_request.deadline

    await intake.deliver_reply(b_request.id, "YES", sender=TOMAS_CHANNEL)
    await intake.drain(limit=60)
    return case_id, b, c, b_request, c_request


async def unrelated(intake: Intake, case_id: UUID) -> dict[str, tuple[str, int]]:
    return {
        track.promise_id: (track.state, len(await intake.effects_for(track.id)))
        for track in await intake.tracks(case_id)
        if track.promise_id in {A, D, E, F}
    }


async def checklist_created(intake: Intake, case_id: UUID, track_id: UUID, runner: Any) -> Any:
    """Run the worker until one track's revalidation exists, and return it before it runs."""
    for _ in range(10):
        step = await intake.step_named(case_id, cases.revalidate_step_key(track_id))
        if step is not None:
            assert step.state == "PENDING"
            return step
        await runner.run_once()
    raise AssertionError("the answer never opened a revalidation")


def after(events: list[str], marker: str) -> list[str]:
    """The case's own moves after the first ``marker`` event, in the order they committed."""
    tail = events[events.index(marker) + 1 :]
    return [event for event in tail if event.startswith("case.")]


# ============================================================ B is applied while C is silent


async def test_an_answered_promise_is_revalidated_and_applied_while_its_sibling_is_silent(
    physical: Intake,
) -> None:
    """The reproduction. Tomas's yes is checked and applied now, and the case waits on C again.

    Before ADR-0025 this ended with the case ``WAITING``, B ``WAITING_FOR_CUSTOMER`` with its
    request ``ANSWERED``, no ``revalidate:B`` step and nothing outstanding: an answer in the
    database that nothing was coming to read until C's window closed.
    """
    case_id, b, c, b_request, c_request = await b_answered_c_silent(physical)

    checked = await physical.step_named(case_id, cases.revalidate_step_key(b.id))
    assert checked is not None, "B's yes was not revalidated while C was silent"
    assert (checked.result["outcome"], checked.result["request_id"]) == (
        "PROCEED",
        str(b_request.id),
    )
    (amended,) = await amendments(physical, b.id)
    assert (amended.state, amended.attempts) == ("DELIVERED", 1)
    assert (await physical.track(case_id, B)).state == recovery.TRACK_RECOVERED

    # C is exactly where it was: asked once, unanswered, unrevalidated, nothing applied.
    c_now = await physical.track(case_id, C)
    assert (c_now.state, c_now.approval_request_id) == (
        cases.TRACK_WAITING_FOR_CUSTOMER,
        c_request.id,
    )
    open_c = await physical.request_for(c.id)
    assert (open_c.state, open_c.decided) == (ApprovalRequestState.SENT.value, False)
    assert await physical.step_named(case_id, cases.revalidate_step_key(c.id)) is None
    assert await amendments(physical, c.id) == []
    assert (len(await asks(physical, b.id)), len(await asks(physical, c.id))) == (1, 1)
    assert [row.request_id for row in await physical.decisions()] == [b_request.id]

    # The case went the way §14.2 draws it, and now truthfully waits on C with nothing running.
    assert after(await physical.events(case_id), approvals.EVENT_APPROVAL_DECIDED) == [
        cases.EVENT_CASE_REVALIDATION_READY,
        cases.EVENT_CASE_RECONCILING,
        cases.EVENT_CASE_WAITING,
    ]
    # Owner attention is D's, escalated at confirmation; nothing about B or C added to it.
    assert (await physical.case(case_id)).state == cases.CASE_WAITING
    assert await physical.outstanding(case_id) == []


async def test_b_s_start_passing_changes_nothing_once_b_is_settled(
    physical: Intake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window the defect spent is irrelevant now: B was settled inside it."""
    case_id, b, _, _, _ = await b_answered_c_silent(physical)
    move_clock(
        monkeypatch, steps, timers, by=await until(physical, ho.LINE_B, past=timedelta(hours=1))
    )
    await physical.drain(limit=40)

    assert (await physical.track(case_id, B)).state == recovery.TRACK_RECOVERED
    assert len(await amendments(physical, b.id)) == 1
    assert await physical.step_named(case_id, analysis.replan_step_key(b.id)) is None
    assert (await physical.case(case_id)).state == cases.CASE_WAITING


# ======================================================================= C answers later


async def test_c_answering_later_is_revalidated_once_and_b_is_not_touched_again(
    physical: Intake,
) -> None:
    """C's own yes, on its own request, checked once; B's rows are not revisited."""
    case_id, b, c, b_request, c_request = await b_answered_c_silent(physical)
    b_checked = await physical.step_named(case_id, cases.revalidate_step_key(b.id))

    # Tomas cannot answer C's question: the sender is checked against C's own channel.
    await physical.deliver_reply(c_request.id, "YES", sender=TOMAS_CHANNEL)
    await physical.drain(limit=20)
    assert [row.request_id for row in await physical.decisions()] == [b_request.id]
    assert (await physical.track(case_id, C)).state == cases.TRACK_WAITING_FOR_CUSTOMER

    await physical.deliver_reply(c_request.id, "YES", sender=OKAFOR_CHANNEL)
    await physical.drain(limit=60)

    c_checked = await physical.step_named(case_id, cases.revalidate_step_key(c.id))
    assert (c_checked.result["outcome"], c_checked.result["request_id"]) == (
        "PROCEED",
        str(c_request.id),
    )
    assert (await physical.track(case_id, B)).state == recovery.TRACK_RECOVERED
    assert (await physical.track(case_id, C)).state == recovery.TRACK_RECOVERED
    assert (len(await amendments(physical, b.id)), len(await amendments(physical, c.id))) == (1, 1)
    # B's checklist is the one that ran before C answered, not a second one.
    again = await physical.step_named(case_id, cases.revalidate_step_key(b.id))
    assert (again.id, again.attempts, again.result) == (
        b_checked.id,
        b_checked.attempts,
        b_checked.result,
    )
    assert [row.request_id for row in await physical.decisions()] == [b_request.id, c_request.id]

    applied = {
        row.track_id: row.provenance
        for row in await physical.audits(case_id)
        if row.type == recovery.AUDIT_RECOVERY_APPLIED and row.track_id in {b.id, c.id}
    }
    assert applied[b.id]["approval_request_id"] == str(b_request.id)
    assert applied[c.id]["approval_request_id"] == str(c_request.id)

    assert (await physical.case(case_id)).state == cases.CASE_RESOLVED
    assert await physical.outstanding(case_id) == []


async def test_replaying_every_step_of_both_rounds_changes_nothing(physical: Intake) -> None:
    """Idempotency: each revalidation, apply, finalize and reconcile runs again and adds nothing."""
    case_id, b, c, _, c_request = await b_answered_c_silent(physical)
    await physical.deliver_reply(c_request.id, "YES", sender=OKAFOR_CHANNEL)
    await physical.drain(limit=60)
    before = (
        len(await physical.requests()),
        len(await physical.decisions()),
        len(await physical.effects()),
    )

    for step in await physical.steps(case_id):
        if step.kind in {
            cases.STEP_REVALIDATE_RECOVERY,
            cases.STEP_RECONCILE_CASE,
            recovery.STEP_APPLY_RECOVERY,
            recovery.STEP_FINALIZE_RECOVERY,
        }:
            await physical.requeue(step.id)
    await physical.drain(limit=60)

    assert (
        len(await physical.requests()),
        len(await physical.decisions()),
        len(await physical.effects()),
    ) == before
    assert (len(await amendments(physical, b.id)), len(await amendments(physical, c.id))) == (1, 1)
    assert (len(await asks(physical, b.id)), len(await asks(physical, c.id))) == (1, 1)
    assert (await physical.case(case_id)).state == cases.CASE_RESOLVED


# ============================================================ C times out, or C says no


async def test_c_timing_out_escalates_c_and_neither_undoes_nor_replays_b(
    physical: Intake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C's window closes on the clock alone. B stays changed once; C goes to the owner."""
    case_id, b, c, b_request, c_request = await b_answered_c_silent(physical)
    move_clock(
        monkeypatch,
        steps,
        timers,
        by=c_request.deadline - await database_time(physical) + timedelta(minutes=1),
    )
    await physical.drain(limit=60)

    c_now = await physical.track(case_id, C)
    assert c_now.state == recovery.TRACK_ESCALATED
    expired = await physical.request_for(c.id)
    assert (expired.state, expired.decided) == (ApprovalRequestState.EXPIRED.value, False)
    closed = await physical.step_named(case_id, cases.revalidate_step_key(c.id))
    assert closed.result["outcome"] == "NO_DECISION"
    assert await amendments(physical, c.id) == []

    assert (await physical.track(case_id, B)).state == recovery.TRACK_RECOVERED
    assert len(await amendments(physical, b.id)) == 1
    assert [row.request_id for row in await physical.decisions()] == [b_request.id]
    case = await physical.case(case_id)
    assert (case.state, case.needs_owner_attention) == (cases.CASE_RESOLVED, True)
    assert await physical.outstanding(case_id) == []


async def test_c_declining_escalates_c_and_neither_undoes_nor_replays_b(physical: Intake) -> None:
    case_id, b, c, b_request, c_request = await b_answered_c_silent(physical)
    await physical.deliver_reply(c_request.id, "NO", sender=OKAFOR_CHANNEL)
    await physical.drain(limit=60)

    assert (await physical.track(case_id, C)).state == recovery.TRACK_ESCALATED
    assert await amendments(physical, c.id) == []
    assert (await physical.track(case_id, B)).state == recovery.TRACK_RECOVERED
    assert len(await amendments(physical, b.id)) == 1
    assert [row.request_id for row in await physical.decisions()] == [b_request.id, c_request.id]
    case = await physical.case(case_id)
    assert (case.state, case.needs_owner_attention) == (cases.CASE_RESOLVED, True)
    assert await physical.outstanding(case_id) == []


# ============================================== C answers while B is still being carried through


@pytest.mark.parametrize("first", ["b", "c"])
async def test_c_answering_during_b_s_revalidation_joins_the_round_in_either_claim_order(
    physical: Intake, first: str
) -> None:
    """Both answers read before either checklist runs: one round, ended once, in either order."""
    case_id, b, c = await asked_twice(physical)
    b_request = await physical.request_for(b.id)
    c_request = await physical.request_for(c.id)
    await physical.deliver_reply(b_request.id, "YES", sender=TOMAS_CHANNEL)
    runner = physical.worker()
    b_step = await checklist_created(physical, case_id, b.id, runner)
    # B's checklist is held only until C's reply has been read, so both answers meet in one round.
    await physical.defer(b_step.id)
    await physical.deliver_reply(c_request.id, "YES", sender=OKAFOR_CHANNEL)
    for _ in range(10):
        if len(await physical.decisions()) == 2:
            break
        await runner.run_once()
    assert (await physical.case(case_id)).state == cases.CASE_REVALIDATING
    await physical.release(b_step.id)
    b_step = await physical.step_named(case_id, cases.revalidate_step_key(b.id))
    c_step = await physical.step_named(case_id, cases.revalidate_step_key(c.id))
    assert (b_step.state, c_step.state) == ("PENDING", "PENDING")

    ahead, later = (b_step, c_step) if first == "b" else (c_step, b_step)
    await physical.defer(later.id)
    for _ in range(10):
        if (await physical.step_named(case_id, ahead.step_key)).state == "DONE":
            break
        await runner.run_once()
    # The first checklist did not end the round under the second.
    assert (await physical.case(case_id)).state == cases.CASE_REVALIDATING
    await physical.requeue(later.id)
    await physical.drain(limit=80)

    assert (await physical.track(case_id, B)).state == recovery.TRACK_RECOVERED
    assert (await physical.track(case_id, C)).state == recovery.TRACK_RECOVERED
    assert (len(await amendments(physical, b.id)), len(await amendments(physical, c.id))) == (1, 1)
    assert (await physical.case(case_id)).state == cases.CASE_RESOLVED
    assert await physical.outstanding(case_id) == []


async def test_c_answering_while_b_is_being_applied_waits_for_b_to_settle(
    physical: Intake,
) -> None:
    """C's yes lands while B's amendment is in flight. It is read now and checked after B settles.

    ``RECONCILING`` finishes what it is applying before the case moves on, and C's checklist then
    counts B's substitute among the allocations "by tracks already RECOVERED" (§14.3 check 5).
    The provider's first answer is a timeout, so B's amendment waits on its retry in the outbox.
    """
    case_id, b, c = await asked_twice(physical)
    b_request = await physical.request_for(b.id)
    c_request = await physical.request_for(c.id)
    adapter = FakeEffectAdapter()
    adapter.script = [ProviderBehaviour.TIMEOUT_BEFORE_APPLYING]
    worker = physical.worker(adapter=adapter)
    await physical.deliver_reply(b_request.id, "YES", sender=TOMAS_CHANNEL)
    await physical.drain(worker=worker, limit=60)

    assert (await physical.track(case_id, B)).state == recovery.TRACK_APPLYING
    (in_flight,) = await amendments(physical, b.id)
    assert (in_flight.state, in_flight.attempts) == ("PENDING", 1)
    assert (await physical.case(case_id)).state == cases.CASE_RECONCILING

    await physical.deliver_reply(c_request.id, "YES", sender=OKAFOR_CHANNEL)
    await physical.drain(worker=worker, limit=40)
    # Read and recorded, and not yet checked: B's change is still being made.
    assert [row.request_id for row in await physical.decisions()] == [b_request.id, c_request.id]
    assert await physical.step_named(case_id, cases.revalidate_step_key(c.id)) is None
    assert (await physical.case(case_id)).state == cases.CASE_RECONCILING

    await physical.make_effect_due(in_flight.id)
    await physical.drain(worker=worker, limit=80)
    c_checked = await physical.step_named(case_id, cases.revalidate_step_key(c.id))
    assert c_checked.result["outcome"] == "PROCEED"
    assert (await physical.track(case_id, B)).state == recovery.TRACK_RECOVERED
    assert (await physical.track(case_id, C)).state == recovery.TRACK_RECOVERED
    (b_amended,) = await amendments(physical, b.id)
    assert (b_amended.state, b_amended.attempts) == ("DELIVERED", 2)
    assert len(await amendments(physical, c.id)) == 1
    assert (await physical.case(case_id)).state == cases.CASE_RESOLVED
    assert await physical.outstanding(case_id) == []


# ========================================================== B goes stale while C is silent


async def test_b_going_stale_while_c_is_silent_re_plans_b_and_c_answers_into_the_plan(
    physical: Intake,
) -> None:
    """B's round ends at ``PLANNED`` with C still open. C's yes is kept, and checked once the plan
    is confirmed; B is asked again under the new plan and nobody is asked twice for one question.
    """
    case_id, b, c = await asked_twice(physical)
    b_request = await physical.request_for(b.id)
    c_request = await physical.request_for(c.id)
    await physical.bump_order_version(ho.ORDER_B)
    await physical.deliver_reply(b_request.id, "YES", sender=TOMAS_CHANNEL)
    await physical.drain(limit=60)

    refused = await physical.step_named(case_id, cases.revalidate_step_key(b.id))
    assert refused.result["outcome"] == "STALE"
    assert (await physical.track(case_id, B)).state == analysis.TRACK_PENDING
    assert (await physical.case(case_id)).state == cases.CASE_PLANNED
    still_open = await physical.request_for(c.id)
    assert (still_open.state, still_open.decided) == (ApprovalRequestState.SENT.value, False)

    await physical.deliver_reply(c_request.id, "YES", sender=OKAFOR_CHANNEL)
    await physical.drain(limit=40)
    # Kept, not lost and not yet checked: a planned case waits on a worker's yes for B.
    assert [row.request_id for row in await physical.decisions()] == [b_request.id, c_request.id]
    assert await physical.step_named(case_id, cases.revalidate_step_key(c.id)) is None
    assert (await physical.case(case_id)).state == cases.CASE_PLANNED

    await physical.confirm(case_id, plan_id=await physical.plan_id(case_id))
    await physical.drain(limit=80)

    c_checked = await physical.step_named(case_id, cases.revalidate_step_key(c.id))
    assert c_checked.result["outcome"] == "PROCEED"
    assert (await physical.track(case_id, C)).state == recovery.TRACK_RECOVERED
    assert len(await amendments(physical, c.id)) == 1
    b_now = await physical.track(case_id, B)
    assert b_now.state == cases.TRACK_WAITING_FOR_CUSTOMER
    assert b_now.approval_request_id not in {b_request.id, c_request.id}
    assert await amendments(physical, b.id) == []
    assert (len(await asks(physical, b.id)), len(await asks(physical, c.id))) == (2, 1)
    assert (await physical.case(case_id)).state == cases.CASE_WAITING
    assert await physical.outstanding(case_id) == []


async def test_an_answer_kept_through_an_unconfirmed_re_plan_is_still_checked(
    physical: Intake,
) -> None:
    """Nobody confirms B's re-plan. B goes to the owner, and C's kept yes is then checked once."""
    case_id, b, c = await asked_twice(physical)
    b_request = await physical.request_for(b.id)
    c_request = await physical.request_for(c.id)
    await physical.bump_order_version(ho.ORDER_B)
    await physical.deliver_reply(b_request.id, "YES", sender=TOMAS_CHANNEL)
    await physical.drain(limit=60)
    await physical.deliver_reply(c_request.id, "YES", sender=OKAFOR_CHANNEL)
    await physical.drain(limit=40)
    assert (await physical.case(case_id)).state == cases.CASE_PLANNED

    assert await physical.close_plan_window(case_id)
    await physical.drain(limit=80)

    assert (await physical.track(case_id, B)).state == recovery.TRACK_ESCALATED
    c_checked = await physical.step_named(case_id, cases.revalidate_step_key(c.id))
    assert c_checked.result["outcome"] == "PROCEED"
    assert (await physical.track(case_id, C)).state == recovery.TRACK_RECOVERED
    assert (len(await amendments(physical, b.id)), len(await amendments(physical, c.id))) == (0, 1)
    case = await physical.case(case_id)
    assert (case.state, case.needs_owner_attention) == (cases.CASE_RESOLVED, True)
    assert await physical.outstanding(case_id) == []


# ================================================================== nothing unrelated moves


async def test_nothing_unrelated_is_touched_while_b_settles_and_c_times_out(
    physical: Intake, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id, _, _ = await asked_twice(physical)
    before = await unrelated(physical, case_id)

    b = await physical.track(case_id, B)
    c_request = await physical.request_for((await physical.track(case_id, C)).id)
    await physical.deliver_reply((await physical.request_for(b.id)).id, "YES", sender=TOMAS_CHANNEL)
    await physical.drain(limit=60)
    assert await unrelated(physical, case_id) == before

    move_clock(
        monkeypatch,
        steps,
        timers,
        by=c_request.deadline - await database_time(physical) + timedelta(minutes=1),
    )
    await physical.drain(limit=60)
    assert await unrelated(physical, case_id) == before
    for promise_id in (E, F):
        track = await physical.track(case_id, promise_id)
        assert await physical.request_for(track.id) is None


# ================================================================ the names the rules count by


def test_the_recovery_work_the_reconciling_rule_waits_on_is_recovery_s_own() -> None:
    """``cases`` names these by value to avoid an import cycle; they must never drift apart."""
    owned = {
        recovery.STEP_APPLY_RECOVERY,
        recovery.STEP_FINALIZE_RECOVERY,
        recovery.STEP_ABANDON_RECOVERY,
    }
    assert owned == cases.RECOVERY_WORK_KINDS


def test_every_entry_into_reconciling_has_its_own_key_naming_the_case() -> None:
    case_id = UUID("6b0f7a9e-0000-4000-8000-000000000001")
    first, third = cases.reconcile_step_key(case_id), cases.reconcile_step_key(case_id, 2)
    assert first == f"reconcile:{case_id}"
    assert third == f"reconcile:{case_id}:2"
    assert cases.case_of(first) == cases.case_of(third) == case_id
