"""Deadlines that outlive the process that armed them.

Three claims are being made and all three are about absence: nothing is scheduled in memory,
nothing is lost when a worker dies, and nothing fires twice when two workers poll at the same
instant. The mechanisms are a row, a partial unique index and a row lock -- there is no timer
thread anywhere in the system to go wrong.

Overdue timers are made overdue by writing a due date in the past, which is what waiting would
have achieved and is deterministic in a way waiting is not.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from _workflow_support import Workflow
from sqlalchemy import text

from promisepatch.db.clock import database_now
from promisepatch.db.models import CaseStep, Timer
from promisepatch.db.uow import Actor
from promisepatch.domain import handlers, steps, timers
from promisepatch.domain.model import CASE_SUBJECT, WAKEUP_TIMER_KIND, StepKind, StepResult

pytestmark = pytest.mark.integration

WORKER_A = "worker-a"
WORKER_B = "worker-b"
ACTOR_A = Actor(kind="SYSTEM", id=WORKER_A)


async def arm(
    workflow: Workflow, case_id: UUID, *, seconds: int = 0, kind: str = WAKEUP_TIMER_KIND
) -> UUID | None:
    async with workflow.database.begin() as connection:
        now = await database_now(connection)
        return await timers.arm_timer(
            connection,
            kind=kind,
            subject_type=CASE_SUBJECT,
            subject_id=str(case_id),
            due_at=now + timedelta(seconds=seconds),
        )


# --------------------------------------------------------------------------------- arming


async def test_arming_the_same_deadline_twice_leaves_one_timer(workflow: Workflow) -> None:
    """Idempotent by index, so a transition replayed after a crash re-arms harmlessly."""
    case_id = await workflow.create_case()
    first = await arm(workflow, case_id)
    second = await arm(workflow, case_id)

    assert first is not None
    assert second is None
    assert len(await workflow.rows(Timer, subject_id=str(case_id))) == 1


async def test_re_arming_does_not_move_a_deadline_that_is_already_counting_down(
    workflow: Workflow,
) -> None:
    """The first arming reflects when the wait actually started; a replay must not extend it."""
    case_id = await workflow.create_case()
    await arm(workflow, case_id, seconds=10)
    original = (await workflow.rows(Timer, subject_id=str(case_id)))[0].due_at

    await arm(workflow, case_id, seconds=3600)
    assert (await workflow.rows(Timer, subject_id=str(case_id)))[0].due_at == original


async def test_a_fired_timer_frees_the_subject_for_the_next_round(workflow: Workflow) -> None:
    """Partial on ``fired_at IS NULL``: one *live* timer per subject, not one ever."""
    case_id = await workflow.create_case()
    await arm(workflow, case_id)
    assert await timers.fire_due_timer(workflow.database, worker=WORKER_A) is not None

    assert await arm(workflow, case_id, seconds=3600) is not None
    assert len(await workflow.rows(Timer, subject_id=str(case_id))) == 2


# ---------------------------------------------------------------------------------- firing


async def test_a_due_timer_becomes_exactly_one_case_step(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    timer_id = await arm(workflow, case_id)
    assert timer_id is not None

    fired = await timers.fire_due_timer(workflow.database, worker=WORKER_A)
    assert fired is not None
    assert fired.timer_id == timer_id
    assert fired.step_key == handlers.timer_step_key(timer_id)

    created = await workflow.rows(CaseStep, case_id=case_id)
    assert [step.step_key for step in created] == [fired.step_key]
    assert created[0].kind == StepKind.TIMER_WAKEUP.value

    row = await workflow.row(Timer, timer_id)
    assert row.fired_at is not None
    assert row.claimed_by == WORKER_A


async def test_a_timer_that_is_not_yet_due_does_not_fire(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    await arm(workflow, case_id, seconds=3600)
    assert await timers.fire_due_timer(workflow.database, worker=WORKER_A) is None


async def test_two_workers_fire_one_timer_once(workflow: Workflow) -> None:
    """The row lock decides it. The loser finds nothing due, not the same deadline again."""
    case_id = await workflow.create_case()
    await arm(workflow, case_id)

    first = await timers.fire_due_timer(workflow.database, worker=WORKER_A)
    second = await timers.fire_due_timer(workflow.database, worker=WORKER_B)

    assert first is not None
    assert second is None
    assert len(await workflow.rows(CaseStep, case_id=case_id)) == 1


async def test_polling_again_after_a_firing_creates_no_second_wake_up(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    await arm(workflow, case_id)
    await timers.fire_due_timer(workflow.database, worker=WORKER_A)

    for _ in range(3):
        assert await timers.fire_due_timer(workflow.database, worker=WORKER_A) is None
    assert len(await workflow.rows(CaseStep, case_id=case_id)) == 1


async def test_an_overdue_timer_fires_immediately_however_long_nobody_was_running(
    workflow: Workflow,
) -> None:
    """The deadline passed whether or not anybody was there, so recovery is not "catch up"."""
    case_id = await workflow.create_case()
    timer_id = await arm(workflow, case_id, seconds=60)
    assert await timers.fire_due_timer(workflow.database, worker=WORKER_A) is None

    async with workflow.database.begin() as connection:
        await connection.execute(
            text(
                "UPDATE promisepatch.timers SET due_at = now() - interval '3 hours' WHERE id = :id"
            ),
            {"id": timer_id},
        )

    fired = await timers.fire_due_timer(workflow.database, worker=WORKER_B)
    assert fired is not None
    assert fired.timer_id == timer_id


async def test_a_fired_timer_wakes_the_workflow_up(workflow: Workflow) -> None:
    """End to end: deadline becomes step, step executes, case moves on."""
    case_id = await workflow.create_case()
    await arm(workflow, case_id)
    before = await workflow.case(case_id)

    assert await timers.fire_due_timer(workflow.database, worker=WORKER_A) is not None
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    assert (
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)
        is StepResult.COMPLETED
    )
    assert (await workflow.case(case_id)).version == before.version + 1


async def test_a_step_arms_a_timer_inside_its_own_transition(workflow: Workflow) -> None:
    """The deadline and the decision that needed it commit together, or neither does."""
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="arm-timer:0", kind=StepKind.ARM_TIMER)

    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    armed = await workflow.rows(Timer, subject_id=str(case_id))
    assert len(armed) == 1
    assert armed[0].kind == WAKEUP_TIMER_KIND


# ------------------------------------------------------------------------ cancel and race


async def test_cancelling_removes_a_live_timer(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    await arm(workflow, case_id, seconds=3600)

    async with workflow.database.begin() as connection:
        removed = await timers.cancel_timer(
            connection,
            kind=WAKEUP_TIMER_KIND,
            subject_type=CASE_SUBJECT,
            subject_id=str(case_id),
        )
    assert removed == 1
    assert await workflow.rows(Timer, subject_id=str(case_id)) == []


async def test_cancelling_after_a_firing_removes_nothing(workflow: Workflow) -> None:
    """The deadline already happened. A cancellation arriving afterwards is a no-op, not an undo."""
    case_id = await workflow.create_case()
    await arm(workflow, case_id)
    fired = await timers.fire_due_timer(workflow.database, worker=WORKER_A)
    assert fired is not None

    async with workflow.database.begin() as connection:
        removed = await timers.cancel_timer(
            connection,
            kind=WAKEUP_TIMER_KIND,
            subject_type=CASE_SUBJECT,
            subject_id=str(case_id),
        )
    assert removed == 0

    row = await workflow.row(Timer, fired.timer_id)
    assert row is not None
    assert row.fired_at is not None
    assert len(await workflow.rows(CaseStep, case_id=case_id)) == 1


async def test_a_firing_that_races_a_cancellation_sees_the_row_disappear(
    workflow: Workflow,
) -> None:
    """Cancel first: the sweep finds nothing due, and no wake-up step is ever created."""
    case_id = await workflow.create_case()
    await arm(workflow, case_id)

    async with workflow.database.begin() as connection:
        await timers.cancel_timer(
            connection,
            kind=WAKEUP_TIMER_KIND,
            subject_type=CASE_SUBJECT,
            subject_id=str(case_id),
        )

    assert await timers.fire_due_timer(workflow.database, worker=WORKER_A) is None
    assert await workflow.rows(CaseStep, case_id=case_id) == []


async def test_a_cancellation_waits_for_a_firing_that_holds_the_row(
    workflow: Workflow, app_database_url: str
) -> None:
    """Both take the row lock, so one of them is second -- and the second re-reads the truth.

    The cancellation is issued while the firing transaction is still open, blocks on the row
    lock, and once the firing commits it re-evaluates ``fired_at IS NULL`` against the row the
    firing left behind. It deletes nothing, which is correct: the deadline fired.
    """
    import asyncio

    from promisepatch.db import build_engine

    case_id = await workflow.create_case()
    timer_id = await arm(workflow, case_id)
    assert timer_id is not None

    engine = build_engine(app_database_url, pool_size=1)
    try:
        firing = await engine.connect()
        await firing.execute(
            text(
                "UPDATE promisepatch.timers SET fired_at = now(), claimed_by = 'worker-a'"
                " WHERE id = :id AND fired_at IS NULL"
            ),
            {"id": timer_id},
        )

        async def cancel() -> int:
            async with workflow.database.begin() as connection:
                return await timers.cancel_timer(
                    connection,
                    kind=WAKEUP_TIMER_KIND,
                    subject_type=CASE_SUBJECT,
                    subject_id=str(case_id),
                )

        blocked = asyncio.create_task(cancel())
        # The task cannot complete: it is waiting on the row lock the open firing holds.
        done, _ = await asyncio.wait({blocked}, timeout=0.5)
        assert done == set()

        await firing.commit()
        await firing.close()

        assert await blocked == 0
        assert (await workflow.row(Timer, timer_id)).fired_at is not None
    finally:
        await engine.dispose()
