"""Test support for the MCP boundary: a real server, on a real socket, spoken to by a real client.

The point of this harness is that nothing about the protocol is faked. The server is the
application ``pp mcp`` runs, served by uvicorn on a loopback port; the client is the official
SDK's Streamable HTTP client; the bytes on the wire are the bytes a third-party MCP client
would send. Registering two tools and asserting they appear in a Python list would prove
nothing about initialization, negotiation, framing, authentication or ``Origin``, which is most
of what this boundary is for.

Only the hop *behind* the server is substitutable. :class:`RecordingIntents` is an intent API
that answers in the real wire shape and remembers what it was asked, so the offline suite can
assert what the tool forwarded -- the credential, the correlation id, the worker's exact words
-- without a database. The integration suite points the same server at the real intent
application instead, and the MCP process cannot tell the difference, because it only ever had
an HTTP client either way.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx2
import pytest_asyncio
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp

from promisepatch.config import Environment, Settings
from promisepatch.mcp import CaseEngine, build_app

BEARER = "test-mcp-bearer-token"
SERVICE_TOKEN = "test-internal-service-token"
SURFACE_WORKER = "maya"
ALLOWED_ORIGIN = "http://localhost:5173"

JSON_RPC_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
"""What the spec requires of a Streamable HTTP POST. Sent explicitly by the raw probes, because
half of what they are checking is what the server does when one of them is wrong."""


@dataclass
class RecordedCall:
    """One request the MCP process made to the intent API."""

    path: str
    headers: dict[str, str]
    body: dict[str, Any]


@dataclass
class RecordingIntents:
    """An intent API that answers in the real shape and remembers what it was asked.

    Deliberately not a mock of the domain: it answers the *wire contract*, so a change to that
    contract breaks these tests. What it lets the offline suite assert is the half of the hop
    that belongs to the MCP process -- which credential it presented, which correlation id it
    minted, and whether the worker's sentence arrived byte for byte.
    """

    calls: list[RecordedCall] = field(default_factory=list)
    report_status: int = 202
    report_body: dict[str, Any] | None = None
    status_status: int = 200
    status_body: dict[str, Any] | None = None

    def app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/internal/intents/report", self._report, methods=["POST"]),
                Route("/internal/intents/status", self._status, methods=["POST"]),
            ]
        )

    @property
    def last(self) -> RecordedCall:
        return self.calls[-1]

    async def _report(self, request: Request) -> JSONResponse:
        body = await request.json()
        self.calls.append(RecordedCall("report", dict(request.headers), body))
        payload = self.report_body or {
            "case_id": str(uuid4()),
            "statement_id": body.get("command_id"),
            "state": "RECEIVED",
            "created": True,
            "attested_by": SURFACE_WORKER,
        }
        return JSONResponse(payload, status_code=self.report_status)

    async def _status(self, request: Request) -> JSONResponse:
        body = await request.json()
        self.calls.append(RecordedCall("status", dict(request.headers), body))
        payload = self.status_body or {
            "case_id": body.get("case_id"),
            "headline": "PLANNED",
            "speech": "Planned, and waiting for you. Nothing has been done yet.",
            "needs_owner_attention": False,
            "exception_category": "DELIVERY_NOT_RECEIVED",
            "threatened": [],
            "untouched": [],
            "untouched_count": 0,
        }
        return JSONResponse(payload, status_code=self.status_status)


def mcp_settings(**overrides: Any) -> Settings:
    """The configuration the MCP process runs under in tests. Never read from the environment."""
    values: dict[str, Any] = {
        "env": Environment.LOCAL,
        "mcp_bearer_token": BEARER,
        "internal_service_token": SERVICE_TOKEN,
        "surface_worker_id": SURFACE_WORKER,
        "mcp_intent_api_base_url": "http://intents.test",
        "mcp_allowed_origins": ALLOWED_ORIGIN,
        "mcp_allowed_hosts": "127.0.0.1:*,localhost:*",
    }
    values.update(overrides)
    return Settings(**values)


class _QuietServer(uvicorn.Server):
    """A uvicorn server that does not try to own the process's signal handlers."""

    def install_signal_handlers(self) -> None:  # pragma: no cover - trivial override
        return


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@dataclass
class McpServer:
    """A running MCP endpoint, and the two ways a test talks to it."""

    url: str
    intents: RecordingIntents | None

    @asynccontextmanager
    async def session(
        self, *, token: str | None = BEARER, headers: dict[str, str] | None = None
    ) -> AsyncIterator[ClientSession]:
        """An initialized SDK client session against the running server.

        A fresh transport every time it is entered, which is what makes the reconnect
        assertions mean something: leaving this block ends the connection, and the next one is
        a new handshake with nothing carried over but a case id.
        """
        outbound = dict(headers or {})
        if token is not None:
            outbound["Authorization"] = f"Bearer {token}"
        async with (
            httpx2.AsyncClient(headers=outbound) as client,
            streamable_http_client(self.url, http_client=client) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session

    @asynccontextmanager
    async def raw(self) -> AsyncIterator[httpx2.AsyncClient]:
        """A plain HTTP client, for the checks that happen before the protocol does."""
        async with httpx2.AsyncClient() as client:
            yield client


@asynccontextmanager
async def serve(app: ASGIApp) -> AsyncIterator[str]:
    """Serve one ASGI application on a loopback port and yield its base URL.

    A thread with its own event loop, which is the point rather than an implementation detail:
    a server that runs where the test does not is the only way to catch a pool, a client or a
    connection that was built on the wrong loop -- and it is what production looks like.
    """
    port = _free_port()
    server = _QuietServer(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.05)
        else:  # pragma: no cover - only on a machine that cannot bind a loopback port
            raise RuntimeError("the test server did not start")
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@asynccontextmanager
async def mcp_against(
    intent_app: ASGIApp, *, settings: Settings | None = None
) -> AsyncIterator[McpServer]:
    """Run the real MCP server with its engine hop pointed at ``intent_app``."""
    resolved = settings or mcp_settings()
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=intent_app)) as client:
        engine = CaseEngine(
            base_url=resolved.require_mcp_intent_api_base_url(),
            service_token=resolved.require_internal_service_token(),
            timeout_seconds=resolved.mcp_intent_timeout_seconds,
            client=client,
        )
        async with serve(build_app(resolved, engine=engine)) as base:
            yield McpServer(url=f"{base}/mcp", intents=None)


@asynccontextmanager
async def mcp_over_http(
    intent_base_url: str, *, settings: Settings | None = None
) -> AsyncIterator[McpServer]:
    """Run the real MCP server against an intent API on a real socket.

    The faithful arrangement: two servers, two processes' worth of loops, one HTTP hop between
    them carrying a service token. Used where the assertion is about durable consequence rather
    than about what was forwarded.
    """
    resolved = settings or mcp_settings(mcp_intent_api_base_url=intent_base_url)
    # The application closes the engine's pool on its own loop when the server stops; doing it
    # here would close it from the test's loop, which is not the one that opened it.
    async with serve(build_app(resolved, engine=CaseEngine.from_settings(resolved))) as base:
        yield McpServer(url=f"{base}/mcp", intents=None)


@asynccontextmanager
async def mcp_with_no_engine_listening() -> AsyncIterator[McpServer]:
    """Run the real MCP server with its engine hop pointed at a port nothing is serving.

    A real HTTP client on purpose: the point is a connection that fails, which an in-process
    ASGI transport cannot produce -- it routes by path and would happily answer.
    """
    settings = mcp_settings(
        mcp_intent_api_base_url=f"http://127.0.0.1:{_free_port()}",
        mcp_intent_timeout_seconds=1.0,
    )
    async with serve(build_app(settings, engine=CaseEngine.from_settings(settings))) as base:
        yield McpServer(url=f"{base}/mcp", intents=None)


@pytest_asyncio.fixture
async def mcp() -> AsyncIterator[McpServer]:
    """The offline harness: a real server and client, a recording intent API behind them."""
    intents = RecordingIntents()
    async with mcp_against(intents.app()) as server:
        server.intents = intents
        yield server
