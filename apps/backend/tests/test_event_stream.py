"""The live feed's correctness, proven against a ledger this test controls exactly.

The database is not involved here, deliberately. Every property that matters about the stream
is a property of *ordering* -- what is read, when a subscriber is woken, and what happens to an
event that commits in the narrow moment between the two -- and those are questions a real
database can only be asked by racing it and hoping. A stand-in ledger can be made to commit an
event at precisely the instant a read is in flight, so the proof is deterministic rather than
probabilistic, and there is not a single sleep in this file waiting for something to maybe
happen.

What a real PostgreSQL contributes -- that ``seq`` is durable and monotonic, that a rolled-back
event leaves nothing behind, that a notification arrives only on commit -- is proven against a
real PostgreSQL in ``test_domain_events.py``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from promisepatch.api.stream import (
    KEEPALIVE_FRAME,
    NO_CURSOR,
    REPLAY_BOUND_EXCEEDED,
    RESYNC_EVENT,
    EventBroadcaster,
    InvalidCursorError,
    Subscription,
    event_stream,
    parse_cursor,
)
from promisepatch.db.events import DomainEventRecord

OCCURRED_AT = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)

PATIENCE = 5.0
"""How long a frame that should arrive immediately is given before the test fails.

Not a synchronisation device -- every wake-up in this file is deterministic. It is the
difference between a broken stream failing the suite and a broken stream hanging it.
"""


class FakeLedger:
    """An append-only sequence with the two reads the stream performs, and a seam to race it.

    ``after_read`` is called once the batch has been computed and before it is returned, which
    is exactly the position a concurrently committing transaction occupies: its row is not in
    the result the reader is about to receive, and its notification has already been sent.
    """

    def __init__(self, *, after_read: Callable[[], None] | None = None) -> None:
        self.records: list[DomainEventRecord] = []
        self.reads = 0
        self.after_read = after_read

    def append(self, *, event_type: str = "test.event") -> DomainEventRecord:
        record = DomainEventRecord(
            seq=len(self.records) + 1,
            event_id=uuid4(),
            type=event_type,
            case_id=None,
            entity_refs=(),
            occurred_at=OCCURRED_AT,
        )
        self.records.append(record)
        return record

    async def latest_seq(self) -> int:
        return self.records[-1].seq if self.records else 0

    async def read_after(self, after_seq: int, limit: int) -> Sequence[DomainEventRecord]:
        self.reads += 1
        batch = [record for record in self.records if record.seq > after_seq][:limit]
        if self.after_read is not None:
            hook, self.after_read = self.after_read, None
            hook()
        return batch


def parse_frame(raw: bytes) -> dict[str, Any]:
    """One SSE frame, split into the fields a client would read off it."""
    frame: dict[str, Any] = {"id": None, "event": None, "data": None, "comment": None}
    for line in raw.decode().split("\n"):
        if line.startswith(": "):
            frame["comment"] = line[2:]
        elif line.startswith("id: "):
            frame["id"] = line[4:]
        elif line.startswith("event: "):
            frame["event"] = line[7:]
        elif line.startswith("data: "):
            frame["data"] = json.loads(line[6:])
    return frame


async def next_frame(stream: Any) -> dict[str, Any]:
    return parse_frame(await asyncio.wait_for(anext(stream), timeout=PATIENCE))


async def frames(stream: Any, count: int) -> list[dict[str, Any]]:
    return [await next_frame(stream) for _ in range(count)]


def open_stream(
    ledger: FakeLedger,
    broadcaster: EventBroadcaster,
    *,
    cursor: int | None,
    keepalive: float = 60.0,
    max_replay: int = 500,
) -> Any:
    """A stream whose keepalive is far away, so nothing in a test can pass by timing out."""
    return event_stream(
        reader=ledger,
        broadcaster=broadcaster,
        cursor=cursor,
        keepalive=keepalive,
        max_replay=max_replay,
    )


# ------------------------------------------------------------------------------------ replay


async def test_a_reconnect_replays_exactly_what_follows_the_cursor() -> None:
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    for _ in range(4):
        ledger.append()

    stream = open_stream(ledger, broadcaster, cursor=2)
    try:
        replayed = await frames(stream, 2)
    finally:
        await stream.aclose()

    assert [frame["id"] for frame in replayed] == ["3", "4"]
    assert [frame["data"]["seq"] for frame in replayed] == [3, 4]


async def test_replay_is_in_ascending_sequence_order() -> None:
    """A consumer advances its cursor to the last row it saw; out of order it would skip rows."""
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    for _ in range(25):
        ledger.append()

    stream = open_stream(ledger, broadcaster, cursor=0)
    try:
        replayed = await frames(stream, 25)
    finally:
        await stream.aclose()

    sequences = [frame["data"]["seq"] for frame in replayed]
    assert sequences == sorted(sequences) == list(range(1, 26))


async def test_a_subscriber_with_no_cursor_is_told_where_the_ledger_is() -> None:
    """It is not replayed the world, and it is not left without a resume point either.

    Without an id the browser would reconnect from "now" again, so an event that committed
    during the gap would be lost with nothing to notice it. The resync frame carries an id, so
    the next reconnect resumes from a real position.
    """
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    for _ in range(3):
        ledger.append()

    stream = open_stream(ledger, broadcaster, cursor=None)
    try:
        first = await next_frame(stream)
    finally:
        await stream.aclose()

    assert first["event"] == RESYNC_EVENT
    assert first["id"] == "3"
    assert first["data"]["reason"] == NO_CURSOR
    assert first["data"]["latest_seq"] == 3


async def test_a_duplicate_reconnect_may_redeliver_and_cannot_lose() -> None:
    """At-least-once is the honest guarantee, so the same cursor twice is the same events."""
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    for _ in range(3):
        ledger.append()

    seen = []
    for _ in range(2):
        stream = open_stream(ledger, broadcaster, cursor=1)
        try:
            seen.append([frame["data"]["seq"] for frame in await frames(stream, 2)])
        finally:
            await stream.aclose()

    assert seen == [[2, 3], [2, 3]]


# ---------------------------------------------------------------------- the replay/live seam


async def test_an_event_committed_during_the_replay_read_is_still_delivered() -> None:
    """The proof that there is no window between replaying and listening.

    The ledger appends a fourth event *after* the replay batch has been computed and publishes
    the wake-up for it while that read is still in flight. If the stream subscribed only once
    replay had finished, the wake-up would land on nobody and the event would be lost until the
    next keepalive; the keepalive here is a minute away, so nothing but a subscription that was
    already attached can make this test pass.
    """
    broadcaster = EventBroadcaster()
    ledger = FakeLedger()
    for _ in range(3):
        ledger.append()

    def commit_during_the_read() -> None:
        ledger.append(event_type="raced.event")
        broadcaster.publish()

    ledger.after_read = commit_during_the_read

    stream = open_stream(ledger, broadcaster, cursor=2)
    try:
        delivered = await frames(stream, 2)
    finally:
        await stream.aclose()

    assert [frame["data"]["seq"] for frame in delivered] == [3, 4]
    assert delivered[1]["event"] == "raced.event"


async def test_a_subscription_exists_before_the_first_read_happens() -> None:
    """The same guarantee, asserted structurally rather than through its consequence."""
    broadcaster = EventBroadcaster()
    ledger = FakeLedger()
    ledger.append()
    subscribers_during_first_read: list[int] = []
    ledger.after_read = lambda: subscribers_during_first_read.append(broadcaster.subscriber_count)

    stream = open_stream(ledger, broadcaster, cursor=0)
    try:
        await next_frame(stream)
    finally:
        await stream.aclose()

    assert subscribers_during_first_read == [1]


async def test_a_lost_wakeup_costs_latency_and_never_the_event() -> None:
    """No notification at all: the keepalive tick reads the ledger and finds it anyway."""
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    stream = open_stream(ledger, broadcaster, cursor=0, keepalive=0.01)
    try:
        assert (await next_frame(stream))["comment"] == "keepalive"
        ledger.append(event_type="unannounced.event")
        # Deliberately no publish: this is what a dropped NOTIFY looks like from in here.
        frame = await next_frame(stream)
        while frame["comment"] == "keepalive":
            frame = await next_frame(stream)
    finally:
        await stream.aclose()

    assert frame["event"] == "unannounced.event"
    assert frame["data"]["seq"] == 1


# --------------------------------------------------------------------------------- keepalive


async def test_a_keepalive_is_a_comment_and_moves_no_cursor() -> None:
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    ledger.append()

    stream = open_stream(ledger, broadcaster, cursor=0, keepalive=0.01)
    try:
        event, keepalive = await frames(stream, 2)
    finally:
        await stream.aclose()

    assert event["id"] == "1"
    assert keepalive["comment"] == "keepalive"
    assert keepalive["id"] is None
    assert keepalive["event"] is None
    assert KEEPALIVE_FRAME == b": keepalive\n\n"


async def test_a_keepalive_writes_nothing_to_the_ledger() -> None:
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    stream = open_stream(ledger, broadcaster, cursor=0, keepalive=0.01)
    try:
        await frames(stream, 3)
    finally:
        await stream.aclose()

    assert ledger.records == []


# ------------------------------------------------------------------------------------ resync


async def test_history_past_the_replay_bound_becomes_an_explicit_resync() -> None:
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    for _ in range(10):
        ledger.append()

    stream = open_stream(ledger, broadcaster, cursor=1, max_replay=3)
    try:
        frame = await next_frame(stream)
    finally:
        await stream.aclose()

    assert frame["event"] == RESYNC_EVENT
    assert frame["data"]["reason"] == REPLAY_BOUND_EXCEEDED
    assert frame["data"]["latest_seq"] == 10
    assert frame["data"]["skipped_from_seq"] == 1
    assert frame["id"] == "10"


async def test_a_resync_never_claims_the_skipped_events_were_delivered() -> None:
    """It says where the ledger is; it does not emit the rows it passed over."""
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    for _ in range(10):
        ledger.append()

    stream = open_stream(ledger, broadcaster, cursor=0, max_replay=3)
    try:
        first = await next_frame(stream)
        ledger.append(event_type="after.resync")
        broadcaster.publish()
        second = await next_frame(stream)
    finally:
        await stream.aclose()

    assert first["event"] == RESYNC_EVENT
    # Nothing between 1 and 10 was emitted, and the stream continues from a safe cursor.
    assert second["data"]["seq"] == 11
    assert second["event"] == "after.resync"


async def test_a_subscriber_that_falls_behind_while_connected_is_resynced_not_dropped() -> None:
    """Overflow is a bigger read, then an honest resync -- never a silently discarded event."""
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    stream = open_stream(ledger, broadcaster, cursor=0, max_replay=3)
    try:
        for _ in range(20):
            ledger.append()
        broadcaster.publish()
        frame = await next_frame(stream)
    finally:
        await stream.aclose()

    assert frame["event"] == RESYNC_EVENT
    assert frame["data"]["latest_seq"] == 20


# ---------------------------------------------------------------------------------- fan-out


async def test_one_wakeup_reaches_every_open_stream() -> None:
    """One listener, one signal, every subscriber -- which is why there is no listener each."""
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    ledger.append()
    streams = [open_stream(ledger, broadcaster, cursor=0) for _ in range(3)]
    try:
        # The first frame of each stream is what attaches its subscription.
        for stream in streams:
            assert (await next_frame(stream))["data"]["seq"] == 1
        assert broadcaster.subscriber_count == 3

        ledger.append(event_type="broadcast.event")
        broadcaster.publish()
        for stream in streams:
            assert (await next_frame(stream))["event"] == "broadcast.event"
    finally:
        for stream in streams:
            await stream.aclose()

    assert broadcaster.subscriber_count == 0


async def test_a_wakeup_carries_no_state_at_all() -> None:
    """The in-memory signal cannot be authoritative, because it has nowhere to put a value."""
    parameters = inspect.signature(EventBroadcaster.publish).parameters
    assert list(parameters) == ["self"]


async def test_a_slow_subscriber_accumulates_one_flag_and_not_a_queue() -> None:
    """A thousand notifications while a subscriber is busy cost one boolean, and lose nothing."""
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    stream = open_stream(ledger, broadcaster, cursor=0, max_replay=2000)
    try:
        first = ledger.append()
        broadcaster.publish()
        assert (await next_frame(stream))["data"]["seq"] == first.seq

        for _ in range(1000):
            ledger.append()
            broadcaster.publish()

        assert Subscription.__slots__ == ("_signal",)
        # Coalesced to one wake-up, and every event still arrives, in order.
        delivered = [frame["data"]["seq"] for frame in await frames(stream, 1000)]
    finally:
        await stream.aclose()

    assert delivered == list(range(2, 1002))


async def test_closing_a_stream_releases_its_subscription() -> None:
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    ledger.append()
    stream = open_stream(ledger, broadcaster, cursor=0)
    await next_frame(stream)
    assert broadcaster.subscriber_count == 1

    await stream.aclose()
    assert broadcaster.subscriber_count == 0


# -------------------------------------------------------------------------- the resume cursor


async def test_a_stream_reads_nothing_it_was_not_woken_for() -> None:
    """One read to replay, and no polling: the wake-up is what causes the next one."""
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    ledger.append()
    stream = open_stream(ledger, broadcaster, cursor=0)
    try:
        await next_frame(stream)
        assert ledger.reads == 1
    finally:
        await stream.aclose()


def test_an_absent_cursor_is_a_fresh_subscriber() -> None:
    assert parse_cursor(None) is None
    assert parse_cursor("") is None
    assert parse_cursor("   ") is None


def test_a_well_formed_cursor_is_the_sequence_it_names() -> None:
    assert parse_cursor("0") == 0
    assert parse_cursor(" 641 ") == 641


@pytest.mark.parametrize(
    "value",
    ["abc", "-1", "1.5", "1e3", "٣", "12 34", "9" * 20, str(2**63)],
)
def test_an_unreadable_cursor_is_refused_rather_than_guessed(value: str) -> None:
    """It goes straight into a query bound, and a coerced one would hide the client's bug."""
    with pytest.raises(InvalidCursorError):
        parse_cursor(value)


# ---------------------------------------------------------------------------------- envelope


async def test_a_frame_carries_identifiers_and_no_business_payload() -> None:
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    ledger.append(event_type="fixture.reset")

    stream = open_stream(ledger, broadcaster, cursor=0)
    try:
        frame = await next_frame(stream)
    finally:
        await stream.aclose()

    assert set(frame["data"]) == {"seq", "id", "type", "occurred_at", "case_id", "entity_refs"}
    assert "payload" not in frame["data"]
    assert "correlation_id" not in frame["data"]


async def test_the_event_name_is_the_stored_event_type() -> None:
    """A client routes on this, so it must be the ledger's own word rather than a category."""
    ledger, broadcaster = FakeLedger(), EventBroadcaster()
    ledger.append(event_type="fixture.reset")

    stream = open_stream(ledger, broadcaster, cursor=0)
    try:
        frame = await next_frame(stream)
    finally:
        await stream.aclose()

    assert frame["event"] == "fixture.reset"
    assert frame["data"]["type"] == "fixture.reset"
