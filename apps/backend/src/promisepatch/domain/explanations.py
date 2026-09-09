"""Turning a settled outcome into the small set of facts a sentence may rest on.

Everything in this module is a projection. The deterministic engine has already decided which
promises are affected, by how much, under which rule, with which pre-authored variant and
whose recorded constraint; ``promise_graph.evidence`` has already assembled that into one
serialisable record. This takes that record and produces the *bounded* view an explanation is
allowed to be built from -- a handful of named, already-rendered facts, and the subset of them
the outcome cannot honestly be explained without.

**Nothing here decides anything, and nothing here can.** There is no classification ladder, no
option validation, no reachability, no constraint reading and no clock. Every value it emits
was computed somewhere else and is copied. If that stopped being true the explanation layer
would have become a second implementation of the engine, and the two would eventually disagree
about the same case in the same demo.

**One projection, two renderings.** The same :class:`ExplanationFacts` object is what a model
is asked to phrase and what the deterministic renderer phrases when no model does. That is
deliberate and is the point of the split: a fallback built from a second reading of the state
would be a second causal path, and the two sentences could differ about what happened rather
than only about how well they say it.

**What is deliberately absent.** No worker sentence, no customer reply, no customisation note,
no case id, no database row, no graph. Explaining that a confirmation is outstanding does not
require the message that caused it, and a payload that carried one would be paying to widen
the injection surface for nothing. The two values that did reach PromisePatch from outside --
a customer's name and an order's own reference -- are display labels, and the prompt builder
fences them with everything else that is data rather than instruction.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final

from promise_graph.evidence import CaseEvidence, PromiseEvidence, Reachability
from promise_graph.fingerprint import canonical_json
from promise_graph.model import (
    ApprovalRequestState,
    Classification,
    ConstraintKind,
    ExceptionCategory,
    OptionKind,
    OrderLineId,
    ReasonDetail,
    ResourceId,
)
from promise_graph.propagation import LineQuantification
from promise_graph.revalidation import CheckResult, RevalidationOutcome, RevalidationResult
from promise_graph.snapshot import GraphSnapshot
from promisepatch.semantic import EvidenceFact, SemanticMetadata, VerbaliseRequest

# ------------------------------------------------------------------------------- surfaces


class ExplanationSurface(StrEnum):
    """The things PromisePatch has an already-settled answer about, and may say out loud.

    Four, because the frozen contract has four questions a person asks of a case: what will
    happen overall, what happens to this promise, why this one is still waiting on somebody,
    and what changed while it waited. Anything else a screen shows is a column, not a passage.
    """

    PLAN_SUMMARY = "PLAN_SUMMARY"
    """The whole case at ``PLANNED``: how many promises, in which postures."""

    TRACK_OUTCOME = "TRACK_OUTCOME"
    """One promise's impact classification and the rule that produced it."""

    CUSTOMER_WAIT = "CUSTOMER_WAIT"
    """One promise waiting on a customer, and what would actually settle it."""

    REVALIDATION = "REVALIDATION"
    """One promise's revalidation result: which of the ten checks decided it."""


SUBJECTS: Final[Mapping[ExplanationSurface, str]] = {
    ExplanationSurface.PLAN_SUMMARY: "what this supply exception does to the day's promises",
    ExplanationSurface.TRACK_OUTCOME: "what happens to one customer promise",
    ExplanationSurface.CUSTOMER_WAIT: "why one promise is waiting on its customer",
    ExplanationSurface.REVALIDATION: "what revalidation concluded about one promise",
}
"""What each passage is about, said the same way every time.

A fixed caption rather than a built one: it names no customer, no order and no ingredient, so
every entity a passage may mention is a fact with an id, and there is nothing outside the
referenced set for the model to have got hold of.
"""

WORD_LIMITS: Final[Mapping[ExplanationSurface, int]] = {
    ExplanationSurface.PLAN_SUMMARY: 70,
    ExplanationSurface.TRACK_OUTCOME: 40,
    ExplanationSurface.CUSTOMER_WAIT: 40,
    ExplanationSurface.REVALIDATION: 40,
}
"""Spec 9.2's numbers, not chosen here: 70 words for the plan summary, 40 for everything else."""


class FactId(StrEnum):
    """Every fact an explanation may be built from. Closed, and small on purpose.

    A closed vocabulary is what makes "the passage refers only to things PromisePatch said"
    checkable rather than reviewable: the request carries these ids, the answer names the ones
    it used, and the boundary compares the two lists. An id that is not here cannot be sent, so
    it cannot be referred to.
    """

    CASE_EXCEPTION = "case.exception"
    CASE_AFFECTED = "case.affected"
    CASE_UNAFFECTED = "case.unaffected"
    CASE_AUTOMATIC = "case.automatic"
    CASE_APPROVAL = "case.approval"
    CASE_BLOCKED = "case.blocked"

    PROMISE_CUSTOMER = "promise.customer"
    PROMISE_ORDER = "promise.order"
    PROMISE_ITEM = "promise.item"

    IMPACT_OUTCOME = "impact.outcome"
    IMPACT_REACHABILITY = "impact.reachability"
    IMPACT_REASON = "impact.reason"

    RESOURCE_AFFECTED = "resource.affected"
    RESOURCE_REQUIRED = "resource.required"
    RESOURCE_AVAILABLE = "resource.available"
    RESOURCE_SHORTFALL = "resource.shortfall"

    RECOVERY_OPTION = "recovery.option"
    RECOVERY_VARIANT = "recovery.variant"
    RECOVERY_SUBSTITUTE = "recovery.substitute"
    CONSTRAINT_CITED = "constraint.cited"

    APPROVAL_STATE = "approval.state"
    APPROVAL_DEADLINE = "approval.deadline"
    CONSENT_AUTHORITY = "consent.authority"
    CONSENT_READING = "consent.reading"

    REVALIDATION_OUTCOME = "revalidation.outcome"
    REVALIDATION_CHECK = "revalidation.check"
    REVALIDATION_COMPARISON = "revalidation.comparison"
    REVALIDATION_NEXT = "revalidation.next"


@dataclass(frozen=True, slots=True)
class Fact:
    """One already-decided value, named so an answer can be checked against it."""

    id: FactId
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class ExplanationFacts:
    """The whole of what may be said about one settled outcome, and what may not be left out.

    ``required`` is deterministic code answering "which cause matters here", which is a
    property of the outcome rather than of the phrasing. A blocked promise whose passage never
    reaches the rule that blocked it is fluent and about something else.
    """

    surface: ExplanationSurface
    facts: tuple[Fact, ...]
    required: tuple[FactId, ...] = ()

    @property
    def subject(self) -> str:
        return SUBJECTS[self.surface]

    @property
    def word_limit(self) -> int:
        return WORD_LIMITS[self.surface]

    def value_of(self, fact_id: FactId) -> str | None:
        for fact in self.facts:
            if fact.id is fact_id:
                return fact.value
        return None

    def fingerprint(self) -> str:
        """A stable name for "this outcome, as it stood when the question was asked".

        Recomputed against the current facts before a passage that arrived late is shown. An
        amendment, a decision or a re-plan between the request and the answer changes it, and a
        sentence about the case as it was is not a sentence about the case as it is.
        """
        payload = {
            "surface": self.surface.value,
            "required": [fact_id.value for fact_id in self.required],
            "facts": [(fact.id.value, fact.label, fact.value) for fact in self.facts],
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def request(
        self, *, case_id: str | None = None, correlation_id: str | None = None
    ) -> VerbaliseRequest:
        """The one semantic question these facts permit. The only way they reach a model.

        Built here rather than at the call site so that what a model is shown and what the
        deterministic renderer is given are provably the same object -- the property the whole
        fallback rests on.
        """
        return VerbaliseRequest(
            subject=self.subject,
            facts=tuple(
                EvidenceFact(id=fact.id.value, label=fact.label, value=fact.value)
                for fact in self.facts
            ),
            required_fact_ids=tuple(fact_id.value for fact_id in self.required),
            word_limit=self.word_limit,
            metadata=SemanticMetadata(case_id=case_id, correlation_id=correlation_id),
        )


# --------------------------------------------------------------------------------- phrasing

_OUTCOME_PHRASES: Final[Mapping[Classification, str]] = {
    Classification.UNAFFECTED: "is not affected",
    Classification.AUTO_RECOVERABLE: "can be recovered automatically",
    Classification.APPROVAL_REQUIRED: "needs the customer's approval first",
    Classification.BLOCKED: "cannot be recovered and goes to the owner",
}

_REACHABILITY_PHRASES: Final[Mapping[Reachability, str]] = {
    Reachability.NO_PATH: "no path runs from the exception to this promise",
    Reachability.REACHABLE_COVERED: "a path runs to it, but its own reserved stock still covers it",
    Reachability.AFFECTED: "a path runs from the exception to it",
}

_REASON_PHRASES: Final[Mapping[ReasonDetail, str]] = {
    ReasonDetail.NONE: "the recovery rules record no further reason",
    ReasonDetail.NOT_REACHABLE: "the exception reaches nothing it depends on",
    ReasonDetail.SHORTFALL_COVERED: "what is already reserved for it still covers the need",
    ReasonDetail.PREAPPROVAL_COVERS: "the order already pre-approves this substitution",
    ReasonDetail.NOT_VISIBLE_NO_ASK: "the change is not visible and no constraint asks first",
    ReasonDetail.VISIBLE_CHANGE_ASK: "the change is visible and the order says to ask",
    ReasonDetail.NOT_PREAPPROVED: "this substitution is not pre-approved on the order",
    ReasonDetail.EQUIPMENT_REASSIGNED: (
        "the task moves to other equipment and the item does not change"
    ),
    ReasonDetail.NOSUB_CONSTRAINT: "the order carries a no-substitution constraint",
    ReasonDetail.NO_PREAUTHORED_VARIANT: "no pre-authored variant exists for this item",
    ReasonDetail.EXCLUDED_SUBSTITUTE: "the substitute is excluded on this order",
    ReasonDetail.INSUFFICIENT_SUBSTITUTE_STOCK: (
        "too little substitute is left after earlier promises"
    ),
    ReasonDetail.NO_ALTERNATIVE_EQUIPMENT: "no other equipment is free before the task starts",
    ReasonDetail.NO_CONSTRAINT_SNAPSHOT: (
        "the order has no recorded constraints, which fails closed"
    ),
    ReasonDetail.UNKNOWN_QUANTITY: "a quantity on the path is unknown, which fails closed",
    ReasonDetail.CONFLICTING_CONSTRAINTS: "two of the order's constraints contradict each other",
}

_CATEGORY_PHRASES: Final[Mapping[ExceptionCategory, str]] = {
    ExceptionCategory.SUPPLY_NOT_RECEIVED: "a supplier delivery did not arrive",
    ExceptionCategory.STOCK_UNUSABLE: "stock on hand is unusable",
    ExceptionCategory.EQUIPMENT_UNAVAILABLE: "a piece of equipment is unavailable",
}

_OPTION_PHRASES: Final[Mapping[OptionKind, str]] = {
    OptionKind.SUBSTITUTE_RESOURCE: "re-pin the line to a pre-authored variant",
    OptionKind.REASSIGN_EQUIPMENT: "move the task to other equipment",
    OptionKind.ESCALATE_TO_OWNER: "hand the promise to the owner",
}

_CONSTRAINT_PHRASES: Final[Mapping[ConstraintKind, str]] = {
    ConstraintKind.NO_SUBSTITUTION: "no substitution",
    ConstraintKind.PREAPPROVED_ALTERNATIVE: "a pre-approved alternative",
    ConstraintKind.ASK_BEFORE_VISIBLE_CHANGE: "ask before a visible change",
    ConstraintKind.EXCLUDE_RESOURCE: "an excluded ingredient",
}

_REQUEST_PHRASES: Final[Mapping[ApprovalRequestState, str]] = {
    ApprovalRequestState.SENT: "the customer has been asked and has not answered",
    ApprovalRequestState.CONFIRMATION_PENDING: (
        "their reply was not a decision, so they were asked to confirm"
    ),
    ApprovalRequestState.ANSWERED: "the customer has answered",
    ApprovalRequestState.EXPIRED: "the window closed with no answer",
    ApprovalRequestState.SUPERSEDED: "the request was withdrawn because the order changed",
}

_REVALIDATION_PHRASES: Final[Mapping[RevalidationOutcome, str]] = {
    RevalidationOutcome.PROCEED: "the plan is still valid",
    RevalidationOutcome.STALE: "the kitchen moved while the promise was waiting",
    RevalidationOutcome.EXPIRED: "the approval window closed",
    RevalidationOutcome.UNAUTHORIZED: "the reply did not come from the customer's own channel",
    RevalidationOutcome.NOOP: "there was nothing here to revalidate",
}

_REVALIDATION_NEXT: Final[Mapping[RevalidationOutcome, str]] = {
    RevalidationOutcome.PROCEED: "the approved change is applied",
    RevalidationOutcome.STALE: "the promise is planned again against the kitchen as it now is",
    RevalidationOutcome.EXPIRED: "the promise goes to the owner",
    RevalidationOutcome.UNAUTHORIZED: "nothing changes and the owner is told",
    RevalidationOutcome.NOOP: "nothing changes",
}

CONSENT_AUTHORITY: Final = "only a literal yes or no on their own channel records a decision"
"""Spec 13.6 in one clause. A fact, so a passage about a wait can be required to carry it."""


def _by_value[Key: StrEnum](table: Mapping[Key, str]) -> Mapping[str, str]:
    """One phrase table keyed by the enum member's own value rather than by the member."""
    return {key.value: phrase for key, phrase in table.items()}


CLOSED_VOCABULARIES: Final[Mapping[FactId, Mapping[str, str]]] = {
    FactId.CASE_EXCEPTION: _by_value(_CATEGORY_PHRASES),
    FactId.IMPACT_OUTCOME: _by_value(_OUTCOME_PHRASES),
    FactId.IMPACT_REACHABILITY: _by_value(_REACHABILITY_PHRASES),
    FactId.IMPACT_REASON: _by_value(_REASON_PHRASES),
    FactId.RECOVERY_OPTION: _by_value(_OPTION_PHRASES),
    FactId.APPROVAL_STATE: _by_value(_REQUEST_PHRASES),
    FactId.CONSENT_AUTHORITY: {"CONSENT_AUTHORITY": CONSENT_AUTHORITY},
    FactId.REVALIDATION_OUTCOME: _by_value(_REVALIDATION_PHRASES),
    FactId.REVALIDATION_NEXT: _by_value(_REVALIDATION_NEXT),
}
"""The facts whose value comes from a closed set, and what each member of that set renders as.

A projection of the phrase tables above -- derived from them rather than restated, so the two
cannot disagree -- keyed by the engine enum member's own value. Nothing reads it at runtime and
nothing here decides anything. It exists so that "this is a value the engine can actually
produce, and it is the one that goes with *that* rule" is a question somebody outside this
module can ask: a reviewer, or a fixture that has to be checked against production rather than
against itself. Copying the phrases into the checker instead would put the wording in a second
place and let the copy rot.

Absent on purpose are the facts whose value is a rendered quantity, an instant, or a label the
order system supplied. Those are not drawn from a set, and pretending they were would be a
vocabulary that quietly excluded a legitimate value.
"""

CONSTRAINT_PREFIXES: Final[frozenset[str]] = frozenset(_CONSTRAINT_PHRASES.values())
"""What a cited constraint's value begins with, before the provenance clause is appended.

Separate from :data:`CLOSED_VOCABULARIES` because ``constraint.cited`` is a closed phrase
followed by who recorded it, so the check on it is a prefix and not an equality.
"""


# ------------------------------------------------------------------------------ projections


def plan_summary(evidence: CaseEvidence, snapshot: GraphSnapshot) -> ExplanationFacts:
    """What the whole case concluded, in counts. Selectivity is the fact that matters.

    ``case.unaffected`` is required because it is the claim the product is making: promises the
    exception cannot reach are untouched, and a summary that only counted damage would be
    describing an alerting system.
    """
    postures = [promise.classification.classification for promise in evidence.promises.values()]
    resources = sorted(
        {
            quantification.resource_id
            for promise_id in evidence.affected_promise_ids
            for quantification in evidence.promises[promise_id].quantifications
            if not quantification.satisfied
        }
    )
    category = ExceptionCategory(evidence.category)

    facts = (
        Fact(FactId.CASE_EXCEPTION, "what happened", _CATEGORY_PHRASES[category]),
        Fact(
            FactId.RESOURCE_AFFECTED,
            "what is short",
            _names(snapshot, resources) if resources else "nothing quantified",
        ),
        Fact(FactId.CASE_AFFECTED, "promises affected", str(len(evidence.affected_promise_ids))),
        Fact(
            FactId.CASE_UNAFFECTED,
            "promises untouched",
            str(len(evidence.unaffected_promise_ids)),
        ),
        Fact(
            FactId.CASE_AUTOMATIC,
            "recovered without asking anyone",
            str(postures.count(Classification.AUTO_RECOVERABLE)),
        ),
        Fact(
            FactId.CASE_APPROVAL,
            "waiting on a customer's approval",
            str(postures.count(Classification.APPROVAL_REQUIRED)),
        ),
        Fact(
            FactId.CASE_BLOCKED,
            "blocked, going to the owner",
            str(postures.count(Classification.BLOCKED)),
        ),
    )
    return ExplanationFacts(
        surface=ExplanationSurface.PLAN_SUMMARY,
        facts=facts,
        required=(FactId.CASE_EXCEPTION, FactId.CASE_AFFECTED, FactId.CASE_UNAFFECTED),
    )


def track_outcome(evidence: PromiseEvidence, snapshot: GraphSnapshot) -> ExplanationFacts:
    """One promise's classification, its cited reason, and the numbers behind both.

    The required set follows the outcome. Unaffected owes an answer to *why* it is unaffected,
    because spec 13.1 has two different unaffected readings and collapsing them would hide the
    selectivity the product is claiming. Everything affected owes the rule it was decided by,
    and a recovery owes the pre-authored variant it selected.
    """
    result = evidence.classification
    classification = result.classification
    facts: list[Fact] = list(_identity(evidence, snapshot))

    facts.append(Fact(FactId.IMPACT_OUTCOME, "outcome", _OUTCOME_PHRASES[classification]))
    facts.append(
        Fact(
            FactId.IMPACT_REACHABILITY,
            "how the exception reaches it",
            _REACHABILITY_PHRASES[evidence.reachability],
        )
    )
    facts.append(Fact(FactId.IMPACT_REASON, "reason", _REASON_PHRASES[result.reason_detail]))

    required = [FactId.IMPACT_OUTCOME, FactId.IMPACT_REASON]
    if classification is Classification.UNAFFECTED:
        required.append(FactId.IMPACT_REACHABILITY)

    shortfall = _shortfall(evidence.quantifications)
    if shortfall is not None:
        unit = _unit(snapshot, shortfall.resource_id)
        facts.append(
            Fact(
                FactId.RESOURCE_AFFECTED,
                "ingredient short",
                _names(snapshot, [shortfall.resource_id]),
            )
        )
        facts.append(
            Fact(FactId.RESOURCE_REQUIRED, "needed", _quantity(shortfall.need, unit)),
        )
        facts.append(
            Fact(
                FactId.RESOURCE_AVAILABLE,
                "available before the task starts",
                _quantity(shortfall.available_before_start, unit),
            )
        )
        facts.append(
            Fact(FactId.RESOURCE_SHORTFALL, "short by", _quantity(shortfall.shortfall, unit))
        )
        required.append(FactId.RESOURCE_SHORTFALL)

    chosen = next(
        (option for option in evidence.valid_options if option.id == result.chosen_option_id),
        None,
    )
    if chosen is not None:
        facts.append(Fact(FactId.RECOVERY_OPTION, "recovery", _OPTION_PHRASES[chosen.kind]))
        if chosen.to_version_id is not None:
            facts.append(
                Fact(
                    FactId.RECOVERY_VARIANT,
                    "pre-authored variant selected",
                    _version_name(snapshot, chosen.to_version_id),
                )
            )
            required.append(FactId.RECOVERY_VARIANT)
        if chosen.substitute_resource_id is not None:
            facts.append(
                Fact(
                    FactId.RECOVERY_SUBSTITUTE,
                    "substitute ingredient",
                    _names(snapshot, [chosen.substitute_resource_id]),
                )
            )

    if evidence.citations:
        citation = evidence.citations[0]
        kind = ConstraintKind(citation.kind)
        facts.append(
            Fact(
                FactId.CONSTRAINT_CITED,
                "constraint on the order",
                f"{_CONSTRAINT_PHRASES[kind]}, recorded by {citation.recorded_by}",
            )
        )
        required.append(FactId.CONSTRAINT_CITED)

    return ExplanationFacts(
        surface=ExplanationSurface.TRACK_OUTCOME,
        facts=tuple(facts),
        required=tuple(required),
    )


@dataclass(frozen=True, slots=True)
class WaitPosture:
    """What an outstanding approval request looks like, as the projection needs to read it.

    Values the graph does not hold: a request's state, its deadline, and the labels a model
    once put on replies that were not decisions. ``apparent_intent`` is carried as the word it
    is -- ``APPARENT_APPROVE`` is not ``APPROVE``, and the passage built from it says that a
    reading exists, never that a customer agreed.
    """

    state: ApprovalRequestState
    deadline: datetime
    apparent_intent: str | None = None


def customer_wait(
    evidence: PromiseEvidence, snapshot: GraphSnapshot, posture: WaitPosture
) -> ExplanationFacts:
    """Why one promise is still waiting, and what would actually end the wait.

    ``consent.authority`` is required on every passage this surface produces, including the one
    built after a model read a reply as apparent approval. That is the whole defence of the
    surface: a passage that has to say only a literal reply counts cannot also read as though
    one has arrived.
    """
    facts: list[Fact] = list(_identity(evidence, snapshot))
    chosen = next(
        (
            option
            for option in evidence.valid_options
            if option.id == evidence.classification.chosen_option_id
        ),
        None,
    )
    if chosen is not None and chosen.to_version_id is not None:
        facts.append(
            Fact(
                FactId.RECOVERY_VARIANT,
                "change the customer was asked about",
                _version_name(snapshot, chosen.to_version_id),
            )
        )
    facts.append(
        Fact(
            FactId.APPROVAL_STATE,
            "where the request stands",
            _REQUEST_PHRASES[posture.state],
        )
    )
    facts.append(Fact(FactId.APPROVAL_DEADLINE, "answer needed by", _instant(posture.deadline)))
    facts.append(Fact(FactId.CONSENT_AUTHORITY, "what counts as an answer", CONSENT_AUTHORITY))

    required = [FactId.APPROVAL_STATE, FactId.CONSENT_AUTHORITY]
    if posture.apparent_intent is not None:
        facts.append(
            Fact(
                FactId.CONSENT_READING,
                "non-authoritative reading of their message",
                posture.apparent_intent,
            )
        )
    return ExplanationFacts(
        surface=ExplanationSurface.CUSTOMER_WAIT,
        facts=tuple(facts),
        required=tuple(required),
    )


def revalidation(
    evidence: PromiseEvidence, snapshot: GraphSnapshot, result: RevalidationResult
) -> ExplanationFacts:
    """What the ten checks concluded, and which one decided it.

    The engine ran the checks and picked the deciding one; this reads that off the result. A
    projection that worked out for itself which check mattered would be a second, quieter
    revalidation, and spec 14.3 has exactly one.
    """
    deciding = _deciding(result)
    facts: list[Fact] = list(_identity(evidence, snapshot)[:2])
    facts.append(
        Fact(
            FactId.REVALIDATION_OUTCOME,
            "revalidation outcome",
            _REVALIDATION_PHRASES[result.outcome],
        )
    )
    required = [FactId.REVALIDATION_OUTCOME, FactId.REVALIDATION_NEXT]
    if deciding is not None:
        facts.append(Fact(FactId.REVALIDATION_CHECK, "the check that decided it", deciding.name))
        facts.append(
            Fact(
                FactId.REVALIDATION_COMPARISON,
                "expected against found",
                f"{deciding.expected} against {deciding.actual}",
            )
        )
        required.append(FactId.REVALIDATION_CHECK)
    facts.append(
        Fact(FactId.REVALIDATION_NEXT, "what happens next", _REVALIDATION_NEXT[result.outcome])
    )
    return ExplanationFacts(
        surface=ExplanationSurface.REVALIDATION,
        facts=tuple(facts),
        required=tuple(required),
    )


# -------------------------------------------------------------------- deterministic rendering


def render(facts: ExplanationFacts) -> str:
    """The passage PromisePatch says when no model does. One renderer, the same facts.

    It is not written to be admired. It is written to be true, short enough for the surface's
    own word limit, and free of anything a listener would have to be an engineer to follow --
    which is all the product actually needs of it when a provider is down.
    """
    if facts.surface is ExplanationSurface.PLAN_SUMMARY:
        return _render_plan(facts)
    if facts.surface is ExplanationSurface.TRACK_OUTCOME:
        return _render_outcome(facts)
    if facts.surface is ExplanationSurface.CUSTOMER_WAIT:
        return _render_wait(facts)
    return _render_revalidation(facts)


def _render_plan(facts: ExplanationFacts) -> str:
    parts = [
        _sentence(
            f"{_get(facts, FactId.CASE_EXCEPTION)}; "
            f"{_get(facts, FactId.RESOURCE_AFFECTED)} are short"
        ),
        f"{_get(facts, FactId.CASE_AFFECTED)} promises are affected and "
        f"{_get(facts, FactId.CASE_UNAFFECTED)} are untouched.",
    ]
    breakdown = [
        (FactId.CASE_AUTOMATIC, "automatic"),
        (FactId.CASE_APPROVAL, "awaiting customer approval"),
        (FactId.CASE_BLOCKED, "blocked"),
    ]
    clauses = [
        f"{facts.value_of(fact_id)} {phrase}"
        for fact_id, phrase in breakdown
        if (facts.value_of(fact_id) or "0") != "0"
    ]
    if clauses:
        parts.append(f"Of those: {', '.join(clauses)}.")
    return " ".join(parts)


def _render_outcome(facts: ExplanationFacts) -> str:
    """Subject, the number, the rule, the variant. The rule is stated once.

    Where a constraint is cited, the citation *is* the rule, with the provenance spec 13.5
    requires an escalation to carry -- so saying the reason clause as well would be the same
    finding twice inside a forty-word budget. Where an outcome is unaffected, reachability is
    the same finding at the level a person actually asks about: whether the exception could
    touch this promise at all.
    """
    parts = [_sentence(f"{_subject_clause(facts)} {_get(facts, FactId.IMPACT_OUTCOME)}")]
    shortfall = facts.value_of(FactId.RESOURCE_SHORTFALL)
    if shortfall is not None:
        parts.append(
            _sentence(f"{facts.value_of(FactId.RESOURCE_AFFECTED)} are short by {shortfall}")
        )
    constraint = facts.value_of(FactId.CONSTRAINT_CITED)
    if constraint is not None:
        parts.append(_sentence(f"the order's constraint is {constraint}"))
    elif FactId.IMPACT_REACHABILITY in facts.required:
        parts.append(_sentence(_get(facts, FactId.IMPACT_REACHABILITY)))
    else:
        parts.append(_sentence(_get(facts, FactId.IMPACT_REASON)))
    variant = facts.value_of(FactId.RECOVERY_VARIANT)
    if variant is not None:
        parts.append(f"The variant is {variant}.")
    return " ".join(parts)


def _render_wait(facts: ExplanationFacts) -> str:
    """Who is waiting, on what, where the request stands, and what would end it.

    The non-authoritative reading is offered to a model and left out here on purpose: the
    request's own state already says the reply was not a decision, and a spoken sentence that
    reported a label as well would be spending words to repeat the half that authorises
    nothing.
    """
    customer = facts.value_of(FactId.PROMISE_CUSTOMER) or "The customer"
    variant = facts.value_of(FactId.RECOVERY_VARIANT)
    opening = f"{customer} is waiting"
    return " ".join(
        [
            _sentence(opening if variant is None else f"{opening} on {variant}"),
            _sentence(_get(facts, FactId.APPROVAL_STATE)),
            _sentence(_get(facts, FactId.CONSENT_AUTHORITY)),
        ]
    )


def _render_revalidation(facts: ExplanationFacts) -> str:
    parts = [_sentence(f"for {_subject_clause(facts)}, {_get(facts, FactId.REVALIDATION_OUTCOME)}")]
    check = facts.value_of(FactId.REVALIDATION_CHECK)
    if check is not None:
        parts.append(f"The check that decided it was {check}.")
    parts.append(_sentence(_get(facts, FactId.REVALIDATION_NEXT)))
    return " ".join(parts)


def _sentence(clause: str) -> str:
    """One clause as a sentence: first letter raised, everything else left alone.

    Not ``str.capitalize``, which lowercases the rest and would turn a pre-authored variant's
    own name into something the bakery never authored.
    """
    return f"{clause[:1].upper()}{clause[1:]}."


def _subject_clause(facts: ExplanationFacts) -> str:
    customer = facts.value_of(FactId.PROMISE_CUSTOMER)
    item = facts.value_of(FactId.PROMISE_ITEM)
    if customer is None:  # pragma: no cover - every promise surface carries its customer
        return "this promise"
    return f"{customer}'s order" if item is None else f"{customer}'s {item}"


def _get(facts: ExplanationFacts, fact_id: FactId) -> str:
    value = facts.value_of(fact_id)
    if value is None:  # pragma: no cover - every surface supplies its own required facts
        raise KeyError(f"{facts.surface.value} has no {fact_id.value}")
    return value


# ------------------------------------------------------------------------------- fact values


def _identity(evidence: PromiseEvidence, snapshot: GraphSnapshot) -> tuple[Fact, ...]:
    """Who this promise belongs to, which order it is, and what was ordered.

    The customer's name and the order's external reference came from the order system, so both
    are display labels PromisePatch did not author. They are carried because a passage naming
    neither is a passage nobody can act on, and they are fenced as data on the way out.
    """
    order = snapshot.orders[evidence.order_id]
    customer = snapshot.customers[evidence.customer_id]
    return (
        Fact(FactId.PROMISE_CUSTOMER, "customer", customer.name),
        Fact(FactId.PROMISE_ORDER, "order", order.external_id),
        Fact(FactId.PROMISE_ITEM, "item ordered", _items(evidence, snapshot)),
    )


def _items(evidence: PromiseEvidence, snapshot: GraphSnapshot) -> str:
    """The pinned variant names on the lines this outcome is about, or on the whole order."""
    lines: list[OrderLineId] = [
        quantification.order_line_id for quantification in evidence.quantifications
    ]
    lines.extend(option.order_line_id for option in evidence.valid_options)
    order = snapshot.orders[evidence.order_id]
    chosen = [line for line in order.lines if line.id in set(lines)] or list(order.lines)
    return ", ".join(
        dict.fromkeys(_version_name(snapshot, line.recipe_version_id) for line in chosen)
    )


def _version_name(snapshot: GraphSnapshot, version_id: str) -> str:
    version = snapshot.versions[version_id]
    return f"{snapshot.recipes[version.recipe_id].name} v{version.version_no}"


def _names(snapshot: GraphSnapshot, resource_ids: Sequence[ResourceId]) -> str:
    return ", ".join(snapshot.resources[resource_id].name for resource_id in resource_ids)


def _unit(snapshot: GraphSnapshot, resource_id: ResourceId) -> str:
    return snapshot.resources[resource_id].unit


def _shortfall(
    quantifications: Sequence[LineQuantification],
) -> LineQuantification | None:
    """The largest quantified shortfall on this promise, or ``None`` when there is none.

    One number rather than every line's, because a forty-word passage that recited a table
    would be a table read aloud. The largest is the one a person acts on.
    """
    quantified = [
        quantification
        for quantification in quantifications
        if quantification.shortfall is not None and quantification.shortfall > 0
    ]
    if not quantified:
        return None
    return max(quantified, key=lambda item: (item.shortfall or Decimal(0), item.resource_id))


def _quantity(value: Decimal | None, unit: str) -> str:
    if value is None:
        return "an unknown amount"
    return f"{format(value.normalize(), 'f')} {unit}"


_MONTHS: Final = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
"""Month names written out here rather than taken from ``strftime``.

``%B`` reads the process locale, which is a value this module has no business depending on: the
same deadline would be explained in different words on two machines, and the facts fingerprint
would differ with it.
"""


def _instant(value: datetime) -> str:
    """A deadline a person can hear. Minutes, in the stored zone, and no seconds."""
    return f"{value.day} {_MONTHS[value.month - 1]} at {value:%H:%M}"


def _deciding(result: RevalidationResult) -> CheckResult | None:
    """The check the engine's own outcome came from: the lowest-numbered failure."""
    failed = result.failed
    return failed[0] if failed else None


__all__ = [
    "CLOSED_VOCABULARIES",
    "CONSENT_AUTHORITY",
    "CONSTRAINT_PREFIXES",
    "SUBJECTS",
    "WORD_LIMITS",
    "ExplanationFacts",
    "ExplanationSurface",
    "Fact",
    "FactId",
    "WaitPosture",
    "customer_wait",
    "plan_summary",
    "render",
    "revalidation",
    "track_outcome",
]
