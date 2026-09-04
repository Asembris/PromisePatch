"""Reading the event spine, which is the only authoritative account of what happened.

The live feed is built out of this module and a wake-up signal, in that order of importance. A
notification says *something changed*; these queries say *what*, from the durable rows, so a
notification that was dropped, delayed or duplicated costs a subscriber latency and never
costs it state.

Two properties of the read are load-bearing:

* **``seq`` is the cursor.** It is the sequence the whole system already checkpoints against --
  a graph snapshot is stamped with the ``seq`` it was loaded at -- so a subscriber's position
  in the stream and a reader's view of the graph are the same coordinate.
* **The read is ordered and bounded.** Ascending ``seq``, with a caller-supplied limit, so a
  subscriber that has been away cannot ask one query to materialise an unbounded history.

**Commit order is what makes the cursor safe, and it is enforced in PostgreSQL.** ``seq`` is
drawn at INSERT and becomes visible at COMMIT, so two overlapping writers could in principle
commit sequence values out of order, and a cursor that only ever moves forward would step over
the later-committing, lower-numbered row -- permanently. A ``BEFORE INSERT`` trigger takes
:data:`~promisepatch.db.boundary.EVENT_ORDER_LOCK_KEY` as a transaction advisory lock and draws
``seq`` only once it holds it, so a transaction cannot obtain a sequence value while an earlier,
lower-numbered one is still unfinished. For committed events, ``seq(e1) < seq(e2)`` implies
``commit(e1) < commit(e2)``.

The correctness lives in the database rather than in this module because there is no way for a
reader to check it, and no way to ask every future writer to remember it. What writers *do*
have to remember is the other half -- see :func:`append_event` for the lock order that keeps
the guarantee from becoming a queue.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.db.models import DomainEvent


@dataclass(frozen=True, slots=True)
class DomainEventRecord:
    """One row of the spine, reduced to what a subscriber is allowed to learn from it.

    ``payload`` and ``correlation_id`` are deliberately absent. The payload is an open
    structure whose contents are decided by whatever wrote the event -- an order, a customer, a
    message body -- and a feed that forwarded it would be publishing business detail to every
    signed-in browser on the strength of a schema nobody had reviewed for that purpose. What a
    subscriber needs is the sequence, the kind of thing that happened and what it happened to;
    the authoritative read APIs supply the rest, under their own rules.
    """

    seq: int
    event_id: UUID
    type: str
    case_id: UUID | None
    entity_refs: tuple[Any, ...]
    occurred_at: datetime


_COLUMNS = (
    DomainEvent.seq,
    DomainEvent.event_id,
    DomainEvent.type,
    DomainEvent.case_id,
    DomainEvent.entity_refs,
    DomainEvent.occurred_at,
)


async def append_event(
    connection: AsyncConnection,
    *,
    event_type: str,
    correlation_id: UUID,
    occurred_at: datetime,
    case_id: UUID | None = None,
    entity_refs: Sequence[Any] = (),
    payload: Mapping[str, Any] | None = None,
    event_id: UUID | None = None,
) -> int:
    """Append one event to the spine and return the sequence it was given.

    **Call this last.** Inserting here takes
    :data:`~promisepatch.db.boundary.EVENT_ORDER_LOCK_KEY` and holds it until the transaction
    ends, so from this point on the transaction should acquire no further lock and do no
    further waiting -- every other event-producing transaction in the system is queued behind
    it. The order every writer follows is:

        ``case_steps`` row → ``cases`` row → owned timer / inbox / outbox rows → this → COMMIT

    A transaction that appended an event and then blocked on a row somebody else held would
    stall the whole spine, and if that somebody were itself waiting to append, the pair would
    deadlock. PostgreSQL would detect and abort one of them, which is a correct outcome and a
    bad design; the ordering is what stops it arising.

    Writes to *its own* rows after this point are fine, and are the reason the rule is phrased
    as "acquire no further lock" rather than "issue no further statement": a row this
    transaction inserted is already locked by it, so stamping the sequence number back onto an
    outbox message it just created waits for nobody.

    ``occurred_at`` is passed in rather than defaulted to ``now()``, so an event carries the
    instant the transaction read once and used for every decision in it.
    """
    statement = (
        insert(DomainEvent)
        .values(
            event_id=event_id or uuid4(),
            type=event_type,
            case_id=case_id,
            entity_refs=list(entity_refs),
            payload=dict(payload or {}),
            correlation_id=correlation_id,
            occurred_at=occurred_at,
        )
        .returning(DomainEvent.seq)
    )
    return int((await connection.execute(statement)).scalar_one())


async def latest_seq(connection: AsyncConnection) -> int:
    """The highest committed sequence number, or ``0`` when the spine is empty.

    ``0`` rather than ``None`` because it is a cursor: a subscriber starting from an empty
    ledger asks for everything after nothing, and ``seq`` starts at one.
    """
    value = await connection.scalar(select(func.coalesce(func.max(DomainEvent.seq), 0)))
    return int(value or 0)


async def read_after(
    connection: AsyncConnection, *, after_seq: int, limit: int
) -> tuple[DomainEventRecord, ...]:
    """Committed events with ``seq`` greater than ``after_seq``, ascending, at most ``limit``.

    Ascending order is the contract, not an incidental property of the query plan: a consumer
    advances its cursor to the last row it received, and a batch that arrived out of order
    would let it step over rows it had not seen.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    rows = (
        await connection.execute(
            select(*_COLUMNS)
            .where(DomainEvent.seq > after_seq)
            .order_by(DomainEvent.seq)
            .limit(limit)
        )
    ).mappings()
    return tuple(_record(row) for row in rows)


def _record(row: RowMapping) -> DomainEventRecord:
    return DomainEventRecord(
        seq=int(row["seq"]),
        event_id=row["event_id"],
        type=row["type"],
        case_id=row["case_id"],
        entity_refs=tuple(row["entity_refs"] or ()),
        occurred_at=row["occurred_at"],
    )
