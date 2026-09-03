"""The live feed: a durable ledger, a wake-up, and one frame format between them.

The whole design is one sentence. **The stream never becomes the state.** A subscriber's
position is a ``domain_events.seq``; every frame it receives was read from that table; the
in-memory signal from the listener only decides *when* the table is read, never *what* is in it.
Everything else here follows:

* **Subscribe first, then read.** A subscription is attached before the first query runs, so an
  event committed while that query is in flight sets the signal that is already waiting. There
  is no window between "finished replaying" and "started listening" for an event to fall into,
  because those are not two phases -- the loop reads from its cursor, waits, and reads again.
* **A wake-up carries nothing.** It is a bare call: no sequence number, no payload. A dropped
  one costs latency, a duplicated one costs an empty query, and neither can cost state. The
  keepalive tick reads too, so even a feed whose notifications are entirely lost still catches
  up on its own.
* **Memory per subscriber is one flag.** Not a queue of events: signals coalesce, so a slow
  subscriber cannot make the process accumulate anything on its behalf. Falling behind costs it
  a bigger read, and past :data:`MAX_REPLAY_EVENTS` it costs it a ``resync`` -- never a growing
  buffer, and never a silently dropped event.
* **A hang-up ends the stream and never a read.** Cancelling a task that is inside a context
  manager destroys its cleanup -- the first await in the exit path re-raises the cancellation --
  so a browser closing a tab mid-query would otherwise leak the database connection that query
  was using. Reads are therefore detached from the stream that asked for them.
* **Delivery is at least once.** A reconnect replays from the client's cursor, so an event
  already seen may arrive twice; the frames carry stable identifiers so a client can tell. This
  is stated rather than engineered around, because exactly-once over a transport that can drop a
  connection mid-frame is not a thing anyone can honestly offer.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Coroutine, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from promisepatch.api.schemas.events import DomainEventEnvelope, ResyncEnvelope
from promisepatch.db import RuntimeDatabase
from promisepatch.db import events as ledger
from promisepatch.db.events import DomainEventRecord

LAST_EVENT_ID_HEADER: Final = "Last-Event-ID"
"""The reconnect cursor, exactly as the browser's own ``EventSource`` sends it."""

KEEPALIVE_INTERVAL: Final = 15.0
"""Seconds of quiet before a comment frame is sent.

Short enough to keep an idle connection out of the way of the proxy and browser timeouts that
would otherwise close it, long enough that an open feed costs one line a quarter minute. A
constant rather than a setting: nothing has asked to vary it, and an environment variable
nobody sets is a promise the code does not keep.
"""

MAX_REPLAY_EVENTS: Final = 500
"""How much history one connection will replay before declaring the subscriber out of date.

A bound has to exist, or a browser left open over a weekend could ask a single connection to
read the whole ledger. Five hundred is far more than a reconnecting client accumulates in a
demo or a shift, and beyond it a full refetch of the read APIs is both cheaper and more correct
than a long catch-up.
"""

RESYNC_EVENT: Final = "resync"
NO_CURSOR: Final = "no_cursor"
REPLAY_BOUND_EXCEEDED: Final = "replay_bound_exceeded"

KEEPALIVE_FRAME: Final = b": keepalive\n\n"
"""An SSE comment. It carries no ``id:``, so it cannot move a subscriber's cursor, and it is
not an event, so it cannot be mistaken for one."""

MAX_CURSOR: Final = 2**63 - 1
"""``seq`` is a ``bigint``; a cursor larger than one could never name a row."""

_DIGITS: Final = re.compile(r"^[0-9]+$")


class InvalidCursorError(ValueError):
    """Raised when ``Last-Event-ID`` is present but is not a sequence number."""


def parse_cursor(value: str | None) -> int | None:
    """The sequence a reconnecting subscriber is resuming from, or ``None`` for a fresh one.

    Strict on purpose. The header is client-controlled and goes straight into a query bound, so
    anything that is not a plain non-negative integer within range is refused rather than
    coerced -- an unreadable cursor is a client bug, and silently treating it as "start from
    now" would hide that bug behind exactly the missed events it caused.
    """
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        # Browsers omit the header until they have seen an id; an empty one means the same.
        return None
    if not _DIGITS.match(candidate) or int(candidate) > MAX_CURSOR:
        raise InvalidCursorError(f"{LAST_EVENT_ID_HEADER} must be a domain event sequence number")
    return int(candidate)


# ------------------------------------------------------------------------------ the fan-out


class Subscription:
    """One subscriber's wake-up flag.

    A flag rather than a queue, which is what makes the memory story trivial: however far
    behind a subscriber falls, and however many events arrive while it is away, this is one
    boolean. What it lost is not lost -- it is in the ledger, and the next read finds it.
    """

    __slots__ = ("_signal",)

    def __init__(self) -> None:
        self._signal = asyncio.Event()

    def arm(self) -> None:
        """Clear the flag before reading, so a wake-up during the read is not missed."""
        self._signal.clear()

    def wake(self) -> None:
        self._signal.set()

    async def wait(self, timeout: float) -> bool:
        """Wait for a wake-up. ``False`` means the timeout came first."""
        try:
            await asyncio.wait_for(self._signal.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True


class EventBroadcaster:
    """The process's in-memory fan-out: one listener in, every open stream out.

    Deliberately the least reliable component in the path, and deliberately allowed to be. It
    is an optimisation over polling; if it dropped every signal, each stream would still catch
    up on its next keepalive tick and every reconnect would still replay from PostgreSQL.
    """

    def __init__(self) -> None:
        self._subscribers: set[Subscription] = set()

    def subscribe(self) -> Subscription:
        subscription = Subscription()
        self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        self._subscribers.discard(subscription)

    def publish(self) -> None:
        """Tell every open stream to read the ledger. Carries no state, by construction."""
        for subscription in tuple(self._subscribers):
            subscription.wake()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# -------------------------------------------------------------------------------- the ledger


class EventReader(Protocol):
    """The two questions a stream asks of the durable ledger."""

    async def latest_seq(self) -> int: ...

    async def read_after(self, after_seq: int, limit: int) -> Sequence[DomainEventRecord]: ...


@dataclass(frozen=True, slots=True)
class DatabaseEventReader:
    """Reads the spine over the runtime connection, one short transaction at a time.

    A connection is taken for the read and given straight back, rather than held for the life
    of the stream. A subscriber sitting idle for an hour should own no database resource at
    all; what it owns is a cursor.
    """

    database: RuntimeDatabase

    async def latest_seq(self) -> int:
        async with self.database.connect() as connection:
            return await ledger.latest_seq(connection)

    async def read_after(self, after_seq: int, limit: int) -> Sequence[DomainEventRecord]:
        async with self.database.connect() as connection:
            return await ledger.read_after(connection, after_seq=after_seq, limit=limit)


# -------------------------------------------------------------------------------- the frames


def event_frame(record: DomainEventRecord) -> bytes:
    """One committed event as an SSE frame, identified by the sequence it will be resumed from."""
    envelope = DomainEventEnvelope.of(record)
    return (
        f"id: {record.seq}\nevent: {record.type}\ndata: {envelope.model_dump_json()}\n\n"
    ).encode()


def resync_frame(latest_seq: int, *, skipped_from: int, reason: str, detail: str) -> bytes:
    """A frame that says the feed is not continuous here, and where it has resumed from."""
    envelope = ResyncEnvelope(
        latest_seq=latest_seq, skipped_from_seq=skipped_from, reason=reason, detail=detail
    )
    return (
        f"id: {latest_seq}\nevent: {RESYNC_EVENT}\ndata: {envelope.model_dump_json()}\n\n"
    ).encode()


# -------------------------------------------------------------------------------- the stream


async def event_stream(
    *,
    reader: EventReader,
    broadcaster: EventBroadcaster,
    cursor: int | None,
    keepalive: float = KEEPALIVE_INTERVAL,
    max_replay: int = MAX_REPLAY_EVENTS,
) -> AsyncIterator[bytes]:
    """Frames for one subscriber, from ``cursor`` onwards, until the client goes away.

    The subscription is taken out before anything is read and released when the generator is
    closed, which is what makes the replay-to-live handover a non-event: there is no handover.
    """
    subscription = broadcaster.subscribe()
    try:
        if cursor is not None:
            position = cursor
        else:
            # A subscriber with no cursor has no idea what it missed, and neither do we. It is
            # told where the ledger is so its next reconnect resumes from a real position, and
            # told to load the read APIs rather than being left to infer a starting state from
            # a feed that begins mid-sentence.
            position = await _detached(reader.latest_seq())
            yield resync_frame(
                position,
                skipped_from=0,
                reason=NO_CURSOR,
                detail="no resume point was presented; load the read APIs for current state",
            )
        while True:
            subscription.arm()
            frames, position = await _detached(_catch_up(reader, position, max_replay))
            for frame in frames:
                yield frame
            if not await subscription.wait(keepalive):
                yield KEEPALIVE_FRAME
    finally:
        broadcaster.unsubscribe(subscription)


_READS_IN_FLIGHT: Final[set[asyncio.Task[Any]]] = set()
"""Strong references to detached reads, because the loop keeps only weak ones.

A task nobody holds can be collected while it is still waiting on the socket, which would lose
the very connection detaching it was meant to return.
"""


async def _detached[T](work: Coroutine[Any, Any, T]) -> T:
    """Run ``work`` in a task of its own, so a disconnect cannot cancel it half-finished.

    The stream is cancelled when its client goes away, and a cancelled task cannot clean up
    after itself: every await in a context manager's exit path re-raises the cancellation, so a
    database connection acquired inside one is never handed back. Detaching means the hang-up
    ends the stream immediately, as it should, while the read it was in the middle of runs to
    completion and releases what it borrowed.
    """
    task = asyncio.create_task(work)
    _READS_IN_FLIGHT.add(task)
    task.add_done_callback(_READS_IN_FLIGHT.discard)
    return await asyncio.shield(task)


async def _catch_up(reader: EventReader, position: int, max_replay: int) -> tuple[list[bytes], int]:
    """Everything committed after ``position``, or a ``resync`` if that is too much history.

    One row past the bound is read deliberately: it is the difference between "there are exactly
    this many" and "there are at least this many", and the second is what decides a resync.
    """
    records = await reader.read_after(position, max_replay + 1)
    if len(records) > max_replay:
        latest = await reader.latest_seq()
        frame = resync_frame(
            max(latest, position),
            skipped_from=position,
            reason=REPLAY_BOUND_EXCEEDED,
            detail=(
                f"more than {max_replay} events have been recorded since this resume point; "
                "load the read APIs for current state"
            ),
        )
        return [frame], max(latest, position)
    if not records:
        return [], position
    return [event_frame(record) for record in records], records[-1].seq
