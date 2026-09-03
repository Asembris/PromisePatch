"""One long-lived ``LISTEN`` for the whole API process.

PostgreSQL tells us when the event spine moves, and this module is what it tells. Every
constraint below follows from what a notification actually is:

* **A wake-up, not a message.** Nothing here reads a payload as state. A notification causes a
  read of the durable ledger, so one that never arrives costs latency and nothing else -- and a
  reconnect deliberately wakes every subscriber, because the gap it just closed is exactly the
  window in which notifications went missing.
* **One connection for the process, not one per browser.** ``LISTEN`` is a property of a
  session, and a session is a server connection; a listener per subscriber would multiply this
  API's connection use by the size of its audience. One session feeds an in-memory fan-out.
* **Its own connection, never a request's.** A request transaction is short by design and hands
  its connection back to the pool. Holding one open for the life of the process would spend a
  connection out of a deliberately small budget on a socket that only ever waits.
* **The runtime role, like everything else the API does.** ``LISTEN`` requires no privilege at
  all, so there is no argument for reaching for the migration credential here, and
  :meth:`DomainEventListener.from_settings` refuses one.

**Session pooling is a requirement, not a detail.** A transaction-pooled endpoint returns a
different server connection after every transaction, so a ``LISTEN`` registered through one is
simply lost -- the notifications arrive at a session nobody holds. This process connects
through the *session* pooler, where a client connection maps to one server connection for its
whole life. :meth:`from_settings` is handed the same URL the API serves requests over, and an
integration test proves a real notification arrives across it.

**Failure is expected and is not fatal.** Poolers restart, networks blip, idle connections get
reaped. The supervisor reconnects with bounded exponential backoff and does not give up while
the process runs, because a live feed that is silently dead until somebody restarts the API is
worse than one that is late. Startup does not block on the first connection either: reads are
served whether or not the feed is up, and ``/readyz`` is where database reachability is
reported.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from typing import Any, Final, Protocol

import asyncpg
from sqlalchemy.engine import make_url

from promisepatch.config import Settings
from promisepatch.db.boundary import EVENT_CHANNEL, RUNTIME_ROLE
from promisepatch.db.runtime import RuntimeRoleError, login_role
from promisepatch.db.session import DEFAULT_CONNECT_TIMEOUT
from promisepatch.observability import get_logger

logger = get_logger(__name__)

INITIAL_BACKOFF: Final = 0.5
"""First retry delay in seconds, short enough that an ordinary blip is invisible."""

MAX_BACKOFF: Final = 30.0
"""The ceiling the delay doubles up to.

A listener retrying twice a second against a database that is down for an hour is a second
outage layered on top of the first.
"""

HEARTBEAT_INTERVAL: Final = 30.0
"""How often an idle listener proves its connection is still there.

A session that only listens sends nothing, so nothing ever fails on it: a connection dropped by
a pooler or a firewall can look open on this side indefinitely. One cheap query turns a silent
half-open socket into an ordinary reconnect.
"""

SHUTDOWN_TIMEOUT: Final = 5.0
"""How long shutdown waits for the supervisor to release its connection before cancelling."""


class ListenerConnection(Protocol):
    """The part of a driver connection this module uses.

    Named so that reconnect, heartbeat and clean shutdown can be driven deterministically by a
    stand-in, rather than by provoking a real network failure and waiting to see what happens.
    """

    async def add_listener(self, channel: str, callback: Any) -> None: ...

    def add_termination_listener(self, callback: Any) -> None: ...

    async def execute(self, query: str, *args: Any) -> Any: ...

    async def close(self) -> None: ...


Connect = Callable[[], Awaitable[ListenerConnection]]
Wakeup = Callable[[], None]


def asyncpg_dsn(url: str) -> str:
    """The same connection string, in the form the driver takes without SQLAlchemy in front."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


class DomainEventListener:
    """A supervised ``LISTEN`` session that calls ``on_wakeup`` when the spine may have moved.

    "May have" is the honest verb. A caller learns that it should read the ledger and nothing
    more, and it is woken on reconnect as well as on notification, because from where a
    subscriber sits those two are the same event.
    """

    def __init__(
        self,
        *,
        connect: Connect,
        on_wakeup: Wakeup,
        channel: str = EVENT_CHANNEL,
        heartbeat: float = HEARTBEAT_INTERVAL,
        initial_backoff: float = INITIAL_BACKOFF,
        max_backoff: float = MAX_BACKOFF,
    ) -> None:
        self._connect = connect
        self._on_wakeup = on_wakeup
        self._channel = channel
        self._heartbeat = heartbeat
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._changed = asyncio.Event()
        self._connected = False
        self._generation = 0

    @classmethod
    def from_settings(cls, settings: Settings, *, on_wakeup: Wakeup) -> DomainEventListener:
        """Build a listener on the connection the API serves requests over, and no other."""
        url = settings.require_database_url()
        role = login_role(url)
        if role != RUNTIME_ROLE:
            raise RuntimeRoleError(
                f"PP_DATABASE_URL logs in as {role!r}; the event listener must connect as "
                f"{RUNTIME_ROLE!r}. Listening for notifications needs no privilege at all, so "
                "there is no reason for it to hold an administrative credential."
            )
        dsn = asyncpg_dsn(url)

        async def connect() -> ListenerConnection:
            # No statement cache, for the reason the engine has none: a cached handle belongs
            # to a server connection that a pooler is free to replace underneath it.
            connection: ListenerConnection = await asyncpg.connect(
                dsn, timeout=DEFAULT_CONNECT_TIMEOUT, statement_cache_size=0
            )
            return connection

        return cls(connect=connect, on_wakeup=on_wakeup)

    # ------------------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Begin listening. Returns immediately; connecting happens in the background."""
        if self._task is not None:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="domain-event-listener")

    async def stop(self) -> None:
        """Stop listening and release the connection. Safe to call more than once."""
        task, self._task = self._task, None
        self._stopping.set()
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=SHUTDOWN_TIMEOUT)
        except TimeoutError:
            # The supervisor is stuck somewhere it cannot be asked to leave politely, and
            # shutdown is not the moment to wait indefinitely on a socket.
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    @property
    def connected(self) -> bool:
        """Whether a ``LISTEN`` is established right now."""
        return self._connected

    @property
    def generation(self) -> int:
        """How many times a ``LISTEN`` has been established; it increments on every reconnect."""
        return self._generation

    async def wait_connected(self, *, timeout: float, after_generation: int = 0) -> bool:
        """Wait until a ``LISTEN`` later than ``after_generation`` is established."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            # Cleared before the check and never after: a change landing between the two is
            # then still waiting to be observed rather than already forgotten.
            self._changed.clear()
            if self._connected and self._generation > after_generation:
                return True
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=remaining)
            except TimeoutError:
                return False

    # ------------------------------------------------------------------------- the supervisor

    async def _run(self) -> None:
        backoff = self._initial_backoff
        while not self._stopping.is_set():
            connection = await self._open()
            if connection is None:
                await _wait_any((self._stopping,), timeout=backoff)
                backoff = min(backoff * 2, self._max_backoff)
                continue
            backoff = self._initial_backoff
            await self._serve(connection)
            if not self._stopping.is_set():
                await _wait_any((self._stopping,), timeout=self._initial_backoff)

    async def _open(self) -> ListenerConnection | None:
        """Connect and subscribe, or report the failure and leave the retry to the caller."""
        try:
            connection = await self._connect()
        except Exception as error:
            # The class of the failure, never its message: a driver routinely quotes the host
            # and the login it was handed, and this line ends up in a log aggregator.
            logger.warning("events.listener_connect_failed", error=type(error).__name__)
            return None
        try:
            await connection.add_listener(self._channel, self._notified)
        except Exception as error:
            logger.warning("events.listener_subscribe_failed", error=type(error).__name__)
            await _close(connection)
            return None
        return connection

    async def _serve(self, connection: ListenerConnection) -> None:
        """Hold one established subscription until it is lost or shutdown is asked for."""
        lost = asyncio.Event()
        try:
            connection.add_termination_listener(lambda _connection: lost.set())
            self._mark(connected=True)
            logger.info("events.listener_started", channel=self._channel)
            # Whatever happened while we were away was not delivered here. The ledger is how a
            # subscriber finds out, so tell every one of them to go and read it.
            self._wake()
            while not self._stopping.is_set() and not lost.is_set():
                woken = await _wait_any((lost, self._stopping), timeout=self._heartbeat)
                if not woken and not await _alive(connection):
                    break
        finally:
            self._mark(connected=False)
            await _close(connection)
            logger.info("events.listener_stopped", channel=self._channel)

    def _notified(self, _connection: Any, _pid: int, channel: str, payload: str) -> None:
        """Called by the driver for every notification. The payload is a sequence number."""
        logger.debug("events.notified", channel=channel, seq=payload)
        self._wake()

    def _wake(self) -> None:
        try:
            self._on_wakeup()
        except Exception:
            # A subscriber that raises must not take down the only listener this process has.
            logger.exception("events.wakeup_failed")

    def _mark(self, *, connected: bool) -> None:
        self._connected = connected
        if connected:
            self._generation += 1
        self._changed.set()


async def _alive(connection: ListenerConnection) -> bool:
    """Whether the connection still answers. A half-open socket says nothing until asked."""
    try:
        await connection.execute("SELECT 1")
    except Exception as error:
        logger.warning("events.listener_heartbeat_failed", error=type(error).__name__)
        return False
    return True


async def _close(connection: ListenerConnection) -> None:
    with suppress(Exception):
        await connection.close()


async def _wait_any(events: Sequence[asyncio.Event], *, timeout: float) -> bool:
    """Wait for the first of ``events`` or for ``timeout``. ``True`` if one of them fired."""
    waiters = [asyncio.create_task(event.wait()) for event in events]
    try:
        done, _ = await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        return bool(done)
    finally:
        for waiter in waiters:
            waiter.cancel()
