"""The customer approval surface: read one question, answer it once, decide nothing.

The only endpoints in PromisePatch that serve somebody it cannot authenticate, and every line
of this module is shaped by that. What the caller presents is a signed link, and a signed link
proves that whoever holds it was given it. That is possession. It is not identity, it is not a
person, and nothing here may treat it as either.

**It is not ``/api/conversation/approve``.** That endpoint is a *worker* agreeing to a
PromisePatch plan, behind a session, a role and a CSRF token, and it spends a durable human
approval recorded where a person was authenticated. This one is a *customer* answering a
question about their own order. The two are different authorities over different things, and
the system has kept them apart in separate tables, separate parsers and separate vocabulary
since §15. Nothing in this module reaches the plan side, and nothing on the plan side reaches
here.

**This is a transport, not a second consent protocol.** The answer is written where a customer
channel writes one -- an ``inbox_events`` row of source ``customer-reply`` -- and everything
after that is the protocol that already existed: the worker binds it to a request, checks the
sender against the channel the request was sent to, checks the request is still open, checks
the deadline against the *database's* clock, and only then hands the text to the literal
parser. This module runs none of those checks in order to *grant* anything. It re-reads some of
them to decide what to draw, which is a different job with no authority in it.

**The channel is server-derived, always.** It is read out of the link's signature, never out of
the request body, and there is no field in :class:`CustomerAnswerRequest` that could carry one.
A worker, an owner, an MCP client or a model holding this endpoint's address can therefore
answer for a customer exactly as far as they can forge an HMAC, and no further -- and if they
somehow hold a link minted for another channel, the reply they write is recorded by the
consent protocol as an unauthorised one and put on the owner's desk.

**One answer per link.** The record's id is derived from the request and the channel and *not*
from the answer, so a second press -- of either button -- proposes an id the database already
holds and writes nothing. A decline cannot be pressed into an approval; the unique index says
so, rather than a branch somebody has to remember.

**It commits before it answers.** Like the order system's ingress and for the same reason: the
response says the answer is stored, and a promise of durability is made only once it is true.

**What it deliberately does not do.** It does not run the worker, so the page can truthfully say
"we have your answer" and not "approved" -- the decision is a row the protocol writes under its
own lock and its own audit, and a transport that reported one it had not seen would be
inventing the only thing in this system that may never be invented.
"""

from __future__ import annotations

import json
from typing import Annotated, Final

from fastapi import APIRouter, Path, Response

from promisepatch.api.dependencies import DatabaseDep, SettingsDep
from promisepatch.api.errors import ApiError
from promisepatch.api.schemas.customer import (
    CustomerAnswer,
    CustomerAnswerRequest,
    CustomerApprovalResponse,
)
from promisepatch.api.views import customer as view
from promisepatch.domain import approvals, consent, customer_link, handlers, inbox
from promisepatch.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/customer", tags=["customer"])

TokenPath = Annotated[str, Path(max_length=customer_link.MAX_TOKEN_CHARACTERS)]
"""Bounded in the route signature, so an oversized link is refused before a handler runs."""

UNCONFIGURED = ApiError(
    status_code=503,
    code="CUSTOMER_LINKS_NOT_CONFIGURED",
    message="this process mints no customer approval links",
)
"""No secret, no surface. A deployment that signs nothing verifies nothing, and saying so is
better than a 404 that would imply the link was merely wrong."""

BAD_LINK = ApiError(
    status_code=404,
    code="LINK_NOT_FOUND",
    message="this link does not open an approval request",
)
"""One answer for forged, malformed, expired-format and never-existed alike.

The holder of a bad link has no legitimate use for the difference, and telling them apart is
telling a forger which half to fix.
"""

ANSWER_TEXT: Final[dict[CustomerAnswer, str]] = {
    CustomerAnswer.APPROVE: consent.APPROVE_TOKEN,
    CustomerAnswer.DECLINE: consent.DECLINE_TOKEN,
}
"""Which word each button writes onto the customer's channel.

The two words the message invited and the two the literal parser reads -- taken from the parser
itself, so a page cannot drift into sending a synonym the protocol would refuse. Composed here
and never taken from the request body: a transport that forwarded text would be a way to put a
sentence in front of the parser, and the parser's whole value is that it is never asked to
interpret one.

Writing the word is not deciding anything. The row this produces is read later, under the case
lock, by code that will check the sender, the state and the deadline before the parser ever
sees it.
"""


@router.get(
    "/approval/{token}",
    response_model=CustomerApprovalResponse,
    summary="Read the approval request one signed link opens",
)
async def read_approval(
    token: TokenPath, settings: SettingsDep, database: DatabaseDep
) -> CustomerApprovalResponse:
    """What this link opens, or the closed view. Nothing is written and nothing is decided.

    The connection is opened *after* the link verifies, rather than by a request dependency, for
    the reason the order system's ingress verifies before it parses: opening a transaction is
    work, the pool it comes out of is small, and an unauthenticated caller must not be able to
    demand either by sending a string.
    """
    possession = _possession(token, settings)
    async with database.connect() as connection:
        reading = await view.read(
            connection, request_id=possession.request_id, channel=possession.channel
        )
    return _rendered(reading)


@router.post(
    "/approval/{token}",
    response_model=CustomerApprovalResponse,
    summary="Answer the approval request one signed link opens",
)
async def answer_approval(
    token: TokenPath,
    body: CustomerAnswerRequest,
    response: Response,
    settings: SettingsDep,
    database: DatabaseDep,
) -> CustomerApprovalResponse:
    """Store one answer on the customer's channel, and report what is now true.

    The answer is written whatever the page last showed, and that is deliberate: the page is a
    reading of rows that may have moved, and a transport that refused to record an answer
    because its own last reading looked closed would be deciding, on stale information, that
    somebody had not spoken. Recording is cheap and honest; what the answer *authorises* is
    decided afterwards by the protocol, against rows held under a lock.

    The one thing refused here is an answer whose link does not verify, because that is not an
    answer from anybody.
    """
    possession = _possession(token, settings)
    message_id = approvals.link_message_id(possession.request_id, possession.channel)

    # A transaction of this handler's own, committed before the response is built. The shared
    # request-scoped one is torn down *after* the response, which is right for a read and wrong
    # for a promise about durability: this answer tells a customer their answer is kept.
    async with database.begin() as connection:
        stored = await inbox.ingest(
            connection,
            source=handlers.CUSTOMER_REPLY_SOURCE,
            provider_event_id=message_id,
            body=_reply_body(
                request_id=str(possession.request_id),
                channel=possession.channel,
                text=ANSWER_TEXT[body.answer],
                message_id=message_id,
            ),
            headers={"transport": "customer-link"},
        )

    async with database.connect() as connection:
        reading = await view.read(
            connection, request_id=possession.request_id, channel=possession.channel
        )

    # A second press is a success and says so, exactly as a redelivered order event does.
    # Answering an error would teach a page to retry an answer that is already kept.
    response.status_code = 202 if stored is not None else 200
    logger.info(
        "api.customer_approval.answered",
        request_id=str(possession.request_id),
        stored=stored is not None,
        phase=reading.phase,
    )
    return _rendered(reading)


def _possession(token: str, settings: SettingsDep) -> customer_link.Possession:
    """Read the link, or refuse. The only authentication this surface has.

    The reason for a rejection stays in this process. It is exactly the information somebody
    writing their own link would want back.
    """
    if settings.customer_link_secret is None:
        raise UNCONFIGURED
    try:
        return customer_link.verify(secret=settings.require_customer_link_secret(), token=token)
    except customer_link.LinkError as failure:
        logger.warning("api.customer_approval.rejected", reason=failure.reason)
        raise BAD_LINK from failure


def _reply_body(*, request_id: str, channel: str, text: str, message_id: str) -> str:
    """The stored record, in the shape every customer reply is stored in.

    ``sender`` is the channel the *link* was minted for, reported as what this transport
    observed. It is not a claim of authority and is not trusted as one: the step that reads this
    row compares it against the channel the request was actually sent to, and that comparison is
    the only thing in PromisePatch that can refuse a reply because of who sent it.
    """
    return json.dumps(
        {
            "request_id": request_id,
            "sender": channel,
            "text": text,
            "provider_message_id": message_id,
        }
    )


def _rendered(reading: view.CustomerApprovalView) -> CustomerApprovalResponse:
    """The view as the wire carries it, with ``answerable`` decided on this side of it."""
    return CustomerApprovalResponse(
        phase=reading.phase,
        answerable=reading.phase in view.ANSWERABLE,
        customer_name=reading.customer_name,
        order_reference=reading.order_reference,
        option_code=reading.option_code,
        due_at=reading.due_at,
        answer_by=reading.answer_by,
        from_product=reading.from_product,
        to_product=reading.to_product,
        affected_resource=reading.affected_resource,
        substitute_resource=reading.substitute_resource,
        outcome=reading.outcome,
        answered_at=reading.answered_at,
        awaiting_outcome=reading.awaiting_outcome,
    )
