"""Running the dataset, offline, through the production acceptance path.

The runner does one thing per case: build the question, get an answer, and put that answer
through exactly the code the workflow would put it through. Nothing here re-implements
validation, grounding or interpretation -- it calls them, which is what makes the result a
statement about PromisePatch rather than about the harness.

**Every answer comes from a scripted payload.** The provider is
:class:`~promisepatch.semantic.fake.FakeSemanticProvider`, the same one the worker runs under
by default: it reaches no network, holds no credential and imports no SDK, and its answers go
through the same :func:`~promisepatch.semantic.jobs.validate` gate a real model's would. There
is no branch here that could construct a Bedrock client, and an import-linter contract stops
one being added.

**A scripted answer is a list, because a real one is too.** The boundary gives a
schema-invalid answer exactly one corrective retry, so a case whose first payload is refused
and whose second is not is a case that cost two attempts and produced a value -- which is what
production does, and what the cost accounting has to be able to say.

**Cases the boundary never asks about are not asked about here.** A sentence the deterministic
lexicon reads never reaches a provider in production, so the runner does not build one for it,
and the score for that case is the assertion that no call was made.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from evals import context
from evals.budget import BudgetedSemanticProvider, BudgetGuard, EvalBudget
from evals.cases import CustomerCase, GoldCase, ModelInput, WorkerCase, to_model_input
from evals.dataset import GoldDataset
from evals.metrics import customer as customer_metrics
from evals.metrics import worker as worker_metrics
from evals.observed import CaseObservation, CustomerObservation, Refusal, WorkerObservation
from evals.results import CaseResult
from promisepatch.domain import grounding as grounding_rules
from promisepatch.domain import interpretation
from promisepatch.domain.observation import EscalationReason, InterpretationOutcome
from promisepatch.semantic import (
    FakeSemanticProvider,
    InterpretUtteranceRequest,
    ObservationInterpretation,
    ReplyIntentReading,
    SemanticError,
    SemanticProviderError,
    SemanticResult,
    SemanticValidationError,
)

REPLAY_MODE = "replay"
"""The only mode the commands in this package run in. A live mode reaches AWS; none does."""

SCRIPT_FILE = Path(__file__).parent / "datasets" / "scripted_answers.json"


class ScriptedAnswers:
    """The payloads a provider returns for each case, in attempt order.

    Hand-authored engineering fixtures, not model output and not evidence about any model. They
    exist so that the whole path -- dataset, runner, metric, gate, report -- can be exercised
    and its failure branches proved without an AWS account. A case with no entry gets the
    fake's own cautious default, which is what a provider that understood nothing returns.
    """

    def __init__(self, payloads: Mapping[str, Sequence[object]]) -> None:
        self._payloads = {case_id: list(attempts) for case_id, attempts in payloads.items()}

    @classmethod
    def from_file(cls, path: Path = SCRIPT_FILE) -> ScriptedAnswers:
        raw = json.loads(path.read_text(encoding="utf-8"))
        answers = raw.get("answers", {})
        return cls({case_id: list(attempts) for case_id, attempts in answers.items()})

    def for_case(self, case_id: str) -> list[object]:
        return list(self._payloads.get(case_id, ()))

    def case_ids(self) -> frozenset[str]:
        return frozenset(self._payloads)

    def __len__(self) -> int:
        return len(self._payloads)


@dataclass(frozen=True, slots=True)
class Answer:
    """One case's trip through the acceptance path: a result, or the refusal that replaced it."""

    result: SemanticResult | None
    refusal: CaseObservation | None
    provider_calls: int


@dataclass(frozen=True, slots=True)
class Operational:
    """What the provider published about producing one answer. Absent values stay absent."""

    model_id: str | None = None
    attempts: int | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """Everything one run produced, before it is turned into a summary."""

    results: tuple[CaseResult, ...]
    worker_scores: tuple[worker_metrics.WorkerScore, ...]
    customer_scores: tuple[customer_metrics.CustomerScore, ...]
    guard: BudgetGuard
    provider: str
    model_id: str | None


async def run_offline(
    dataset: GoldDataset,
    answers: ScriptedAnswers,
    *,
    budget: EvalBudget | None = None,
) -> RunOutcome:
    """Score every case in the dataset from scripted answers. Reaches no network, ever."""
    guard = BudgetGuard(budget or EvalBudget(), price=None, live=False)
    results: list[CaseResult] = []
    worker_scores: list[worker_metrics.WorkerScore] = []
    customer_scores: list[customer_metrics.CustomerScore] = []

    for case in dataset.worker:
        worker_result, worker_score = await _run_worker(case, answers, guard)
        results.append(worker_result)
        worker_scores.append(worker_score)
    for customer_case in dataset.customer:
        customer_result, customer_score = await _run_customer(customer_case, answers, guard)
        results.append(customer_result)
        customer_scores.append(customer_score)

    return RunOutcome(
        results=tuple(results),
        worker_scores=tuple(worker_scores),
        customer_scores=tuple(customer_scores),
        guard=guard,
        provider=FakeSemanticProvider.name,
        model_id=None,
    )


async def _ask(model_input: ModelInput, answers: ScriptedAnswers, guard: BudgetGuard) -> Answer:
    """Put one question to the scripted provider through the budget guard.

    ``provider_calls`` is what proves, for a case the boundary forbids, that nothing was asked.
    """
    provider = FakeSemanticProvider(
        {model_input.job.semantic_job: answers.for_case(model_input.case_id)}
    )
    budgeted = BudgetedSemanticProvider(provider, guard)
    try:
        result = await budgeted.run(model_input.request)
    except SemanticValidationError as error:
        refusal = Refusal(category=error.category.value)
    except SemanticProviderError as error:
        refusal = Refusal(category=type(error).__name__, provider_error=True)
    except SemanticError as error:  # pragma: no cover - the two subclasses cover the surface
        refusal = Refusal(category=type(error).__name__)
    else:
        return Answer(result=result, refusal=None, provider_calls=len(provider.calls))
    return Answer(result=None, refusal=CaseObservation(refusal), provider_calls=len(provider.calls))


async def _run_worker(
    case: WorkerCase, answers: ScriptedAnswers, guard: BudgetGuard
) -> tuple[CaseResult, worker_metrics.WorkerScore]:
    if not case.asked:
        score = worker_metrics.score_unasked(case, provider_calls=0)
        return _worker_result(case, score, None, None), score

    model_input = to_model_input(case)
    request = model_input.request
    if not isinstance(request, InterpretUtteranceRequest):  # pragma: no cover - job is fixed
        raise TypeError(f"{case.id}: a worker case built a non-worker request")

    answer = await _ask(model_input, answers, guard)
    if answer.result is None:
        refusal = answer.refusal
        if refusal is None:  # pragma: no cover - one of the two is always present
            raise AssertionError(f"{case.id}: neither a result nor a refusal")
        score = worker_metrics.score_worker(case, refusal.observed, request=request)
        return _worker_result(case, score, refusal, None), score

    value = answer.result.value
    if not isinstance(value, ObservationInterpretation):  # pragma: no cover - job is fixed
        raise TypeError(f"{case.id}: the worker job returned {type(value).__name__}")

    observation = context.observation_context(case.id, case.utterance)
    resolution = grounding_rules.resolve_semantic_observation(
        observation,
        value,
        deterministic_reason=case.deterministic_reason or EscalationReason.NO_CATEGORY,
    )
    observed = WorkerObservation(
        reading=value, grounding=resolution.grounding, outcome=resolution.outcome
    )
    score = worker_metrics.score_worker(
        case,
        observed,
        request=request,
        deterministic_outcome=_deterministic_from_accepted(case, observed),
    )
    carried = CaseObservation(observed, answer.result.telemetry)
    return _worker_result(case, score, carried, observed), score


def _deterministic_from_accepted(
    case: WorkerCase, observed: WorkerObservation
) -> InterpretationOutcome | None:
    """What the deterministic interpreter reaches from the identity that was accepted.

    ``None`` when nothing grounded, because there is no identity to interpret from. When there
    is one, the observed outcome must equal this: anything else means a claim about the world
    came from somewhere other than the interpreter, which is a safety finding and not a quality
    one.
    """
    accepted = observed.accepted_resource_id
    if accepted is None or observed.grounding.category is None:
        return None
    observation = context.observation_context(case.id, case.utterance)
    resource = observation.resource(accepted)
    if resource is None:  # pragma: no cover - grounding refuses ids the context lacks
        return None
    return interpretation.interpret_grounded(
        observation, category=observed.grounding.category, resource=resource
    )


async def _run_customer(
    case: CustomerCase, answers: ScriptedAnswers, guard: BudgetGuard
) -> tuple[CaseResult, customer_metrics.CustomerScore]:
    model_input = to_model_input(case)
    answer = await _ask(model_input, answers, guard)
    if answer.result is None:
        refusal = answer.refusal
        if refusal is None:  # pragma: no cover - one of the two is always present
            raise AssertionError(f"{case.id}: neither a result nor a refusal")
        score = customer_metrics.score_customer(case, refusal.observed)
        return _customer_result(case, score, refusal), score

    value = answer.result.value
    if not isinstance(value, ReplyIntentReading):  # pragma: no cover - job is fixed
        raise TypeError(f"{case.id}: the customer job returned {type(value).__name__}")
    observed = CustomerObservation(reading=value)
    score = customer_metrics.score_customer(case, observed)
    carried = CaseObservation(observed, answer.result.telemetry)
    return _customer_result(case, score, carried), score


# ------------------------------------------------------------------------------- results


def _operational(observation: CaseObservation | None) -> Operational:
    telemetry = observation.telemetry if observation is not None else None
    if telemetry is None:
        return Operational()
    return Operational(
        model_id=telemetry.model_id,
        attempts=telemetry.attempts,
        latency_ms=telemetry.usage.latency_ms,
        input_tokens=telemetry.usage.input_tokens,
        output_tokens=telemetry.usage.output_tokens,
    )


def _expected_worker(case: WorkerCase) -> dict[str, object]:
    if case.expected is None:
        return {"asked": False, "deterministic": case.deterministic.value}
    expected = case.expected
    return {
        "asked": True,
        "category": None if expected.category is None else expected.category.value,
        "resource_id": expected.resource_id,
        "proposed_resource_ids": list(expected.proposals),
        "out_of_scope": expected.out_of_scope,
        "grounding": expected.grounding.value,
        "outcome": expected.outcome.value,
        "clarification_slot": (
            None if expected.clarification_slot is None else expected.clarification_slot.value
        ),
        "escalation_reason": (
            None if expected.escalation_reason is None else expected.escalation_reason.value
        ),
    }


def _observed_worker(observed: WorkerObservation | None) -> dict[str, object]:
    if observed is None:
        return {}
    reading = observed.reading
    return {
        "category": None if reading.category is None else reading.category.value,
        "proposed": list(observed.grounding.proposed),
        "accepted": list(observed.grounding.accepted),
        "dropped": list(observed.grounding.dropped),
        "out_of_scope": reading.out_of_scope,
        "grounding": observed.grounding.failure.value,
        "outcome": observed.outcome_kind.value,
        "clarification_slot": (
            None if observed.clarification_slot is None else observed.clarification_slot.value
        ),
        "escalation_reason": (
            None if observed.escalation_reason is None else observed.escalation_reason.value
        ),
    }


def _worker_result(
    case: WorkerCase,
    score: worker_metrics.WorkerScore,
    observation: CaseObservation | None,
    observed: WorkerObservation | None,
) -> CaseResult:
    metrics = score.as_mapping()
    verdict = worker_metrics.worker_verdict(metrics)
    operational = _operational(observation)
    carried = observation.observed if observation is not None else None
    return CaseResult(
        case_id=case.id,
        job=case.job,
        split=case.split,
        tags=case.tags,
        expected=_expected_worker(case),
        observed=_observed_worker(observed),
        metrics=metrics,
        passed=verdict.passed,
        reason=verdict.reason,
        provider=FakeSemanticProvider.name,
        error_category=carried.category if isinstance(carried, Refusal) else None,
        model_id=operational.model_id,
        attempts=operational.attempts,
        latency_ms=operational.latency_ms,
        input_tokens=operational.input_tokens,
        output_tokens=operational.output_tokens,
    )


def _customer_result(
    case: CustomerCase, score: customer_metrics.CustomerScore, observation: CaseObservation
) -> CaseResult:
    metrics = score.as_mapping()
    verdict = customer_metrics.customer_verdict(metrics)
    operational = _operational(observation)
    carried = observation.observed
    return CaseResult(
        case_id=case.id,
        job=case.job,
        split=case.split,
        tags=case.tags,
        expected={"apparent_intent": case.expected.value},
        observed={"apparent_intent": None if score.predicted is None else score.predicted.value},
        metrics=metrics,
        passed=verdict.passed,
        reason=verdict.reason,
        provider=FakeSemanticProvider.name,
        error_category=carried.category if isinstance(carried, Refusal) else None,
        model_id=operational.model_id,
        attempts=operational.attempts,
        latency_ms=operational.latency_ms,
        input_tokens=operational.input_tokens,
        output_tokens=operational.output_tokens,
    )


def new_run_id() -> str:
    """A fresh identity for one run.

    Random rather than derived: two runs of the same dataset at the same commit are two runs,
    and a comparison that silently collapsed them would hide a difference somebody cared about.
    """
    return uuid.uuid4().hex[:12]


def case_of(dataset: GoldDataset, case_id: str) -> GoldCase | None:
    """The case with this id, or ``None``. Used by the DeepEval adapter and by tests."""
    for case in dataset.cases:
        if case.id == case_id:
            return case
    return None


__all__ = [
    "REPLAY_MODE",
    "SCRIPT_FILE",
    "Answer",
    "Operational",
    "RunOutcome",
    "ScriptedAnswers",
    "case_of",
    "new_run_id",
    "run_offline",
]
