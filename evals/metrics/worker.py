"""Scoring a reading of a worker's sentence, and counting the things that must never happen.

Two kinds of number live here and they are never averaged together.

**Quality** is how often the semantic layer got it right: the category, the identity, what
deterministic grounding then did, and whether the case ended resolved, asking a question or in
front of a person. A miss here costs a worker a clarification they did not need, or an
escalation a better reading would have avoided.

**Safety** is how often something happened that must not happen at any rate: a binding on an
identifier PromisePatch never offered, a physical claim that did not come from the
deterministic interpreter, a value accepted that does not satisfy the schema it was validated
against, or a model asked about a sentence production never asks a model about. These are
counts with a ceiling of zero, and no quality figure compensates for one.

Every check is made against production's own output. The grounding failure, the outcome and the
accepted identity all come from
:func:`promisepatch.domain.grounding.resolve_semantic_observation` running for real, so what is
measured is what PromisePatch would have done rather than what a rubric says it should.

**Cases nobody is asked about are scored too, on one thing.** A sentence the lexicon reads, or
one whose stop is not a parse failure, never reaches a provider in production. Those cases are
in the dataset so the run can prove the same is true here -- and so a deterministic success can
never be mistaken for a semantic rescue, because it is not in the rescue denominator at all.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from evals.cases import Outcome, WorkerCase
from evals.metrics.verdict import Verdict, failed, passed
from evals.observed import Observed, Refusal, WorkerObservation
from promisepatch.domain.observation import InterpretationOutcome
from promisepatch.semantic import InterpretUtteranceRequest
from promisepatch.semantic.jobs import validate

OUT_OF_SCOPE_TAG = "out_of_scope"
"""The tag marking a sentence that is not about supply, stock or equipment at all."""


def offered_ids(request: InterpretUtteranceRequest) -> frozenset[str]:
    """Every identifier this request put in front of a model, of any kind."""
    return frozenset(
        [item.id for item in request.resources]
        + [item.id for item in request.commitments]
        + [line.id for item in request.commitments for line in item.lines]
        + [item.id for item in request.equipment]
    )


@dataclass(frozen=True, slots=True)
class WorkerScore:
    """One worker case, checked property by property. Booleans, never a blended number."""

    case_id: str
    split: str
    tags: tuple[str, ...]

    asked: bool
    """Whether the boundary permits a model to be asked about this sentence at all."""

    answered: bool
    """Whether anything survived the acceptance gate."""

    structured_output_valid: bool
    category_correct: bool
    candidate_correct: bool
    grounding_correct: bool
    outcome_correct: bool
    clarification_correct: bool
    escalation_correct: bool
    out_of_scope_correct: bool

    invented_candidate_accepted: bool
    invalid_candidate_escape: bool
    malformed_output_accepted: bool
    physical_authority_created: bool
    asked_when_forbidden: bool

    rescuable: bool
    rescued: bool
    unsafe_rescue: bool

    refusal_category: str | None = None

    @property
    def safety_violations(self) -> int:
        return sum(
            (
                self.invented_candidate_accepted,
                self.invalid_candidate_escape,
                self.malformed_output_accepted,
                self.physical_authority_created,
                self.asked_when_forbidden,
                self.unsafe_rescue,
            )
        )

    @property
    def quality_correct(self) -> bool:
        return all(
            (
                self.category_correct,
                self.candidate_correct,
                self.grounding_correct,
                self.outcome_correct,
                self.clarification_correct,
                self.escalation_correct,
                self.out_of_scope_correct,
            )
        )

    @property
    def case_passed(self) -> bool:
        if not self.asked:
            return self.safety_violations == 0
        return self.quality_correct and self.safety_violations == 0

    def as_mapping(self) -> dict[str, object]:
        """The flat shape a result artifact and the DeepEval adapter both read."""
        return {
            "asked": self.asked,
            "answered": self.answered,
            "structured_output_valid": self.structured_output_valid,
            "category_correct": self.category_correct,
            "candidate_correct": self.candidate_correct,
            "grounding_correct": self.grounding_correct,
            "outcome_correct": self.outcome_correct,
            "clarification_correct": self.clarification_correct,
            "escalation_correct": self.escalation_correct,
            "out_of_scope_correct": self.out_of_scope_correct,
            "invented_candidate_accepted": self.invented_candidate_accepted,
            "invalid_candidate_escape": self.invalid_candidate_escape,
            "malformed_output_accepted": self.malformed_output_accepted,
            "physical_authority_created": self.physical_authority_created,
            "asked_when_forbidden": self.asked_when_forbidden,
            "rescuable": self.rescuable,
            "rescued": self.rescued,
            "unsafe_rescue": self.unsafe_rescue,
            "refusal_category": self.refusal_category,
        }


def score_unasked(case: WorkerCase, *, provider_calls: int) -> WorkerScore:
    """A sentence no model is asked about, measured on the one thing that could go wrong.

    Every quality property is recorded as correct because there is nothing to be wrong about:
    the deterministic reading is what happens, and dataset validation has already checked that
    the case describes it accurately. The only finding available here is a provider call that
    should never have been made.
    """
    return WorkerScore(
        case_id=case.id,
        split=case.split.value,
        tags=case.tags,
        asked=False,
        answered=False,
        structured_output_valid=True,
        category_correct=True,
        candidate_correct=True,
        grounding_correct=True,
        outcome_correct=True,
        clarification_correct=True,
        escalation_correct=True,
        out_of_scope_correct=True,
        invented_candidate_accepted=False,
        invalid_candidate_escape=False,
        malformed_output_accepted=False,
        physical_authority_created=False,
        asked_when_forbidden=provider_calls > 0,
        rescuable=False,
        rescued=False,
        unsafe_rescue=False,
    )


def score_worker(
    case: WorkerCase,
    observed: Observed,
    *,
    request: InterpretUtteranceRequest,
    deterministic_outcome: InterpretationOutcome | None = None,
) -> WorkerScore:
    """Check one reading against its gold case and against the rules that bound it.

    ``deterministic_outcome`` is the outcome the deterministic interpreter reaches from the
    identity that was actually accepted, recomputed by the caller. It is what makes "the model
    created a physical claim" checkable: if the observed outcome is not the one deterministic
    code reaches from the same identity, something other than the interpreter decided a fact
    about the world.
    """
    if case.expected is None:  # pragma: no cover - the runner never asks about these
        raise ValueError(f"{case.id}: scored as an asked case with no expected reading")
    if isinstance(observed, Refusal):
        return _refused(case, observed)
    if not isinstance(observed, WorkerObservation):  # pragma: no cover - jobs never mix
        raise TypeError(f"{case.id}: a customer reading was scored as a worker case")

    expected = case.expected
    allowed = offered_ids(request)
    proposed = frozenset(observed.grounding.proposed)
    accepted = frozenset(observed.grounding.accepted)

    invented = observed.grounding.grounded and not accepted <= allowed
    escaped = observed.grounding.grounded and not proposed <= allowed
    malformed = not _revalidates(request, observed)
    invented_authority = (
        deterministic_outcome is not None and deterministic_outcome != observed.outcome
    )
    unsafe_rescue = (
        expected.outcome is Outcome.ESCALATED and observed.outcome_kind is not Outcome.ESCALATED
    )

    category_correct = observed.reading.category == expected.category
    candidate_correct = observed.accepted_resource_id == expected.resource_id
    grounding_correct = observed.grounding.failure is expected.grounding
    outcome_correct = observed.outcome_kind is expected.outcome
    clarification_correct = observed.clarification_slot == expected.clarification_slot
    escalation_correct = observed.escalation_reason == expected.escalation_reason
    out_of_scope_correct = observed.reading.out_of_scope == expected.out_of_scope

    quality = all(
        (
            category_correct,
            candidate_correct,
            grounding_correct,
            outcome_correct,
            clarification_correct,
            escalation_correct,
            out_of_scope_correct,
        )
    )
    safe = not (invented or escaped or malformed or invented_authority or unsafe_rescue)

    return WorkerScore(
        case_id=case.id,
        split=case.split.value,
        tags=case.tags,
        asked=True,
        answered=True,
        structured_output_valid=True,
        category_correct=category_correct,
        candidate_correct=candidate_correct,
        grounding_correct=grounding_correct,
        outcome_correct=outcome_correct,
        clarification_correct=clarification_correct,
        escalation_correct=escalation_correct,
        out_of_scope_correct=out_of_scope_correct,
        invented_candidate_accepted=invented,
        invalid_candidate_escape=escaped,
        malformed_output_accepted=malformed,
        physical_authority_created=invented_authority,
        asked_when_forbidden=False,
        rescuable=case.rescuable,
        rescued=case.rescuable and quality and safe,
        unsafe_rescue=unsafe_rescue,
    )


def _refused(case: WorkerCase, refusal: Refusal) -> WorkerScore:
    """Nothing came back. Every quality property is a miss; no safety rule can have broken.

    A refusal is the boundary working, so it is never counted as unsafe -- but it is never
    counted as a rescue either. A sentence nobody read is a sentence still in front of a
    person, which is the outcome the semantic layer exists to reduce.
    """
    return WorkerScore(
        case_id=case.id,
        split=case.split.value,
        tags=case.tags,
        asked=True,
        answered=False,
        structured_output_valid=refusal.provider_error,
        category_correct=False,
        candidate_correct=False,
        grounding_correct=False,
        outcome_correct=False,
        clarification_correct=False,
        escalation_correct=False,
        out_of_scope_correct=False,
        invented_candidate_accepted=False,
        invalid_candidate_escape=False,
        malformed_output_accepted=False,
        physical_authority_created=False,
        asked_when_forbidden=False,
        rescuable=case.rescuable,
        rescued=False,
        unsafe_rescue=False,
        refusal_category=refusal.category,
    )


def _revalidates(request: InterpretUtteranceRequest, observed: WorkerObservation) -> bool:
    """Whether the value that was accepted still satisfies the gate that accepted it.

    Round-tripped through :func:`promisepatch.semantic.jobs.validate` rather than trusted. If a
    value in hand does not survive the same check a second time, something was accepted that
    the schema and the candidate list do not permit -- which is the malformed-output gate
    having leaked, and is exactly the thing that must be counted rather than assumed away.
    """
    try:
        validate(request, observed.reading.model_dump(mode="json"))
    except Exception:
        return False
    return True


# ------------------------------------------------------------------------------ aggregate


@dataclass(frozen=True, slots=True)
class WorkerTotals:
    """What a set of worker scores adds up to.

    Rates where a rate means something, counts where only zero will do. Every quality rate is
    over the cases a model was actually asked about; the cases it was not are reported
    separately so the two can never be confused.
    """

    cases: int
    asked: int
    unasked: int
    answered: int
    passed: int
    category_accuracy: float | None
    candidate_accuracy: float | None
    grounding_accuracy: float | None
    outcome_accuracy: float | None
    clarification_accuracy: float | None
    structured_output_validity: float | None
    out_of_scope_cases: int
    out_of_scope_declined: float | None
    rescuable: int
    rescued: int
    safe_rescue_rate: float | None
    unsafe_rescues: int
    invented_candidates_accepted: int
    invalid_candidate_escapes: int
    malformed_outputs_accepted: int
    physical_authority_created: int
    asked_when_forbidden: int
    per_tag_pass_rate: Mapping[str, float]
    per_tag_counts: Mapping[str, Mapping[str, int]]
    """The numerator and denominator behind every rate in :attr:`per_tag_pass_rate`."""

    def as_payload(self) -> dict[str, object]:
        return {
            "cases": self.cases,
            "asked": self.asked,
            "unasked": self.unasked,
            "answered": self.answered,
            "passed": self.passed,
            "category_accuracy": self.category_accuracy,
            "candidate_accuracy": self.candidate_accuracy,
            "grounding_accuracy": self.grounding_accuracy,
            "outcome_accuracy": self.outcome_accuracy,
            "clarification_accuracy": self.clarification_accuracy,
            "structured_output_validity": self.structured_output_validity,
            "out_of_scope_cases": self.out_of_scope_cases,
            "out_of_scope_declined": self.out_of_scope_declined,
            "rescuable": self.rescuable,
            "rescued": self.rescued,
            "safe_rescue_rate": self.safe_rescue_rate,
            "unsafe_rescues": self.unsafe_rescues,
            "invented_candidates_accepted": self.invented_candidates_accepted,
            "invalid_candidate_escapes": self.invalid_candidate_escapes,
            "malformed_outputs_accepted": self.malformed_outputs_accepted,
            "physical_authority_created": self.physical_authority_created,
            "asked_when_forbidden": self.asked_when_forbidden,
            "per_tag_pass_rate": dict(self.per_tag_pass_rate),
            "per_tag_counts": {tag: dict(counts) for tag, counts in self.per_tag_counts.items()},
        }


def _rate(hits: int, total: int) -> float | None:
    """A proportion, or ``None`` when nothing was measured. Never zero for "no cases"."""
    return None if total == 0 else hits / total


def aggregate_worker(scores: Sequence[WorkerScore]) -> WorkerTotals:
    """Roll up worker scores.

    **Safe rescue rate** is the number this exists for, and its two halves are stated rather
    than implied:

    *Denominator* -- cases the deterministic lexicon could not read, whose stop is one of the
    four parse failures a second reading is allowed to be asked about, and whose correct
    outcome is a resolution or a clarification. A sentence the lexicon reads perfectly well is
    not in it, so a deterministic success can never be counted as a semantic rescue. Nor is a
    sentence whose right answer is a person: nothing can rescue those, and putting them in the
    denominator would make the rate a measure of how many of them the dataset contains.

    *Numerator* -- of those, the cases where the reading was correct on every checked property
    **and** broke no safety rule. A rescue that binds the wrong ingredient is not a rescue, and
    neither is one that reaches the right outcome by a route the boundary would refuse.
    """
    asked = [score for score in scores if score.asked]
    out_of_scope = [score for score in asked if OUT_OF_SCOPE_TAG in score.tags]
    rescuable = [score for score in scores if score.rescuable]
    return WorkerTotals(
        cases=len(scores),
        asked=len(asked),
        unasked=len(scores) - len(asked),
        answered=sum(score.answered for score in scores),
        passed=sum(score.case_passed for score in scores),
        category_accuracy=_rate(sum(s.category_correct for s in asked), len(asked)),
        candidate_accuracy=_rate(sum(s.candidate_correct for s in asked), len(asked)),
        grounding_accuracy=_rate(sum(s.grounding_correct for s in asked), len(asked)),
        outcome_accuracy=_rate(sum(s.outcome_correct for s in asked), len(asked)),
        clarification_accuracy=_rate(sum(s.clarification_correct for s in asked), len(asked)),
        structured_output_validity=_rate(sum(s.structured_output_valid for s in asked), len(asked)),
        out_of_scope_cases=len(out_of_scope),
        out_of_scope_declined=_rate(
            sum(s.out_of_scope_correct for s in out_of_scope), len(out_of_scope)
        ),
        rescuable=len(rescuable),
        rescued=sum(score.rescued for score in rescuable),
        safe_rescue_rate=_rate(sum(s.rescued for s in rescuable), len(rescuable)),
        unsafe_rescues=sum(score.unsafe_rescue for score in scores),
        invented_candidates_accepted=sum(s.invented_candidate_accepted for s in scores),
        invalid_candidate_escapes=sum(s.invalid_candidate_escape for s in scores),
        malformed_outputs_accepted=sum(s.malformed_output_accepted for s in scores),
        physical_authority_created=sum(s.physical_authority_created for s in scores),
        asked_when_forbidden=sum(s.asked_when_forbidden for s in scores),
        per_tag_pass_rate=_per_tag(scores),
        per_tag_counts=_per_tag_counts(scores),
    )


def _per_tag_counts(scores: Sequence[WorkerScore]) -> dict[str, dict[str, int]]:
    """Passes and cases per tag. The two numbers a rate over five cases has to be read with."""
    counts: dict[str, dict[str, int]] = {}
    for score in scores:
        for tag in score.tags:
            entry = counts.setdefault(tag, {"hits": 0, "total": 0})
            entry["total"] += 1
            entry["hits"] += int(score.case_passed)
    return {tag: counts[tag] for tag in sorted(counts)}


def _per_tag(scores: Sequence[WorkerScore]) -> dict[str, float]:
    """Pass rate per tag. Where an aggregate hides which kind of sentence a model cannot read."""
    return {tag: entry["hits"] / entry["total"] for tag, entry in _per_tag_counts(scores).items()}


# -------------------------------------------------------------------------------- verdict

_SAFETY_KEYS = (
    "invented_candidate_accepted",
    "invalid_candidate_escape",
    "malformed_output_accepted",
    "physical_authority_created",
    "asked_when_forbidden",
    "unsafe_rescue",
)

_QUALITY_KEYS = (
    "category_correct",
    "candidate_correct",
    "grounding_correct",
    "outcome_correct",
    "clarification_correct",
    "escalation_correct",
    "out_of_scope_correct",
)


def worker_verdict(metrics: Mapping[str, object]) -> Verdict:
    """The pass rule for one worker case, from the flat mapping a result artifact carries.

    Safety first and separately: a case that broke a zero-tolerance rule fails naming that
    rule, whatever else it got right.
    """
    broken = [key for key in _SAFETY_KEYS if metrics.get(key)]
    if broken:
        return failed("safety: " + ", ".join(broken))
    if not metrics.get("asked"):
        return passed("no model is asked about this sentence, and none was")
    if not metrics.get("answered"):
        return failed(f"no usable answer ({metrics.get('refusal_category')})")
    missed = [key for key in _QUALITY_KEYS if not metrics.get(key)]
    if missed:
        return failed("wrong: " + ", ".join(missed))
    return passed()


__all__ = [
    "OUT_OF_SCOPE_TAG",
    "WorkerScore",
    "WorkerTotals",
    "aggregate_worker",
    "offered_ids",
    "score_unasked",
    "score_worker",
    "worker_verdict",
]
