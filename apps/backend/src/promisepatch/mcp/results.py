"""What each tool puts inside the envelope.

These models are read from JSON the intent API sent, not shared with it. The MCP process cannot
import :mod:`promisepatch.api`, so the two ends of that hop describe the same payload twice on
purpose: it is a wire contract between processes, and a shared Python class would quietly make
it an in-process one that an import-linter contract could no longer see.

They are also the tools' *output schemas*. The SDK derives them from these annotations, so a
client can validate a result before showing it to anybody, and a model can be told what shape
to expect rather than inferring one from an example.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from promisepatch.mcp.envelope import Envelope


class ReportResult(Envelope):
    """A statement was made durable and the work that reads it was enqueued.

    Nothing has been concluded about anybody's order when this is returned, and the field names
    say so: ``state`` is the case's durable state -- ``RECEIVED`` -- and there is no field here
    that could be mistaken for a recovery.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    statement_id: str = Field(description="the stored statement, identical for a redelivery")
    created: bool = Field(
        description="false when this exact request was already accepted, which is a success"
    )
    attested_by: str = Field(
        description=(
            "the worker the case engine attributed this statement to, resolved from server "
            "configuration. Not something the caller chose and not something it can change."
        )
    )
    speech: str = Field(description="what to say back, rendered deterministically")


class ClarifyResult(Envelope):
    """A worker's answer to the open question was made durable, and nothing was concluded.

    Same shape as a report on purpose: an answer is another thing somebody said, stored before
    it is read. ``state`` is still ``CLARIFYING`` when this returns, because the interpreter
    has not run and the case has therefore not moved.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    statement_id: str = Field(description="the stored answer, identical for a redelivery")
    created: bool = Field(
        description="false when this exact answer was already accepted, which is a success"
    )
    attested_by: str = Field(
        description=(
            "the worker the case engine attributed this answer to, resolved from server "
            "configuration. Not something the caller chose and not something it can change."
        )
    )
    speech: str = Field(description="what to say back, rendered deterministically by the engine")


class ConfirmResult(Envelope):
    """One worker's yes to one specific plan, and what that yes permits. Never what it did.

    Every count here is a permission or a queued intention. ``applying`` is how many tracks a
    standing preference covers -- the contract's ``AUTHORIZED``, which is explicitly not
    ``RECOVERED`` -- and ``awaiting_approval`` is how many customers this authorises *asking*.
    There is no field in this result that could say an order was changed, because when it is
    returned none has been.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    created: bool = Field(
        description="false when this exact confirmation was already accepted, which is a success"
    )
    confirmed_by: str = Field(
        description="the worker whose yes this is, resolved from server configuration"
    )
    applying: int = Field(description="tracks a standing preference covers; permission, not an act")
    awaiting_approval: int = Field(
        description="tracks whose customer this authorises asking, and nothing further"
    )
    escalated: int = Field(description="tracks handed to the owner, with their tasks held")
    speech: str = Field(description="what to say back, rendered deterministically by the engine")


class WithdrawResult(Envelope):
    """What a withdrawal stopped, and -- in its own field -- what it could not stop.

    ``applied`` is the field that makes this result honest, and it is why a withdrawal does not
    reuse the confirmation's shape. Every entry in it is a sentence about something a customer or
    the order system **already has**: an amendment that stands, a message that cannot be unsent.
    A result that carried only ``reversed_writes`` would let a conversation describe a rollback
    that did not happen.

    Nothing here reports a physical fact. Withdrawing a plan does not un-spoil an ingredient or
    make a missing delivery arrive, and there is no field in this schema that could say it did.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    created: bool = Field(
        description="false when this exact withdrawal was already accepted, which is a success"
    )
    withdrawn_by: str = Field(
        description=(
            "the worker the case engine attributed this withdrawal to, resolved from server "
            "configuration. Not something the caller chose and not something it can change."
        )
    )
    withdrawn: int = Field(
        description="promises taken out of the case with nothing having been carried out for them"
    )
    escalated: int = Field(
        description="promises handed to the owner because something had already gone out"
    )
    reversed_writes: tuple[str, ...] = Field(
        default=(),
        description=(
            "what this withdrawal stood down, each already true when the result is returned"
        ),
    )
    applied: tuple[str, ...] = Field(
        default=(),
        description=(
            "what had already happened and is **not** undone. Deliver every entry: it is the "
            "difference between a withdrawal and a rollback, and the rollback did not happen."
        ),
    )
    speech: str = Field(description="what to say back, rendered deterministically by the engine")


class OptionResult(BaseModel):
    """One answer the open question will accept."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    label: str


class QuestionResult(BaseModel):
    """The question a case is waiting on, so a surface can ask it rather than invent it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    clarification_id: str
    question: str
    options: tuple[OptionResult, ...] = ()


class PromiseResult(BaseModel):
    """One customer promise, in the product's own vocabulary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    promise_id: str
    customer_name: str
    order_external_id: str
    state: str = Field(description="the truthful product state, bound to a durable source")
    phrase: str = Field(description="how that state is said to a person")
    authority: str = Field(
        description="who decides this change: a standing preference, the customer, the owner"
    )
    reason: str
    deadline_at: str | None = None
    track_id: str
    track_state: str
    classification: str | None = None
    rule_id: str | None = None


class StatusResult(Envelope):
    """One case as it currently stands, projected and rendered by the case engine.

    ``speech`` arrives already written. A conversational layer delivers it; restating it in the
    model's own words is how "planned" becomes "done" without anybody deciding it should.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    headline: str = Field(description="where the case as a whole has got to")
    speech: str = Field(description="the deterministic status, rendered by the engine")
    needs_owner_attention: bool
    exception_category: str | None = None
    threatened: tuple[PromiseResult, ...] = ()
    untouched: tuple[PromiseResult, ...] = ()
    untouched_count: int = Field(description="how many promises this case left alone")
    question: QuestionResult | None = Field(
        default=None, description="the open clarification, while one is open"
    )
    plan_id: str | None = Field(
        default=None,
        description=(
            "the identity of the plan on offer, present only while a plan is waiting for a "
            "worker's yes. Quote it back to `confirm`. It names a plan this engine rendered "
            "and cannot describe one it did not; nothing can be selected with it."
        ),
    )
    awaiting_confirmation: bool = Field(
        default=False, description="whether a worker's yes is what this case is waiting for"
    )
