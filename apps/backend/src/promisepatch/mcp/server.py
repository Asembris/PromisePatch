"""The real MCP Streamable HTTP server: two tools, one envelope, no authority of its own.

Protocol revision **2025-11-25**, over Streamable HTTP at ``/mcp``, on the official Python SDK
pinned to an exact release. The revision is the thing being claimed, not the package: the SDK
also speaks a later era reached by a different entry point, and this server negotiates through
the ``initialize`` handshake, whose newest revision in the pinned release is 2025-11-25.
``tests/test_mcp_protocol.py`` asserts the revision rather than the version, so a bump that
moved the handshake default would fail rather than silently change what we serve.

**Stateless.** Every request builds its own transport and the server issues no session id.
Conversational continuity comes from the durable case, not from anything held here: a client
that disconnects, restarts or is replaced by a different client entirely asks ``status`` for
the case id and gets the current truth. That is also the AgentCore Runtime contract, so the
same process runs locally and hosted without a second code path. The cost is stated plainly:
there is no ``Last-Event-ID`` stream resumption, because there is no session to resume.

**Three checks before a tool exists.** DNS-rebinding protection rejects an unlisted ``Origin``
with ``403`` and an unlisted ``Host`` with ``421``; the bearer credential is checked before the
JSON-RPC layer sees a byte, so an unauthenticated caller cannot even discover the tool list.
Neither is a substitute for the domain's own checks, which run again on every intent regardless
of what this process believed.

**The surface is closed and it is not an authority.** Two tools in this slice. Neither takes an
actor, a timestamp, a version, a customer or a consent: the case engine resolves who is
speaking from its own configuration, and there is no argument here that a model could fill in
to become somebody else. What this process adds is a transport and a delegation; every rule
about who may do what still lives behind the intent API.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Final
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx2
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.applications import Starlette

from promisepatch import __version__
from promisepatch.config import Settings
from promisepatch.mcp.auth import BearerAuthMiddleware, require_principal
from promisepatch.mcp.engine import CaseEngine
from promisepatch.mcp.envelope import ToolCode, ToolRefusalError
from promisepatch.mcp.results import PromiseResult, ReportResult, StatusResult
from promisepatch.observability import get_logger

logger = get_logger(__name__)

PROTOCOL_REVISION: Final = "2025-11-25"
"""The revision this server is built to serve, asserted in the protocol tests."""

MCP_PATH: Final = "/mcp"

SERVER_NAME: Final = "promisepatch"

INSTRUCTIONS: Final = """\
PromisePatch turns one physical exception in a bakery -- a delivery that did not arrive, an \
ingredient that spoiled, an oven that is out -- into the customer promises it puts at risk, and \
recovers only the ones it is permitted to recover.

Use `report` to hand over what a worker said, in their own words. Do not tidy it, translate it \
or summarise it: the words are stored verbatim and the system reads them itself. `report` opens \
a case and concludes nothing; nothing about any order has changed when it returns.

Use `status` to read a case. It answers with sentences that were rendered from the durable case. \
Deliver them. Do not restate them in your own words, do not round "planned" up to "done", and \
do not describe an outcome the answer did not contain.

You cannot confirm a plan, record a customer's consent, choose who is speaking, or name a recipe \
version. Those are not tools you have not been given yet -- they are decisions this system does \
not accept from a conversation."""
"""What a model is told about this server. Deliberately about the boundary, not just the verbs."""

COMMAND_NAMESPACE: Final = uuid5(NAMESPACE_URL, "https://promisepatch.local/mcp/command")
"""The namespace a caller-supplied idempotency key is minted into.

Derived, so the same client asking twice with the same key reaches the same case rather than
opening a second one. Namespaced by the *authenticated* principal as well, so one client's key
can never land on another client's case: an idempotency key is a convenience, and a convenience
that could address somebody else's case would be an authority.
"""


def build_server(engine: CaseEngine) -> MCPServer:
    """The tool surface, bound to one case engine. No database, no provider, no clock."""
    server: MCPServer = MCPServer(
        name=SERVER_NAME,
        title="PromisePatch",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/Asembris/PromisePatch",
    )

    @server.tool(
        name="report",
        title="Report a physical exception",
        description=(
            "Hand over what a worker said about something physical that went wrong, in their "
            "own words and unedited. Opens a case and stores the statement; concludes nothing "
            "and changes nothing about any order."
        ),
    )
    async def report(
        text: Annotated[
            str,
            Field(
                description=(
                    "The worker's own sentence, verbatim. Stored exactly as sent, before "
                    "anything is concluded from it. Do not paraphrase, translate or shorten it."
                )
            ),
        ],
        client_request_id: Annotated[
            str | None,
            Field(
                description=(
                    "An optional idempotency key of your own. Sending the same key twice "
                    "reaches the same case instead of opening a second one; omit it and every "
                    "call opens a new case."
                )
            ),
        ] = None,
    ) -> ReportResult:
        principal = require_principal()
        if not text.strip():
            raise _refuse(
                ToolCode.INVALID_ARGUMENT, "a report needs something a worker actually said"
            )
        command_id = command_id_for(principal.client_id, client_request_id)
        correlation_id = uuid4()
        # `text` is forwarded untouched -- not stripped, not normalised, not case-folded. What
        # was said is evidence, and the first thing a transport does to evidence must be
        # nothing.
        body = await _call(
            engine.report(command_id=command_id, text=text, correlation_id=correlation_id)
        )
        logger.info(
            "mcp.tool.report",
            client=principal.client_id,
            case_id=body.get("case_id"),
            correlation_id=str(correlation_id),
        )
        return ReportResult(
            ok=True,
            intent="report",
            correlation_id=str(correlation_id),
            case_id=_text(body, "case_id"),
            state=_text(body, "state"),
            statement_id=_required(body, "statement_id"),
            created=bool(body.get("created", False)),
            attested_by=_required(body, "attested_by"),
            speech=(
                "Noted, and nothing has changed yet. I am working out which promises this affects."
            ),
        )

    @server.tool(
        name="status",
        title="Read a case",
        description=(
            "Read one case as it currently stands. Returns sentences rendered from the durable "
            "case: deliver them as given rather than restating them."
        ),
    )
    async def status(
        case_id: Annotated[
            str,
            Field(description="The case identifier a previous `report` returned."),
        ],
    ) -> StatusResult:
        principal = require_principal()
        try:
            case = UUID(case_id)
        except ValueError as error:
            raise _refuse(ToolCode.INVALID_ARGUMENT, "that is not a case identifier") from error
        correlation_id = uuid4()
        body = await _call(engine.status(case_id=case, correlation_id=correlation_id))
        logger.info(
            "mcp.tool.status",
            client=principal.client_id,
            case_id=case_id,
            correlation_id=str(correlation_id),
        )
        return StatusResult(
            ok=True,
            intent="status",
            correlation_id=str(correlation_id),
            case_id=_required(body, "case_id"),
            state=_text(body, "headline"),
            headline=_required(body, "headline"),
            speech=_required(body, "speech"),
            needs_owner_attention=bool(body.get("needs_owner_attention", False)),
            exception_category=_text(body, "exception_category"),
            threatened=_promises(body, "threatened"),
            untouched=_promises(body, "untouched"),
            untouched_count=int(body.get("untouched_count", 0)),
        )

    return server


def build_app(
    settings: Settings,
    *,
    engine: CaseEngine | None = None,
    http_client: httpx2.AsyncClient | None = None,
) -> Starlette:
    """The whole ``mcp`` entrypoint as one ASGI application.

    Assembled in this order for a reason: the bearer check is the outermost thing a request
    meets, so an unauthenticated caller never reaches the protocol, never sees a tool list and
    never learns whether an identifier it guessed is real.
    """
    resolved = engine or CaseEngine.from_settings(settings, client=http_client)
    app = build_server(resolved).streamable_http_app(
        streamable_http_path=MCP_PATH,
        json_response=settings.mcp_json_response,
        # Stateless: no session id is issued and none is honoured. Continuity is the durable
        # case's job, which is what makes a reconnect a new handshake rather than a recovery.
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(settings.mcp_allowed_host_list),
            allowed_origins=list(settings.mcp_allowed_origin_list),
        ),
    )
    app.add_middleware(BearerAuthMiddleware, token=settings.require_mcp_bearer_token())
    _close_engine_with(app, resolved)
    return app


def _close_engine_with(app: Starlette, engine: CaseEngine) -> None:
    """Release the engine's connection pool when the server stops, on the server's own loop.

    Composed onto the transport's lifespan rather than registered as a shutdown handler,
    because the SDK's application already owns a lifespan and Starlette ignores the event lists
    once one is set. Doing it here also puts the close on the loop that opened the pool, which
    is the loop uvicorn is running -- not whichever one happened to build the application.
    """
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(scope: Starlette) -> AsyncIterator[None]:
        async with inner(scope):
            try:
                yield
            finally:
                await engine.aclose()

    app.router.lifespan_context = lifespan


# ------------------------------------------------------------------------------- plumbing


async def _call(awaitable: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    """Await one engine call and turn its refusal into the SDK's tool-error shape.

    One place, so every tool refuses the same way. The 2025-11-25 guidance is that a tool
    *execution* failure is an ``isError`` result rather than a JSON-RPC protocol error: the
    model is meant to read it and say something sensible, which it cannot do with a transport
    fault it never sees.
    """
    try:
        return await awaitable
    except ToolRefusalError as refusal:
        raise ToolError(str(refusal)) from refusal


def command_id_for(client_id: str, client_request_id: str | None) -> UUID:
    """One command identity, derived from the caller's key or minted fresh.

    A derived id is namespaced by the authenticated principal, so a key is only ever a retry of
    *this* client's own call. Without a key every call is a new statement, which is the right
    default: two reports of the same wording minutes apart are usually two things that happened.
    """
    if not client_request_id:
        return uuid4()
    return uuid5(COMMAND_NAMESPACE, f"{client_id}|{client_request_id}")


def _refuse(code: ToolCode, message: str) -> ToolError:
    """A refusal the SDK will return as ``isError`` with the code in the first token."""
    return ToolError(f"{code.value}: {message}")


def _text(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    return None if value is None else str(value)


def _required(body: dict[str, Any], key: str) -> str:
    """A field the engine's answer must carry, or an unavailable answer.

    Read defensively on purpose. An envelope missing a field it promised is a system that did
    not answer the question, and reporting a blank where a case id belongs would put a hole in
    the evidence trail rather than a failure in the conversation.
    """
    value = body.get(key)
    if value is None:
        logger.error("mcp.engine.incomplete", field=key)
        raise _refuse(ToolCode.ENGINE_UNAVAILABLE, "the case engine's answer was incomplete")
    return str(value)


def _promises(body: dict[str, Any], key: str) -> tuple[PromiseResult, ...]:
    value = body.get(key)
    entries = value if isinstance(value, list) else []
    return tuple(PromiseResult.model_validate(item) for item in entries)
