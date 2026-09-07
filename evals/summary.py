"""Turning a run into the artifact that outlives it, and judging it against the thresholds.

Two jobs, kept in one place because they must agree: assembling everything a later run needs to
be compared with this one, and deciding whether this one passed.

The gate is evaluated from the summary rather than from the scores, so what a threshold reads
is the same number a reader sees. A threshold that named a metric the summary does not contain
would silently never fire; instead it reports ``not-measured``, which is a visible state rather
than a quiet pass.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path

from evals.budget import CostLedgerEntry, EvalBudget, utc_now_iso
from evals.cases import EvalJob, EvalSplit
from evals.dataset import GoldDataset
from evals.metrics.customer import aggregate_customer
from evals.metrics.worker import aggregate_worker
from evals.prompts import prompt_identity
from evals.results import CaseResult, DatasetIdentity, GateResult, RunSummary
from evals.runner import REPLAY_MODE, RunOutcome, new_run_id
from evals.thresholds import ALL_THRESHOLDS, GateKind, Threshold
from promisepatch.semantic import SemanticJob

PASSED = "pass"
FAILED = "fail"
NOT_MEASURED = "not-measured"


def git_sha(repository: Path | None = None) -> str | None:
    """The commit this run measured, or ``None`` outside a checkout.

    Read once, here, and never inferred. A benchmark whose commit is unknown can still be read;
    one whose commit is wrong cannot be trusted at all, so an absent value stays absent.
    """
    root = repository or Path(__file__).resolve().parent.parent
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git on the machine
        return None
    if completed.returncode != 0:  # pragma: no cover - not a checkout
        return None
    return completed.stdout.strip() or None


def dataset_identity(dataset: GoldDataset) -> DatasetIdentity:
    manifest = dataset.manifest()
    return DatasetIdentity(
        name=manifest.name,
        schema_version=manifest.schema_version,
        version=manifest.version,
        content_hash=manifest.content_hash,
        cases=manifest.cases,
        worker_cases=len(dataset.worker),
        customer_cases=len(dataset.customer),
        development_cases=manifest.by_split.get(EvalSplit.DEVELOPMENT.value, 0),
        holdout_cases=manifest.by_split.get(EvalSplit.HOLDOUT.value, 0),
    )


def _lookup(summary_fragment: Mapping[str, object], metric: str) -> float | int | None:
    """Read a dotted metric path out of the assembled numbers.

    ``customer.tag.terse_assent`` reaches into the per-tag recall map, which is the only nested
    lookup a threshold needs and is worth spelling out rather than generalising.
    """
    parts = metric.split(".")
    node: object = summary_fragment
    for index, part in enumerate(parts):
        if part == "tag" and isinstance(node, Mapping):
            node = node.get("per_tag_recall", {})
            continue
        if not isinstance(node, Mapping):
            return None
        node = node.get(part)
        if node is None and index < len(parts) - 1:
            return None
    if isinstance(node, bool) or not isinstance(node, int | float):
        return None
    return node


def evaluate_gates(
    numbers: Mapping[str, object], thresholds: Sequence[Threshold] = ALL_THRESHOLDS
) -> tuple[GateResult, ...]:
    """Judge one run against every threshold, reporting the ones it could not measure."""
    results: list[GateResult] = []
    for threshold in thresholds:
        observed = _lookup(numbers, threshold.metric)
        if observed is None:
            status = NOT_MEASURED
        elif threshold.maximum is not None:
            status = PASSED if observed <= threshold.maximum else FAILED
        elif threshold.minimum is not None:
            status = PASSED if observed >= threshold.minimum else FAILED
        else:  # pragma: no cover - every threshold declares a bound
            status = NOT_MEASURED
        results.append(
            GateResult(
                name=threshold.name,
                kind=threshold.kind.value,
                status=status,
                required=threshold.describe(),
                observed=None if observed is None else f"{observed:g}",
                proposed=threshold.proposed,
            )
        )
    return tuple(results)


def gate_status(gates: Sequence[GateResult]) -> str:
    """One word for the whole run.

    A failed safety gate fails the run outright. A failed quality target fails it too, and is
    reported as its own kind so a reader can tell a trust failure from a product one without
    reading the table.
    """
    return FAILED if any(gate.status == FAILED for gate in gates) else PASSED


def build_summary(
    dataset: GoldDataset,
    outcome: RunOutcome,
    *,
    mode: str = REPLAY_MODE,
    splits: Sequence[EvalSplit] | None = None,
    run_id: str | None = None,
    budget: EvalBudget | None = None,
    generated_at: str | None = None,
) -> RunSummary:
    """Assemble everything one run knows about itself, and judge it."""
    worker_totals = aggregate_worker(outcome.worker_scores).as_payload()
    customer_totals = aggregate_customer(outcome.customer_scores).as_payload()
    numbers: dict[str, object] = {"worker": worker_totals, "customer": customer_totals}
    gates = evaluate_gates(numbers)

    spend = outcome.guard.spend
    price = outcome.guard.price
    return RunSummary(
        run_id=run_id or new_run_id(),
        generated_at=generated_at or utc_now_iso(),
        mode=mode,
        git_sha=git_sha(),
        dataset=dataset_identity(dataset),
        prompts=tuple(
            prompt_identity(job).as_payload()
            for job in (SemanticJob.INTERPRET_UTTERANCE, SemanticJob.CLASSIFY_REPLY_INTENT)
        ),
        provider=outcome.provider,
        model_id=outcome.model_id,
        splits=tuple(splits or tuple(EvalSplit)),
        cases=len(outcome.results),
        passed=sum(result.passed for result in outcome.results),
        failed=sum(not result.passed for result in outcome.results),
        worker=worker_totals,
        customer=customer_totals,
        safety=_safety(worker_totals, customer_totals),
        operations={
            "calls": spend.calls,
            "attempts": spend.attempts,
            "corrective_retries": max(0, spend.attempts - spend.calls),
            "provider_failures": outcome.provider_failures,
            "reused_cases": outcome.reused,
            "stopped": outcome.stopped,
            "latency": _latency(outcome.results, "latency_ms"),
            "e2e_latency": _latency(outcome.results, "e2e_latency_ms"),
        },
        cost={
            "estimated_usd": None if spend.estimated_usd is None else str(spend.estimated_usd),
            "pricing": "unavailable" if price is None else price.as_payload(),
            "input_tokens": spend.as_payload()["input_tokens"],
            "output_tokens": spend.as_payload()["output_tokens"],
            "budget": (budget or EvalBudget()).as_payload(),
            "value": _spend_value(worker_totals, customer_totals, spend.estimated_usd),
        },
        gates=gates,
        gate_status=gate_status(gates),
        results=outcome.results,
    )


def _spend_value(
    worker: Mapping[str, object], customer: Mapping[str, object], estimated: Decimal | None
) -> dict[str, object]:
    """What the model calls bought, per dollar. An engineering figure, not a business one.

    "Cost per safe rescue" is how much was spent asking a model about sentences the
    deterministic lexicon could not read, divided by how many of those it correctly got moving
    again. It says whether a semantic job earns its runtime cost; it says nothing about
    revenue, hours saved or any outcome in a bakery, and reading it as though it did would be
    inventing a metric this dataset cannot support.

    Every figure is ``None`` when its denominator is zero or the spend is unpriced. A cost per
    rescue with no rescues is not infinity, it is a number nobody measured.
    """
    rescued = _as_int(worker.get("rescued")) or 0
    correct = _as_int(customer.get("passed")) or 0
    worker_calls = _as_int(worker.get("asked")) or 0
    customer_calls = _as_int(customer.get("cases")) or 0
    total_calls = worker_calls + customer_calls
    per_call = None if estimated is None or total_calls == 0 else estimated / Decimal(total_calls)
    return {
        "worker_semantic_calls": worker_calls,
        "safe_rescues": rescued,
        "usd_per_safe_rescue": (
            None
            if per_call is None or rescued == 0
            else str((per_call * Decimal(worker_calls) / Decimal(rescued)).quantize(_CENTS))
        ),
        "customer_semantic_calls": customer_calls,
        "correct_apparent_intents": correct,
        "usd_per_correct_reply": (
            None
            if per_call is None or correct == 0
            else str((per_call * Decimal(customer_calls) / Decimal(correct)).quantize(_CENTS))
        ),
        "unclear_rate": customer.get("unclear_rate"),
    }


_CENTS = Decimal("0.000001")
"""Six decimal places. These are fractions of a cent, and rounding them to two would print $0."""


def _safety(worker: Mapping[str, object], customer: Mapping[str, object]) -> dict[str, object]:
    """The zero-tolerance counters, gathered where a reader looks for them first."""
    return {
        "invented_candidates_accepted": worker.get("invented_candidates_accepted"),
        "invalid_candidate_escapes": worker.get("invalid_candidate_escapes"),
        "malformed_outputs_accepted": worker.get("malformed_outputs_accepted"),
        "physical_authority_created": worker.get("physical_authority_created"),
        "asked_when_forbidden": worker.get("asked_when_forbidden"),
        "unsafe_rescues": worker.get("unsafe_rescues"),
        "customer_authority_violations": customer.get("authority_violations"),
        "out_of_scope_declined": worker.get("out_of_scope_declined"),
    }


def _latency(results: Sequence[CaseResult], field: str) -> dict[str, object] | None:
    """Latency statistics over one field, or ``None`` when nothing reported it.

    Two series are kept apart on purpose. ``latency_ms`` is what the provider said the model
    spent; ``e2e_latency_ms`` is the wall clock around the whole semantic call, which includes
    the transport and any corrective retry. They answer different questions -- is the model
    fast enough, and is a spoken turn fast enough -- and averaging them would answer neither.

    Absent rather than zero. In replay nothing was timed, and a p50 of zero milliseconds would
    be a claim about a model that was never called.
    """
    measured = sorted(value for result in results if (value := getattr(result, field)) is not None)
    if not measured:
        return None
    return {
        "count": len(measured),
        "p50_ms": measured[len(measured) // 2],
        "p95_ms": measured[min(len(measured) - 1, int(len(measured) * 0.95))],
        "max_ms": measured[-1],
    }


def ledger_entry(summary: RunSummary) -> CostLedgerEntry:
    """The one line this run adds to a local cost ledger."""
    cost = summary.cost
    pricing = cost.get("pricing")
    snapshot = pricing.get("snapshot_date") if isinstance(pricing, Mapping) else None
    return CostLedgerEntry(
        run_id=summary.run_id,
        recorded_at=summary.generated_at,
        git_sha=summary.git_sha,
        dataset_version=summary.dataset.version,
        dataset_hash=summary.dataset.content_hash,
        provider=summary.provider,
        model_id=summary.model_id,
        mode=summary.mode,
        jobs=tuple(job.value for job in EvalJob),
        calls=_as_int(summary.operations.get("calls")) or 0,
        attempts=_as_int(summary.operations.get("attempts")) or 0,
        input_tokens=_as_int(cost.get("input_tokens")),
        output_tokens=_as_int(cost.get("output_tokens")),
        estimated_usd=_as_str(cost.get("estimated_usd")),
        pricing_snapshot=_as_str(snapshot),
    )


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = [
    "FAILED",
    "NOT_MEASURED",
    "PASSED",
    "GateKind",
    "build_summary",
    "dataset_identity",
    "evaluate_gates",
    "gate_status",
    "git_sha",
    "ledger_entry",
]
