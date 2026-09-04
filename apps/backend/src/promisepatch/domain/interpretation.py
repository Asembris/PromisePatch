"""The deterministic reading of a worker's sentence. Pure, closed-vocabulary, fail-closed.

There is no model here and no room for one. The interpreter matches a fixed lexicon of English
markers and vocabulary drawn from persisted rows, and it may reach exactly one of four
conclusions: a binding the words support, a question whose candidates came from the graph, a
correction to lines that are already bound, or "a person has to look at this".

**It never invents a physical fact.** Every branch that could have guessed instead stops. A
report naming two ingredients, a delivery that also contained something the worker did not
mention, an unusable-stock report with no attested quantity -- each becomes a question or an
escalation, never a settled line. That is what makes the clarification in the canonical demo
*consequential*: the system genuinely does not know whether the strawberries arrived, and what
it does with them depends entirely on the worker's answer.

**Parameters of the reading are inputs, not ambient state.** ``now`` and the bakery's calendar
day arrive on the context, because "today's delivery" is a claim about the kitchen's day and
this module is not allowed to know what time it is or where the bakery is.

Where the lexicon is thin, it is thin in the safe direction. ``failed`` is not an equipment
marker because a delivery can fail; ``is off`` is not a spoilage marker because an oven can be
off. A phrase this module does not recognise produces ``NEEDS_HUMAN_INTERPRETATION`` with the
worker's words intact, which costs somebody thirty seconds. A phrase it recognises wrongly
would settle a delivery that arrived.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from promise_graph.model import ExceptionCategory, ReceivedState, ResourceKind
from promisepatch.domain.model import (
    EVENT_STEP_COMPLETED,
    EVENT_STEP_SKIPPED,
    TERMINAL_CASE_STATES,
    CaseChange,
    CreateStep,
    Disposition,
    StepOutcome,
)
from promisepatch.domain.observation import (
    CASE_INTERPRETING,
    STEP_RESOLVE_OBSERVATION,
    WHOLE_DELIVERY_CODE,
    ClarificationOption,
    ClarificationRequired,
    ClarificationSlot,
    ClarificationView,
    CommitmentLineView,
    CommitmentView,
    CorrectionResolved,
    EscalationReason,
    HumanInterpretationRequired,
    InterpretationOutcome,
    LineOutcome,
    ObservationContext,
    ReportKind,
    ResolvedObservation,
    ResourceView,
    just_code,
    resolve_step_key,
    statement_id_of,
)

# --------------------------------------------------------------------------------- lexicon


def normalize(text: str) -> str:
    """Lower-case, strip every non-alphanumeric character to a space, collapse runs.

    ``didn't`` becomes ``didn t``, which is why every marker below is written in the same
    shape. One normalisation for text and markers alike means an apostrophe, an em dash or a
    double space can never be the reason a sentence is not understood.
    """
    return " ".join("".join(c if c.isalnum() else " " for c in text.lower()).split())


def _phrases(*raw: str) -> tuple[str, ...]:
    return tuple(normalize(item) for item in raw)


SUPPLY_MARKERS: Final = _phrases(
    "didn't arrive",
    "did not arrive",
    "never arrived",
    "hasn't arrived",
    "has not arrived",
    "didn't come",
    "did not come",
    "never came",
    "didn't show up",
    "did not show up",
    "never showed up",
    "didn't turn up",
    "never turned up",
    "not delivered",
    "wasn't delivered",
    "no delivery",
)
"""Arrival negations only. Nothing here can be said about a fridge or a tray of cream."""

STOCK_MARKERS: Final = _phrases(
    "went off",
    "gone off",
    "has gone off",
    "spoiled",
    "spoilt",
    "unusable",
    "not usable",
    "ruined",
    "curdled",
    "thrown out",
    "has to be binned",
)

EQUIPMENT_MARKERS: Final = _phrases(
    "is down",
    "are down",
    "went down",
    "is broken",
    "broke down",
    "broken down",
    "not working",
    "isn't working",
    "out of order",
    "stopped working",
    "has failed",
    "won't start",
    "will not start",
)

_CATEGORY_MARKERS: Final[Mapping[ExceptionCategory, tuple[str, ...]]] = {
    ExceptionCategory.SUPPLY_NOT_RECEIVED: SUPPLY_MARKERS,
    ExceptionCategory.STOCK_UNUSABLE: STOCK_MARKERS,
    ExceptionCategory.EQUIPMENT_UNAVAILABLE: EQUIPMENT_MARKERS,
}

_CATEGORY_KINDS: Final[Mapping[ExceptionCategory, ResourceKind]] = {
    ExceptionCategory.SUPPLY_NOT_RECEIVED: ResourceKind.INGREDIENT,
    ExceptionCategory.STOCK_UNUSABLE: ResourceKind.INGREDIENT,
    ExceptionCategory.EQUIPMENT_UNAVAILABLE: ResourceKind.EQUIPMENT,
}

TODAY_MARKERS: Final = _phrases("today", "this morning", "this afternoon", "tonight")

PARTIAL_MARKERS: Final = _phrases(
    "some", "some of", "a few", "part of", "half", "a couple", "several", "a bit of", "most of"
)
"""Phrases that say *not all of it* without saying how much.

An unqualified spoilage report is a total loss and the architecture says so; a partial one
needs a number, and no number may be synthesized, so it goes to a human.
"""

POSITIVE_MARKERS: Final = _phrases(
    "came",
    "came in",
    "arrived",
    "did arrive",
    "turned up",
    "showed up",
    "is here",
    "are here",
    "was here",
    "were here",
    "delivered",
    "did come",
    "we got",
    "we have",
)

NEGATIVE_MARKERS: Final = _phrases(
    "didn't arrive",
    "did not arrive",
    "never arrived",
    "didn't come",
    "did not come",
    "never came",
    "missing",
    "not here",
    "didn't show up",
    "never showed up",
    "not delivered",
    "didn't turn up",
    "wasn't there",
    "weren't there",
    "short",
)

RESTRICT_MARKERS: Final = _phrases("just", "only", "nothing but")

WHOLE_MARKERS: Final = _phrases("whole", "entire", "all", "all of it", "everything", "the lot")

EM_DASH, EN_DASH = chr(0x2014), chr(0x2013)
"""Written as code points rather than as glyphs: an em dash and an en dash are not the
same separator, and in a source file they are indistinguishable to a reader.
"""

_CLAUSE_SEPARATORS: Final = (
    EM_DASH,
    EN_DASH,
    ";",
    ",",
    ".",
    "!",
    "?",
    " - ",
    " but ",
    " and ",
    " though ",
    " while ",
    " however ",
)

_CLAUSE_PATTERN: Final = re.compile(
    "|".join(re.escape(separator) for separator in _CLAUSE_SEPARATORS)
)
"""Where one claim about the world ends and the next begins.

Split on the raw sentence rather than the normalised one, because normalisation removes the
punctuation that marks the boundary. ``and`` is a separator too: "the raspberries and the
strawberries didn't arrive" is two claims that happen to share a verb.
"""


def _contains(haystack: str, needle: str) -> bool:
    """Whole-word containment over normalised text. ``off`` never matches inside ``coffee``."""
    return f" {needle} " in f" {haystack} "


def _any(haystack: str, needles: Iterable[str]) -> bool:
    return any(_contains(haystack, needle) for needle in needles)


def _mentions(normalized: str, resource: ResourceView) -> bool:
    return _any(normalized, resource.terms)


def _matched_resources(context: ObservationContext, normalized: str) -> tuple[ResourceView, ...]:
    return tuple(
        sorted(
            (item for item in context.resources if _mentions(normalized, item)),
            key=lambda item: item.id,
        )
    )


# ---------------------------------------------------------------------------- the step shape


def begin(*, case_state: str, step_key: str) -> StepOutcome:
    """Move a case into ``INTERPRETING`` and enqueue the step that does the reading.

    Two steps rather than one, because "we are interpreting this" is a durable fact worth
    having: a worker that dies between the two leaves a case that visibly reached
    ``INTERPRETING`` and a resolve step that the next worker claims. The successor's key is
    derived from this one, so a transaction that ran, failed to commit and ran again proposes
    the identical key and the unique index refuses the duplicate.
    """
    if case_state in TERMINAL_CASE_STATES:
        return StepOutcome(
            disposition=Disposition.SKIPPED,
            event_type=EVENT_STEP_SKIPPED,
            result={"skipped_because": case_state},
        )
    statement_id = statement_id_of(step_key)
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=CASE_INTERPRETING),
        successors=(
            CreateStep(step_key=resolve_step_key(statement_id), kind=STEP_RESOLVE_OBSERVATION),
        ),
        result={"statement": str(statement_id), "case_state": CASE_INTERPRETING},
    )


# ------------------------------------------------------------------------------ entry point


def interpret(context: ObservationContext) -> InterpretationOutcome:
    """Read one statement against the graph. Deterministic in ``context`` alone."""
    if context.current.kind is ReportKind.CORRECTION:
        return _interpret_correction(context)
    return _interpret_report(context)


# --------------------------------------------------------------------------------- reports


def _interpret_report(context: ObservationContext) -> InterpretationOutcome:
    """The original report, optionally narrowed by an answer to a question we asked."""
    pinned_commitment: str | None = None
    pinned_scope: tuple[str, ...] | None = None

    if context.current.kind is ReportKind.CLARIFICATION_ANSWER:
        clarification = context.open_clarification
        if clarification is None or clarification.answer_text is None:
            return HumanInterpretationRequired(
                reason=EscalationReason.CLARIFICATION_UNRESOLVED,
                detail="a clarification answer arrived with no open question to answer",
            )
        chosen = _resolve_answer(context, clarification)
        if chosen is not None:
            pinned_commitment = chosen.commitment_id
            pinned_scope = chosen.scope_line_ids or None

    outcome = _resolve(context, pinned_commitment=pinned_commitment, pinned_scope=pinned_scope)
    if isinstance(outcome, ClarificationRequired) and not context.may_ask_again:
        return HumanInterpretationRequired(
            reason=EscalationReason.CLARIFICATION_CEILING_REACHED,
            detail=(
                f"still ambiguous after {context.clarifications_asked} clarifications; "
                f"the {outcome.slot.value.lower()} needs an owner to bind it"
            ),
        )
    return outcome


def _resolve(
    context: ObservationContext,
    *,
    pinned_commitment: str | None,
    pinned_scope: tuple[str, ...] | None,
) -> InterpretationOutcome:
    normalized = normalize(context.report.raw_text)

    category = _category(context, normalized)
    if isinstance(category, HumanInterpretationRequired):
        return category

    resource = _resource(context, normalized, category)
    if isinstance(resource, HumanInterpretationRequired):
        return resource

    if category is ExceptionCategory.SUPPLY_NOT_RECEIVED:
        return _resolve_supply(
            context,
            normalized,
            resource,
            pinned_commitment=pinned_commitment,
            pinned_scope=pinned_scope,
        )
    if category is ExceptionCategory.STOCK_UNUSABLE:
        return _resolve_stock(context, normalized, resource)
    return ResolvedObservation(
        category=ExceptionCategory.EQUIPMENT_UNAVAILABLE, resource_id=resource.id
    )


def _category(
    context: ObservationContext, normalized: str
) -> ExceptionCategory | HumanInterpretationRequired:
    """Which kind of physical exception this is, or nothing at all.

    Two categories matching is not a tie to be broken by ordering them; it is a sentence this
    build cannot read. The only narrowing permitted is by the kind of resource actually named,
    which is evidence rather than preference.
    """
    candidates = [
        category for category, markers in _CATEGORY_MARKERS.items() if _any(normalized, markers)
    ]
    if not candidates:
        return HumanInterpretationRequired(
            reason=EscalationReason.NO_CATEGORY,
            detail="no supply, stock or equipment marker in the report",
        )
    if len(candidates) == 1:
        return candidates[0]

    kinds = {item.kind for item in _matched_resources(context, normalized)}
    narrowed = [item for item in candidates if _CATEGORY_KINDS[item] in kinds]
    if len(narrowed) == 1:
        return narrowed[0]
    return HumanInterpretationRequired(
        reason=EscalationReason.AMBIGUOUS_CATEGORY,
        detail="the report reads as " + " and ".join(sorted(item.value for item in candidates)),
    )


def _resource(
    context: ObservationContext, normalized: str, category: ExceptionCategory
) -> ResourceView | HumanInterpretationRequired:
    matched = _matched_resources(context, normalized)
    wanted = _CATEGORY_KINDS[category]
    of_kind = [item for item in matched if item.kind is wanted]

    if not of_kind:
        if matched:
            return HumanInterpretationRequired(
                reason=EscalationReason.RESOURCE_KIND_MISMATCH,
                detail=(
                    f"{category.value} needs a {wanted.value.lower()}; the report names "
                    + ", ".join(item.name for item in matched)
                ),
            )
        return HumanInterpretationRequired(
            reason=EscalationReason.NO_RESOURCE,
            detail="the report names no resource this bakery knows",
        )
    if len(of_kind) > 1:
        return HumanInterpretationRequired(
            reason=EscalationReason.AMBIGUOUS_RESOURCE,
            detail="the report names " + ", ".join(item.name for item in of_kind),
        )
    return of_kind[0]


# ------------------------------------------------------------------------ supply resolution


def _resolve_supply(
    context: ObservationContext,
    normalized: str,
    resource: ResourceView,
    *,
    pinned_commitment: str | None,
    pinned_scope: tuple[str, ...] | None,
) -> InterpretationOutcome:
    candidates = _commitment_candidates(
        context, normalized, resource, pinned_commitment=pinned_commitment
    )
    if not candidates:
        return HumanInterpretationRequired(
            reason=EscalationReason.NO_OPEN_COMMITMENT,
            detail=f"no open commitment line for {resource.name} matches the report",
        )
    if len(candidates) > 1:
        return _commitment_question(context, resource, candidates)

    commitment = candidates[0]
    named = tuple(line for line in commitment.open_lines if line.resource_id == resource.id)
    others = tuple(line for line in commitment.open_lines if line.resource_id != resource.id)

    if pinned_scope is not None:
        open_ids = {line.id for line in commitment.open_lines}
        if set(pinned_scope) <= open_ids and pinned_scope:
            return ResolvedObservation(
                category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
                commitment_id=commitment.id,
                scope_line_ids=tuple(sorted(pinned_scope)),
                resource_id=resource.id,
            )
    if not others:
        return ResolvedObservation(
            category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
            commitment_id=commitment.id,
            scope_line_ids=tuple(sorted(line.id for line in named)),
            resource_id=resource.id,
        )
    return _scope_question(context, resource, commitment, others)


def _commitment_candidates(
    context: ObservationContext,
    normalized: str,
    resource: ResourceView,
    *,
    pinned_commitment: str | None,
) -> tuple[CommitmentView, ...]:
    """Open commitments for this resource, narrowed only by what the report actually says.

    A named supplier and a "today" qualifier are evidence in the sentence; nothing else
    narrows. In particular, "the nearest one" is not a rule, because a delivery due in an hour
    and one due tomorrow are different physical claims.
    """
    candidates = [
        commitment
        for commitment in context.commitments
        if any(line.resource_id == resource.id for line in commitment.open_lines)
    ]
    if pinned_commitment is not None:
        return tuple(item for item in candidates if item.id == pinned_commitment)

    named_supplier = [
        item for item in candidates if _contains(normalized, normalize(item.supplier_name))
    ]
    if named_supplier:
        candidates = named_supplier
    if _any(normalized, TODAY_MARKERS):
        today = [item for item in candidates if context.day_start <= item.due_at < context.day_end]
        if today:
            candidates = today
    return tuple(sorted(candidates, key=lambda item: item.id))


def _commitment_question(
    context: ObservationContext,
    resource: ResourceView,
    candidates: Sequence[CommitmentView],
) -> ClarificationRequired:
    options = tuple(
        ClarificationOption(
            code=_slug(commitment.id),
            label=f"the {commitment.supplier_name} delivery due {_when(commitment.due_at)}",
            keywords=(
                *normalize(commitment.supplier_name).split(),
                _day_word(context, commitment),
            ),
            commitment_id=commitment.id,
        )
        for commitment in candidates
    )
    labels = " or ".join(option.label for option in options)
    return ClarificationRequired(
        slot=ClarificationSlot.COMMITMENT,
        question=f"There is more than one open {resource.name} delivery. Do you mean {labels}?",
        options=options,
        category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
        resource_id=resource.id,
    )


def _scope_question(
    context: ObservationContext,
    resource: ResourceView,
    commitment: CommitmentView,
    others: Sequence[CommitmentLineView],
) -> ClarificationRequired:
    """The consequential one: the delivery held something the worker did not mention.

    Whether those goods are on the bench or still on the van decides how much substitute stock
    the bakery has, and therefore whether a promise can be recovered at all. Guessing either
    way would settle a line nobody attested, so the question is asked -- and its two answers
    are built from the commitment's own rows, never from the sentence.
    """
    other_names = _names(context, others)
    named_lines = tuple(line for line in commitment.open_lines if line.resource_id == resource.id)
    options = (
        ClarificationOption(
            code=WHOLE_DELIVERY_CODE,
            label=f"the whole {commitment.supplier_name} delivery",
            keywords=WHOLE_MARKERS,
            scope_line_ids=tuple(sorted(line.id for line in commitment.open_lines)),
            commitment_id=commitment.id,
        ),
        ClarificationOption(
            code=just_code(resource.name),
            label=f"just the {resource.name}",
            keywords=RESTRICT_MARKERS + resource.terms,
            scope_line_ids=tuple(sorted(line.id for line in named_lines)),
            commitment_id=commitment.id,
        ),
    )
    return ClarificationRequired(
        slot=ClarificationSlot.SCOPE,
        question=(
            f"The {commitment.supplier_name} delivery also includes {_join(other_names)}. "
            f"Did the whole delivery fail, or just the {resource.name}?"
        ),
        options=options,
        category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
        commitment_id=commitment.id,
        resource_id=resource.id,
    )


# ------------------------------------------------------------------------- stock resolution


def _resolve_stock(
    context: ObservationContext, normalized: str, resource: ResourceView
) -> InterpretationOutcome:
    """Unusable stock. Unqualified means all of it; qualified without a number means ask.

    ``None`` is unknown and stays unknown: a report that says *some* of the cream is off has
    told us that a number exists and not what it is, and inventing one would write a physical
    quantity nobody attested.
    """
    if _any(normalized, PARTIAL_MARKERS):
        return HumanInterpretationRequired(
            reason=EscalationReason.UNKNOWN_QUANTITY,
            detail=f"a partial loss of {resource.name} was reported without a quantity",
        )
    if context.on_hand.get(resource.id) is None:
        return HumanInterpretationRequired(
            reason=EscalationReason.UNKNOWN_QUANTITY,
            detail=f"on-hand {resource.name} is unknown, so a total loss has no size",
        )
    return ResolvedObservation(
        category=ExceptionCategory.STOCK_UNUSABLE, resource_id=resource.id, quantity=None
    )


# ------------------------------------------------------------------------- answer resolution


@dataclass(frozen=True, slots=True)
class ScopeReading:
    """What a sentence says about which things arrived and which did not."""

    whole: bool = False
    missing: frozenset[str] = frozenset()
    arrived: frozenset[str] = frozenset()
    conflict: bool = False

    @property
    def usable(self) -> bool:
        return not self.conflict and not (self.missing & self.arrived)


def read_scope(context: ObservationContext, text: str, *, default_missing: bool) -> ScopeReading:
    """Split a sentence into claims and attribute a physical polarity to each.

    ``default_missing`` is what an unqualified mention means, and it differs by why the worker
    is speaking. Answering "did the whole delivery fail, or just the raspberries?" with
    "raspberries" plainly means the raspberries failed. Volunteering "the strawberries" out of
    nowhere in a correction means nothing determinate, and is refused.
    """
    whole = False
    conflict = False
    missing: set[str] = set()
    arrived: set[str] = set()

    for clause in _CLAUSE_PATTERN.split(text.lower()):
        normalized = normalize(clause)
        if not normalized:
            continue
        named = {item.id for item in _matched_resources(context, normalized)}
        positive = _any(normalized, POSITIVE_MARKERS)
        negative = _any(normalized, NEGATIVE_MARKERS)
        if positive and negative:
            conflict = True
            continue
        if _any(normalized, WHOLE_MARKERS) and not named:
            if positive:
                conflict = True
            else:
                whole = True
            continue
        if not named:
            continue
        if positive:
            arrived |= named
        elif negative or _any(normalized, RESTRICT_MARKERS) or default_missing:
            missing |= named

    return ScopeReading(
        whole=whole, missing=frozenset(missing), arrived=frozenset(arrived), conflict=conflict
    )


def _resolve_answer(
    context: ObservationContext, clarification: ClarificationView
) -> ClarificationOption | None:
    """Match an answer to one of the options that were offered, or to none of them.

    An answer that names a scope nobody offered is not a safe deterministic selection, so it
    resolves to nothing and the question is asked again -- or, at the ceiling, a person binds
    it. Choosing the closest option would be exactly the guess this slice exists to avoid.
    """
    answer = clarification.answer_text or ""
    if clarification.slot is ClarificationSlot.SCOPE:
        return _resolve_scope_answer(context, clarification, answer)
    return _resolve_by_keywords(clarification, answer)


def _resolve_scope_answer(
    context: ObservationContext, clarification: ClarificationView, answer: str
) -> ClarificationOption | None:
    reading = read_scope(context, answer, default_missing=True)
    if not reading.usable:
        return None
    if reading.whole and not reading.arrived and not reading.missing:
        return clarification.option(WHOLE_DELIVERY_CODE)

    if not reading.missing:
        return None
    for option in clarification.options:
        if option.code == WHOLE_DELIVERY_CODE:
            continue
        if _resources_of(context, option.scope_line_ids) == reading.missing:
            return option
    whole = clarification.option(WHOLE_DELIVERY_CODE)
    if whole is not None and _resources_of(context, whole.scope_line_ids) == reading.missing:
        return whole
    return None


def _resolve_by_keywords(
    clarification: ClarificationView, answer: str
) -> ClarificationOption | None:
    normalized = normalize(answer)
    scored = [
        (sum(1 for keyword in option.keywords if _contains(normalized, keyword)), option)
        for option in clarification.options
    ]
    best = max((score for score, _ in scored), default=0)
    if best == 0:
        return None
    winners = [option for score, option in scored if score == best]
    return winners[0] if len(winners) == 1 else None


def _resources_of(context: ObservationContext, line_ids: Sequence[str]) -> frozenset[str]:
    wanted = set(line_ids)
    return frozenset(
        line.resource_id
        for commitment in context.commitments
        for line in commitment.lines
        if line.id in wanted
    )


# ---------------------------------------------------------------------------- corrections


def _interpret_correction(context: ObservationContext) -> InterpretationOutcome:
    """A later claim about lines that are already settled.

    Restricted to the delivery the case is already bound to, and to lines that delivery
    actually has. A correction may change what is true about a line; it may never rebind the
    exception to a different commitment, because that would be a different exception.
    """
    bound = context.bound
    if (
        bound is None
        or bound.category is not ExceptionCategory.SUPPLY_NOT_RECEIVED
        or bound.commitment_id is None
    ):
        return HumanInterpretationRequired(
            reason=EscalationReason.NOT_BOUND,
            detail="only a bound supply exception can be corrected deterministically",
        )
    commitment = context.commitment(bound.commitment_id)
    if commitment is None:
        return HumanInterpretationRequired(
            reason=EscalationReason.NOT_BOUND,
            detail=f"commitment {bound.commitment_id} is no longer in the graph",
        )

    reading = read_scope(context, context.current.raw_text, default_missing=False)
    if not reading.usable:
        return HumanInterpretationRequired(
            reason=EscalationReason.CORRECTION_UNRESOLVED,
            detail="the correction says a thing both arrived and did not",
        )

    named = reading.missing | reading.arrived
    on_commitment = {line.resource_id for line in commitment.lines}
    if named - on_commitment:
        return HumanInterpretationRequired(
            reason=EscalationReason.CORRECTION_UNRESOLVED,
            detail="the correction names something this delivery did not contain",
        )

    outcomes = _correction_outcomes(commitment, reading)
    if not outcomes:
        return HumanInterpretationRequired(
            reason=EscalationReason.CORRECTION_UNRESOLVED,
            detail="the correction states no physical outcome for any line of this delivery",
        )
    return CorrectionResolved(outcomes=outcomes)


def _correction_outcomes(
    commitment: CommitmentView, reading: ScopeReading
) -> tuple[LineOutcome, ...]:
    outcomes: list[LineOutcome] = []
    for line in sorted(commitment.lines, key=lambda item: item.id):
        if reading.whole or line.resource_id in reading.missing:
            outcomes.append(
                LineOutcome(commitment_line_id=line.id, received_state=ReceivedState.NOT_RECEIVED)
            )
        elif line.resource_id in reading.arrived:
            outcomes.append(
                LineOutcome(commitment_line_id=line.id, received_state=ReceivedState.RECEIVED)
            )
    return tuple(outcomes)


# ------------------------------------------------------------------------------- formatting


def _names(context: ObservationContext, lines: Iterable[CommitmentLineView]) -> tuple[str, ...]:
    seen: list[str] = []
    for line in lines:
        resource = context.resource(line.resource_id)
        name = resource.name if resource is not None else line.resource_id
        if name not in seen:
            seen.append(name)
    return tuple(seen)


def _join(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return names[0] if names else "nothing else"
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _slug(identifier: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in identifier).upper()


def _when(moment: datetime) -> str:
    """A due time in a form a person can read back to us, and a test can assert on."""
    return moment.isoformat(timespec="minutes")


def _day_word(context: ObservationContext, commitment: CommitmentView) -> str:
    return "today" if context.day_start <= commitment.due_at < context.day_end else "tomorrow"


__all__ = [
    "EQUIPMENT_MARKERS",
    "PARTIAL_MARKERS",
    "STOCK_MARKERS",
    "SUPPLY_MARKERS",
    "ScopeReading",
    "begin",
    "interpret",
    "normalize",
    "read_scope",
]
