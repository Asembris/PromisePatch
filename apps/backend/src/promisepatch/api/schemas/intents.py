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


class ClarifyIntent(BaseModel):
    """A worker's answer to the one question this case is waiting on.

    An answer, and nothing else. There is no field for the question being answered, because a
    case has at most one open and choosing among several would be an authority; no field for a
    physical fact, because the words are interpreted by the worker process against options
    derived from stored rows; and no field for an actor or a clock, for the reason at the top
    of this module.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: UUID = Field(description="stable command identity; a redelivery must reuse it")
    case_id: UUID
    text: str = Field(
        min_length=1,
        max_length=MAX_UNTRUSTED_CHARACTERS,
        description=(
            "what the worker answered, verbatim. Stored exactly as sent and resolved against "
            "the options the question was asked with, never against a fresh reading."
        ),
    )


class ClarificationAccepted(BaseModel):
    """What the case engine did with one answer. Nothing is concluded when this returns."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: UUID
    statement_id: UUID
    state: str
    created: bool = Field(
        description="false for a redelivery of an answer already accepted, which is a success"
    )
    attested_by: str = Field(
        description="the worker this server attributed the answer to, from its own configuration"
    )
    speech: str = Field(description="what to say back, rendered deterministically by the domain")


class ConfirmIntent(BaseModel):
    """A worker's yes to one specific plan.

    ``plan_id`` is the whole difference between this and a blanket authorisation. It is the
    identity of the plan ``status`` presented, and the domain checks it against the plan the
    case is currently offering before anything is enqueued -- so a yes cannot land on a plan
    that was re-made after the worker read it.

    There is no ``confirmed: bool``. A false one would be a withdrawal wearing a confirmation's
    name, and withdrawal is its own intent with its own rules; calling this endpoint *is* the
    yes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: UUID = Field(description="stable command identity; a redelivery must reuse it")
    case_id: UUID
    plan_id: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "the identity of the plan being confirmed, exactly as `status` returned it. "
            "Opaque: it names a plan the server rendered and cannot describe one it did not."
        ),
    )


class ConfirmationAccepted(BaseModel):
    """What a worker's yes authorised, in counts -- and never what it completed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: UUID
    command_id: UUID
    state: str
    created: bool = Field(
        description="false for a redelivery of a confirmation already accepted, which is a success"
    )
    confirmed_by: str
    applying: int = Field(
        description="tracks a standing preference covers. Permission to act; not an act"
    )
    awaiting_approval: int = Field(
        description="tracks whose customer this authorises *asking*, and nothing further"
    )
    escalated: int = Field(description="tracks handed to the owner, with their tasks held")
    speech: str = Field(description="what to say back, rendered deterministically by the domain")


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


class QuestionOption(BaseModel):
    """One answer the open question will accept."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    label: str


class PendingQuestion(BaseModel):
    """The question a case is waiting on. Band 1 of the workspace, and never a result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    clarification_id: UUID
    question: str
    options: tuple[QuestionOption, ...] = ()


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
    question: PendingQuestion | None = Field(
        default=None, description="the open clarification, while one is open"
    )
    plan_id: str | None = Field(
        default=None,
        description=(
            "the identity of the plan on offer, present only while a plan is actually waiting "
            "for a worker's yes. Quote it back to `confirm`; it is not a recipe, an order or a "
            "version, and nothing can be selected with it."
        ),
    )
    awaiting_confirmation: bool = Field(
        default=False, description="whether a worker's yes is what this case is waiting for"
    )
