"""``/api/conversation/simulated-alexa`` -- one worker turn over the real MCP endpoint (ADR-0028).

Labelled "Simulated Alexa+ via MCP" everywhere it surfaces, and never presented as Alexa+, an
Alexa skill or Amazon's agent. What is real is the browser's speech, PromisePatch's own
orchestrator choosing a verb with a model, and the authenticated MCP 2025-11-25 Streamable HTTP
endpoint it calls. This module composes those exactly as ``pp converse`` does and decides nothing
of its own: no phase, no permitted verb, no yes, no refusal sentence and no authorisation.

**Who may drive it.** A signed-in session with its CSRF token, whose worker *is*
``PP_SURFACE_WORKER_ID`` -- the identity MCP attributes every statement to anyway. Anybody else is
refused before a connection is opened, so the bridge lets a person reach over MCP only what that
same person can already do on ``/api/conversation/*``. An observer, the owner or another worker
gets nothing from it: neither escalation nor somebody else's name on their words.

**What it holds.** The MCP bearer token, server-side, presented as any client would. It is never
returned, logged or sent to the browser.

**What it remembers.** Nothing. Every request opens one MCP session, reads ``status(case_id)``,
builds the conversation from that reading alone and takes one turn. A failed read leaves the
conversation at ``UNDERSTANDING``, whose only verb is a read. The durable case is the continuity.

**What it cannot do.** Report: a conversation with a case is never in ``NO_CASE``, the only phase
that offers it. Create a plan approval: MCP ``confirm`` only spends one the worker recorded through
``/api/conversation/approve`` (ADR-0018). Reach a customer: consent stays on the signed link.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final
from uuid import UUID, uuid4

from fastapi import APIRouter

from promisepatch.api.auth.rate_limit import FixedWindowLimiter
from promisepatch.api.dependencies import CsrfPrincipalDep, SettingsDep, now
from promisepatch.api.errors import ApiError
from promisepatch.api.schemas.simulated_alexa import SimulatedAlexaReply, SimulatedAlexaTurn
from promisepatch.integrations import build_semantic_provider
from promisepatch.observability import get_logger
from promisepatch.orchestrator import Conversation, Orchestrator, ToolSurface, TurnResult
from promisepatch.orchestrator import connect as connect_mcp
from promisepatch.orchestrator.loop import _reading as reading_of

logger = get_logger(__name__)

router = APIRouter(prefix="/api/conversation", tags=["conversation"])

TURN_LIMIT: Final = 20
TURN_WINDOW: Final = timedelta(minutes=1)
"""Per worker. A turn costs a model call and up to three MCP round trips, each an intent call."""

_limiter: FixedWindowLimiter = FixedWindowLimiter(limit=TURN_LIMIT, window=TURN_WINDOW)

NOT_THE_SURFACE_WORKER = ApiError(
    status_code=403,
    code="NOT_THE_SURFACE_WORKER",
    message="only the worker MCP speaks for may use the simulated Alexa+ bridge",
)
NOT_CONFIGURED = ApiError(
    status_code=503,
    code="SIMULATED_ALEXA_NOT_CONFIGURED",
    message="this deployment has no MCP endpoint configured for the simulated Alexa+ bridge",
)
UNREACHABLE = ApiError(
    status_code=503,
    code="SIMULATED_ALEXA_UNAVAILABLE",
    message="the MCP endpoint could not be reached, so nothing was said to the case",
)
TOO_MANY_TURNS = ApiError(
    status_code=429,
    code="TOO_MANY_TURNS",
    message="too many simulated Alexa+ turns; wait a moment and try again",
)


@router.post(
    "/simulated-alexa",
    response_model=SimulatedAlexaReply,
    summary="Simulated Alexa+ via MCP: one reviewed turn to one existing case",
)
async def turn(
    body: SimulatedAlexaTurn,
    principal: CsrfPrincipalDep,
    settings: SettingsDep,
) -> SimulatedAlexaReply:
    """Read the case fresh over MCP, let the orchestrator take one turn, and say what is true."""
    surface_worker = settings.surface_worker_id
    if surface_worker is None or principal.worker_id != surface_worker:
        logger.info("simulated_alexa.refused", reason="not_surface_worker", role=principal.role)
        raise NOT_THE_SURFACE_WORKER
    url = settings.orchestrator_mcp_url
    if not url or settings.mcp_bearer_token is None:
        raise NOT_CONFIGURED
    if not _limiter.allow(principal.worker_id, now()):
        raise TOO_MANY_TURNS

    provider = build_semantic_provider(settings)
    result: TurnResult | None = None
    hydrated = False
    try:
        async with connect_mcp(
            url,
            token=settings.require_mcp_bearer_token(),
            timeout_seconds=settings.orchestrator_timeout_seconds,
        ) as surface:
            conversation, hydrated = await _hydrate(surface, body.case_id)
            result = await Orchestrator(provider=provider, surface=surface).take_turn(
                conversation, body.text, correlation_id=str(uuid4())
            )
    except Exception as error:
        # Deliberately everything, as at the orchestrator's own boundary. Before the turn ran,
        # nothing was said to the case and the honest answer is unavailability. After it ran, the
        # turn's own result is what happened, and a failure closing the session does not unsay it.
        logger.warning("simulated_alexa.mcp_failed", error=type(error).__name__)
        if result is None:
            raise UNREACHABLE from error

    assert result is not None
    logger.info(
        "simulated_alexa.turn",
        case_id=str(body.case_id),
        hydrated=hydrated,
        selected=result.selected.value if result.selected else None,
        calls=list(result.calls),
        phase=result.conversation.phase.value,
    )
    return SimulatedAlexaReply(
        case_id=body.case_id,
        reply=result.reply,
        phase=result.conversation.phase.value,
        hydrated=hydrated,
        selected=result.selected.value if result.selected else None,
        calls=list(result.calls),
        blocked=result.blocked.value if result.blocked else None,
        refusal=result.refusal.value if result.refusal else None,
    )


async def _hydrate(surface: ToolSurface, case_id: UUID) -> tuple[Conversation, bool]:
    """The conversation as one fresh ``status`` read renders it, or a read-only one.

    Outside ADR-0011's per-turn budget (ADR-0028 decision 12): the utterance does not cause it, it
    cannot change anything, and it narrows the turn to the server's own rendering of the case. A
    read that fails, or that describes some other case, leaves ``with_case`` alone --
    ``UNDERSTANDING``, whose only permitted verb is a read.
    """
    bare = Conversation().with_case(str(case_id))
    outcome = await surface.call("status", {"case_id": str(case_id)})
    reading = reading_of(outcome.body) if outcome.ok else None
    if reading is None or reading.case_id != str(case_id):
        return bare, False
    return bare.with_reading(reading), True
