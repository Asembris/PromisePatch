"""The wire shape of the case workspace: five bands, and the evidence behind them.

The P5 product contract fixes what a worker is shown and in what order, so the response models
carry the bands rather than a flat bag the browser would have to arrange for itself. A frontend
that grouped promises by classification, counted the untouched ones or composed a closing
sentence would be a second implementation of
:mod:`promisepatch.domain.status_view` in TypeScript, and the two would eventually disagree.

**Every field here is a projected durable value.** Nothing is computed on the way out that the
domain did not already conclude, and there is no field a screen could fill in itself: the
counts, the phrases, the next action and the reasons all arrive decided.

**Bands 1-4 are sentences; band 5 is evidence.** Sequence numbers, fingerprints, idempotency
keys, rule ids and provider references live in :class:`EvidenceView` because the contract puts
engineering vocabulary in the drawer. They are present in the payload rather than behind a
second request so that opening the drawer proves nothing was fetched to fill it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QuestionOptionView(BaseModel):
    """One answer the open question will accept."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    label: str


class QuestionView(BaseModel):
    """The question band 1 shows instead of a result, while one is open."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    clarification_id: UUID
    question: str
    options: tuple[QuestionOptionView, ...]


class ClarificationHistoryView(BaseModel):
    """One question this case asked, beside whatever answered it.

    Band 1 keeps the question and its answer together after the answer arrives, and this is the
    durable pair it reads. ``question`` is the only open one's twin: a screen that rebuilt an
    answered question from the answer, or from the case's category, would be showing a sentence
    nobody asked.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    clarification_id: UUID
    ordinal: int
    slot: str
    question: str
    options: tuple[QuestionOptionView, ...]
    asked_at: datetime
    answered: bool
    answer_text: str | None = Field(description="the worker's own answer, verbatim, or null")
    answered_by: str | None
    answered_at: datetime | None
    resolved_option_code: str | None


class NextActionView(BaseModel):
    """Band 2. Exactly one action, and exactly one person it belongs to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    owner: str = Field(description="YOU, OWNER, CUSTOMER, SYSTEM or NOBODY")
    owner_label: str
    action: str


class CausalStepView(BaseModel):
    """One node of the traversal that reached a promise, named by the domain.

    ``slot`` is the fixed column this step belongs in -- what did not arrive, what it fell short
    of, the version the order pins, the promise -- so every chain occupies the same geometry and
    a reader compares rows rather than relearning a layout. A column may carry more than one
    step, and the array is rendered in the order it arrives: never sorted, filtered or reversed.

    ``node_ref`` is drawer vocabulary and is never drawn in bands 1-4.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    slot: str = Field(description="SHORTFALL, RESOURCE, VERSION or PROMISE")
    label: str
    detail: str | None
    node_ref: str


class CausalChainView(BaseModel):
    """How the exception reached one promise, or the reason nothing did.

    Carried on **every** promise, threatened and untouched alike, because an untouched promise's
    empty chain is the selectivity claim and a field that were simply absent would read as a
    screen that had not finished loading.

    ``path_count`` is how many traversals the track actually has, which is not the length of
    ``steps``: where several exist this carries the one whose stored rule decided the track, and
    says how many others there were. **A merged or synthesised path is never returned.**
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    present: bool
    steps: tuple[CausalStepView, ...]
    absence_reason: str | None = Field(
        description="why there is no chain to show, whenever present is false"
    )
    path_count: int
    deciding_rule: str | None


class PromiseWorkspaceView(BaseModel):
    """One customer promise, as this case has left it, in the words the product may use."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    promise_id: str
    customer_name: str
    order_external_id: str
    state: str = Field(description="the truthful product state, never a durable track state")
    phrase: str = Field(description="how that state is said to a person, rendered by the domain")
    authority: str = Field(description="under whose authority this promise changes")
    reason: str
    deadline_at: str | None
    owner: str = Field(description="whose move this promise is now")
    next_action: str = Field(description="what moves it, or a sentence saying nothing does")
    track_id: UUID
    track_state: str
    classification: str | None
    rule_id: str | None
    causal_chain: CausalChainView


class AuthorityBandView(BaseModel):
    """Band 3, one group: threatened promises that change under the same authority.

    ``count`` is stated beside the list for the same reason ``untouched_count`` is: the number
    a screen shows under a group header is a claim about how many promises this authority
    decides, and a surface that took the length of a list it had rendered would be reporting on
    its own rendering rather than on the case.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    authority: str
    title: str
    promises: tuple[PromiseWorkspaceView, ...]
    count: int


class EffectEvidenceView(BaseModel):
    """One outbound effect a track caused, with the two identifiers that prove it happened."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    state: str
    idempotency_key: str
    provider_ref: str | None
    attempts: int
    result: dict[str, Any] | None
    delivered_at: datetime | None
    last_error: str | None


class ApprovalEvidenceView(BaseModel):
    """What was asked of one customer and what came back. No channel, no reply text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    option_code: str
    state: str
    decided: bool
    sent_at: datetime
    deadline: datetime
    provider_ref: str | None
    decision: str | None
    parser: str | None
    replies: int


class RevalidationCheckView(BaseModel):
    """One of the ten checks, with the two values it compared."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int
    name: str
    passed: bool
    expected: str
    actual: str


class RevalidationEvidenceView(BaseModel):
    """What the checklist concluded about one track, read from the ledger rather than rerun."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: str
    deciding_check: int | None
    detail: str | None
    fingerprint: str | None
    checks: tuple[RevalidationCheckView, ...]


class TrackEvidenceView(BaseModel):
    """The drawer's row for one promise: identifiers, and what actually left the building."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    promise_id: str
    track_id: UUID
    track_state: str
    classification: str | None
    rule_id: str | None
    reason_detail: str | None
    fingerprint: str | None
    order_external_id: str
    order_external_version: int
    mirrored_versions: dict[str, str]
    paths: int
    watched_entities: int
    effects: tuple[EffectEvidenceView, ...]
    approval: ApprovalEvidenceView | None
    revalidation: RevalidationEvidenceView | None


class InterpretationEvidenceView(BaseModel):
    """How the sentence came to be understood, and who is on the record for the facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    outcome: str | None
    attestor: str | None
    step_state: str | None
    provider: str | None
    model_id: str | None
    deterministic_reason: str | None
    grounded: tuple[str, ...]
    rejected: tuple[str, ...]
    failure: str | None
    last_error: str | None


class EvidenceView(BaseModel):
    """Band 5, collapsed by default. The engineering vocabulary, all of it durable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: UUID
    case_state: str
    case_version: int
    plan_id: str = Field(description="the derived identity of the plan these tracks currently are")
    exception_id: UUID | None
    interpretation: InterpretationEvidenceView | None
    tracks: tuple[TrackEvidenceView, ...]


class CaseWorkspaceResponse(BaseModel):
    """One case, as the workspace shows it: what happened, what is yours, and what was untouched.

    ``untouched_count`` is carried explicitly even though the list is here, because it is the
    product's central published claim and a screen that recomputed it could recompute it
    differently -- filtered, paginated or deduplicated -- without anybody noticing.

    ``promise_count`` is the same argument applied to the denominator. "0 incident-caused
    operational effects on 3 of 6 orders" is two numbers, and the second one is the universe
    this case considered. A screen that added the untouched count to the threatened one would
    be composing the claim rather than reading it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: UUID
    headline: str
    sentence: str
    exception_category: str | None
    reported_text: str | None = Field(
        description="the worker's own words, verbatim, or null when nothing has been reported"
    )
    reported_by: str | None
    reported_at: datetime | None
    needs_owner_attention: bool
    question: QuestionView | None
    clarifications: tuple[ClarificationHistoryView, ...] = Field(
        description="every question this case asked, oldest first, the open one included"
    )
    next_action: NextActionView
    authority_bands: tuple[AuthorityBandView, ...]
    untouched: tuple[PromiseWorkspaceView, ...]
    untouched_count: int
    threatened_count: int
    promise_count: int
    plan_id: str | None
    awaiting_confirmation: bool
    evidence: EvidenceView


class CaseSummaryView(BaseModel):
    """One row of the case list: enough to choose a case, and nothing that would prejudge it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: UUID
    state: str
    headline: str
    sentence: str
    needs_owner_attention: bool
    reported_text: str | None
    opened_at: datetime
    updated_at: datetime


class CaseListResponse(BaseModel):
    """Every case this worker may open, newest first."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cases: tuple[CaseSummaryView, ...]
