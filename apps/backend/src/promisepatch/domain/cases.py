"""The case row: locking it, and changing it through the audited boundary.

``cases`` is a governed table, so nothing here writes it outside a
:meth:`~promisepatch.db.uow.UnitOfWork.governed` block -- and the database refuses the write if
anything tries. What this module adds on top is the lock, which is what serialises a worker's
step against an owner's action on the same case, and the version bump, which is what an
optimistic reader elsewhere detects a concurrent change with.

**Where this sits in the lock order.** The case row is taken *after* the step row and *before*
any timer, inbox or outbox row, and before the event append. Every transaction in the system
takes these in the same order, which is what stops two of them from waiting on each other.

It also answers *where the case stands now*. Several transitions can be the last one to finish
-- a recovery completing, an approval request going out, a customer's reply arriving -- and each
has to decide whether the case as a whole has moved on. Asking the same question of the same
rows from one place is what makes the answer independent of which of them happened to be last.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.model import ApprovalRequestState
from promisepatch.db.models import ApprovalRequest, Case, CaseStep, Track
from promisepatch.db.types import TERMINAL_TRACK_STATES
from promisepatch.db.uow import GovernedWrite
from promisepatch.domain.model import (
    CASE_SUBJECT,
    AppendEvent,
    ArmTimer,
    CaseChange,
    CreateStep,
)

CASE_PLANNED: Final = "PLANNED"
CASE_EXECUTING: Final = "EXECUTING"
CASE_WAITING: Final = "WAITING"
CASE_REVALIDATING: Final = "REVALIDATING"
CASE_RECONCILING: Final = "RECONCILING"
CASE_RESOLVED: Final = "RESOLVED"
"""The §14.1 states the engine can write. The rest arrive with the work that reaches them."""

STEP_RECONCILE_CASE: Final = "RECONCILE_CASE"
"""The work item that finishes a case once nothing consequential is outstanding.

Declared here rather than beside its handler because entering ``RECONCILING`` is what creates
it, and the transitions that do so live all over the engine. A case that reached the
reconciling boundary and had nothing enqueued to carry it off again would sit there for ever,
so the step is a structural consequence of the state rather than something each caller has to
remember.
"""


STEP_REVALIDATE_RECOVERY: Final = "REVALIDATE_RECOVERY"
"""One track's ten checks, created by the transition that hands a case to ``REVALIDATING``.

Declared beside the reconciliation step for the same reason: the transitions that create these
are spread across the engine, and several modules need to read a track's checklist back without
importing the module that runs it.
"""


TIMER_PLAN_AUTO_ESCALATION: Final = "PLAN_AUTO_ESCALATION"
"""§14.1's deadline on a plan nobody has confirmed, named as ``ARCHITECTURE_PLAN`` names it.

One of the four persisted deadline kinds, armed in the same transaction as the state it belongs
to. A case in ``PLANNED`` is waiting for a person to say yes, which is right; waiting for one
without limit is not, and an unbounded wait is the one resting state §14.1 does not allow.
"""

PLAN_CONFIRMATION_WINDOW: Final = timedelta(minutes=10)
"""§14.1: "awaiting worker 'yes'. Auto-escalates to owner after 10 min.\""""


def reconcile_step_key(case_id: UUID) -> str:
    """One reconciliation per case, whatever transition happened to reach the boundary."""
    return f"reconcile:{case_id}"


def revalidate_step_key(track_id: UUID) -> str:
    """One revalidation per track. A second delivery collides on ``(case_id, step_key)``."""
    return f"revalidate:{track_id}"


def case_of(step_key: str) -> UUID:
    """The case a reconciliation step is about, read back out of its key."""
    return UUID(step_key.partition(":")[2])


RUNNABLE_TRACK_STATES: Final[tuple[str, ...]] = ("PENDING", "APPLYING")
"""Track postures that still have immediate work in them.

A case with one of these has not finished executing, whatever else is true of it, so it may not
claim to be waiting on a customer -- §14.2's "only if at least one approval request was
actually sent" has a second half, which is that everything else already ran.
"""

TRACK_WAITING_FOR_CUSTOMER: Final = "WAITING_FOR_CUSTOMER"
TRACK_ESCALATED: Final = "ESCALATED"

OPEN_APPROVAL_STATES: Final[tuple[str, ...]] = (
    ApprovalRequestState.SENT.value,
    ApprovalRequestState.CONFIRMATION_PENDING.value,
)
"""Request states in which a customer could still answer. Everything else is settled."""

UNSETTLED_STEP_STATES: Final[tuple[str, ...]] = ("PENDING", "RETRYING", "IN_FLIGHT")
"""Step postures that still have work in them. A case with one of these has not finished."""

EVENT_CASE_WAITING: Final = "case.waiting"
EVENT_CASE_REVALIDATION_READY: Final = "case.revalidation_ready"
EVENT_CASE_RECONCILING: Final = "case.reconciling"
EVENT_CASE_RESOLVED: Final = "case.resolved"
"""The case's own announcements, declared beside the rule that decides when they are true.

Several unrelated transitions can be the one that moves a case, so the event has to be emitted
by whichever of them did -- and an announcement each of them spelled for itself would eventually
be spelled two ways.
"""


class CaseMissingError(RuntimeError):
    """A step names a case that does not exist.

    Not recoverable by retrying: the step is describing work on something that is not there.
    """


@dataclass(frozen=True, slots=True)
class LockedCase:
    """A case row this transaction holds exclusively until it ends."""

    id: UUID
    state: str
    version: int
    needs_owner_attention: bool


async def lock_case(connection: AsyncConnection, case_id: UUID) -> LockedCase:
    """Take the case row for update, and return what it says.

    A pessimistic lock rather than a version check, because the engine must not discover a
    conflict after doing the work: the point of holding it is that the handler reads a state
    nobody can change underneath it while the transaction decides what to do about it.
    """
    row = (
        await connection.execute(
            select(Case.id, Case.state, Case.version, Case.needs_owner_attention)
            .where(Case.id == case_id)
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise CaseMissingError(f"case {case_id} does not exist")
    return LockedCase(
        id=row.id,
        state=row.state,
        version=row.version,
        needs_owner_attention=row.needs_owner_attention,
    )


async def apply_case_change(
    write: GovernedWrite, *, case: LockedCase, change: CaseChange, now: datetime
) -> int:
    """Write the transition's effect on the case, and return its new version.

    The version is bumped on every consequential execution, whether or not the handler asked
    for a field to change. A step that ran and committed *is* a change to the case -- it is a
    different case afterwards, with different work outstanding -- and a reader that cached the
    old version has a stale view of it either way.
    """
    values: dict[str, object] = {"version": case.version + 1, "updated_at": now}
    if change.state is not None:
        values["state"] = change.state
    if change.needs_owner_attention is not None:
        values["needs_owner_attention"] = change.needs_owner_attention

    result = await write.execute(
        update(Case).where(Case.id == case.id, Case.version == case.version).values(**values)
    )
    if result.rowcount != 1:
        # Unreachable while the row lock is held, and asserted anyway: if it ever fires, the
        # lock discipline has been broken somewhere and the transition must not commit.
        raise CaseMissingError(
            f"case {case.id} changed under a held lock; expected version {case.version}"
        )
    return case.version + 1


# ------------------------------------------------------------------- where the case stands now


async def settled_case_state(
    connection: AsyncConnection, *, case: LockedCase, except_step_key: str | None = None
) -> str | None:
    """The state this case should move to now that a transition has finished, or ``None``.

    Called by every transition that can be the *last* one -- a recovery finishing, an approval
    request going out, a decision arriving -- because which of them finishes last depends on how
    fast a provider answered, and a case whose state depended on that would be a case whose
    state depended on luck. Each of them asks the same question of the same rows, under the case
    lock it already holds, and at most one of them gets an answer.

    The transitions that live here are §14.2's:

    * ``EXECUTING -> WAITING``: nothing runnable is left and at least one track is genuinely
      waiting on a customer. A track still ``PENDING`` or ``APPLYING`` blocks it, which is what
      makes "do not wait while A is still applying" structural rather than a matter of ordering.
    * ``EXECUTING -> REVALIDATING``: the same, except the customer has already answered.
    * ``EXECUTING -> RECONCILING``: nothing runnable is left and there is nobody to wait for at
      all -- §14.2's "an all-AUTO/BLOCKED case never waits".
    * ``WAITING -> REVALIDATING``: no approval request can be answered any more, because every
      one of them has been decided or has expired.
    * ``RECONCILING -> RESOLVED`` / ``RECONCILING -> WAITING``: the reconciling boundary is
      finished when no track is non-terminal and nothing durable is outstanding; if another
      track is still waiting on its own customer, the case goes back to waiting instead.

    A case that finishes executing to find its request *already* answered goes straight to
    ``REVALIDATING``. §14.2 permits ``EXECUTING`` to skip ``WAITING`` when there is nothing to
    wait for, and a customer who replied while the last recovery was still running is exactly
    that: entering ``WAITING`` would be waiting for an answer already in the database, and
    nothing would ever come to wake it.

    ``except_step_key`` names the step this transition is itself executing. That step is
    outstanding right now and will be settled by the same commit, so counting it would make a
    case permanently unable to resolve through the very step whose job that is.

    Read without ``FOR UPDATE`` deliberately: every transition that could move one of these rows
    takes the case row first, and this transaction is holding it.
    """
    if case.state == CASE_EXECUTING:
        if await _has_runnable_track(connection, case.id):
            return None
        if not await _has_waiting_track(connection, case.id):
            return CASE_RECONCILING
        return CASE_WAITING if await _has_open_approval(connection, case.id) else CASE_REVALIDATING
    if case.state == CASE_WAITING:
        return None if await _has_open_approval(connection, case.id) else CASE_REVALIDATING
    if case.state == CASE_RECONCILING:
        return await _settled_reconciling(connection, case.id, except_step_key=except_step_key)
    return None


async def _settled_reconciling(
    connection: AsyncConnection, case_id: UUID, *, except_step_key: str | None
) -> str | None:
    """§14.2's two exits from ``RECONCILING``, decided from rows alone.

    ``RESOLVED`` requires every track terminal *and* nothing outstanding, which is §23's list
    read off the database rather than restated: a track still ``PENDING``, ``APPLYING``,
    ``WAITING_FOR_CUSTOMER`` or ``STALE`` is a non-terminal track, and an undelivered effect or
    an unfinished re-plan is an unsettled step of the same case.
    """
    if await _has_waiting_track(connection, case_id) and await _has_open_approval(
        connection, case_id
    ):
        return CASE_WAITING
    return (
        CASE_RESOLVED
        if await resolvable(connection, case_id, except_step_key=except_step_key)
        else None
    )


async def resolvable(
    connection: AsyncConnection, case_id: UUID, *, except_step_key: str | None = None
) -> bool:
    """Whether every track is terminal and no durable work is left.

    The single reading of §23's "do not resolve if": one function, so the reconciler and the
    transition that happens to finish last cannot disagree about what finished means.
    """
    if await non_terminal_tracks(connection, case_id):
        return False
    return not await _has_unsettled_work(connection, case_id, except_step_key=except_step_key)


async def non_terminal_tracks(connection: AsyncConnection, case_id: UUID) -> tuple[str, ...]:
    """The states of the tracks that still hold their promise, in §13.4's vocabulary."""
    rows = (
        await connection.execute(
            select(Track.state).where(
                Track.case_id == case_id, Track.state.not_in(TERMINAL_TRACK_STATES)
            )
        )
    ).scalars()
    return tuple(sorted(rows))


async def any_escalated(connection: AsyncConnection, case_id: UUID) -> bool:
    """Whether a track was handed to the owner. §14.1's ``needs_owner_attention`` on RESOLVED."""
    escalated = select(Track.id).where(Track.case_id == case_id, Track.state == TRACK_ESCALATED)
    return bool(await connection.scalar(select(exists(escalated))))


async def _has_unsettled_work(
    connection: AsyncConnection, case_id: UUID, *, except_step_key: str | None
) -> bool:
    """Any step of this case that is still going to do something, other than this one."""
    statement = select(CaseStep.id).where(
        CaseStep.case_id == case_id, CaseStep.state.in_(UNSETTLED_STEP_STATES)
    )
    if except_step_key is not None:
        statement = statement.where(CaseStep.step_key != except_step_key)
    return bool(await connection.scalar(select(exists(statement))))


async def _has_runnable_track(connection: AsyncConnection, case_id: UUID) -> bool:
    runnable = select(Track.id).where(
        Track.case_id == case_id, Track.state.in_(RUNNABLE_TRACK_STATES)
    )
    return bool(await connection.scalar(select(exists(runnable))))


async def _has_waiting_track(connection: AsyncConnection, case_id: UUID) -> bool:
    waiting = select(Track.id).where(
        Track.case_id == case_id, Track.state == TRACK_WAITING_FOR_CUSTOMER
    )
    return bool(await connection.scalar(select(exists(waiting))))


async def _has_open_approval(connection: AsyncConnection, case_id: UUID) -> bool:
    """Whether any request on this case could still receive an authoritative answer.

    ``decided`` is checked as well as the state, because the two are written together and a
    reader that trusted only one of them would be trusting half of a row.
    """
    open_request = (
        select(ApprovalRequest.id)
        .join(Track, Track.id == ApprovalRequest.track_id)
        .where(
            Track.case_id == case_id,
            ApprovalRequest.state.in_(OPEN_APPROVAL_STATES),
            ApprovalRequest.decided.is_(False),
        )
    )
    return bool(await connection.scalar(select(exists(open_request))))


async def case_successors(
    connection: AsyncConnection, moved_to: str | None, *, case_id: UUID
) -> tuple[CreateStep, ...]:
    """The work a case's own move makes runnable.

    Two of the states do. Entering ``REVALIDATING`` creates one revalidation per settled
    approval request; entering ``RECONCILING`` creates the step that finishes the case. Both are
    enqueued by the transition that reached the boundary rather than by a sweep, so the state
    and the work that leaves it commit together -- and both keys are derived from rows, so a
    second transition reaching the same boundary proposes identical rows and the unique index
    declines them.

    Without this, a case could arrive at a boundary with nothing enqueued to carry it off
    again: a declined approval would park a finished case in ``REVALIDATING`` for ever, which is
    the failure mode §44 names.

    The import is deferred because the module that runs those steps reads this one to decide
    where a case stands, and a module-level import in both directions would be a cycle. It takes
    no lock this transaction does not already hold.
    """
    if moved_to == CASE_RECONCILING:
        return (CreateStep(step_key=reconcile_step_key(case_id), kind=STEP_RECONCILE_CASE),)
    if moved_to == CASE_REVALIDATING:
        from promisepatch.domain.revalidation import work_for_case

        return await work_for_case(connection, case_id)
    return ()


def case_timers(moved_to: str | None, *, case_id: UUID) -> tuple[ArmTimer, ...]:
    """The deadline a case's own move starts, when the move starts one.

    One state does. Entering ``PLANNED`` begins a wait on a human being, and §14.1 bounds that
    wait at ten minutes. Armed by the transition that reached the state rather than by a sweep,
    for the same reason its successors are: the wait and the limit on it commit together, so
    there is no window in which a case is waiting and nothing is counting.

    Idempotent by the database rather than by this function -- ``timers`` carries one live row
    per subject -- so a transition retried after a crash re-arms harmlessly and does not move a
    deadline that is already counting down.
    """
    if moved_to == CASE_PLANNED:
        return (
            ArmTimer(
                kind=TIMER_PLAN_AUTO_ESCALATION,
                subject_type=CASE_SUBJECT,
                subject_id=str(case_id),
                delay=PLAN_CONFIRMATION_WINDOW,
            ),
        )
    return ()


def case_events(moved_to: str | None, *, case_id: UUID) -> tuple[AppendEvent, ...]:
    """The case's announcement of its own move, when a transition made one and not otherwise.

    Emitted by the transition that moved the case rather than by a watcher, so the event and the
    row it describes commit together: there is no window in which a case is waiting and the feed
    has not been told, or has been told and the case is not.
    """
    if moved_to == CASE_WAITING:
        return (
            AppendEvent(
                type=EVENT_CASE_WAITING,
                payload={"state": CASE_WAITING},
                entity_refs=({"kind": "case", "id": str(case_id)},),
            ),
        )
    if moved_to == CASE_REVALIDATING:
        return (
            AppendEvent(
                type=EVENT_CASE_REVALIDATION_READY,
                payload={"state": CASE_REVALIDATING},
                entity_refs=({"kind": "case", "id": str(case_id)},),
            ),
        )
    if moved_to == CASE_RECONCILING:
        return (
            AppendEvent(
                type=EVENT_CASE_RECONCILING,
                payload={"state": CASE_RECONCILING},
                entity_refs=({"kind": "case", "id": str(case_id)},),
            ),
        )
    if moved_to == CASE_RESOLVED:
        return (
            AppendEvent(
                type=EVENT_CASE_RESOLVED,
                payload={"state": CASE_RESOLVED},
                entity_refs=({"kind": "case", "id": str(case_id)},),
            ),
        )
    return ()
