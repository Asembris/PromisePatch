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

from sqlalchemy import exists, func, select, update
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

STEP_REPLAN_TRACK: Final = "REPLAN_TRACK"
"""§14.4's re-plan of one stale promise, created by the revalidation that found it stale.

Declared here rather than beside its handler in ``analysis`` because it belongs to the same
revalidation round as :data:`STEP_REVALIDATE_RECOVERY`, and the rule that decides when that round
is over has to count both (ADR-0023).
"""

REVALIDATION_ROUND_KINDS: Final[frozenset[str]] = frozenset(
    {STEP_REVALIDATE_RECOVERY, STEP_REPLAN_TRACK}
)
"""The work one revalidation round is made of: every settled request's checks, and every re-plan
a stale one called for. §14.2 lists all of their outcomes as the round's, per track."""


TIMER_PLAN_AUTO_ESCALATION: Final = "PLAN_AUTO_ESCALATION"
"""§14.1's deadline on a plan nobody has confirmed, named as ``ARCHITECTURE_PLAN`` names it.

One of the four persisted deadline kinds, armed in the same transaction as the state it belongs
to. A case in ``PLANNED`` is waiting for a person to say yes, which is right; waiting for one
without limit is not, and an unbounded wait is the one resting state §14.1 does not allow.
"""

PLAN_CONFIRMATION_WINDOW: Final = timedelta(minutes=10)
"""§14.1: "awaiting worker 'yes'. Auto-escalates to owner after 10 min.\""""


RECOVERY_WORK_KINDS: Final[frozenset[str]] = frozenset(
    {"APPLY_RECOVERY", "FINALIZE_RECOVERY", "ABANDON_RECOVERY"}
)
"""The steps that carry an approved or automatic change from its decision to its settlement.

Named here by value rather than imported, because ``recovery`` reads this module to decide where
a case stands and a module-level import in both directions would be a cycle; a test pins these to
``recovery``'s own constants. ``RECONCILING`` does not move on while one of them is outstanding
(ADR-0025): the case is still making a change, and it must not claim to be waiting.
"""


def reconcile_step_key(case_id: UUID, entry: int = 0) -> str:
    """One reconciliation per entry into ``RECONCILING``, whatever transition reached it.

    The first entry keeps the key it has always had. A case can come back to the boundary after
    waiting on another customer (ADR-0025), and the *n*-th return, after *n* reconciliations have
    settled, is ``reconcile:<case>:<n>`` -- so a second transition reaching the same boundary while
    its reconciliation is outstanding still proposes the same key, and the index declines it.
    """
    return f"reconcile:{case_id}" if entry == 0 else f"reconcile:{case_id}:{entry}"


def revalidate_step_key(track_id: UUID, scope: UUID | None = None) -> str:
    """One revalidation per approval request. A second delivery collides on ``(case_id, step_key)``.

    ``scope`` is :func:`promisepatch.domain.approvals.ask_scope` of the request being checked:
    ``None`` for a track's first ask, which keeps the per-track key it has always had, and the
    request's own id for a re-ask (ADR-0022). Without it a re-asked track would propose the key
    its first, stale revalidation already settled, and the index would decline the second.
    """
    return track_scoped_key("revalidate", track_id, scope)


def track_scoped_key(prefix: str, track_id: UUID, scope: object | None) -> str:
    """``prefix:<track>``, or ``prefix:<track>:<scope>`` when the step belongs to one episode.

    The track stays first in every shape, so a reader that only wants the track reads it the same
    way from a key written before ADR-0022 as from one written after.
    """
    return f"{prefix}:{track_id}" if scope is None else f"{prefix}:{track_id}:{scope}"


def track_in(step_key: str) -> UUID:
    """The track a track-scoped key names: the first identity after its prefix."""
    return UUID(step_key.split(":")[1])


def scope_in(step_key: str) -> str | None:
    """What a track-scoped key names after its track, or ``None`` for a per-track key."""
    parts = step_key.split(":", 2)
    return parts[2] if len(parts) == 3 else None


def case_of(step_key: str) -> UUID:
    """The case a reconciliation step is about, read back out of either shape of its key."""
    return UUID(step_key.split(":")[1])


RUNNABLE_TRACK_STATES: Final[tuple[str, ...]] = ("PENDING", "APPLYING")
"""Track postures that still have immediate work in them.

A case with one of these has not finished executing, whatever else is true of it, so it may not
claim to be waiting on a customer -- §14.2's "only if at least one approval request was
actually sent" has a second half, which is that everything else already ran.
"""

TRACK_PENDING: Final = "PENDING"
TRACK_APPLYING: Final = "APPLYING"
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
    * ``EXECUTING -> REVALIDATING``: the same, except a customer has already answered.
    * ``EXECUTING -> RECONCILING``: nothing runnable is left and there is nobody to wait for at
      all -- §14.2's "an all-AUTO/BLOCKED case never waits".
    * ``WAITING -> REVALIDATING``: a literal approval arrived that nothing has checked yet, or no
      approval request can be answered any more. §14.2 makes a decision its own exit, so one
      customer's yes is not held for a sibling who has not answered (ADR-0025).
    * ``REVALIDATING -> REVALIDATING``: an approval that arrives during a round joins it. The move
      is what makes its checklist part of the round, and the round still ends once (ADR-0023).
    * ``RECONCILING -> REVALIDATING`` / ``-> WAITING`` / ``-> RESOLVED``: once no change is still
      being made, an approval that arrived meanwhile is checked, a track still waiting on its own
      customer is waited on, and a case with nothing left resolves.

    A case that finishes executing to find a request *already* answered goes straight to
    ``REVALIDATING``. §14.2 permits ``EXECUTING`` to skip ``WAITING`` when there is nothing to
    wait for, and a customer who replied while the last recovery was still running is exactly
    that: entering ``WAITING`` would be waiting for an answer already in the database, and
    nothing would ever come to wake it.

    ``PLANNED`` has no exit here. It waits on a worker's yes for a re-planned track (ADR-0023),
    and an answer recorded meanwhile is checked by whichever transition leaves it.

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
        if await has_unchecked_approval(connection, case.id):
            return CASE_REVALIDATING
        return CASE_WAITING if await _has_open_approval(connection, case.id) else CASE_REVALIDATING
    if case.state == CASE_WAITING:
        if await has_unchecked_approval(connection, case.id):
            return CASE_REVALIDATING
        return None if await _has_open_approval(connection, case.id) else CASE_REVALIDATING
    if case.state == CASE_REVALIDATING:
        return CASE_REVALIDATING if await has_unchecked_approval(connection, case.id) else None
    if case.state == CASE_RECONCILING:
        return await _settled_reconciling(connection, case.id, except_step_key=except_step_key)
    return None


async def _settled_reconciling(
    connection: AsyncConnection, case_id: UUID, *, except_step_key: str | None
) -> str | None:
    """The exits from ``RECONCILING``, decided from rows alone (§14.2, ADR-0025).

    Nothing leaves while a change is still being made: ``RECONCILING`` is where approved changes
    are applied, and ``WAITING`` is the state in which nothing consequential runs. The recovery
    step that settles last asks this again, so the case never waits on a reconciliation that has
    already run.

    Then an approval that arrived meanwhile is checked -- against a world in which the change
    just made has settled, so §14.3's check 5 counts it among the tracks "already RECOVERED" --
    and a track still waiting on its own open request is waited on.

    ``RESOLVED`` requires every track terminal *and* nothing outstanding, which is §23's list
    read off the database rather than restated: a track still ``PENDING``, ``APPLYING``,
    ``WAITING_FOR_CUSTOMER`` or ``STALE`` is a non-terminal track, and an undelivered effect or
    an unfinished re-plan is an unsettled step of the same case.
    """
    if await _recovery_in_flight(connection, case_id, except_step_key=except_step_key):
        return None
    if await has_unchecked_approval(connection, case_id):
        return CASE_REVALIDATING
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


async def revalidation_round_exit(
    connection: AsyncConnection, *, case_id: UUID, step_key: str, leaves_a_plan: bool = False
) -> str | None:
    """Where a revalidating case goes once this step finishes, or ``None`` if it stays (ADR-0023).

    A round ends once, when its last revalidation or re-plan finishes, whichever claim order the
    worker happened to take them in. Counting only the revalidations let a sibling's ``PROCEED``
    move the case to ``RECONCILING`` under a re-plan that could then never run.

    When it ends, the case goes to ``PLANNED`` if a re-plan left a promise waiting for a worker's
    yes, and to ``RECONCILING`` otherwise. A confirmed case reaches ``REVALIDATING`` only when
    nothing is runnable, so a ``PENDING`` track here is one a re-plan produced and nothing else.
    ``leaves_a_plan`` is the re-plan saying so about its own track, whose ``PENDING`` it is writing
    in the same transaction.
    """
    outstanding = select(CaseStep.id).where(
        CaseStep.case_id == case_id,
        CaseStep.kind.in_(sorted(REVALIDATION_ROUND_KINDS)),
        CaseStep.step_key != step_key,
        CaseStep.state.in_(UNSETTLED_STEP_STATES),
    )
    if await connection.scalar(select(exists(outstanding))):
        return None
    if leaves_a_plan:
        return CASE_PLANNED
    pending = select(Track.id).where(Track.case_id == case_id, Track.state == TRACK_PENDING)
    return CASE_PLANNED if await connection.scalar(select(exists(pending))) else CASE_RECONCILING


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


async def has_unchecked_approval(connection: AsyncConnection, case_id: UUID) -> bool:
    """Whether a customer's literal yes is in the database and nothing has checked it yet.

    A track still ``WAITING_FOR_CUSTOMER`` whose carried request is answered and decided, with no
    revalidation step under that request's key. A decline or an expiry is never one: both escalate
    the track where they happen. A refused-as-unauthorised answer is not one either, because its
    checklist ran. Read from rows, so it is the same answer whichever transition asks (ADR-0025).

    The import is deferred for the reason :func:`case_successors` gives: the module that builds
    request identities reads this one to decide where a case stands.
    """
    from promisepatch.domain.approvals import ask_scope

    answered = (
        await connection.execute(
            select(ApprovalRequest)
            .join(Track, Track.approval_request_id == ApprovalRequest.id)
            .where(
                Track.case_id == case_id,
                Track.state == TRACK_WAITING_FOR_CUSTOMER,
                ApprovalRequest.state == ApprovalRequestState.ANSWERED.value,
                ApprovalRequest.decided.is_(True),
            )
        )
    ).all()
    for request in answered:
        checked = select(CaseStep.id).where(
            CaseStep.case_id == case_id,
            CaseStep.step_key == revalidate_step_key(request.track_id, ask_scope(request)),
        )
        if not await connection.scalar(select(exists(checked))):
            return True
    return False


async def _recovery_in_flight(
    connection: AsyncConnection, case_id: UUID, *, except_step_key: str | None
) -> bool:
    """Whether a change is still being made: a track ``APPLYING``, or recovery work unsettled.

    The step half covers the moment between a ``PROCEED`` and its ``APPLY_RECOVERY``, when the
    track has not yet left ``WAITING_FOR_CUSTOMER`` but its change is already decided.
    """
    applying = select(Track.id).where(Track.case_id == case_id, Track.state == TRACK_APPLYING)
    if await connection.scalar(select(exists(applying))):
        return True
    work = select(CaseStep.id).where(
        CaseStep.case_id == case_id,
        CaseStep.kind.in_(sorted(RECOVERY_WORK_KINDS)),
        CaseStep.state.in_(UNSETTLED_STEP_STATES),
    )
    if except_step_key is not None:
        work = work.where(CaseStep.step_key != except_step_key)
    return bool(await connection.scalar(select(exists(work))))


async def reconcile_step(connection: AsyncConnection, case_id: UUID) -> CreateStep:
    """The reconciliation this entry into ``RECONCILING`` needs, keyed by how many have settled.

    One per entry rather than one per case (ADR-0025). A reconciliation still outstanding has the
    index this proposes, so a second transition reaching the same boundary is declined by the
    unique index; one that has settled does not stand in the way of the next return.
    """
    settled = await connection.scalar(
        select(func.count())
        .select_from(CaseStep)
        .where(
            CaseStep.case_id == case_id,
            CaseStep.kind == STEP_RECONCILE_CASE,
            CaseStep.state.not_in(UNSETTLED_STEP_STATES),
        )
    )
    return CreateStep(
        step_key=reconcile_step_key(case_id, int(settled or 0)), kind=STEP_RECONCILE_CASE
    )


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
        return (await reconcile_step(connection, case_id),)
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
