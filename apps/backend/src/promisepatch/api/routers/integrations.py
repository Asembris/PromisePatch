"""``POST /api/integrations/order-system/events`` -- the external order system's ingress.

The one endpoint in this application that no browser calls, and it is built accordingly.

**It authenticates a service, not a person.** There is no session cookie and no CSRF token: the
caller is another server, it holds neither, and a cookie it did hold would make every delivery a
cross-site request. What it presents instead is an HMAC over the exact bytes it sent and the
timestamp it sent them at, and the secret is shared out of band.

**It verifies before it parses.** The signature covers raw bytes, so re-serialising the payload
to check it would be checking something else; and parsing untrusted input is work an
unauthenticated caller must not be able to demand. The order is therefore: size, signature,
then schema.

**It answers only once the delivery is durable.** The record is written and committed in a
transaction of the handler's own, before the response is built, because ``202`` tells the sender
it may stop retrying. Everywhere else in this application a request-scoped transaction commits
after the response, which is right for a read and wrong for a promise about durability.

**It changes no business state.** The handler stores the delivery in ``inbox_events`` and
answers. Whether that event moves a mirrored order is decided later, by the worker, under its
own lock and its own audit -- so HTTP transport and business-state mutation stay two different
things, and a delivery that arrives while the database is busy is durable rather than lost.

**A redelivery is a success.** ``(source, provider_event_id)`` is unique, so the tenth delivery
of one event stores nothing and is answered ``202`` exactly like the first. Answering an error
would make a correct sender retry for ever.

**Rejections say nothing.** A caller that cannot sign has no legitimate need to know whether the
timestamp, the signature or the body was the problem, and telling them would be telling them how
to get it right next time.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Response
from starlette.requests import Request

from order_contract import signing
from order_contract.events import OrderEvent
from promisepatch.api.dependencies import DatabaseDep, SettingsDep
from promisepatch.api.errors import ApiError
from promisepatch.api.schemas.integrations import OrderEventAccepted
from promisepatch.domain import inbox
from promisepatch.domain.order_mirror import ORDER_SYSTEM_SOURCE
from promisepatch.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

REJECTED = ApiError(
    status_code=401,
    code="SIGNATURE_INVALID",
    message="this delivery is not signed by the configured order system",
)
"""One rejection for missing, expired, forged and tampered alike.

The reason is logged for us and withheld from the caller, for the same reason an unauthenticated
login failure does not say which half was wrong.
"""

UNCONFIGURED = ApiError(
    status_code=503,
    code="ORDER_SYSTEM_NOT_CONFIGURED",
    message="this process has no order-system webhook secret configured",
)
"""No secret, no acceptance. An endpoint that took unsigned deliveries would take them from
anyone, and defaulting a secret would mean every copy of this repository shared one."""


@router.post(
    "/order-system/events",
    response_model=OrderEventAccepted,
    status_code=202,
    summary="Ingest one signed order-system event",
)
async def order_system_event(
    request: Request,
    response: Response,
    settings: SettingsDep,
    database: DatabaseDep,
    signature: Annotated[str | None, Header(alias=signing.SIGNATURE_HEADER)] = None,
    timestamp: Annotated[str | None, Header(alias=signing.TIMESTAMP_HEADER)] = None,
) -> OrderEventAccepted:
    """Store one delivery, and answer. Nothing about an order changes in this request."""
    if settings.order_system_webhook_secret is None:
        raise UNCONFIGURED

    body = await request.body()
    try:
        signing.verify(
            secret=settings.require_order_system_webhook_secret(),
            body=body,
            timestamp=timestamp,
            signature=signature,
        )
    except signing.SignatureError as failure:
        # The reason stays here. It is exactly the information a forger would want.
        logger.warning("api.order_system.rejected", reason=failure.reason)
        raise REJECTED from failure

    event_id = _event_identity(body)
    # A transaction of this handler's own, committed before the answer is written. The shared
    # request-scoped one is torn down *after* the response, which is right for a read and wrong
    # here: answering ``202`` is a promise that the delivery is durable, and a sender that is
    # told so stops retrying. The window between the two is small and the loss it would cause
    # is permanent, so the promise is made only once it is true.
    async with database.begin() as connection:
        stored = await inbox.ingest(
            connection,
            source=ORDER_SYSTEM_SOURCE,
            provider_event_id=str(event_id),
            body=body.decode("utf-8"),
            headers={"content-type": request.headers.get("content-type", "")},
        )
    # A redelivery is a success, and saying so is what stops a correct sender retrying for ever.
    response.status_code = 202 if stored is not None else 200
    logger.info(
        "api.order_system.ingested",
        event_id=str(event_id),
        inbox_id=None if stored is None else str(stored),
        duplicate=stored is None,
    )
    return OrderEventAccepted(
        accepted=True, event_id=event_id, duplicate=stored is None, inbox_event_id=stored
    )


def _event_identity(body: bytes) -> UUID:
    """The sender's own id for this change, read out of a body whose signature already held.

    Only the identity is read here. Whether the rest of the event is applicable -- the schema
    version, the type, the order it names -- is a question for the worker, from the stored row,
    because answering it in the request path would make the endpoint's behaviour depend on
    business state it has no lock on.
    """
    try:
        return OrderEvent.model_validate_json(body).event_id
    except ValueError as error:
        raise ApiError(
            status_code=422,
            code="ORDER_EVENT_UNREADABLE",
            message="the delivery is signed but is not a readable order event",
        ) from error
