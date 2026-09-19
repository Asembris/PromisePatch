"""The four receivers, read from their own records and from nothing an arm holds.

The contract's central scoring decision is that everything scored is receiver-side. These four
readers are where that becomes a property of the harness rather than a claim about it: each one
opens the record of the system that received the effect, reads it, and can say nothing at all
about which arm was driving.

| receiver | what it is | read here from |
|---|---|---|
| ``E1`` | the external order system | the simulator's committed event log, and ``GET /orders`` |
| ``E2`` | the customer channel | the outbound delivery record and the accepted-reply record |
| ``E3`` | the kitchen | the ``production_tasks`` rows, sampled twice |
| ``E4`` | the worker report | the single report the arm handed over, collected by the world |

**A read is never a write.** Nothing in this module inserts, updates or deletes anything, in any
store. That is what makes it legitimate for fixture observation while arm actions stay on the
ordinary product surfaces: an arm cannot reach these objects at all -- an
:class:`~scripts.sur1.arms.AttemptRequest` carries a world and a budget and no reader -- and
these objects cannot change what they observe.

**One disclosed discrepancy about E1, and it is the contract's own.** The contract names
``GET /orders`` and ``GET /admin/events`` as E1's read path and lists
``event.command.idempotency_key`` among the fields it uses. The simulator's ``/admin/events``
projection publishes the event's id, order, type, version, instant and source -- and not the
command key, not the previous version and not the line's item. Rule ``B2`` attributes an
amendment to an arm *by the idempotency key on the order system's own event*, so the named
endpoint cannot support the rule that depends on it. This reader therefore reads the same events
out of the order system's **own committed record**, where the whole event body including its
command lives, and uses the HTTP endpoints for reachability and for the current snapshot. The
source is still E1's own record; only the route to it is the one that actually carries the
fields. The frozen document is **not** edited: it is a published hash, and a name is not worth
moving one over. This is recorded in the execution predeclaration beside the other one.

**Nothing here has been pointed at a ``SUR-1`` scenario.**
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from scripts.sur1.bindings import REAL, Probe
from scripts.sur1.evidence import (
    AMENDMENT_EVENTS,
    INBOUND,
    OUTBOUND,
    ChannelMessage,
    OrderEvent,
    TaskSample,
)

AMENDMENT_SOURCE: Final = "amendment"
"""The order system's own word for a change somebody asked it to make through the contract.

The other value it writes is ``operator``, which is a person editing the order book directly.
Rule ``B6`` says an external change is that customer's own command and never an arm's effect, so
an operator row is read and carried, and is not attributed to anybody's attempt.
"""

ORDER_AMENDED: Final = "ORDER_AMENDED"
"""What an amendment is called in :data:`~scripts.sur1.evidence.AMENDMENT_EVENTS`.

The order system calls the same thing ``order.updated`` with an ``amendment`` source, because
its vocabulary is about orders and the benchmark's is about effects. The translation happens
once, here, and is asserted in a test rather than remembered.
"""

MESSAGE_SEND: Final = "MESSAGE_SEND"
"""The outbox kind that is an outbound customer message. Read, never written."""


class ReceiverUnreadableError(RuntimeError):
    """A declared evidence source could not be read at all.

    Deliberately distinct from an empty source. An empty receiver is a reading and may be a
    zero; an unreadable one is not, and the driver carries it through as an unreadable source,
    which the scorer turns into ``VOID``.
    """

    def __init__(self, source: str, detail: str) -> None:
        super().__init__(f"{source}: {detail}")
        self.source = source
        self.detail = detail


def _moment(raw: object) -> datetime:
    """A receiver's own timestamp, as an aware instant.

    Receivers store ISO-8601. A naive one is a receiver that did not record a zone rather than
    an instant in this machine's zone, and reading it as local time would silently reorder the
    sequence the whole consent question turns on -- so it is read as UTC and the reading is the
    same on every machine.
    """
    from datetime import UTC

    if isinstance(raw, datetime):
        stamp = raw
    else:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=UTC)


# ------------------------------------------------------------------------------ E1, the orders


@dataclass(slots=True)
class OrderSystemReceiver:
    """``E1``: what the external order system committed, in its own record.

    ``base_url`` is the contract's named HTTP surface and is what :meth:`probe` asks, because
    reachability of the service is the fact the preflight needs. ``store_path`` is the order
    system's own committed event log, which is where the fields rule ``B2`` depends on actually
    live.
    """

    base_url: str
    store_path: Path | None = None
    binding_kind: str = REAL

    def identity(self) -> Mapping[str, Any]:
        return {
            "receiver": "E1",
            "base_url": self.base_url,
            "store": None if self.store_path is None else str(self.store_path),
        }

    def probe(self) -> Probe:
        """Ask the order system whether it is ready, and check the record is readable.

        Two questions because there are two facts: a service that answers with no readable event
        log cannot support attribution, and a readable log belonging to a service that is down
        is a stale file.
        """
        import httpx2

        try:
            answer = httpx2.get(f"{self.base_url}/readyz", timeout=5.0)
        except Exception as failure:
            return Probe("E1", False, f"{type(failure).__name__}: {failure}")
        if answer.status_code != 200:
            return Probe("E1", False, f"/readyz answered {answer.status_code}")
        if self.store_path is None:
            return Probe("E1", False, "no order-system event log is configured; see B2")
        if not self.store_path.is_file():
            return Probe("E1", False, f"{self.store_path} is not a file")
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1 FROM order_events LIMIT 1").fetchone()
        except sqlite3.Error as failure:
            return Probe("E1", False, f"the event log did not read: {failure}")
        return Probe("E1", True, self.base_url)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A read-only connection to the order system's record. It cannot write if it tried."""
        if self.store_path is None:
            raise ReceiverUnreadableError("E1", "no order-system event log is configured")
        uri = f"file:{self.store_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def read(self, *, since: datetime) -> tuple[OrderEvent, ...]:
        """Every order event the system committed at or after this instant, in its own order.

        ``since`` is the attempt's own start. Everything before it was the fixture or somebody
        else's command -- a pre-incident external re-pin is exactly that -- and rule ``B6`` says
        an arm owns neither.
        """
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT event_id, external_order_id, type, previous_version, version,"
                    " occurred_at, source, payload FROM order_events ORDER BY seq"
                ).fetchall()
        except sqlite3.Error as failure:
            raise ReceiverUnreadableError("E1", str(failure)) from failure

        events: list[OrderEvent] = []
        for row in rows:
            occurred_at = _moment(row["occurred_at"])
            if occurred_at < since:
                continue
            events.append(self._event(row, occurred_at))
        return tuple(events)

    def _event(self, row: Mapping[str, Any], occurred_at: datetime) -> OrderEvent:
        """One committed row, as the benchmark's own vocabulary.

        The body is read for the two things the projection does not carry: the command that
        caused the change, and the item the changed line now holds. A body that carries neither
        is an event about something other than an amendment, and reads as one.
        """
        body: Mapping[str, Any] = json.loads(str(row["payload"]))
        command = body.get("command") or {}
        changed = tuple(str(line) for line in body.get("changed_line_ids") or ())
        item: str | None = None
        for line in (body.get("order") or {}).get("lines") or ():
            if not changed or str(line.get("external_line_id")) in changed:
                item = str(line.get("external_item_id"))
                break
        source = str(row["source"])
        return OrderEvent(
            external_id=str(row["external_order_id"]),
            event_type=ORDER_AMENDED if source == AMENDMENT_SOURCE else str(row["type"]),
            event_source=source,
            idempotency_key=str(command.get("idempotency_key", "")),
            occurred_at=occurred_at,
            version=int(row["version"]),
            previous_version=(
                None if row["previous_version"] is None else int(row["previous_version"])
            ),
            line_external_item_id=item,
        )

    def snapshot(self) -> Mapping[str, Any]:
        """``GET /orders``: the current state of every order, for an arm's own read."""
        import httpx2

        try:
            answer = httpx2.get(f"{self.base_url}/orders", timeout=10.0)
            answer.raise_for_status()
        except Exception as failure:
            raise ReceiverUnreadableError("E1", f"{type(failure).__name__}: {failure}") from failure
        body: Mapping[str, Any] = answer.json()
        return body


# ------------------------------------------------------------------- E2 and E3, the database


@dataclass(slots=True)
class DatabaseReader:
    """One read-only query at a time, for the two receivers whose records are rows.

    Over ``asyncpg``, which is the driver this repository already ships and the one the
    application's own listener uses. Synchronous on the outside because the harness is: each
    query runs on its own event loop, which is what a receiver read wants -- it is one statement,
    it holds nothing, and a connection that outlived it would be a connection sitting
    ``idle in transaction`` beside a suite that truncates.

    The URL is normalised rather than assumed: the application configures ``postgresql+asyncpg``
    and the driver wants the scheme without the suffix. That is a spelling, not a database.
    """

    url: str

    def dsn(self) -> str:
        scheme, separator, rest = self.url.partition("://")
        return f"{scheme.split('+')[0]}{separator}{rest}"

    def rows(self, source: str, statement: str) -> list[tuple[Any, ...]]:
        """One statement's rows, or a declared unreadable source.

        Every failure -- a driver that is not installed, a database that refuses, a table that
        does not exist -- becomes :class:`ReceiverUnreadableError`, because from the benchmark's
        point of view they are one fact: this evidence source could not be read. An unreadable
        source is never an empty one and is never a zero on a safety ceiling.
        """
        try:
            return asyncio.run(self._rows(statement))
        except ReceiverUnreadableError:
            raise
        except Exception as failure:
            raise ReceiverUnreadableError(
                source, f"{type(failure).__name__}: {failure}"
            ) from failure

    async def _rows(self, statement: str) -> list[tuple[Any, ...]]:
        import asyncpg

        connection = await asyncpg.connect(dsn=self.dsn(), timeout=5)
        try:
            records = await connection.fetch(statement)
        finally:
            await connection.close()
        return [tuple(record) for record in records]


@dataclass(slots=True)
class ChannelReceiver:
    """``E2``: what a customer was sent, and what they actually said.

    Two directions from two records. Outbound is the outbound transport's delivery record -- the
    outbox row for a customer message, read only once the transport has accepted it, because a
    message nobody accepted did not leave. Inbound is the accepted-reply record.

    ``ledger`` is the harness's own channel, which is where an arm that is not PromisePatch
    sends and where a stipulated customer reply that is not carried on a signed link arrives.
    It is a second *transport*, never a second protocol: nothing in it is read as a decision,
    and the scorer decides ``literal_decision`` structurally on the text either way.
    """

    database: DatabaseReader
    ledger: ChannelLedger
    binding_kind: str = REAL

    def identity(self) -> Mapping[str, Any]:
        return {"receiver": "E2", "records": ["outbox_messages", "inbound_replies", "ledger"]}

    def probe(self) -> Probe:
        try:
            self.database.rows("E2", "SELECT 1 FROM outbox_messages LIMIT 1")
            self.database.rows("E2", "SELECT 1 FROM inbound_replies LIMIT 1")
        except ReceiverUnreadableError as failure:
            return Probe("E2", False, failure.detail)
        return Probe("E2", True, "outbox_messages and inbound_replies read")

    def read(self, *, since: datetime) -> tuple[ChannelMessage, ...]:
        messages = [
            *self._outbound(since=since),
            *self._inbound(since=since),
            *self.ledger.since(since),
        ]
        return tuple(sorted(messages, key=lambda message: (message.accepted_at, message.text)))

    def _outbound(self, *, since: datetime) -> list[ChannelMessage]:
        rows = self.database.rows(
            "E2",
            "SELECT payload, provider_ref, delivered_at FROM outbox_messages"
            f" WHERE kind = '{MESSAGE_SEND}' AND delivered_at IS NOT NULL",
        )
        found = []
        for payload, provider_ref, delivered_at in rows:
            accepted_at = _moment(delivered_at)
            if accepted_at < since:
                continue
            body: Mapping[str, Any] = (
                payload if isinstance(payload, Mapping) else json.loads(payload)
            )
            found.append(
                ChannelMessage(
                    channel_address=str(body.get("channel_address", "")),
                    direction=OUTBOUND,
                    text=str(body.get("text", "")),
                    accepted_at=accepted_at,
                    provider_event_id=None if provider_ref is None else str(provider_ref),
                )
            )
        return found

    def _inbound(self, *, since: datetime) -> list[ChannelMessage]:
        rows = self.database.rows(
            "E2",
            "SELECT sender_identity, raw_text, received_at, provider_message_id"
            " FROM inbound_replies",
        )
        found = []
        for sender, text, received_at, provider_message_id in rows:
            accepted_at = _moment(received_at)
            if accepted_at < since:
                continue
            found.append(
                ChannelMessage(
                    channel_address=str(sender),
                    direction=INBOUND,
                    text=str(text),
                    accepted_at=accepted_at,
                    provider_event_id=str(provider_message_id),
                )
            )
        return found


@dataclass(slots=True)
class ChannelLedger:
    """The harness's own transport, for the messages PromisePatch's outbox never holds.

    Arm A is not PromisePatch and has no outbox; its ``send_customer_message`` has to be
    accepted by something, and this is it. A stipulated inbound reply that no signed link
    carries arrives here too.

    It records and never interprets. Nothing in this class reads a text, and the direction is a
    field the caller states rather than a thing inferred.
    """

    messages: list[ChannelMessage] = field(default_factory=list)

    def accept(self, message: ChannelMessage) -> ChannelMessage:
        self.messages.append(message)
        return message

    def since(self, moment: datetime) -> list[ChannelMessage]:
        return [message for message in self.messages if message.accepted_at >= moment]

    def clear(self) -> None:
        """Between scenarios. A ledger that carried a previous scenario's messages would be
        evidence about an attempt that is not this one."""
        self.messages.clear()


@dataclass(slots=True)
class KitchenReceiver:
    """``E3``: each production task's state, sampled at the incident and at the report.

    Two samples rather than a log, because that is what the contract asks for and what the rows
    can honestly give: ``production_tasks`` holds a current state, and the difference between
    the two readings is what ``task_hold`` and ``task_release`` mean.

    ``held_by_case_id`` is how a hold is attributed. A task held by a case this attempt opened
    was held by this attempt; a task held by anything else was not, and saying so is the whole
    of the attribution rule for E3.
    """

    database: DatabaseReader
    binding_kind: str = REAL

    def identity(self) -> Mapping[str, Any]:
        return {"receiver": "E3", "records": ["production_tasks"]}

    def probe(self) -> Probe:
        try:
            self.database.rows("E3", "SELECT 1 FROM production_tasks LIMIT 1")
        except ReceiverUnreadableError as failure:
            return Probe("E3", False, failure.detail)
        return Probe("E3", True, "production_tasks read")

    def sample(self) -> dict[str, tuple[str, str | None]]:
        """One reading: every task's state and holder, by task id."""
        rows = self.database.rows(
            "E3",
            "SELECT t.id, t.state, t.held_by_case_id, l.order_id FROM production_tasks t"
            " JOIN order_lines l ON l.id = t.order_line_id",
        )
        return {
            str(task): (str(state), None if held is None else str(held))
            for task, state, held, _ in rows
        }

    def orders(self) -> dict[str, str]:
        """Which order each task belongs to. Read once and used to place every sample."""
        rows = self.database.rows(
            "E3",
            "SELECT t.id, l.order_id FROM production_tasks t"
            " JOIN order_lines l ON l.id = t.order_line_id",
        )
        return {str(task): str(order) for task, order in rows}

    def compare(
        self,
        *,
        at_incident: Mapping[str, tuple[str, str | None]],
        at_report: Mapping[str, tuple[str, str | None]],
        orders: Mapping[str, str],
        case_ids: Sequence[str],
    ) -> tuple[TaskSample, ...]:
        """The two readings as the evidence rows the projection places.

        A task that appeared or disappeared between the samples is not given a made-up state:
        both readings are required, and a task with only one is left out of the comparison and
        reported by its absence, which the projection refuses as a partial sample.
        """
        mine = {str(case) for case in case_ids}
        samples = []
        for task, (state_at_incident, held_at_incident) in sorted(at_incident.items()):
            if task not in at_report:
                continue
            state_at_report, held_at_report = at_report[task]
            samples.append(
                TaskSample(
                    task_id=task,
                    order=str(orders.get(task, "")),
                    state_at_incident=state_at_incident,
                    state_at_report=state_at_report,
                    held_by=held_at_report,
                    held_by_this_attempt=(
                        held_at_report is not None
                        and held_at_report in mine
                        and held_at_incident != held_at_report
                    ),
                    released_by_this_attempt=(
                        held_at_incident is not None
                        and held_at_incident in mine
                        and held_at_report is None
                    ),
                )
            )
        return tuple(samples)


__all__ = [
    "AMENDMENT_EVENTS",
    "AMENDMENT_SOURCE",
    "MESSAGE_SEND",
    "ORDER_AMENDED",
    "ChannelLedger",
    "ChannelReceiver",
    "DatabaseReader",
    "KitchenReceiver",
    "OrderSystemReceiver",
    "ReceiverUnreadableError",
]
