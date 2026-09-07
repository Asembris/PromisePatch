"""The process's one subscription: what it does when the connection under it fails.

Reconnection, backoff, heartbeat and shutdown are driven through a stand-in connection rather
than by breaking a real one, because "the pooler dropped us" is not a condition a test can
provoke on demand -- and a test that waited around hoping for one would be slow when it worked
and silent when it did not. The stand-in can be terminated at an exact instant, so each of
these properties is asserted rather than sampled.

One test at the end uses the real database, and it is the one thing the stand-in cannot
establish: that a notification actually crosses the session pooler this deployment connects
through, to the least-privileged role the API actually authenticates as.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from _database_safety import migration_database_url
from sqlalchemy.ext.asyncio import AsyncEngine

from promisepatch.config import Settings
from promisepatch.db import build_engine
from promisepatch.db.boundary import EVENT_CHANNEL, RUNTIME_ROLE
from promisepatch.db.listen import DomainEventListener, ListenerConnection, asyncpg_dsn
from promisepatch.db.runtime import RuntimeRoleError
from promisepatch.db.uow import Actor
from promisepatch.fixtures import demo
from promisepatch.fixtures.reset import reset_demo_state

PATIENCE = 5.0
"""Failure bound for something that should happen at once. Nothing here passes by waiting."""

QUICK = 0.01
"""Backoff and heartbeat for tests, so the supervisor's own timing is never what is asserted."""


class FakeConnection:
    """A driver connection with the four operations the supervisor performs, and a kill switch."""

    def __init__(self) -> None:
        self.listeners: dict[str, list[Any]] = {}
        self.terminations: list[Any] = []
        self.queries: list[str] = []
        self.closed = False
        self.subscribe_error: Exception | None = None
        self.execute_error: Exception | None = None

    async def add_listener(self, channel: str, callback: Any) -> None:
        if self.subscribe_error is not None:
            raise self.subscribe_error
        self.listeners.setdefault(channel, []).append(callback)

    def add_termination_listener(self, callback: Any) -> None:
        self.terminations.append(callback)

    async def execute(self, query: str, *args: Any) -> Any:
        self.queries.append(query)
        if self.execute_error is not None:
            raise self.execute_error
        return "SELECT 1"

    async def close(self) -> None:
        self.closed = True

    def notify(self, payload: str, *, channel: str = EVENT_CHANNEL) -> None:
        for callback in self.listeners.get(channel, ()):
            callback(self, 4242, channel, payload)

    def terminate(self) -> None:
        """What the driver does to us when the server goes away underneath the socket."""
        for callback in tuple(self.terminations):
            callback(self)


class FakeDriver:
    """Hands out connections, refusing the first ``failures`` attempts."""

    def __init__(self, *, failures: int = 0) -> None:
        self.connections: list[FakeConnection] = []
        self.attempts = 0
        self.failures = failures

    async def connect(self) -> ListenerConnection:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise OSError("connection refused")
        connection = FakeConnection()
        self.connections.append(connection)
        return connection


class Wakeups:
    """Counts wake-ups, and records that each one arrived carrying nothing."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.count = 0
        self.raises = raises
        self.signal = asyncio.Event()

    def __call__(self) -> None:
        self.count += 1
        self.signal.set()
        if self.raises is not None:
            raise self.raises

    async def wait(self, timeout: float = PATIENCE) -> bool:
        try:
            await asyncio.wait_for(self.signal.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True


def build(driver: FakeDriver, wakeups: Wakeups, **overrides: Any) -> DomainEventListener:
    arguments: dict[str, Any] = {
        "connect": driver.connect,
        "on_wakeup": wakeups,
        "heartbeat": 60.0,
        "initial_backoff": QUICK,
        "max_backoff": QUICK,
    }
    arguments.update(overrides)
    return DomainEventListener(**arguments)


# ------------------------------------------------------------------------------ the wake-up


async def test_a_notification_wakes_the_subscribers() -> None:
    driver, wakeups = FakeDriver(), Wakeups()
    listener = build(driver, wakeups)
    await listener.start()
    try:
        assert await listener.wait_connected(timeout=PATIENCE)
        before = wakeups.count
        driver.connections[0].notify("641")
        assert wakeups.count == before + 1
    finally:
        await listener.stop()


async def test_a_wakeup_carries_nothing_the_notification_said() -> None:
    """The signal is a bare call. There is nowhere for a payload to become authoritative."""
    driver, wakeups = FakeDriver(), Wakeups()
    listener = build(driver, wakeups)
    await listener.start()
    try:
        assert await listener.wait_connected(timeout=PATIENCE)
        driver.connections[0].notify("641")
        driver.connections[0].notify("not-a-number")
        driver.connections[0].notify("")
    finally:
        await listener.stop()

    # Every payload produced the same thing: a call with no arguments.
    assert wakeups.count >= 3


async def test_establishing_a_subscription_wakes_every_subscriber() -> None:
    """The gap before a subscription exists is exactly where notifications were missed.

    So a fresh ``LISTEN`` is itself a reason to read the ledger, and saying so here is what
    turns a reconnect from a silent hole into a catch-up.
    """
    driver, wakeups = FakeDriver(), Wakeups()
    listener = build(driver, wakeups)
    await listener.start()
    try:
        assert await listener.wait_connected(timeout=PATIENCE)
        assert wakeups.count == 1
    finally:
        await listener.stop()


async def test_a_subscriber_that_raises_does_not_take_the_listener_down() -> None:
    driver = FakeDriver()
    wakeups = Wakeups(raises=RuntimeError("subscriber exploded"))
    listener = build(driver, wakeups)
    await listener.start()
    try:
        assert await listener.wait_connected(timeout=PATIENCE)
        driver.connections[0].notify("1")
        assert listener.connected
        assert wakeups.count >= 2
    finally:
        await listener.stop()


# ------------------------------------------------------------------------------- reconnection


async def test_a_lost_connection_is_reconnected() -> None:
    driver, wakeups = FakeDriver(), Wakeups()
    listener = build(driver, wakeups)
    await listener.start()
    try:
        assert await listener.wait_connected(timeout=PATIENCE)
        first = driver.connections[0]
        first.terminate()

        assert await listener.wait_connected(timeout=PATIENCE, after_generation=1)
        assert listener.generation == 2
        assert first.closed
        assert len(driver.connections) == 2
    finally:
        await listener.stop()


async def test_a_reconnect_wakes_subscribers_so_the_gap_is_read_from_the_ledger() -> None:
    driver, wakeups = FakeDriver(), Wakeups()
    listener = build(driver, wakeups)
    await listener.start()
    try:
        assert await listener.wait_connected(timeout=PATIENCE)
        driver.connections[0].terminate()
        assert await listener.wait_connected(timeout=PATIENCE, after_generation=1)
        assert wakeups.count == 2
    finally:
        await listener.stop()


async def test_a_refused_connection_is_retried_until_it_succeeds() -> None:
    driver, wakeups = FakeDriver(failures=3), Wakeups()
    listener = build(driver, wakeups)
    await listener.start()
    try:
        assert await listener.wait_connected(timeout=PATIENCE)
        assert driver.attempts == 4
    finally:
        await listener.stop()


async def test_a_failed_subscription_closes_its_connection_and_retries() -> None:
    """A socket that connected but could not subscribe is not left open behind us."""

    class RefusingDriver(FakeDriver):
        async def connect(self) -> ListenerConnection:
            connection = await super().connect()
            if self.attempts == 1:
                assert isinstance(connection, FakeConnection)
                connection.subscribe_error = OSError("subscribe failed")
            return connection

    driver, wakeups = RefusingDriver(), Wakeups()
    listener = build(driver, wakeups)
    await listener.start()
    try:
        assert await listener.wait_connected(timeout=PATIENCE)
        assert driver.connections[0].closed
        assert listener.generation == 1
    finally:
        await listener.stop()


async def test_retrying_does_not_become_a_busy_loop() -> None:
    """Backoff is bounded above and below: it waits, and it never stops trying."""
    driver, wakeups = FakeDriver(failures=10**6), Wakeups()
    listener = build(driver, wakeups, initial_backoff=0.05, max_backoff=0.05)
    await listener.start()
    try:
        assert not await listener.wait_connected(timeout=0.3)
    finally:
        await listener.stop()

    assert driver.attempts >= 2, "a listener that stopped trying is a feed that is silently dead"
    assert driver.attempts <= 20, "retrying without waiting would be a second outage"


async def test_the_heartbeat_notices_a_silently_dead_connection() -> None:
    """Nothing is ever sent over a session that only listens, so nothing ever fails on it."""
    driver, wakeups = FakeDriver(), Wakeups()
    listener = build(driver, wakeups, heartbeat=QUICK)
    await listener.start()
    try:
        assert await listener.wait_connected(timeout=PATIENCE)
        driver.connections[0].execute_error = OSError("half-open socket")

        assert await listener.wait_connected(timeout=PATIENCE, after_generation=1)
        assert "SELECT 1" in driver.connections[0].queries
        assert driver.connections[0].closed
    finally:
        await listener.stop()


# ---------------------------------------------------------------------------------- lifecycle


async def test_shutdown_releases_the_connection() -> None:
    driver, wakeups = FakeDriver(), Wakeups()
    listener = build(driver, wakeups)
    await listener.start()
    assert await listener.wait_connected(timeout=PATIENCE)

    await listener.stop()

    assert not listener.connected
    assert driver.connections[0].closed


async def test_shutdown_is_idempotent() -> None:
    """A reload may run it twice, and the second time must not be an error."""
    driver, wakeups = FakeDriver(), Wakeups()
    listener = build(driver, wakeups)
    await listener.start()
    assert await listener.wait_connected(timeout=PATIENCE)

    await listener.stop()
    await listener.stop()

    assert not listener.connected


async def test_starting_twice_keeps_one_subscription() -> None:
    """One listener for the process is the whole point; a second would double its connections."""
    driver, wakeups = FakeDriver(), Wakeups()
    listener = build(driver, wakeups)
    await listener.start()
    await listener.start()
    try:
        assert await listener.wait_connected(timeout=PATIENCE)
        assert len(driver.connections) == 1
    finally:
        await listener.stop()


# ------------------------------------------------------------------------------- construction


def test_the_listener_refuses_an_administrative_credential() -> None:
    """Listening needs no privilege, so nothing here has an excuse to hold the owner's login."""
    settings = Settings(
        database_url="postgresql+asyncpg://postgres.abcdefghij:pw@pooler.example:5432/postgres"
    )
    with pytest.raises(RuntimeRoleError, match=RUNTIME_ROLE):
        DomainEventListener.from_settings(settings, on_wakeup=lambda: None)


def test_the_dsn_drops_the_dialect_and_keeps_the_connection() -> None:
    dsn = asyncpg_dsn("postgresql+asyncpg://promisepatch_app.ref:pw@pooler.example:5432/postgres")
    assert dsn.startswith("postgresql://")
    assert "+asyncpg" not in dsn
    assert "promisepatch_app.ref" in dsn
    assert dsn.endswith("/postgres")


# --------------------------------------------------------------------------- the real database


@pytest.fixture
def operator_settings() -> Settings:
    settings = Settings()
    if settings.database_url is None:
        pytest.skip("PP_DATABASE_URL is not set; the listener integration test needs it")
    if settings.migration_database_url is None:
        pytest.skip("PP_MIGRATION_DATABASE_URL is not set; producing an event needs it")
    if settings.demo_worker_password is None or settings.demo_owner_password is None:
        pytest.skip("PP_DEMO_WORKER_PASSWORD / PP_DEMO_OWNER_PASSWORD are not set")
    return settings


@pytest_asyncio.fixture
async def operator_engine(operator_settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = build_engine(migration_database_url(operator_settings), pool_size=1)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_a_real_notification_crosses_the_session_pooler(
    operator_settings: Settings, operator_engine: AsyncEngine
) -> None:
    """The one thing a stand-in cannot establish.

    ``LISTEN`` is a property of a session, and a transaction-pooled endpoint would hand the
    session back after each transaction and lose the subscription silently. This connects the
    way the API connects, commits a real domain event, and waits for the wake-up to arrive.
    """
    wakeups = Wakeups()
    listener = DomainEventListener.from_settings(operator_settings, on_wakeup=wakeups)
    await listener.start()
    try:
        assert await listener.wait_connected(timeout=30.0)
        wakeups.signal.clear()

        async with operator_engine.begin() as connection:
            await reset_demo_state(
                connection,
                anchor=datetime(2026, 3, 4, 7, 0, tzinfo=UTC),
                now=datetime.now(UTC),
                passwords={
                    demo.BAKER_ROLE: operator_settings.require_demo_worker_password(),
                    demo.OWNER_ROLE: operator_settings.require_demo_owner_password(),
                },
                actor=Actor(kind="SYSTEM", id="listener-integration-test"),
            )

        assert await wakeups.wait(timeout=30.0)
    finally:
        await listener.stop()
