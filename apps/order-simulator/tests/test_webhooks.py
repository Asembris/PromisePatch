"""Delivery: signed, durable, retried, and never a second change.

The receiver here is a small in-process ASGI application rather than a mock, so the assertions
are about what actually arrived over HTTP -- headers included -- rather than about what the
dispatcher believed it sent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from _simulator_support import WEBHOOK_SECRET
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from order_contract import signing
from order_contract.events import OrderEvent
from order_simulator.config import Settings
from order_simulator.store import OrderStore
from order_simulator.webhooks import WebhookDispatcher, backoff_seconds

LENA_ORDER = "EXT-D"
LENA_LINE = "ol-d"
LEMON_CURD = "rv-lemon-curd-1"
NOW = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)


class Receiver:
    """A stand-in for PromisePatch's ingress: it records what arrived and answers as told."""

    def __init__(self, status: int = 202) -> None:
        self.status = status
        self.deliveries: list[dict[str, Any]] = []

    async def handle(self, request: Request) -> JSONResponse:
        body = await request.body()
        self.deliveries.append(
            {
                "body": body,
                "signature": request.headers.get(signing.SIGNATURE_HEADER),
                "timestamp": request.headers.get(signing.TIMESTAMP_HEADER),
            }
        )
        return JSONResponse({"accepted": True}, status_code=self.status)

    def app(self) -> Starlette:
        return Starlette(routes=[Route("/events", self.handle, methods=["POST"])])


def client_for(receiver: Receiver) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=receiver.app()))


def settings_for(store: OrderStore) -> Settings:
    return Settings(
        database_path=store.path,
        webhook_url="http://order-receiver.test/events",
        webhook_secret=SecretStr(WEBHOOK_SECRET),
        log_level="warning",
    )


async def test_a_committed_event_is_delivered_signed(store: OrderStore) -> None:
    mutation = store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD, now=NOW
    )
    receiver = Receiver()

    async with client_for(receiver) as client:
        assert await WebhookDispatcher(store, settings_for(store)).deliver_one(client, now=NOW)

    assert len(receiver.deliveries) == 1
    delivered = receiver.deliveries[0]
    signing.verify(
        secret=WEBHOOK_SECRET,
        body=delivered["body"],
        timestamp=delivered["timestamp"],
        signature=delivered["signature"],
        now=NOW,
    )
    assert OrderEvent.model_validate_json(delivered["body"]).event_id == mutation.event.event_id
    assert store.undelivered_count() == 0


async def test_nothing_to_deliver_is_not_a_delivery(store: OrderStore) -> None:
    receiver = Receiver()

    async with client_for(receiver) as client:
        assert not await WebhookDispatcher(store, settings_for(store)).deliver_one(client, now=NOW)

    assert receiver.deliveries == []


async def test_a_rejected_delivery_is_retried_under_the_same_event_id(store: OrderStore) -> None:
    """Transport retries are transport. The change happened once and has one identity."""
    mutation = store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD, now=NOW
    )
    receiver = Receiver(status=500)
    dispatcher = WebhookDispatcher(store, settings_for(store))

    async with client_for(receiver) as client:
        await dispatcher.deliver_one(client, now=NOW)
        receiver.status = 202
        await dispatcher.deliver_one(client, now=NOW + timedelta(minutes=5))

    assert len(receiver.deliveries) == 2
    ids = {OrderEvent.model_validate_json(d["body"]).event_id for d in receiver.deliveries}
    assert ids == {mutation.event.event_id}
    assert store.undelivered_count() == 0
    assert store.event_count(LENA_ORDER) == 1


async def test_a_receiver_that_already_has_the_event_ends_the_delivery(store: OrderStore) -> None:
    """A duplicate the receiver deduplicated is delivered, not a failure to argue with."""
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD, now=NOW
    )
    receiver = Receiver(status=409)

    async with client_for(receiver) as client:
        await WebhookDispatcher(store, settings_for(store)).deliver_one(client, now=NOW)

    assert store.undelivered_count() == 0


async def test_an_unreachable_receiver_leaves_the_event_queued(store: OrderStore) -> None:
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD, now=NOW
    )

    async def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(refuse)) as client:
        assert await WebhookDispatcher(store, settings_for(store)).deliver_one(client, now=NOW)

    assert store.undelivered_count() == 1
    assert store.latest_deliveries()[0].last_error is not None


async def test_an_event_survives_a_restart_and_is_delivered_afterwards(
    store: OrderStore,
) -> None:
    """The crash proof: committed here, delivered after a process that never came back."""
    mutation = store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD, now=NOW
    )
    dead = store.claim_delivery(now=NOW, lease=timedelta(seconds=60))
    assert dead is not None

    restarted = OrderStore(store.path)
    restarted.initialize()
    receiver = Receiver()
    async with client_for(receiver) as client:
        await WebhookDispatcher(restarted, settings_for(restarted)).deliver_one(client, now=NOW)

    assert len(receiver.deliveries) == 1
    body = OrderEvent.model_validate_json(receiver.deliveries[0]["body"])
    assert body.event_id == mutation.event.event_id
    assert restarted.undelivered_count() == 0


async def test_an_unconfigured_webhook_never_sends_an_unsigned_delivery(
    store: OrderStore,
) -> None:
    """Sending unsigned would turn a configuration mistake into a rejection loop."""
    store.operator_change(
        external_order_id=LENA_ORDER, external_line_id=LENA_LINE, to_item_id=LEMON_CURD, now=NOW
    )
    receiver = Receiver()
    unconfigured = Settings(database_path=store.path, log_level="warning")

    async with client_for(receiver) as client:
        assert await WebhookDispatcher(store, unconfigured).deliver_one(client, now=NOW)

    assert receiver.deliveries == []
    assert store.undelivered_count() == 1


@pytest.mark.parametrize(
    ("attempts", "expected"), [(1, 1.0), (2, 2.0), (3, 4.0), (6, 30.0), (40, 30.0)]
)
def test_the_backoff_climbs_and_then_stops_climbing(attempts: int, expected: float) -> None:
    assert backoff_seconds(attempts, maximum=30.0) == expected
