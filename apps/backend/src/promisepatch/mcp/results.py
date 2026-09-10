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
