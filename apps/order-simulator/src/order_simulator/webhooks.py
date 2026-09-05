"""Getting a committed order event out of this system, however long that takes.

The delivery loop is deliberately small, and deliberately durable. It owns no queue: every
event waiting to go out is a row in ``webhook_deliveries``, so restarting this process loses
nothing and resuming needs no hand-off. That is the whole reason the loop exists rather than a
``POST`` at the end of the mutation -- an order that changed and an event that evaporated
because the network blinked would leave two systems disagreeing with nothing to notice it.

**It never gives up.** There is no attempt bound and no dead-letter state. A committed event is
a fact about this system's own orders; abandoning it would mean the mirror on the other side
stays wrong for ever. It retreats to half a minute between attempts and keeps going, which is
what "no manual resend required" means in practice.

**It signs, or it does not send.** An unsigned webhook is one the receiver is right to refuse,
and sending it anyway would turn a configuration mistake into a confusing rejection loop
instead of a readable error.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Final

import httpx2

from order_contract import signing
from order_simulator.config import Settings
from order_simulator.observability import get_logger
from order_simulator.store import OrderStore

logger = get_logger(__name__)

LEASE: Final = timedelta(seconds=60)
"""How long one attempt owns a delivery before another may retry it."""

IDLE_INTERVAL: Final = 0.25
"""Seconds between sweeps when there is nothing to deliver.

Short, because the demo's whole claim is that an external change reaches PromisePatch within
seconds, and this is the only hop that a poll interval can lengthen.
"""

ACCEPTED_STATUSES: Final[frozenset[int]] = frozenset({200, 201, 202, 204, 409})
"""Answers that mean the receiver has the event.

``409`` is in the set on purpose: a receiver that says "I already have this one" has the event,
and retrying would be arguing with it. That is what makes at-least-once delivery converge
rather than loop.
"""


def backoff_seconds(attempts: int, *, maximum: float) -> float:
    """Exponential, capped. One second, two, four, ... and then the cap for as long as needed."""
    return min(float(2 ** min(attempts - 1, 16)), maximum)


class WebhookDispatcher:
    """One process's delivery loop over the durable delivery rows."""

    def __init__(self, store: OrderStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    async def deliver_one(self, client: httpx2.AsyncClient, *, now: datetime | None = None) -> bool:
        """Attempt at most one delivery. ``True`` if there was one to attempt."""
        moment = now or datetime.now(UTC)
        claim = await asyncio.to_thread(self.store.claim_delivery, now=moment, lease=LEASE)
        if claim is None:
            return False

        if not self.settings.webhook_url or self.settings.webhook_secret is None:
            await asyncio.to_thread(
                self.store.record_delivery_failure,
                claim.event_id,
                error="no webhook endpoint or secret is configured",
                retry_at=moment
                + timedelta(
                    seconds=backoff_seconds(
                        claim.attempts, maximum=self.settings.webhook_max_backoff_seconds
                    )
                ),
            )
            return True

        body = claim.body.encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            **signing.headers_for(
                secret=self.settings.require_webhook_secret(), body=body, now=moment
            ),
        }
        try:
            response = await client.post(
                self.settings.webhook_url,
                content=body,
                headers=headers,
                timeout=self.settings.webhook_timeout_seconds,
            )
            outcome: str | None = (
                None
                if response.status_code in ACCEPTED_STATUSES
                else f"the receiver answered {response.status_code}"
            )
        except httpx2.HTTPError as error:
            outcome = f"{type(error).__name__}: {error}"

        if outcome is None:
            await asyncio.to_thread(self.store.record_delivered, claim.event_id, now=moment)
            logger.info(
                "simulator.webhook.delivered",
                event_id=str(claim.event_id),
                delivery_attempt=claim.attempts,
                webhook_result="delivered",
            )
            return True

        retry_at = moment + timedelta(
            seconds=backoff_seconds(
                claim.attempts, maximum=self.settings.webhook_max_backoff_seconds
            )
        )
        await asyncio.to_thread(
            self.store.record_delivery_failure, claim.event_id, error=outcome, retry_at=retry_at
        )
        logger.warning(
            "simulator.webhook.retrying",
            event_id=str(claim.event_id),
            delivery_attempt=claim.attempts,
            webhook_result=outcome,
        )
        return True

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Sweep until asked to stop. Every failure is a row, so nothing is held here."""
        async with httpx2.AsyncClient() as client:
            while not stop.is_set():
                try:
                    busy = await self.deliver_one(client)
                except Exception as error:
                    logger.warning("simulator.webhook.loop_error", error=str(error))
                    busy = False
                if not busy:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=IDLE_INTERVAL)
                    except TimeoutError:
                        continue
