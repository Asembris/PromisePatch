"""An answer that was kept although its response never arrived.

The customer surface commits a pressed answer **before** it builds the response. So the one thing
a page cannot infer from a failed request is that nothing was recorded: the connection can drop,
or a proxy can give up, after the commit. What the page must do instead is read the same request
again and say what that reading says -- and the server must make a second press, of either
button, harmless.

These tests take the failure out of the page and put it on the wire. A transport forwards the
press to the real application, lets it commit, and then raises instead of returning its answer.
Everything the customer does next goes through the same signed link.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx2
import pytest
import pytest_asyncio
from _intake_support import TOMAS_CHANNEL, Intake
from _intake_support import physical as physical
from test_customer_approval_link import BASE, Customer, _served, link_for, the_request, waiting_case

from promisepatch.api.views.customer import Phase
from promisepatch.db.models import InboxEvent
from promisepatch.domain import consent, handlers

pytestmark = pytest.mark.integration


class LosesTheAnswer(httpx2.AsyncBaseTransport):
    """Delivers every request, and loses the response to a POST after the server has handled it."""

    def __init__(self, inner: httpx2.AsyncBaseTransport) -> None:
        self.inner = inner
        self.lost = 0

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        response = await self.inner.handle_async_request(request)
        if request.method == "POST":
            await response.aread()
            self.lost += 1
            raise httpx2.ReadError(
                "the connection dropped after the server answered", request=request
            )
        return response


async def kept_answers(intake: Intake) -> list[str]:
    """The answers the customer surface has stored, before any worker has read them."""
    return [
        json.loads(row.raw_body)["text"]
        for row in await intake.rows_of(InboxEvent)
        if row.source == handlers.CUSTOMER_REPLY_SOURCE
    ]


@pytest_asyncio.fixture
async def lossy(physical: Intake) -> AsyncIterator[tuple[Customer, LosesTheAnswer]]:
    transport = LosesTheAnswer(httpx2.ASGITransport(app=_served(physical.database)))
    async with httpx2.AsyncClient(transport=transport, base_url=BASE) as client:
        yield Customer(client), transport


async def test_an_answer_whose_response_was_lost_is_kept_and_read_back(
    physical: Intake, lossy: tuple[Customer, LosesTheAnswer]
) -> None:
    """The press committed; the customer never heard. A re-read of the same link says so."""
    customer, transport = lossy
    await waiting_case(physical)
    token = link_for(await the_request(physical))

    with pytest.raises(httpx2.ReadError):
        await customer.press(token, "APPROVE")
    assert transport.lost == 1
    assert await kept_answers(physical) == [consent.APPROVE_TOKEN]

    reading = (await customer.open(token)).json()
    assert reading["phase"] == Phase.RECEIVED
    assert reading["answerable"] is False


async def test_a_second_answer_after_a_lost_response_does_not_overwrite_the_first(
    physical: Intake, lossy: tuple[Customer, LosesTheAnswer]
) -> None:
    """The customer, told nothing, presses the other button. The kept yes stands.

    Pressed before and after the worker has read the first answer, so both windows are covered:
    the stored reply that has not yet become a decision, and the decision itself.
    """
    customer, _ = lossy
    await waiting_case(physical)
    token = link_for(await the_request(physical))

    with pytest.raises(httpx2.ReadError):
        await customer.press(token, "APPROVE")
    with pytest.raises(httpx2.ReadError):
        await customer.press(token, "DECLINE")
    assert await kept_answers(physical) == [consent.APPROVE_TOKEN]

    await physical.drain_until_decided()
    with pytest.raises(httpx2.ReadError):
        await customer.press(token, "DECLINE")
    await physical.drain(limit=30)

    assert await kept_answers(physical) == [consent.APPROVE_TOKEN]
    [reply] = await physical.replies()
    assert reply.sender_identity == TOMAS_CHANNEL
    [decision] = await physical.decisions()
    assert decision.decision == "APPROVE"
    assert (await customer.open(token)).json()["phase"] in {Phase.APPROVED, Phase.RECEIVED}
