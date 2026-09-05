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
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.model import ApprovalRequestState
from promisepatch.db.models import ApprovalRequest, Case, Track
from promisepatch.db.uow import GovernedWrite
from promisepatch.domain.model import AppendEvent, CaseChange

CASE_PLANNED: Final = "PLANNED"
CASE_EXECUTING: Final = "EXECUTING"
CASE_WAITING: Final = "WAITING"
CASE_REVALIDATING: Final = "REVALIDATING"
"""The §14.1 states this slice can write. The rest arrive with the work that reaches them."""

RUNNABLE_TRACK_STATES: Final[tuple[str, ...]] = ("PENDING", "APPLYING")
"""Track postures that still have immediate work in them.

A case with one of these has not finished executing, whatever else is true of it, so it may not
claim to be waiting on a customer -- §14.2's "only if at least one approval request was
actually sent" has a second half, which is that everything else already ran.
"""

TRACK_WAITING_FOR_CUSTOMER: Final = "WAITING_FOR_CUSTOMER"

OPEN_APPROVAL_STATES: Final[tuple[str, ...]] = (
    ApprovalRequestState.SENT.value,
    ApprovalRequestState.CONFIRMATION_PENDING.value,
)
"""Request states in which a customer could still answer. Everything else is settled."""

EVENT_CASE_WAITING: Final = "case.waiting"
EVENT_CASE_REVALIDATION_READY: Final = "case.revalidation_ready"
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


async def settled_case_state(connection: AsyncConnection, *, case: LockedCase) -> str | None:
    """The state this case should move to now that a transition has finished, or ``None``.

    Called by every transition that can be the *last* one -- a recovery finishing, an approval
    request going out, a decision arriving -- because which of them finishes last depends on how
    fast a provider answered, and a case whose state depended on that would be a case whose
    state depended on luck. Each of them asks the same question of the same rows, under the case
    lock it already holds, and at most one of them gets an answer.

    Two transitions live here, both from §14.2:

    * ``EXECUTING -> WAITING``: nothing runnable is left and at least one track is genuinely
      waiting on a customer. A track still ``PENDING`` or ``APPLYING`` blocks it, which is what
      makes "do not wait while A is still applying" structural rather than a matter of ordering.
    * ``WAITING -> REVALIDATING``: no approval request can be answered any more, because every
      one of them has been decided or has expired. Revalidation itself is a later slice; what
      this does is hand the case to it durably rather than leaving it parked on a customer who
      has already replied.

    A case that finishes executing to find its request *already* answered goes straight to
    ``REVALIDATING``. §14.2 permits ``EXECUTING`` to skip ``WAITING`` when there is nothing to
    wait for, and a customer who replied while the last recovery was still running is exactly
    that: entering ``WAITING`` would be waiting for an answer already in the database, and
    nothing would ever come to wake it.

    Read without ``FOR UPDATE`` deliberately: every transition that could move one of these rows
    takes the case row first, and this transaction is holding it.
    """
    if case.state == CASE_EXECUTING:
        if not await _ready_to_wait(connection, case.id):
            return None
        return CASE_WAITING if await _has_open_approval(connection, case.id) else CASE_REVALIDATING
    if case.state == CASE_WAITING:
        return None if await _has_open_approval(connection, case.id) else CASE_REVALIDATING
    return None


async def _ready_to_wait(connection: AsyncConnection, case_id: UUID) -> bool:
    """Nothing left to run, and something real to wait for."""
    states = set(
        (await connection.execute(select(Track.state).where(Track.case_id == case_id))).scalars()
    )
    return TRACK_WAITING_FOR_CUSTOMER in states and not states & set(RUNNABLE_TRACK_STATES)


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
    return ()
