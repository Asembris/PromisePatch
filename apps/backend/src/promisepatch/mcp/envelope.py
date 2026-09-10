"""The one shape every tool answers in, and the closed list of ways one can refuse.

A conversational client has to be able to act on an answer without parsing prose, and a model
has to be able to *verbalise a refusal* without guessing what went wrong. So every result is
the same envelope -- ``ok``, which intent it was, the case it concerns, the state that case is
in, the payload, any warnings, and the correlation id that ties the call to durable evidence --
and every failure carries one of a fixed set of codes.

The codes are the frozen set from the architecture's MCP section. They say what kind of thing
went wrong, never what the engine's internals look like: a tool refusal is the easiest place in
a system to hand an attacker a schema, and "the engine could not be reached" is all a caller
is owed.

Nothing in this module decides anything. It is the vocabulary a decision made elsewhere is
reported in.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field


class ToolCode(StrEnum):
    """Why a tool call did not do what was asked. Closed, and stable across releases."""

    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    """The words were not something this surface can act on at all."""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    """The call was well formed as JSON and wrong as a request."""

    UNKNOWN_RESOURCE = "UNKNOWN_RESOURCE"
    """Nothing by that identity exists -- a case, a promise, an order."""

    CASE_NOT_IN_STATE = "CASE_NOT_IN_STATE"
    """The case exists and these words do not mean anything to it where it currently is."""

    UNAUTHORIZED_SURFACE = "UNAUTHORIZED_SURFACE"
    """This surface may not do that. Never a hint about what would have been allowed."""

    ENGINE_UNAVAILABLE = "ENGINE_UNAVAILABLE"
    """The case engine could not be reached, or did not answer in time.

    Deliberately not a reading. A provider that was never reached is reported as an unavailable
    answer and never as an answer, because a conversation that fills that silence with a guess
    is the failure mode the whole semantic boundary exists to prevent.
    """


class ToolRefusalError(Exception):
    """A refusal a tool saw coming, carrying the code a client is allowed to branch on."""

    def __init__(self, code: ToolCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.message = message


class Envelope(BaseModel):
    """What every tool returns, minus the payload each one adds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool = Field(
        description="whether the intent was accepted; a refusal arrives as a tool error"
    )
    intent: str = Field(description="which of the finite intents this answers")
    correlation_id: str = Field(
        description="ties this call to the durable audit and event rows it caused"
    )
    case_id: str | None = Field(default=None, description="the case this call concerns, if any")
    state: str | None = Field(default=None, description="that case's durable state when answered")
    warnings: tuple[str, ...] = Field(
        default=(), description="things a caller should say out loud but that did not stop the call"
    )


REFUSAL_PREFIX: Final = ": "
"""How a code and its sentence are joined in the text a refused call returns.

The transport carries a tool failure as ``isError`` with text content and no structured body,
so the code travels in the first token of that text rather than in a field. Ugly, and better
than the alternatives: a client can still branch on it, and it is one string rather than a
second error channel nobody would keep in step with this enum.
"""
