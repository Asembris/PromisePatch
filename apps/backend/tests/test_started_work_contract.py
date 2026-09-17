"""What this system may and may not say about kitchen work that has already begun.

The whole claim is one sentence -- **work that has started is never reported as stopped** --
and every test here asks it from a different angle. It is the started-work half of the physical
invariant the product is built on: a physical fact is authoritative independently of recovery
authorization, and only an explicit correcting attestation reverses one.

The world is S12's. Ahmed edits ``ord-e`` in the external order system into a raspberry version
before anybody reports anything, so the shortfall reaches a promise whose production task the
frozen fixture stipulates is already ``STARTED`` -- the only one of the six that is. That makes
``ord-e`` a blocked promise whose kitchen work cannot be stopped by a database write, and the
four tests in the middle of this file are the four ways a system could lie about that:

* hold it anyway, and report a stop that never happened;
* escalate it silently, so the owner is never told the work is running;
* release it on withdrawal, rewriting ``STARTED`` into ``SCHEDULED``;
* count it in a sentence read out to a person as a task that was put back.

``ord-c`` and ``ord-d`` are in every assertion beside it, because a hold that stopped happening
at all would pass a suite that only watched ``ord-e``. Scheduled work on a blocked promise is
held; started work on the same case, in the same transaction, is not.

The last test is deliberately a characterisation rather than a goal: it pins S12's published
divergence, so the day the behaviour changes, this file fails and says which decision moved.
See ADR-0017 and ``docs/started-work-contract.md``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from _intake_support import BAKER, RASPBERRY_ONLY, Intake
from _intake_support import physical as physical

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import Classification
from promisepatch.domain import recovery, status_view, withdrawal

pytestmark = pytest.mark.integration

STARTED_LINE = ho.LINE_E
"""The one order line whose kitchen work has already begun, in the fixture, before anything."""

STARTED_TASK = f"task-{ho.LINE_E}"

SCHEDULED_BLOCKED_LINES = (ho.LINE_C, ho.LINE_D)
"""The blocked promises whose work has *not* begun. A hold on these is the truthful write."""

SCHEDULED_BLOCKED_TASKS = tuple(f"task-{line}" for line in SCHEDULED_BLOCKED_LINES)

UNREACHED_LINE = ho.LINE_F
"""The standing pastry order the raspberry shortfall never arrives at."""


async def started_blocked_case(intake_fixture: Intake) -> UUID:
    """S12's world, driven to ``PLANNED``: Ahmed's order edited into the blast radius.

    The edit happens before the exception is reported, which is what makes ``ord-e``'s
    membership of the threatened set a consequence of stored state rather than of anything the
    case decided. ``bump_order`` is left on because a real external amendment moves the order's
    version with it, exactly as S12 stipulates.
    """
    await intake_fixture.repin_order_line(STARTED_LINE, ho.RLL_V2)
    opened = await intake_fixture.report()
    await intake_fixture.drain()
    await intake_fixture.answer(opened.case_id, RASPBERRY_ONLY)
    await intake_fixture.drain()
    return opened.case_id


async def track_of(intake_fixture: Intake, case_id: UUID, promise_id: str) -> Any:
    row = await intake_fixture.track(case_id, promise_id)
    assert row is not None
    return row


async def withdraw(intake_fixture: Intake, case_id: UUID) -> withdrawal.WithdrawalResult:
    return await withdrawal.withdraw_exception(
        intake_fixture.database,
        case_id=case_id,
        command_id=uuid4(),
        worker_id=BAKER,
    )


# ------------------------------------------------------------------ the premise, made explicit


async def test_exactly_one_task_in_the_fixture_has_already_started(physical: Intake) -> None:
    """The stipulation every other test here rests on, asserted rather than assumed.

    If this fixture ever changes so that nothing has started, the four tests below would keep
    passing while proving nothing at all.
    """
    tasks = await physical.tasks()

    started = {task for task, (state, _) in tasks.items() if state == "STARTED"}
    assert started == {STARTED_TASK}, started
    assert all(state == "SCHEDULED" for task, (state, _) in tasks.items() if task != STARTED_TASK)


async def test_the_started_promise_is_the_one_the_external_edit_reaches(
    physical: Intake,
) -> None:
    """Ahmed's edit puts him in the blast radius, and nothing this system may do repairs it.

    Asserted before any hold is discussed, because "not held" is only interesting about a
    promise the case actually decided something about.
    """
    case_id = await started_blocked_case(physical)

    track = await track_of(physical, case_id, ho.PROMISE_E)
    assert track.classification == Classification.BLOCKED.value


# ------------------------------------------------------ what a hold may and may not be taken on


async def test_scheduled_work_on_a_blocked_promise_is_held(physical: Intake) -> None:
    """The truthful hold: work that has not begun can be prevented from beginning."""
    case_id = await started_blocked_case(physical)

    await physical.confirm(case_id)

    tasks = await physical.tasks()
    for task in SCHEDULED_BLOCKED_TASKS:
        assert tasks[task] == ("HELD", case_id), task


async def test_started_work_on_a_blocked_promise_is_not_held(physical: Intake) -> None:
    """The load-bearing negative. A row cannot stop an oven, so it does not claim to.

    ``recovery.hold_tasks`` is predicated on ``SCHEDULED`` and that predicate is the contract,
    not an implementation detail: holding a started task would assert a physical stop nobody
    performed, and -- because release restores the literal ``SCHEDULED`` -- would let a later
    withdrawal assert that begun work had never begun.
    """
    case_id = await started_blocked_case(physical)

    await physical.confirm(case_id)

    assert (await physical.tasks())[STARTED_TASK] == ("STARTED", None)


async def test_the_started_promise_still_reaches_its_owner(physical: Intake) -> None:
    """Not holding it is not ignoring it. The obligation is raised; only the stop is not faked.

    This is the outcome that replaces the hold: the track lands on the owner's desk in the same
    transaction that holds the other two, and the case says out loud that it needs attention.
    """
    case_id = await started_blocked_case(physical)

    await physical.confirm(case_id)

    track = await track_of(physical, case_id, ho.PROMISE_E)
    assert track.state == recovery.TRACK_ESCALATED
    assert (await physical.case(case_id)).needs_owner_attention is True


async def test_a_started_task_is_escalated_without_being_held_in_the_same_transaction(
    physical: Intake,
) -> None:
    """Both halves at once, because the pair is the claim and either alone is not.

    A build that held nothing would pass "started work is not held"; a build that held
    everything would pass "the owner is told". Only the split is the contract.
    """
    case_id = await started_blocked_case(physical)

    await physical.confirm(case_id)

    tasks = await physical.tasks()
    held = {task for task, (state, holder) in tasks.items() if holder == case_id}
    assert held == set(SCHEDULED_BLOCKED_TASKS), held
    for promise_id in (ho.PROMISE_C, ho.PROMISE_D, ho.PROMISE_E):
        assert (await track_of(physical, case_id, promise_id)).state == recovery.TRACK_ESCALATED


# ------------------------------------------------------------ what a withdrawal may not rewrite


async def test_a_withdrawal_does_not_rewind_started_work(physical: Intake) -> None:
    """The one that would be found out from a customer. A stand-down is not an attestation.

    ``withdrawal._release_holds`` writes the literal ``SCHEDULED``. It reaches only rows this
    case actually holds, so a started task is out of its range -- and that is exactly why the
    hold was never taken.
    """
    case_id = await started_blocked_case(physical)
    await physical.confirm(case_id)
    assert (await physical.tasks())[STARTED_TASK] == ("STARTED", None)

    await withdraw(physical, case_id)

    assert (await physical.tasks())[STARTED_TASK] == ("STARTED", None)


async def test_a_withdrawal_releases_only_the_work_it_really_stopped(physical: Intake) -> None:
    """The count in the reversal record is the count of rows that moved, and no larger."""
    case_id = await started_blocked_case(physical)
    await physical.confirm(case_id)

    result = await withdraw(physical, case_id)

    assert dict(result.reversals)[withdrawal.ReversalKind.TASK_HOLD] == len(SCHEDULED_BLOCKED_TASKS)
    tasks = await physical.tasks()
    for task in SCHEDULED_BLOCKED_TASKS:
        assert tasks[task] == ("SCHEDULED", None), task


async def test_the_withdrawal_sentence_claims_no_stop_that_did_not_happen(
    physical: Intake,
) -> None:
    """What a person is told, rather than what a row holds. The two must be the same number.

    Read through the domain's own renderer because a screen may not re-word what it was given:
    if the sentence said three production tasks, a worker would believe Ahmed's oven was off.
    """
    case_id = await started_blocked_case(physical)
    await physical.confirm(case_id)

    result = await withdraw(physical, case_id)

    sentence = status_view.render_withdrawal(
        withdrawn=len(result.withdrawn),
        escalated=len(result.escalated),
        reversals=[(kind.value, count) for kind, count in result.reversals],
        applied=[(kind.value, count) for kind, count in result.applied],
        already_withdrawn=False,
    )
    assert "3 production tasks" not in sentence
    assert f"{len(SCHEDULED_BLOCKED_TASKS)} production tasks" in sentence


# ------------------------------------------------------------------------- selective, as always


async def test_work_the_exception_never_reaches_is_untouched(physical: Intake) -> None:
    """The promise outside the blast radius keeps its task, its holder and its state."""
    case_id = await started_blocked_case(physical)
    before = (await physical.tasks())[f"task-{UNREACHED_LINE}"]

    await physical.confirm(case_id)

    assert (await physical.tasks())[f"task-{UNREACHED_LINE}"] == before
    assert before[1] is None


# ---------------------------------------------------------------- S12, characterised on purpose


async def test_s12_escalates_ahmeds_promise_and_holds_no_task_for_it(physical: Intake) -> None:
    """The published divergence, pinned so that it cannot move without this file saying so.

    The frozen manifest labels ``ord-e task_hold 1`` at three checkpoints and this build
    produces ``0``; S12 is committed failing on that difference and nothing else. ADR-0017
    records why the label is not changed and why the behaviour is not changed either. This test
    is neither a repair nor an endorsement of the label -- it is the statement of what is
    actually true here, so a future change to either side is visible immediately.
    """
    case_id = await started_blocked_case(physical)

    await physical.confirm(case_id)

    tasks = await physical.tasks()
    assert tasks[STARTED_TASK] == ("STARTED", None), "no hold: manifest expects 1, build gives 0"
    assert (await track_of(physical, case_id, ho.PROMISE_E)).state == recovery.TRACK_ESCALATED
