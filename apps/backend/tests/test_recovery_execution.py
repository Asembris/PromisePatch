"""Plan confirmation and the recovery saga, against a real database and the real worker.

The shape of these tests is the shape of the guarantee, and it has three halves.

The first is **what a worker's yes means**. It authorises the recoveries the customer's own
constraints already permit, and nothing else: A executes, B does not, and no amount of
confirming changes that. The tests assert the *absence* of work for B as hard as they assert
its presence for A, because an engine that quietly applied a visible change nobody agreed to
would pass every test that only looked at A.

The second is **crash safety at every persistence boundary**. Each one is provoked
deterministically with :mod:`promisepatch.domain.crash` -- never with a sleep, never with a
handled error -- and then recovered from by a *fresh* worker, because a recovery that only
works in the process that crashed is not a recovery. The central one is the uncertain window:
the provider applied the amendment and the process died before the acknowledgement committed.
Two transport calls, one logical effect, one recovered track.

The third is **that nothing else moved**. The order book is read before and compared after,
and the only differences permitted are the ones the frozen architecture names.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from uuid import UUID, uuid4

import pytest
from _intake_support import (
    BAKER,
    OWNER,
    RASPBERRY_ONLY,
    Intake,
)
from _intake_support import physical as physical

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import Classification, RuleId
from promisepatch.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    OutboxMessage,
    RecipeVersion,
)
from promisepatch.db.types import TERMINAL_TRACK_STATES
from promisepatch.db.uow import Actor
from promisepatch.domain import cases, crash, intake, outbox, recovery, steps, withdrawal
from promisepatch.domain.adapters import FakeEffectAdapter, ProviderBehaviour
from promisepatch.domain.model import StepResult

pytestmark = pytest.mark.integration

A, B, C, D, E, F = (
    ho.PROMISE_A,
    ho.PROMISE_B,
    ho.PROMISE_C,
    ho.PROMISE_D,
    ho.PROMISE_E,
    ho.PROMISE_F,
)

RASPBERRY_ALMOND_V3 = ho.RAC_V3
RASPBERRY_ALMOND_V4 = ho.RAC_V4

TASK_C = f"task-{ho.LINE_C}"
TASK_D = f"task-{ho.LINE_D}"
"""The kitchen work behind the two blocked promises. One task per line, by construction."""

UNTOUCHED = (B, C, D, E, F)
"""Every promise in the canonical case except the one a worker's yes actually authorises."""


# ------------------------------------------------------------------------------------ driving


async def planned_case(intake_fixture: Intake) -> UUID:
    """The canonical path, driven all the way to ``PLANNED`` by the real worker."""
    opened = await intake_fixture.report()
    await intake_fixture.drain()
    await intake_fixture.answer(opened.case_id, RASPBERRY_ONLY)
    await intake_fixture.drain()
    return opened.case_id


async def confirmed_case(intake_fixture: Intake, *, ask: bool = False) -> UUID:
    """The same path, plus Maya's yes, and no worker run yet.

    A confirmation enqueues two independent pieces of work: A's amendment and the ask that goes
    to B's customer. They are created in one transaction, so nothing fixes which the worker
    claims first, and this file is about the amendment. ``ask=False`` therefore defers the
    approval work, which is what makes a test that runs a single worker cycle a test about the
    step it names rather than about a random UUID.

    ``ask=True`` leaves both runnable, for the handful of tests here whose subject is precisely
    that a confirmation authorises the asking as well.
    """
    case_id = await planned_case(intake_fixture)
    await intake_fixture.confirm(case_id)
    if not ask:
        await intake_fixture.defer_approvals(case_id)
    return case_id


async def track_of(intake_fixture: Intake, case_id: UUID, promise_id: str) -> Any:
    row = await intake_fixture.track(case_id, promise_id)
    assert row is not None
    return row


async def states(intake_fixture: Intake, case_id: UUID) -> dict[str, str]:
    return {track.promise_id: track.state for track in await intake_fixture.tracks(case_id)}


async def only_amendment(intake_fixture: Intake) -> Any:
    """The one order-system effect the canonical case produces. Its uniqueness is the assertion.

    Scoped to amendments rather than to the whole outbox, because the canonical case also sends
    one message -- to B's customer, asking them. Asking somebody is not amending their order,
    and conflating the two would make "exactly one order was touched" untestable.
    """
    effects = [
        effect
        for effect in await intake_fixture.effects()
        if effect.kind == recovery.EFFECT_ORDER_AMEND
    ]
    assert len(effects) == 1
    return effects[0]


async def amendments_for(intake_fixture: Intake, track_id: Any) -> list[Any]:
    """Order-system effects for one track, which is what "this promise moved" means."""
    return [
        effect
        for effect in await intake_fixture.effects_for(track_id)
        if effect.kind == recovery.EFFECT_ORDER_AMEND
    ]


# ------------------------------------------------------------ confirmation: what a yes means


async def test_a_worker_confirmation_moves_the_case_to_executing(physical: Intake) -> None:
    case_id = await planned_case(physical)

    outcome = await physical.confirm(case_id)

    assert outcome.created is True
    assert outcome.state == cases.CASE_EXECUTING
    case = await physical.case(case_id)
    assert case.state == cases.CASE_EXECUTING


async def test_confirmation_enqueues_no_recovery_work_for_the_approval_track(
    physical: Intake,
) -> None:
    """``B`` earns approval work and never recovery work, at the moment of the yes itself."""
    case_id = await confirmed_case(physical)
    track_b = await track_of(physical, case_id, B)

    kinds = {step.kind for step in await physical.steps(case_id) if step.track_id == track_b.id}

    assert kinds == {"REQUEST_APPROVAL"}
    assert recovery.STEP_APPLY_RECOVERY not in kinds
    assert await physical.rows_of(ApprovalRequest) == []
    assert await physical.effects() == []


async def test_confirmation_enqueues_execution_work_only_for_the_automatic_track(
    physical: Intake,
) -> None:
    """One step, for A, and the step keys say which track each piece of work belongs to."""
    case_id = await confirmed_case(physical)
    track_a = await track_of(physical, case_id, A)

    applying = [
        step for step in await physical.steps(case_id) if step.kind == recovery.STEP_APPLY_RECOVERY
    ]

    assert [step.step_key for step in applying] == [recovery.apply_step_key(track_a.id)]
    assert applying[0].track_id == track_a.id
    assert applying[0].state == "PENDING"


async def test_confirmation_leaves_every_track_in_the_state_its_classification_earned(
    physical: Intake,
) -> None:
    """The frozen §13.4 postures, immediately after a yes and before any execution.

    ``B`` is the one that matters. It stays ``PENDING``: the customer has not been asked, so
    there is nothing for it to be waiting for, and a track that claimed to be waiting would be
    claiming an approval request that does not exist.
    """
    case_id = await confirmed_case(physical)

    assert await states(physical, case_id) == {
        A: recovery.TRACK_PENDING,
        B: recovery.TRACK_PENDING,
        C: recovery.TRACK_ESCALATED,
        D: recovery.TRACK_ESCALATED,
        E: "UNAFFECTED",
        F: "UNAFFECTED",
    }


async def test_confirmation_never_authorises_the_approval_required_track(
    physical: Intake,
) -> None:
    """The hard invariant: a worker's yes is not the customer's.

    What a confirmation authorises for ``B`` is *asking*. The customer is contacted and the
    track waits for their answer, and until that answer arrives no amendment is enqueued and
    nothing about their order moves. This is the assertion that would fail if confirmation were
    ever widened into blanket authority.
    """
    case_id = await confirmed_case(physical, ask=True)
    track_b = await track_of(physical, case_id, B)
    await physical.drain(limit=40)

    assert track_b.classification == Classification.APPROVAL_REQUIRED.value
    assert (await track_of(physical, case_id, B)).state == "WAITING_FOR_CUSTOMER"
    amendments = [
        effect
        for effect in await physical.effects_for(track_b.id)
        if effect.kind == recovery.EFFECT_ORDER_AMEND
    ]
    assert amendments == []
    assert await physical.rows_of(ApprovalDecision) == []


async def test_blocked_tracks_escalate_and_their_kitchen_work_is_held(
    physical: Intake,
) -> None:
    """§13.5: the one write a blocked track performs, so nobody starts a cake that cannot end.

    Only the lines the track's own evidence reaches. A hold on work the exception never
    touched would be the selectivity failure the spec forbids, dressed up as caution.
    """
    case_id = await planned_case(physical)
    before = await physical.tasks()

    await physical.confirm(case_id)

    after = await physical.tasks()
    moved = {task: after[task] for task in after if before[task] != after[task]}
    assert set(moved) == {TASK_C, TASK_D}
    assert all(state == "HELD" and holder == case_id for state, holder in moved.values())


async def test_a_blocked_escalation_puts_the_case_on_the_owners_desk(physical: Intake) -> None:
    case_id = await planned_case(physical)
    assert (await physical.case(case_id)).needs_owner_attention is False

    await physical.confirm(case_id)

    assert (await physical.case(case_id)).needs_owner_attention is True


async def test_unaffected_tracks_are_untouched_by_a_confirmation(physical: Intake) -> None:
    """E and F were considered and dismissed, and a yes does not reconsider them."""
    case_id = await planned_case(physical)
    before = {track.promise_id: track for track in await physical.tracks(case_id)}

    await physical.confirm(case_id)
    after = {track.promise_id: track for track in await physical.tracks(case_id)}

    for promise_id in (E, F):
        assert after[promise_id].state == "UNAFFECTED"
        assert after[promise_id].version == before[promise_id].version


# ------------------------------------------------- the plan window: a wait with a limit on it


async def plan_deadline(intake_fixture: Intake, case_id: UUID) -> Any:
    """This case's live plan deadline, or ``None`` if it is not waiting for a confirmation."""
    live = [
        timer
        for timer in await intake_fixture.timers()
        if timer.kind == cases.TIMER_PLAN_AUTO_ESCALATION
        and timer.subject_id == str(case_id)
        and timer.fired_at is None
    ]
    assert len(live) <= 1, "a case waits for one confirmation at a time"
    return live[0] if live else None


async def test_a_planned_case_arms_the_deadline_on_its_own_wait(physical: Intake) -> None:
    """§14.1 bounds ``PLANNED`` at ten minutes, and the bound is a row rather than a promise."""
    case_id = await planned_case(physical)

    timer = await plan_deadline(physical, case_id)

    assert timer is not None
    assert timer.subject_type == "CASE"
    assert timer.due_at > (await physical.case(case_id)).updated_at


async def test_a_plan_deadline_that_has_not_passed_changes_nothing(physical: Intake) -> None:
    """The wait is real. Running the worker is not what ends it -- the ten minutes are."""
    case_id = await planned_case(physical)
    before = await physical.tasks()

    await physical.drain(limit=30)

    assert (await physical.case(case_id)).state == cases.CASE_PLANNED
    assert await physical.tasks() == before
    assert await physical.effects() == []


async def test_a_plan_nobody_confirms_reaches_the_owner_with_its_kitchen_work_held(
    physical: Intake,
) -> None:
    """The ending §14.1 names, and the one an unbounded wait never arrived at.

    Every live track goes, because what expired is the plan rather than any one track of it,
    and each takes §13.5's hold with it: the kitchen is not left making a cake whose recovery
    this case can no longer authorise.
    """
    case_id = await planned_case(physical)
    live = {
        track.promise_id for track in await physical.tracks(case_id) if track.state == "PENDING"
    }

    assert await physical.close_plan_window(case_id) is True
    await physical.drain(limit=40)

    after = await states(physical, case_id)
    assert live == {A, B, C, D}
    assert all(after[promise_id] == recovery.TRACK_ESCALATED for promise_id in live)
    held = await physical.tasks()
    for line in (ho.LINE_A, ho.LINE_B, ho.LINE_C, ho.LINE_D):
        assert held[f"task-{line}"] == ("HELD", case_id)
    case = await physical.case(case_id)
    assert case.needs_owner_attention is True
    assert case.state == cases.CASE_RESOLVED


async def test_an_unconfirmed_plan_is_never_carried_out(physical: Intake) -> None:
    """The gate is not what this removes. A plan nobody read is still never executed.

    The escalation ends the waiting and authorises nothing: no order is amended, no customer is
    asked anything, and the promises the exception never reached are not reconsidered.
    """
    case_id = await planned_case(physical)
    before = {track.promise_id: track for track in await physical.tracks(case_id)}

    await physical.close_plan_window(case_id)
    await physical.drain(limit=40)

    assert await physical.effects() == []
    assert await physical.requests() == []
    after = {track.promise_id: track for track in await physical.tracks(case_id)}
    for promise_id in (E, F):
        assert after[promise_id].state == "UNAFFECTED"
        assert after[promise_id].version == before[promise_id].version


async def test_a_confirmation_ends_the_deadline_it_is_the_answer_to(physical: Intake) -> None:
    """A yes that arrives after the ten minutes have elapsed is still a yes.

    The deadline is cancelled inside the confirming transaction, so a worker who answers a
    moment too late gets their plan executed rather than an escalation of it -- and the case is
    never escalated by a deadline for a wait that has ended.
    """
    case_id = await planned_case(physical)
    assert await physical.close_plan_window(case_id) is True

    await physical.confirm(case_id)
    await physical.drain(limit=40)

    assert await plan_deadline(physical, case_id) is None
    assert (await states(physical, case_id))[A] == recovery.TRACK_RECOVERED


async def test_an_auto_escalation_that_runs_twice_escalates_once(physical: Intake) -> None:
    """A redelivered deadline is a deadline for a plan the case has already moved past."""
    case_id = await planned_case(physical)
    await physical.close_plan_window(case_id)
    await physical.drain(limit=40)
    escalation = next(
        step for step in await physical.steps(case_id) if step.kind == recovery.STEP_ESCALATE_PLAN
    )
    held = await physical.tasks()
    tracks = {track.promise_id: track.version for track in await physical.tracks(case_id)}

    await physical.requeue(escalation.id)
    await physical.drain(limit=40)

    replayed = await physical.step_named(case_id, escalation.step_key)
    assert replayed.result["outcome"] == "NOT_APPLICABLE"
    assert await physical.tasks() == held
    assert {track.promise_id: track.version for track in await physical.tracks(case_id)} == tracks


async def test_confirming_a_case_that_is_not_planned_is_rejected(physical: Intake) -> None:
    """A yes is an answer to a question, and an unplanned case has not asked one."""
    opened = await physical.report()
    await physical.drain_intake(opened.case_id)

    with pytest.raises(recovery.PlanNotConfirmableError):
        await physical.confirm(opened.case_id)


async def test_a_second_confirmation_under_a_new_command_is_rejected(physical: Intake) -> None:
    """The case is ``EXECUTING`` by then, and confirming it again would authorise nothing."""
    case_id = await confirmed_case(physical)

    with pytest.raises(recovery.PlanNotConfirmableError):
        await physical.confirm(case_id)


async def test_an_unknown_worker_cannot_confirm(physical: Intake) -> None:
    case_id = await planned_case(physical)

    with pytest.raises(intake.UnknownWorkerError):
        await physical.confirm(case_id, worker_id="nobody")


async def test_a_worker_who_did_not_open_the_case_cannot_confirm_it(physical: Intake) -> None:
    case_id = await planned_case(physical)

    async with physical.another_baker() as stranger:
        with pytest.raises(intake.NotPermittedError):
            await physical.confirm(case_id, worker_id=stranger)


async def test_the_owner_may_confirm_any_case(physical: Intake) -> None:
    """Escalation is the owner's to resolve, so a case is never theirs to be locked out of."""
    case_id = await planned_case(physical)

    outcome = await physical.confirm(case_id, worker_id=OWNER)

    assert outcome.created is True


# ---------------------------------------------------------------- confirmation: idempotency


async def test_a_redelivered_confirmation_is_the_same_confirmation(physical: Intake) -> None:
    """One case, one set of steps, one confirmation -- decided by a row, not by timing.

    Both deliveries carry the plan identity that was read once, because that is what a
    redelivery is: the identical request arriving twice. A caller that re-read the plan in
    between would be sending a *different* request under the same name, which is the conflict
    two tests below.
    """
    case_id = await planned_case(physical)
    command_id = uuid4()
    plan_id = await physical.plan_id(case_id)

    first = await physical.confirm(case_id, command_id=command_id, plan_id=plan_id)
    second = await physical.confirm(case_id, command_id=command_id, plan_id=plan_id)

    assert first.created is True
    assert second.created is False
    assert second.state == cases.CASE_EXECUTING
    applying = [
        step for step in await physical.steps(case_id) if step.kind == recovery.STEP_APPLY_RECOVERY
    ]
    assert len(applying) == 1


async def test_two_concurrent_deliveries_of_one_confirmation_produce_one_effect(
    physical: Intake,
) -> None:
    """The mandatory concurrency case, and the result comes from the database, not from luck.

    One confirmation, however many times it is delivered, produces one amendment and one ask --
    never two of either. The count is what a second accepted confirmation would break.
    """
    case_id = await planned_case(physical)
    command_id = uuid4()
    plan_id = await physical.plan_id(case_id)

    outcomes = await asyncio.gather(
        physical.confirm(case_id, command_id=command_id, plan_id=plan_id),
        physical.confirm(case_id, command_id=command_id, plan_id=plan_id),
    )

    assert sorted(outcome.created for outcome in outcomes) == [False, True]
    await physical.drain(limit=40)
    effects = await physical.effects()
    assert [effect.kind for effect in effects].count(recovery.EFFECT_ORDER_AMEND) == 1
    assert len(effects) == 2
    assert len(await physical.rows_of(OutboxMessage)) == 2


async def test_a_confirmation_cannot_name_who_approved_the_plan(physical: Intake) -> None:
    """The old way two confirmations differed is gone, and gone is stronger than refused.

    This used to be the same command id carrying two different *workers*, refused as a conflict.
    It is no longer expressible: a confirmation carries out the approval a person recorded on a
    channel this system authenticated them on, and there is no parameter through which a caller
    states who that was. A conflict is a refusal, and a missing parameter is not a door.
    """
    assert "worker_id" not in inspect.signature(recovery.confirm_plan).parameters
    assert "approval_id" in inspect.signature(recovery.confirm_plan).parameters


async def test_the_same_command_id_carrying_a_different_request_is_a_conflict(
    physical: Intake,
) -> None:
    """Two different statements claiming one identity. Refused, rather than one silently won.

    The two statements are a withdrawal and a confirmation, which is the sharpest pair available:
    one stops this case's future work and the other authorises it, so silently treating the
    second as a redelivery of the first would be the worst possible way to resolve a collision.
    The approval is recorded first, so what the confirmation lacks is the command id and nothing
    else.
    """
    case_id = await planned_case(physical)
    approval = await physical.approve(case_id)
    command_id = uuid4()
    await withdrawal.withdraw_exception(
        physical.database, case_id=case_id, command_id=command_id, worker_id=BAKER
    )

    with pytest.raises(recovery.ConfirmationConflictError):
        await physical.confirm(
            case_id,
            command_id=command_id,
            plan_id=approval.plan_id,
            approval_id=approval.id,
        )


async def test_the_confirmation_row_records_who_confirmed_and_what_it_authorised(
    physical: Intake,
) -> None:
    """Provenance is persisted, not inferred from the audit ledger alone."""
    case_id = await planned_case(physical)
    command_id = uuid4()
    await physical.confirm(case_id, command_id=command_id)
    track_a = await track_of(physical, case_id, A)

    row = await physical.step_named(case_id, recovery.confirm_step_key(command_id))

    assert row.id == command_id
    assert row.kind == recovery.STEP_CONFIRM_PLAN
    assert row.state == "DONE"
    assert row.request_hash
    assert row.result["confirmed_by"] == BAKER
    assert row.result["applying"] == [str(track_a.id)]


# ------------------------------------------------------------------ execution: the canonical A


async def test_the_canonical_case_recovers_a_and_leaves_everything_else_alone(
    physical: Intake,
) -> None:
    """The whole slice, in one run of the real worker against a real database."""
    case_id = await confirmed_case(physical, ask=True)
    adapter = FakeEffectAdapter()

    await physical.drain(worker=physical.worker(adapter=adapter), limit=30)

    assert await states(physical, case_id) == {
        A: recovery.TRACK_RECOVERED,
        B: "WAITING_FOR_CUSTOMER",
        C: recovery.TRACK_ESCALATED,
        D: recovery.TRACK_ESCALATED,
        E: "UNAFFECTED",
        F: "UNAFFECTED",
    }
    # Two effects: A's amendment, and the message asking B's customer. The order system heard
    # about A only, which is the whole of "a worker's yes moved exactly one order".
    assert adapter.effect_count == 2
    assert [call.kind for call in adapter.attempts].count(recovery.EFFECT_ORDER_AMEND) == 1
    # Waiting, not resolved: B's customer has been asked and has not answered, and the
    # authority that will answer is theirs alone.
    assert (await physical.case(case_id)).state == cases.CASE_WAITING
    assert await physical.rows_of(ApprovalDecision) == []


async def test_the_effect_names_the_exact_pre_authored_version_planning_chose(
    physical: Intake,
) -> None:
    """Raspberry Almond v3 to the variant a human authored, and nothing derived at runtime."""
    case_id = await confirmed_case(physical)
    track_a = await track_of(physical, case_id, A)
    chosen = next(
        option
        for option in await physical.options(track_a.id)
        if option.id == track_a.chosen_option_id
    )
    adapter = FakeEffectAdapter()

    await physical.drain(worker=physical.worker(adapter=adapter), limit=30)

    assert chosen.from_version_id == RASPBERRY_ALMOND_V3
    assert chosen.to_version_id == RASPBERRY_ALMOND_V4
    delivered = adapter.attempts[0]
    assert delivered.kind == recovery.EFFECT_ORDER_AMEND
    assert delivered.payload["option_id"] == str(chosen.id)
    assert delivered.payload["from_version_id"] == RASPBERRY_ALMOND_V3
    assert delivered.payload["to_version_id"] == RASPBERRY_ALMOND_V4


async def test_the_option_is_read_back_at_execution_and_never_selected_again(
    physical: Intake,
) -> None:
    """The applied option is the row planning chose, by id, and the audit says so."""
    case_id = await confirmed_case(physical)
    track_a = await track_of(physical, case_id, A)
    await physical.drain(limit=30)

    applied = next(
        row for row in await physical.audits(case_id) if row.type == recovery.AUDIT_RECOVERY_APPLIED
    )

    assert applied.after["option_id"] == str(track_a.chosen_option_id)
    assert applied.rule_id == RuleId.R_PREAPPROVED.value


async def test_the_track_reaches_applying_only_once_the_effect_is_durably_queued(
    physical: Intake,
) -> None:
    """One transaction: there is no committed state in which one exists without the other."""
    case_id = await confirmed_case(physical)
    track_a = await track_of(physical, case_id, A)
    adapter = FakeEffectAdapter()
    worker = physical.worker(adapter=adapter)

    with crash.arm(crash.AFTER_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await worker.run_once()

    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_APPLYING
    queued = await physical.effects_for(track_a.id)
    assert [effect.state for effect in queued] == ["PENDING"]
    assert adapter.call_count == 0


async def test_no_provider_is_called_before_the_effect_commits(physical: Intake) -> None:
    """A death inside the applying transaction leaves no track state and no effect at all."""
    case_id = await confirmed_case(physical)
    adapter = FakeEffectAdapter()
    worker = physical.worker(adapter=adapter)

    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await worker.run_once()

    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_PENDING
    assert await physical.effects() == []
    assert adapter.call_count == 0


async def test_the_finalized_track_carries_the_providers_own_reference(physical: Intake) -> None:
    case_id = await confirmed_case(physical)
    adapter = FakeEffectAdapter()
    await physical.drain(worker=physical.worker(adapter=adapter), limit=30)

    effect = await only_amendment(physical)
    completed = next(
        row
        for row in await physical.audits(case_id)
        if row.type == recovery.AUDIT_RECOVERY_COMPLETED
    )

    applied = adapter.effect_for(effect.idempotency_key)
    assert applied is not None
    assert effect.state == "DELIVERED"
    assert effect.provider_ref == applied.provider_ref
    assert completed.after["provider_ref"] == effect.provider_ref


async def test_nothing_but_a_amends_an_order(physical: Intake) -> None:
    """The mandatory zero-effect invariant, asserted per track rather than in aggregate.

    ``B`` is allowed exactly one effect and it is a question, not a change: the message that
    asks its customer. Every other promise the exception reached, and every promise it did not,
    has nothing outbound at all.
    """
    case_id = await confirmed_case(physical, ask=True)
    await physical.drain(limit=40)
    tracks = {track.promise_id: track for track in await physical.tracks(case_id)}

    for promise_id in UNTOUCHED:
        assert await amendments_for(physical, tracks[promise_id].id) == []
    for promise_id in (C, D, E, F):
        assert await physical.effects_for(tracks[promise_id].id) == []
    assert len(await physical.rows_of(OutboxMessage)) == 2


# -------------------------------------------------------------------------- the effect's identity


async def test_the_idempotency_key_is_derived_from_persisted_identity_alone(
    physical: Intake,
) -> None:
    """Track, option, order version. Nothing that changes between two attempts at one recovery."""
    case_id = await confirmed_case(physical)
    track_a = await track_of(physical, case_id, A)
    order = await physical.snapshot()
    await physical.drain(limit=30)

    effect = await only_amendment(physical)

    assert effect.idempotency_key == recovery.amend_idempotency_key(
        track_id=track_a.id,
        option_id=track_a.chosen_option_id,
        order_version=order.orders[ho.ORDER_A].external_version,
    )


async def test_one_logical_recovery_keeps_one_key_across_every_retry(physical: Intake) -> None:
    """Two transport calls under one key, because the provider lost the first answer."""
    case_id = await confirmed_case(physical)
    adapter = FakeEffectAdapter(script=[ProviderBehaviour.APPLY_THEN_LOSE_RESPONSE])
    worker = physical.worker(adapter=adapter)

    await worker.run_once()
    effect = await only_amendment(physical)
    await physical.make_effect_due(effect.id)
    await physical.drain(worker=worker, limit=30)

    amend_calls = [
        attempt for attempt in adapter.attempts if attempt.idempotency_key == effect.idempotency_key
    ]
    assert len(amend_calls) == 2
    assert adapter.effect_for(effect.idempotency_key) is not None
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED


async def test_the_database_refuses_a_second_effect_under_one_key(physical: Intake) -> None:
    """Uniqueness, not care, is what stops one recovery from becoming two amendments."""
    await confirmed_case(physical)
    await physical.drain(limit=30)
    effect = await only_amendment(physical)

    async with physical.database.begin() as connection:
        with pytest.raises(outbox.DuplicateEffectError):
            await outbox.enqueue_effect(
                connection,
                kind=recovery.EFFECT_ORDER_AMEND,
                payload=dict(effect.payload),
                idempotency_key=effect.idempotency_key,
            )


async def test_a_live_lease_cannot_be_claimed_by_a_second_dispatcher(physical: Intake) -> None:
    """One dispatcher owns a message until its lease runs out, and no second one may send it."""
    await confirmed_case(physical)
    with crash.arm(crash.AFTER_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.worker().run_once()
    assert (await only_amendment(physical)).state == "PENDING"

    first = await outbox.claim_effect(physical.database, worker="dispatcher-a")
    second = await outbox.claim_effect(physical.database, worker="dispatcher-b")

    assert first is not None
    assert second is None
    assert (await only_amendment(physical)).lease_owner == "dispatcher-a"


# ------------------------------------------------------------------ provider failure semantics


async def test_a_timeout_before_the_provider_applied_keeps_the_effect_retryable(
    physical: Intake,
) -> None:
    """Nothing happened outside, so the track is not recovered and the key is unchanged."""
    case_id = await confirmed_case(physical)
    adapter = FakeEffectAdapter(script=[ProviderBehaviour.TIMEOUT_BEFORE_APPLYING])
    worker = physical.worker(adapter=adapter)

    await worker.run_once()

    effect = await only_amendment(physical)
    assert effect.state == "PENDING"
    assert effect.next_attempt_at is not None
    assert adapter.effect_count == 0
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_APPLYING


async def test_a_recovered_timeout_finishes_the_recovery_under_the_same_key(
    physical: Intake,
) -> None:
    case_id = await confirmed_case(physical)
    adapter = FakeEffectAdapter(script=[ProviderBehaviour.TIMEOUT_BEFORE_APPLYING])
    worker = physical.worker(adapter=adapter)
    await worker.run_once()
    first_key = (await only_amendment(physical)).idempotency_key

    await physical.make_effect_due((await only_amendment(physical)).id)
    await physical.drain(worker=worker, limit=30)

    assert (await only_amendment(physical)).idempotency_key == first_key
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED
    assert adapter.effect_count == 1


async def test_a_terminal_rejection_escalates_the_track_rather_than_pretending(
    physical: Intake,
) -> None:
    """§11.6: the case carries on with its other tracks and never reports an unobserved success."""
    case_id = await confirmed_case(physical)
    adapter = FakeEffectAdapter(script=[ProviderBehaviour.REJECT])

    await physical.drain(worker=physical.worker(adapter=adapter), limit=30)

    effect = await only_amendment(physical)
    assert effect.state == "FAILED"
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_ESCALATED
    assert (await physical.case(case_id)).needs_owner_attention is True
    abandoned = next(
        row
        for row in await physical.audits(case_id)
        if row.type == recovery.AUDIT_RECOVERY_ABANDONED
    )
    assert abandoned.after["reason"] == recovery.ESCALATION_DOWNSTREAM_UNAVAILABLE


async def test_a_terminally_failed_recovery_never_becomes_recovered(physical: Intake) -> None:
    case_id = await confirmed_case(physical)
    adapter = FakeEffectAdapter(script=[ProviderBehaviour.REJECT])

    await physical.drain(worker=physical.worker(adapter=adapter), limit=30)

    assert (await track_of(physical, case_id, A)).state != recovery.TRACK_RECOVERED
    assert recovery.EVENT_TRACK_RECOVERED not in await physical.events(case_id)


# --------------------------------------------------------------------------- crash boundaries


async def test_a_death_before_the_confirmation_commits_leaves_the_case_planned(
    physical: Intake,
) -> None:
    case_id = await planned_case(physical)
    before = len(await physical.steps(case_id))

    with crash.arm(crash.BEFORE_CONFIRMATION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.confirm(case_id)

    assert (await physical.case(case_id)).state == cases.CASE_PLANNED
    assert len(await physical.steps(case_id)) == before
    assert await physical.effects() == []
    assert await states(physical, case_id) == {
        A: recovery.TRACK_PENDING,
        B: recovery.TRACK_PENDING,
        C: recovery.TRACK_PENDING,
        D: recovery.TRACK_PENDING,
        E: "UNAFFECTED",
        F: "UNAFFECTED",
    }


async def test_a_death_after_the_confirmation_commits_leaves_work_a_fresh_worker_finishes(
    physical: Intake,
) -> None:
    case_id = await planned_case(physical)

    with crash.arm(crash.AFTER_CONFIRMATION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.confirm(case_id)

    assert (await physical.case(case_id)).state == cases.CASE_EXECUTING
    await physical.drain(worker=physical.worker(identity="fresh"), limit=30)
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED


async def test_a_step_whose_worker_died_after_claiming_is_reclaimed(physical: Intake) -> None:
    """The claim committed and the work never ran. A lease is what makes that recoverable."""
    case_id = await confirmed_case(physical)
    track_a = await track_of(physical, case_id, A)
    step = await physical.step_named(case_id, recovery.apply_step_key(track_a.id))

    with crash.arm(crash.DURING_HANDLER), pytest.raises(crash.WorkerDied):
        await physical.worker(identity="died").run_once()

    await physical.expire_lease(step.id)
    await physical.drain(worker=physical.worker(identity="fresh"), limit=30)
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED


async def test_an_effect_that_survived_a_crash_is_sent_by_the_next_worker(
    physical: Intake,
) -> None:
    """After the enqueue commit and before the send: the row is the whole handover."""
    case_id = await confirmed_case(physical)
    first = FakeEffectAdapter()

    with crash.arm(crash.AFTER_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.worker(adapter=first, identity="died").run_once()

    assert first.call_count == 0
    second = FakeEffectAdapter()
    await physical.drain(worker=physical.worker(adapter=second, identity="fresh"), limit=30)
    assert second.call_count == 1
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED


async def test_a_message_claimed_by_a_dead_dispatcher_is_reclaimed_under_the_same_key(
    physical: Intake,
) -> None:
    """The claim commits before the call, so an uncertain attempt is visible rather than lost."""
    await confirmed_case(physical)
    adapter = FakeEffectAdapter()
    worker = physical.worker(adapter=adapter, identity="died")

    with crash.arm(crash.AFTER_OUTBOX_CLAIM), pytest.raises(crash.WorkerDied):
        await worker.run_once()

    effect = await only_amendment(physical)
    assert effect.state == "IN_FLIGHT"
    assert adapter.call_count == 0

    await physical.expire_effect_lease(effect.id)
    fresh = FakeEffectAdapter()
    await physical.drain(worker=physical.worker(adapter=fresh, identity="fresh"), limit=30)
    assert [attempt.idempotency_key for attempt in fresh.attempts] == [effect.idempotency_key]


async def test_a_provider_effect_applied_before_a_crash_becomes_exactly_one_recovery(
    physical: Intake,
) -> None:
    """The central acceptance proof of this slice.

    The provider accepted the amendment and the process died before the acknowledgement
    committed. Locally the effect is uncertain; outside, it has already happened. A fresh
    worker reclaims the *same row*, presents the *same key*, and the provider -- which honours
    keys -- returns the same reference rather than amending the order twice.

    Two transport calls. One logical external effect. One recovered track.
    """
    case_id = await confirmed_case(physical)
    provider = FakeEffectAdapter()

    with crash.arm(crash.AFTER_EXTERNAL_SUCCESS), pytest.raises(crash.WorkerDied):
        await physical.worker(adapter=provider, identity="died").run_once()

    effect = await only_amendment(physical)
    applied = provider.effect_for(effect.idempotency_key)
    assert applied is not None
    assert effect.state == "IN_FLIGHT"
    assert provider.call_count == 1
    assert provider.effect_count == 1

    await physical.expire_effect_lease(effect.id)
    await physical.drain(worker=physical.worker(adapter=provider, identity="fresh"), limit=30)

    assert provider.call_count == 2
    assert provider.effect_count == 1
    settled = await only_amendment(physical)
    assert settled.idempotency_key == effect.idempotency_key
    assert settled.state == "DELIVERED"
    assert settled.provider_ref == applied.provider_ref
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED


async def test_a_delivered_effect_is_finalized_by_whichever_worker_runs_next(
    physical: Intake,
) -> None:
    """The acknowledgement is durable and the track is still ``APPLYING``. Nothing is lost."""
    case_id = await confirmed_case(physical)
    adapter = FakeEffectAdapter()
    track_a = await track_of(physical, case_id, A)

    await physical.worker(adapter=adapter, identity="first").run_once()

    assert (await only_amendment(physical)).state == "DELIVERED"
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_APPLYING
    finalize = await physical.step_named(case_id, recovery.finalize_step_key(track_a.id))
    assert finalize.state == "PENDING"

    await physical.drain(worker=physical.worker(identity="second"), limit=30)
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED


async def test_running_again_after_finalization_changes_nothing(physical: Intake) -> None:
    case_id = await confirmed_case(physical)
    adapter = FakeEffectAdapter()
    await physical.drain(worker=physical.worker(adapter=adapter), limit=30)
    events_before = await physical.events(case_id)

    await physical.drain(worker=physical.worker(adapter=adapter, identity="again"), limit=10)

    assert adapter.call_count == 1
    assert adapter.effect_count == 1
    assert await physical.events(case_id) == events_before
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED


async def test_a_worker_stopped_mid_recovery_resumes_without_repair(physical: Intake) -> None:
    """The restart proof: stop while ``APPLYING``, start again, and A ends up recovered."""
    case_id = await confirmed_case(physical)

    with crash.arm(crash.AFTER_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.worker(identity="before-restart").run_once()
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_APPLYING

    await physical.drain(worker=physical.worker(identity="after-restart"), limit=30)

    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED
    assert (await only_amendment(physical)).state == "DELIVERED"


# ------------------------------------------------------------------- stale worker protection


async def test_a_stale_worker_cannot_enqueue_a_second_recovery(physical: Intake) -> None:
    """A claims attempt N, loses its lease, B finishes as N+1, and A's write matches no row."""
    case_id = await confirmed_case(physical)
    track_a = await track_of(physical, case_id, A)
    step = await physical.step_named(case_id, recovery.apply_step_key(track_a.id))

    stale = await steps.claim_step(physical.database, worker="worker-a")
    assert stale is not None
    await physical.expire_lease(step.id)
    await physical.drain(worker=physical.worker(identity="worker-b"), limit=30)

    result = await steps.execute_step(
        physical.database, claim=stale, actor=Actor(kind="SYSTEM", id="worker-a")
    )

    assert result in (StepResult.LEASE_LOST, StepResult.STALE)
    assert len(await physical.effects()) == 1
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED


async def test_a_stale_dispatcher_cannot_overwrite_a_reclaimed_effect(physical: Intake) -> None:
    """A dispatcher that stalled past its lease writes nothing when it finally wakes up."""
    case_id = await confirmed_case(physical)
    with crash.arm(crash.AFTER_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.worker().run_once()
    effect = await only_amendment(physical)

    stale = await outbox.claim_effect(physical.database, worker="dispatcher-a")
    assert stale is not None
    await physical.expire_effect_lease(effect.id)
    await physical.drain(worker=physical.worker(identity="dispatcher-b"), limit=30)

    with pytest.raises(outbox.EffectLeaseLostError):
        await outbox.record_delivery(
            physical.database,
            claim=stale,
            outcome=await FakeEffectAdapter().deliver(
                kind=stale.kind, payload=stale.payload, idempotency_key=stale.idempotency_key
            ),
            actor=Actor(kind="SYSTEM", id="dispatcher-a"),
        )
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED


async def test_only_one_worker_can_own_an_execution_step(physical: Intake) -> None:
    """No leader, no partitioning, no global mutex -- only ``FOR UPDATE SKIP LOCKED``.

    Two workers sweep the same database at the same moment. One takes the step; the other is
    told there is nothing to do rather than queueing behind it, and neither is coordinated by
    anything outside PostgreSQL.
    """
    case_id = await confirmed_case(physical)
    track_a = await track_of(physical, case_id, A)

    first = await steps.claim_step(physical.database, worker="worker-a")
    second = await steps.claim_step(physical.database, worker="worker-b")

    assert first is not None
    assert first.step_key == recovery.apply_step_key(track_a.id)
    assert second is None

    result = await steps.execute_step(
        physical.database, claim=first, actor=Actor(kind="SYSTEM", id="worker-a")
    )
    assert result is StepResult.COMPLETED
    assert len(await physical.effects()) == 1


# --------------------------------------------------------------------------- stale plan input


async def test_a_plan_whose_inputs_moved_produces_no_external_effect(physical: Intake) -> None:
    """§23: a recovery invalid before execution writes nothing, and the promise goes to a person.

    The mutation is one watched fingerprint input and nothing else, so what is being proved is
    that the recomputed fingerprint is compared and acted on -- not that a large change happens
    to break something.

    The stale finding is recorded and the order is untouched, which is §23's "nothing written".
    What follows it is an escalation rather than a resting ``STALE``: this path has no re-plan
    to enqueue, and a non-terminal track nothing can ever move is a promise silently abandoned.
    """
    case_id = await confirmed_case(physical)
    planned = (await track_of(physical, case_id, A)).fingerprint
    adapter = FakeEffectAdapter()

    await physical.bump_order_version(ho.ORDER_A)
    await physical.drain(worker=physical.worker(adapter=adapter), limit=30)

    track_a = await track_of(physical, case_id, A)
    assert track_a.state == recovery.TRACK_ESCALATED
    assert track_a.fingerprint == planned
    assert await physical.effects() == []
    assert adapter.call_count == 0
    events = await physical.events(case_id)
    assert recovery.EVENT_TRACK_STALE in events
    assert recovery.EVENT_TRACK_ESCALATED in events


async def test_a_stale_plan_holds_the_kitchen_work_and_lets_the_case_finish(
    physical: Intake,
) -> None:
    """The route onward a stale plan had none of: the owner's desk, and an ending.

    A track left ``STALE`` is non-terminal, so its case could not reconcile and could not
    resolve, and nothing in the system swept it. Both halves are asserted here rather than the
    escalation alone, because the state change is only half the repair -- the other half is that
    the case reaches an ending at all.
    """
    case_id = await confirmed_case(physical)
    track_a = await track_of(physical, case_id, A)

    await physical.bump_order_version(ho.ORDER_A)
    await physical.drain(limit=30)

    assert (await physical.tasks())[f"task-{ho.LINE_A}"] == ("HELD", case_id)
    assert (await track_of(physical, case_id, A)).id == track_a.id
    assert (await track_of(physical, case_id, A)).state in TERMINAL_TRACK_STATES


async def test_a_stale_plan_is_not_quietly_replaced_by_another_one(physical: Intake) -> None:
    """No option is re-selected and no fresh plan is invented; the chosen option is untouched."""
    case_id = await confirmed_case(physical)
    before = await track_of(physical, case_id, A)

    await physical.bump_order_version(ho.ORDER_A)
    await physical.drain(limit=30)

    after = await track_of(physical, case_id, A)
    assert after.chosen_option_id == before.chosen_option_id
    assert [option.id for option in await physical.options(after.id)] == [
        option.id for option in await physical.options(before.id)
    ]


# ------------------------------------------------------------------------- audit and events


async def test_the_confirmation_audit_names_the_human_who_authorised_it(
    physical: Intake,
) -> None:
    """§11.8: recovery authorisation is held by a person, and the ledger says which one."""
    case_id = await planned_case(physical)
    command_id = uuid4()
    await physical.confirm(case_id, command_id=command_id)

    row = next(
        entry
        for entry in await physical.audits(case_id)
        if entry.type == recovery.AUDIT_PLAN_CONFIRMED
    )

    assert row.actor_kind == "WORKER"
    assert row.actor_id == BAKER
    assert row.authority == "HUMAN_APPROVAL"
    assert row.provenance["command_id"] == str(command_id)


async def test_the_execution_audit_names_the_system_and_not_a_new_authorisation(
    physical: Intake,
) -> None:
    """The worker process executed an already-authorised action; it did not invent authority.

    The authority recorded is what permits this change to this customer's order -- her own
    pre-approval -- and the confirming human is on the confirmation row, not restated here as
    though the system had asked her.
    """
    case_id = await confirmed_case(physical)
    await physical.drain(limit=30)
    types = {row.type: row for row in await physical.audits(case_id)}

    applied = types[recovery.AUDIT_RECOVERY_APPLIED]
    assert applied.actor_kind == "SYSTEM"
    assert applied.authority == "CONSTRAINT"
    assert applied.provenance["cited_constraint_ids"] == [ho.CONSTRAINT_A_PREAPPROVED]
    assert types[recovery.AUDIT_RECOVERY_COMPLETED].actor_kind == "SYSTEM"


async def test_the_spine_tells_the_story_in_order(physical: Intake) -> None:
    """Confirmed, applying, recovered, asked, waiting -- in the order it actually happened.

    An exact sequence rather than a set: the spine is what a person reads to reconstruct a
    case, and an assertion that only checked membership would pass on a story told backwards.
    The two pieces of work a confirmation enqueues are independent, so the run is staged to
    give the spine one story to tell rather than two interleaved ones at random.
    """
    case_id = await confirmed_case(physical)
    await physical.drain(limit=40)
    await physical.release_approvals(case_id)
    await physical.drain(limit=40)

    events = await physical.events(case_id)
    named = [event for event in events if not event.startswith("workflow.step.")]

    assert named[named.index(recovery.EVENT_EXECUTION_CONFIRMED) :] == [
        recovery.EVENT_EXECUTION_CONFIRMED,
        recovery.EVENT_TRACK_ESCALATED,
        recovery.EVENT_TRACK_ESCALATED,
        recovery.EVENT_TRACK_APPLYING,
        "workflow.effect.delivered",
        recovery.EVENT_TRACK_RECOVERED,
        "approval.requested",
        "workflow.effect.delivered",
        "approval.sent",
        cases.EVENT_CASE_WAITING,
    ]


async def test_the_effect_is_stamped_with_the_event_that_announced_it(
    physical: Intake,
) -> None:
    """The effect and its cause were created by one transaction, and the row says which.

    ``created_in_tx_seq`` is what lets a reader of the spine find the effect a transition
    caused without trusting timestamps -- and its being set at all is the evidence that the
    outbox insert and the event append shared a commit.
    """
    before = await physical.latest_event_seq()
    case_id = await confirmed_case(physical)
    await physical.drain(limit=30)

    effect = await only_amendment(physical)
    appended = {
        event.seq: event.type
        for event in await physical.events_after(before)
        if event.case_id == case_id
    }
    delivered = next(seq for seq, kind in appended.items() if kind == "workflow.effect.delivered")
    recovered = next(
        seq for seq, kind in appended.items() if kind == recovery.EVENT_TRACK_RECOVERED
    )

    assert effect.created_in_tx_seq in appended
    # Three separate transactions, in the only order that can be crash-safe: the effect was
    # queued, then the provider's answer was recorded, then the track was finished.
    assert effect.created_in_tx_seq < delivered < recovered


async def test_a_rolled_back_execution_leaves_no_audit_no_event_and_no_effect(
    physical: Intake,
) -> None:
    """One transaction, one fate. There is no half-applied recovery to find afterwards."""
    case_id = await confirmed_case(physical)
    audits_before = len(await physical.audits(case_id))
    events_before = len(await physical.events(case_id))

    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.worker().run_once()

    assert len(await physical.audits(case_id)) == audits_before
    assert len(await physical.events(case_id)) == events_before
    assert await physical.effects() == []


# ------------------------------------------------------------------------ the zero-write proof


async def test_the_saga_writes_nothing_it_was_not_authorised_to_write(physical: Intake) -> None:
    """Every row of the order book, before and after, with one named exception.

    The blocked tracks' production tasks move to ``HELD`` because §13.5 says they must. Nothing
    else in ``orders``, ``order_lines``, ``reservations``, ``recipe_versions`` or ``promises``
    is permitted to differ -- and in particular no recipe version is created at runtime, and no
    order line is re-pinned locally, because the external order system is the record for that
    and this slice has not pushed to one yet.
    """
    case_id = await confirmed_case(physical)
    before = await physical.order_book()
    tasks_before = await physical.tasks()

    await physical.drain(limit=30)

    after = await physical.order_book()
    for table in ("orders", "order_lines", "reservations", "recipe_versions", "promises"):
        assert after[table] == before[table], table

    tasks_after = await physical.tasks()
    moved = {task for task in tasks_after if tasks_before[task] != tasks_after[task]}
    assert moved == set()
    assert case_id is not None


async def test_no_recipe_version_is_ever_created_at_runtime(physical: Intake) -> None:
    """The variant applied was authored by a human before the exception existed."""
    before = await physical.rows_of(RecipeVersion)

    await confirmed_case(physical)
    await physical.drain(limit=30)

    after = await physical.rows_of(RecipeVersion)
    assert after == before
