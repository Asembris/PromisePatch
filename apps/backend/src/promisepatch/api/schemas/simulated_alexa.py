"""One simulated Alexa+ turn on the wire (ADR-0028): a case and the reviewed words, nothing else.

There is no actor, no plan identity, no tool name, no clock and no reason. The actor is the session
behind the cookie, the plan identity is whatever a fresh ``status`` read returns, and the verb is
chosen by the orchestrator from the list the case's own state permits. ``extra="forbid"`` makes an
attempt to send any of them a ``422`` rather than a value quietly ignored.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from promisepatch.semantic.contracts import MAX_UNTRUSTED_CHARACTERS


class SimulatedAlexaTurn(BaseModel):
    """What the worker said to an existing case, after reviewing the transcript."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: UUID
    text: str = Field(min_length=1, max_length=MAX_UNTRUSTED_CHARACTERS)


class SimulatedAlexaReply(BaseModel):
    """What the turn did, in the server's own words.

    ``reply`` is the orchestrator's reply: the server-rendered speech plus at most one sentence of
    accepted glue. ``calls`` are the MCP tool calls the turn made, in order, not counting the
    hydration read that preceded it; ``hydrated`` says whether that read succeeded. ``blocked``
    and ``refusal`` say why nothing was done, when nothing was: a turn the orchestrator stopped, or
    a tool call the MCP surface refused.
    """

    model_config = ConfigDict(frozen=True)

    case_id: UUID
    reply: str
    phase: str
    hydrated: bool
    selected: str | None
    calls: list[str]
    blocked: str | None
    refusal: str | None
