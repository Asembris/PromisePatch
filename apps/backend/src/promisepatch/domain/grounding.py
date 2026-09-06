"""What a model's reading of a worker's sentence is worth. Pure, values in, values out.

The deterministic interpreter reads a fixed lexicon. When a worker says something it does not
contain -- "the deck oven packed up", "Valley only brought part of the raspberries" -- the
sentence is not unreadable, it is only unread by *that* lexicon. This module is where a model's
reading of such a sentence meets the rules, and where it either becomes an ordinary
deterministic reading or becomes nothing at all.

**The model contributes identity, and only identity.** One category, and one thing in the
bakery the worker was reaching for. It contributes no delivery, no scope, no quantity and no
physical outcome. Which commitment, whether the crate also held something nobody mentioned,
whether a number was attested -- every one of those is decided afterwards by
:func:`~promisepatch.domain.interpretation.interpret_grounded`, which is the same code that
decides them for the canonical sentence. So there is one interpreter, not two, and the reading
a model helped with is subject to every question the reading it did not help with is subject
to, including the clarification that makes the demo consequential.

**Identity must be in the bakery's own words.** A proposed resource is accepted only if the
worker's sentence contains that resource's stored name or one of its recorded aliases. That
single rule is what separates *parsing* from *knowing*: a model may work out that "packed up"
is an equipment failure and that "the deck oven" is the deck oven, because the deck oven is
written in the sentence. It may not work out that "the berries" means raspberries, because
nothing the bakery authored says so, and a reading resting on the model's world knowledge
alone is a reading nobody can check. Sentences like that fail closed to a human, exactly as
they did before this module existed.

**Three things a model says are never read here.** Its confidence, its scope and quantity
hints, and its "this looked ambiguous to me" flag. Ambiguity is decided by the deterministic
triggers and by whether the identity survives the vocabulary check; a flag that could turn
those off would be a model deciding when the protocol applies to it. What the model says about
its own certainty changes nothing, in either direction: a confident reading of words that are
not in the sentence is refused, and a hesitant reading of words that are is accepted.

Nothing here reaches a database, a provider, a clock or the environment. It is given a context
and a reading and returns a conclusion, which is what makes "what would PromisePatch do with
this model output" answerable without a model or a database in the room.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from promise_graph.model import ExceptionCategory, ResourceKind
from promisepatch.domain import interpretation
from promisepatch.domain.observation import (
    EscalationReason,
    HumanInterpretationRequired,
    InterpretationOutcome,
    ObservationContext,
    ReportKind,
    ResourceView,
)
from promisepatch.semantic import (
    CandidateCommitment,
    CandidateCommitmentLine,
    CandidateEquipment,
    CandidateNodeType,
    CandidateResource,
    InterpretUtteranceRequest,
    ObservationInterpretation,
    SemanticMetadata,
    UntrustedText,
)

SUPPORTED_CATEGORIES: Final[tuple[ExceptionCategory, ...]] = (
    ExceptionCategory.SUPPLY_NOT_RECEIVED,
    ExceptionCategory.STOCK_UNUSABLE,
    ExceptionCategory.EQUIPMENT_UNAVAILABLE,
)
"""The three categories the MVP supports, in the order the specification names them.

Offered to the model as the whole of what it may choose from, and checked again on the way
back. A worker reporting a late pickup or a quality complaint is outside this list, and the
answer to that is a person, not a fourth category invented at runtime.
"""

FALLBACK_REASONS: Final[frozenset[EscalationReason]] = frozenset(
    {
        EscalationReason.NO_CATEGORY,
        EscalationReason.AMBIGUOUS_CATEGORY,
        EscalationReason.NO_RESOURCE,
        EscalationReason.RESOURCE_KIND_MISMATCH,
    }
)
"""The deterministic stops a second reading could plausibly get past, and no others.

Every member is a *parse* failure: the lexicon did not recognise the phrasing, or recognised
two phrasings at once, or matched no word the bakery has authored. A model reading the same
sentence may genuinely do better at those.

The ones deliberately absent are the stops where a second reading would have to invent
something rather than read it:

``AMBIGUOUS_RESOURCE``
    The sentence names two of the bakery's ingredients. Both readings are correct; choosing
    between them is the worker's to do, and a model preferring one would be guessing with
    extra steps.
``NO_OPEN_COMMITMENT``
    The resource resolved and there is no open delivery of it. No amount of understanding
    creates a commitment that does not exist.
``UNKNOWN_QUANTITY``
    A number the worker did not say. A model that supplied one would be attesting.
``CLARIFICATION_*`` and ``CORRECTION_*``
    The clarification and correction protocols answer against options derived from stored
    rows. Neither is a reading of an open-ended sentence, so neither has a parse failure for a
    second reading to improve on.
"""


class GroundingFailure(StrEnum):
    """Why a reading did not become a binding. Every member is a place we stopped instead.

    Recorded as provenance so the ledger can distinguish "the model named something we never
    offered it" from "the model read the sentence and the sentence still does not say which
    ingredient" -- two very different things for whoever has to look at the case.
    """

    NONE = "NONE"
    """The reading grounded. The outcome after this point is the deterministic reader's."""

    UNKNOWN_CANDIDATE = "UNKNOWN_CANDIDATE"
    """An identifier that is not in the candidate set this interpretation offered.

    Reached even for an identifier that names a real row: existing in the database is not the
    test, having been deterministically offered *for this reading* is.
    """

    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    """The sentence is not about supply, stock or equipment, and the reading says so."""

    NO_CATEGORY = "NO_CATEGORY"
    """The reading named no category, so there is nothing to resolve."""

    CATEGORY_NOT_OFFERED = "CATEGORY_NOT_OFFERED"
    """A category outside the three this request permitted."""

    NO_CONFIRMED_RESOURCE = "NO_CONFIRMED_RESOURCE"
    """Nothing the reading proposed is named in the worker's own words.

    The load-bearing refusal. It is what "the berries didn't arrive" reaches when a model
    confidently answers ``raspberries``: plausible, well-formed, grounded in the candidate set,
    and resting on nothing the bakery wrote down.
    """

    AMBIGUOUS_RESOURCE = "AMBIGUOUS_RESOURCE"
    """More than one of the bakery's things is named, and the sentence does not choose."""


@dataclass(frozen=True, slots=True)
class Grounding:
    """What became of a reading, in enough detail to answer for it afterwards.

    Deliberately identifiers and outcomes rather than text. It says which candidates were
    offered, which the reading named, which survived the vocabulary check and which did not --
    and nothing about how a model arrived at any of it. There is no prompt here, no model
    prose, and no reasoning: those are neither evidence nor ours to keep.
    """

    failure: GroundingFailure
    category: ExceptionCategory | None = None
    accepted: tuple[str, ...] = ()
    """The identifiers deterministic code went on to use. At most one, in this design."""

    proposed: tuple[str, ...] = ()
    """Every identifier the reading named, in the order it named them."""

    dropped: tuple[str, ...] = ()
    """Offered candidates the reading named that the worker's words do not support."""

    detail: str = ""

    @property
    def grounded(self) -> bool:
        return self.failure is GroundingFailure.NONE

    def as_payload(self) -> dict[str, object]:
        """The provenance shape persisted on an audit row and a step result."""
        return {
            "failure": self.failure.value,
            "category": None if self.category is None else self.category.value,
            "accepted": list(self.accepted),
            "proposed": list(self.proposed),
            "dropped": list(self.dropped),
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class SemanticResolution:
    """The application's decision about one reading: an ordinary outcome, plus why.

    ``outcome`` is a member of the same union the deterministic interpreter returns, and that
    is the whole design: whatever happens next is decided by code that cannot tell how the
    binding was arrived at.
    """

    outcome: InterpretationOutcome
    grounding: Grounding


# --------------------------------------------------------------- the fallback condition


def is_fallback_eligible(context: ObservationContext, outcome: HumanInterpretationRequired) -> bool:
    """Whether this deterministic stop is one a second reading may be asked about.

    Three conditions, all of them cheap and all of them about state rather than about words.
    A statement that is not the original report is excluded outright: a clarification answer is
    resolved against option codes derived from stored rows, and a correction may only restate
    the outcome of lines that are already bound. Neither is an open-ended sentence, and putting
    either in front of a model would be inviting it to choose a physical outcome.
    """
    return (
        context.current.kind is ReportKind.REPORT
        and context.bound is None
        and outcome.reason in FALLBACK_REASONS
    )


# ------------------------------------------------------------------ the candidate set


def build_request(
    context: ObservationContext, *, case_id: UUID | None = None
) -> InterpretUtteranceRequest:
    """The one question this reading may put to a model, built from persisted rows alone.

    What goes in is the bakery's operational vocabulary and nothing else: the ingredients it
    could plausibly be about, the deliveries still open, the equipment, and the worker's
    sentence. What stays out is everything a model has no business reading in order to answer
    "which of these was spoken about" -- customers, orders, promises, recipes, prices, other
    cases, the audit ledger.

    The narrowing is deterministic and states its own reasons:

    * an **ingredient** is offered when it is on a line of an open delivery or the ledger knows
      how much of it is on hand -- the two ways an ingredient can be the subject of a supply or
      a stock exception at all;
    * a **delivery** is offered when at least one of its lines is still expected, and it
      carries only those lines, because a line that has already been settled is a fact somebody
      attested rather than a candidate for one;
    * **equipment** is offered whole, because there is a handful of it and every piece can
      fail.

    Quantities are absent throughout. A model that was never shown a number cannot hand one
    back as though it were an observation.
    """
    resources = tuple(
        CandidateResource(id=item.id, name=item.name, aliases=item.aliases)
        for item in context.resources
        if item.kind is ResourceKind.INGREDIENT and _offerable(context, item)
    )
    commitments = tuple(
        CandidateCommitment(
            id=commitment.id,
            supplier_name=commitment.supplier_name,
            due_at=commitment.due_at,
            lines=tuple(
                CandidateCommitmentLine(id=line.id, resource_id=line.resource_id)
                for line in commitment.open_lines
            ),
        )
        for commitment in context.commitments
        if commitment.open_lines
    )
    equipment = tuple(
        CandidateEquipment(id=item.id, name=item.name)
        for item in context.resources
        if item.kind is ResourceKind.EQUIPMENT
    )
    return InterpretUtteranceRequest(
        utterance=UntrustedText(text=context.report.raw_text),
        categories=SUPPORTED_CATEGORIES,
        resources=resources,
        commitments=commitments,
        equipment=equipment,
        metadata=SemanticMetadata(case_id=None if case_id is None else str(case_id)),
    )


def _offerable(context: ObservationContext, resource: ResourceView) -> bool:
    """An ingredient is a candidate if a delivery still owes it or the ledger has counted it."""
    if resource.id in context.on_hand:
        return True
    return any(
        line.resource_id == resource.id
        for commitment in context.commitments
        for line in commitment.open_lines
    )


def request_fingerprint(request: InterpretUtteranceRequest, context: ObservationContext) -> str:
    """A stable identity for "this sentence, against this vocabulary, at this point".

    A reading is an answer to one question, and this is that question's name. It covers the
    words, every candidate they were offered against, the categories, and how far into the
    clarification protocol the case had got -- so a delivery corrected, a line settled, a
    resource renamed or a question already asked between the call and its consumption all
    change it.

    The consuming transaction recomputes it under the case lock and refuses a reading whose
    fingerprint no longer matches. That is what stops an answer to a question about a kitchen
    that has since changed from being applied to the kitchen as it is now.
    """
    payload = {
        "statement": str(context.report.id),
        "clarifications_asked": context.clarifications_asked,
        "request": json.loads(request.model_dump_json(exclude={"metadata"})),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# ------------------------------------------------------------------- the resolution


def resolve_semantic_observation(
    context: ObservationContext,
    reading: ObservationInterpretation,
    *,
    deterministic_reason: EscalationReason,
) -> SemanticResolution:
    """Decide what one reading is worth, and hand the rest to the deterministic interpreter.

    ``deterministic_reason`` is the stop that caused the model to be asked in the first place.
    A reading that does not ground restores it: the sentence is still unread for the reason it
    was always unread, and inventing a new one would tell an operator to go and look at a
    model when what they need to look at is the sentence.
    """
    request = build_request(context)
    proposed = tuple(binding.node_id for binding in reading.bindings)

    unknown = _unknown_candidates(request, reading)
    if unknown:
        return _refuse(
            deterministic_reason,
            Grounding(
                failure=GroundingFailure.UNKNOWN_CANDIDATE,
                proposed=proposed,
                dropped=unknown,
                detail=f"the reading named {', '.join(unknown)}, which was not offered to it",
            ),
        )

    if reading.out_of_scope:
        return _refuse(
            deterministic_reason,
            Grounding(
                failure=GroundingFailure.OUT_OF_SCOPE,
                proposed=proposed,
                detail="the reading places the sentence outside supply, stock and equipment",
            ),
        )
    if reading.category is None:
        return _refuse(
            deterministic_reason,
            Grounding(
                failure=GroundingFailure.NO_CATEGORY,
                proposed=proposed,
                detail="the reading named no exception category",
            ),
        )
    if reading.category not in request.categories:
        return _refuse(
            deterministic_reason,
            Grounding(
                failure=GroundingFailure.CATEGORY_NOT_OFFERED,
                proposed=proposed,
                detail=f"category {reading.category.value} was not offered to the reading",
            ),
        )

    category = reading.category
    wanted = interpretation.CATEGORY_KINDS[category]
    named = _named_resources(context, reading)
    confirmed = tuple(
        item for item in named if item.kind is wanted and interpretation.mentions(context, item)
    )
    dropped = tuple(item.id for item in named if item not in confirmed)

    if not confirmed:
        return _refuse(
            deterministic_reason,
            Grounding(
                failure=GroundingFailure.NO_CONFIRMED_RESOURCE,
                category=category,
                proposed=proposed,
                dropped=dropped,
                detail=(
                    f"nothing the reading proposed for {category.value} is named in the "
                    f"worker's own words"
                ),
            ),
        )
    if len(confirmed) > 1:
        return _refuse(
            deterministic_reason,
            Grounding(
                failure=GroundingFailure.AMBIGUOUS_RESOURCE,
                category=category,
                proposed=proposed,
                dropped=dropped,
                detail="the report names " + ", ".join(item.name for item in confirmed),
            ),
        )

    resource = confirmed[0]
    return SemanticResolution(
        outcome=interpretation.interpret_grounded(context, category=category, resource=resource),
        grounding=Grounding(
            failure=GroundingFailure.NONE,
            category=category,
            accepted=(resource.id,),
            proposed=proposed,
            dropped=dropped,
            detail=f"{resource.name} is named in the report",
        ),
    )


def _refuse(reason: EscalationReason, grounding: Grounding) -> SemanticResolution:
    """No binding. The case goes to a person under the stop that sent it here."""
    return SemanticResolution(
        outcome=HumanInterpretationRequired(reason=reason, detail=grounding.detail),
        grounding=grounding,
    )


def _unknown_candidates(
    request: InterpretUtteranceRequest, reading: ObservationInterpretation
) -> tuple[str, ...]:
    """Identifiers the reading names that this request did not offer, in the order named.

    Checked again here, against the candidate set as it stands *now*, even though the semantic
    boundary already checked it against the set as it stood when the call was made. The two
    sets are usually identical and the day they are not is the day this matters: a line settled
    while the model was answering is no longer a candidate, and a reading that names it is
    answering about a kitchen that has moved on.
    """
    allowed: Mapping[CandidateNodeType, frozenset[str]] = {
        CandidateNodeType.RESOURCE: frozenset(item.id for item in request.resources),
        CandidateNodeType.COMMITMENT: frozenset(item.id for item in request.commitments),
        CandidateNodeType.COMMITMENT_LINE: frozenset(
            line.id for commitment in request.commitments for line in commitment.lines
        ),
        CandidateNodeType.EQUIPMENT: frozenset(item.id for item in request.equipment),
    }
    return tuple(
        binding.node_id
        for binding in reading.bindings
        if binding.node_id not in allowed[binding.node_type]
    )


def _named_resources(
    context: ObservationContext, reading: ObservationInterpretation
) -> tuple[ResourceView, ...]:
    """The bakery's own rows for every resource and equipment binding, deduplicated.

    Commitment and commitment-line bindings are read past deliberately. Which delivery a
    sentence is about is decided by the deterministic reader from the supplier the worker named
    and the day they said -- or asked as a question when neither settles it. A model preferring
    one open delivery over another would be choosing between two different claims about the
    world on the strength of how a sentence sounded.
    """
    wanted = (CandidateNodeType.RESOURCE, CandidateNodeType.EQUIPMENT)
    seen: dict[str, ResourceView] = {}
    for binding in reading.bindings:
        if binding.node_type not in wanted or binding.node_id in seen:
            continue
        resource = context.resource(binding.node_id)
        if resource is not None:
            seen[binding.node_id] = resource
    return tuple(seen.values())


__all__: Sequence[str] = [
    "FALLBACK_REASONS",
    "SUPPORTED_CATEGORIES",
    "Grounding",
    "GroundingFailure",
    "SemanticResolution",
    "build_request",
    "is_fallback_eligible",
    "request_fingerprint",
    "resolve_semantic_observation",
]
