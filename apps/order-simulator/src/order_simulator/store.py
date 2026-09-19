"""The order system's own storage: SQLite, its own file, its own transactions.

This is where external truth lives. Nothing in PromisePatch reads it, nothing in PromisePatch
writes it, and the only way anything leaves it is a signed event or an answer to an API call.

Four properties are enforced here rather than by the callers, because a caller that forgot one
would be a caller that silently made the demo untrue.

**A mutation, its version bump and its event are one transaction.** ``BEGIN IMMEDIATE``, then
the line, the order, the event and the delivery row, then ``COMMIT``. A process that dies
anywhere inside that leaves the order exactly as it was; one that dies after it leaves an
event nobody has delivered yet, which the delivery loop finds on the next boot. There is no
arrangement in which the order changed and the news of it was lost.

**``version`` moves only forward, and only when something happened.** A rejected amendment does
not touch it; a replayed one does not touch it again. It is the number PromisePatch mirrors, so
a version that moved without a change -- or a change that did not move it -- would make the two
systems disagree with no way to notice.

**One logical mutation, one event id.** Delivery attempts are rows in ``webhook_deliveries``;
the event they deliver is one row in ``order_events`` with one id. Retrying is therefore
transport, never a second change.

**Idempotency is persisted, not remembered.** ``idempotent_commands`` stores the key, a hash of
the request it belonged to, and the answer that was given. The same key with the same request
replays the stored answer without touching the order; the same key with a *different* request
is a caller bug and is refused, because accepting either would silently discard the other.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

from order_contract import amendments as contract_errors
from order_contract.amendments import AmendmentRequest, AmendmentResult
from order_contract.events import (
    EVENT_ORDER_UPDATED,
    SCHEMA_VERSION,
    ChannelRef,
    CommandRef,
    CustomerRef,
    OrderEvent,
    OrderLineRef,
    OrderSnapshot,
)
from order_simulator import seed

SCHEMA_STATE_ID: Final = 1
STORE_SCHEMA_VERSION: Final = 1
"""This store's own schema version. Not Alembic, and deliberately not pretending to be.

The simulator is a small application that owns a small database. Its schema is created in one
statement set and stamped with a number; if that number ever has to move, the migration is a
function in this module. PromisePatch's migration history is a different system's history and
the two must not be conflated.
"""

DELIVERY_PENDING: Final = "PENDING"
DELIVERY_IN_FLIGHT: Final = "IN_FLIGHT"
DELIVERY_DELIVERED: Final = "DELIVERED"

_SCHEMA: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS schema_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        schema_version INTEGER NOT NULL,
        seed_anchor TEXT NOT NULL,
        seeded_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS catalogue_items (
        external_item_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        alternative_item_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS customers (
        external_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        channel_kind TEXT NOT NULL,
        channel_address TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        external_id TEXT PRIMARY KEY,
        customer_external_id TEXT NOT NULL REFERENCES customers(external_id),
        version INTEGER NOT NULL CHECK (version > 0),
        state TEXT NOT NULL,
        due_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS order_lines (
        external_line_id TEXT PRIMARY KEY,
        external_order_id TEXT NOT NULL REFERENCES orders(external_id) ON DELETE CASCADE,
        external_item_id TEXT NOT NULL REFERENCES catalogue_items(external_item_id),
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        note TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS order_events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        external_order_id TEXT NOT NULL,
        type TEXT NOT NULL,
        previous_version INTEGER,
        version INTEGER NOT NULL,
        occurred_at TEXT NOT NULL,
        source TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS webhook_deliveries (
        event_id TEXT PRIMARY KEY REFERENCES order_events(event_id) ON DELETE CASCADE,
        state TEXT NOT NULL CHECK (state IN ('PENDING', 'IN_FLIGHT', 'DELIVERED')),
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT,
        last_error TEXT,
        delivered_at TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotent_commands (
        idempotency_key TEXT PRIMARY KEY,
        request_hash TEXT NOT NULL,
        external_order_id TEXT NOT NULL,
        resulting_version INTEGER NOT NULL,
        provider_ref TEXT NOT NULL,
        event_id TEXT NOT NULL,
        response TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_order_lines_order ON order_lines(external_order_id)",
    "CREATE INDEX IF NOT EXISTS ix_order_events_order_seq ON order_events(external_order_id, seq)",
    "CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_state ON webhook_deliveries(state)",
)

EVENT_PAGE: Final = 200
"""How many events ``events`` returns when a reader names no window of its own."""

EVENT_PAGE_MAX: Final = 2000
"""The largest window one read may ask for, so a log read stays one bounded answer."""

SOURCE_OPERATOR: Final = "operator"
SOURCE_AMENDMENT: Final = "amendment"
"""Who made a change. Recorded on the event row so the operator screen can say which it was."""


class SimulatorError(Exception):
    """A deterministic refusal, with the code and status the contract names for it."""

    def __init__(
        self, code: str, message: str, *, status: int = 409, current_version: int | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.current_version = current_version


@dataclass(frozen=True, slots=True)
class Mutation:
    """One committed change: the event that records it and the answer the caller gets."""

    event: OrderEvent
    result: AmendmentResult


@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    """One event this process is about to try to deliver."""

    event_id: UUID
    attempts: int
    body: str


@dataclass(frozen=True, slots=True)
class CommittedEvent:
    """One committed event, whole: the published message and where its delivery got to.

    ``body`` is the exact :class:`~order_contract.events.OrderEvent` this system committed and
    hands to a webhook subscriber -- the same bytes, read rather than re-derived. An audit of
    this system asks the same question a subscriber does, and answering it with a summary that
    drops the command that caused the change would make the log unable to say who asked.
    """

    event_id: UUID
    external_order_id: str
    type: str
    previous_version: int | None
    version: int
    occurred_at: datetime
    source: str
    body: str
    state: str
    attempts: int


@dataclass(frozen=True, slots=True)
class DeliveryStatus:
    """What the operator screen shows about an event's journey out of this system."""

    event_id: UUID
    external_order_id: str
    type: str
    version: int
    occurred_at: datetime
    source: str
    state: str
    attempts: int
    last_error: str | None


def request_digest(payload: object) -> str:
    """A stable hash of a request, so a replayed key can be told from a reused one."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(value)


class OrderStore:
    """The external order system's database. One file, one schema, one owner."""

    def __init__(self, path: Path) -> None:
        self.path = path

    # ------------------------------------------------------------------------- connections

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, isolation_level=None, timeout=30.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """One write transaction. ``IMMEDIATE`` so two writers queue rather than collide late."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")

    # ------------------------------------------------------------------------ initialising

    def initialize(self, *, anchor: datetime | None = None, now: datetime | None = None) -> None:
        """Create the schema, seed it if it is empty, and resume interrupted deliveries.

        Idempotent: a restart against a populated database changes no order. What it does change
        is any delivery that was in flight when the process died -- there is no other process
        that could still be attempting it, so it returns to the queue rather than waiting for a
        lease that will never expire.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._write() as connection:
            for statement in _SCHEMA:
                connection.execute(statement)
            state = connection.execute("SELECT schema_version FROM schema_state").fetchone()
            if state is None:
                self._seed(connection, anchor=anchor or seed.SEED_ANCHOR, now=now)
            connection.execute(
                "UPDATE webhook_deliveries SET state = ?, next_attempt_at = NULL WHERE state = ?",
                (DELIVERY_PENDING, DELIVERY_IN_FLIGHT),
            )

    def reset(self, *, anchor: datetime | None = None, now: datetime | None = None) -> None:
        """Put the order book back to its seeded state, keeping nothing.

        The event log goes with it. This system's history is a demo convenience, not a ledger of
        record -- PromisePatch keeps the ledger that must survive, and it keeps it elsewhere.
        """
        with self._write() as connection:
            for statement in _SCHEMA:
                connection.execute(statement)
            for table in (
                "webhook_deliveries",
                "order_events",
                "idempotent_commands",
                "order_lines",
                "orders",
                "customers",
                "catalogue_items",
                "schema_state",
            ):
                connection.execute(f"DELETE FROM {table}")
            connection.execute("DELETE FROM sqlite_sequence WHERE name = 'order_events'")
            self._seed(connection, anchor=anchor or seed.SEED_ANCHOR, now=now)

    def _seed(
        self, connection: sqlite3.Connection, *, anchor: datetime, now: datetime | None
    ) -> None:
        moment = now or datetime.now(UTC)
        connection.execute(
            "INSERT INTO schema_state (id, schema_version, seed_anchor, seeded_at)"
            " VALUES (?, ?, ?, ?)",
            (SCHEMA_STATE_ID, STORE_SCHEMA_VERSION, _iso(anchor), _iso(moment)),
        )
        connection.executemany(
            "INSERT INTO catalogue_items (external_item_id, name, alternative_item_id)"
            " VALUES (?, ?, ?)",
            [
                (item.external_item_id, item.name, item.alternative_item_id)
                for item in seed.CATALOGUE
            ],
        )
        connection.executemany(
            "INSERT INTO customers (external_id, name, channel_kind, channel_address)"
            " VALUES (?, ?, ?, ?)",
            [
                (
                    customer.external_id,
                    customer.name,
                    customer.channel_kind,
                    customer.channel_address,
                )
                for customer in seed.CUSTOMERS
            ],
        )
        for order in seed.ORDERS:
            due_at = anchor + timedelta(minutes=order.due_offset_minutes)
            connection.execute(
                "INSERT INTO orders"
                " (external_id, customer_external_id, version, state, due_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    order.external_id,
                    order.customer_external_id,
                    seed.INITIAL_VERSION,
                    seed.ORDER_STATE_ACCEPTED,
                    _iso(due_at),
                    _iso(moment),
                ),
            )
            connection.execute(
                "INSERT INTO order_lines"
                " (external_line_id, external_order_id, external_item_id, quantity, note)"
                " VALUES (?, ?, ?, ?, '')",
                (
                    order.line.external_line_id,
                    order.external_id,
                    order.line.external_item_id,
                    order.line.quantity,
                ),
            )

    def seed_anchor(self) -> datetime:
        with self._connect() as connection:
            row = connection.execute("SELECT seed_anchor FROM schema_state").fetchone()
        if row is None:
            raise SimulatorError("NOT_SEEDED", "the order system has no seeded state", status=503)
        return _moment(row["seed_anchor"])

    def is_ready(self) -> bool:
        """Whether this system can answer for its orders: schema present, seed loaded."""
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT schema_version FROM schema_state WHERE id = ?", (SCHEMA_STATE_ID,)
                ).fetchone()
                if row is None or row["schema_version"] != STORE_SCHEMA_VERSION:
                    return False
                count = connection.execute("SELECT COUNT(*) AS n FROM orders").fetchone()
        except sqlite3.Error:
            return False
        return bool(count["n"])

    # ----------------------------------------------------------------------------- reading

    def read_order(self, external_id: str) -> OrderSnapshot:
        with self._connect() as connection:
            return self._snapshot(connection, external_id)

    def list_orders(self) -> tuple[OrderSnapshot, ...]:
        with self._connect() as connection:
            ids = [
                row["external_id"]
                for row in connection.execute("SELECT external_id FROM orders ORDER BY external_id")
            ]
            return tuple(self._snapshot(connection, external_id) for external_id in ids)

    def catalogue(self) -> tuple[seed.CatalogueItem, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT external_item_id, name, alternative_item_id FROM catalogue_items"
                " ORDER BY external_item_id"
            ).fetchall()
        return tuple(
            seed.CatalogueItem(row["external_item_id"], row["name"], row["alternative_item_id"])
            for row in rows
        )

    def latest_deliveries(self, limit: int = 20) -> tuple[DeliveryStatus, ...]:
        """The most recent events and where each one got to. The operator screen's evidence."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT e.event_id, e.external_order_id, e.type, e.version, e.occurred_at,"
                " e.source, d.state, d.attempts, d.last_error"
                " FROM order_events e JOIN webhook_deliveries d ON d.event_id = e.event_id"
                " ORDER BY e.seq DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(
            DeliveryStatus(
                event_id=UUID(row["event_id"]),
                external_order_id=row["external_order_id"],
                type=row["type"],
                version=row["version"],
                occurred_at=_moment(row["occurred_at"]),
                source=row["source"],
                state=row["state"],
                attempts=row["attempts"],
                last_error=row["last_error"],
            )
            for row in rows
        )

    def events(
        self, *, since: datetime | None = None, limit: int = EVENT_PAGE
    ) -> tuple[tuple[CommittedEvent, ...], bool]:
        """The committed event log, oldest first, with whether the window was cut short.

        Chronological rather than newest-first, because this is the log and not the operator
        screen: a reader following the system forwards from an instant wants the next events in
        the order they happened.

        ``limit`` is a window and never a silent one. The second half of the answer says whether
        more events matched than were returned, so a reader that stopped early knows it did --
        a truncated log that looked complete would let an audit conclude something never
        happened when it simply was not fetched.
        """
        window = max(1, min(int(limit), EVENT_PAGE_MAX))
        clause = "" if since is None else " WHERE e.occurred_at >= ?"
        parameters: tuple[Any, ...] = () if since is None else (_iso(since),)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT e.event_id, e.external_order_id, e.type, e.previous_version, e.version,"
                " e.occurred_at, e.source, e.payload, d.state, d.attempts"
                " FROM order_events e JOIN webhook_deliveries d ON d.event_id = e.event_id"
                f"{clause} ORDER BY e.seq LIMIT ?",
                (*parameters, window + 1),
            ).fetchall()
        truncated = len(rows) > window
        return (
            tuple(
                CommittedEvent(
                    event_id=UUID(row["event_id"]),
                    external_order_id=row["external_order_id"],
                    type=row["type"],
                    previous_version=row["previous_version"],
                    version=row["version"],
                    occurred_at=_moment(row["occurred_at"]),
                    source=row["source"],
                    body=str(row["payload"]),
                    state=row["state"],
                    attempts=row["attempts"],
                )
                for row in rows[:window]
            ),
            truncated,
        )

    def event_body(self, event_id: UUID) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM order_events WHERE event_id = ?", (str(event_id),)
            ).fetchone()
        if row is None:
            raise SimulatorError("EVENT_NOT_FOUND", f"no event {event_id}", status=404)
        return str(row["payload"])

    def _snapshot(self, connection: sqlite3.Connection, external_id: str) -> OrderSnapshot:
        order = connection.execute(
            "SELECT o.external_id, o.version, o.state, o.due_at,"
            " c.external_id AS customer_id, c.name, c.channel_kind, c.channel_address"
            " FROM orders o JOIN customers c ON c.external_id = o.customer_external_id"
            " WHERE o.external_id = ?",
            (external_id,),
        ).fetchone()
        if order is None:
            raise SimulatorError(
                contract_errors.ERROR_ORDER_NOT_FOUND,
                f"no order {external_id}",
                status=404,
            )
        lines = connection.execute(
            "SELECT external_line_id, external_item_id, quantity, note FROM order_lines"
            " WHERE external_order_id = ? ORDER BY external_line_id",
            (external_id,),
        ).fetchall()
        return OrderSnapshot(
            external_id=order["external_id"],
            version=order["version"],
            state=order["state"],
            customer=CustomerRef(
                external_id=order["customer_id"],
                name=order["name"],
                approval_channel=ChannelRef(
                    kind=order["channel_kind"], address=order["channel_address"]
                ),
            ),
            due_at=_moment(order["due_at"]),
            lines=tuple(
                OrderLineRef(
                    external_line_id=line["external_line_id"],
                    external_item_id=line["external_item_id"],
                    quantity=line["quantity"],
                    note=line["note"],
                )
                for line in lines
            ),
        )

    # ---------------------------------------------------------------------------- mutating

    def operator_change(
        self,
        *,
        external_order_id: str,
        external_line_id: str,
        to_item_id: str,
        quantity: int | None = None,
        now: datetime | None = None,
    ) -> Mutation:
        """An operator edits an order in this system's own screen. No expected version.

        A person looking at the current state is the authority for their own edit; optimistic
        concurrency is what an *integration* needs, because a program planned against a version
        it may no longer be looking at.

        ``quantity`` is the operator screen's own capability and is deliberately absent from
        the amendment contract: a governed recovery amendment re-points a line to another
        authored version and never changes how many of a thing a customer bought. A customer
        who wants two cakes instead of one says so to their own order system, and this is that
        edit. ``None`` leaves the quantity exactly where it is.
        """
        if quantity is not None and quantity <= 0:
            raise ValueError("an order line quantity is a positive whole number")
        moment = now or datetime.now(UTC)
        with self._write() as connection:
            return self._apply(
                connection,
                external_order_id=external_order_id,
                external_line_id=external_line_id,
                to_item_id=to_item_id,
                from_item_id=None,
                expected_version=None,
                note="",
                source=SOURCE_OPERATOR,
                command=None,
                now=moment,
                quantity=quantity,
            )

    def amend(
        self, request: AmendmentRequest, *, idempotency_key: str, now: datetime | None = None
    ) -> Mutation:
        """Apply a governed recovery amendment, exactly once per idempotency key.

        The key is looked up inside the same transaction that would perform the change, so two
        concurrent deliveries of one amendment cannot both find it absent.
        """
        if request.schema_version != SCHEMA_VERSION:
            raise SimulatorError(
                contract_errors.ERROR_SCHEMA_VERSION,
                f"this order system speaks schema version {SCHEMA_VERSION}",
                status=400,
            )
        moment = now or datetime.now(UTC)
        digest = request_digest(request.model_dump(mode="json"))

        with self._write() as connection:
            replayed = self._replay(connection, idempotency_key, digest)
            if replayed is not None:
                return replayed

            provider_ref = f"amd-{uuid4().hex[:12]}"
            mutation = self._apply(
                connection,
                external_order_id=request.external_order_id,
                external_line_id=request.external_line_id,
                to_item_id=request.to_item_id,
                from_item_id=request.from_item_id,
                expected_version=request.expected_version,
                note=request.note,
                source=SOURCE_AMENDMENT,
                command=CommandRef(idempotency_key=idempotency_key, provider_ref=provider_ref),
                now=moment,
                provider_ref=provider_ref,
            )
            connection.execute(
                "INSERT INTO idempotent_commands (idempotency_key, request_hash,"
                " external_order_id, resulting_version, provider_ref, event_id, response,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    idempotency_key,
                    digest,
                    request.external_order_id,
                    mutation.result.external_version,
                    provider_ref,
                    str(mutation.event.event_id),
                    mutation.result.model_dump_json(),
                    _iso(moment),
                ),
            )
            return mutation

    def _replay(
        self, connection: sqlite3.Connection, idempotency_key: str, digest: str
    ) -> Mutation | None:
        """The stored answer for a key, or ``None`` when this key has never been used.

        A key presented with a different request is refused rather than served: two different
        amendments claiming one identity means the caller's key derivation is wrong, and
        answering either of them would quietly discard the other.
        """
        row = connection.execute(
            "SELECT request_hash, response, event_id FROM idempotent_commands"
            " WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != digest:
            raise SimulatorError(
                contract_errors.ERROR_IDEMPOTENCY_CONFLICT,
                f"idempotency key {idempotency_key!r} was used for a different amendment",
            )
        payload = connection.execute(
            "SELECT payload FROM order_events WHERE event_id = ?", (row["event_id"],)
        ).fetchone()
        result = AmendmentResult.model_validate_json(row["response"])
        return Mutation(
            event=OrderEvent.model_validate_json(payload["payload"]),
            result=result.model_copy(update={"replayed": True}),
        )

    def _apply(
        self,
        connection: sqlite3.Connection,
        *,
        external_order_id: str,
        external_line_id: str,
        to_item_id: str,
        from_item_id: str | None,
        expected_version: int | None,
        note: str,
        source: str,
        command: CommandRef | None,
        now: datetime,
        provider_ref: str | None = None,
        quantity: int | None = None,
    ) -> Mutation:
        """Re-point one line, move the version, and record the event. One transaction.

        Every refusal below happens before anything is written, so a rejected request leaves
        this system byte-for-byte as it was -- which is what makes "an old amendment cannot
        overwrite newer truth" a property rather than a hope.
        """
        order = connection.execute(
            "SELECT version, state FROM orders WHERE external_id = ?", (external_order_id,)
        ).fetchone()
        if order is None:
            raise SimulatorError(
                contract_errors.ERROR_ORDER_NOT_FOUND,
                f"no order {external_order_id}",
                status=404,
            )
        if order["state"] not in seed.OPEN_STATES:
            raise SimulatorError(
                contract_errors.ERROR_ORDER_NOT_OPEN,
                f"order {external_order_id} is {order['state']} and cannot be amended",
                current_version=order["version"],
            )
        if expected_version is not None and expected_version != order["version"]:
            raise SimulatorError(
                contract_errors.ERROR_VERSION_CONFLICT,
                f"order {external_order_id} is at version {order['version']}, "
                f"not the version {expected_version} this amendment was planned against",
                current_version=order["version"],
            )

        line = connection.execute(
            "SELECT external_item_id FROM order_lines"
            " WHERE external_line_id = ? AND external_order_id = ?",
            (external_line_id, external_order_id),
        ).fetchone()
        if line is None:
            raise SimulatorError(
                contract_errors.ERROR_LINE_NOT_FOUND,
                f"order {external_order_id} has no line {external_line_id}",
                status=404,
                current_version=order["version"],
            )
        if from_item_id is not None and line["external_item_id"] != from_item_id:
            raise SimulatorError(
                contract_errors.ERROR_LINE_MOVED,
                f"line {external_line_id} carries {line['external_item_id']}, "
                f"not the {from_item_id} this amendment was planned against",
                current_version=order["version"],
            )
        known = connection.execute(
            "SELECT 1 FROM catalogue_items WHERE external_item_id = ?", (to_item_id,)
        ).fetchone()
        if known is None:
            raise SimulatorError(
                contract_errors.ERROR_UNKNOWN_ITEM,
                f"{to_item_id!r} is not in this order system's catalogue",
                status=400,
                current_version=order["version"],
            )

        previous_version = int(order["version"])
        version = previous_version + 1
        connection.execute(
            "UPDATE order_lines SET external_item_id = ?, note = ? WHERE external_line_id = ?",
            (to_item_id, note or "", external_line_id),
        )
        if quantity is not None:
            connection.execute(
                "UPDATE order_lines SET quantity = ? WHERE external_line_id = ?",
                (quantity, external_line_id),
            )
        connection.execute(
            "UPDATE orders SET version = ?, state = ?, updated_at = ? WHERE external_id = ?",
            (version, seed.ORDER_STATE_AMENDED, _iso(now), external_order_id),
        )

        event = OrderEvent(
            event_id=uuid4(),
            type=EVENT_ORDER_UPDATED,
            occurred_at=now,
            previous_version=previous_version,
            changed_line_ids=(external_line_id,),
            order=self._snapshot(connection, external_order_id),
            command=command,
        )
        body = event.model_dump_json()
        connection.execute(
            "INSERT INTO order_events (event_id, external_order_id, type, previous_version,"
            " version, occurred_at, source, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(event.event_id),
                external_order_id,
                event.type,
                previous_version,
                version,
                _iso(now),
                source,
                body,
            ),
        )
        connection.execute(
            "INSERT INTO webhook_deliveries (event_id, state, attempts, next_attempt_at,"
            " created_at) VALUES (?, ?, 0, NULL, ?)",
            (str(event.event_id), DELIVERY_PENDING, _iso(now)),
        )

        return Mutation(
            event=event,
            result=AmendmentResult(
                external_order_id=external_order_id,
                external_line_id=external_line_id,
                previous_version=previous_version,
                external_version=version,
                item_id=to_item_id,
                state=seed.ORDER_STATE_AMENDED,
                provider_ref=provider_ref or f"opr-{event.event_id.hex[:12]}",
                event_id=event.event_id,
            ),
        )

    # ---------------------------------------------------------------------------- delivery

    def claim_delivery(self, *, now: datetime, lease: timedelta) -> DeliveryClaim | None:
        """Take the oldest event that is due to be delivered, and record that we took it.

        The claim commits before anything is sent, so a process that dies mid-send leaves a row
        that says an attempt was made rather than one that looks untouched.
        """
        with self._write() as connection:
            row = connection.execute(
                "SELECT d.event_id, d.attempts, e.payload FROM webhook_deliveries d"
                " JOIN order_events e ON e.event_id = d.event_id"
                " WHERE (d.state = ? AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= ?))"
                "    OR (d.state = ? AND d.next_attempt_at IS NOT NULL AND d.next_attempt_at <= ?)"
                " ORDER BY e.seq LIMIT 1",
                (DELIVERY_PENDING, _iso(now), DELIVERY_IN_FLIGHT, _iso(now)),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE webhook_deliveries SET state = ?, attempts = attempts + 1,"
                " next_attempt_at = ? WHERE event_id = ?",
                (DELIVERY_IN_FLIGHT, _iso(now + lease), row["event_id"]),
            )
            return DeliveryClaim(
                event_id=UUID(row["event_id"]),
                attempts=int(row["attempts"]) + 1,
                body=str(row["payload"]),
            )

    def record_delivered(self, event_id: UUID, *, now: datetime) -> None:
        with self._write() as connection:
            connection.execute(
                "UPDATE webhook_deliveries SET state = ?, next_attempt_at = NULL,"
                " last_error = NULL, delivered_at = ? WHERE event_id = ?",
                (DELIVERY_DELIVERED, _iso(now), str(event_id)),
            )

    def record_delivery_failure(self, event_id: UUID, *, error: str, retry_at: datetime) -> None:
        """Back to the queue with a time on it. The event is untouched; only the attempt failed."""
        with self._write() as connection:
            connection.execute(
                "UPDATE webhook_deliveries SET state = ?, next_attempt_at = ?, last_error = ?"
                " WHERE event_id = ?",
                (DELIVERY_PENDING, _iso(retry_at), error[:500], str(event_id)),
            )

    def undelivered_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM webhook_deliveries WHERE state <> ?",
                (DELIVERY_DELIVERED,),
            ).fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------------- diagnostics

    def event_count(self, external_order_id: str | None = None) -> int:
        """How many logical mutations this system has recorded. Transport attempts are not one."""
        with self._connect() as connection:
            if external_order_id is None:
                row = connection.execute("SELECT COUNT(*) AS n FROM order_events").fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM order_events WHERE external_order_id = ?",
                    (external_order_id,),
                ).fetchone()
        return int(row["n"])

    def commands(self) -> Sequence[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT idempotency_key, external_order_id, resulting_version, provider_ref"
                " FROM idempotent_commands ORDER BY created_at, idempotency_key"
            ).fetchall()
        return [dict(row) for row in rows]
