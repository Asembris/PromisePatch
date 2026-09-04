"""Outbound effects, and the honest limit of what an outbox can promise.

The guarantee being tested is **at-least-once delivery under a stable idempotency key**, not
exactly-once anything. The clearest expression of that is
:func:`test_a_death_after_the_provider_accepted_sends_the_same_key_again`: the provider is
called twice, deliberately, and the reason that is acceptable is that both calls carry the
identical key -- so a provider that honours keys records one effect, and a provider that does
not would record two and we would not be able to stop it.

Everything else here is about the two boundaries that make that window as small as it can be:
the claim commits before anything is sent, and the acknowledgement is fenced so a dispatcher
that lost its lease cannot overwrite the result of the one that took over.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from _workflow_support import Workflow
from sqlalchemy import text

from promisepatch.db.models import OutboxMessage
from promisepatch.db.uow import Actor
from promisepatch.domain import crash, outbox, steps
from promisepatch.domain.adapters import FakeEffectAdapter
from promisepatch.domain.handlers import effect_key
from promisepatch.domain.model import (
    EVENT_EFFECT_DELIVERED,
    DeliveryOutcome,
    DeliveryStatus,
    StepKind,
    StepResult,
)

pytestmark = pytest.mark.integration

WORKER_A = "worker-a"
WORKER_B = "worker-b"
ACTOR_A = Actor(kind="SYSTEM", id=WORKER_A)

RETRYABLE = DeliveryOutcome(status=DeliveryStatus.RETRYABLE, error="provider timed out")
TERMINAL = DeliveryOutcome(status=DeliveryStatus.TERMINAL, error="provider rejected the payload")


async def emit(workflow: Workflow, *, case_id: UUID, step_key: str = "emit-effect:1") -> str:
    """Run one ``EMIT_EFFECT`` step, and return the key of the effect it enqueued."""
    await workflow.add_step(case_id, step_key=step_key, kind=StepKind.EMIT_EFFECT)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    assert (
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)
        is StepResult.COMPLETED
    )
    return effect_key(case_id, step_key)


# ---------------------------------------------------------------------------------- enqueue


async def test_an_effect_exists_exactly_when_its_transition_committed(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    key = await emit(workflow, case_id=case_id)

    rows = await workflow.rows(OutboxMessage, idempotency_key=key)
    assert len(rows) == 1
    assert rows[0].state == "PENDING"
    assert rows[0].attempts == 0
    assert rows[0].payload["case_id"] == str(case_id)


async def test_a_rolled_back_transition_leaves_no_effect(workflow: Workflow) -> None:
    """No cause, no effect -- the row and the decision share one transaction and one fate."""
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="emit-effect:1", kind=StepKind.EMIT_EFFECT)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None

    with (
        crash.arm(crash.BEFORE_TRANSITION_COMMIT),
        pytest.raises(crash.WorkerDied),
    ):
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    assert await workflow.rows(OutboxMessage) == []


async def test_an_effect_records_the_event_it_was_created_alongside(workflow: Workflow) -> None:
    """``created_in_tx_seq`` is stamped after the append, on rows this transaction owns."""
    case_id = await workflow.create_case()
    key = await emit(workflow, case_id=case_id)
    row = (await workflow.rows(OutboxMessage, idempotency_key=key))[0]
    assert row.created_in_tx_seq is not None


async def test_a_duplicate_key_rolls_the_whole_transition_back(workflow: Workflow) -> None:
    """A collision means two decisions believe they are the same one -- a bug, not a race.

    The transition that hit it commits nothing at all: no step completion, no case version
    bump, no successor. Minting a fresh key instead would turn one intended effect into two
    real ones, which is the failure this refuses to have.
    """
    case_id = await workflow.create_case()
    key = await emit(workflow, case_id=case_id, step_key="emit-effect:1")

    # A second case whose step key matches would derive a different key, so the collision has
    # to be staged: the same case and the same step key, replayed after the row was cleared.
    async with workflow.database.begin() as connection:
        await connection.execute(
            text("DELETE FROM promisepatch.case_steps WHERE case_id = :case"), {"case": case_id}
        )
    before = await workflow.case(case_id)

    await workflow.add_step(case_id, step_key="emit-effect:1", kind=StepKind.EMIT_EFFECT)
    claim = await steps.claim_step(workflow.database, worker=WORKER_A)
    assert claim is not None
    with pytest.raises(outbox.DuplicateEffectError):
        await steps.execute_step(workflow.database, claim=claim, actor=ACTOR_A)

    assert len(await workflow.rows(OutboxMessage, idempotency_key=key)) == 1
    assert (await workflow.case(case_id)).version == before.version


# ------------------------------------------------------------------------- claim and deliver


async def test_a_claim_commits_before_anything_is_sent(workflow: Workflow) -> None:
    """Which is what makes the uncertain window recoverable instead of invisible."""
    case_id = await workflow.create_case()
    await emit(workflow, case_id=case_id)

    claim = await outbox.claim_effect(workflow.database, worker=WORKER_A)
    assert claim is not None
    row = await workflow.row(OutboxMessage, claim.effect_id)
    assert row.state == "IN_FLIGHT"
    assert row.attempts == 1
    assert row.lease_owner == WORKER_A


async def test_two_dispatchers_cannot_claim_one_message(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    await emit(workflow, case_id=case_id)

    assert await outbox.claim_effect(workflow.database, worker=WORKER_A) is not None
    assert await outbox.claim_effect(workflow.database, worker=WORKER_B) is None


async def test_an_expired_dispatch_lease_is_reclaimable(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    await emit(workflow, case_id=case_id)
    first = await outbox.claim_effect(workflow.database, worker=WORKER_A)
    assert first is not None

    await workflow.expire_effect_lease(first.effect_id)
    second = await outbox.claim_effect(workflow.database, worker=WORKER_B)
    assert second is not None
    assert second.attempts == first.attempts + 1


async def test_a_successful_delivery_is_recorded_with_the_providers_reference(
    workflow: Workflow,
) -> None:
    case_id = await workflow.create_case()
    key = await emit(workflow, case_id=case_id)
    adapter = FakeEffectAdapter()
    before = await workflow.latest_event_seq()

    status = await outbox.dispatch_one(workflow.database, adapter, worker=WORKER_A, actor=ACTOR_A)
    assert status is DeliveryStatus.DELIVERED

    row = (await workflow.rows(OutboxMessage, idempotency_key=key))[0]
    assert row.state == "DELIVERED"
    assert row.delivered_at is not None
    assert row.provider_ref
    assert row.lease_owner is None

    events = [e for e in await workflow.events_since(before) if e.type == EVENT_EFFECT_DELIVERED]
    assert len(events) == 1


async def test_a_delivered_message_is_never_sent_again(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    await emit(workflow, case_id=case_id)
    adapter = FakeEffectAdapter()

    await outbox.dispatch_one(workflow.database, adapter, worker=WORKER_A, actor=ACTOR_A)
    assert (
        await outbox.dispatch_one(workflow.database, adapter, worker=WORKER_A, actor=ACTOR_A)
        is None
    )
    assert adapter.call_count == 1


# ------------------------------------------------------------------------------ retry ladder


async def test_a_timeout_schedules_a_retry_and_keeps_the_key(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    key = await emit(workflow, case_id=case_id)
    adapter = FakeEffectAdapter(fail_with=RETRYABLE)

    status = await outbox.dispatch_one(workflow.database, adapter, worker=WORKER_A, actor=ACTOR_A)
    assert status is DeliveryStatus.RETRYABLE

    row = (await workflow.rows(OutboxMessage, idempotency_key=key))[0]
    assert row.state == "PENDING"
    assert row.next_attempt_at is not None
    assert row.last_error == RETRYABLE.error
    assert row.idempotency_key == key


async def test_a_retry_presents_the_identical_key(workflow: Workflow) -> None:
    """The key is the row's, not the attempt's. That is the whole of the idempotency story."""
    case_id = await workflow.create_case()
    key = await emit(workflow, case_id=case_id)
    adapter = FakeEffectAdapter(fail_with=RETRYABLE)

    row = (await workflow.rows(OutboxMessage, idempotency_key=key))[0]
    for _ in range(3):
        await outbox.dispatch_one(workflow.database, adapter, worker=WORKER_A, actor=ACTOR_A)
        await workflow.make_effect_due(row.id)

    assert {attempt.idempotency_key for attempt in adapter.attempts} == {key}
    assert adapter.call_count == 3


async def test_the_ladder_ends_in_a_recorded_terminal_failure(workflow: Workflow) -> None:
    from promisepatch.domain.retry import MAX_ATTEMPTS

    case_id = await workflow.create_case()
    key = await emit(workflow, case_id=case_id)
    adapter = FakeEffectAdapter(fail_with=RETRYABLE)
    row_id = (await workflow.rows(OutboxMessage, idempotency_key=key))[0].id

    statuses = []
    for _ in range(MAX_ATTEMPTS):
        statuses.append(
            await outbox.dispatch_one(workflow.database, adapter, worker=WORKER_A, actor=ACTOR_A)
        )
        await workflow.make_effect_due(row_id)

    assert statuses[-1] is DeliveryStatus.TERMINAL
    row = await workflow.row(OutboxMessage, row_id)
    assert row.state == "FAILED"
    assert row.attempts == MAX_ATTEMPTS
    assert (
        await outbox.dispatch_one(workflow.database, adapter, worker=WORKER_A, actor=ACTOR_A)
        is None
    )


async def test_a_terminal_failure_on_a_case_linked_effect_raises_owner_attention(
    workflow: Workflow,
) -> None:
    """An effect that will never happen is a promise nobody is keeping. Someone has to know."""
    case_id = await workflow.create_case()
    await emit(workflow, case_id=case_id)
    audit_before = await workflow.latest_audit_seq()

    status = await outbox.dispatch_one(
        workflow.database, FakeEffectAdapter(fail_with=TERMINAL), worker=WORKER_A, actor=ACTOR_A
    )
    assert status is DeliveryStatus.TERMINAL
    assert (await workflow.case(case_id)).needs_owner_attention is True

    audits = await workflow.audits_since(audit_before, case_id=case_id)
    assert [audit.type for audit in audits] == ["WORKFLOW_EFFECT_FAILED"]


# ------------------------------------------------------------------------- the honest window


async def test_a_death_after_the_provider_accepted_sends_the_same_key_again(
    workflow: Workflow,
) -> None:
    """The uncertain window, and the guarantee we actually make about it.

    The dispatcher dies between the provider accepting and the acknowledgement committing. The
    lease expires, the message is retried, and the provider is called a *second* time -- which
    is at-least-once, exactly as documented. What makes that acceptable is the key: both calls
    carry it, so the fake provider (like any provider honouring idempotency keys) records one
    logical effect. A provider without key support would record two, and nothing on our side
    could prevent it.
    """
    case_id = await workflow.create_case()
    key = await emit(workflow, case_id=case_id)
    adapter = FakeEffectAdapter()

    with (
        crash.arm(crash.AFTER_EXTERNAL_SUCCESS),
        pytest.raises(crash.WorkerDied),
    ):
        await outbox.dispatch_one(workflow.database, adapter, worker=WORKER_A, actor=ACTOR_A)

    row = (await workflow.rows(OutboxMessage, idempotency_key=key))[0]
    assert row.state == "IN_FLIGHT"
    assert row.delivered_at is None
    assert adapter.call_count == 1

    await workflow.expire_effect_lease(row.id)
    status = await outbox.dispatch_one(workflow.database, adapter, worker=WORKER_B, actor=ACTOR_A)
    assert status is DeliveryStatus.DELIVERED

    assert adapter.call_count == 2
    assert {attempt.idempotency_key for attempt in adapter.attempts} == {key}
    assert adapter.effect_count == 1

    settled = (await workflow.rows(OutboxMessage, idempotency_key=key))[0]
    assert settled.state == "DELIVERED"
    assert settled.attempts == 2


async def test_a_dispatcher_that_lost_its_lease_cannot_record_a_result(workflow: Workflow) -> None:
    case_id = await workflow.create_case()
    await emit(workflow, case_id=case_id)

    stalled = await outbox.claim_effect(workflow.database, worker=WORKER_A)
    assert stalled is not None
    await workflow.expire_effect_lease(stalled.effect_id)
    reclaimed = await outbox.claim_effect(workflow.database, worker=WORKER_B)
    assert reclaimed is not None

    with pytest.raises(outbox.EffectLeaseLostError):
        await outbox.record_delivery(
            workflow.database,
            claim=stalled,
            outcome=DeliveryOutcome(status=DeliveryStatus.DELIVERED, provider_ref="stale"),
            actor=ACTOR_A,
        )

    row = await workflow.row(OutboxMessage, stalled.effect_id)
    assert row.state == "IN_FLIGHT"
    assert row.provider_ref is None


async def test_a_committed_pending_effect_survives_the_worker_that_created_it(
    workflow: Workflow,
) -> None:
    """Nothing is held in the process; a fresh dispatcher finds the row and sends it."""
    case_id = await workflow.create_case()
    key = await emit(workflow, case_id=case_id)

    fresh = FakeEffectAdapter()
    assert (
        await outbox.dispatch_one(
            workflow.database, fresh, worker="worker-after-restart", actor=ACTOR_A
        )
        is DeliveryStatus.DELIVERED
    )
    assert fresh.attempts[0].idempotency_key == key
