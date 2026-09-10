"""The wire shapes of the internal intent API.

Two things are conspicuously absent from every request model here, and their absence is the
design: **no actor field and no timestamp field.** Who is speaking and when they spoke are
resolved on this server -- from its configuration and from its own clock -- so there is no
argument for an orchestrator, a model or a compromised MCP process to fill in with a name it
preferred. A field that could carry an actor is an authority somebody eventually gets to choose.

``extra="forbid"`` everywhere for the same reason. A request that arrives carrying a
``worker_id`` it invented is rejected rather than quietly ignored, so a caller labouring under
that misunderstanding finds out immediately instead of believing it worked.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from promisepatch.semantic.contracts import MAX_UNTRUSTED_CHARACTERS


class ReportIntent(BaseModel):
    """One spoken physical exception, as it arrived at the conversational surface."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: UUID = Field(
        description="stable command identity; a redelivery must reuse it, and it derives the case"
    )
    text: str = Field(
        min_length=1,
        max_length=MAX_UNTRUSTED_CHARACTERS,
        description=(
            "what the worker said, verbatim. Stored exactly as sent, before anything is "
            "concluded from it. The bound is the semantic boundary's own, so an input this "
            "application could not carry is refused here rather than deeper in."
        ),
    )


class ReportAccepted(BaseModel):
    """What the case engine did with one report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: UUID
    statement_id: UUID
    state: str
    created: bool = Field(
        description="false for a redelivery of a request already accepted, which is a success"
    )
    attested_by: str = Field(
        description="the worker this server attributed the statement to, from its own configuration"
    )


class StatusIntent(BaseModel):
    """A request to read one case as it currently stands."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: UUID


class PromiseStatus(BaseModel):
    """One customer promise in the case, in the product's own vocabulary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    promise_id: str
    customer_name: str
    order_external_id: str
    state: str
    phrase: str
    authority: str
    reason: str
    deadline_at: str | None = None
    track_id: str
    track_state: str
    classification: str | None = None
    rule_id: str | None = None


class CaseStatusResponse(BaseModel):
    """A case, projected deterministically, with the sentences already rendered.

    ``speech`` is rendered here rather than by whatever is holding the conversation, because a
    layer that re-words "planned" is one word away from "done". The structured fields beside it
    are the same projection, for a caller that wants to lay it out rather than say it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: UUID
    headline: str
    speech: str
    needs_owner_attention: bool
    exception_category: str | None = None
    threatened: tuple[PromiseStatus, ...] = ()
    untouched: tuple[PromiseStatus, ...] = ()
    untouched_count: int
