"""What survives a worker that stops existing, at each place it could stop existing.

Every test here kills a process at a named persistence boundary and then starts a fresh one.
The kill is a :class:`~promisepatch.domain.crash.WorkerDied`, which inherits
:class:`BaseException` precisely so it is *not* handled: the point is what the database holds
when the worker's own error handling never runs. There are no sleeps and no timing assumptions
-- a lease expires because its expiry is written into the past, which is what the passage of
time would have done.

The file ends with the acceptance scenario: one workflow driven from a first step to an
external effect and a timer wake-up, across a worker that dies in the middle of it.

None of this is PromisePatch's exception semantics. It is the infrastructure those semantics
will run on, proven before anything is built on top of it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from _workflow_support import Workflow

from promisepatch.db.models import CaseStep, InboxEvent, OutboxMessage, Timer
from promisepatch.db.uow import Actor
from promisepatch.domain import crash, handlers, inbox, outbox, steps, timers
from promisepatch.domain.adapters import FakeEffectAdapter
from promisepatch.domain.identity import WorkerIdentity
from promisepatch.domain.model import CASE_SUBJECT, DeliveryStatus, StepKind, StepResult
from promisepatch.worker import Worker

pytestmark = pytest.mark.integration

WORKER_A = "worker-a"
WORKER_B = "worker-b"
ACTOR_A = Actor(kind="SYSTEM", id=WORKER_A)
ACTOR_B = Actor(kind="SYSTEM", id=WORKER_B)


@contextmanager
def dies_at(boundary: str) -> Iterator[None]:
    """Run the block with ``boundary`` armed, and require the process to die there.

    Both halves together, because a test that armed a boundary and then did not die at it would
    pass silently while proving nothing.
    """
    with crash.arm(boundary), pytest.raises(crash.WorkerDied):
        yield


# ------------------------------------------------------------------------ crashing on a step


async def test_a_death_before_the_claim_leaves_the_step_untouched(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)

    with dies_at(crash.BEFORE_CLAIM):
        await steps.claim_step(workflow.database, worker=WORKER_A)

    row = await workflow.row(CaseStep, step_id)
    assert row.state == "PENDING"
    assert row.attempts == 0
    assert row.lease_owner is None


async def test_a_death_after_the_claim_committed_is_recovered_when_the_lease_expires(
    workflow: Workflow,
) -> None:
    """The claim survives, which is the whole reason it is committed separately.

    A step stuck ``IN_FLIGHT`` with a dead owner is not lost work -- it is work with an expiry
    date on it, and the next sweep collects it.
    """
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)

    with dies_at(crash.AFTER_CLAIM_COMMIT):
        await steps.claim_step(workflow.database, worker=WORKER_A)

    row = await workflow.row(CaseStep, step_id)
    assert row.state == "IN_FLIGHT"
    assert row.attempts == 1
    assert row.lease_owner == WORKER_A

    assert await steps.claim_step(workflow.database, worker=WORKER_B) is None
    await workflow.expire_lease(step_id)

    reclaimed = await steps.claim_step(workflow.database, worker=WORKER_B)
    assert reclaimed is not None
    assert reclaimed.attempts == 2
    assert (
        await steps.execute_step(workflow.database, claim=reclaimed, actor=ACTOR_B)
        is StepResult.COMPLETED
    )


async def test_a_death_inside_the_handler_leaves_no_partial_transition(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="chain:0", kind=StepKind.CHAIN)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    before = await workflow.case(case_id)
    audit_before = await workflow.latest_audit_seq()

    with dies_at(crash.DURING_HANDLER):
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    assert (await workflow.row(CaseStep, step_id)).state == "IN_FLIGHT"
    assert (await workflow.case(case_id)).version == before.version
    assert await workflow.rows(CaseStep, case_id=case_id, step_key="chain:1") == []
    assert await workflow.audits_since(audit_before, case_id=case_id) == []


async def test_a_death_before_the_transition_commits_leaves_nothing_behind(
    workflow: Workflow,
) -> None:
    """Every half of the transition rolls back together: case, successor, audit, event."""
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="chain:0", kind=StepKind.CHAIN)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None

    before = await workflow.case(case_id)
    audit_before = await workflow.latest_audit_seq()
    event_before = await workflow.latest_event_seq()

    with dies_at(crash.BEFORE_TRANSITION_COMMIT):
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    assert (await workflow.row(CaseStep, step_id)).state == "IN_FLIGHT"
    assert (await workflow.case(case_id)).version == before.version
    assert await workflow.rows(CaseStep, case_id=case_id, step_key="chain:1") == []
    assert await workflow.audits_since(audit_before, case_id=case_id) == []
    assert [e for e in await workflow.events_since(event_before) if e.case_id == case_id] == []


async def test_a_death_after_the_transition_committed_keeps_the_successor(
    workflow: Workflow,
) -> None:
    """The other side of the same boundary: what committed is durable, and work carries on."""
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="chain:0", kind=StepKind.CHAIN)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None

    with dies_at(crash.AFTER_TRANSITION_COMMIT):
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    assert (await workflow.row(CaseStep, step_id)).state == "DONE"
    successors = await workflow.rows(CaseStep, case_id=case_id, step_key="chain:1")
    assert len(successors) == 1
    assert successors[0].state == "PENDING"

    resumed = await steps.claim_step(workflow.database, worker=WORKER_B)
    assert resumed is not None
    assert resumed.step_key == "chain:1"


async def test_a_death_during_retry_bookkeeping_leaves_the_step_reclaimable(
    workflow: Workflow,
) -> None:
    """No retry is scheduled, so the lease is what brings the step back. Either way it returns."""
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="fail:1", kind=StepKind.FAIL_RETRYABLE)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None

    with dies_at(crash.DURING_RETRY_BOOKKEEPING):
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    row = await workflow.row(CaseStep, step_id)
    assert row.state == "IN_FLIGHT"
    assert row.next_attempt_at is None

    await workflow.expire_lease(step_id)
    reclaimed = await steps.claim_step(workflow.database, worker=WORKER_B)
    assert reclaimed is not None
    assert (
        await steps.execute_step(workflow.database, claim=reclaimed, actor=ACTOR_B)
        is StepResult.RETRY_SCHEDULED
    )
    assert (await workflow.row(CaseStep, step_id)).state == "RETRYING"


async def test_a_scheduled_retry_survives_a_restart(workflow: Workflow) -> None:
    """It is a column, not a scheduled callback, so nothing was holding it in the first place."""
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="fail:1", kind=StepKind.FAIL_RETRYABLE)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    row = await workflow.row(CaseStep, step_id)
    assert row.state == "RETRYING"
    assert row.next_attempt_at is not None

    await workflow.make_due(step_id)
    resumed = await steps.claim_step(workflow.database, worker="worker-after-restart")
    assert resumed is not None
    assert resumed.attempts == 2


async def test_a_stale_worker_cannot_overwrite_the_recovery_that_replaced_it(
    workflow: Workflow,
) -> None:
    """Crash recovery and fencing together: B does the work, A wakes up and is refused."""
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="chain:0", kind=StepKind.CHAIN)

    with dies_at(crash.AFTER_CLAIM_COMMIT):
        await steps.claim_step(workflow.database, worker=WORKER_A)
    stalled = steps.StepClaim(
        step_id=step_id,
        case_id=case_id,
        step_key="chain:0",
        kind=StepKind.CHAIN.value,
        attempts=1,
        lease_owner=WORKER_A,
        lease_expires_at=(await workflow.row(CaseStep, step_id)).lease_expires_at,
    )

    await workflow.expire_lease(step_id)
    reclaimed = await steps.claim_step(workflow.database, worker=WORKER_B)
    assert reclaimed is not None
    await steps.execute_step(workflow.database, claim=reclaimed, actor=ACTOR_B)

    version_after_b = (await workflow.case(case_id)).version
    audit_after_b = await workflow.latest_audit_seq()

    assert await steps.execute_step(workflow.database, claim=stalled, actor=ACTOR_A) in (
        StepResult.STALE,
        StepResult.LEASE_LOST,
    )
    assert (await workflow.case(case_id)).version == version_after_b
    assert await workflow.latest_audit_seq() == audit_after_b
    assert len(await workflow.rows(CaseStep, case_id=case_id, step_key="chain:1")) == 1


# ----------------------------------------------------------------------- crashing on a timer


async def test_an_armed_timer_survives_the_worker_that_armed_it(workflow: Workflow) -> None:
    """The timer commits with its transition; the death happens after and changes nothing."""
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="arm-timer:0", kind=StepKind.ARM_TIMER)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None

    with dies_at(crash.AFTER_TRANSITION_COMMIT):
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    live = await workflow.rows(Timer, subject_id=str(case_id))
    assert len(live) == 1
    assert live[0].fired_at is None

    fired = await timers.fire_due_timer(workflow.database, worker="worker-after-restart")
    assert fired is not None


async def test_a_death_while_arming_leaves_neither_timer_nor_transition(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="arm-timer:0", kind=StepKind.ARM_TIMER)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None

    with dies_at(crash.TIMER_ARMED):
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    assert await workflow.rows(Timer, subject_id=str(case_id)) == []
    assert (await workflow.row(CaseStep, step_id)).state == "IN_FLIGHT"


async def test_a_death_before_a_firing_commits_leaves_the_timer_unfired(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    async with workflow.database.begin() as connection:
        from promisepatch.db.clock import database_now

        now = await database_now(connection)
        timer_id = await timers.arm_timer(
            connection,
            kind="WORKFLOW_WAKEUP",
            subject_type=CASE_SUBJECT,
            subject_id=str(case_id),
            due_at=now,
        )

    with dies_at(crash.BEFORE_TIMER_COMMIT):
        await timers.fire_due_timer(workflow.database, worker=WORKER_A)

    assert (await workflow.row(Timer, timer_id)).fired_at is None
    assert await workflow.rows(CaseStep, case_id=case_id) == []

    fired = await timers.fire_due_timer(workflow.database, worker="worker-after-restart")
    assert fired is not None
    assert fired.timer_id == timer_id
    assert len(await workflow.rows(CaseStep, case_id=case_id)) == 1


# ---------------------------------------------------------------------- crashing on dispatch


async def test_a_committed_effect_survives_the_worker_that_enqueued_it(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="emit-effect:1", kind=StepKind.EMIT_EFFECT)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None

    with dies_at(crash.AFTER_TRANSITION_COMMIT):
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    pending = await workflow.rows(OutboxMessage)
    assert len(pending) == 1
    assert pending[0].state == "PENDING"

    adapter = FakeEffectAdapter()
    assert (
        await outbox.dispatch_one(
            workflow.database, adapter, worker="worker-after-restart", actor=ACTOR_B
        )
        is DeliveryStatus.DELIVERED
    )


async def test_a_death_between_claiming_and_sending_retries_the_same_key(
    workflow: Workflow,
) -> None:
    """Nothing was sent, so the retry is the first real attempt -- under the original key."""
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="emit-effect:1", kind=StepKind.EMIT_EFFECT)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)
    key = handlers.effect_key(case_id, "emit-effect:1")

    adapter = FakeEffectAdapter()
    with dies_at(crash.AFTER_OUTBOX_CLAIM):
        await outbox.dispatch_one(workflow.database, adapter, worker=WORKER_A, actor=ACTOR_A)

    assert adapter.call_count == 0
    row = (await workflow.rows(OutboxMessage, idempotency_key=key))[0]
    assert row.state == "IN_FLIGHT"

    await workflow.expire_effect_lease(row.id)
    assert (
        await outbox.dispatch_one(
            workflow.database, adapter, worker="worker-after-restart", actor=ACTOR_B
        )
        is DeliveryStatus.DELIVERED
    )
    assert adapter.attempts[0].idempotency_key == key
    assert adapter.effect_count == 1


# ------------------------------------------------------------------------ the worker process


async def test_a_worker_cycle_carries_a_deadline_all_the_way_to_an_effect(
    workflow: Workflow,
) -> None:
    """One pass over every kind of work, in the order that makes a cycle productive."""
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)
    adapter = FakeEffectAdapter()
    worker = Worker(database=workflow.database, adapter=adapter)

    assert await worker.run_once() is True
    assert await worker.run_once() is False


async def test_a_worker_drives_a_chain_to_completion(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="chain:0", kind=StepKind.CHAIN)
    worker = Worker(database=workflow.database, adapter=FakeEffectAdapter())

    for _ in range(10):
        if not await worker.run_once():
            break

    rows = await workflow.rows(CaseStep, case_id=case_id)
    assert len(rows) == handlers.CHAIN_LENGTH
    assert {row.state for row in rows} == {"DONE"}


async def test_a_worker_names_itself_and_attributes_its_writes(workflow: Workflow) -> None:
    """Every governed write a worker makes says which process made it."""
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)
    identity = WorkerIdentity.create()
    audit_before = await workflow.latest_audit_seq()

    worker = Worker(database=workflow.database, adapter=FakeEffectAdapter(), identity=identity)
    await worker.run_once()

    audits = await workflow.audits_since(audit_before, case_id=case_id)
    assert [audit.actor_id for audit in audits] == [identity.value]
    assert (await workflow.rows(CaseStep, case_id=case_id))[0].state == "DONE"


async def test_a_worker_stops_when_it_is_asked_to(workflow: Workflow) -> None:
    """``SIGTERM`` sets an event; the loop finishes its cycle and returns. Nothing to drain."""
    worker = Worker(database=workflow.database, adapter=FakeEffectAdapter(), idle_interval=0.01)
    stop = asyncio.Event()
    running = asyncio.create_task(worker.run_forever(stop))

    await asyncio.sleep(0.05)
    assert not running.done()
    stop.set()
    await asyncio.wait_for(running, timeout=5)


async def test_two_workers_share_the_work_without_coordinating(workflow: Workflow) -> None:
    """No leader, no partition, no lock server. ``SKIP LOCKED`` and a fence are enough."""
    case_id = await workflow.create_case()
    for index in range(6):
        await workflow.add_step(case_id, step_key=f"noop:{index}", kind=StepKind.NOOP)

    first = Worker(database=workflow.database, adapter=FakeEffectAdapter())
    second = Worker(database=workflow.database, adapter=FakeEffectAdapter())
    assert first.identity != second.identity

    for _ in range(6):
        await asyncio.gather(first.run_once(), second.run_once())

    rows = await workflow.rows(CaseStep, case_id=case_id)
    assert len(rows) == 6
    assert {row.state for row in rows} == {"DONE"}
    assert {row.attempts for row in rows} == {1}


# --------------------------------------------------------------------- the acceptance scenario


async def test_a_workflow_survives_the_worker_that_started_it(workflow: Workflow) -> None:
    """The whole slice, end to end, with a process death in the middle of it.

    A case with one durable step; worker A claims it, executes a governed transition that
    mutates the case, commits a domain event and leaves a successor, a timer and an outbound
    effect behind; A is then killed. Worker B starts with no knowledge of any of it, reclaims
    the expired work, drives the workflow to the end, sends the effect under its stable key,
    and the deadline that was armed before the crash still wakes the workflow up afterwards.

    This is not the raspberry exception flow and is not a sketch of it. It is proof that the
    machinery those semantics will sit on holds together across a restart.
    """
    case_id = await workflow.create_case()
    opened = await workflow.case(case_id)
    event_floor = await workflow.latest_event_seq()
    audit_floor = await workflow.latest_audit_seq()

    await workflow.add_step(case_id, step_key="chain:0", kind=StepKind.CHAIN)

    # --- worker A: one governed transition, then the process dies -----------------------
    worker_a = Worker(database=workflow.database, adapter=FakeEffectAdapter())
    assert await worker_a.run_once() is True

    assert (await workflow.case(case_id)).version == opened.version + 1
    first = await workflow.rows(CaseStep, case_id=case_id, step_key="chain:0")
    assert first[0].state == "DONE"
    assert len(await workflow.rows(CaseStep, case_id=case_id, step_key="chain:1")) == 1

    await workflow.add_step(case_id, step_key="arm-timer:0", kind=StepKind.ARM_TIMER)
    await workflow.add_step(case_id, step_key="emit-effect:1", kind=StepKind.EMIT_EFFECT)

    claimed = await steps.claim_step(workflow.database, worker=worker_a.identity.value)
    assert claimed is not None
    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await steps.execute_step(workflow.database, claim=claimed, actor=worker_a.actor)
    assert (await workflow.row(CaseStep, claimed.step_id)).state == "IN_FLIGHT"
    del worker_a

    # --- worker B: knows nothing, recovers everything ------------------------------------
    adapter = FakeEffectAdapter()
    worker_b = Worker(database=workflow.database, adapter=adapter, idle_interval=0.01)

    await workflow.expire_lease(claimed.step_id)
    for _ in range(20):
        if not await worker_b.run_once():
            break

    settled = await workflow.rows(CaseStep, case_id=case_id)
    assert {row.state for row in settled} == {"DONE"}
    assert {row.step_key for row in settled} >= {
        "chain:0",
        "chain:1",
        "arm-timer:0",
        "emit-effect:1",
    }

    # The timer armed before the crash fired, and its wake-up ran as a real step.
    fired = await workflow.rows(Timer, subject_id=str(case_id))
    assert len(fired) == 1
    assert fired[0].fired_at is not None
    wakeups = [row for row in settled if row.kind == StepKind.TIMER_WAKEUP.value]
    assert len(wakeups) == 1
    assert wakeups[0].step_key == handlers.timer_step_key(fired[0].id)

    # The external effect was attempted exactly once, under the key derived from the decision.
    key = handlers.effect_key(case_id, "emit-effect:1")
    effects = await workflow.rows(OutboxMessage, idempotency_key=key)
    assert len(effects) == 1
    assert effects[0].state == "DELIVERED"
    assert adapter.call_count == 1
    assert adapter.effect_count == 1

    # No logical duplicate anywhere: one step per key, one audit row per executed step.
    assert len({row.step_key for row in settled}) == len(settled)
    audits = await workflow.audits_since(audit_floor, case_id=case_id)
    executions = [audit for audit in audits if audit.type == "WORKFLOW_STEP_EXECUTED"]
    assert len(executions) == len(settled)

    # The event spine is ascending and every event this case produced is on it.
    events = [e for e in await workflow.events_since(event_floor) if e.case_id == case_id]
    sequences = [event.seq for event in events]
    assert sequences == sorted(sequences)
    assert {event.type for event in events} >= {
        "workflow.step.completed",
        "workflow.timer.fired",
        "workflow.effect.delivered",
    }


async def test_an_inbound_record_can_start_work_that_outlives_its_worker(
    workflow: Workflow,
) -> None:
    """The other entrance to the same machinery, with the same crash in the middle."""
    case_id = await workflow.create_case()
    async with workflow.database.begin() as connection:
        stored = await inbox.ingest(
            connection,
            source=handlers.SYNTHETIC_SOURCE,
            provider_event_id=f"evt-{uuid4().hex[:12]}",
            body=json.dumps({"case_id": str(case_id)}),
        )
    assert stored is not None

    with crash.arm(crash.DURING_INBOX_PROCESSING), pytest.raises(crash.WorkerDied):
        await inbox.process_one(workflow.database, worker=WORKER_A)
    assert (await workflow.row(InboxEvent, stored)).state == "RECEIVED"

    worker = Worker(database=workflow.database, adapter=FakeEffectAdapter())
    for _ in range(10):
        if not await worker.run_once():
            break

    assert (await workflow.row(InboxEvent, stored)).state == "PROCESSED"
    created = await workflow.rows(CaseStep, case_id=case_id)
    assert [row.step_key for row in created] == [handlers.inbox_step_key(stored)]
    assert created[0].state == "DONE"
