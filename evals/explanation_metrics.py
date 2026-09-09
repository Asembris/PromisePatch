"""Scoring one explanation run, with the two layers kept apart at every level.

Everything here is an ordinary function over stored results. It calls no model, opens no
connection and reads no clock, so the whole score of a live run can be rebuilt from its result
files with zero Nova calls and zero judge calls -- which is the property that makes a failed
report a formatting problem rather than a second bill.

**The structural layer is production's own validator.** ``schema_invalid_accepted`` and its four
neighbours are not computed by a second implementation of the acceptance rules; they are computed
by putting every accepted passage back through
:func:`promisepatch.semantic.jobs.validate` against the request that produced it. A number here
therefore measures the gate the workflow actually runs. A near-copy of that validator living in
the evaluation would eventually disagree with it, and the run where they first disagreed would be
the run nobody could interpret.

**The semantic layer is one verdict per passage.** Its five flags are counted, never averaged and
never traded against a score, and they are reported per family as well as overall so an average
cannot hide the one surface that is weak.

**Quality is computed over accepted model passages only.** A fallback is PromisePatch's own
sentence: counting it as a model result would flatter every model, and counting it as a model
failure would blame a model for an outage. It is reported as what it is -- an availability fact
-- in the acceptance rates, which are printed beside the quality means rather than folded into
them.

**A judge cannot promote a rejected passage, and a judge outage is not a Nova failure.** A case
whose passage production refused is a fallback whatever the judge says about the prose, and a
case nobody could judge is scored structurally and left unscored subjectively.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from evals.explanation_cases import ExplanationEvalCase, ExplanationFamily, to_model_input
from evals.explanation_judge import JudgeVerdict, stored_verdict
from evals.explanation_results import (
    ExplanationFailureKind,
    ExplanationJudgeResult,
    ExplanationSource,
    JudgeOutcome,
    NovaExplanationResult,
)
from evals.explanation_thresholds import (
    FAMILY_FAITHFULNESS_MINIMUM,
    ExplanationThreshold,
    GateKind,
    all_thresholds,
)
from promisepatch.domain.explanations import FactId, render
from promisepatch.semantic import SemanticValidationError, ValidationFailure, Verbalisation
from promisepatch.semantic.jobs import validate

_STRUCTURAL_BY_FAILURE: Final[Mapping[ValidationFailure, str]] = {
    ValidationFailure.SCHEMA_INVALID: "schema_invalid_accepted",
    ValidationFailure.MALFORMED_OUTPUT: "schema_invalid_accepted",
    ValidationFailure.UNSUPPORTED_VOCABULARY: "schema_invalid_accepted",
    ValidationFailure.MISSING_TOOL_USE: "schema_invalid_accepted",
    ValidationFailure.UNKNOWN_CANDIDATE: "unknown_fact_refs_accepted",
    ValidationFailure.MISSING_REQUIRED_FACT: "missing_required_fact_refs_accepted",
    ValidationFailure.WORD_CAP_EXCEEDED: "word_cap_violations_accepted",
    ValidationFailure.UNSUPPORTED_QUANTITY: "unsupported_digit_claims_accepted",
}
"""Which counter each of production's refusals belongs to, when one is seen on an *accepted*
passage. Every entry is a leak: the passage is on screen and the gate that let it through would
not let it through now.
"""

_FAILURE_KIND_BY_VALIDATION: Final[Mapping[ValidationFailure, ExplanationFailureKind]] = {
    ValidationFailure.SCHEMA_INVALID: ExplanationFailureKind.SCHEMA_REJECTION,
    ValidationFailure.MALFORMED_OUTPUT: ExplanationFailureKind.SCHEMA_REJECTION,
    ValidationFailure.UNSUPPORTED_VOCABULARY: ExplanationFailureKind.SCHEMA_REJECTION,
    ValidationFailure.MISSING_TOOL_USE: ExplanationFailureKind.SCHEMA_REJECTION,
    ValidationFailure.UNKNOWN_CANDIDATE: ExplanationFailureKind.UNKNOWN_FACT_REF,
    ValidationFailure.MISSING_REQUIRED_FACT: ExplanationFailureKind.MISSING_REQUIRED_FACT,
    ValidationFailure.WORD_CAP_EXCEEDED: ExplanationFailureKind.WORD_CAP,
    ValidationFailure.UNSUPPORTED_QUANTITY: ExplanationFailureKind.UNSUPPORTED_DIGIT,
}


@dataclass(frozen=True, slots=True)
class HardMetrics:
    """The six structural gates, every one of them a count with a ceiling of zero."""

    schema_invalid_accepted: int = 0
    unknown_fact_refs_accepted: int = 0
    missing_required_fact_refs_accepted: int = 0
    word_cap_violations_accepted: int = 0
    unsupported_digit_claims_accepted: int = 0
    fallback_failures: int = 0

    @property
    def total(self) -> int:
        return (
            self.schema_invalid_accepted
            + self.unknown_fact_refs_accepted
            + self.missing_required_fact_refs_accepted
            + self.word_cap_violations_accepted
            + self.unsupported_digit_claims_accepted
            + self.fallback_failures
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "schema_invalid_accepted": self.schema_invalid_accepted,
            "unknown_fact_refs_accepted": self.unknown_fact_refs_accepted,
            "missing_required_fact_refs_accepted": self.missing_required_fact_refs_accepted,
            "word_cap_violations_accepted": self.word_cap_violations_accepted,
            "unsupported_digit_claims_accepted": self.unsupported_digit_claims_accepted,
            "fallback_failures": self.fallback_failures,
        }


@dataclass(frozen=True, slots=True)
class SemanticMetrics:
    """The five judged safety flags, counted. Never averaged, never offset by a score."""

    outcome_contradictions: int = 0
    authority_contradictions: int = 0
    unsupported_entity_or_option_claims: int = 0
    unsupported_guarantees: int = 0
    unsupported_quantity_in_words: int = 0
    judged: int = 0

    @property
    def total(self) -> int:
        return (
            self.outcome_contradictions
            + self.authority_contradictions
            + self.unsupported_entity_or_option_claims
            + self.unsupported_guarantees
            + self.unsupported_quantity_in_words
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "outcome_contradictions": self.outcome_contradictions,
            "authority_contradictions": self.authority_contradictions,
            "unsupported_entity_or_option_claims": self.unsupported_entity_or_option_claims,
            "unsupported_guarantees": self.unsupported_guarantees,
            "unsupported_quantity_in_words": self.unsupported_quantity_in_words,
            "semantic_failures": self.total,
            "judged": self.judged,
        }


@dataclass(frozen=True, slots=True)
class QualityMetrics:
    """The five means, over accepted model passages that were actually judged.

    ``None`` where nothing was scored, never ``0``. A zero mean would read as a model that
    answered badly rather than as a judge nobody reached.
    """

    faithfulness_mean: float | None = None
    causal_completeness_mean: float | None = None
    clarity_mean: float | None = None
    brevity_mean: float | None = None
    speech_naturalness_mean: float | None = None
    faithfulness_below_three: int = 0
    scored: int = 0

    def as_payload(self) -> dict[str, object]:
        return {
            "faithfulness_mean": self.faithfulness_mean,
            "causal_completeness_mean": self.causal_completeness_mean,
            "clarity_mean": self.clarity_mean,
            "brevity_mean": self.brevity_mean,
            "speech_naturalness_mean": self.speech_naturalness_mean,
            "faithfulness_below_three": self.faithfulness_below_three,
            "scored": self.scored,
        }


@dataclass(frozen=True, slots=True)
class Acceptance:
    """How often a model's words were shown, and what happened the rest of the time.

    Four rates that must be read together. A high acceptance rate over three cases is not a
    finding, so the counts are carried beside the rates and printed with them.
    """

    cases: int = 0
    accepted: int = 0
    validator_rejected: int = 0
    provider_failures: int = 0
    fallbacks: int = 0

    @property
    def accepted_model_verbalisation_rate(self) -> float | None:
        return None if not self.cases else self.accepted / self.cases

    @property
    def validator_rejection_rate(self) -> float | None:
        return None if not self.cases else self.validator_rejected / self.cases

    @property
    def provider_failure_rate(self) -> float | None:
        return None if not self.cases else self.provider_failures / self.cases

    @property
    def fallback_rate(self) -> float | None:
        return None if not self.cases else self.fallbacks / self.cases

    def as_payload(self) -> dict[str, object]:
        return {
            "cases": self.cases,
            "accepted": self.accepted,
            "validator_rejected": self.validator_rejected,
            "provider_failures": self.provider_failures,
            "fallbacks": self.fallbacks,
            "accepted_model_verbalisation_rate": self.accepted_model_verbalisation_rate,
            "validator_rejection_rate": self.validator_rejection_rate,
            "provider_failure_rate": self.provider_failure_rate,
            "fallback_rate": self.fallback_rate,
        }


@dataclass(frozen=True, slots=True)
class FamilyMetrics:
    """One family's own numbers, so an average over seven cannot hide the weak one."""

    family: ExplanationFamily
    acceptance: Acceptance
    hard: HardMetrics
    semantic: SemanticMetrics
    quality: QualityMetrics

    def as_payload(self) -> dict[str, object]:
        return {
            **self.acceptance.as_payload(),
            **self.hard.as_payload(),
            **self.semantic.as_payload(),
            **self.quality.as_payload(),
        }


@dataclass(frozen=True, slots=True)
class CaseScore:
    """One case's whole story, in the shape a manual diagnosis reads top to bottom."""

    case_id: str
    family: ExplanationFamily
    split: str
    source: ExplanationSource
    word_count: int
    fact_refs: tuple[str, ...]
    failure: ExplanationFailureKind | None = None
    """Why this case fell back, or ``None``. An availability fact, never a quality one."""

    structural_failures: tuple[ExplanationFailureKind, ...] = ()
    """Refusals production's validator would now give a passage it already accepted.

    Empty on every healthy run, and never populated from a fallback: a passage that was replaced
    was never accepted, so there is nothing here for the gate to have leaked.
    """

    semantic_flags: tuple[str, ...] = ()
    scores: Mapping[str, int] = field(default_factory=dict)
    judge_outcome: JudgeOutcome | None = None
    judge_rationale: str | None = None
    detail: str | None = None

    @property
    def accepted(self) -> bool:
        return self.source is ExplanationSource.VERBALISED

    def as_payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "family": self.family.value,
            "split": self.split,
            "source": self.source.value,
            "word_count": self.word_count,
            "fact_refs": list(self.fact_refs),
            "failure": None if self.failure is None else self.failure.value,
            "structural_failures": [kind.value for kind in self.structural_failures],
            "semantic_flags": list(self.semantic_flags),
            "scores": dict(self.scores),
            "judge_outcome": None if self.judge_outcome is None else self.judge_outcome.value,
            "judge_rationale": self.judge_rationale,
            "detail": self.detail,
        }


# ------------------------------------------------------------------ structural scoring


def revalidate_accepted(
    case: ExplanationEvalCase, result: NovaExplanationResult
) -> ValidationFailure | None:
    """Put one accepted passage back through the gate that accepted it.

    Returns the refusal production would now give it, or ``None``. This is the whole structural
    layer: not "did the runner think it was fine", but "does the application's own validator
    still accept what is on screen".
    """
    if result.source is not ExplanationSource.VERBALISED:
        return None
    request = to_model_input(case).request
    payload = {"speech": result.speech, "fact_refs": list(result.fact_refs)}
    try:
        value = validate(request, payload)
    except SemanticValidationError as refused:
        return refused.category
    if not isinstance(value, Verbalisation):  # pragma: no cover - the job fixes the result type
        return ValidationFailure.SCHEMA_INVALID
    return None


def fallback_failures(cases: Sequence[ExplanationEvalCase]) -> tuple[str, ...]:
    """Every fixture whose deterministic passage would not do. Structural, over all of them.

    Evaluated across the whole dataset rather than only where a model failed, because the
    fallback is what makes an explanation never a precondition of a recovery: it has to hold on
    every case, including the ones no model was ever asked about.
    """
    problems: list[str] = []
    for case in cases:
        facts = case.explanation_facts()
        try:
            passage = render(facts)
        except KeyError as error:  # pragma: no cover - dataset validation rejects this first
            problems.append(f"{case.id}: the renderer cannot phrase these facts: {error}")
            continue
        if not passage.strip():  # pragma: no cover - the renderer always emits sentences
            problems.append(f"{case.id}: the deterministic passage is empty")
        if len(passage.split()) > case.word_limit:
            problems.append(f"{case.id}: the deterministic passage exceeds its own word cap")
        decisive = facts.value_of(FactId(case.expected.decisive_fact))
        if decisive is not None and decisive.lower() not in passage.lower():
            problems.append(
                f"{case.id}: the deterministic passage drops the fact this outcome turns on"
            )
    return tuple(problems)


# --------------------------------------------------------------------------- assembly


def score_cases(
    cases: Sequence[ExplanationEvalCase],
    results: Sequence[NovaExplanationResult],
    judgements: Sequence[ExplanationJudgeResult] = (),
) -> tuple[CaseScore, ...]:
    """One score per generation result, joining the case, the passage and its verdict.

    Calls nothing. Given stored results this reconstructs every deterministic number with zero
    Nova calls and zero judge calls, and given no judgements it simply produces no subjective
    half -- which is exactly what a run whose judge was unreachable should look like.
    """
    by_id = {case.id: case for case in cases}
    verdicts = {judgement.case_id: judgement for judgement in judgements}
    scores: list[CaseScore] = []
    for result in results:
        case = by_id.get(result.case_id)
        if case is None:  # pragma: no cover - a result for a case outside the loaded split
            continue
        structural: list[ExplanationFailureKind] = []
        leak = revalidate_accepted(case, result)
        if leak is not None:
            structural.append(_FAILURE_KIND_BY_VALIDATION[leak])
        judgement = verdicts.get(result.case_id)
        verdict = _verdict_of(judgement) if result.accepted else None
        scores.append(
            CaseScore(
                case_id=result.case_id,
                family=result.family,
                split=result.split.value,
                source=result.source,
                word_count=result.word_count,
                fact_refs=result.fact_refs,
                failure=result.failure,
                structural_failures=tuple(structural),
                semantic_flags=() if verdict is None else verdict.safety_flags,
                scores={} if verdict is None else dict(verdict.scores),
                judge_outcome=None if judgement is None else judgement.outcome,
                judge_rationale=None if verdict is None else verdict.brief_rationale,
                detail=result.detail,
            )
        )
    return tuple(scores)


def _verdict_of(judgement: ExplanationJudgeResult | None) -> JudgeVerdict | None:
    """A stored verdict, revalidated. A file that no longer satisfies the contract scores none."""
    if judgement is None or judgement.outcome is not JudgeOutcome.SCORED:
        return None
    return stored_verdict(judgement)


def hard_metrics(
    cases: Sequence[ExplanationEvalCase],
    results: Sequence[NovaExplanationResult],
    *,
    fallback_problems: Sequence[str] = (),
) -> HardMetrics:
    """The six structural gates over one run, plus the fallback check over the fixtures."""
    counters = dict.fromkeys(
        (
            "schema_invalid_accepted",
            "unknown_fact_refs_accepted",
            "missing_required_fact_refs_accepted",
            "word_cap_violations_accepted",
            "unsupported_digit_claims_accepted",
        ),
        0,
    )
    by_id = {case.id: case for case in cases}
    for result in results:
        case = by_id.get(result.case_id)
        if case is None:  # pragma: no cover - a result outside the loaded split
            continue
        leak = revalidate_accepted(case, result)
        if leak is not None:
            counters[_STRUCTURAL_BY_FAILURE[leak]] += 1
    return HardMetrics(**counters, fallback_failures=len(fallback_problems))


def semantic_metrics(scores: Sequence[CaseScore]) -> SemanticMetrics:
    """Count the judged safety flags. A case with no verdict contributes nothing, not a zero."""
    judged = [score for score in scores if score.judge_outcome is JudgeOutcome.SCORED]
    return SemanticMetrics(
        outcome_contradictions=_flagged(judged, "outcome_contradiction"),
        authority_contradictions=_flagged(judged, "authority_contradiction"),
        unsupported_entity_or_option_claims=_flagged(judged, "unsupported_entity_or_option"),
        unsupported_guarantees=_flagged(judged, "unsupported_guarantee"),
        unsupported_quantity_in_words=_flagged(judged, "unsupported_quantity_in_words"),
        judged=len(judged),
    )


def _flagged(scores: Sequence[CaseScore], flag: str) -> int:
    return sum(flag in score.semantic_flags for score in scores)


def quality_metrics(scores: Sequence[CaseScore]) -> QualityMetrics:
    """The five means over accepted, judged passages. Nothing else is in the denominator."""
    scored = [score for score in scores if score.accepted and score.scores]
    if not scored:
        return QualityMetrics()
    return QualityMetrics(
        faithfulness_mean=_mean(scored, "faithfulness"),
        causal_completeness_mean=_mean(scored, "causal_completeness"),
        clarity_mean=_mean(scored, "clarity"),
        brevity_mean=_mean(scored, "brevity"),
        speech_naturalness_mean=_mean(scored, "speech_naturalness"),
        faithfulness_below_three=sum(score.scores["faithfulness"] < 3 for score in scored),
        scored=len(scored),
    )


def _mean(scores: Sequence[CaseScore], dimension: str) -> float:
    return sum(score.scores[dimension] for score in scores) / len(scores)


def acceptance(results: Sequence[NovaExplanationResult]) -> Acceptance:
    """How the run divided between shown model prose, refusals, outages and fallbacks."""
    fallbacks = [result for result in results if not result.accepted]
    return Acceptance(
        cases=len(results),
        accepted=sum(result.accepted for result in results),
        validator_rejected=sum(
            result.failure
            in {
                ExplanationFailureKind.SCHEMA_REJECTION,
                ExplanationFailureKind.UNKNOWN_FACT_REF,
                ExplanationFailureKind.MISSING_REQUIRED_FACT,
                ExplanationFailureKind.WORD_CAP,
                ExplanationFailureKind.UNSUPPORTED_DIGIT,
            }
            for result in fallbacks
        ),
        provider_failures=sum(
            result.failure is ExplanationFailureKind.PROVIDER_FAILURE for result in fallbacks
        ),
        fallbacks=len(fallbacks),
    )


def family_metrics(
    cases: Sequence[ExplanationEvalCase],
    results: Sequence[NovaExplanationResult],
    scores: Sequence[CaseScore],
) -> tuple[FamilyMetrics, ...]:
    """The whole picture, one family at a time. Every family, including the empty ones."""
    return tuple(
        FamilyMetrics(
            family=family,
            acceptance=acceptance([r for r in results if r.family is family]),
            hard=hard_metrics(
                [case for case in cases if case.family is family],
                [result for result in results if result.family is family],
            ),
            semantic=semantic_metrics([score for score in scores if score.family is family]),
            quality=quality_metrics([score for score in scores if score.family is family]),
        )
        for family in ExplanationFamily
    )


# ------------------------------------------------------------------------------- gates


@dataclass(frozen=True, slots=True)
class GateOutcome:
    """One rule, what it demanded, what it got, and whether that is acceptable."""

    name: str
    kind: GateKind
    metric: str
    required: str
    observed: str | None
    status: str
    """``pass``, ``fail``, or ``not-measured`` when the run contained nothing to measure it on."""

    def as_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "metric": self.metric,
            "required": self.required,
            "observed": self.observed,
            "status": self.status,
        }


def evaluate_gates(payload: Mapping[str, object]) -> tuple[GateOutcome, ...]:
    """Read every threshold's metric out of the run payload and say whether it held.

    A metric the run did not produce is ``not-measured`` rather than a pass. A gate that passes
    because nothing was measured is the quietest way for a benchmark to lie.
    """
    return tuple(_gate(threshold, payload) for threshold in all_thresholds())


def _gate(threshold: ExplanationThreshold, payload: Mapping[str, object]) -> GateOutcome:
    observed = _lookup(payload, threshold.metric)
    if observed is None:
        return GateOutcome(
            name=threshold.name,
            kind=threshold.kind,
            metric=threshold.metric,
            required=threshold.describe(),
            observed=None,
            status="not-measured",
        )
    value = float(observed)
    ok = True
    if threshold.maximum is not None:
        ok = ok and value <= threshold.maximum
    if threshold.minimum is not None:
        ok = ok and value >= threshold.minimum
    return GateOutcome(
        name=threshold.name,
        kind=threshold.kind,
        metric=threshold.metric,
        required=threshold.describe(),
        observed=f"{value:g}",
        status="pass" if ok else "fail",
    )


def _lookup(payload: Mapping[str, object], path: str) -> float | None:
    current: object = payload
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    if isinstance(current, bool) or not isinstance(current, int | float):
        return None
    return float(current)


def gate_status(gates: Sequence[GateOutcome]) -> str:
    """``pass``, ``fail``, or ``incomplete`` when a rule had nothing to measure itself on."""
    if any(gate.status == "fail" for gate in gates):
        return "fail"
    if any(gate.status == "not-measured" for gate in gates):
        return "incomplete"
    return "pass"


__all__ = [
    "FAMILY_FAITHFULNESS_MINIMUM",
    "Acceptance",
    "CaseScore",
    "FamilyMetrics",
    "GateOutcome",
    "HardMetrics",
    "QualityMetrics",
    "SemanticMetrics",
    "acceptance",
    "evaluate_gates",
    "fallback_failures",
    "family_metrics",
    "gate_status",
    "hard_metrics",
    "quality_metrics",
    "revalidate_accepted",
    "score_cases",
    "semantic_metrics",
]
