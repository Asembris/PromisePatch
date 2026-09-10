"""The MCP process's only way to reach a case: HTTP to the internal intent API.

This module is the reason the boundary is real rather than a naming convention. The MCP server
cannot import :mod:`promisepatch.domain` or :mod:`promisepatch.db` -- an import-linter contract
forbids it -- so there is no shortcut by which a tool could open a transaction, read a row or
call a domain service directly. It sends an authenticated request to another process and
believes what comes back, exactly as an unrelated client would.

Two things travel with every call and neither is a tool argument. The **service token** proves
which process is asking. The **correlation id** is minted here, per call, and returned in the
tool's envelope, so the durable audit and event rows the intent causes can be found from the
conversation that caused them.

Failure has one shape. A refused intent becomes a
:class:`~promisepatch.mcp.envelope.ToolRefusalError` carrying a stable code; an engine that
could not be reached, answered too slowly, or answered something this client cannot read
becomes ``ENGINE_UNAVAILABLE``. None of them becomes a
plausible-looking answer, because a conversation that fills that silence with a guess is the
failure this product's semantic boundary exists to prevent.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

import httpx2

from promisepatch.config import Settings
from promisepatch.mcp.envelope import ToolCode, ToolRefusalError
from promisepatch.observability import get_logger

logger = get_logger(__name__)

SERVICE_TOKEN_HEADER: Final = "X-Service-Token"
CORRELATION_HEADER: Final = "X-Correlation-ID"

STATUS_CODES: Final[dict[int, ToolCode]] = {
    400: ToolCode.INVALID_ARGUMENT,
    401: ToolCode.UNAUTHORIZED_SURFACE,
    403: ToolCode.UNAUTHORIZED_SURFACE,
    404: ToolCode.UNKNOWN_RESOURCE,
    409: ToolCode.CASE_NOT_IN_STATE,
    422: ToolCode.INVALID_ARGUMENT,
}
"""How the intent API's answers become the tool vocabulary. Anything else is unavailability.

Mapping the unlisted codes to ``ENGINE_UNAVAILABLE`` rather than to a nearest-fit refusal is
deliberate: a client told "invalid argument" will rephrase and try again, and a client told the
engine is unavailable will say so. An unknown 5xx deserves the second answer.
"""

REFUSAL_MESSAGES: Final[dict[ToolCode, str]] = {
    ToolCode.INVALID_ARGUMENT: "the case engine would not accept that request",
    ToolCode.UNAUTHORIZED_SURFACE: "this surface is not permitted to do that",
    ToolCode.UNKNOWN_RESOURCE: "nothing by that identity exists",
    ToolCode.CASE_NOT_IN_STATE: "that case is not in a state where this means anything",
    ToolCode.ENGINE_UNAVAILABLE: "the case engine could not be reached",
}
"""One sentence per code, written here rather than forwarded from the engine.

The intent API's own message is for an operator reading a log. Passing it through to a model
would make our internal wording part of a public contract, and would eventually leak a detail
somebody added to a message for a colleague.
"""


class CaseEngine:
    """A thin, authenticated client for ``/internal/intents``. Holds no state about a case."""

    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout = timeout_seconds
        # Injectable so a test can drive the real intent application in-process rather than
        # over a socket. The credential, the headers and the failure mapping are the same
        # either way -- only the transport underneath changes.
        #
        # A client this object opens for itself is opened on first use rather than here. An
        # async connection pool belongs to the event loop that drives it, and a server is
        # routinely *built* on one loop and *run* on another -- a factory called before
        # startup, a test that assembles an application and then serves it. Constructing the
        # pool at first request puts it on the loop that will actually use it.
        self._client = client
        self._owns_client = client is None

    @classmethod
    def from_settings(
        cls, settings: Settings, *, client: httpx2.AsyncClient | None = None
    ) -> CaseEngine:
        return cls(
            base_url=settings.require_mcp_intent_api_base_url(),
            service_token=settings.require_internal_service_token(),
            timeout_seconds=settings.mcp_intent_timeout_seconds,
            client=client,
        )

    async def aclose(self) -> None:
        """Release the connection pool, when this object opened one and ever used it."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx2.AsyncClient:
        if self._client is None:
            self._client = httpx2.AsyncClient(timeout=self._timeout)
        return self._client

    async def report(self, *, command_id: UUID, text: str, correlation_id: UUID) -> dict[str, Any]:
        """Open a case for one spoken exception. The text travels exactly as it was given."""
        return await self._post(
            "/internal/intents/report",
            {"command_id": str(command_id), "text": text},
            correlation_id=correlation_id,
        )

    async def status(self, *, case_id: UUID, correlation_id: UUID) -> dict[str, Any]:
        """Read one case as it currently stands, already projected and already rendered."""
        return await self._post(
            "/internal/intents/status",
            {"case_id": str(case_id)},
            correlation_id=correlation_id,
        )

    async def _post(
        self, path: str, payload: dict[str, Any], *, correlation_id: UUID
    ) -> dict[str, Any]:
        try:
            response = await self._http().post(
                f"{self._base_url}{path}",
                json=payload,
                headers={
                    SERVICE_TOKEN_HEADER: self._service_token,
                    CORRELATION_HEADER: str(correlation_id),
                },
                timeout=self._timeout,
            )
        except httpx2.HTTPError as error:
            # Reached nobody, or nobody in time. Not a reading of anything.
            logger.warning("mcp.engine.unreachable", path=path, error=type(error).__name__)
            raise _refuse(ToolCode.ENGINE_UNAVAILABLE) from error

        if response.status_code >= 400:
            code = STATUS_CODES.get(response.status_code, ToolCode.ENGINE_UNAVAILABLE)
            logger.warning("mcp.engine.refused", path=path, status=response.status_code, code=code)
            raise _refuse(code)

        try:
            body = response.json()
        except ValueError as error:
            logger.error("mcp.engine.unreadable", path=path, status=response.status_code)
            raise _refuse(ToolCode.ENGINE_UNAVAILABLE) from error
        if not isinstance(body, dict):
            # An envelope of the wrong shape is an unavailable answer, not a partial one. The
            # same rule the Bedrock adapter learned in P4.9: read every level as untrusted.
            logger.error("mcp.engine.unshaped", path=path, kind=type(body).__name__)
            raise _refuse(ToolCode.ENGINE_UNAVAILABLE)
        return body


def _refuse(code: ToolCode) -> ToolRefusalError:
    return ToolRefusalError(code, REFUSAL_MESSAGES[code])
