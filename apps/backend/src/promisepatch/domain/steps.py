"""Claiming a step, fencing it, and executing it in one transaction that commits or does not.

Three transactions, and the boundaries between them are the design.

**Claim** is short, ungoverned and does no work. It moves one eligible row to ``IN_FLIGHT``,
increments ``attempts`` and stamps a lease, then commits immediately. Nothing is decided here,
so nothing is audited: this is bookkeeping about who is going to look at a row, not a change to
anything a customer promised.

**Execution** is one transaction that ends in a commit or leaves the database untouched. It
re-reads the claimed row under ``FOR UPDATE`` and checks the fence before anything else,
because a claim is a statement about the past: between claiming and executing, a lease can
expire and another worker can take the step over. Everything the handler asks for is then
persisted inside a single governed block, ending with the domain event.

**Failure bookkeeping** is short and deliberately dull. A retryable failure sets a time and
gets out of the way; a terminal one escalates, which is a real change to the case and is
therefore audited like one.

The fence is ``(state, lease_owner, attempts)``, checked under the row lock and repeated on the
final update, which must affect exactly one row. That is what makes this impossible::

    A claims attempt N → A stalls → lease expires → B reclaims as attempt N+1
    → B completes → A wakes and commits obsolete work

A's completion names attempt N, no row has that combination any more, zero rows are affected,
and the transaction is aborted before it can commit anything at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.db.clock import database_now
from promisepatch.db.events import append_event
from promisepatch.db.models import CaseStep
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.db.uow import Actor, GovernedWrite, UnitOfWork
from promisepatch.domain import crash, handlers, retry
from promisepatch.domain.cases import LockedCase, apply_case_change, lock_case
from promisepatch.domain.model import (
    AUDIT_STEP_EXECUTED,
    AUDIT_STEP_FAILED,
    EVENT_STEP_FAILED,
    CaseChange,
    Disposition,
    StepContext,
    StepKind,
    StepOutcome,
    StepResult,
)
from promisepatch.domain.observation import INTAKE_STEP_KINDS
from promisepatch.domain.outbox import enqueue_effect, stamp_created_in_tx_seq
from promisepatch.domain.timers import arm_timer, cancel_timer
from promisepatch.observability import get_logger

logger = get_logger(__name__)

LEASE_DURATION: Final = timedelta(seconds=60)
"""How long a claim is good for before another worker may take the step over.

Long enough that an ordinary step finishes inside it with room to spare, short enough that a
killed container's work is picked up within a minute. A constant rather than a setting: nothing
has asked to vary it, and a variable nobody sets is a promise the code does not keep.
"""

CLAIMABLE_STATES: Final[tuple[str, ...]] = ("PENDING", "RETRYING")


class LeaseLostError(RuntimeError):
    """The claim this worker holds no longer describes the row. Raised to force a rollback.

    Carries which of the two things happened, because they mean different things to an
    operator: ``LEASE_LOST`` is a worker that was too slow, ``STALE`` is work that is already
    finished.
    """

    def __init__(self, result: StepResult, detail: str) -> None:
        super().__init__(detail)
        self.result = result


@dataclass(frozen=True, slots=True)
class StepClaim:
    """One worker's exclusive right to execute one step, until ``lease_expires_at``.

    ``attempts`` is the fencing token. It is the value the claim wrote, and every later write in
    this claim's name repeats it as a predicate.
    """

    step_id: UUID
    case_id: UUID
    step_key: str
    kind: str
    attempts: int
    lease_owner: str
    lease_expires_at: datetime


# ---------------------------------------------------------------------------------- enqueueing


async def enqueue_step(
    connection: AsyncConnection,
    *,
    case_id: UUID,
    step_key: str,
    kind: StepKind | str,
    next_attempt_at: datetime | None = None,
) -> UUID | None:
    """Create a step, or do nothing because it already exists.

    ``ON CONFLICT DO NOTHING`` against ``(case_id, step_key)`` is what makes a replayed
    transition idempotent: the second attempt proposes the identical key and the database
    declines it, rather than the application having to remember to look first. Returns the new
    id, or ``None`` when the step was already there.
    """
    statement = (
        pg_insert(CaseStep)
        .values(
            id=uuid4(),
            case_id=case_id,
            step_key=step_key,
            kind=str(kind),
            state="PENDING",
            attempts=0,
            next_attempt_at=next_attempt_at,
        )
        .on_conflict_do_nothing(index_elements=[CaseStep.case_id, CaseStep.step_key])
        .returning(CaseStep.id)
    )
    return (await connection.execute(statement)).scalar_one_or_none()


# ------------------------------------------------------------------------------------ claiming


async def claim_step(
    database: RuntimeDatabase, *, worker: str, lease: timedelta = LEASE_DURATION
) -> StepClaim | None:
    """Take one eligible step, in a short transaction of its own.

    Eligible means either due work -- ``PENDING`` or ``RETRYING`` with no future retry time --
    or an ``IN_FLIGHT`` row whose lease has run out, which is how a dead worker's step comes
    back. ``FOR UPDATE SKIP LOCKED`` means several workers sweeping at once take different rows
    instead of queueing behind the same one.

    Every instant compared here is the database's, never the process's: two workers with
    drifting clocks must agree about whether a lease has expired.
    """
    crash.at(crash.BEFORE_CLAIM)
    async with database.begin() as connection:
        now = await database_now(connection)
        due = CaseStep.state.in_(CLAIMABLE_STATES) & (
            CaseStep.next_attempt_at.is_(None) | (CaseStep.next_attempt_at <= now)
        )
        expired = (CaseStep.state == "IN_FLIGHT") & (CaseStep.lease_expires_at <= now)

        candidate = (
            await connection.execute(
                select(CaseStep.id)
                .where(or_(due, expired))
                .order_by(CaseStep.created_at, CaseStep.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if candidate is None:
            return None

        expires_at = now + lease
        claimed = (
            await connection.execute(
                update(CaseStep)
                .where(CaseStep.id == candidate)
                .values(
                    state="IN_FLIGHT",
                    attempts=CaseStep.attempts + 1,
                    lease_owner=worker,
                    lease_expires_at=expires_at,
                    started_at=now,
                    next_attempt_at=None,
                )
                .returning(
                    CaseStep.id,
                    CaseStep.case_id,
                    CaseStep.step_key,
                    CaseStep.kind,
                    CaseStep.attempts,
                )
            )
        ).one()

    crash.at(crash.AFTER_CLAIM_COMMIT)
    return StepClaim(
        step_id=claimed.id,
        case_id=claimed.case_id,
        step_key=claimed.step_key,
        kind=claimed.kind,
        attempts=claimed.attempts,
        lease_owner=worker,
        lease_expires_at=expires_at,
    )


# ----------------------------------------------------------------------------------- execution


async def execute_step(database: RuntimeDatabase, *, claim: StepClaim, actor: Actor) -> StepResult:
    """Run one claimed step, and persist everything it decided, or nothing at all.

    Returns what happened rather than raising for the ordinary outcomes, because a worker loop
    treats a lost lease and a scheduled retry the same way: log it and move on to the next
    piece of work. Only a genuinely broken invariant escapes as an exception.
    """
    try:
        async with database.begin() as connection:
            result = await _run(connection, claim=claim, actor=actor)
    except LeaseLostError as lost:
        # The transaction rolled back on the way out of the block, so this worker wrote
        # nothing at all -- which is the entire guarantee.
        logger.info(
            "worker.step.fenced",
            step_id=str(claim.step_id),
            step_key=claim.step_key,
            attempt=claim.attempts,
            result=lost.result.value,
            detail=str(lost),
        )
        return lost.result

    # Outside the block, so it is genuinely after the COMMIT: a death armed here must leave the
    # transition durable, which is the opposite of what BEFORE_TRANSITION_COMMIT proves.
    crash.at(crash.AFTER_TRANSITION_COMMIT)
    return result


async def _run(connection: AsyncConnection, *, claim: StepClaim, actor: Actor) -> StepResult:
    row = await _fence(connection, claim)
    case = await lock_case(connection, claim.case_id)
    now = await database_now(connection)

    crash.at(crash.DURING_HANDLER)
    executor = _executor_for(row.kind)
    if executor is not None:
        outcome = await executor(
            connection,
            case=case,
            kind=row.kind,
            step_key=claim.step_key,
            now=now,
            worker=claim.lease_owner,
        )
    else:
        outcome = handlers.handle(
            StepContext(
                step_id=claim.step_id,
                case_id=claim.case_id,
                step_key=claim.step_key,
                kind=StepKind(row.kind),
                attempts=claim.attempts,
                case_state=case.state,
                now=now,
            )
        )

    if outcome.disposition is Disposition.RETRYING:
        return await _schedule_retry(connection, claim=claim, outcome=outcome, now=now)
    return await _commit_transition(
        connection, claim=claim, case=case, outcome=outcome, now=now, actor=actor
    )


class StepExecutor(Protocol):
    """A unit of work that decides from the database rather than from a context alone."""

    async def __call__(
        self,
        connection: AsyncConnection,
        *,
        case: LockedCase,
        kind: str,
        step_key: str,
        now: datetime,
        worker: str,
    ) -> StepOutcome: ...


def _executor_for(kind: str) -> StepExecutor | None:
    """The module that runs this kind of step, or ``None`` for a pure handler.

    Intake, analysis, recovery and the consent protocol all read the graph, the plan, the outbox
    or a stored reply to decide, so they read and write inside the execution transaction instead
    of returning directives for one.

    The import is deferred because each of those modules names step keys *this* module
    enqueues, and a module-level import in both directions would be a cycle. Resolved once per
    step rather than once per process, which costs a dictionary lookup in ``sys.modules``.
    """
    from promisepatch.domain import analysis, approvals, physical, recovery

    if kind in INTAKE_STEP_KINDS:
        return physical.execute
    if kind in analysis.ANALYSIS_STEP_KINDS:
        return analysis.execute
    if kind in recovery.RECOVERY_STEP_KINDS:
        return recovery.execute
    if kind in approvals.APPROVAL_STEP_KINDS:
        return approvals.execute
    return None


async def _fence(connection: AsyncConnection, claim: StepClaim) -> CaseStep:
    """Re-read the claimed row under lock and prove the claim still describes it.

    Under ``FOR UPDATE``, so the answer cannot change between this check and the write at the
    end of the transaction. The two failures are told apart deliberately: a row that has moved
    on to another owner or attempt was *reclaimed*; a row that is no longer in flight at all was
    *settled* by somebody, and there is nothing left to do either way.
    """
    row = (
        await connection.execute(
            select(CaseStep).where(CaseStep.id == claim.step_id).with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise LeaseLostError(StepResult.STALE, f"step {claim.step_id} no longer exists")
    if row.state != "IN_FLIGHT":
        raise LeaseLostError(
            StepResult.STALE, f"step {claim.step_id} is {row.state}, not in flight"
        )
    if row.lease_owner != claim.lease_owner or row.attempts != claim.attempts:
        raise LeaseLostError(
            StepResult.LEASE_LOST,
            f"step {claim.step_id} is held by {row.lease_owner!r} at attempt {row.attempts}; "
            f"this claim is {claim.lease_owner!r} at attempt {claim.attempts}",
        )
    return row  # type: ignore[return-value]


async def _commit_transition(
    connection: AsyncConnection,
    *,
    claim: StepClaim,
    case: LockedCase,
    outcome: StepOutcome,
    now: datetime,
    actor: Actor,
) -> StepResult:
    """One governed block: case, successors, timers, effects, the step itself, then the event.

    The order is the lock order. Everything that can contend with another transaction is taken
    first; the event append comes last because it holds the spine's ordering lock until commit,
    and nothing may queue behind that.
    """
    terminal = outcome.disposition is Disposition.FAILED
    exhausted = terminal or (
        outcome.disposition is Disposition.RETRYING and retry.is_exhausted(claim.attempts)
    )
    change = (
        CaseChange(state=outcome.case_change.state, needs_owner_attention=True)
        if exhausted
        else outcome.case_change
    )

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_STEP_FAILED if terminal else AUDIT_STEP_EXECUTED,
        actor=actor,
        # No policy and no consent permitted this. The engine reached a step it had already
        # planned and ran it; saying `NONE` is the honest record of that.
        authority="NONE",
        case_id=claim.case_id,
        before={"case_version": case.version, "step_state": "IN_FLIGHT"},
        after={
            "case_version": case.version + 1,
            "step_state": outcome.disposition.value,
            "step_key": claim.step_key,
            "attempt": claim.attempts,
        },
        provenance={"worker": claim.lease_owner, "step_id": str(claim.step_id)},
        occurred_at=now,
    ) as write:
        await apply_case_change(write, case=case, change=change, now=now)

        for successor in outcome.successors:
            await enqueue_step(
                connection,
                case_id=claim.case_id,
                step_key=successor.step_key,
                kind=successor.kind,
            )
        for timer in outcome.timers:
            await arm_timer(
                connection,
                kind=timer.kind,
                subject_type=timer.subject_type,
                subject_id=timer.subject_id,
                due_at=now + timer.delay,
            )
            crash.at(crash.TIMER_ARMED)
        for cancellation in outcome.cancellations:
            await cancel_timer(
                connection,
                kind=cancellation.kind,
                subject_type=cancellation.subject_type,
                subject_id=cancellation.subject_id,
            )
        effect_ids = [
            await enqueue_effect(
                connection,
                kind=effect.kind,
                payload={**effect.payload, "case_id": str(claim.case_id)},
                idempotency_key=effect.idempotency_key,
            )
            for effect in outcome.effects
        ]

        await _settle(
            connection,
            claim=claim,
            state=outcome.disposition.value,
            now=now,
            result=dict(outcome.result),
            error=outcome.error,
        )

        # Last. From here the transaction holds the spine's ordering lock, so it acquires no
        # lock it does not already hold -- the stamp below touches only rows it just inserted.
        seq = await append_event(
            connection,
            event_type=outcome.event_type,
            correlation_id=write.correlation_id,
            occurred_at=now,
            case_id=claim.case_id,
            entity_refs=[{"kind": "case_step", "id": str(claim.step_id)}],
            payload={
                "step_key": claim.step_key,
                "kind": claim.kind,
                "disposition": outcome.disposition.value,
                "attempt": claim.attempts,
            },
        )
        # What the transition did, in its own words, after what the engine did in ours. Still
        # inside the transaction and still taking no lock the spine's own has not already
        # taken, so the ordering guarantee is untouched.
        for event in outcome.events:
            await append_event(
                connection,
                event_type=event.type,
                correlation_id=write.correlation_id,
                occurred_at=now,
                case_id=claim.case_id,
                entity_refs=list(event.entity_refs),
                payload=dict(event.payload),
            )
        await stamp_created_in_tx_seq(connection, effect_ids=effect_ids, seq=seq)

        crash.at(crash.BEFORE_TRANSITION_COMMIT)

    return StepResult.FAILED if terminal else _settled_result(outcome.disposition)


def _settled_result(disposition: Disposition) -> StepResult:
    return StepResult.SKIPPED if disposition is Disposition.SKIPPED else StepResult.COMPLETED


async def _schedule_retry(
    connection: AsyncConnection, *, claim: StepClaim, outcome: StepOutcome, now: datetime
) -> StepResult:
    """Set a time and get out of the way -- or, at the bound, stop pretending.

    Retry bookkeeping touches only ``case_steps``, which is ungoverned: nothing about a customer
    promise has changed, and auditing "we will look at this again in five seconds" would fill
    the ledger with the engine's own scheduling. Exhaustion is different, and takes the terminal
    path, which is audited.
    """
    backoff = retry.backoff_after(claim.attempts)
    if backoff is None:
        return await _commit_transition(
            connection,
            claim=claim,
            case=await lock_case(connection, claim.case_id),
            outcome=StepOutcome(
                disposition=Disposition.FAILED,
                event_type=EVENT_STEP_FAILED,
                case_change=CaseChange(needs_owner_attention=True),
                result=dict(outcome.result),
                error=(
                    f"{outcome.error or 'step failed'}; giving up after {claim.attempts} attempts"
                ),
            ),
            now=now,
            actor=Actor(kind="SYSTEM", id=claim.lease_owner),
        )

    crash.at(crash.DURING_RETRY_BOOKKEEPING)
    await _settle(
        connection,
        claim=claim,
        state=Disposition.RETRYING.value,
        now=None,
        result=dict(outcome.result),
        error=outcome.error,
        next_attempt_at=now + backoff,
    )
    return StepResult.RETRY_SCHEDULED


async def _settle(
    connection: AsyncConnection | GovernedWrite,
    *,
    claim: StepClaim,
    state: str,
    now: datetime | None,
    result: dict[str, object],
    error: str | None,
    next_attempt_at: datetime | None = None,
) -> None:
    """The fenced final write. Exactly one row, or the transition does not commit.

    The predicate is the claim, repeated: a worker whose lease expired and was reclaimed while
    it worked matches nothing here, so its transaction aborts instead of overwriting the result
    of the worker that actually did the job.
    """
    statement = (
        update(CaseStep)
        .where(
            CaseStep.id == claim.step_id,
            CaseStep.state == "IN_FLIGHT",
            CaseStep.lease_owner == claim.lease_owner,
            CaseStep.attempts == claim.attempts,
        )
        .values(
            state=state,
            done_at=now,
            result=result,
            error=error,
            next_attempt_at=next_attempt_at,
            lease_owner=None,
            lease_expires_at=None,
        )
    )
    affected = (await connection.execute(statement)).rowcount
    if affected != 1:
        raise LeaseLostError(
            StepResult.LEASE_LOST,
            f"step {claim.step_id} was reclaimed while attempt {claim.attempts} was running",
        )


# -------------------------------------------------------------------------------- inspection


async def outstanding_steps(connection: AsyncConnection, case_id: UUID) -> Sequence[str]:
    """Step keys for a case that are not yet settled. For operator views and tests."""
    rows = (
        await connection.execute(
            select(CaseStep.step_key)
            .where(
                CaseStep.case_id == case_id,
                CaseStep.state.in_(("PENDING", "RETRYING", "IN_FLIGHT")),
            )
            .order_by(CaseStep.created_at)
        )
    ).scalars()
    return list(rows)


async def count_steps(connection: AsyncConnection, case_id: UUID) -> int:
    value = await connection.scalar(
        select(func.count()).select_from(CaseStep).where(CaseStep.case_id == case_id)
    )
    return int(value or 0)
