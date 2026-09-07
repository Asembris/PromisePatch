"""Running the dataset through the production acceptance path, offline or against a model.

The runner does one thing per case: build the question, get an answer, and put that answer
through exactly the code the workflow would put it through. Nothing here re-implements
validation, grounding or interpretation -- it calls them, which is what makes the result a
statement about PromisePatch rather than about the harness.

**Where the answer comes from is an argument.** A :data:`ProviderFactory` is handed one
model input and returns the provider to ask. :func:`scripted_provider` is the offline one --
:class:`~promisepatch.semantic.fake.FakeSemanticProvider`, the same one the worker runs under
by default, reaching no network, holding no credential and importing no SDK -- and it is the
only one this package can build. A live benchmark passes a factory in from a composition root
outside both cores, because an import-linter contract stops an AWS SDK entering this package's
import graph at all. The seam is a parameter; it is not a branch, and there is no flag here
that turns a replay into a spend.

**The budget wrapper is applied here, not by the caller.** :func:`_ask` wraps whatever the
factory returned in :class:`~evals.budget.BudgetedSemanticProvider` before asking it anything,
so a factory cannot hand in a provider that skips the accounting -- not by mistake and not on
purpose. There is one path to a provider call and it is counted.

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
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from evals import context
from evals.budget import BudgetedSemanticProvider, BudgetGuard, EvalBudget, estimate_usd
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
    ApparentIntent,
    FakeSemanticProvider,
    InterpretUtteranceRequest,
    ObservationInterpretation,
    ReplyIntentReading,
    SemanticError,
    SemanticProvider,
    SemanticProviderError,
    SemanticResult,
    SemanticValidationError,
)

REPLAY_MODE = "replay"
"""Every answer came from a scripted payload. Nothing was reached and nothing was spent."""

LIVE_MODE = "live"
"""A real provider answered. Only reachable by passing one in; nothing here can build one."""

SCRIPT_FILE = Path(__file__).parent / "datasets" / "scripted_answers.json"

type ProviderFactory = Callable[[ModelInput], SemanticProvider]
"""How one case gets something to ask. The whole of the seam a live benchmark needs."""


@dataclass(frozen=True, slots=True)
class StopPolicy:
    """When a run gives up rather than spending more.

    Both bounds exist because the failure they describe gets more expensive the longer it is
    tolerated. A hard-safety violation means the thing the benchmark was checking for has
    already happened, and the remaining cases would buy more copies of the same finding. A
    string of transport failures means the infrastructure is not answering, and retrying a
    whole split is how a benchmark's cost stops relating to its dataset.
    """

    max_provider_failures: int | None = None
    stop_on_safety_violation: bool = False


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


def scripted_provider(answers: ScriptedAnswers) -> ProviderFactory:
    """The offline factory: a deterministic fake, scripted per case. Reaches nothing, ever."""

    def build(model_input: ModelInput) -> SemanticProvider:
        return FakeSemanticProvider(
            {model_input.job.semantic_job: answers.for_case(model_input.case_id)}
        )

    return build


@dataclass(frozen=True, slots=True)
class Answer:
    """One case's trip through the acceptance path: a result, or the refusal that replaced it."""

    result: SemanticResult | None
    refusal: CaseObservation | None
    provider_calls: int
    e2e_latency_ms: int | None = None


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
    provider_failures: int = 0
    stopped: str | None = None
    """Why the run ended early, or ``None`` when it ran to the end.

    A stopped run is reported as stopped rather than as a smaller run. Its numbers describe
    the cases it reached and nothing else, and a reader has to be told which of the two they
    are looking at.
    """

    reused: int = 0
    """Cases answered by an earlier attempt at this run and read back rather than re-asked."""


async def run_offline(
    dataset: GoldDataset,
    answers: ScriptedAnswers,
    *,
    budget: EvalBudget | None = None,
) -> RunOutcome:
    """Score every case in the dataset from scripted answers. Reaches no network, ever."""
    return await run_cases(
        dataset,
        scripted_provider(answers),
        guard=BudgetGuard(budget or EvalBudget(), price=None, live=False),
        provider_name=FakeSemanticProvider.name,
    )


async def run_cases(
    dataset: GoldDataset,
    factory: ProviderFactory,
    *,
    guard: BudgetGuard,
    provider_name: str,
    mode: str = REPLAY_MODE,
    expected_model_id: str | None = None,
    reuse: Sequence[CaseResult] = (),
    on_result: Callable[[CaseResult], None] | None = None,
    stop: StopPolicy | None = None,
) -> RunOutcome:
    """Score every case, asking ``factory`` for whatever answers each one.

    ``reuse`` is what an earlier attempt at this same run already paid for: those cases are
    scored from their stored result and no provider is asked about them again. ``on_result``
    is called with each case result as it is produced, which is how a live run writes its
    answers down before anything else can go wrong with them.

    ``expected_model_id`` is checked against what each answer's telemetry reports. A benchmark
    that silently measured a different model than the one it names would be worse than no
    benchmark, and the default configured model in this repository is not the one this slice
    is about -- so the mismatch is a stop, not a warning.
    """
    policy = stop or StopPolicy()
    stored = {result.case_id: result for result in reuse}
    results: list[CaseResult] = []
    worker_scores: list[worker_metrics.WorkerScore] = []
    customer_scores: list[customer_metrics.CustomerScore] = []
    failures = 0
    stopped: str | None = None
    reused = 0

    def keep(result: CaseResult, *, fresh: bool) -> None:
        results.append(result)
        if fresh and on_result is not None:
            on_result(result)

    for case in dataset.cases:
        if stopped is not None:
            break
        previous = stored.get(case.id)
        if previous is not None:
            score = _rescore(case, previous)
            _collect(score, worker_scores, customer_scores)
            keep(previous, fresh=False)
            reused += 1
        elif isinstance(case, WorkerCase):
            previous, worker_score = await _run_worker(case, factory, guard, mode=mode)
            worker_scores.append(worker_score)
            keep(previous, fresh=True)
            failures += int(previous.provider_error)
        else:
            previous, customer_score = await _run_customer(case, factory, guard, mode=mode)
            customer_scores.append(customer_score)
            keep(previous, fresh=True)
            failures += int(previous.provider_error)

        # Checked for a reused result as well as a fresh one. A run that resumed past a
        # violation it had already recorded would be a benchmark continuing after the protocol
        # said to stop -- silently, and using a result somebody had already paid for.
        limit = policy.max_provider_failures
        if limit is not None and failures >= limit:
            stopped = (
                f"{failures} provider or transport failures in one split; stopping rather "
                f"than spending more against unstable infrastructure"
            )
        if (
            expected_model_id is not None
            and previous.model_id is not None
            and previous.model_id != expected_model_id
        ):
            stopped = (
                f"{case.id} was answered by {previous.model_id!r}, not the benchmarked "
                f"{expected_model_id!r}"
            )
        if policy.stop_on_safety_violation and _broke_safety(previous):
            stopped = f"{case.id} broke a hard safety gate: {previous.reason}"

    return RunOutcome(
        results=tuple(results),
        worker_scores=tuple(worker_scores),
        customer_scores=tuple(customer_scores),
        guard=guard,
        provider=provider_name,
        model_id=_single_model_id(results, expected_model_id),
        provider_failures=failures,
        stopped=stopped,
        reused=reused,
    )


def _collect(
    score: worker_metrics.WorkerScore | customer_metrics.CustomerScore,
    worker_scores: list[worker_metrics.WorkerScore],
    customer_scores: list[customer_metrics.CustomerScore],
) -> None:
    if isinstance(score, worker_metrics.WorkerScore):
        worker_scores.append(score)
    else:
        customer_scores.append(score)


def _broke_safety(result: CaseResult) -> bool:
    """Whether this case's own metrics record a zero-tolerance failure."""
    return result.reason.startswith("safety:")


def _single_model_id(results: Sequence[CaseResult], expected: str | None) -> str | None:
    """The one model that answered, or ``None`` when nothing reported one.

    Reported from what came back rather than from what was asked for, because "which model
    produced these numbers" is a fact about the answers.
    """
    seen = {result.model_id for result in results if result.model_id is not None}
    if not seen:
        return None
    if len(seen) == 1:
        return seen.pop()
    return expected  # pragma: no cover - a mixed run is stopped at the case that mixed it


async def _ask(model_input: ModelInput, factory: ProviderFactory, guard: BudgetGuard) -> Answer:
    """Put one question to a provider, through the budget guard and nothing else.

    The guard wraps here rather than at the call site: a factory returns something that can
    answer, and the only way this package knows how to ask it is through the wrapper that
    counts. ``provider_calls`` is read from the guard for the same reason -- it is the number
    the accounting actually used, not a second count kept beside it -- and it is what proves,
    for a case the boundary forbids, that nothing was asked.
    """
    budgeted = BudgetedSemanticProvider(factory(model_input), guard)
    before = guard.spend.calls
    started = time.perf_counter()
    try:
        result = await budgeted.run(model_input.request)
    except SemanticValidationError as error:
        refusal = Refusal(category=error.category.value)
    except SemanticProviderError as error:
        refusal = Refusal(category=type(error).__name__, provider_error=True)
    except SemanticError as error:  # pragma: no cover - the two subclasses cover the surface
        refusal = Refusal(category=type(error).__name__)
    else:
        return Answer(
            result=result,
            refusal=None,
            provider_calls=guard.spend.calls - before,
            e2e_latency_ms=_elapsed_ms(started),
        )
    return Answer(
        result=None,
        refusal=CaseObservation(refusal),
        provider_calls=guard.spend.calls - before,
        e2e_latency_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


async def _run_worker(
    case: WorkerCase, factory: ProviderFactory, guard: BudgetGuard, *, mode: str
) -> tuple[CaseResult, worker_metrics.WorkerScore]:
    if not case.asked:
        score = worker_metrics.score_unasked(case, provider_calls=0)
        return _worker_result(case, score, None, None, guard, mode=mode), score

    model_input = to_model_input(case)
    request = model_input.request
    if not isinstance(request, InterpretUtteranceRequest):  # pragma: no cover - job is fixed
        raise TypeError(f"{case.id}: a worker case built a non-worker request")

    answer = await _ask(model_input, factory, guard)
    if answer.result is None:
        refusal = answer.refusal
        if refusal is None:  # pragma: no cover - one of the two is always present
            raise AssertionError(f"{case.id}: neither a result nor a refusal")
        score = worker_metrics.score_worker(case, refusal.observed, request=request)
        return _worker_result(case, score, refusal, None, guard, mode=mode, answer=answer), score

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
    return _worker_result(case, score, carried, observed, guard, mode=mode, answer=answer), score


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
    case: CustomerCase, factory: ProviderFactory, guard: BudgetGuard, *, mode: str
) -> tuple[CaseResult, customer_metrics.CustomerScore]:
    model_input = to_model_input(case)
    answer = await _ask(model_input, factory, guard)
    if answer.result is None:
        refusal = answer.refusal
        if refusal is None:  # pragma: no cover - one of the two is always present
            raise AssertionError(f"{case.id}: neither a result nor a refusal")
        score = customer_metrics.score_customer(case, refusal.observed)
        return _customer_result(case, score, refusal, guard, mode=mode, answer=answer), score

    value = answer.result.value
    if not isinstance(value, ReplyIntentReading):  # pragma: no cover - job is fixed
        raise TypeError(f"{case.id}: the customer job returned {type(value).__name__}")
    observed = CustomerObservation(reading=value)
    score = customer_metrics.score_customer(case, observed)
    carried = CaseObservation(observed, answer.result.telemetry)
    return _customer_result(case, score, carried, guard, mode=mode, answer=answer), score


# ------------------------------------------------------------------- reading a run back


def _rescore(
    case: GoldCase, result: CaseResult
) -> worker_metrics.WorkerScore | customer_metrics.CustomerScore:
    """Rebuild one case's score from the result an earlier attempt wrote down.

    The flat metric mapping a result carries is the score, field for field, which is what
    makes a resumed run identical to an uninterrupted one rather than approximately it. No
    provider is asked and no scoring rule is re-decided: the properties were checked when the
    answer arrived, and reading them back is not a second opinion.

    **A property the stored run predates is recomputed from its stored evidence, not guessed.**
    ``out_of_scope_declined`` reads the deterministic outcome, the grounding failure and the
    accepted identities that every result already records, so a run written before the property
    existed can be scored on it exactly, from answers already paid for. A result that does
    carry the value is trusted as written; only an absent one is reconstructed, and a result
    carrying neither the value nor the evidence would fail closed rather than pass.
    """
    metrics = result.metrics
    if isinstance(case, WorkerCase):
        return worker_metrics.WorkerScore(
            case_id=case.id,
            split=case.split.value,
            tags=case.tags,
            asked=bool(metrics["asked"]),
            answered=bool(metrics["answered"]),
            structured_output_valid=bool(metrics["structured_output_valid"]),
            category_correct=bool(metrics["category_correct"]),
            candidate_correct=bool(metrics["candidate_correct"]),
            grounding_correct=bool(metrics["grounding_correct"]),
            outcome_correct=bool(metrics["outcome_correct"]),
            clarification_correct=bool(metrics["clarification_correct"]),
            escalation_correct=bool(metrics["escalation_correct"]),
            out_of_scope_correct=bool(metrics["out_of_scope_correct"]),
            invented_candidate_accepted=bool(metrics["invented_candidate_accepted"]),
            invalid_candidate_escape=bool(metrics["invalid_candidate_escape"]),
            malformed_output_accepted=bool(metrics["malformed_output_accepted"]),
            physical_authority_created=bool(metrics["physical_authority_created"]),
            asked_when_forbidden=bool(metrics["asked_when_forbidden"]),
            rescuable=bool(metrics["rescuable"]),
            rescued=bool(metrics["rescued"]),
            unsafe_rescue=bool(metrics["unsafe_rescue"]),
            refusal_category=_as_optional_str(metrics.get("refusal_category")),
            out_of_scope_case=case.expected is not None and case.expected.out_of_scope,
            out_of_scope_declined=_declined(result),
        )
    predicted = _as_optional_str(metrics.get("predicted"))
    return customer_metrics.CustomerScore(
        case_id=case.id,
        split=case.split.value,
        tags=case.tags,
        expected=case.expected,
        predicted=None if predicted is None else ApparentIntent(predicted),
        answered=bool(metrics["answered"]),
        correct=bool(metrics["correct"]),
        authority_violation=bool(metrics["authority_violation"]),
        refusal_category=_as_optional_str(metrics.get("refusal_category")),
    )


def _declined(result: CaseResult) -> bool:
    """Whether the stored run's own evidence says the system refused this sentence."""
    stored = result.metrics.get("out_of_scope_declined")
    if isinstance(stored, bool):
        return stored
    return worker_metrics.declined_from_payload(result.observed, result.metrics)


def _as_optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


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


def _provider_name(mode: str, observation: CaseObservation | None) -> str:
    """Who answered this case. In replay that is the fake; live it is whatever telemetry says.

    Read from the answer rather than passed down, so a result cannot claim a provider that did
    not produce it.
    """
    telemetry = observation.telemetry if observation is not None else None
    if telemetry is not None:
        return telemetry.provider
    return FakeSemanticProvider.name if mode == REPLAY_MODE else mode


def _case_cost(guard: BudgetGuard, operational: Operational) -> str | None:
    """What this one case cost, or ``None`` when that cannot be said.

    Priced per case from the same catalog entry the run's total uses, so the per-case column a
    later comparison joins on is the same money as the headline figure.
    """
    estimate = estimate_usd(
        guard.price,
        input_tokens=operational.input_tokens,
        output_tokens=operational.output_tokens,
    )
    return None if estimate is None else str(estimate)


def _worker_result(
    case: WorkerCase,
    score: worker_metrics.WorkerScore,
    observation: CaseObservation | None,
    observed: WorkerObservation | None,
    guard: BudgetGuard,
    *,
    mode: str,
    answer: Answer | None = None,
) -> CaseResult:
    metrics = score.as_mapping()
    verdict = worker_metrics.worker_verdict(metrics)
    operational = _operational(observation)
    carried = observation.observed if observation is not None else None
    refusal = carried if isinstance(carried, Refusal) else None
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
        provider=_provider_name(mode, observation),
        error_category=refusal.category if refusal is not None else None,
        provider_error=refusal.provider_error if refusal is not None else False,
        model_id=operational.model_id,
        attempts=operational.attempts,
        latency_ms=operational.latency_ms,
        e2e_latency_ms=None if answer is None else answer.e2e_latency_ms,
        input_tokens=operational.input_tokens,
        output_tokens=operational.output_tokens,
        estimated_usd=_case_cost(guard, operational),
    )


def _customer_result(
    case: CustomerCase,
    score: customer_metrics.CustomerScore,
    observation: CaseObservation,
    guard: BudgetGuard,
    *,
    mode: str,
    answer: Answer | None = None,
) -> CaseResult:
    metrics = score.as_mapping()
    verdict = customer_metrics.customer_verdict(metrics)
    operational = _operational(observation)
    carried = observation.observed
    refusal = carried if isinstance(carried, Refusal) else None
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
        provider=_provider_name(mode, observation),
        error_category=refusal.category if refusal is not None else None,
        provider_error=refusal.provider_error if refusal is not None else False,
        model_id=operational.model_id,
        attempts=operational.attempts,
        latency_ms=operational.latency_ms,
        e2e_latency_ms=None if answer is None else answer.e2e_latency_ms,
        input_tokens=operational.input_tokens,
        output_tokens=operational.output_tokens,
        estimated_usd=_case_cost(guard, operational),
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
    "LIVE_MODE",
    "REPLAY_MODE",
    "SCRIPT_FILE",
    "Answer",
    "Operational",
    "ProviderFactory",
    "RunOutcome",
    "ScriptedAnswers",
    "StopPolicy",
    "case_of",
    "new_run_id",
    "run_cases",
    "run_offline",
    "scripted_provider",
]
