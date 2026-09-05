"""Two applications, two databases, and the wire between them.

These helpers run the real External Order System simulator -- its own FastAPI application over
its own SQLite file -- beside the real PromisePatch application over PostgreSQL, and let a test
drive the traffic that crosses between them. Nothing is faked at the boundary: the amendment is
a real HTTP request the simulator parses, the webhook is a real signed request PromisePatch's
ingress verifies, and each side reads only its own storage.

What that buys is the assertion the whole slice exists for. A test can change an order in the
order system and then ask PromisePatch what it believes, and the answer is genuinely "still the
old thing" until the event has been delivered and processed -- because the two systems really do
not share a table.

The transport is in-process, which is the one thing here that is not literally what production
does. It changes nothing about the boundary: both applications are separate ASGI applications
with separate storage, and the bytes on the wire, the signature over them and the status codes
are the real ones. A genuinely separate operating-system process is what Docker Compose and the
browser suite exercise.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import httpx2
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

from order_contract import signing
from order_contract.events import (
    EVENT_ORDER_UPDATED,
    ChannelRef,
    CustomerRef,
    OrderEvent,
    OrderLineRef,
    OrderSnapshot,
    OrderStateName,
)
from order_simulator.app import create_app as create_simulator
from order_simulator.config import Settings as SimulatorSettings
from order_simulator.store import OrderStore
from order_simulator.webhooks import WebhookDispatcher
from promisepatch.config import Settings
from promisepatch.db.models import AuditEvent, InboxEvent, Order, OrderLine
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.domain.adapters import FakeEffectAdapter, RoutedEffectAdapter
from promisepatch.domain.model import EFFECT_ORDER_AMEND
from promisepatch.domain.order_mirror import ORDER_SYSTEM_SOURCE
from promisepatch.integrations.order_system import OrderSystemAdapter, OrderSystemClient
from promisepatch.main import create_app as create_promisepatch

WEBHOOK_SECRET: Final = "promisepatch-order-system-test-secret"
"""The shared secret both sides of these tests sign and verify with.

A literal, and committed, because it authenticates nothing outside the test process. The
deployed value is generated into a gitignored file and never appears in this repository.
"""

WEBHOOK_PATH: Final = "/api/integrations/order-system/events"
SIMULATOR_ORIGIN: Final = "http://order-system.test"
PROMISEPATCH_ORIGIN: Final = "http://promisepatch.test"

LENA_ORDER: Final = "EXT-D"
LENA_LINE: Final = "ol-d"
RASPBERRY_LEMON: Final = "rv-raspberry-lemon-2"
LEMON_CURD: Final = "rv-lemon-curd-1"


def order_system_settings(base: Settings) -> Settings:
    """PromisePatch's settings, pointed at the order system this test is running.

    ``model_copy`` rather than environment mutation: the deployment's own configuration decides
    whether an order system exists, and a test that changed the process environment to say so
    would leak that decision into every test after it.
    """
    return base.model_copy(
        update={
            "order_system_base_url": SIMULATOR_ORIGIN,
            "order_system_webhook_secret": SecretStr(WEBHOOK_SECRET),
        }
    )


# ------------------------------------------------------------------------ building an event


def a_snapshot(
    *,
    external_id: str = LENA_ORDER,
    version: int,
    item: str = LEMON_CURD,
    line_id: str = LENA_LINE,
    quantity: int = 1,
    state: OrderStateName = "AMENDED",
) -> OrderSnapshot:
    """An authoritative order, as the order system would describe it."""
    return OrderSnapshot(
        external_id=external_id,
        version=version,
        state=state,
        customer=CustomerRef(
            external_id="cus-lena",
            name="Lena Fischer",
            approval_channel=ChannelRef(kind="telegram", address="1004"),
        ),
        due_at=datetime.now(UTC),
        lines=(OrderLineRef(external_line_id=line_id, external_item_id=item, quantity=quantity),),
    )


def an_event(
    *,
    version: int,
    previous_version: int | None = None,
    event_id: UUID | None = None,
    **snapshot: Any,
) -> OrderEvent:
    """One order-system event, hand-built for the orderings a live simulator will not produce."""
    return OrderEvent(
        event_id=event_id or uuid4(),
        type=EVENT_ORDER_UPDATED,
        occurred_at=datetime.now(UTC),
        previous_version=version - 1 if previous_version is None else previous_version,
        changed_line_ids=(snapshot.get("line_id", LENA_LINE),),
        order=a_snapshot(version=version, **snapshot),
    )


def signed_headers(
    body: bytes, *, secret: str = WEBHOOK_SECRET, now: datetime | None = None
) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        **signing.headers_for(secret=secret, body=body, now=now),
    }


# --------------------------------------------------------------------------- the two systems


@dataclass
class Boundary:
    """Both applications, running, with the traffic between them under a test's control."""

    database: RuntimeDatabase
    simulator: OrderStore
    client: OrderSystemClient
    order_system_adapter: OrderSystemAdapter
    """The order system's own adapter, for the tests that are about it specifically."""
    adapter: RoutedEffectAdapter
    """What the worker is actually given: amendments to the order system, the rest elsewhere.

    A worker has one adapter and several kinds of effect. Handing it the order system's adapter
    alone would make the customer message -- whose real channel is a later slice -- fail with
    "this adapter cannot deliver that", which is a fact about the test rig rather than about
    the system. So the tests compose it exactly as ``promisepatch.worker.run`` does.
    """
    simulator_http: httpx2.AsyncClient
    promisepatch_http: httpx2.AsyncClient
    dispatcher: WebhookDispatcher

    # ------------------------------------------------------------------ the order system

    async def operator_changes(self, *, item: str = LEMON_CURD, order: str = LENA_ORDER) -> Any:
        """An operator edits the order in the order system's own screen.

        Through its HTTP surface, exactly as the browser does. No PromisePatch helper touches
        anything: this is a mutation in another application's database, and PromisePatch will
        find out about it the same way it finds out about every other one.
        """
        line = self.simulator.read_order(order).lines[0].external_line_id
        response = await self.simulator_http.post(
            f"{SIMULATOR_ORIGIN}/ui/orders/{order}/lines/{line}",
            data={"to_item_id": item},
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
        return self.simulator.read_order(order)

    def external_order(self, external_id: str = LENA_ORDER) -> OrderSnapshot:
        """What the order system itself says, read from its own storage."""
        return self.simulator.read_order(external_id)

    # ------------------------------------------------------------------------- the wire

    async def deliver_webhooks(self, *, limit: int = 10) -> int:
        """Run the order system's delivery loop until its queue is empty."""
        delivered = 0
        for _ in range(limit):
            if not await self.dispatcher.deliver_one(self.promisepatch_http):
                return delivered
            delivered += 1
        return delivered

    # ------------------------------------------------------------------ the mirror side

    async def mirrored_order(self, external_id: str = LENA_ORDER) -> Any:
        async with self.database.connect() as connection:
            return (
                await connection.execute(select(Order).where(Order.external_id == external_id))
            ).one()

    async def mirrored_version_of(self, line_id: str = LENA_LINE) -> str:
        async with self.database.connect() as connection:
            return (
                await connection.execute(
                    select(OrderLine.recipe_version_id).where(OrderLine.id == line_id)
                )
            ).scalar_one()

    async def inbox_rows(self) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(InboxEvent)
                        .where(InboxEvent.source == ORDER_SYSTEM_SOURCE)
                        .order_by(InboxEvent.received_at)
                    )
                ).all()
            )

    async def audits_of(self, *types: str) -> list[Any]:
        async with self.database.connect() as connection:
            return list(
                (
                    await connection.execute(
                        select(AuditEvent)
                        .where(AuditEvent.type.in_(types))
                        .order_by(AuditEvent.seq)
                    )
                ).all()
            )


@asynccontextmanager
async def boundary(
    database: RuntimeDatabase,
    *,
    settings: Settings,
    sqlite_path: Path,
    transport: Callable[[httpx2.AsyncClient], httpx2.AsyncClient] | None = None,
) -> AsyncIterator[Boundary]:
    """Bring both applications up, wire them to each other, and take them down again.

    ``transport`` wraps the client PromisePatch uses to reach the order system, which is how a
    test injects the one fault that cannot be produced any other way: a response that is lost
    after the order system has already applied the change.
    """
    simulator_settings = SimulatorSettings(
        database_path=sqlite_path,
        webhook_url=f"{PROMISEPATCH_ORIGIN}{WEBHOOK_PATH}",
        webhook_secret=SecretStr(WEBHOOK_SECRET),
        log_level="warning",
    )
    simulator_app = create_simulator(simulator_settings, deliver=False)
    promisepatch_app = create_promisepatch(order_system_settings(settings))

    async with (
        _running(simulator_app),
        _running(promisepatch_app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=simulator_app)) as simulator_http,
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=promisepatch_app)
        ) as promisepatch_http,
    ):
        amendment_http = simulator_http if transport is None else transport(simulator_http)
        client = OrderSystemClient(base_url=SIMULATOR_ORIGIN, timeout=5.0, client=amendment_http)
        order_system_adapter = OrderSystemAdapter(client)
        yield Boundary(
            database=database,
            simulator=OrderStore(sqlite_path),
            client=client,
            order_system_adapter=order_system_adapter,
            adapter=RoutedEffectAdapter(
                routes={EFFECT_ORDER_AMEND: order_system_adapter},
                default=FakeEffectAdapter(),
            ),
            simulator_http=simulator_http,
            promisepatch_http=promisepatch_http,
            dispatcher=WebhookDispatcher(OrderStore(sqlite_path), simulator_settings),
        )


@asynccontextmanager
async def ingress_client(settings: Settings) -> AsyncIterator[httpx2.AsyncClient]:
    """The real PromisePatch application, driven in this test's own event loop.

    An async client over the ASGI application rather than the synchronous ``TestClient``,
    because a test that asserts what the database holds the instant a request returns needs the
    request to be genuinely finished when it returns. The synchronous client hands control back
    from a portal thread, and "the handler has answered" and "the handler has run to completion"
    are then two different moments.
    """
    app = create_promisepatch(settings)
    async with (
        _running(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url=PROMISEPATCH_ORIGIN
        ) as client,
    ):
        yield client


@asynccontextmanager
async def _running(app: FastAPI) -> AsyncIterator[None]:
    """Run an ASGI application's lifespan, which is what opens its database handles."""
    async with app.router.lifespan_context(app):
        yield


class LosingTransport(httpx2.AsyncBaseTransport):
    """A transport that lets the request through and then loses the answer, once.

    The uncertain window, produced deliberately. The order system really applies the amendment;
    the caller really never learns that it did. It is a test transport rather than an endpoint
    on the order system, because a running system with a "lose the next response" control would
    be a system that can be made to lie.
    """

    def __init__(self, inner: httpx2.AsyncClient, *, lose: int = 1) -> None:
        self.inner = inner
        self.lose = lose
        self.requests: list[httpx2.Request] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        response = await self.inner.request(
            request.method,
            request.url,
            content=request.content,
            headers=request.headers,
        )
        if self.lose > 0:
            self.lose -= 1
            raise httpx2.ReadTimeout("the answer was lost after the provider applied it")
        return response


def losing(lose: int = 1) -> Callable[[httpx2.AsyncClient], httpx2.AsyncClient]:
    def wrap(inner: httpx2.AsyncClient) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=LosingTransport(inner, lose=lose))

    return wrap
