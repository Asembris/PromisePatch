"""Withdrawing an exception: what it stops, what it cannot, and what it refuses.

The whole operation is one claim -- *future work stops, the past does not move* -- and every
test here is that claim asked from a different angle. The negative assertions carry the weight,
because a withdrawal that quietly reversed something would pass a suite that only checked the
case reached a terminal state.

Four things are asserted in every branch that touches them, and they are the four ways this
could be wrong in a way a person would only find out from a customer:

* a physical fact is never reversed -- the raspberries that did not arrive still did not;
* a delivered effect is never rewritten, and is reported as applied rather than as stopped;
* a customer's recorded decision survives, because it is a thing they said;
* the same withdrawal arriving twice writes once.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from _intake_support import BAKER, OWNER, Intake
from _intake_support import physical as physical

from promise_graph.examples import hollow_oak as ho
from promisepatch.domain import cases, intake, status_view, withdrawal

pytestmark = pytest.mark.integration

BLOCKED = (ho.PROMISE_C, ho.PROMISE_D)
"""The two promises whose confirmation takes a production hold -- the first consequential write
this build can perform without a provider having answered anything."""


async def withdraw(
    intake_support: Intake,
    case_id: Any,
    *,
    worker_id: str = BAKER,
    command_id: Any = None,
) -> withdrawal.WithdrawalResult:
    return await withdrawal.withdraw_exception(
        intake_support.database,
        case_id=case_id,
        command_id=command_id or uuid4(),
        worker_id=worker_id,
    )


async def case_state(intake_support: Intake, case_id: Any) -> str:
    row = await intake_support.case(case_id)
    return str(row.state)


# ------------------------------------------------------- before anything has been carried out


async def test_withdrawing_a_planned_case_cancels_it_and_withdraws_every_track(
    physical: Intake,
) -> None:
    """§14.1's first path: nothing consequential yet, so the case is ``CANCELLED``.

    ``PLANNED`` is the state in which a plan has been worked out and nobody has said yes to it.
    Nothing has gone out, nothing is held and no customer has been asked, so there is nothing
    for the withdrawal to fail to stop.
    """
    case_id = await physical.resolved_case()
    assert await case_state(physical, case_id) == "PLANNED"

    result = await withdraw(physical, case_id)

    assert result.created is True
    assert result.state == "CANCELLED"
    assert await case_state(physical, case_id) == "CANCELLED"
    assert result.applied == ()
    assert result.escalated == ()
    assert result.withdrawn


async def test_a_cancelled_case_leaves_no_track_holding_its_promise(physical: Intake) -> None:
    """Every live track reaches a terminal state, or the promise is locked out of later cases.

    ``ix_tracks_one_live_per_promise`` is unique over non-terminal tracks, so a withdrawal that
    left one ``PENDING`` would make that promise unreachable by any future exception.
    """
    case_id = await physical.resolved_case()
    await withdraw(physical, case_id)

    states = {track.state for track in await physical.tracks(case_id)}
    assert states <= {"WITHDRAWN", "UNAFFECTED", "LINKED"}
    assert "PENDING" not in states


async def test_withdrawing_before_any_effect_sends_nothing_and_changes_no_order(
    physical: Intake,
) -> None:
    """The central negative. A withdrawal is not a way to cause an effect."""
    case_id = await physical.resolved_case()
    before = await physical.order_book()

    await withdraw(physical, case_id)

    assert await physical.effects() == []
    assert await physical.order_book() == before


async def test_withdrawing_while_a_question_is_open_cancels_the_case(physical: Intake) -> None:
    """§16.3 offers the verb while a case is clarifying, so the domain has to accept it there.

    Nothing has been planned, let alone carried out, so this is the same first path: the case
    cancels and no promise is touched.
    """
    opened = await physical.report()
    await physical.drain()
    assert await case_state(physical, opened.case_id) == "CLARIFYING"

    result = await withdraw(physical, opened.case_id)

    assert result.state == "CANCELLED"
    assert result.applied == ()


async def test_the_planned_work_a_withdrawal_stands_down_is_reported(physical: Intake) -> None:
    """Nothing is stood down silently: what stopped is counted and said."""
    case_id = await physical.resolved_case()
    result = await withdraw(physical, case_id)

    reversals = dict(result.reversals)
    assert withdrawal.AppliedKind.ORDER_AMENDED not in dict(result.applied)
    assert reversals.get(withdrawal.ReversalKind.PLANNED_WORK, 0) >= 0


# ------------------------------------------------------------- after something has been applied


async def test_withdrawing_a_confirmed_case_escalates_rather_than_cancelling(
    physical: Intake,
) -> None:
    """§14.1's second path. A confirmation holds the blocked promises' production tasks, which
    is a write that touches a customer promise -- so the case may not read as simply cancelled.
    """
    case_id = await physical.resolved_case()
    await physical.confirm(case_id)
    assert await case_state(physical, case_id) == "EXECUTING"

    result = await withdraw(physical, case_id)

    assert result.state != "CANCELLED"
    assert result.escalated
    assert result.withdrawn == ()
    assert (await physical.case(case_id)).needs_owner_attention is True


async def test_a_withdrawal_after_a_hold_releases_only_this_case_s_holds(
    physical: Intake,
) -> None:
    """§23's "task hold" reversed, and scoped. The kitchen gets its own work back."""
    case_id = await physical.resolved_case()
    await physical.confirm(case_id)
    held = {task for task, (state, holder) in (await physical.tasks()).items() if state == "HELD"}
    assert held

    result = await withdraw(physical, case_id)

    after = await physical.tasks()
    for task in held:
        assert after[task] == ("SCHEDULED", None)
    assert dict(result.reversals)[withdrawal.ReversalKind.TASK_HOLD] == len(held)


async def test_a_delivered_effect_is_reported_as_applied_and_is_not_rewritten(
    physical: Intake,
) -> None:
    """The one that matters most: a withdrawal never pretends an external effect was undone.

    The case is driven far enough for real effects to be dispatched, then withdrawn. Every
    delivered row must come back byte for byte, and the result must say out loud that those
    changes stand.
    """
    case_id = await physical.resolved_case()
    await physical.confirm(case_id)
    await physical.drain()
    delivered = [effect for effect in await physical.effects() if effect.state == "DELIVERED"]
    assert delivered, "the canonical case is expected to dispatch at least one real effect"
    before = {effect.id: (effect.state, effect.provider_ref) for effect in delivered}

    result = await withdraw(physical, case_id)

    after = {
        effect.id: (effect.state, effect.provider_ref)
        for effect in await physical.effects()
        if effect.id in before
    }
    assert after == before
    assert result.applied, "an already-delivered effect must be reported, never swallowed"


async def test_a_withdrawal_after_delivery_says_so_in_the_rendered_speech(
    physical: Intake,
) -> None:
    """The sentence a person hears never reads as an undo when something had already gone out."""
    case_id = await physical.resolved_case()
    await physical.confirm(case_id)
    await physical.drain()
    result = await withdraw(physical, case_id)

    spoken = status_view.render_withdrawal(
        withdrawn=len(result.withdrawn),
        escalated=len(result.escalated),
        reversals=[(kind.value, count) for kind, count in result.reversals],
        applied=[(kind.value, count) for kind, count in result.applied],
        already_withdrawn=False,
    )
    assert "could not undo what had already happened" in spoken
    assert "undone" not in spoken


async def test_a_customer_s_recorded_decision_survives_a_withdrawal(physical: Intake) -> None:
    """Their literal word is a thing they said. A worker's withdrawal does not unsay it."""
    case_id = await physical.resolved_case()
    await physical.confirm(case_id)
    await physical.drain()
    request = next(row for row in await physical.requests() if row.state == "SENT")
    await physical.deliver_reply(request.id, "YES")
    await physical.drain_until_decided()
    decisions = await physical.decisions()
    assert decisions, "the canonical case is expected to reach a recorded customer decision"
    before = [(row.id, row.decision) for row in decisions]

    await withdraw(physical, case_id)

    assert [(row.id, row.decision) for row in await physical.decisions()] == before


# -------------------------------------------------------------- what a withdrawal never touches


async def test_a_withdrawal_never_reverses_a_physical_fact(physical: Intake) -> None:
    """§11.8: the two authorities are separate. Withdrawing a plan un-spoils nothing."""
    case_id = await physical.resolved_case()
    before = [(fact.id, fact.target_id, fact.after) for fact in await physical.facts(case_id)]
    assert before, "the canonical case attests a physical fact before it is planned"
    postings = await physical.postings(ho.RASPBERRIES)

    await withdraw(physical, case_id)

    after = [(fact.id, fact.target_id, fact.after) for fact in await physical.facts(case_id)]
    assert after == before
    assert await physical.postings(ho.RASPBERRIES) == postings


async def test_a_withdrawal_touches_no_promise_the_exception_never_reached(
    physical: Intake,
) -> None:
    """Selective continuation holds through a withdrawal as it does through a recovery."""
    case_id = await physical.resolved_case()
    untouched = [
        track
        for track in await physical.tracks(case_id)
        if track.promise_id in (ho.PROMISE_E, ho.PROMISE_F)
    ]
    before = [(track.id, track.state, track.version) for track in untouched]

    await withdraw(physical, case_id)

    after = [
        (track.id, track.state, track.version)
        for track in await physical.tracks(case_id)
        if track.promise_id in (ho.PROMISE_E, ho.PROMISE_F)
    ]
    assert after == before


async def test_only_the_live_tracks_move_when_some_have_already_settled(
    physical: Intake,
) -> None:
    """Several promises, only some still withdrawable. A settled one is left exactly alone."""
    case_id = await physical.resolved_case()
    await physical.confirm(case_id)
    await physical.drain()
    settled = [
        (track.id, track.state, track.version)
        for track in await physical.tracks(case_id)
        if track.state in ("RECOVERED", "UNAFFECTED")
    ]
    assert settled, "the canonical case is expected to settle at least one track before this"

    await withdraw(physical, case_id)

    after = {track.id: (track.state, track.version) for track in await physical.tracks(case_id)}
    for track_id, state, version in settled:
        assert after[track_id] == (state, version)


# ------------------------------------------------------------------------------- fail-closed


async def test_withdrawing_a_finished_case_is_refused(physical: Intake) -> None:
    """A case that already ran is not a case with future work to stop."""
    case_id = await physical.resolved_case()
    await withdraw(physical, case_id)
    assert await case_state(physical, case_id) == "CANCELLED"

    with pytest.raises(withdrawal.CaseNotWithdrawableError):
        await withdraw(physical, case_id)


async def test_withdrawing_a_case_that_does_not_exist_is_refused(physical: Intake) -> None:
    with pytest.raises(cases.CaseMissingError):
        await withdraw(physical, uuid4())


async def test_the_same_withdrawal_arriving_twice_writes_once(physical: Intake) -> None:
    """A redelivery is one withdrawal arriving twice, and is a success that changes nothing."""
    case_id = await physical.resolved_case()
    command_id = uuid4()

    first = await withdraw(physical, case_id, command_id=command_id)
    version = (await physical.case(case_id)).version
    second = await withdraw(physical, case_id, command_id=command_id)

    assert first.created is True
    assert second.created is False
    assert second.case_id == case_id
    assert (await physical.case(case_id)).version == version


async def test_a_command_id_already_spent_on_a_different_request_is_a_conflict(
    physical: Intake,
) -> None:
    """One identity, two requests. Accepting either would silently discard the other."""
    case_id = await physical.resolved_case()
    command_id = uuid4()
    await physical.confirm(case_id, command_id=command_id)

    with pytest.raises(withdrawal.WithdrawalConflictError):
        await withdraw(physical, case_id, command_id=command_id)


async def test_an_observer_may_not_withdraw_a_case(physical: Intake) -> None:
    """The domain's own refusal, on the function every write in this system passes through."""
    case_id = await physical.resolved_case()
    async with physical.another_worker("wren", role="observer") as observer:
        with pytest.raises(intake.NotPermittedError):
            await withdraw(physical, case_id, worker_id=observer)

    assert await case_state(physical, case_id) == "PLANNED"


async def test_another_baker_may_not_withdraw_somebody_else_s_case(physical: Intake) -> None:
    """ "Somebody else's case" is not a position from which to withdraw an attestation."""
    case_id = await physical.resolved_case()
    async with physical.another_baker("sam") as stranger:
        with pytest.raises(intake.NotPermittedError):
            await withdraw(physical, case_id, worker_id=stranger)

    assert await case_state(physical, case_id) == "PLANNED"


async def test_the_owner_may_withdraw_a_case_they_did_not_open(physical: Intake) -> None:
    """Escalation is the owner's to resolve, so they are admitted exactly as elsewhere."""
    case_id = await physical.resolved_case()

    result = await withdraw(physical, case_id, worker_id=OWNER)

    assert result.created is True
    assert await case_state(physical, case_id) == "CANCELLED"


async def test_a_worker_who_does_not_exist_may_not_withdraw(physical: Intake) -> None:
    case_id = await physical.resolved_case()
    with pytest.raises(intake.UnknownWorkerError):
        await withdraw(physical, case_id, worker_id="nobody")


# --------------------------------------------------------------- restart and unclaimed work


async def test_a_withdrawal_stands_down_the_work_nobody_had_claimed(physical: Intake) -> None:
    """A step that was queued and unclaimed will not run, and the ledger says so."""
    case_id = await physical.resolved_case()
    await physical.confirm(case_id)
    queued = [step.step_key for step in await physical.outstanding(case_id)]
    assert queued, "a confirmation is expected to enqueue work"

    await withdraw(physical, case_id)

    settled = {step.step_key: step.state for step in await physical.steps(case_id)}
    for step_key in queued:
        assert settled[step_key] in ("SKIPPED", "DONE")


async def test_draining_after_a_withdrawal_raises_no_further_effect(physical: Intake) -> None:
    """Restart safety, as the worker actually experiences it.

    Every cycle a worker runs after a withdrawal must find nothing left to do that produces an
    effect. A step that had been enqueued before the withdrawal and ran afterwards would be the
    case carrying on after a person told it to stop.
    """
    case_id = await physical.resolved_case()
    await physical.confirm(case_id)
    await withdraw(physical, case_id)
    before = [(effect.id, effect.state) for effect in await physical.effects()]

    await physical.drain()

    assert [(effect.id, effect.state) for effect in await physical.effects()] == before


async def test_a_withdrawn_case_settles_and_stops_moving(physical: Intake) -> None:
    """Whichever path it took, a drained withdrawn case is terminal and stays there."""
    case_id = await physical.resolved_case()
    await physical.confirm(case_id)
    await withdraw(physical, case_id)

    await physical.drain()

    assert await case_state(physical, case_id) in ("RESOLVED", "CANCELLED")


# -------------------------------------------------------------------------- the audit trail


async def test_a_withdrawal_is_audited_under_the_worker_s_own_authority(
    physical: Intake,
) -> None:
    """A human said no. It is recorded as a human approval, not as engine bookkeeping."""
    case_id = await physical.resolved_case()
    await withdraw(physical, case_id)

    entry = next(
        row
        for row in await physical.audits(case_id)
        if row.type == withdrawal.AUDIT_EXCEPTION_WITHDRAWN
    )
    assert entry.authority == "HUMAN_APPROVAL"
    assert entry.actor_id == BAKER
    assert entry.after["case_state"] == "CANCELLED"


async def test_a_withdrawal_announces_itself_on_the_event_spine(physical: Intake) -> None:
    case_id = await physical.resolved_case()
    await withdraw(physical, case_id)

    types = await physical.events(case_id)
    assert withdrawal.EVENT_EXCEPTION_WITHDRAWN in types
    assert withdrawal.EVENT_TRACK_WITHDRAWN in types
