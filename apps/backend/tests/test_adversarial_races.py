"""What happens when the world moves between a decision and the effect it authorised.

Every other race file in this suite asks its question *sequentially*: worker A acts, then
worker B acts, and the interleaving is produced by writing the two calls in an order. That is
the right way to prove a fence, because a fence is a predicate and a predicate does not care
when it was evaluated. It is not enough for two other questions, and this file exists for
those two.

**Real contention, not a written-down order.** Section 1 races four genuinely independent
PostgreSQL sessions -- four engines, four pools, four connections -- at one ready row through
``asyncio.gather``. Nothing here decides who wins; the database does, and the assertion is
that exactly one of them is told it may proceed. A sequential test cannot ask this, because
the loser it constructs never contended for anything.

**Receiver-side, not database-side.** The existing fencing proofs assert that a stale worker
wrote no row -- no case version, no successor, no audit, no event. None of them follows the
chain to the end and asserts what the *provider* saw, which is the only place a duplicate
would be a duplicate a customer could feel. Section 2 drives the whole path with a recording
adapter in it and counts the calls.

The four interleavings each carry the same five lines, because a race nobody wrote down is a
race nobody can re-run:

============ =============================================================================
initial      what exists before anything contends
race         the interleaving, and what forces it
invariant    the property being attacked
receiver     what the provider actually saw, counted
fail-closed  the expected refusal, named
============ =============================================================================

**Nothing here sleeps to create a race.** Leases expire because their expiry is moved into
the past, which is what time would have done; concurrency is produced by ``asyncio.gather``
over independent connections, which either contends or does not. A test that waited would be
asserting a scheduler's habits.

Two races this file does *not* re-prove, because they are already pinned and the roadmap
forbids duplicating a core test for the count: the stale-plan revalidation family in
``test_recovery_revalidation.py`` -- order version, substitute stock, recipe pin, constraint
snapshot, production task and the change that lands *after* a passing checklist -- and the
duplicate-delivery family in ``test_workflow_inbox.py``, ``test_workflow_outbox.py`` and
``test_customer_approval.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Final
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from _intake_support import BAKER, RASPBERRY_ONLY, Intake
from _intake_support import physical as physical
from _workflow_support import Workflow
from sqlalchemy import select

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import ApprovalRequestState
from promisepatch.db import RuntimeDatabase, build_engine
from promisepatch.db.models import CaseStep, OutboxMessage
from promisepatch.db.uow import Actor
from promisepatch.domain import steps, withdrawal
from promisepatch.domain.adapters import FakeEffectAdapter
from promisepatch.domain.handlers import effect_key
from promisepatch.domain.model import (
    EFFECT_ORDER_AMEND,
    FAKE_EFFECT_KIND,
    TERMINAL_CASE_STATES,
    StepKind,
    StepResult,
)

pytestmark = pytest.mark.integration

CONTENDERS: Final = 4
"""How many independent sessions race for one row.

Four rather than two: two contenders can pass a broken ``SKIP LOCKED`` by luck often enough
that a flake looks like a pass, and four costs four connections.
"""


@pytest_asyncio.fixture
async def sessions(app_database_url: str) -> AsyncIterator[tuple[RuntimeDatabase, ...]]:
    """Independent database handles, one pool each, so a claim really is another session's.

    ``pool_size=1`` is the point rather than an economy: a handle that could hand out a second
    connection would let one contender queue behind itself, and the race would be with the pool
    instead of with PostgreSQL.
    """
    built = tuple(
        RuntimeDatabase(engine=build_engine(app_database_url, pool_size=1))
        for _ in range(CONTENDERS)
    )
    try:
        yield built
    finally:
        for handle in built:
            await handle.dispose()


def _worker(index: int) -> str:
    return f"contender-{index}"


def _actor(index: int) -> Actor:
    return Actor(kind="SYSTEM", id=_worker(index))


# ============================================================ 1. concurrent claim, for real


async def test_four_independent_sessions_racing_one_step_leave_exactly_one_owner(
    workflow: Workflow, sessions: tuple[RuntimeDatabase, ...]
) -> None:
    """initial: one ``PENDING`` step, nothing claimed.

    race: four separate PostgreSQL sessions call :func:`~promisepatch.domain.steps.claim_step`
    inside one ``asyncio.gather``, so the interleaving is the database's and not this test's.
    invariant: a claim is exclusive -- ``FOR UPDATE SKIP LOCKED`` plus the conditional update
    must hand the row to one session and tell the rest there was nothing to take.
    receiver: nothing is executed here, so nothing reaches a provider.
    fail-closed: three of the four get ``None``, which is the same answer they would get from
    an empty queue. A loser is never given a second claim on the same work.
    """
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="noop:1", kind=StepKind.NOOP)

    claims = await asyncio.gather(
        *(
            steps.claim_step(handle, worker=_worker(index))
            for index, handle in enumerate(sessions)
        )
    )

    won = [claim for claim in claims if claim is not None]
    assert len(won) == 1, f"{len(won)} sessions were told they own the same step"
    # The fencing token is the *first* attempt, so no loser silently bumped it on the way past.
    assert won[0].attempts == 1
    row = await workflow.row(CaseStep, won[0].step_id)
    assert row.state == "IN_FLIGHT"
    assert row.lease_owner == won[0].lease_owner
    assert row.attempts == 1


async def test_racing_sessions_that_all_execute_deliver_one_effect_to_the_provider(
    workflow: Workflow, sessions: tuple[RuntimeDatabase, ...]
) -> None:
    """initial: one ``PENDING`` ``EMIT_EFFECT`` step -- the kind whose transition enqueues an
    outbound effect, so the race has somewhere to show up outside the database.

    race: four independent sessions claim concurrently, and then every session that won
    *executes* concurrently as well. Both halves are one ``gather``.
    invariant: exactly one transition commits, so exactly one effect is enqueued, so the
    provider is called about this step exactly once.
    receiver: ``adapter.attempts`` -- every call including redeliveries -- is counted, not just
    the logical effects the adapter deduplicates. A test that counted only ``adapter.effects``
    would pass even if the outbox had sent twice.
    fail-closed: one ``COMPLETED``; every other contender is refused at the claim.
    """
    case_id = await workflow.create_case()
    await workflow.add_step(case_id, step_key="emit:1", kind=StepKind.EMIT_EFFECT)
    key = effect_key(case_id, "emit:1")

    claims = await asyncio.gather(
        *(
            steps.claim_step(handle, worker=_worker(index))
            for index, handle in enumerate(sessions)
        )
    )
    executed = await asyncio.gather(
        *(
            steps.execute_step(sessions[index], claim=claim, actor=_actor(index))
            for index, claim in enumerate(claims)
            if claim is not None
        )
    )

    assert executed.count(StepResult.COMPLETED) == 1

    enqueued = await workflow.rows(OutboxMessage, idempotency_key=key)
    assert len(enqueued) == 1, f"{len(enqueued)} outbox rows for one step"

    adapter = FakeEffectAdapter()
    while await _dispatch(sessions[0], adapter):
        pass
    calls = [call for call in adapter.attempts if call.idempotency_key == key]
    assert len(calls) == 1, f"the provider was called {len(calls)} times for one step"
    assert calls[0].kind == FAKE_EFFECT_KIND


async def _dispatch(database: RuntimeDatabase, adapter: FakeEffectAdapter) -> bool:
    """One outbox sweep. Returns whether it found anything, so a caller can drain."""
    from promisepatch.domain import outbox

    sent = await outbox.dispatch_one(
        database, adapter, worker="dispatcher", actor=Actor(kind="SYSTEM", id="dispatcher")
    )
    return sent is not None


# ================================================ 2. lease expiry, fencing, and the receiver


async def test_a_fenced_worker_causes_no_second_call_to_the_provider(
    workflow: Workflow, sessions: tuple[RuntimeDatabase, ...]
) -> None:
    """initial: one ``EMIT_EFFECT`` step, claimed by A.

    race: A's lease is aged into the past; B reclaims the row as attempt 2, executes it, and
    the effect it enqueued is **dispatched all the way to the provider**. Only then does A
    wake up and try to finish the work it still believes it owns.
    invariant: losing the fence must cost A everything, including the effect. The existing
    fencing proofs stop at the database; this one carries the chain to the provider, which is
    the only place a duplicate would be one a customer could feel.
    receiver: the adapter is called exactly once, before A resumes and again afterwards -- the
    count is taken twice so a second call caused by A's resumption cannot hide behind the
    first.
    fail-closed: A is told ``STALE``, and the outbox holds one row, not two.
    """
    case_id = await workflow.create_case()
    step_id = await workflow.add_step(case_id, step_key="emit:1", kind=StepKind.EMIT_EFFECT)
    key = effect_key(case_id, "emit:1")
    adapter = FakeEffectAdapter()

    stalled = await steps.claim_step(sessions[0], worker=_worker(0))
    assert stalled is not None

    await workflow.expire_lease(step_id)
    reclaimed = await steps.claim_step(sessions[1], worker=_worker(1))
    assert reclaimed is not None
    assert reclaimed.attempts == stalled.attempts + 1

    assert (
        await steps.execute_step(sessions[1], claim=reclaimed, actor=_actor(1))
        is StepResult.COMPLETED
    )
    while await _dispatch(sessions[1], adapter):
        pass
    before = [call for call in adapter.attempts if call.idempotency_key == key]
    assert len(before) == 1, "the effect B committed did not reach the provider exactly once"

    # A wakes up holding a claim that describes nobody, and tries to finish.
    assert (
        await steps.execute_step(sessions[0], claim=stalled, actor=_actor(0)) is StepResult.STALE
    )
    while await _dispatch(sessions[0], adapter):
        pass

    after = [call for call in adapter.attempts if call.idempotency_key == key]
    assert len(after) == 1, f"A's resumption produced {len(after) - 1} further provider calls"
    assert len(await workflow.rows(OutboxMessage, idempotency_key=key)) == 1
    assert (await workflow.row(CaseStep, step_id)).attempts == reclaimed.attempts


# ======================================================= 3. a withdrawal racing a customer


async def _the_request(intake_fixture: Intake) -> object:
    requests = await intake_fixture.requests()
    assert len(requests) == 1, f"expected one approval request, found {len(requests)}"
    return requests[0]


async def _waiting_case(intake_fixture: Intake) -> UUID:
    """The canonical case driven to a durable wait on promise B's customer.

    Same path as ``test_customer_approval.py``'s helper of the same shape, repeated here rather
    than imported because a test module is not a support module and importing one from another
    makes the two files' fixtures each other's problem.
    """
    opened = await intake_fixture.report()
    await intake_fixture.drain()
    await intake_fixture.answer(opened.case_id, RASPBERRY_ONLY)
    await intake_fixture.drain()
    await intake_fixture.confirm(opened.case_id)
    await intake_fixture.drain(limit=40)
    return opened.case_id


async def _amendments(intake_fixture: Intake, track_id: UUID) -> list[object]:
    """Order-system effects for one track. The approval message names the track too."""
    return [
        row
        for row in await intake_fixture.effects_for(track_id)
        if row.kind == EFFECT_ORDER_AMEND
    ]


async def test_a_yes_queued_before_a_withdrawal_authorises_nothing_after_it(
    physical: Intake,
) -> None:
    """initial: the canonical case waiting on promise B's customer, request ``SENT``.

    race: the customer's literal ``YES`` is **delivered but not yet processed** -- it is an
    inbound row nobody has swept -- and the worker withdraws the case first. The withdrawal
    commits, and only then does a worker sweep the reply that was already sitting there.
    invariant: *a withdrawal stops future work.* A reply that arrived before the withdrawal but
    is read after it must not authorise an amendment: the plan it would authorise no longer
    exists, and the request it answers has been superseded.
    receiver: the order book is captured **after the withdrawal has committed** and compared
    again after the drain, and B's track is asserted to carry no ``ORDER_AMEND`` effect at all.
    fail-closed: the request is ``SUPERSEDED``, the case is terminal, and nothing was sent.

    **Why the baseline is taken after the withdrawal and not before it.** The withdrawal is
    itself entitled to change business state: it releases the production holds this case took,
    which is its documented reversal and is pinned by
    ``test_withdrawal.py::test_a_withdrawal_after_a_hold_releases_only_this_case_s_holds``. A
    baseline taken before it would fail on that authorised change and prove nothing about the
    thing under attack. What is under attack is the *drain* -- the sweep that reads a reply
    written before the withdrawal and must make nothing of it -- so the baseline is the world
    the withdrawal left behind, and the assertion is that the drain moved none of it.

    This is the one ordering the consent and withdrawal files do not between them cover:
    ``test_withdrawal.py`` proves a decision recorded *before* a withdrawal survives it, and
    ``test_recovery_revalidation.py`` proves a superseded request authorises nothing -- but no
    test lets a real reply cross a real withdrawal in flight.
    """
    case_id = await _waiting_case(physical)
    request = await _the_request(physical)
    track = await physical.track(case_id, ho.PROMISE_B)
    assert track is not None

    # The reply is on the doorstep: stored, unprocessed, and about to be overtaken.
    await physical.deliver_reply(request.id, "YES")
    await withdrawal.withdraw_exception(
        physical.database, case_id=case_id, command_id=uuid4(), worker_id=BAKER
    )
    stood_down = await physical.order_book()

    await physical.drain(limit=40)

    assert await _amendments(physical, track.id) == []
    assert await physical.order_book() == stood_down
    refreshed = await _reload_request(physical, request.id)
    assert refreshed.state == ApprovalRequestState.SUPERSEDED.value
    assert (await physical.case(case_id)).state in TERMINAL_CASE_STATES


async def test_a_superseded_request_records_no_customer_decision_at_all(
    physical: Intake,
) -> None:
    """initial: as above -- a waiting case whose request a withdrawal is about to supersede.

    race: identical ordering, asked of the consent ledger rather than of the order system.
    invariant: consent is an authority, and an authority nothing can spend must not be minted.
    A decision row written against a superseded request would be a record saying the customer
    authorised a plan that had already been stood down.
    receiver: no message goes out either -- the dispatcher refuses a message whose request is
    no longer open, so the count of outbound customer effects cannot grow across the drain.
    fail-closed: zero decisions, and the customer's words are still kept verbatim as a reply.
    """
    case_id = await _waiting_case(physical)
    request = await _the_request(physical)
    effects_before = len(await physical.effects())

    await physical.deliver_reply(request.id, "YES")
    await withdrawal.withdraw_exception(
        physical.database, case_id=case_id, command_id=uuid4(), worker_id=BAKER
    )
    await physical.drain(limit=40)

    assert await physical.decisions() == []
    assert len(await physical.effects()) == effects_before
    # Refused as authority, kept as testimony: the two are different things.
    assert [reply.raw_text for reply in await physical.replies()] == ["YES"]


async def _reload_request(intake_fixture: Intake, request_id: UUID) -> object:
    from promisepatch.db.models import ApprovalRequest

    async with intake_fixture.database.connect() as connection:
        return (
            await connection.execute(
                select(ApprovalRequest).where(ApprovalRequest.id == request_id)
            )
        ).one()
