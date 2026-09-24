"""Execution-time freshness: what must still be true when an amendment is committed (ADR-0024).

Every test here moves **only the clock**. No row is written between the moment the checks last
passed and the moment the amendment would be committed, so the fingerprint -- which covers every
watched row, the production task's state and start included -- cannot see anything change. What
changes is whether the task's start is still ahead, and that is the one half of §14.3's check 6
that only the clock can answer.

The clock is the step runner's: :func:`promisepatch.db.clock.database_now` as the step module
reads it, advanced by a fixed offset. It is how a paused worker, a backlog or a restart looks to
the transaction that finally runs, and it touches nothing else in the database.

Four things are pinned:

- an approved amendment is not committed after its production start, although revalidation
  passed and nothing else moved;
- an approval consumed before its deadline still executes after the deadline, while the start is
  ahead -- the deadline governs the answer, not the execution;
- an automatic amendment is held to the same start;
- once the amendment is committed, the outbox delivers it: a retry after a lost acknowledgement
  goes out under the same key after the start has passed, and the order changes exactly once.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from _intake_support import RASPBERRY_ONLY, Intake
from _intake_support import physical as physical
from sqlalchemy.ext.asyncio import AsyncConnection
from test_recovery_revalidation import amendments_for, approved_case, track_of

from promise_graph.examples import hollow_oak as ho
from promisepatch.db.clock import database_now as real_database_now
from promisepatch.domain import cases, outbox, recovery, steps
from promisepatch.domain.adapters import FakeEffectAdapter, ProviderBehaviour

pytestmark = pytest.mark.integration

A, B = ho.PROMISE_A, ho.PROMISE_B


# ------------------------------------------------------------------------------------ the clock


def move_clock(monkeypatch: pytest.MonkeyPatch, *modules: Any, by: timedelta) -> None:
    """Advance the clock these modules read by ``by``. No row is touched."""

    async def later(connection: AsyncConnection) -> datetime:
        return await real_database_now(connection) + by

    for module in modules:
        monkeypatch.setattr(module, "database_now", later)


async def database_time(intake: Intake) -> datetime:
    async with intake.database.connect() as connection:
        return await real_database_now(connection)


async def until(intake: Intake, line_id: str, *, past: timedelta) -> timedelta:
    """The offset that puts the clock ``past`` beyond one line's scheduled production start."""
    task = await intake.task_of_line(line_id)
    start: datetime = task.scheduled_start
    assert start is not None
    return start - await database_time(intake) + past


async def proceeded(
    intake: Intake, case_id: UUID, *, adapter: FakeEffectAdapter | None = None
) -> Any:
    """Run the worker only until B's checklist has recorded PROCEED. ``apply:B`` is then queued."""
    track_b = await track_of(intake, case_id, B)
    worker = intake.worker(adapter=adapter)
    for _ in range(12):
        step = await intake.step_named(case_id, cases.revalidate_step_key(track_b.id))
        if step is not None and step.state == "DONE":
            break
        await worker.run_once()
    assert step is not None and step.result["outcome"] == "PROCEED"
    apply = await intake.step_named(case_id, recovery.apply_step_key(track_b.id))
    assert apply is not None and apply.state == "PENDING"
    return track_b


async def fingerprint_now(intake: Intake, track: Any) -> str:
    async with intake.database.connect() as connection:
        return await recovery.current_fingerprint(connection, track)


# ------------------------------------------------------------------------------ approved tracks


async def test_an_approved_amendment_is_not_committed_after_its_production_start(
    physical: Intake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reproduction: PROCEED, a pause, only time passes, and the order must not change.

    Before ADR-0024 this committed and delivered the amendment and settled B ``RECOVERED`` with
    its task still ``SCHEDULED`` at a start already in the past. The fingerprint is asserted
    equal to the planned one before the clock moves, so the refusal is provably the clock's and
    not a row's; the hold the refusal itself takes moves it afterwards, as it should.
    """
    case_id, _ = await approved_case(physical)
    track_b = await proceeded(physical, case_id)
    # Nothing a row can say has moved since the plan: only the clock will.
    assert await fingerprint_now(physical, track_b) == track_b.fingerprint

    move_clock(monkeypatch, steps, by=await until(physical, ho.LINE_B, past=timedelta(minutes=1)))
    await physical.drain(limit=40)

    assert await amendments_for(physical, track_b.id) == []
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED
    assert (await physical.tasks())[f"task-{ho.LINE_B}"] == ("HELD", case_id)

    applied = await physical.step_named(case_id, recovery.apply_step_key(track_b.id))
    assert applied.result["outcome"] == "ESCALATED"
    assert applied.result["reason"] == recovery.ESCALATION_PLAN_STALE
    assert "production start" in applied.result["detail"]

    # The customer's yes and the checklist that consumed it are history, and stay exactly so.
    revalidated = await physical.step_named(case_id, cases.revalidate_step_key(track_b.id))
    assert revalidated.result["outcome"] == "PROCEED"
    assert len(await physical.decisions()) == 1


async def test_an_approval_consumed_in_time_executes_after_its_deadline_while_the_start_is_ahead(
    physical: Intake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deadline governs the answer, not the execution.

    Check 7 was judged when the revalidation consumed the decision. The deadline is an hour
    before the start by construction, so a worker that resumes between the two still has a live
    production window, and the change the customer approved in time is made.
    """
    case_id, request = await approved_case(physical)
    track_b = await proceeded(physical, case_id)
    task = await physical.task_of_line(ho.LINE_B)
    assert request.deadline < task.scheduled_start

    move_clock(
        monkeypatch,
        steps,
        by=request.deadline - await database_time(physical) + timedelta(minutes=1),
    )
    await physical.drain(limit=40)

    delivered = await amendments_for(physical, track_b.id)
    assert [(row.state, row.attempts) for row in delivered] == [("DELIVERED", 1)]
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_RECOVERED


# ----------------------------------------------------------------------------- automatic tracks


async def test_an_automatic_amendment_is_held_to_the_same_production_start(
    physical: Intake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§24: validation is re-run at APPLYING for automatic tracks too.

    The confirmation enqueues ``apply:A``; the worker does not reach it until A's start has
    passed. Nothing is written in between, and A's order is not changed.
    """
    opened = await physical.report()
    await physical.drain()
    await physical.answer(opened.case_id, RASPBERRY_ONLY)
    await physical.drain()
    await physical.confirm(opened.case_id)
    track_a = await track_of(physical, opened.case_id, A)
    assert await fingerprint_now(physical, track_a) == track_a.fingerprint

    move_clock(monkeypatch, steps, by=await until(physical, ho.LINE_A, past=timedelta(minutes=1)))
    await physical.drain(limit=40)

    assert await amendments_for(physical, track_a.id) == []
    assert (await track_of(physical, opened.case_id, A)).state == recovery.TRACK_ESCALATED
    applied = await physical.step_named(opened.case_id, recovery.apply_step_key(track_a.id))
    assert applied.result["reason"] == recovery.ESCALATION_PLAN_STALE
    assert "production start" in applied.result["detail"]


# ------------------------------------------------------------------- after the commit boundary


async def test_a_committed_amendment_whose_acknowledgement_was_lost_is_still_delivered_once(
    physical: Intake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No time gate after the commit: an uncertain effect is re-sent, never cancelled.

    The order system accepted B's amendment and the answer was lost. By the time the retry is
    due, B's start has passed. Refusing now would record "not changed" for an order that has
    changed; the retry goes out under the same key instead, and the order changes once.
    """
    adapter = FakeEffectAdapter()
    case_id, request = await approved_case(physical, adapter=adapter)
    track_b = await proceeded(physical, case_id, adapter=adapter)
    adapter.script = [ProviderBehaviour.APPLY_THEN_LOSE_RESPONSE]

    worker = physical.worker(adapter=adapter)
    await physical.drain(worker=worker, limit=40)
    [amendment] = await amendments_for(physical, track_b.id)
    assert (amendment.state, amendment.attempts) == ("PENDING", 1)
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_APPLYING

    move_clock(
        monkeypatch,
        steps,
        outbox,
        by=await until(physical, ho.LINE_B, past=timedelta(minutes=1)),
    )
    await physical.make_effect_due(amendment.id)
    await physical.drain(worker=worker, limit=40)

    key = recovery.amend_idempotency_key(
        track_id=track_b.id,
        option_id=request.option_id,
        order_version=request.captured_order_version,
    )
    sent = [attempt for attempt in adapter.attempts if attempt.idempotency_key == key]
    assert len(sent) == 2
    assert [effect for effect in adapter.effects if effect == key] == [key]
    [delivered] = await amendments_for(physical, track_b.id)
    assert (delivered.state, delivered.attempts) == ("DELIVERED", 2)
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_RECOVERED
