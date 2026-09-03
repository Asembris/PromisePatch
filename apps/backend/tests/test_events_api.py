"""``GET /events`` end to end: the real application, the real database, the real listener.

The suite drives the ASGI application directly rather than through the usual test client. That
is not a preference: a test client reads a response to completion before handing it back, and a
live feed has no completion, so every assertion about an open stream would be a deadlock. What
is exercised here is otherwise the whole path -- routing, middleware, the session cookie, the
runtime connection, the ``LISTEN`` started by the application's own lifespan -- with nothing
faked.

Events are produced the way an operator produces them, by resetting the demo fixture over the
privileged connection. The API never gains a write endpoint to make a test convenient.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, MutableMapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from promisepatch.api.routers import auth as login_router
from promisepatch.api.stream import NO_CURSOR, RESYNC_EVENT
from promisepatch.config import Settings
from promisepatch.db import build_engine
from promisepatch.db.models import Session
from promisepatch.db.uow import Actor
from promisepatch.fixtures import demo
from promisepatch.fixtures.reset import ResetOutcome, reset_demo_state
from promisepatch.main import create_app

pytestmark = pytest.mark.integration

PATIENCE = 30.0
"""Failure bound for a frame that should already be on its way. Never a synchroniser."""

FIXTURE_ANCHOR = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
"""The anchor the shared demo fixture is guaranteed at, so these resets leave it as found."""

BAKER, OWNER = "maya", "jo"


# ------------------------------------------------------------------------- driving the app


@dataclass(frozen=True, slots=True)
class Reply:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


@dataclass
class AsgiSession:
    """A cookie jar and an ASGI caller: enough to log in and to hold a stream open."""

    app: FastAPI
    cookies: dict[str, str] = field(default_factory=dict)

    def scope(self, method: str, path: str, headers: dict[str, str]) -> MutableMapping[str, Any]:
        raw = [(b"host", b"testserver")]
        if self.cookies:
            jar = "; ".join(f"{name}={value}" for name, value in self.cookies.items())
            raw.append((b"cookie", jar.encode()))
        raw.extend((name.lower().encode(), value.encode()) for name, value in headers.items())
        return {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": raw,
            "client": ("127.0.0.1", 5555),
            "server": ("testserver", 80),
        }

    def absorb(self, headers: list[tuple[bytes, bytes]]) -> None:
        for name, value in headers:
            if name.lower() != b"set-cookie":
                continue
            key, _, raw = value.decode().partition("=")
            cookie = raw.split(";")[0]
            if cookie:
                self.cookies[key] = cookie
            else:
                self.cookies.pop(key, None)

    async def request(
        self, method: str, path: str, *, body: Any = None, headers: dict[str, str] | None = None
    ) -> Reply:
        payload = b"" if body is None else json.dumps(body).encode()
        sending = dict(headers or {})
        if body is not None:
            sending["content-type"] = "application/json"
            sending["content-length"] = str(len(payload))

        messages: list[MutableMapping[str, Any]] = []
        delivered = False

        async def receive() -> MutableMapping[str, Any]:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": payload, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: MutableMapping[str, Any]) -> None:
            messages.append(message)

        await self.app(self.scope(method, path, sending), receive, send)
        start = next(m for m in messages if m["type"] == "http.response.start")
        self.absorb(start["headers"])
        return Reply(
            status=start["status"],
            headers={
                name.decode().lower(): value.decode()
                for name, value in start["headers"]
                if name.lower() != b"set-cookie"
            },
            body=b"".join(
                m.get("body", b"") for m in messages if m["type"] == "http.response.body"
            ),
        )

    async def login(self, username: str, password: str) -> Reply:
        return await self.request(
            "POST", "/api/auth/login", body={"username": username, "password": password}
        )

    async def logout(self) -> Reply:
        return await self.request(
            "POST", "/api/auth/logout", headers={"X-CSRF-Token": self.cookies["pp_csrf"]}
        )

    def stream(self, headers: dict[str, str] | None = None) -> AsgiStream:
        return AsgiStream(self.app, self.scope("GET", "/events", headers or {}))


class AsgiStream:
    """One open ``/events`` response, read frame by frame and closed like a real client."""

    def __init__(self, app: FastAPI, scope: MutableMapping[str, Any]) -> None:
        self._app = app
        self._scope = scope
        self._chunks: asyncio.Queue[bytes] = asyncio.Queue()
        self._started = asyncio.Event()
        self._disconnected = asyncio.Event()
        self._buffer = b""
        self._task: asyncio.Task[None] | None = None
        self.status = 0
        self.headers: dict[str, str] = {}

    async def __aenter__(self) -> AsgiStream:
        async def receive() -> MutableMapping[str, Any]:
            await self._disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                self.status = message["status"]
                self.headers = {
                    name.decode().lower(): value.decode() for name, value in message["headers"]
                }
                self._started.set()
            elif message["type"] == "http.response.body":
                self._chunks.put_nowait(message.get("body", b""))

        self._task = asyncio.create_task(self._app(self._scope, receive, send))
        started = asyncio.create_task(self._started.wait())
        await asyncio.wait(
            {started, self._task}, timeout=PATIENCE, return_when=asyncio.FIRST_COMPLETED
        )
        started.cancel()
        if not self._started.is_set():  # pragma: no cover - only on a broken endpoint
            raise AssertionError("the endpoint never began a response")
        return self

    async def __aexit__(self, *_: object) -> None:
        self._disconnected.set()
        task = self._task
        if task is None:  # pragma: no cover - set in __aenter__
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=PATIENCE)
        except TimeoutError:  # pragma: no cover - a stream that ignores a disconnect
            task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def frame(self, timeout: float = PATIENCE) -> dict[str, Any]:
        while b"\n\n" not in self._buffer:
            self._buffer += await asyncio.wait_for(self._chunks.get(), timeout=timeout)
        raw, _, self._buffer = self._buffer.partition(b"\n\n")
        return parse_frame(raw)

    async def event_frame(self, timeout: float = PATIENCE) -> dict[str, Any]:
        """The next frame that is not a keepalive comment."""
        frame = await self.frame(timeout)
        while frame["comment"] is not None:
            frame = await self.frame(timeout)
        return frame


def parse_frame(raw: bytes) -> dict[str, Any]:
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


# ------------------------------------------------------------------------------- the fixtures


@pytest.fixture
def live_settings(runtime_settings: Settings) -> Settings:
    if runtime_settings.migration_database_url is None:
        pytest.skip("PP_MIGRATION_DATABASE_URL is not set; producing an event needs it")
    if (
        runtime_settings.demo_worker_password is None
        or runtime_settings.demo_owner_password is None
    ):
        pytest.skip("PP_DEMO_WORKER_PASSWORD / PP_DEMO_OWNER_PASSWORD are not set")
    return runtime_settings


@pytest_asyncio.fixture
async def live_app(live_settings: Settings, demo_state: object) -> AsyncIterator[FastAPI]:
    """The real application, with its lifespan run on this test's event loop.

    The lifespan is what opens the runtime engine and starts the process's one ``LISTEN``, so
    running it here rather than in a client's background thread is what lets every connection
    in the test belong to the same loop.
    """
    login_router._limiter.reset()
    app = create_app(live_settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def operator_engine(live_settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = build_engine(live_settings.require_migration_database_url(), pool_size=1)
    try:
        yield engine
    finally:
        await engine.dispose()


async def append_one_event(engine: AsyncEngine, settings: Settings) -> ResetOutcome:
    """One committed domain event, through the operator path that already exists."""
    async with engine.begin() as connection:
        return await reset_demo_state(
            connection,
            anchor=FIXTURE_ANCHOR,
            now=datetime.now(UTC),
            passwords={
                demo.BAKER_ROLE: settings.require_demo_worker_password(),
                demo.OWNER_ROLE: settings.require_demo_owner_password(),
            },
            actor=Actor(kind="SYSTEM", id="events-api-tests"),
        )


async def signed_in(app: FastAPI, settings: Settings, who: str = BAKER) -> AsgiSession:
    session = AsgiSession(app)
    password = (
        settings.require_demo_worker_password()
        if who == BAKER
        else settings.require_demo_owner_password()
    )
    assert (await session.login(who, password)).status == 200
    return session


# ------------------------------------------------------------------------------------ access


async def test_an_unauthenticated_stream_is_refused(live_app: FastAPI) -> None:
    reply = await AsgiSession(live_app).request("GET", "/events")

    assert reply.status == 401
    assert reply.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_a_forged_session_cookie_is_refused(live_app: FastAPI) -> None:
    session = AsgiSession(live_app, cookies={"pp_session": "not.a-real-signature"})

    reply = await session.request("GET", "/events")

    assert reply.status == 401


async def test_a_revoked_session_cannot_open_a_stream(
    live_app: FastAPI, live_settings: Settings
) -> None:
    session = await signed_in(live_app, live_settings)
    assert (await session.logout()).status == 204

    assert (await session.request("GET", "/events")).status == 401


async def test_an_expired_session_cannot_open_a_stream(
    live_app: FastAPI, live_settings: Settings, operator_engine: AsyncEngine
) -> None:
    """Expiry is decided by the row, not by the cookie a client chooses to keep presenting."""
    session = await signed_in(live_app, live_settings)
    session_id = UUID(session.cookies["pp_session"].split(".")[0])

    async with operator_engine.begin() as connection:
        await connection.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(expires_at=datetime.now(UTC) - timedelta(hours=1))
        )

    reply = await session.request("GET", "/events")
    assert reply.status == 401
    assert reply.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_the_baker_may_open_a_stream(live_app: FastAPI, live_settings: Settings) -> None:
    session = await signed_in(live_app, live_settings, BAKER)

    async with session.stream() as stream:
        assert stream.status == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert "no-cache" in stream.headers["cache-control"]
        assert stream.headers["x-accel-buffering"] == "no"


async def test_the_owner_may_open_a_stream(live_app: FastAPI, live_settings: Settings) -> None:
    """The live feed is evidence, and both roles read evidence."""
    session = await signed_in(live_app, live_settings, OWNER)

    async with session.stream() as stream:
        assert stream.status == 200


async def test_an_unreadable_resume_cursor_is_refused(
    live_app: FastAPI, live_settings: Settings
) -> None:
    session = await signed_in(live_app, live_settings)

    reply = await session.request("GET", "/events", headers={"Last-Event-ID": "yesterday"})

    assert reply.status == 400
    assert reply.json()["error"]["code"] == "INVALID_LAST_EVENT_ID"


# ------------------------------------------------------------------------------------ replay


async def test_a_fresh_stream_opens_by_saying_where_the_ledger_is(
    live_app: FastAPI, live_settings: Settings
) -> None:
    session = await signed_in(live_app, live_settings)

    async with session.stream() as stream:
        frame = await stream.event_frame()

    assert frame["event"] == RESYNC_EVENT
    assert frame["data"]["reason"] == NO_CURSOR
    assert int(frame["id"]) == frame["data"]["latest_seq"]


async def test_a_reconnect_replays_an_event_no_stream_was_open_for(
    live_app: FastAPI, live_settings: Settings, operator_engine: AsyncEngine
) -> None:
    """The durability proof, and it owes nothing to ``NOTIFY``.

    Nobody is listening when the event commits, so no notification can have been delivered to
    anyone. The event is nonetheless waiting in PostgreSQL for a client that reconnects with a
    cursor, which is the entire reason the transport is not allowed to be the state.
    """
    session = await signed_in(live_app, live_settings)
    async with session.stream() as stream:
        opening = await stream.event_frame()
    before = int(opening["id"])

    outcome = await append_one_event(operator_engine, live_settings)
    assert outcome.domain_event_seq > before

    # A reset empties the session table along with everything else it owns, so the operator
    # signs in again -- exactly what happens to a browser when the demo is reset under it.
    session = await signed_in(live_app, live_settings)
    async with session.stream({"Last-Event-ID": str(before)}) as stream:
        assert stream.status == 200
        replayed = await stream.event_frame()

    assert int(replayed["id"]) == outcome.domain_event_seq
    assert replayed["event"] == "fixture.reset"


async def test_a_restarted_api_replays_the_same_event_from_postgresql(
    live_app: FastAPI, live_settings: Settings, operator_engine: AsyncEngine
) -> None:
    """Restart safety is a property of the table, not of anything this process remembers."""
    session = await signed_in(live_app, live_settings)
    async with session.stream() as stream:
        before = int((await stream.event_frame())["id"])

    outcome = await append_one_event(operator_engine, live_settings)

    restarted = create_app(live_settings)
    async with restarted.router.lifespan_context(restarted):
        fresh = await signed_in(restarted, live_settings)
        async with fresh.stream({"Last-Event-ID": str(before)}) as stream:
            replayed = await stream.event_frame()

    assert int(replayed["id"]) == outcome.domain_event_seq


async def test_a_replayed_frame_carries_no_business_payload(
    live_app: FastAPI, live_settings: Settings, operator_engine: AsyncEngine
) -> None:
    session = await signed_in(live_app, live_settings)
    async with session.stream() as stream:
        before = int((await stream.event_frame())["id"])
    await append_one_event(operator_engine, live_settings)

    session = await signed_in(live_app, live_settings)
    async with session.stream({"Last-Event-ID": str(before)}) as stream:
        frame = await stream.event_frame()

    assert set(frame["data"]) == {"seq", "id", "type", "occurred_at", "case_id", "entity_refs"}
    assert "digest" not in frame["data"]


# -------------------------------------------------------------------------------- the fan-out


async def test_every_stream_shares_the_one_listener(
    live_app: FastAPI, live_settings: Settings
) -> None:
    """One ``LISTEN`` for the process, however many browsers are watching."""
    listener = live_app.state.event_listener
    assert listener is not None
    assert await listener.wait_connected(timeout=PATIENCE)

    first = await signed_in(live_app, live_settings, BAKER)
    second = await signed_in(live_app, live_settings, OWNER)

    async with first.stream() as one, second.stream() as two:
        await one.event_frame()
        await two.event_frame()
        assert live_app.state.broadcaster.subscriber_count == 2
        assert live_app.state.event_listener is listener
        assert listener.generation == 1

    assert live_app.state.broadcaster.subscriber_count == 0


async def test_opening_and_closing_streams_does_not_exhaust_the_connection_pool(
    live_app: FastAPI, live_settings: Settings
) -> None:
    """A stream cut off mid-read must hand its connection back, or the pool drains away.

    The runtime role has a deliberately small budget and the engine allows no overflow, so a
    connection kept by an abandoned reader would not fail loudly -- it would make the next
    request wait. More streams are opened and dropped here than the pool holds, and then an
    ordinary read is asked for.
    """
    session = await signed_in(live_app, live_settings)
    for _ in range(8):
        # Closed without reading anything, so each reader is cut off during its very first
        # query: the moment at which a connection is lost if one ever is.
        async with session.stream() as stream:
            assert stream.status == 200

    reply = await session.request("GET", "/api/promises")
    assert reply.status == 200


async def test_a_live_event_reaches_an_already_open_stream(
    live_app: FastAPI, live_settings: Settings, operator_engine: AsyncEngine
) -> None:
    """The whole path in one test: commit, trigger, ``NOTIFY``, listener, fan-out, frame."""
    listener = live_app.state.event_listener
    assert await listener.wait_connected(timeout=PATIENCE)

    session = await signed_in(live_app, live_settings)
    async with session.stream() as stream:
        await stream.event_frame()

        outcome = await append_one_event(operator_engine, live_settings)

        delivered = await stream.event_frame()

    assert int(delivered["id"]) == outcome.domain_event_seq
    assert delivered["data"]["type"] == "fixture.reset"
