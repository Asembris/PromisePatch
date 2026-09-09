"""Running the explanation dataset through production's own acceptance path, offline or live.

The runner does one thing per case: build the production request, get a passage, and put that
passage through exactly the code the workflow puts it through. It does not re-implement the
acceptance rules -- it calls :func:`promisepatch.domain.verbalisation.prepare`, which is the
function the worker calls -- so a result here is a statement about PromisePatch rather than about
the harness.

**Where a passage comes from is an argument.** A provider factory is handed one model input and
returns the provider to ask. :func:`scripted_provider` is the offline one, built on the same
production fake the worker runs under by default, and it is the only one this package can build.
A live run passes a factory in from a composition root outside both cores, because an import
contract stops a vendor SDK entering this import graph at all.

**Generation and judging are two passes, not one loop.** Nova writes every passage, the results
are complete and stored, and only then is the judge asked about the accepted ones. That ordering
is what makes rejudging free: the second pass reads results and never reaches Nova.

**One judge call per accepted passage.** Not per dimension, not per metric, not per framework
callback. The counted judge refuses the call that would exceed the ceiling, so twenty-one
accepted passages cannot become a hundred and five judge calls by anybody's accident.

**A judge outage stops judging and nothing else.** Three unexpected transport failures end the
subjective pass, the generation results stand untouched, and the run reports its quality verdict
as incomplete rather than as a model that did badly.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from evals.budget import BudgetedSemanticProvider, BudgetGuard, EvalBudget
from evals.explanation_budget import RunCost, run_cost
from evals.explanation_cases import ExplanationEvalCase, ExplanationModelInput, to_model_input
from evals.explanation_dataset import ExplanationDataset
from evals.explanation_judge import (
    CountedJudge,
    JudgeNotConfiguredError,
    ScriptedJudge,
    StructuredJudge,
    build_judge_request,
    to_judge_result,
)
from evals.explanation_metrics import (
    Acceptance,
    CaseScore,
    FamilyMetrics,
    GateOutcome,
    HardMetrics,
    QualityMetrics,
    SemanticMetrics,
    acceptance,
    evaluate_gates,
    fallback_failures,
    family_metrics,
    gate_status,
    hard_metrics,
    quality_metrics,
    score_cases,
    semantic_metrics,
)
from evals.explanation_results import (
    NO_USAGE,
    ExplanationFailureKind,
    ExplanationJudgeResult,
    ExplanationSource,
    GenerationIdentity,
    NovaExplanationResult,
    Usage,
)
from evals.explanation_thresholds import MAX_JUDGE_PROVIDER_FAILURES, RUBRIC_VERSION
from evals.prompts import prompt_identity
from promisepatch.domain import verbalisation
from promisepatch.domain.verbalisation import Explanation, ExplanationFailure
from promisepatch.semantic import FakeSemanticProvider, SemanticJob, SemanticProvider

REPLAY_MODE = "replay"
"""Every passage came from a scripted payload. Nothing was reached and nothing was spent."""

LIVE_MODE = "live"
"""A real provider answered. Only reachable by passing one in; nothing here can build one."""

SCRIPT_FILE = Path(__file__).parent / "datasets" / "explanation_scripted.json"
JUDGE_SCRIPT_FILE = Path(__file__).parent / "datasets" / "explanation_judge_scripted.json"

type ExplanationProviderFactory = Callable[[ExplanationModelInput], SemanticProvider]
"""How one case gets something to ask. The whole of the seam a live run needs."""


_GROUNDING_KINDS: Final[Mapping[str, ExplanationFailureKind]] = {
    "UNKNOWN_CANDIDATE": ExplanationFailureKind.UNKNOWN_FACT_REF,
    "MISSING_REQUIRED_FACT": ExplanationFailureKind.MISSING_REQUIRED_FACT,
    "WORD_CAP_EXCEEDED": ExplanationFailureKind.WORD_CAP,
    "UNSUPPORTED_QUANTITY": ExplanationFailureKind.UNSUPPORTED_DIGIT,
}
"""Production records a grounding refusal as one failure with the category in its detail line.

The four are separated back out here because they are four different findings about a model: one
reached past its facts, one dropped the cause, one ignored the cap and one invented a number.
Collapsing them would leave a report unable to say which.
"""


class ScriptedExplanations:
    """The payloads a provider returns for each case, in attempt order.

    Hand-authored engineering fixtures, not model output and not evidence about any model. They
    exist so the whole path -- dataset, acceptance, structural scoring, judging, gates, report --
    can be exercised and its failure branches proved without an AWS account.
    """

    def __init__(self, payloads: Mapping[str, Sequence[object]]) -> None:
        self._payloads = {case_id: list(attempts) for case_id, attempts in payloads.items()}

    @classmethod
    def from_file(cls, path: Path = SCRIPT_FILE) -> ScriptedExplanations:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls({case_id: list(items) for case_id, items in raw.get("answers", {}).items()})

    def for_case(self, case_id: str) -> list[object]:
        return list(self._payloads.get(case_id, ()))

    def __len__(self) -> int:
        return len(self._payloads)


def scripted_verdicts(path: Path = JUDGE_SCRIPT_FILE) -> dict[str, list[object]]:
    """The hand-authored verdicts an offline run judges with. Never a model's opinion."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {case_id: list(items) for case_id, items in raw.get("verdicts", {}).items()}


def scripted_provider(answers: ScriptedExplanations) -> ExplanationProviderFactory:
    """The offline factory: the production fake, scripted per case. Reaches nothing, ever."""

    def build(model_input: ExplanationModelInput) -> SemanticProvider:
        return FakeSemanticProvider({SemanticJob.VERBALISE: answers.for_case(model_input.case_id)})

    return build


# ------------------------------------------------------------------------- generation


@dataclass(frozen=True, slots=True)
class GenerationOutcome:
    """Everything the generation pass produced, before anything grades it."""

    results: tuple[NovaExplanationResult, ...]
    guard: BudgetGuard
    provider: str
    model_id: str | None
    run_id: str
    mode: str


def _failure_kind(explanation: Explanation) -> ExplanationFailureKind | None:
    if explanation.failure is None:
        return None
    if explanation.failure is ExplanationFailure.PROVIDER_FAILURE:
        return ExplanationFailureKind.PROVIDER_FAILURE
    if explanation.failure is ExplanationFailure.GROUNDING_REJECTED:
        category = (explanation.detail or "").split(":", 1)[0]
        return _GROUNDING_KINDS.get(category, ExplanationFailureKind.SCHEMA_REJECTION)
    return ExplanationFailureKind.SCHEMA_REJECTION


def _identity(
    case: ExplanationEvalCase,
    dataset: ExplanationDataset,
    explanation: Explanation,
    *,
    provider: str,
    model_id: str | None,
    git_sha: str | None,
    run_id: str,
) -> GenerationIdentity:
    prompt = prompt_identity(SemanticJob.VERBALISE)
    from evals.explanation_dataset import DATASET_NAME

    return GenerationIdentity(
        provider=provider,
        model_id=model_id,
        git_sha=git_sha,
        dataset_name=DATASET_NAME,
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        case_id=case.id,
        family=case.family,
        facts_fingerprint=explanation.fingerprint,
        prompt_system_hash=prompt.system_hash,
        schema_hash=prompt.schema_hash,
        word_limit=case.word_limit,
        run_id=run_id,
    )


async def generate(
    dataset: ExplanationDataset,
    factory: ExplanationProviderFactory,
    *,
    guard: BudgetGuard,
    provider_name: str,
    model_id: str | None = None,
    git_sha: str | None = None,
    run_id: str | None = None,
    mode: str = REPLAY_MODE,
    on_result: Callable[[NovaExplanationResult], None] | None = None,
) -> GenerationOutcome:
    """Ask for one passage per case, through production's own acceptance path.

    Every provider is wrapped in the budget guard before being asked anything, so a factory
    cannot hand in one that skips the accounting. ``on_result`` is called with each result as it
    is produced, which is how a live run writes a passage down before anything else can go wrong
    with it.
    """
    identifier = run_id or uuid.uuid4().hex[:12]
    results: list[NovaExplanationResult] = []
    for case in dataset.cases:
        model_input = to_model_input(case)
        provider = BudgetedSemanticProvider(factory(model_input), guard)
        explanation = await verbalisation.prepare(provider, case.explanation_facts())
        # A provider that could not be built never sent this case's request, so what came back
        # is production's fallback rather than an observation about the model. Recorded as the
        # non-terminal kind, with the call it never made counted as neither a call nor an
        # attempt: the guard has already handed that permission back.
        not_prepared = provider.not_prepared
        usage = (
            Usage(logical_calls=0, provider_attempts=0)
            if not_prepared
            else Usage(logical_calls=1, provider_attempts=explanation.attempts or 1)
        )
        result = NovaExplanationResult(
            identity=_identity(
                case,
                dataset,
                explanation,
                provider=provider_name,
                model_id=explanation.model_id or model_id,
                git_sha=git_sha,
                run_id=identifier,
            ),
            split=case.split,
            source=ExplanationSource(explanation.source.value),
            speech=explanation.speech,
            fact_refs=explanation.fact_refs,
            failure=(
                ExplanationFailureKind.PROVIDER_NOT_PREPARED
                if not_prepared
                else _failure_kind(explanation)
            ),
            detail=explanation.detail,
            usage=usage,
        )
        results.append(result)
        if on_result is not None:
            on_result(result)
    return GenerationOutcome(
        results=tuple(results),
        guard=guard,
        provider=provider_name,
        model_id=model_id,
        run_id=identifier,
        mode=mode,
    )


# ---------------------------------------------------------------------------- judging


@dataclass(frozen=True, slots=True)
class JudgingOutcome:
    """Every verdict the judge produced, and why it stopped if it did."""

    results: tuple[ExplanationJudgeResult, ...]
    usage: Usage
    provider: str
    model_id: str | None
    stopped: str | None = None
    """Why judging ended early, or ``None``. A stopped pass is reported as stopped, never as a
    smaller one whose numbers happen to look fine."""

    @property
    def complete(self) -> bool:
        return self.stopped is None


async def judge_explanations(
    dataset: ExplanationDataset,
    results: Sequence[NovaExplanationResult],
    judge: CountedJudge | None,
    *,
    run_id: str,
    on_result: Callable[[ExplanationJudgeResult], object] | None = None,
) -> JudgingOutcome:
    """One structured verdict per accepted passage, and none for anything else.

    A fallback is not judged: PromisePatch wrote it, and grading our own template against our own
    facts would put a number on the harness. A refused passage is not judged either -- it is not
    on screen, and a judge's opinion could not put it there.

    Judging stops after :data:`~evals.explanation_thresholds.MAX_JUDGE_PROVIDER_FAILURES`
    unexpected transport failures. The generation results are untouched by that: an outage at the
    judge is an outage at the judge.

    ``on_result`` is called with each verdict as it is produced, which is how a live run writes
    one down before anything else can go wrong with it -- the same seam :func:`generate` has,
    for the same reason. A judge call against a free endpoint costs no money and still spends a
    quota nobody gets back.
    """
    if judge is None:
        raise JudgeNotConfiguredError(
            "no judge provider and model were named. Judging refuses rather than selecting a "
            "default: an evaluation model nobody chose is an opinion nobody authorised."
        )
    by_id = {case.id: case for case in dataset.cases}
    verdicts: list[ExplanationJudgeResult] = []
    stopped: str | None = None
    for result in results:
        if stopped is not None:
            break
        if not result.accepted:
            continue
        case = by_id.get(result.case_id)
        if case is None:  # pragma: no cover - a result outside the loaded split
            continue
        request = build_judge_request(
            case.id, case.family, to_model_input(case).request, result.speech
        )
        judgement = await judge.judge(request)
        verdict = to_judge_result(
            result,
            judgement,
            provider=judge.name,
            model_id=judge.model_id,
            run_id=run_id,
        )
        verdicts.append(verdict)
        if on_result is not None:
            on_result(verdict)
        if judge.provider_failures >= MAX_JUDGE_PROVIDER_FAILURES:
            stopped = (
                f"{judge.provider_failures} judge provider failures; subjective quality is "
                f"INCOMPLETE and no other judge was tried"
            )
    return JudgingOutcome(
        results=tuple(verdicts),
        usage=judge.usage,
        provider=judge.name,
        model_id=judge.model_id,
        stopped=stopped,
    )


# ---------------------------------------------------------------------------- summary


@dataclass(frozen=True, slots=True)
class ExplanationRunSummary:
    """Everything one explanation run knows about itself, in one serialisable record."""

    run_id: str
    mode: str
    git_sha: str | None
    dataset_name: str
    dataset_version: str
    dataset_hash: str
    splits: tuple[str, ...]
    generation_provider: str
    generation_model_id: str | None
    judge_provider: str | None
    judge_model_id: str | None
    rubric_version: str
    acceptance: Acceptance
    hard: HardMetrics
    semantic: SemanticMetrics
    quality: QualityMetrics
    families: tuple[FamilyMetrics, ...]
    scores: tuple[CaseScore, ...]
    cost: RunCost
    generation_usage: Usage
    judge_usage: Usage
    gates: tuple[GateOutcome, ...]
    gate_status: str
    judging_stopped: str | None = None
    fallback_problems: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "git_sha": self.git_sha,
            "dataset": {
                "name": self.dataset_name,
                "version": self.dataset_version,
                "content_hash": self.dataset_hash,
                "splits": list(self.splits),
            },
            "system_under_test": {
                "provider": self.generation_provider,
                "model_id": self.generation_model_id,
            },
            "judge": {
                "provider": self.judge_provider,
                "model_id": self.judge_model_id,
                "rubric_version": self.rubric_version,
                "stopped": self.judging_stopped,
            },
            "acceptance": self.acceptance.as_payload(),
            "hard": self.hard.as_payload(),
            "semantic": self.semantic.as_payload(),
            "quality": self.quality.as_payload(),
            "families": {metrics.family.value: metrics.as_payload() for metrics in self.families},
            "cases": [score.as_payload() for score in self.scores],
            "cost": self.cost.as_payload(),
            "usage": {
                "generation": self.generation_usage.model_dump(mode="json"),
                "judge": self.judge_usage.model_dump(mode="json"),
            },
            "fallback_problems": list(self.fallback_problems),
            "gates": [gate.as_payload() for gate in self.gates],
            "gate_status": self.gate_status,
        }


def build_summary(
    dataset: ExplanationDataset,
    generation: GenerationOutcome,
    judging: JudgingOutcome | None = None,
    *,
    git_sha: str | None = None,
) -> ExplanationRunSummary:
    """Assemble one run's whole score. Calls nothing and can be run again over stored results."""
    from evals.explanation_dataset import DATASET_NAME

    judgements = () if judging is None else judging.results
    problems = fallback_failures(dataset.cases)
    scores = score_cases(dataset.cases, generation.results, judgements)
    hard = hard_metrics(dataset.cases, generation.results, fallback_problems=problems)
    semantic = semantic_metrics(scores)
    quality = quality_metrics(scores)
    families = family_metrics(dataset.cases, generation.results, scores)
    spend = generation.guard.spend
    generation_usage = Usage(
        logical_calls=spend.calls,
        provider_attempts=spend.attempts,
        input_tokens=spend.input_tokens if spend.tokens_reported else None,
        output_tokens=spend.output_tokens if spend.tokens_reported else None,
    )
    judge_usage = Usage() if judging is None else judging.usage
    cost = run_cost(
        generation_input_tokens=generation_usage.input_tokens,
        generation_output_tokens=generation_usage.output_tokens,
        judge_input_tokens=judge_usage.input_tokens,
        judge_output_tokens=judge_usage.output_tokens,
    )
    payload: dict[str, object] = {
        "hard": hard.as_payload(),
        "semantic": semantic.as_payload(),
        "quality": quality.as_payload(),
        "families": {metrics.family.value: metrics.as_payload() for metrics in families},
    }
    gates = evaluate_gates(payload)
    return ExplanationRunSummary(
        run_id=generation.run_id,
        mode=generation.mode,
        git_sha=git_sha,
        dataset_name=DATASET_NAME,
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        splits=tuple(sorted({case.split.value for case in dataset.cases})),
        generation_provider=generation.provider,
        generation_model_id=generation.model_id,
        judge_provider=None if judging is None else judging.provider,
        judge_model_id=None if judging is None else judging.model_id,
        rubric_version=RUBRIC_VERSION,
        acceptance=acceptance(generation.results),
        hard=hard,
        semantic=semantic,
        quality=quality,
        families=families,
        scores=scores,
        cost=cost,
        generation_usage=generation_usage,
        judge_usage=judge_usage,
        gates=gates,
        gate_status=gate_status(gates),
        judging_stopped=None if judging is None else judging.stopped,
        fallback_problems=problems,
    )


async def run_offline(
    dataset: ExplanationDataset,
    answers: ScriptedExplanations | None = None,
    judge_answers: Mapping[str, Sequence[object]] | None = None,
    *,
    budget: EvalBudget | None = None,
    judge_call_ceiling: int | None = None,
) -> ExplanationRunSummary:
    """Score the whole dataset from scripted payloads. Reaches no network, ever."""
    scripted = answers or ScriptedExplanations.from_file()
    guard = BudgetGuard(budget or EvalBudget(), price=None, live=False)
    generation = await generate(
        dataset, scripted_provider(scripted), guard=guard, provider_name=FakeSemanticProvider.name
    )
    verdicts = scripted_verdicts() if judge_answers is None else judge_answers
    judge = CountedJudge(
        StructuredJudge(ScriptedJudge(verdicts)),
        max_logical_calls=judge_call_ceiling,
    )
    judging = await judge_explanations(dataset, generation.results, judge, run_id=generation.run_id)
    return build_summary(dataset, generation, judging)


def rescore(
    dataset: ExplanationDataset,
    results: Sequence[NovaExplanationResult],
    judgements: Sequence[ExplanationJudgeResult] = (),
    *,
    run_id: str,
    provider: str,
    model_id: str | None = None,
    judge_provider: str | None = None,
    judge_model_id: str | None = None,
    generation_usage: Usage = NO_USAGE,
    judge_usage: Usage = NO_USAGE,
    git_sha: str | None = None,
    mode: str = REPLAY_MODE,
) -> ExplanationRunSummary:
    """Rebuild a whole summary from stored results. Zero Nova calls and zero judge calls.

    The operation that makes a lost terminal cheap and a metric change free. Every deterministic
    number in a report is a function of what is already on disk, so a scorer can be fixed and the
    run it was wrong about re-read rather than re-bought.
    """
    guard = BudgetGuard(EvalBudget(), price=None, live=False)
    guard.spend.calls = generation_usage.logical_calls
    guard.spend.attempts = generation_usage.provider_attempts
    if generation_usage.input_tokens is not None or generation_usage.output_tokens is not None:
        guard.spend.tokens_reported = True
        guard.spend.input_tokens = generation_usage.input_tokens or 0
        guard.spend.output_tokens = generation_usage.output_tokens or 0
    generation = GenerationOutcome(
        results=tuple(results),
        guard=guard,
        provider=provider,
        model_id=model_id,
        run_id=run_id,
        mode=mode,
    )
    judging = (
        None
        if judge_provider is None
        else JudgingOutcome(
            results=tuple(judgements),
            usage=judge_usage,
            provider=judge_provider,
            model_id=judge_model_id,
        )
    )
    return build_summary(dataset, generation, judging, git_sha=git_sha)


def judgeable(results: Sequence[NovaExplanationResult]) -> tuple[NovaExplanationResult, ...]:
    """The passages a judge may be asked about: accepted model prose, and nothing else."""
    return tuple(result for result in results if result.accepted)


def rejudgeable(
    stored: Sequence[NovaExplanationResult], current: Sequence[NovaExplanationResult]
) -> tuple[str, ...]:
    """Cases whose production request has moved, so a stored passage cannot be rejudged.

    Rejudging a passage written under a different prompt, schema, cap or set of facts would put
    a fresh verdict on a stale answer and file it as this run's. The fingerprint is what makes
    that checkable, and this is the check.
    """
    fingerprints = {result.case_id: result.identity.fingerprint() for result in current}
    return tuple(
        result.case_id
        for result in stored
        if fingerprints.get(result.case_id) != result.identity.fingerprint()
    )


__all__ = [
    "JUDGE_SCRIPT_FILE",
    "LIVE_MODE",
    "REPLAY_MODE",
    "SCRIPT_FILE",
    "ExplanationProviderFactory",
    "ExplanationRunSummary",
    "GenerationOutcome",
    "JudgingOutcome",
    "ScriptedExplanations",
    "build_summary",
    "generate",
    "judge_explanations",
    "judgeable",
    "rejudgeable",
    "rescore",
    "run_offline",
    "scripted_provider",
    "scripted_verdicts",
]
