"""Who is calling the MCP endpoint, decided before the protocol sees a byte.

Two separate jobs, deliberately not merged with the tool code.

**Authentication is a transport concern.** A request with no credential is answered ``401``
before it reaches the JSON-RPC layer, so an unauthenticated caller never learns which tools
exist, what their schemas are, or whether a case id is real. It is a plain ASGI middleware
rather than a Starlette ``BaseHTTPMiddleware`` because the latter runs the application in a
task of its own, and this one has to leave something behind in the *calling* task's context.

**Identity is not a tool argument, and there is nowhere for it to be one.** The authenticated
principal is published in a :class:`~contextvars.ContextVar` that the middleware sets before it
calls downstream, so a tool handler reads it out of the request's own context. The MCP session
manager spawns its per-request server task from inside that call, and a task inherits the
context it was spawned in, so the value a tool reads belongs to the request that authenticated
it and to no other.

The stateless Streamable HTTP transport carries no request headers into a tool's context at
all -- that is exactly why the value has to travel this way rather than being re-derived from a
header inside the tool. :func:`require_principal` therefore **fails closed**: a tool that finds
no principal refuses, rather than falling back to anything a caller could have supplied.

The static bearer token is the local and self-hosted credential. A deployment behind AgentCore
Runtime replaces it with SigV4 at the edge; that changes the credential and nothing about the
rule above.
"""

from __future__ import annotations

import hashlib
import hmac
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Final

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from promisepatch.mcp.envelope import ToolCode, ToolRefusalError
from promisepatch.observability import get_logger

logger = get_logger(__name__)

REALM: Final = "promisepatch-mcp"
BEARER_PREFIX: Final = "bearer "


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller of one MCP request.

    ``client_id`` is a digest of the credential rather than the credential, so a log line can
    say which client called without a log line becoming somewhere the token is kept.
    """

    client_id: str

    @classmethod
    def of(cls, token: str) -> Principal:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
        return cls(client_id=f"bearer:{digest}")


_PRINCIPAL: ContextVar[Principal | None] = ContextVar("promisepatch_mcp_principal", default=None)


def current_principal() -> Principal | None:
    """The caller of the request being served, or ``None`` outside one."""
    return _PRINCIPAL.get()


def require_principal() -> Principal:
    """The caller, or a refusal. There is no third answer and no default identity.

    Reached only if the middleware was somehow bypassed -- a misassembled application, a tool
    invoked outside a request. Both are bugs, and the safe behaviour for both is to refuse: an
    intake attributed to nobody is a physical claim with no attestor.
    """
    principal = _PRINCIPAL.get()
    if principal is None:
        logger.error("mcp.principal.absent")
        raise ToolRefusalError(
            ToolCode.UNAUTHORIZED_SURFACE,
            "this call arrived without an authenticated surface",
        )
    return principal


class BearerAuthMiddleware:
    """Refuse every request that does not present the configured bearer token.

    One rejection for absent, malformed and wrong alike: a caller has no legitimate use for the
    difference, and distinguishing them tells a guesser which half they got right. The
    ``WWW-Authenticate`` challenge is the standard one, so an ordinary HTTP client knows what
    kind of credential to offer without our inventing a scheme.
    """

    def __init__(self, app: ASGIApp, *, token: str) -> None:
        self.app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        presented = _bearer(Headers(scope=scope).get("authorization"))
        if presented is None or not hmac.compare_digest(presented, self._token):
            logger.warning("mcp.auth.rejected", path=scope.get("path"))
            response = PlainTextResponse(
                "Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": f'Bearer realm="{REALM}"'},
            )
            await response(scope, receive, send)
            return
        # Set on the request's own context, before the application is entered. The session
        # manager starts its per-request server task from inside this call, so that task
        # inherits this value; concurrent requests each carry their own.
        token = _PRINCIPAL.set(Principal.of(presented))
        try:
            await self.app(scope, receive, send)
        finally:
            _PRINCIPAL.reset(token)


def _bearer(header: str | None) -> str | None:
    """The credential out of an ``Authorization`` header, or ``None`` if there is not one."""
    if not header or not header.lower().startswith(BEARER_PREFIX):
        return None
    value = header[len(BEARER_PREFIX) :].strip()
    return value or None
