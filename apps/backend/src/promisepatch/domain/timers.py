"""Deadlines that are rows, so downtime delays them and never loses them.

There is no scheduler here, and that is the point. A timer is a row with a due date; firing one
is a short transaction that turns it into a case step. A worker that is killed while a deadline
is pending loses nothing, and a worker that starts an hour late finds every overdue deadline
waiting and fires them all immediately -- which is exactly what should happen, because the
deadlines passed whether or not anybody was running.

Three properties, all enforced by the database rather than by this module:

* **One live timer per subject.** A partial unique index over ``(kind, subject_type,
  subject_id) WHERE fired_at IS NULL`` means arming a deadline twice produces one row. Arming
  is therefore idempotent, so a transition that is retried after a crash re-arms harmlessly.
* **One logical wake-up per timer.** The step a firing creates is keyed ``timer:{id}``, derived
  from the timer rather than invented, so two workers polling at the same instant -- or one
  worker polling twice -- cannot produce two wake-ups.
* **Fire and cancel cannot both win.** Both take the row lock; whichever is second re-evaluates
  its predicate against the row the first one left. A cancel that arrives after a firing
  deletes nothing, because the row is no longer unfired.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.db.clock import database_now
from promisepatch.db.events import append_event
from promisepatch.db.models import Timer
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.domain import crash, handlers
from promisepatch.domain.model import CASE_SUBJECT, EVENT_TIMER_FIRED, StepKind
from promisepatch.observability import get_logger

logger = get_logger(__name__)

_LIVE = "fired_at IS NULL"


@dataclass(frozen=True, slots=True)
class FiredTimer:
    """One deadline that has just become a piece of work."""

    timer_id: UUID
    kind: str
    subject_type: str
    subject_id: str
    step_key: str | None
    seq: int


async def arm_timer(
    connection: AsyncConnection,
    *,
    kind: str,
    subject_type: str,
    subject_id: str,
    due_at: datetime,
) -> UUID | None:
    """Arm a deadline, or leave the one already armed alone.

    Returns the new timer's id, or ``None`` when a live timer for this subject already existed.
    Deliberately *not* an update: re-arming must not move a deadline that is already counting
    down, because the first arming is the one that reflects when the wait actually started.
    """
    statement = (
        pg_insert(Timer)
        .values(
            id=uuid4(),
            kind=kind,
            subject_type=subject_type,
            subject_id=subject_id,
            due_at=due_at,
        )
        .on_conflict_do_nothing(
            index_elements=[Timer.kind, Timer.subject_type, Timer.subject_id],
            index_where=Timer.fired_at.is_(None),
        )
        .returning(Timer.id)
    )
    return (await connection.execute(statement)).scalar_one_or_none()


async def cancel_timer(
    connection: AsyncConnection, *, kind: str, subject_type: str, subject_id: str
) -> int:
    """Delete the live timer for a subject, if there still is one. Returns how many were removed.

    Only ever called from inside the governed transition that makes the deadline obsolete, so a
    cancellation and the reason for it commit together. Racing a firing is safe in both
    directions: this deletes only rows that are still unfired, and a firing that has already
    committed leaves nothing here to delete.
    """
    result = await connection.execute(
        delete(Timer).where(
            Timer.kind == kind,
            Timer.subject_type == subject_type,
            Timer.subject_id == subject_id,
            Timer.fired_at.is_(None),
        )
    )
    return int(result.rowcount)


async def fire_due_timer(database: RuntimeDatabase, *, worker: str) -> FiredTimer | None:
    """Fire at most one overdue deadline, in a transaction of its own.

    No lease and no claim state: a timer is either unfired or fired, and the row lock held for
    the length of this short transaction is the whole of the mutual exclusion. A worker killed
    mid-firing leaves the timer unfired and the step uncreated, and the next poll does it again
    from the beginning.

    Ungoverned throughout. A deadline arriving is not a decision about a customer promise; the
    step it creates is what will eventually make one, under its own audited transition.
    """
    async with database.begin() as connection:
        now = await database_now(connection)
        candidate = (
            await connection.execute(
                select(Timer.id, Timer.kind, Timer.subject_type, Timer.subject_id)
                .where(Timer.fired_at.is_(None), Timer.due_at <= now)
                .order_by(Timer.due_at, Timer.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).one_or_none()
        if candidate is None:
            return None

        step_key: str | None = None
        if candidate.subject_type == CASE_SUBJECT:
            # Imported here rather than at module scope: `steps` needs `timers` for arming and
            # cancellation, so the two modules refer to each other and one of the edges has to
            # be deferred. This is the edge that runs once per fired deadline, not per step.
            from promisepatch.domain.steps import enqueue_step

            step_key = handlers.timer_step_key(candidate.id)
            await enqueue_step(
                connection,
                case_id=UUID(candidate.subject_id),
                step_key=step_key,
                kind=StepKind.TIMER_WAKEUP,
            )

        fired = (
            await connection.execute(
                update(Timer)
                .where(Timer.id == candidate.id, Timer.fired_at.is_(None))
                .values(fired_at=now, claimed_by=worker, claimed_at=now)
            )
        ).rowcount
        if fired != 1:
            # Unreachable under the row lock, and asserted anyway: firing twice would mean two
            # logical wake-ups, which the step key would absorb but which must not be silent.
            raise RuntimeError(f"timer {candidate.id} was fired by someone else under a held lock")

        seq = await append_event(
            connection,
            event_type=EVENT_TIMER_FIRED,
            correlation_id=uuid4(),
            occurred_at=now,
            case_id=UUID(candidate.subject_id) if candidate.subject_type == CASE_SUBJECT else None,
            entity_refs=[{"kind": "timer", "id": str(candidate.id)}],
            payload={
                "kind": candidate.kind,
                "subject_type": candidate.subject_type,
                "subject_id": candidate.subject_id,
                "step_key": step_key,
            },
        )
        crash.at(crash.BEFORE_TIMER_COMMIT)

    logger.info(
        "worker.timer.fired",
        timer_id=str(candidate.id),
        kind=candidate.kind,
        subject_id=candidate.subject_id,
        step_key=step_key,
    )
    return FiredTimer(
        timer_id=candidate.id,
        kind=candidate.kind,
        subject_type=candidate.subject_type,
        subject_id=candidate.subject_id,
        step_key=step_key,
        seq=seq,
    )
