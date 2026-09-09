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

**No model is judged from inside this module, and no model is called from it.** There is no
``GEval``, no ``FaithfulnessMetric``, no ``AnswerRelevancyMetric`` and no LLM-backed metric of any
kind. The two semantic jobs have objectively knowable answers -- a category, an identity, a label
from a closed set -- and asking a model to grade another model on those would replace a
verifiable comparison with an opinion.

Explanation quality *is* subjective and is judged by a model, and that judgement still does not
happen here. PromisePatch owns one combined judge protocol in :mod:`evals.explanation_judge`:
**one structured call per accepted passage**, producing every safety flag and all five scores at
once. This module receives the verdict that call already produced and reports it.

That ordering is a cost boundary as much as a design one. Five LLM-backed metrics over one
result is five provider calls where PromisePatch spends one, and a framework default judge is a
model nobody chose being billed to somebody who did not know it had been selected. So the rule
is structural: **no metric in this module may hold, construct or reach a model**, and the
explanation metric is a shell over a verdict that already exists.

**Nothing leaves the machine.** DeepEval is used through its local API with telemetry opted out
in the eval suite's environment; no Confident AI account, key or upload is involved, and none is
required.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from evals.cases import EvalJob
from evals.explanation_metrics import CaseScore
from evals.metrics.customer import customer_verdict
from evals.metrics.verdict import Verdict
from evals.metrics.worker import worker_verdict
from evals.results import CaseResult

METRIC_KEY = "promisepatch_metrics"
JOB_KEY = "promisepatch_job"
EXPLANATION_KEY = "promisepatch_explanation"


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


class ExplanationQualityMetric(BaseMetric):
    """Reports one explanation's already-computed verdict. Holds no model and calls nothing.

    Its ``measure`` is arithmetic over a :class:`~evals.explanation_metrics.CaseScore` that was
    produced before DeepEval was involved: the structural findings come from production's own
    validator and the subjective ones from the single judge call PromisePatch already made. Run
    it over twenty-one results and exactly zero provider calls happen, which is the property the
    fan-out regression test asserts.

    A hard finding fails the case outright, whatever the scores say. That is the same rule the
    report follows and it is enforced here too, so a framework summary can never disagree with
    the gate about whether a passage was safe.
    """

    def __init__(self, threshold: float = 0.8) -> None:
        self.threshold = threshold
        self.async_mode = False
        self.include_reason = True
        self.strict_mode = True

    @property
    def __name__(self) -> str:
        return "PromisePatch explanation quality"

    def measure(self, test_case: LLMTestCase, *args: object, **kwargs: object) -> float:
        metadata = test_case.metadata or {}
        payload = metadata.get(EXPLANATION_KEY)
        if not isinstance(payload, Mapping):
            self.skipped = True
            self.score = 0.0
            self.success = True
            self.reason = "not an explanation case"
            return self.score
        self.score, self.success, self.reason = _explanation_verdict(payload)
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args: object, **kwargs: object) -> float:
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self) -> bool:
        return bool(self.success)


def _strings(value: object) -> list[str]:
    """Whatever a stored payload put there, read as the list of names it is meant to be."""
    return [str(item) for item in value] if isinstance(value, list | tuple) else []


def _explanation_verdict(payload: Mapping[str, object]) -> tuple[float, bool, str]:
    """Score, pass and reason for one explanation, from values that already exist.

    Structural findings and semantic flags are absolute. Only when there are none does the mean
    of the five dimensions decide anything, and a case with no verdict is reported as unscored
    rather than as a zero -- because a judge nobody reached said nothing about this passage.
    """
    structural = _strings(payload.get("structural_failures"))
    flags = _strings(payload.get("semantic_flags"))
    if structural:
        return 0.0, False, f"the acceptance gate leaked: {', '.join(structural)}"
    if flags:
        return 0.0, False, f"hard semantic finding: {', '.join(flags)}"
    scores = payload.get("scores")
    if not isinstance(scores, Mapping) or not scores:
        source = payload.get("source")
        if source == "FALLBACK":
            return 0.0, True, "PromisePatch phrased this one; there is no model prose to score"
        return 0.0, True, "no verdict: subjective quality was not scored for this passage"
    mean = sum(float(value) for value in scores.values()) / len(scores)
    return mean / 5.0, True, f"mean of five judged dimensions: {mean:.2f}"


def to_explanation_test_case(score: CaseScore) -> LLMTestCase:
    """One explanation case result in the shape DeepEval iterates over.

    ``input`` is the case id and nothing else. The passage, the facts and the verdict travel in
    metadata, where the metric reads them structurally instead of parsing prose -- and where no
    reference explanation, threshold or split can reach a provider, because nothing in this
    module reaches one.
    """
    return LLMTestCase(
        name=score.case_id,
        input=score.case_id,
        actual_output=score.source.value,
        expected_output=score.family.value,
        metadata={EXPLANATION_KEY: score.as_payload()},
    )


def to_explanation_test_cases(scores: Sequence[CaseScore]) -> list[LLMTestCase]:
    return [to_explanation_test_case(score) for score in scores]


def metric_for(job: EvalJob) -> PromisePatchMetric:
    """The metric that judges this job."""
    if job is EvalJob.WORKER_SEMANTICS:
        return WorkerSemanticsMetric()
    return CustomerIntentMetric()


def to_test_cases(results: Sequence[CaseResult]) -> list[LLMTestCase]:
    return [to_test_case(result) for result in results]


__all__ = [
    "EXPLANATION_KEY",
    "JOB_KEY",
    "METRIC_KEY",
    "CustomerIntentMetric",
    "ExplanationQualityMetric",
    "PromisePatchMetric",
    "WorkerSemanticsMetric",
    "metric_for",
    "to_explanation_test_case",
    "to_explanation_test_cases",
    "to_test_case",
    "to_test_cases",
]
