"""Claiming, leasing, fencing, and the stale worker that must not be able to write.

The whole file is about one hazard::

    A claims attempt N → A stalls → A's lease expires → B reclaims as attempt N+1
    → B executes and commits → A wakes up and tries to finish

If A's write lands, the case is mutated twice, a successor may exist twice, the audit ledger
records two authorisations for one piece of work, and A's stale result overwrites B's. The
protocol that makes it impossible is ``(state, lease_owner, attempts)``: checked under the row
lock at the start of A's transaction and repeated on its final update, which must affect
exactly one row.

Nothing here sleeps. A lease expires because its expiry is moved into the past, which is what
the passage of time would have done and is deterministic in a way that waiting is not.
"""

from __future__ import annotations

import pytest
from _workflow_support import Workflow
from sqlalchemy import text

from promisepatch.db.models import CaseStep
from promisepatch.db.uow import Actor
from promisepatch.domain import steps
from promisepatch.domain.model import StepKind, StepResult

pytestmark = pytest.mark.integration

WORKER_A = "worker-a"
WORKER_B = "worker-b"
ACTOR_A = Actor(kind="SYSTEM", id=WORKER_A)
ACTOR_B = Actor(kind="SYSTEM", id=WORKER_B)


# ------------------------------------------------------------------------------------ claiming


async def test_a_claim_marks_the_step_in_flight_and_takes_the_fencing_token(
    workflow: Workflow,
) -> None:
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)

    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    assert claim.attempts == 1

    row = await workflow.row(CaseStep, claim.step_id)
    assert row.state == "IN_FLIGHT"
    assert row.lease_owner == WORKER_A
    assert row.lease_expires_at is not None
    assert row.started_at is not None


async def test_two_workers_cannot_own_the_same_step(workflow: Workflow) -> None:
    """One row, one claim. The loser gets nothing rather than a second claim on the same work."""
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)

    first = await steps.claim_step(workflow.database, worker=WORKER_A)
    second = await steps.claim_step(workflow.database, worker=WORKER_B)

    assert first is not None
    assert second is None


async def test_skip_locked_lets_workers_take_different_steps(workflow: Workflow) -> None:
    """Two workers sweeping at once do twice the work, not the same work twice."""
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)
    await workflow.add_step(case_id, step_key="noop:2", kind=StepKind.NOOP)

    first = await steps.claim_step(workflow.database, worker=WORKER_A)
    second = await steps.claim_step(workflow.database, worker=WORKER_B)

    assert first is not None
    assert second is not None
    assert first.step_id != second.step_id


async def test_a_live_lease_cannot_be_stolen(workflow: Workflow) -> None:
    """Being slow is not the same as being dead, and the difference is the lease."""
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)
    await steps.claim_step(workflow.database, worker=WORKER_A)

    assert await steps.claim_step(workflow.database, worker=WORKER_B) is None


async def test_an_expired_lease_is_reclaimable_and_bumps_the_fencing_token(
    workflow: Workflow,
) -> None:
    """This is how a killed worker's step comes back, and why its old claim stops matching."""
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)

    first = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert first is not None
    await workflow.expire_lease(step_id)

    second = await steps.claim_step(workflow.database, worker=WORKER_B)
    assert second is not None
    assert second.step_id == first.step_id
    assert second.attempts == first.attempts + 1
    assert second.lease_owner == WORKER_B


async def test_a_retry_scheduled_for_later_is_not_claimable_yet(workflow: Workflow) -> None:
    """``next_attempt_at`` is compared against the database's clock, not any process's."""
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None

    async with workflow.database.begin() as connection:
        await connection.execute(
            text(
                "UPDATE promisepatch.case_steps SET state = 'RETRYING',"
                " lease_owner = NULL, lease_expires_at = NULL,"
                " next_attempt_at = now() + interval '1 hour' WHERE id = :id"
            ),
            {"id": claim.step_id},
        )

    assert await steps.claim_step(workflow.database, worker=WORKER_B) is None


async def test_a_due_retry_is_claimable(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="fail:1", kind=StepKind.FAIL_RETRYABLE)

    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    assert (
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)
        is StepResult.RETRY_SCHEDULED
    )
    assert await steps.claim_step(workflow.database, worker=WORKER_B) is None

    await workflow.make_due(step_id)
    again = await steps.claim_step(workflow.database, worker=WORKER_B)
    assert again is not None
    assert again.attempts == 2


@pytest.mark.parametrize("state", ["DONE", "FAILED", "SKIPPED"])
async def test_a_settled_step_is_never_claimed_again(workflow: Workflow, state: str) -> None:
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)
    async with workflow.database.begin() as connection:
        await connection.execute(
            text("UPDATE promisepatch.case_steps SET state = :state WHERE id = :id"),
            {"state": state, "id": step_id},
        )

    assert await steps.claim_step(workflow.database, worker=WORKER_A) is None


async def test_a_worker_holding_the_execution_row_lock_cannot_be_reclaimed_from(
    workflow: Workflow, app_database_url: str
) -> None:
    """The complementary case: an expired lease on a row somebody is *actively* writing.

    ``SKIP LOCKED`` skips it, which is the correct answer -- the row lock says a transaction is
    in the middle of that step right now, and the reclaim sweep must not queue behind it or
    steal it.
    """
    from promisepatch.db import build_engine

    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    await workflow.expire_lease(step_id)

    engine = build_engine(app_database_url, pool_size=1)
    try:
        async with engine.connect() as holder:
            await holder.execute(
                text("SELECT 1 FROM promisepatch.case_steps WHERE id = :id FOR UPDATE"),
                {"id": step_id},
            )
            assert await steps.claim_step(workflow.database, worker=WORKER_B) is None
            await holder.rollback()

        assert await steps.claim_step(workflow.database, worker=WORKER_B) is not None
    finally:
        await engine.dispose()


# ------------------------------------------------------------------------------- stale worker


async def test_a_stale_worker_cannot_overwrite_the_work_that_replaced_it(
    workflow: Workflow,
) -> None:
    """The scenario the whole protocol exists for, end to end.

    Everything asserted afterwards is a thing that would have happened twice if the fence had
    not held: the case mutated, a successor enqueued, an audit row written, an event appended.
    """
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="chain:0", kind=StepKind.CHAIN)

    stalled = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert stalled is not None

    await workflow.expire_lease(step_id)
    reclaimed = await steps.claim_step(workflow.database, worker=WORKER_B)
    assert reclaimed is not None
    assert reclaimed.attempts == stalled.attempts + 1

    audit_before = await workflow.latest_audit_seq()
    event_before = await workflow.latest_event_seq()

    assert (
        await steps.execute_step(workflow.database, claim=reclaimed, actor=ACTOR_B)
        is StepResult.COMPLETED
    )
    case_after_b = await workflow.case(case_id)
    settled = await workflow.row(CaseStep, step_id)

    audit_after_b = await workflow.latest_audit_seq()
    event_after_b = await workflow.latest_event_seq()

    # A wakes up and tries to finish the work it was claimed to be doing. It finds the step
    # settled rather than merely reassigned -- B got all the way to DONE -- so the fence reports
    # STALE. The distinction is diagnostic only: both refuse, and both write nothing.
    assert (
        await steps.execute_step(workflow.database, claim=stalled, actor=ACTOR_A)
        is StepResult.STALE
    )

    assert (await workflow.case(case_id)).version == case_after_b.version
    assert (await workflow.row(CaseStep, step_id)).result == settled.result
    assert (await workflow.row(CaseStep, step_id)).state == "DONE"
    assert await workflow.latest_audit_seq() == audit_after_b
    assert await workflow.latest_event_seq() == event_after_b

    successors = await workflow.rows(CaseStep, case_id=case_id, step_key="chain:1")
    assert len(successors) == 1

    audits = await workflow.audits_since(audit_before, case_id=case_id)
    assert len(audits) == 1
    events = [
        event for event in await workflow.events_since(event_before) if event.case_id == case_id
    ]
    assert len(events) == 1


async def test_a_reclaimed_step_rejects_its_previous_owner_before_anyone_finishes_it(
    workflow: Workflow,
) -> None:
    """The narrower window: B has taken the step over but has not run it yet.

    A must be refused *here* too, not merely once B has committed something -- otherwise the two
    of them would execute the same attempt concurrently and race to the final update.
    """
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)

    stalled = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert stalled is not None
    await workflow.expire_lease(step_id)
    reclaimed = await steps.claim_step(workflow.database, worker=WORKER_B)
    assert reclaimed is not None

    audit_before = await workflow.latest_audit_seq()
    assert (
        await steps.execute_step(workflow.database, claim=stalled, actor=ACTOR_A)
        is StepResult.LEASE_LOST
    )
    assert await workflow.audits_since(audit_before, case_id=case_id) == []

    # B is unaffected by A's attempt and completes normally.
    assert (
        await steps.execute_step(workflow.database, claim=reclaimed, actor=ACTOR_B)
        is StepResult.COMPLETED
    )


async def test_a_stale_worker_writes_nothing_when_the_step_was_already_settled(
    workflow: Workflow,
) -> None:
    """The other half of the fence: not reclaimed, just finished. Different word, same silence."""
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None

    async with workflow.database.begin() as connection:
        await connection.execute(
            text(
                "UPDATE promisepatch.case_steps SET state = 'DONE',"
                " lease_owner = NULL, lease_expires_at = NULL WHERE id = :id"
            ),
            {"id": step_id},
        )

    audit_before = await workflow.latest_audit_seq()
    event_before = await workflow.latest_event_seq()

    assert (
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A) is StepResult.STALE
    )
    assert await workflow.latest_audit_seq() == audit_before
    assert await workflow.latest_event_seq() == event_before


async def test_a_step_deleted_under_a_worker_is_stale_rather_than_a_crash(
    workflow: Workflow,
) -> None:
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None

    async with workflow.database.begin() as connection:
        await connection.execute(
            text("DELETE FROM promisepatch.case_steps WHERE id = :id"), {"id": step_id}
        )

    assert (
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A) is StepResult.STALE
    )


# --------------------------------------------------------------------------------- execution


async def test_a_completed_step_records_its_result_and_releases_its_lease(
    workflow: Workflow,
) -> None:
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None

    assert (
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)
        is StepResult.COMPLETED
    )
    row = await workflow.row(CaseStep, step_id)
    assert row.state == "DONE"
    assert row.done_at is not None
    assert row.lease_owner is None
    assert row.lease_expires_at is None
    assert row.result == {"kind": "NOOP"}


async def test_a_transition_bumps_the_case_version(workflow: Workflow) -> None:
    """A step that ran is a different case afterwards, whatever it did to the state column."""
    case_id = await workflow.create_case()
    before = await workflow.case(case_id)
    await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)

    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    assert (await workflow.case(case_id)).version == before.version + 1


async def test_a_guard_reads_the_case_state_the_transaction_locked(workflow: Workflow) -> None:
    case_id = await workflow.create_case(state="RESOLVED")
    step_id = await workflow.add_step(case_id, step_key="guard:1", kind=StepKind.SKIP_IF_TERMINAL)

    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    assert (
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)
        is StepResult.SKIPPED
    )
    assert (await workflow.row(CaseStep, step_id)).state == "SKIPPED"


async def test_a_chain_walks_to_its_end_one_claim_at_a_time(workflow: Workflow) -> None:
    """Each link is enqueued by the transition that committed the previous one."""
    from promisepatch.domain.handlers import CHAIN_LENGTH

    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="chain:0", kind=StepKind.CHAIN)

    executed = 0
    while (claim := await steps.claim_step(workflow.database, worker=WORKER_A)) is not None:
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)
        executed += 1

    assert executed == CHAIN_LENGTH
    rows = await workflow.rows(CaseStep, case_id=case_id)
    assert len(rows) == CHAIN_LENGTH
    assert {row.state for row in rows} == {"DONE"}


# ------------------------------------------------------------------------- failure semantics


async def test_a_retryable_failure_schedules_a_later_attempt_and_audits_nothing(
    workflow: Workflow,
) -> None:
    """Retry bookkeeping is the engine's own scheduling, not a decision about a promise."""
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="fail:1", kind=StepKind.FAIL_RETRYABLE)
    audit_before = await workflow.latest_audit_seq()

    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    assert (
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)
        is StepResult.RETRY_SCHEDULED
    )

    row = await workflow.row(CaseStep, step_id)
    assert row.state == "RETRYING"
    assert row.next_attempt_at is not None
    assert row.lease_owner is None
    assert row.error
    assert await workflow.audits_since(audit_before, case_id=case_id) == []


async def test_the_ladder_ends_in_escalation_rather_than_in_more_retries(
    workflow: Workflow,
) -> None:
    """Five attempts, then the case is somebody's problem and the ledger says so."""
    from promisepatch.domain.retry import MAX_ATTEMPTS

    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="fail:1", kind=StepKind.FAIL_RETRYABLE)
    audit_before = await workflow.latest_audit_seq()

    results = []
    for _ in range(MAX_ATTEMPTS):
        claim = await steps.claim_step(workflow.database, worker=WORKER_A)
        assert claim is not None
        results.append(await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A))
        await workflow.make_due(step_id)

    assert results[:-1] == [StepResult.RETRY_SCHEDULED] * (MAX_ATTEMPTS - 1)
    assert results[-1] is StepResult.FAILED

    row = await workflow.row(CaseStep, step_id)
    assert row.state == "FAILED"
    assert row.attempts == MAX_ATTEMPTS
    assert (await workflow.case(case_id)).needs_owner_attention is True

    audits = await workflow.audits_since(audit_before, case_id=case_id)
    assert [audit.type for audit in audits] == ["WORKFLOW_STEP_FAILED"]
    assert await steps.claim_step(workflow.database, worker=WORKER_A) is None


async def test_a_terminal_failure_escalates_immediately(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="fail:1", kind=StepKind.FAIL_TERMINAL)
    audit_before = await workflow.latest_audit_seq()

    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    assert (
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A) is StepResult.FAILED
    )

    assert (await workflow.row(CaseStep, step_id)).state == "FAILED"
    assert (await workflow.case(case_id)).needs_owner_attention is True
    audits = await workflow.audits_since(audit_before, case_id=case_id)
    assert [audit.type for audit in audits] == ["WORKFLOW_STEP_FAILED"]
    assert audits[0].authority == "NONE"
    assert audits[0].actor_kind == "SYSTEM"
