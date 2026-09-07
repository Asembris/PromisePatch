"""DeepEval running PromisePatch's own metrics, offline, deciding nothing.

What is proved here is the shape of the integration rather than the correctness of any score:
that a gold case becomes a DeepEval test case carrying no gold answer, that DeepEval's metric
protocol reaches PromisePatch's verdict functions, that a right answer passes and a wrong one
fails through that path, and that the framework needs no account, no key and no network to do
any of it.

Everything the metrics decide is decided in :mod:`evals.metrics`, which
:mod:`evals.tests.test_metrics` exercises directly. If this file were deleted, every number in
the report would still be reachable and still be tested.
"""

from __future__ import annotations

import os

import pytest
from evals.cases import EvalJob
from evals.dataset import GoldDataset, load_dataset
from evals.metrics.deepeval_adapter import (
    JOB_KEY,
    METRIC_KEY,
    CustomerIntentMetric,
    WorkerSemanticsMetric,
    metric_for,
    to_test_case,
    to_test_cases,
)
from evals.results import CaseResult
from evals.runner import ScriptedAnswers, run_offline

from promisepatch.semantic import ApparentIntent


@pytest.fixture(scope="module", autouse=True)
def offline_deepeval() -> None:
    """DeepEval phones home unless told not to. This suite tells it not to.

    Set here as well as in the CI job so that a developer running the suite by hand gets the
    same behaviour as the pipeline: no telemetry, no error reporting, nothing leaving the
    machine. PromisePatch evaluation data is not uploaded anywhere.
    """
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    os.environ.setdefault("ERROR_REPORTING", "NO")


@pytest.fixture(scope="module")
def dataset() -> GoldDataset:
    return load_dataset()


@pytest.fixture
async def results(dataset: GoldDataset) -> tuple[CaseResult, ...]:
    answers = ScriptedAnswers.from_file()
    outcome = await run_offline(dataset, answers)
    return outcome.results


async def test_a_case_result_becomes_a_deepeval_case_carrying_no_gold_answer(
    results: tuple[CaseResult, ...],
) -> None:
    """The framework sees an identifier and a verdict payload, never the label to reach for."""
    result = next(item for item in results if item.job is EvalJob.CUSTOMER_INTENT)
    test_case = to_test_case(result)

    assert test_case.name == result.case_id
    assert test_case.input == result.case_id
    assert test_case.metadata is not None
    assert test_case.metadata[JOB_KEY] == result.job.value
    assert METRIC_KEY in test_case.metadata


async def test_deepeval_reaches_promisepatch_and_agrees_with_it(
    results: tuple[CaseResult, ...],
) -> None:
    """The integration proof: the framework's protocol, PromisePatch's decision."""
    for result in results:
        metric = metric_for(result.job)
        score = metric.measure(to_test_case(result))
        assert metric.is_successful() is result.passed
        assert score == (1.0 if result.passed else 0.0)
        assert metric.reason == result.reason


async def test_a_wrong_reading_fails_through_the_same_path(dataset: GoldDataset) -> None:
    """The failing half. One reply, deliberately misread, judged by DeepEval's metric."""
    terse = next(case for case in dataset.customer if case.id == "customer.approve.terse.001")
    narrowed = GoldDataset(
        version=dataset.version, worker=(), customer=(terse,), provenance=dataset.provenance
    )
    wrong = ScriptedAnswers({terse.id: [{"apparent_intent": ApparentIntent.UNCLEAR.value}]})
    outcome = await run_offline(narrowed, wrong)

    metric = CustomerIntentMetric()
    assert metric.measure(to_test_case(outcome.results[0])) == 0.0
    assert not metric.is_successful()
    assert metric.reason is not None
    assert "UNCLEAR" in metric.reason


async def test_a_metric_skips_a_case_belonging_to_the_other_job(
    results: tuple[CaseResult, ...],
) -> None:
    """Both metrics run over one list of cases, so each has to ignore the other's."""
    worker_result = next(item for item in results if item.job is EvalJob.WORKER_SEMANTICS)
    metric = CustomerIntentMetric()
    metric.measure(to_test_case(worker_result))
    assert metric.skipped
    assert metric.is_successful()


async def test_the_whole_run_can_be_handed_to_deepeval_as_test_cases(
    results: tuple[CaseResult, ...],
) -> None:
    cases = to_test_cases(results)
    assert len(cases) == len(results)
    assert len({case.name for case in cases}) == len(cases)


async def test_deepeval_needs_no_account_key_or_network(
    results: tuple[CaseResult, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local metrics only. With every Confident AI variable removed, the path still works."""
    for variable in ("CONFIDENT_API_KEY", "DEEPEVAL_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

    metric = WorkerSemanticsMetric()
    worker_result = next(item for item in results if item.job is EvalJob.WORKER_SEMANTICS)
    metric.measure(to_test_case(worker_result))
    assert metric.is_successful()
    assert metric.evaluation_model is None, "no model is used to judge anything here"


async def test_the_metrics_are_not_llm_backed(results: tuple[CaseResult, ...]) -> None:
    """There is no judge. Both jobs have objectively knowable answers, so none is needed."""
    for metric in (WorkerSemanticsMetric(), CustomerIntentMetric()):
        assert metric.model is None
        assert metric.using_native_model is None
        assert metric.evaluation_cost is None


async def test_deepeval_metrics_run_synchronously_and_deterministically(
    results: tuple[CaseResult, ...],
) -> None:
    """Twice over the same case, the same verdict. Nothing here is sampled."""
    result = results[0]
    metric = metric_for(result.job)
    first = metric.measure(to_test_case(result))
    second = metric.measure(to_test_case(result))
    assert first == second
    assert not metric.async_mode
