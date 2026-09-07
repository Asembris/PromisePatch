"""DeepEval as a runner, and only as a runner.

DeepEval executes cases and reports; it decides nothing. Every metric here is a thin shell
around :func:`evals.metrics.worker.worker_verdict` or
:func:`evals.metrics.customer.customer_verdict`, which are ordinary functions over the expected
and observed mappings a case result already carries. Delete this module and every number in the
report is still reachable; delete the metric functions and there is nothing left to run.

That ordering is deliberate. A metric whose logic lives inside a framework callback can only be
checked by running the framework, and a score nobody can reproduce by hand is not evidence. It
also keeps the dependency where it belongs: this is the only module in the package that imports
DeepEval, so the dataset, the metrics, the runner and the report all work without it installed.

**No model judges anything.** There is no ``GEval``, no LLM-backed metric and no judge of any
kind. Both jobs here have objectively knowable answers -- a category, an identity, a label from
a closed set -- and asking a model to grade another model on those would replace a verifiable
comparison with an opinion.

**Nothing leaves the machine.** DeepEval is used through its local API with telemetry opted out
in the eval suite's environment; no Confident AI account, key or upload is involved, and none is
required.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from evals.cases import EvalJob
from evals.metrics.customer import customer_verdict
from evals.metrics.verdict import Verdict
from evals.metrics.worker import worker_verdict
from evals.results import CaseResult

METRIC_KEY = "promisepatch_metrics"
JOB_KEY = "promisepatch_job"


def to_test_case(result: CaseResult) -> LLMTestCase:
    """One PromisePatch case result, in the shape DeepEval iterates over.

    ``input`` is what was actually put to the provider for this case -- the worker's sentence
    or the customer's reply. ``expected_output`` and ``actual_output`` are the gold and observed
    readings rendered for a human reading the runner's table; the metric does not parse them,
    it reads the structured mapping in ``metadata``.
    """
    return LLMTestCase(
        name=result.case_id,
        input=_input_of(result),
        actual_output=_render(result.observed),
        expected_output=_render(result.expected),
        tags=list(result.tags),
        metadata={
            METRIC_KEY: dict(result.metrics),
            JOB_KEY: result.job.value,
            "split": result.split.value,
        },
    )


def _input_of(result: CaseResult) -> str:
    """What the case is about, for the runner's own display. Never the gold answer."""
    return result.case_id


def _render(payload: Mapping[str, object]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(payload.items())) or "(none)"


class PromisePatchMetric(BaseMetric):
    """The base of both metrics: read the mapping, call PromisePatch, report what it said."""

    def __init__(self, job: EvalJob, threshold: float = 1.0) -> None:
        self.job = job
        self.threshold = threshold
        self.async_mode = False
        self.include_reason = True
        self.strict_mode = True

    @property
    def __name__(self) -> str:
        return f"PromisePatch {self.job.value}"

    def _verdict(self, metrics: Mapping[str, object]) -> Verdict:
        raise NotImplementedError

    def measure(self, test_case: LLMTestCase, *args: object, **kwargs: object) -> float:
        metadata = test_case.metadata or {}
        if metadata.get(JOB_KEY) != self.job.value:
            self.skipped = True
            self.score = 0.0
            self.success = True
            self.reason = f"not a {self.job.value} case"
            return self.score
        metrics = metadata.get(METRIC_KEY)
        if not isinstance(metrics, Mapping):  # pragma: no cover - the adapter always sets it
            raise ValueError(f"{test_case.name}: no PromisePatch metrics on the test case")
        verdict = self._verdict(metrics)
        self.score = verdict.score
        self.success = verdict.passed
        self.reason = verdict.reason
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: object, **kwargs: object) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return bool(self.success)


class WorkerSemanticsMetric(PromisePatchMetric):
    """Whether one worker reading was right, and broke no rule that must never break."""

    def __init__(self, threshold: float = 1.0) -> None:
        super().__init__(EvalJob.WORKER_SEMANTICS, threshold)

    def _verdict(self, metrics: Mapping[str, object]) -> Verdict:
        return worker_verdict(metrics)


class CustomerIntentMetric(PromisePatchMetric):
    """Whether one customer reply was read as the label the dataset says it means."""

    def __init__(self, threshold: float = 1.0) -> None:
        super().__init__(EvalJob.CUSTOMER_INTENT, threshold)

    def _verdict(self, metrics: Mapping[str, object]) -> Verdict:
        return customer_verdict(metrics)


def metric_for(job: EvalJob) -> PromisePatchMetric:
    """The metric that judges this job."""
    if job is EvalJob.WORKER_SEMANTICS:
        return WorkerSemanticsMetric()
    return CustomerIntentMetric()


def to_test_cases(results: Sequence[CaseResult]) -> list[LLMTestCase]:
    return [to_test_case(result) for result in results]


__all__ = [
    "JOB_KEY",
    "METRIC_KEY",
    "CustomerIntentMetric",
    "PromisePatchMetric",
    "WorkerSemanticsMetric",
    "metric_for",
    "to_test_case",
    "to_test_cases",
]
