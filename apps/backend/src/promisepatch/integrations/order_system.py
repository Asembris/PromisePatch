"""The HTTP boundary to the external order system. No database, by construction.

This module is the only thing in PromisePatch that speaks to the order system, and it is
deliberately unable to do anything else. It holds a base URL, a timeout and an HTTP client; it
imports no SQLAlchemy model, opens no connection and cannot be handed one. That is what makes
the rule underneath Proof A structural rather than remembered:

    an amendment leaves through here, and the mirror changes only when the order system
    says it did.

If this module could write ``order_lines``, PromisePatch would be quietly amending its own copy
of a customer's order and calling the result an integration. It cannot, so it isn't -- the
mirror moves in :mod:`promisepatch.domain.order_mirror` and nowhere else, on the strength of an
event or an authoritative read.

**Every call is made with no transaction open.** The dispatcher claims the outbox row, commits
that claim, and only then calls :meth:`OrderSystemAdapter.deliver`. A provider that hangs
therefore costs latency, not a held connection with its locks and its snapshot.

**The idempotency key is the row's, never this module's.** It is derived once from persisted
identity and stored on the outbox message, so every attempt after every crash presents the same
one. An adapter that generated its own would turn each retry into a second amendment.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final
from uuid import UUID

import httpx2
import pydantic

from order_contract.amendments import (
    DETERMINISTIC_REFUSALS,
    IDEMPOTENCY_HEADER,
    AmendmentCorrelation,
    AmendmentRequest,
    AmendmentResult,
    ErrorResponse,
)
from order_contract.events import OrderSnapshot
from promisepatch.config import Settings
from promisepatch.domain.model import EFFECT_ORDER_AMEND, DeliveryOutcome, DeliveryStatus
from promisepatch.observability import get_logger

logger = get_logger(__name__)

AMENDMENT_NOTE: Final = "Amended by PromisePatch — approved by customer, ref {reference}"
"""The note the order system records against the change, as the architecture words it.

It is what makes an operator looking at the order system afterwards able to see that the change
came from PromisePatch and why, without having to be told.
"""


class OrderSystemUnavailableError(RuntimeError):
    """The order system could not be reached or could not be understood."""


class OrderSystemClient:
    """A typed client for one external order system. Two calls, and nothing else.

    The client is constructed per worker rather than per call so the connection pool survives a
    dispatch cycle; it holds no state about any order.
    """

    def __init__(self, *, base_url: str, timeout: float, client: httpx2.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client or httpx2.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_order(self, external_order_id: str) -> OrderSnapshot:
        """The order system's own current state of one order.

        Used to repair a mirror that has fallen behind, which is the only situation in which
        PromisePatch asks rather than waits: an event stream with a hole in it cannot be applied
        safely, and the whole order can.
        """
        try:
            response = await self._client.get(
                f"{self.base_url}/orders/{external_order_id}", timeout=self.timeout
            )
        except httpx2.HTTPError as error:
            raise OrderSystemUnavailableError(f"{type(error).__name__}: {error}") from error
        if response.status_code != 200:
            raise OrderSystemUnavailableError(
                f"the order system answered {response.status_code} for {external_order_id}"
            )
        try:
            return OrderSnapshot.model_validate_json(response.content)
        except pydantic.ValidationError as error:
            raise OrderSystemUnavailableError(
                f"the order system's answer for {external_order_id} is not a readable order"
            ) from error

    async def amend(
        self, request: AmendmentRequest, *, idempotency_key: str
    ) -> tuple[AmendmentResult | None, DeliveryOutcome]:
        """Push one governed amendment, and say what came back.

        Three answers, and the difference between them is the whole retry story.

        *Applied.* The order system moved the order and says which version it is at now. The
        result is persisted, and the recovery waits for the mirror to catch up before it claims
        anything.

        *Refused, deterministically.* The order moved on, the item is unknown, the line is
        already elsewhere. Sending it again would produce the same answer, so it is terminal --
        and refusing to overwrite a newer external truth is exactly what optimistic concurrency
        is for.

        *Uncertain.* A timeout, a connection error, a server error. The order system may or may
        not have applied it, and there is no way to tell from here. The retry presents the same
        key and the order system decides whether that is one amendment or two.
        """
        try:
            response = await self._client.post(
                f"{self.base_url}/orders/{request.external_order_id}/amendments",
                content=request.model_dump_json(),
                headers={
                    "Content-Type": "application/json",
                    IDEMPOTENCY_HEADER: idempotency_key,
                },
                timeout=self.timeout,
            )
        except httpx2.HTTPError as error:
            return None, DeliveryOutcome(
                status=DeliveryStatus.RETRYABLE,
                error=f"the order system could not be reached: {type(error).__name__}",
            )

        if response.status_code == 200:
            try:
                result = AmendmentResult.model_validate_json(response.content)
            except pydantic.ValidationError as error:
                return None, DeliveryOutcome(
                    status=DeliveryStatus.TERMINAL,
                    error=f"the order system's answer is not a readable amendment result: {error}",
                )
            return result, DeliveryOutcome(
                status=DeliveryStatus.DELIVERED, provider_ref=result.provider_ref
            )

        code = _refusal_code(response.content)
        if code in DETERMINISTIC_REFUSALS:
            return None, DeliveryOutcome(
                status=DeliveryStatus.TERMINAL,
                error=f"the order system refused this amendment: {code}",
            )
        return None, DeliveryOutcome(
            status=DeliveryStatus.RETRYABLE,
            error=f"the order system answered {response.status_code}",
        )


def _refusal_code(body: bytes) -> str | None:
    """The contract code a refusal carries, or ``None`` when the body is not one."""
    try:
        return ErrorResponse.model_validate_json(body).error.code
    except pydantic.ValidationError:
        return None


class OrderSystemAdapter:
    """The effect adapter the outbox dispatcher calls for a recovery amendment.

    It conforms to the same contract the fake provider does -- one ``deliver`` call, one
    :class:`~promisepatch.domain.model.DeliveryOutcome` back -- so the recovery saga does not
    know or care which of them is configured. What it adds is a real system of record on the
    other end, and a result on the row saying what that system did.

    Anything it is asked to deliver that is not an order amendment is refused rather than
    guessed at. An adapter that quietly accepted an unfamiliar effect kind would report a
    success nobody performed.
    """

    def __init__(self, client: OrderSystemClient) -> None:
        self.client = client

    @classmethod
    def from_settings(cls, settings: Settings) -> OrderSystemAdapter:
        return cls(
            OrderSystemClient(
                base_url=settings.require_order_system_base_url(),
                timeout=settings.order_system_timeout_seconds,
            )
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def deliver(
        self, *, kind: str, payload: Mapping[str, Any], idempotency_key: str
    ) -> DeliveryOutcome:
        if kind != EFFECT_ORDER_AMEND:
            return DeliveryOutcome(
                status=DeliveryStatus.TERMINAL,
                error=f"the order system adapter cannot deliver a {kind!r} effect",
            )

        request = build_request(payload, reference=idempotency_key)
        result, outcome = await self.client.amend(request, idempotency_key=idempotency_key)
        logger.info(
            "worker.order_system.amended",
            external_order_id=request.external_order_id,
            expected_version=request.expected_version,
            idempotency_key=idempotency_key,
            status=outcome.status.value,
            external_version=None if result is None else result.external_version,
        )
        if result is None:
            return outcome
        # The authoritative outcome travels back on the row. It is what turns "the provider
        # accepted the call" into "the order is at version N with this variant on this line",
        # which is the thing the mirror is later required to agree with before a recovery may
        # call itself complete.
        return DeliveryOutcome(
            status=outcome.status,
            provider_ref=outcome.provider_ref,
            result=result.model_dump(mode="json"),
        )


def build_request(payload: Mapping[str, Any], *, reference: str) -> AmendmentRequest:
    """Turn the persisted effect payload into the typed amendment, copying nothing new in.

    Every field is read off the outbox row, which was written by the transaction that chose the
    option. Nothing here selects an option, computes a version or decides what to change: doing
    any of that at dispatch time would mean the amendment finally sent was not the one the plan
    was confirmed for.
    """
    return AmendmentRequest(
        external_order_id=str(payload["order_external_id"]),
        expected_version=int(payload["order_external_version"]),
        external_line_id=str(payload["order_line_id"]),
        from_item_id=str(payload["from_version_id"]),
        to_item_id=str(payload["to_version_id"]),
        note=AMENDMENT_NOTE.format(reference=reference),
        correlation=AmendmentCorrelation(
            case_id=UUID(str(payload["case_id"])),
            track_id=UUID(str(payload["track_id"])),
            option_id=UUID(str(payload["option_id"])),
        ),
    )
