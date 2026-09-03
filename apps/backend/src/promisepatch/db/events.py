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

**A note on commit order.** ``seq`` is drawn at INSERT and becomes visible at COMMIT, so two
overlapping writers could in principle commit sequence values out of order and a cursor that
only ever moves forward would step over the later-committing, lower-numbered row. Today that
cannot happen: every ``domain_events`` insert is made by :mod:`promisepatch.fixtures.reset`,
which holds ``pg_advisory_xact_lock`` for its whole transaction, so domain events commit in
sequence order by construction. The case engine will introduce a second writer, and when it
does, either that serialisation has to be preserved or the cursor has to gain a commit-ordered
coordinate. It is written down here because it is the one assumption this module cannot check
for itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
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
