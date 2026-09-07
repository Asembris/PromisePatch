"""The human-readable run report: four sections, and nothing invented in any of them.

Quality, safety, operations, cost -- in that order, and never blended. A single headline score
would let a zero-tolerance failure hide inside an average, which is the one thing this report
exists to prevent.

Where a number was not measured it says ``n/a``. In replay there is no model, no latency and no
token count; printing zeros for those would turn the absence of a measurement into a
measurement, and a reader skimming the cost section would come away believing a benchmark had
been priced.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from evals.results import GateResult, RunSummary
from evals.summary import FAILED, NOT_MEASURED

NA = "n/a"


def _number(value: object, *, digits: int = 3) -> str:
    if isinstance(value, bool) or value is None:
        return NA
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _line(label: str, value: object, *, width: int = 34) -> str:
    return f"  {label.ljust(width)} {_number(value)}"


def render(summary: RunSummary) -> str:
    """The whole report as one string. Printed by the CLI, asserted by the tests."""
    sections = [
        _header(summary),
        _quality(summary),
        _safety(summary),
        _operations(summary),
        _cost(summary),
        _gates(summary.gates),
        _failures(summary),
    ]
    return "\n".join(section for section in sections if section)


def _header(summary: RunSummary) -> str:
    dataset = summary.dataset
    prompts = ", ".join(
        f"{entry['job']}:{entry['system_hash']}/{entry['schema_hash']}" for entry in summary.prompts
    )
    return "\n".join(
        [
            "PromisePatch semantic evaluation",
            f"  run          {summary.run_id}  ({summary.mode})",
            f"  commit       {summary.git_sha or NA}",
            f"  dataset      {dataset.name} v{dataset.version} "
            f"(schema {dataset.schema_version}, {dataset.content_hash[:12]})",
            f"  cases        {dataset.cases}  "
            f"({dataset.worker_cases} worker, {dataset.customer_cases} customer; "
            f"{dataset.development_cases} development, {dataset.holdout_cases} holdout)",
            f"  provider     {summary.provider}  model {summary.model_id or NA}",
            f"  prompts      {prompts}",
            f"  result       {summary.passed}/{summary.cases} passed  "
            f"[gate {summary.gate_status.upper()}]",
            "",
        ]
    )


def _quality(summary: RunSummary) -> str:
    lines = ["QUALITY"]
    worker = summary.worker or {}
    customer = summary.customer or {}
    lines.append(
        f"  worker semantics ({_number(worker.get('asked'))} asked, "
        f"{_number(worker.get('unasked'))} never asked)"
    )
    for label, key in (
        ("category accuracy", "category_accuracy"),
        ("candidate exact match", "candidate_accuracy"),
        ("grounding outcome accuracy", "grounding_accuracy"),
        ("interpretation outcome accuracy", "outcome_accuracy"),
        ("structured-output validity", "structured_output_validity"),
    ):
        lines.append(_line(label, worker.get(key)))
    lines.append(
        f"    {'safe rescue rate'.ljust(32)} {_number(worker.get('safe_rescue_rate'))}"
        f"  ({_number(worker.get('rescued'))}/{_number(worker.get('rescuable'))} rescuable)"
    )
    lines.append("")
    lines.append(f"  customer intent ({_number(customer.get('cases'))} replies)")
    for label, key in (
        ("accuracy", "accuracy"),
        ("macro F1", "macro_f1"),
        ("UNCLEAR rate", "unclear_rate"),
    ):
        lines.append(_line(label, customer.get(key)))
    for entry in _per_class(customer):
        lines.append(
            f"    {str(entry['label']).ljust(32)} "
            f"recall {_number(entry['recall'])}  precision {_number(entry['precision'])}  "
            f"F1 {_number(entry['f1'])}  (n={_number(entry['support'])})"
        )
    lines.append("")
    lines.extend(_confusion(customer))
    lines.append("")
    lines.extend(_weakest(worker, customer))
    lines.append("")
    return "\n".join(lines)


def _weakest(worker: Mapping[str, object], customer: Mapping[str, object]) -> list[str]:
    """The clusters this run did worst on, lowest first.

    Reported because the aggregate is the number most likely to be quoted and least likely to
    be actionable: a classifier can score well overall while missing every member of one
    cluster, and the cluster is what a customer notices. The full per-tag tables are in the
    JSON summary; this is the part worth reading first.
    """
    scored: list[tuple[float, str]] = []
    for source, label in ((customer, "customer"), (worker, "worker")):
        per_tag = source.get("per_tag_recall") or source.get("per_tag_pass_rate")
        if not isinstance(per_tag, dict):
            continue
        scored.extend(
            (float(rate), f"{label}:{tag}")
            for tag, rate in per_tag.items()
            if isinstance(rate, int | float)
        )
    if not scored:
        return []
    scored.sort()
    lines = ["  weakest clusters (lowest first; full per-tag tables are in the JSON summary)"]
    lines.extend(f"    {name.ljust(38)} {rate:.3f}" for rate, name in scored[:5])
    return lines


def _per_class(customer: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
    per_class = customer.get("per_class")
    if not isinstance(per_class, list):
        return ()
    return [entry for entry in per_class if isinstance(entry, dict)]


def _confusion(customer: Mapping[str, object]) -> list[str]:
    matrix = customer.get("confusion")
    if not isinstance(matrix, dict) or not matrix:
        return []
    columns = list(next(iter(matrix.values())))
    header = "    " + "gold \\ read".ljust(20) + "".join(name[:10].rjust(12) for name in columns)
    lines = ["  confusion matrix", header]
    for gold, row in matrix.items():
        cells = "".join(str(row.get(column, 0)).rjust(12) for column in columns)
        lines.append("    " + gold.ljust(20) + cells)
    return lines


def _safety(summary: RunSummary) -> str:
    lines = ["SAFETY  (zero tolerance; a count above zero fails the run)"]
    for label, key in (
        ("accepted invented candidate ids", "invented_candidates_accepted"),
        ("invalid candidate escapes", "invalid_candidate_escapes"),
        ("malformed outputs accepted", "malformed_outputs_accepted"),
        ("model-created physical authority", "physical_authority_created"),
        ("asked when the boundary forbids", "asked_when_forbidden"),
        ("unsafe rescues", "unsafe_rescues"),
        ("customer authority violations", "customer_authority_violations"),
    ):
        lines.append(_line(label, summary.safety.get(key)))
    lines.append(_line("out-of-scope declined", summary.safety.get("out_of_scope_declined")))
    lines.append("")
    return "\n".join(lines)


def _operations(summary: RunSummary) -> str:
    lines = ["OPERATIONS"]
    lines.append(_line("provider calls", summary.operations.get("calls")))
    lines.append(_line("provider attempts", summary.operations.get("attempts")))
    latency = summary.operations.get("latency")
    if isinstance(latency, dict):
        lines.append(_line("latency p50 (ms)", latency.get("p50_ms")))
        lines.append(_line("latency p95 (ms)", latency.get("p95_ms")))
        lines.append(_line("latency max (ms)", latency.get("max_ms")))
    else:
        lines.append(f"  {'latency'.ljust(34)} {NA}  (no provider reported any)")
    lines.append("")
    return "\n".join(lines)


def _cost(summary: RunSummary) -> str:
    cost = summary.cost
    pricing = cost.get("pricing")
    lines = ["COST  (estimate from a recorded price list; AWS Billing is the truth)"]
    lines.append(_line("input tokens", cost.get("input_tokens")))
    lines.append(_line("output tokens", cost.get("output_tokens")))
    estimated = cost.get("estimated_usd")
    lines.append(
        f"  {'estimated spend'.ljust(34)} "
        f"{'unavailable' if estimated is None else '$' + str(estimated)}"
    )
    if isinstance(pricing, dict):
        lines.append(
            f"  {'pricing snapshot'.ljust(34)} "
            f"{pricing.get('snapshot_date')}  {pricing.get('source')}"
        )
    else:
        lines.append(
            f"  {'pricing snapshot'.ljust(34)} {NA}  "
            f"(no verified price is configured for this model)"
        )
    lines.append("")
    return "\n".join(lines)


def _gates(gates: Sequence[GateResult]) -> str:
    lines = ["GATES"]
    for gate in gates:
        marker = {"pass": "ok  ", FAILED: "FAIL", NOT_MEASURED: "--  "}.get(gate.status, "?   ")
        suffix = "  [PROPOSED - REVIEW BEFORE LIVE BENCHMARK]" if gate.proposed else ""
        lines.append(
            f"  {marker} {gate.kind.ljust(8)} {gate.name.ljust(38)} "
            f"{gate.required.ljust(9)} got {gate.observed or NA}{suffix}"
        )
    lines.append("")
    return "\n".join(lines)


def _failures(summary: RunSummary) -> str:
    failures = [result for result in summary.results if not result.passed]
    if not failures:
        return "No case failed.\n"
    lines = [f"FAILING CASES ({len(failures)})"]
    for result in failures:
        lines.append(f"  {result.case_id.ljust(46)} {result.reason}")
    lines.append("")
    return "\n".join(lines)


__all__ = ["NA", "render"]
