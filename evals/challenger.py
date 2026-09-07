"""A targeted challenger: does a second model repair the first one's failures, or not?

A broad sweep against every case and every job is the expensive way to answer a narrow
question. The narrow question here is whether one model's *known failure clusters* are
repaired by another, and it is answerable with two calls per failure -- the failure itself,
and a case the first model already got right, to see whether the repair cost something
elsewhere.

So the set is built from a finished run rather than chosen. :func:`select_stage_a` takes the
persisted results of the model being challenged and returns every case it got wrong, each
paired with a matched control it got right. Nothing in it is a judgement call: the failures are
whatever the stored answers say they are, the controls are picked by class, then by tag
overlap, then by case id, and the whole thing is computed before the challenger has answered
anything. A selection that could see the challenger's answers would be a selection somebody
could tune, and the number it produced would mean nothing.

**The challenger is never told what it is.** A case reaches it through
:func:`~evals.cases.to_model_input` like any other, carrying the production semantic request
and nothing else. It does not know it is a failure, a control, or part of a comparison at all.

**Two gates, and the first one is about money rather than quality.** Stage A exists only to
decide whether the remaining cases are worth buying: :data:`STAGE_A_MATERIALITY` is a floor on
"is this promising enough to continue", fixed before the first call, and it is emphatically not
a production acceptance bar -- that is :mod:`evals.thresholds`, unchanged and applied to the
full development split in Stage B.

Nothing in this module calls anything. It reads stored results and a dataset, and returns
values.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from math import comb

from evals.budget import ModelPrice
from evals.cases import CustomerCase, EvalJob, EvalSplit
from evals.dataset import GoldDataset
from evals.metrics.customer import CustomerScore, aggregate_customer, score_from_metrics
from evals.results import CaseResult, ExecutionStatus
from evals.store import ProviderFailureRecord
from promisepatch.semantic import ApparentIntent

SELECTION_ALGORITHM_VERSION = "1"
"""Bumped whenever the rule below changes, because a set built by another rule is another set."""

MAX_STAGE_A_CASES = 18
"""The hard bound on Stage A. Reached rather than exceeded: selection raises instead."""


class ChallengerError(RuntimeError):
    """The challenger set cannot be built from what is on disk, so nothing is bought."""


# ------------------------------------------------------------------ reading the source run


@dataclass(frozen=True, slots=True)
class SourceRun:
    """The finished run being challenged, narrowed to the cases this slice is about.

    ``results_sha`` is over the customer results themselves rather than the whole file, so it
    identifies the answers the comparison is actually joined against. Two challenger runs
    quoting the same source sha compared against the same readings.
    """

    run_id: str
    model_id: str | None
    provider: str
    git_sha: str | None
    dataset_version: str
    dataset_hash: str
    results: tuple[CaseResult, ...]

    @property
    def results_sha(self) -> str:
        payload = [
            result.model_dump(mode="json")
            for result in sorted(self.results, key=lambda item: item.case_id)
        ]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def by_case(self) -> dict[str, CaseResult]:
        return {result.case_id: result for result in self.results}


def customer_development(results: Sequence[CaseResult]) -> tuple[CaseResult, ...]:
    """The customer-intent development results in a run, and only those.

    The narrowing is the guarantee: a worker case and a holdout case cannot enter a challenger
    set built from this, because they are filtered out before anything else looks at them.
    """
    return tuple(
        result
        for result in results
        if result.job is EvalJob.CUSTOMER_INTENT and result.split is EvalSplit.DEVELOPMENT
    )


def predicted_label(result: CaseResult) -> ApparentIntent | None:
    """The label a stored result recorded, or ``None`` when nothing came back for it."""
    value = result.observed.get("apparent_intent")
    return ApparentIntent(value) if isinstance(value, str) else None


# ------------------------------------------------------------------------------ selection


@dataclass(frozen=True, slots=True)
class ChallengerPair:
    """One failure of the challenged model, and the case chosen to watch beside it."""

    failure_case_id: str
    failure_gold: str
    failure_predicted: str | None
    failure_tags: tuple[str, ...]
    control_case_id: str
    control_gold: str
    control_tags: tuple[str, ...]
    shared_tags: tuple[str, ...]
    same_class: bool
    """``False`` when no unused control of the failure's own class was left. Documented, not
    hidden: a cross-class control still watches for a regression, and a reader has to be able
    to tell the two apart."""

    def as_payload(self) -> dict[str, object]:
        return {
            "failure_case_id": self.failure_case_id,
            "failure_gold": self.failure_gold,
            "failure_predicted": self.failure_predicted,
            "failure_tags": list(self.failure_tags),
            "control_case_id": self.control_case_id,
            "control_gold": self.control_gold,
            "control_tags": list(self.control_tags),
            "shared_tags": list(self.shared_tags),
            "same_class": self.same_class,
        }


@dataclass(frozen=True, slots=True)
class StageASelection:
    """The challenger set, and everything needed to rebuild it without calling anything."""

    algorithm_version: str
    source_run_id: str
    source_model_id: str | None
    source_results_sha: str
    dataset_version: str
    dataset_hash: str
    pairs: tuple[ChallengerPair, ...]

    @property
    def failure_ids(self) -> tuple[str, ...]:
        return tuple(pair.failure_case_id for pair in self.pairs)

    @property
    def control_ids(self) -> tuple[str, ...]:
        return tuple(pair.control_case_id for pair in self.pairs)

    @property
    def case_ids(self) -> frozenset[str]:
        return frozenset(self.failure_ids) | frozenset(self.control_ids)

    def as_payload(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "source_run_id": self.source_run_id,
            "source_model_id": self.source_model_id,
            "source_results_sha": self.source_results_sha,
            "dataset_version": self.dataset_version,
            "dataset_hash": self.dataset_hash,
            "failures": len(self.pairs),
            "controls": len(self.pairs),
            "cases": len(self.case_ids),
            "failure_case_ids": list(self.failure_ids),
            "control_case_ids": list(self.control_ids),
            "pairs": [pair.as_payload() for pair in self.pairs],
        }


def select_stage_a(dataset: GoldDataset, source: SourceRun) -> StageASelection:
    """Build the challenger set from a finished run. Deterministic, and blind to the challenger.

    Every customer development case the source model got wrong is challenged -- the count comes
    from the data, never from a number somebody remembered. Each is paired with one control the
    source model got right, chosen by, in order:

    1. the same gold class, so a control watches the same decision the failure is about;
    2. the most overlapping tags, so it is the nearest neighbour among those;
    3. the lowest case id, so a tie is broken the same way on every machine.

    A control is used once. When a failure's own class has no control left, the same ordering
    runs over the remaining cases of any class and the pair records ``same_class=False``: a
    cross-class control still answers "did the challenger break something that worked", which
    is what a control is for.
    """
    cases = {case.id: case for case in dataset.customer if case.split is EvalSplit.DEVELOPMENT}
    stored = customer_development(source.results)
    _refuse_an_incomplete_source(cases, stored)

    by_case = {result.case_id: result for result in stored}
    failures: list[CustomerCase] = []
    controls: list[CustomerCase] = []
    for case_id in sorted(cases):
        case = cases[case_id]
        if predicted_label(by_case[case_id]) is case.expected:
            controls.append(case)
        else:
            failures.append(case)

    if not failures:
        raise ChallengerError(
            "the source run has no customer-intent development failures, so there is nothing "
            "to challenge and nothing to buy"
        )
    if len(controls) < len(failures):
        raise ChallengerError(
            f"{len(failures)} failure(s) need a matched control each and the source run has "
            f"only {len(controls)} correct case(s). A paired comparison cannot be built from "
            f"this without spending to fill the gap, which this slice does not do."
        )

    available = {case.id: case for case in controls}
    pairs: list[ChallengerPair] = []
    for failure in failures:
        control, same_class = _match(failure, available)
        del available[control.id]
        pairs.append(
            ChallengerPair(
                failure_case_id=failure.id,
                failure_gold=failure.expected.value,
                failure_predicted=_label_value(predicted_label(by_case[failure.id])),
                failure_tags=failure.tags,
                control_case_id=control.id,
                control_gold=control.expected.value,
                control_tags=control.tags,
                shared_tags=tuple(sorted(set(failure.tags) & set(control.tags))),
                same_class=same_class,
            )
        )

    selection = StageASelection(
        algorithm_version=SELECTION_ALGORITHM_VERSION,
        source_run_id=source.run_id,
        source_model_id=source.model_id,
        source_results_sha=source.results_sha,
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        pairs=tuple(pairs),
    )
    if len(selection.case_ids) > MAX_STAGE_A_CASES:
        raise ChallengerError(
            f"deterministic selection needs {len(selection.case_ids)} cases and the Stage-A "
            f"bound is {MAX_STAGE_A_CASES}. Report the selection rather than trimming it: a "
            f"set narrowed to fit a cap is a set somebody chose."
        )
    return selection


def _refuse_an_incomplete_source(
    cases: Mapping[str, CustomerCase], stored: Sequence[CaseResult]
) -> None:
    """A paired comparison needs a reading for every case, so a gap stops rather than shrinks."""
    answered = {result.case_id for result in stored if result.has_reading}
    unreadable = sorted(result.case_id for result in stored if not result.has_reading)
    missing = sorted(set(cases) - answered)
    unknown = sorted({result.case_id for result in stored} - set(cases))
    if missing:
        detail = (
            ""
            if not unreadable
            else (
                f" {len(unreadable)} of them recorded an attempt with no reading "
                f"({', '.join(unreadable)}), which is an execution fact and not an answer."
            )
        )
        raise ChallengerError(
            f"the source run has no reading for {len(missing)} customer development case(s): "
            f"{', '.join(missing)}. Every case needs one for a paired comparison, and this "
            f"slice does not re-run the source model to get it.{detail}"
        )
    if unknown:  # pragma: no cover - a result file from another dataset fails the hash first
        raise ChallengerError(
            f"the source run answered case(s) this dataset does not contain: {', '.join(unknown)}"
        )


def _match(
    failure: CustomerCase, available: Mapping[str, CustomerCase]
) -> tuple[CustomerCase, bool]:
    """The control for one failure: same class if one is left, nearest by tags, then by id."""
    same_class = [case for case in available.values() if case.expected is failure.expected]
    pool = same_class or list(available.values())
    chosen = min(pool, key=lambda case: (-len(set(case.tags) & set(failure.tags)), case.id))
    return chosen, bool(same_class)


def _label_value(label: ApparentIntent | None) -> str | None:
    return None if label is None else label.value


# ------------------------------------------------------------------------------- taxonomy


class PairedOutcome(StrEnum):
    """What happened to one case: four model-quality states, and one that is not about a model.

    The first four are claims about how a challenger read a sentence, and each of them needs
    the challenger to have read it. :data:`PROVIDER_FAILURE` is the state where it did not --
    where nobody was reached and no reading exists -- and it is a member of this enum rather
    than an absence precisely so that it cannot be quietly rounded into the nearest quality
    label. A report once did exactly that, calling three unreachable calls two unchanged
    failures and one control regression, which read as evidence about a model and was evidence
    about an account.
    """

    REPAIRED = "REPAIRED"
    UNCHANGED_FAILURE = "UNCHANGED_FAILURE"
    CONTROL_PRESERVED = "CONTROL_PRESERVED"
    CONTROL_REGRESSION = "CONTROL_REGRESSION"

    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    """No reading was obtained, so nothing about model quality is claimed for this case."""

    @property
    def is_model_quality(self) -> bool:
        """Whether this outcome is a statement about a model at all."""
        return self is not PairedOutcome.PROVIDER_FAILURE


SEMANTIC_OUTCOMES = frozenset(outcome for outcome in PairedOutcome if outcome.is_model_quality)
"""The outcomes that require two readings. Nothing outside this set is a win, a loss or a tie."""


class Role(StrEnum):
    """Whether a case is in the set because it failed or because it did not."""

    FAILURE = "failure"
    CONTROL = "control"


def is_directional_inversion(gold: ApparentIntent, predicted: ApparentIntent | None) -> bool:
    """Whether a reading flipped a stance rather than retreating from it.

    Reading an approval as a refusal, or a refusal as an approval, is a different kind of miss
    from reading either as ``UNCLEAR``. Both send the same confirmation prompt and neither
    decides anything -- but one puts the opposite stance on the ledger for whoever reviews the
    case, and a challenger that repaired a cluster by inverting it has not repaired anything.
    """
    approve, decline = ApparentIntent.APPARENT_APPROVE, ApparentIntent.APPARENT_DECLINE
    return (gold is approve and predicted is decline) or (gold is decline and predicted is approve)


class ProviderFailureCategory(StrEnum):
    """Why nobody was reached, in the coarsest terms the evaluator can state truthfully.

    Derived from the exception class the semantic boundary raised, which is the only thing
    about the failure that reaches a stored result. Production distinguishes a retryable
    transport fault from a non-retryable one on the exception object, and puts the provider's
    own code in the message; neither is carried into the surface the evaluator sees, and this
    gate does not widen production logging to fetch them. So the categories are deliberately
    coarse, and no raw provider message is ever persisted here.
    """

    TIMEOUT = "TIMEOUT"
    """The model did not answer inside the bound. Retryable in the transport sense."""

    PROVIDER_UNREACHABLE = "PROVIDER_UNREACHABLE"
    """The provider refused, could not be reached, or did not answer with a response. Covers
    authentication, access denial, throttling and network faults alike: telling those apart
    from a stored result would need a sanitised provider code production does not publish."""

    UNKNOWN_PROVIDER_FAILURE = "UNKNOWN_PROVIDER_FAILURE"
    """A failure whose recorded category names nothing this evaluator knows."""


def provider_failure_category(result: CaseResult) -> ProviderFailureCategory | None:
    """The coarse category of one provider failure, or ``None`` when the case is not one."""
    if result.execution_status is not ExecutionStatus.PROVIDER_FAILURE:
        return None
    if result.error_category == "SemanticTimeoutError":
        return ProviderFailureCategory.TIMEOUT
    if result.error_category == "SemanticProviderError":
        return ProviderFailureCategory.PROVIDER_UNREACHABLE
    return ProviderFailureCategory.UNKNOWN_PROVIDER_FAILURE


@dataclass(frozen=True, slots=True)
class PairedCase:
    """One case seen by both models, with the raw labels kept rather than collapsed.

    ``outcome`` is a model-quality verdict only when ``execution_status`` is ``ANSWERED``. When
    it is not, every quality field on this record is deliberately empty rather than defaulted:
    there is no predicted label, no inversion and no authority violation to report about a call
    nobody answered, and a ``False`` in those places would read as a measurement.
    """

    case_id: str
    role: Role
    tags: tuple[str, ...]
    gold: ApparentIntent
    source_predicted: ApparentIntent | None
    challenger_predicted: ApparentIntent | None
    outcome: PairedOutcome
    directional_inversion: bool
    authority_violation: bool
    execution_status: ExecutionStatus = ExecutionStatus.ANSWERED
    failure_category: ProviderFailureCategory | None = None

    @property
    def comparable(self) -> bool:
        """Whether this case may be counted in any model-quality number."""
        return self.outcome.is_model_quality

    @property
    def source_correct(self) -> bool:
        return self.source_predicted is self.gold

    @property
    def challenger_correct(self) -> bool:
        return self.comparable and self.challenger_predicted is self.gold

    def as_payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "role": self.role.value,
            "tags": list(self.tags),
            "gold": self.gold.value,
            "source_predicted": _label_value(self.source_predicted),
            "challenger_predicted": _label_value(self.challenger_predicted),
            "outcome": self.outcome.value,
            "execution_status": self.execution_status.value,
            "provider_failure_category": (
                None if self.failure_category is None else self.failure_category.value
            ),
            "comparable": self.comparable,
            "directional_inversion": self.directional_inversion,
            "authority_violation": self.authority_violation,
        }


def pair_case(
    case: CustomerCase, role: Role, source: CaseResult, challenger: CaseResult
) -> PairedCase:
    """Classify one case from the two stored readings of it.

    A challenger result with no reading is classified as :data:`PairedOutcome.PROVIDER_FAILURE`
    and stops there. It is not a repair, not an unchanged failure and not a regression, because
    each of those words asserts something about what a model said, and nothing was said.
    """
    source_label = predicted_label(source)
    if not challenger.has_reading:
        return PairedCase(
            case_id=case.id,
            role=role,
            tags=case.tags,
            gold=case.expected,
            source_predicted=source_label,
            challenger_predicted=None,
            outcome=PairedOutcome.PROVIDER_FAILURE,
            directional_inversion=False,
            authority_violation=False,
            execution_status=challenger.execution_status,
            failure_category=provider_failure_category(challenger),
        )
    challenger_label = predicted_label(challenger)
    correct = challenger_label is case.expected
    if role is Role.FAILURE:
        outcome = PairedOutcome.REPAIRED if correct else PairedOutcome.UNCHANGED_FAILURE
    else:
        outcome = PairedOutcome.CONTROL_PRESERVED if correct else PairedOutcome.CONTROL_REGRESSION
    return PairedCase(
        case_id=case.id,
        role=role,
        tags=case.tags,
        gold=case.expected,
        source_predicted=source_label,
        challenger_predicted=challenger_label,
        outcome=outcome,
        directional_inversion=is_directional_inversion(case.expected, challenger_label),
        authority_violation=bool(challenger.metrics.get("authority_violation")),
        execution_status=ExecutionStatus.ANSWERED,
        failure_category=None,
    )


def unread_result(record: ProviderFailureRecord, case: CustomerCase) -> CaseResult:
    """Turn one logged failed attempt back into the shape the taxonomy reads.

    Used only to rebuild a report from stored evidence. The result it returns carries no
    reading, no metrics and no usage -- there were none -- and its ``provider_error`` flag is
    what makes :func:`pair_case` classify it as an execution failure rather than a misread
    sentence. Constructing one costs nothing and calls nothing.
    """
    return CaseResult(
        case_id=case.id,
        job=case.job,
        split=case.split,
        tags=case.tags,
        expected={"apparent_intent": case.expected.value},
        observed={},
        metrics={},
        passed=False,
        reason=f"no reading: the provider was not reached ({record.category or 'unknown'})",
        provider=record.provider,
        model_id=record.model_id,
        error_category=record.category,
        provider_error=True,
        e2e_latency_ms=record.e2e_latency_ms,
    )


@dataclass(frozen=True, slots=True)
class StageAOutcome:
    """What Stage A found, in the counts the materiality gate is written in."""

    selection: StageASelection
    cases: tuple[PairedCase, ...]

    @property
    def failures(self) -> tuple[PairedCase, ...]:
        return tuple(case for case in self.cases if case.role is Role.FAILURE)

    @property
    def controls(self) -> tuple[PairedCase, ...]:
        return tuple(case for case in self.cases if case.role is Role.CONTROL)

    @property
    def comparable(self) -> tuple[PairedCase, ...]:
        """The cases a model-quality statement may be made about: both models read them."""
        return tuple(case for case in self.cases if case.comparable)

    @property
    def comparable_failures(self) -> tuple[PairedCase, ...]:
        return tuple(case for case in self.failures if case.comparable)

    @property
    def comparable_controls(self) -> tuple[PairedCase, ...]:
        return tuple(case for case in self.controls if case.comparable)

    @property
    def provider_failures(self) -> tuple[PairedCase, ...]:
        """Cases the challenger was asked about and did not answer. Not quality evidence."""
        return tuple(case for case in self.cases if not case.comparable)

    @property
    def provider_completion(self) -> str:
        """Readings obtained over cases selected, as a fraction a reader can check."""
        return f"{len(self.comparable)}/{len(self.selection.case_ids)}"

    @property
    def repairs(self) -> int:
        return sum(case.outcome is PairedOutcome.REPAIRED for case in self.cases)

    @property
    def unchanged_failures(self) -> int:
        return sum(case.outcome is PairedOutcome.UNCHANGED_FAILURE for case in self.cases)

    @property
    def controls_preserved(self) -> int:
        return sum(case.outcome is PairedOutcome.CONTROL_PRESERVED for case in self.cases)

    @property
    def control_regressions(self) -> int:
        return sum(case.outcome is PairedOutcome.CONTROL_REGRESSION for case in self.cases)

    @property
    def directional_inversions(self) -> int:
        return sum(case.directional_inversion for case in self.cases)

    @property
    def authority_violations(self) -> int:
        return sum(case.authority_violation for case in self.cases)

    @property
    def repair_rate(self) -> float | None:
        """Repairs over the failures the challenger actually read, or ``None`` when it read none.

        The denominator is comparable failures rather than selected failures, and the two
        differ by exactly the provider failures. Dividing by the selected count would fold an
        unreachable endpoint into the model's score as an unrepaired failure, which is a claim
        about availability wearing the costume of a claim about quality. The rate is therefore
        never reported on its own: :attr:`provider_completion` travels with it, and
        :attr:`complete` is what decides whether either may be acted on.
        """
        challenged = len(self.comparable_failures)
        return None if challenged == 0 else self.repairs / challenged

    @property
    def complete(self) -> bool:
        """Whether every selected case produced a reading. A partial stage decides nothing.

        A provider failure leaves the stage incomplete, which is the mechanism by which an
        execution problem cannot become a quality verdict: :func:`evaluate_materiality` refuses
        to pass an incomplete stage whatever its partial numbers say, so Stage B stays shut.
        """
        return {case.case_id for case in self.comparable} == self.selection.case_ids

    def as_payload(self) -> dict[str, object]:
        return {
            "selection": self.selection.as_payload(),
            "complete": self.complete,
            "failures_challenged": len(self.failures),
            "controls": len(self.controls),
            "eligible_semantic_comparisons": len(self.comparable),
            "comparable_failures": len(self.comparable_failures),
            "comparable_controls": len(self.comparable_controls),
            "provider_failures": len(self.provider_failures),
            "provider_completion": self.provider_completion,
            "repairs": self.repairs,
            "unchanged_failures": self.unchanged_failures,
            "directional_inversions": self.directional_inversions,
            "controls_preserved": self.controls_preserved,
            "control_regressions": self.control_regressions,
            "authority_violations": self.authority_violations,
            "repair_rate": self.repair_rate,
            "cases": [case.as_payload() for case in self.cases],
        }


def build_stage_a(
    dataset: GoldDataset,
    selection: StageASelection,
    source: SourceRun,
    challenger_results: Sequence[CaseResult],
) -> StageAOutcome:
    """Join the two runs on case id, for the cases the selection named and no others."""
    cases = {case.id: case for case in dataset.customer}
    source_by_case = source.by_case()
    challenger_by_case = {result.case_id: result for result in challenger_results}
    roles = {pair.failure_case_id: Role.FAILURE for pair in selection.pairs}
    roles.update({pair.control_case_id: Role.CONTROL for pair in selection.pairs})

    paired = [
        pair_case(cases[case_id], roles[case_id], source_by_case[case_id], challenger)
        for case_id in sorted(selection.case_ids)
        if (challenger := challenger_by_case.get(case_id)) is not None
    ]
    return StageAOutcome(selection=selection, cases=tuple(paired))


# ------------------------------------------------------------------------ materiality gate


@dataclass(frozen=True, slots=True)
class MaterialityGate:
    """The floor Stage A has to clear for the rest of the split to be worth buying.

    Not a production bar. It answers one question -- is this promising enough to spend another
    small batch on -- and it is fixed here, before any challenger call, for the same reason
    every other threshold in this repository is: a bar set once the numbers are in is not a bar.
    """

    min_repair_rate: float
    min_repairs: int
    max_directional_inversions: int
    max_control_regressions: int
    max_authority_violations: int


STAGE_A_MATERIALITY = MaterialityGate(
    min_repair_rate=0.50,
    min_repairs=2,
    max_directional_inversions=0,
    max_control_regressions=1,
    max_authority_violations=0,
)


@dataclass(frozen=True, slots=True)
class Criterion:
    """One materiality condition, what it demanded, what it got, and whether that is enough."""

    name: str
    required: str
    observed: str
    passed: bool

    def as_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "required": self.required,
            "observed": self.observed,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class MaterialityVerdict:
    """Whether Stage B may be opened, and every criterion behind that."""

    criteria: tuple[Criterion, ...]
    complete: bool

    @property
    def passed(self) -> bool:
        return self.complete and all(criterion.passed for criterion in self.criteria)

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(criterion.name for criterion in self.criteria if not criterion.passed)

    def as_payload(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "complete": self.complete,
            "failed": list(self.failed),
            "criteria": [criterion.as_payload() for criterion in self.criteria],
        }


def evaluate_materiality(
    outcome: StageAOutcome, gate: MaterialityGate = STAGE_A_MATERIALITY
) -> MaterialityVerdict:
    """Judge Stage A. An incomplete stage never passes, whatever its partial numbers say."""
    rate = outcome.repair_rate
    criteria = (
        Criterion(
            name="failure repair rate",
            required=f">= {gate.min_repair_rate:g}",
            observed="n/a" if rate is None else f"{rate:.3f}",
            passed=rate is not None and rate >= gate.min_repair_rate,
        ),
        Criterion(
            name="failures repaired",
            required=f">= {gate.min_repairs}",
            observed=str(outcome.repairs),
            passed=outcome.repairs >= gate.min_repairs,
        ),
        Criterion(
            name="directional inversions",
            required=f"<= {gate.max_directional_inversions}",
            observed=str(outcome.directional_inversions),
            passed=outcome.directional_inversions <= gate.max_directional_inversions,
        ),
        Criterion(
            name="matched-control regressions",
            required=f"<= {gate.max_control_regressions}",
            observed=str(outcome.control_regressions),
            passed=outcome.control_regressions <= gate.max_control_regressions,
        ),
        Criterion(
            name="customer authority violations",
            required=f"<= {gate.max_authority_violations}",
            observed=str(outcome.authority_violations),
            passed=outcome.authority_violations <= gate.max_authority_violations,
        ),
    )
    return MaterialityVerdict(criteria=criteria, complete=outcome.complete)


# --------------------------------------------------------------------- the paired comparison


@dataclass(frozen=True, slots=True)
class PairedTotals:
    """Two models over the same cases, counted the way a decision needs them counted."""

    cases: int
    both_correct: int
    both_wrong: int
    challenger_only_correct: int
    source_only_correct: int

    @property
    def wins(self) -> int:
        return self.challenger_only_correct

    @property
    def losses(self) -> int:
        return self.source_only_correct

    @property
    def ties(self) -> int:
        return self.both_correct + self.both_wrong

    @property
    def exact_paired_p(self) -> float | None:
        """Two-sided exact sign test over the discordant pairs, or ``None`` when there are none.

        Secondary evidence and nothing more. It is the exact binomial probability of a split at
        least this lopsided under "the two models are equally likely to be the one that is
        right", computed with :func:`math.comb` because a paired comparison of this size does
        not justify a statistics dependency -- and because, over a set this small and this
        deliberately chosen, no p-value should be read as a claim about a population.
        """
        discordant = self.wins + self.losses
        if discordant == 0:
            return None
        extreme = min(self.wins, self.losses)
        tail = sum(comb(discordant, k) for k in range(extreme + 1))
        return min(1.0, 2.0 * tail / float(2**discordant))

    def as_payload(self) -> dict[str, object]:
        return {
            "cases": self.cases,
            "both_correct": self.both_correct,
            "both_wrong": self.both_wrong,
            "challenger_fixes_source_miss": self.challenger_only_correct,
            "source_fixes_challenger_miss": self.source_only_correct,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "exact_paired_p": self.exact_paired_p,
        }


def compare(cases: Sequence[PairedCase]) -> PairedTotals:
    """Roll up a set of paired readings into wins, losses and ties.

    Cases with no challenger reading are dropped before anything is counted. A win, a loss and
    a tie are all statements about two models disagreeing or agreeing, and a case where only
    one of them spoke supports none of the three -- least of all a loss, which is what
    counting it as "not correct" would silently make it.
    """
    comparable = [case for case in cases if case.comparable]
    return PairedTotals(
        cases=len(comparable),
        both_correct=sum(case.source_correct and case.challenger_correct for case in comparable),
        both_wrong=sum(
            not case.source_correct and not case.challenger_correct for case in comparable
        ),
        challenger_only_correct=sum(
            case.challenger_correct and not case.source_correct for case in comparable
        ),
        source_only_correct=sum(
            case.source_correct and not case.challenger_correct for case in comparable
        ),
    )


@dataclass(frozen=True, slots=True)
class ClusterDelta:
    """One tag, read by both models, with both denominators kept beside both rates."""

    tag: str
    total: int
    source_hits: int
    challenger_hits: int

    @property
    def source_recall(self) -> float:
        return self.source_hits / self.total

    @property
    def challenger_recall(self) -> float:
        return self.challenger_hits / self.total

    @property
    def delta(self) -> float:
        return self.challenger_recall - self.source_recall

    def as_payload(self) -> dict[str, object]:
        return {
            "tag": self.tag,
            "total": self.total,
            "source_hits": self.source_hits,
            "challenger_hits": self.challenger_hits,
            "source_recall": self.source_recall,
            "challenger_recall": self.challenger_recall,
            "delta": self.delta,
        }


def cluster_deltas(cases: Sequence[PairedCase]) -> tuple[ClusterDelta, ...]:
    """Per-tag recall for both models over exactly the same cases.

    The counts travel with the rates. Several of these clusters are five cases or fewer, and a
    percentage over five hand-authored examples is four of them -- a reader shown only the
    percentage cannot tell that from four hundred of five hundred.
    """
    tags: dict[str, list[PairedCase]] = {}
    for case in cases:
        if not case.comparable:
            continue
        for tag in case.tags:
            tags.setdefault(tag, []).append(case)
    return tuple(
        ClusterDelta(
            tag=tag,
            total=len(members),
            source_hits=sum(case.source_correct for case in members),
            challenger_hits=sum(case.challenger_correct for case in members),
        )
        for tag, members in sorted(tags.items())
    )


def pair_all(
    dataset: GoldDataset, source: SourceRun, challenger_results: Sequence[CaseResult]
) -> tuple[PairedCase, ...]:
    """Join two runs over every customer development case both of them answered.

    Used for the full-split comparison, where the failure/control roles of Stage A no longer
    describe the set. Every case is labelled by the role it had in Stage A when it had one, so
    a reader can still see which readings were bought first.
    """
    cases = {case.id: case for case in dataset.customer if case.split is EvalSplit.DEVELOPMENT}
    source_by_case = source.by_case()
    challenger_by_case = {result.case_id: result for result in challenger_results}
    return tuple(
        pair_case(cases[case_id], Role.FAILURE, source_by_case[case_id], challenger)
        if predicted_label(source_by_case[case_id]) is not cases[case_id].expected
        else pair_case(cases[case_id], Role.CONTROL, source_by_case[case_id], challenger)
        for case_id in sorted(cases)
        if case_id in source_by_case and (challenger := challenger_by_case.get(case_id))
    )


def scores_for(dataset: GoldDataset, results: Sequence[CaseResult]) -> tuple[CustomerScore, ...]:
    """Re-score stored customer results with the scorer every other number here comes from.

    The point is that the challenger is not graded by a challenger-specific rule. These are the
    same :class:`~evals.metrics.customer.CustomerScore` values a live run produces, so
    :func:`~evals.metrics.customer.aggregate_customer` gives the challenger exactly the numbers
    it gave the model being challenged.
    """
    cases = {case.id: case for case in dataset.customer}
    return tuple(
        score_from_metrics(cases[result.case_id], result.metrics)
        for result in sorted(results, key=lambda item: item.case_id)
        if result.case_id in cases
        and result.execution_status is not ExecutionStatus.PROVIDER_FAILURE
    )


def customer_totals(dataset: GoldDataset, results: Sequence[CaseResult]) -> dict[str, object]:
    """The full customer metric block for one model's stored readings."""
    return aggregate_customer(scores_for(dataset, results)).as_payload()


# ------------------------------------------------------------------------ operational cost


@dataclass(frozen=True, slots=True)
class UsageProfile:
    """What one model's customer-intent calls used, and what that projects to at scale.

    ``usd_per_thousand`` is an engineering estimate built from this run's average token usage
    and a recorded pricing snapshot. It is not an AWS bill, it is not a forecast, and it is
    only comparable with another model's figure because both are computed the same way from
    the same cases.
    """

    model_id: str | None
    calls: int
    attempts: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_usd: Decimal | None
    correct: int

    @property
    def mean_input_tokens(self) -> float | None:
        return (
            None if self.input_tokens is None or self.calls == 0 else self.input_tokens / self.calls
        )

    @property
    def mean_output_tokens(self) -> float | None:
        return (
            None
            if self.output_tokens is None or self.calls == 0
            else self.output_tokens / self.calls
        )

    def usd_per_thousand(self, price: ModelPrice | None) -> Decimal | None:
        """What a thousand calls of this shape would cost at the recorded price."""
        if price is None or self.input_tokens is None or self.output_tokens is None:
            return None
        if self.calls == 0:
            return None
        per_call = (
            Decimal(self.input_tokens) * price.input_usd_per_million
            + Decimal(self.output_tokens) * price.output_usd_per_million
        ) / (Decimal(1_000_000) * Decimal(self.calls))
        return (per_call * Decimal(1000)).quantize(Decimal("0.000001"))

    def usd_per_correct(self) -> Decimal | None:
        if self.estimated_usd is None or self.correct == 0:
            return None
        return (self.estimated_usd / Decimal(self.correct)).quantize(Decimal("0.000001"))

    def as_payload(self, price: ModelPrice | None) -> dict[str, object]:
        per_thousand = self.usd_per_thousand(price)
        per_correct = self.usd_per_correct()
        return {
            "model_id": self.model_id,
            "calls": self.calls,
            "attempts": self.attempts,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "mean_input_tokens": self.mean_input_tokens,
            "mean_output_tokens": self.mean_output_tokens,
            "estimated_usd": None if self.estimated_usd is None else str(self.estimated_usd),
            "correct": self.correct,
            "usd_per_correct_classification": None if per_correct is None else str(per_correct),
            "usd_per_thousand_classifications": (
                None if per_thousand is None else str(per_thousand)
            ),
        }


def usage_profile(
    dataset: GoldDataset, results: Sequence[CaseResult], model_id: str | None
) -> UsageProfile:
    """What one model's stored customer readings cost, counted from the results themselves."""
    scored = scores_for(dataset, results)
    tokens_reported = any(
        result.input_tokens is not None or result.output_tokens is not None for result in results
    )
    priced = [result.estimated_usd for result in results if result.estimated_usd is not None]
    return UsageProfile(
        model_id=model_id,
        calls=sum(1 for result in results if result.attempts is not None),
        attempts=sum(result.attempts or 0 for result in results),
        input_tokens=(
            sum(result.input_tokens or 0 for result in results) if tokens_reported else None
        ),
        output_tokens=(
            sum(result.output_tokens or 0 for result in results) if tokens_reported else None
        ),
        estimated_usd=sum((Decimal(value) for value in priced), Decimal(0)) if priced else None,
        correct=sum(score.correct for score in scored),
    )


def latency_profile(results: Sequence[CaseResult], field: str) -> dict[str, object] | None:
    """p50 / p95 over one latency series, or ``None`` when nothing reported it."""
    measured = sorted(value for result in results if (value := getattr(result, field)) is not None)
    if not measured:
        return None
    return {
        "count": len(measured),
        "p50_ms": measured[len(measured) // 2],
        "p95_ms": measured[min(len(measured) - 1, int(len(measured) * 0.95))],
        "max_ms": measured[-1],
    }


__all__ = [
    "MAX_STAGE_A_CASES",
    "SELECTION_ALGORITHM_VERSION",
    "SEMANTIC_OUTCOMES",
    "STAGE_A_MATERIALITY",
    "ChallengerError",
    "ChallengerPair",
    "ClusterDelta",
    "Criterion",
    "MaterialityGate",
    "MaterialityVerdict",
    "PairedCase",
    "PairedOutcome",
    "PairedTotals",
    "ProviderFailureCategory",
    "Role",
    "SourceRun",
    "StageAOutcome",
    "StageASelection",
    "UsageProfile",
    "build_stage_a",
    "cluster_deltas",
    "compare",
    "customer_development",
    "customer_totals",
    "evaluate_materiality",
    "is_directional_inversion",
    "latency_profile",
    "pair_all",
    "pair_case",
    "predicted_label",
    "provider_failure_category",
    "scores_for",
    "select_stage_a",
    "unread_result",
    "usage_profile",
]
