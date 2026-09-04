"""The one property the forward-only SSE cursor cannot survive without.

``domain_events.seq`` is the coordinate every subscriber advances through, and it only moves
forward. That is safe if and only if committed sequence numbers agree with commit order:

    seq(e1) < seq(e2)  ⇒  commit(e1) < commit(e2)

Without it, two overlapping writers can commit out of order -- B takes ``N+1`` and commits, a
reader advances past it, then A commits ``N`` and is *permanently* behind the cursor. The row is
in the ledger and no subscriber will ever be shown it.

The guarantee is enforced by a ``BEFORE INSERT`` trigger that takes a transaction advisory lock
before drawing ``seq``, so these tests coordinate on that lock explicitly. Nothing here passes
because a sleep was long enough: the blocked transaction is proven blocked by a ``lock_timeout``
it could only hit while waiting, and the unblocked one is proven unblocked by succeeding.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from promisepatch.db import build_engine
from promisepatch.db.boundary import EVENT_ORDER_LOCK_KEY
from promisepatch.db.events import append_event, read_after

pytestmark = pytest.mark.integration

LOCK_NOT_AVAILABLE = "55P03"

EVENT_TYPE = "test.event-order"
"""A type of its own, so these rows are identifiable in a ledger nothing may delete."""

CLASSID = (EVENT_ORDER_LOCK_KEY >> 32) & 0xFFFFFFFF
OBJID = EVENT_ORDER_LOCK_KEY & 0xFFFFFFFF
"""How PostgreSQL splits a 64-bit advisory key across ``pg_locks``: high half, then low half."""

BLOCK_TIMEOUT = "250ms"
"""How long a transaction waits before reporting that it is blocked.

A failure bound, not a synchronisation device. The lock is either held or it is not; this only
decides how long the test is willing to sit there finding out.
"""


@pytest_asyncio.fixture
async def writer(app_database_url: str) -> AsyncIterator[AsyncConnection]:
    """An independent runtime connection, so two transactions can genuinely overlap."""
    engine: AsyncEngine = build_engine(app_database_url, pool_size=1)
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def other_writer(app_database_url: str) -> AsyncIterator[AsyncConnection]:
    engine: AsyncEngine = build_engine(app_database_url, pool_size=1)
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


async def append(connection: AsyncConnection, **overrides: object) -> int:
    return await append_event(
        connection,
        event_type=EVENT_TYPE,
        correlation_id=uuid4(),
        occurred_at=datetime.now(UTC),
        payload={"marker": uuid4().hex},
        **overrides,  # type: ignore[arg-type]
    )


async def backend_pid(connection: AsyncConnection) -> int:
    return int((await connection.execute(text("SELECT pg_backend_pid()"))).scalar_one())


async def holds_event_order_lock(observer: AsyncConnection, pid: int) -> bool:
    """Whether ``pid`` holds the spine's advisory lock, asked of a third connection."""
    granted = (
        await observer.execute(
            text(
                "SELECT granted FROM pg_locks WHERE locktype = 'advisory'"
                " AND pid = :pid AND classid = :classid AND objid = :objid AND objsubid = 1"
            ),
            {"pid": pid, "classid": CLASSID, "objid": OBJID},
        )
    ).scalars()
    return list(granted) == [True]


def sqlstate(error: DBAPIError) -> str:
    return str(getattr(error.orig, "sqlstate", ""))


# ------------------------------------------------------------------------------ lock ownership


async def test_appending_an_event_takes_the_ordering_lock_for_the_whole_transaction(
    writer: AsyncConnection, conn: AsyncConnection
) -> None:
    """The lock is what serialises sequence assignment, and it is held to the end.

    Asked of a *third* connection: a transaction reporting on its own locks proves only that it
    can read a catalog, and the property that matters is that everyone else can see it held.
    """
    pid = await backend_pid(writer)
    assert not await holds_event_order_lock(conn, pid)

    await append(writer)
    assert await holds_event_order_lock(conn, pid)

    await writer.rollback()
    assert not await holds_event_order_lock(conn, pid)


async def test_the_lock_is_released_by_commit_and_not_before(
    writer: AsyncConnection, conn: AsyncConnection
) -> None:
    pid = await backend_pid(writer)
    await append(writer)
    assert await holds_event_order_lock(conn, pid)
    await writer.commit()
    assert not await holds_event_order_lock(conn, pid)


# ------------------------------------------------------------------------ concurrent insertion


async def test_a_second_writer_cannot_draw_a_sequence_while_the_first_is_open(
    writer: AsyncConnection, other_writer: AsyncConnection
) -> None:
    """This is the hazard, closed: B cannot get ``N+1`` until A has decided about ``N``.

    B is proven blocked rather than merely slow -- it fails with ``lock_not_available``, which
    only a transaction that was waiting on a lock can produce.
    """
    first_seq = await append(writer)

    await other_writer.execute(text(f"SET LOCAL lock_timeout = '{BLOCK_TIMEOUT}'"))
    with pytest.raises(DBAPIError) as blocked:
        await append(other_writer)
    assert sqlstate(blocked.value) == LOCK_NOT_AVAILABLE
    await other_writer.rollback()

    # A commits; the number it took is now settled, and B may draw the next one.
    await writer.commit()

    second_seq = await append(other_writer)
    assert second_seq > first_seq
    await other_writer.commit()

    committed = await read_after(writer, after_seq=first_seq - 1, limit=50)
    ordered = [record.seq for record in committed]
    assert ordered == sorted(ordered)
    assert first_seq in ordered
    assert second_seq in ordered


async def test_a_rolled_back_writer_leaves_the_forward_reader_a_usable_cursor(
    writer: AsyncConnection, other_writer: AsyncConnection
) -> None:
    """A abandons its number; B commits a later one. Gaps are fine, skipped rows are not."""
    before = await _latest(writer)
    await writer.rollback()

    abandoned = await append(writer)
    await writer.rollback()

    kept = await append(other_writer)
    await other_writer.commit()

    assert kept > abandoned

    records = await read_after(writer, after_seq=before, limit=50)
    sequences = [record.seq for record in records]
    assert abandoned not in sequences
    assert kept in sequences
    assert sequences == sorted(sequences)


# --------------------------------------------------------------------------- multi-row append


async def test_several_events_in_one_transaction_keep_their_order(
    writer: AsyncConnection,
) -> None:
    """One transaction holds the lock throughout, so its own events are numbered in sequence."""
    sequences = [await append(writer) for _ in range(4)]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    await writer.rollback()


async def test_a_committed_batch_reads_back_in_the_order_it_was_written(
    writer: AsyncConnection,
) -> None:
    before = await _latest(writer)
    await writer.rollback()

    sequences = [await append(writer) for _ in range(3)]
    await writer.commit()

    records = await read_after(writer, after_seq=before, limit=50)
    assert [record.seq for record in records if record.seq in set(sequences)] == sequences


async def _latest(connection: AsyncConnection) -> int:
    statement = text("SELECT coalesce(max(seq), 0) FROM promisepatch.domain_events")
    value = (await connection.execute(statement)).scalar_one()
    return int(value)
