"""The shape a run leaves behind, designed for the run after it rather than for this one.

A benchmark result is only worth keeping if a later one can be compared with it honestly. That
needs four identities recorded together -- which dataset, which prompt, which commit, which
model -- and it needs the per-case detail, because an aggregate that moved tells you nothing
about which cases moved.

So a summary carries every case, and every case carries what it cost as well as whether it was
right. Two summaries over the same dataset can then be joined on ``case_id`` to get the paired
comparison a model-selection decision needs: same case, two readings, the quality difference,
the latency difference and the cost difference. That join is not implemented here and no
challenger is run in this slice; the schema is what makes it possible without a redesign.

**Nothing is invented.** In replay there is no model, no latency and no token count, so those
fields are ``null``. A zero would be a measurement, and there was no measurement.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import Field

from evals.cases import EvalJob, EvalSplit, Frozen


class CaseResult(Frozen):
    """One case, what was asked, what came back, and what it cost to find out."""

    case_id: str
    job: EvalJob
    split: EvalSplit
    tags: tuple[str, ...]

    expected: Mapping[str, object]
    observed: Mapping[str, object]
    metrics: Mapping[str, object]

    passed: bool
    reason: str

    provider: str
    model_id: str | None = None
    attempts: int | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_usd: str | None = None
    error_category: str | None = None


class DatasetIdentity(Frozen):
    """Which dataset this run measured, in enough detail to fetch exactly it again."""

    name: str
    schema_version: str
    version: str
    content_hash: str
    cases: int
    worker_cases: int
    customer_cases: int
    development_cases: int
    holdout_cases: int


class GateResult(Frozen):
    """One threshold, what it demanded, what it got, and whether that is acceptable."""

    name: str
    kind: str
    """``safety`` for a zero-tolerance rule, ``quality`` for a target."""

    status: str
    """``pass``, ``fail`` or ``not-measured`` when the run contained no case to measure it on."""

    required: str
    observed: str | None
    proposed: bool = False
    """Whether this threshold is still awaiting product-owner review before a live benchmark."""


class RunSummary(Frozen):
    """Everything one evaluation run knows about itself."""

    run_id: str
    generated_at: str
    mode: str
    """``replay`` when every answer came from a scripted payload, ``live`` when a model was
    called. Only ``replay`` is reachable from the commands that exist today."""

    git_sha: str | None
    dataset: DatasetIdentity
    prompts: tuple[Mapping[str, str], ...]
    provider: str
    model_id: str | None
    splits: tuple[EvalSplit, ...]

    cases: int
    passed: int
    failed: int

    worker: Mapping[str, object] | None
    customer: Mapping[str, object] | None
    safety: Mapping[str, object]
    operations: Mapping[str, object]
    cost: Mapping[str, object]
    gates: tuple[GateResult, ...]
    gate_status: str

    results: tuple[CaseResult, ...] = Field(default=())

    def as_payload(self) -> dict[str, object]:
        """The machine-readable form: plain JSON, no database, no framework types."""
        return self.model_dump(mode="json")


def counts_by(results: Sequence[CaseResult], job: EvalJob) -> int:
    return sum(result.job is job for result in results)


__all__ = ["CaseResult", "DatasetIdentity", "GateResult", "RunSummary", "counts_by"]
