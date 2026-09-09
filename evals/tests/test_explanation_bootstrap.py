"""A provider that could not be built is not an answer, and must not cost a run.

The failure this file is about happened once, for real. ``p48dev-repaired``'s canary reached no
Bedrock client -- the AWS login credential provider needed a dependency that was not installed
-- and the harness recorded the result as a terminal ``PROVIDER_FAILURE``, marked the case
answered, and charged the identity with the second and last DEVELOPMENT run. Nothing had been
sent and nothing had been billed, so the gate had spent its allowance on an observation it never
made, and a resume would have skipped the one case the repair existed to re-measure.

The distinction under test is *when* the failure happened rather than how bad it was:

* **before the request left the process** -- no profile, no Region, no credential dependency.
  Nothing was asked, so nothing was learned. Non-terminal, unbilled, still outstanding.
* **after the request path began** -- a throttle, a timeout, a refusal. Something was asked and
  the answer was that there is no answer. Terminal, counted, and production falls back exactly
  as it always has.

Every provider here is a fake that raises. Nothing reaches a network, holds a credential or
imports an SDK.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from evals.authorisation import SpendScope
from evals.budget import NOVA_2_LITE, BudgetGuard, EvalBudget, LedgerTotals
from evals.cases import EvalSplit
from evals.explanation_cases import ExplanationModelInput
from evals.explanation_dataset import DATASET_NAME, ExplanationDataset, load_explanation_dataset
from evals.explanation_results import (
    ExplanationFailureKind,
    ExplanationSource,
    NovaExplanationResult,
)
from evals.explanation_runner import (
    LIVE_MODE,
    ScriptedExplanations,
    generate,
    scripted_provider,
)
from evals.explanation_store import ExplanationResultStore, ExplanationRunHeader, read_run
from evals.prompts import prompt_identity
from scripts.run_explanation_eval import GENERATION_SCOPES, RecognisedRun, _recorded_totals

from promisepatch.semantic import (
    SemanticJob,
    SemanticProvider,
    SemanticProviderError,
    SemanticProviderNotPreparedError,
    SemanticRequest,
    SemanticResult,
)

RUN_ID = "p48devrepaired"
"""One identity throughout. A resume that needed a second one would be the bug."""

NOT_PREPARED = (
    "the AWS SDK could not be prepared for Bedrock: Missing Dependency: Using the login "
    "credential provider requires an additional dependency."
)
"""The sentence the real canary failed with, in the shape production emits it."""


class NeverPrepared:
    """A provider that cannot be built. Raises before anything is sent, every time."""

    name = "bedrock"
    model_id: str | None = None

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, request: SemanticRequest) -> SemanticResult:
        self.calls += 1
        raise SemanticProviderNotPreparedError(NOT_PREPARED)


class Throttled:
    """A provider that was reached and refused. The request path began."""

    name = "bedrock"
    model_id: str | None = None

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, request: SemanticRequest) -> SemanticResult:
        self.calls += 1
        raise SemanticProviderError("Bedrock refused the call: ThrottlingException", retryable=True)


@pytest.fixture(scope="module")
def development() -> ExplanationDataset:
    return load_explanation_dataset().split([EvalSplit.DEVELOPMENT])


@pytest.fixture(scope="module")
def one(development: ExplanationDataset) -> ExplanationDataset:
    """The canonical plan summary -- the case the real failure landed on."""
    return ExplanationDataset(
        version=development.version,
        provenance=development.provenance,
        cases=development.cases[:1],
    )


def header_for(dataset: ExplanationDataset) -> ExplanationRunHeader:
    prompt = prompt_identity(SemanticJob.VERBALISE)
    return ExplanationRunHeader(
        run_id=RUN_ID,
        started_at="2026-09-09T00:00:00+00:00",
        git_sha="0123456789abcdef",
        dataset_name=DATASET_NAME,
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        provider=NOVA_2_LITE.provider,
        model_id=NOVA_2_LITE.model_id,
        mode=LIVE_MODE,
        splits=(EvalSplit.DEVELOPMENT.value,),
        prompt_system_hash=prompt.system_hash,
        schema_hash=prompt.schema_hash,
    )


def factory_of(provider: SemanticProvider) -> Callable[[ExplanationModelInput], SemanticProvider]:
    def build(model_input: ExplanationModelInput) -> SemanticProvider:
        return provider

    return build


async def run_once(
    dataset: ExplanationDataset,
    factory: Callable[[ExplanationModelInput], SemanticProvider],
    store: ExplanationResultStore,
) -> BudgetGuard:
    """One generation pass over whatever is still outstanding, written to the store.

    The narrowing is the production one: the pass generates the split minus what the store
    already counts as answered.
    """
    guard = BudgetGuard(EvalBudget(), price=None, live=False)

    def written(result: NovaExplanationResult) -> None:
        store.record_generation(result)

    outstanding = ExplanationDataset(
        version=dataset.version,
        provenance=dataset.provenance,
        cases=tuple(case for case in dataset.cases if case.id not in store.completed()),
    )
    await generate(
        outstanding,
        factory,
        guard=guard,
        provider_name=NOVA_2_LITE.provider,
        model_id=NOVA_2_LITE.model_id,
        git_sha="0123456789abcdef",
        run_id=RUN_ID,
        mode=LIVE_MODE,
        on_result=written,
    )
    return guard


def scripted() -> Callable[[ExplanationModelInput], SemanticProvider]:
    return scripted_provider(ScriptedExplanations.from_file())


# ----------------------------------------------- 1. a failed setup does not answer the case


async def test_a_provider_that_could_not_be_built_leaves_the_case_outstanding(
    one: ExplanationDataset, tmp_path: Path
) -> None:
    """The defect, inverted. Nothing was asked, so the question is still open."""
    store = ExplanationResultStore(tmp_path / "run.jsonl", header_for(one))
    await run_once(one, factory_of(NeverPrepared()), store)

    [recorded] = store.generations
    assert recorded.failure is ExplanationFailureKind.PROVIDER_NOT_PREPARED
    assert recorded.terminal is False
    assert store.completed() == frozenset()
    assert store.not_prepared() == frozenset({one.cases[0].id})
    # Production still explained the outcome: the passage is PromisePatch's own sentence.
    assert recorded.source is ExplanationSource.FALLBACK
    assert recorded.speech


async def test_the_attempt_is_kept_as_evidence_and_never_rewritten(
    one: ExplanationDataset, tmp_path: Path
) -> None:
    """Append-only. The record of a broken environment is worth reading afterwards."""
    path = tmp_path / "run.jsonl"
    store = ExplanationResultStore(path, header_for(one))
    await run_once(one, factory_of(NeverPrepared()), store)
    await run_once(one, scripted(), ExplanationResultStore(path, header_for(one)))

    _, generations, _ = read_run(path)
    assert len(generations) == 2, "the failed attempt must still be on disk beside the answer"
    assert generations[0].failure is ExplanationFailureKind.PROVIDER_NOT_PREPARED
    assert generations[0].detail == NOT_PREPARED
    assert generations[1].terminal is True


async def test_a_record_written_before_the_kind_existed_is_still_read_as_unsent(
    one: ExplanationDataset, tmp_path: Path
) -> None:
    """Compatibility for the one real record, which says ``PROVIDER_FAILURE`` on disk.

    It is not rewritten. Production's own sentence for a client that could not be built is what
    identifies it, and ``terminal`` is where that is decided for every reader.
    """
    store = ExplanationResultStore(tmp_path / "run.jsonl", header_for(one))
    await run_once(one, factory_of(NeverPrepared()), store)
    [recorded] = store.generations

    historical = recorded.model_copy(update={"failure": ExplanationFailureKind.PROVIDER_FAILURE})
    assert historical.failure is ExplanationFailureKind.PROVIDER_FAILURE
    assert historical.terminal is False


# ------------------------------------------------- 2. the resume finishes the same identity


async def test_a_resume_retries_the_case_under_the_same_run_identity(
    one: ExplanationDataset, tmp_path: Path
) -> None:
    """The property that makes a third run identity unnecessary."""
    path = tmp_path / "run.jsonl"
    store = ExplanationResultStore(path, header_for(one))
    await run_once(one, factory_of(NeverPrepared()), store)

    resumed = ExplanationResultStore(path, header_for(one))
    assert resumed.header.run_id == RUN_ID
    await run_once(one, scripted(), resumed)

    assert resumed.completed() == frozenset({one.cases[0].id})
    assert len([result for result in resumed.generations if result.terminal]) == 1
    assert {result.identity.run_id for result in resumed.generations} == {RUN_ID}


# --------------------------------------------------- 3. it does not consume the second run


async def test_a_run_that_sent_nothing_is_not_a_run_that_was_bought(
    one: ExplanationDataset, tmp_path: Path
) -> None:
    """The allowance question. An identity that bought nothing has bought nothing."""
    store = ExplanationResultStore(tmp_path / "run.jsonl", header_for(one))
    guard = await run_once(one, factory_of(NeverPrepared()), store)

    assert guard.spend.calls == 0, "the permission was handed back"
    assert guard.spend.unsent_calls == 1, "and the event is still counted"

    totals = _recorded_totals(store.generations, model_id=NOVA_2_LITE.model_id)
    assert totals.calls == 0
    assert totals.attempts == 0
    assert totals.runs == 0
    assert totals.unsent_calls == 1
    assert totals.input_tokens == 0
    assert totals.output_tokens == 0

    run = RecognisedRun(run_id=RUN_ID, ledgered=LedgerTotals(), recorded=totals, splits=())
    assert run.bought is False


async def test_a_ledger_line_written_before_the_distinction_existed_is_discounted(
    one: ExplanationDataset, tmp_path: Path
) -> None:
    """The real ``p48dev-repaired`` line says one call. The run file says it was never sent.

    Neither record is edited. The run file is the per-case evidence of what left the process,
    so recognition discounts what it proves was unsent and prints the disagreement.
    """
    store = ExplanationResultStore(tmp_path / "run.jsonl", header_for(one))
    await run_once(one, factory_of(NeverPrepared()), store)
    totals = _recorded_totals(store.generations, model_id=NOVA_2_LITE.model_id)

    stale = LedgerTotals(runs=1, calls=1, attempts=1)
    run = RecognisedRun(run_id=RUN_ID, ledgered=stale, recorded=totals, splits=())

    assert run.recognised.calls == 0
    assert run.recognised.attempts == 0
    assert run.bought is False
    assert run.discrepancy is not None
    assert "reached no provider" in run.discrepancy
    assert "neither removed nor rewritten" in run.discrepancy


# ----------------------------------------------------- 4. the resumed answer is kept once


async def test_a_resumed_answer_is_persisted_exactly_once(
    one: ExplanationDataset, tmp_path: Path
) -> None:
    """One answer per case, however many times the environment failed first."""
    path = tmp_path / "run.jsonl"
    store = ExplanationResultStore(path, header_for(one))
    await run_once(one, factory_of(NeverPrepared()), store)
    await run_once(one, factory_of(NeverPrepared()), ExplanationResultStore(path, header_for(one)))
    await run_once(one, scripted(), ExplanationResultStore(path, header_for(one)))

    _, generations, _ = read_run(path)
    answered = [result for result in generations if result.terminal]
    assert len(answered) == 1
    assert [result.case_id for result in answered] == [one.cases[0].id]

    # A further pass buys nothing at all: the case is answered now.
    final = ExplanationResultStore(path, header_for(one))
    guard = await run_once(one, factory_of(NeverPrepared()), final)
    assert guard.spend.calls == 0
    assert guard.spend.unsent_calls == 0, "nothing was even attempted"
    assert len([result for result in final.generations if result.terminal]) == 1


# ----------------------------------------------- 5. a real provider failure is unchanged


async def test_a_failure_after_the_request_began_stays_terminal_and_counted(
    one: ExplanationDataset, tmp_path: Path
) -> None:
    """The regression guard. A throttle is an observation, and it still ends the case."""
    store = ExplanationResultStore(tmp_path / "run.jsonl", header_for(one))
    guard = await run_once(one, factory_of(Throttled()), store)

    [recorded] = store.generations
    assert recorded.failure is ExplanationFailureKind.PROVIDER_FAILURE
    assert recorded.terminal is True
    assert recorded.source is ExplanationSource.FALLBACK, "production fell back, as always"
    assert store.completed() == frozenset({one.cases[0].id})
    assert guard.spend.calls == 1, "a request that was sent is a call"
    assert guard.spend.unsent_calls == 0

    totals = _recorded_totals(store.generations, model_id=NOVA_2_LITE.model_id)
    assert totals.calls == 1
    assert totals.runs == 1
    bought = RecognisedRun(run_id=RUN_ID, ledgered=LedgerTotals(), recorded=totals, splits=())
    assert bought.bought is True


# ------------------------------------------------------------ 6. nothing is charged twice


async def test_a_bootstrap_failure_then_an_answer_is_charged_once(
    one: ExplanationDataset, tmp_path: Path
) -> None:
    """Two passes, one call. The unsent one is beside the total and never inside it."""
    path = tmp_path / "run.jsonl"
    store = ExplanationResultStore(path, header_for(one))
    first = await run_once(one, factory_of(NeverPrepared()), store)
    second = await run_once(one, scripted(), ExplanationResultStore(path, header_for(one)))

    assert first.spend.calls == 0
    assert second.spend.calls == 1

    _, generations, _ = read_run(path)
    totals = _recorded_totals(generations, model_id=NOVA_2_LITE.model_id)
    assert totals.calls == 1, "the answer, and only the answer"
    assert totals.unsent_calls == 1, "the attempt, reported and not charged"
    assert totals.runs == 1


# ------------------------------------------------------------- 7. the holdout stays sealed


async def test_no_bootstrap_failure_makes_the_holdout_reachable(
    one: ExplanationDataset, tmp_path: Path
) -> None:
    """A broken environment is not a key. Development stays development."""
    path = tmp_path / "run.jsonl"
    store = ExplanationResultStore(path, header_for(one))
    await run_once(one, factory_of(NeverPrepared()), store)
    await run_once(one, scripted(), ExplanationResultStore(path, header_for(one)))

    _, generations, _ = read_run(path)
    assert generations, "the run recorded something to check"
    assert all(result.split is EvalSplit.DEVELOPMENT for result in generations)
    # And the split still maps to its own scope, which the development phrase does not carry.
    assert GENERATION_SCOPES[EvalSplit.HOLDOUT] is SpendScope.P4_8_EXPLANATION_HOLDOUT
    assert GENERATION_SCOPES[EvalSplit.DEVELOPMENT] is not SpendScope.P4_8_EXPLANATION_HOLDOUT
