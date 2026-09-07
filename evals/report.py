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
from decimal import Decimal

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
    """The clusters this run did worst on, lowest first, each with its two counts.

    Reported because the aggregate is the number most likely to be quoted and least likely to
    be actionable: a classifier can score well overall while missing every member of one
    cluster, and the cluster is what a customer notices. The full per-tag tables are in the
    JSON summary; this is the part worth reading first.

    The numerator and denominator are printed beside the rate and not instead of it. Several
    of these clusters are five hand-authored cases, and "0.800" over five of them is four --
    a fact a reader is entitled to see without opening the JSON.
    """
    scored: list[tuple[float, str, str]] = []
    for source, label in ((customer, "customer"), (worker, "worker")):
        per_tag = source.get("per_tag_recall") or source.get("per_tag_pass_rate")
        counts = source.get("per_tag_counts")
        if not isinstance(per_tag, dict):
            continue
        for tag, rate in per_tag.items():
            if not isinstance(rate, int | float):
                continue
            scored.append((float(rate), f"{label}:{tag}", _fraction(counts, tag)))
    if not scored:
        return []
    scored.sort()
    lines = ["  weakest clusters (lowest first; full per-tag tables are in the JSON summary)"]
    lines.extend(
        f"    {name.ljust(38)} {rate:.3f}  {fraction}" for rate, name, fraction in scored[:5]
    )
    return lines


def _fraction(counts: object, tag: str) -> str:
    """``(4/5)`` for one tag, or empty when the run did not record the counts."""
    if not isinstance(counts, Mapping):
        return ""
    entry = counts.get(tag)
    if not isinstance(entry, Mapping):
        return ""
    return f"({entry.get('hits')}/{entry.get('total')})"


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
    operations = summary.operations
    lines = ["OPERATIONS"]
    lines.append(_line("logical provider calls", operations.get("calls")))
    lines.append(_line("provider attempts", operations.get("attempts")))
    lines.append(_line("structured-output retries", operations.get("corrective_retries")))
    lines.append(_line("provider/transport failures", operations.get("provider_failures")))
    reused = operations.get("reused_cases")
    if isinstance(reused, int) and reused:
        lines.append(_line("cases reused from an earlier attempt", reused))
    lines.extend(_latency_lines("model latency", operations.get("latency")))
    lines.extend(_latency_lines("end-to-end latency", operations.get("e2e_latency")))
    stopped = operations.get("stopped")
    if isinstance(stopped, str):
        lines.append(f"  RUN STOPPED EARLY: {stopped}")
    lines.append("")
    return "\n".join(lines)


def _latency_lines(label: str, latency: object) -> list[str]:
    """One latency series, or the statement that nobody measured it."""
    if not isinstance(latency, Mapping):
        return [f"  {label.ljust(34)} {NA}  (nothing reported it)"]
    return [
        _line(f"{label} p50 (ms)", latency.get("p50_ms")),
        _line(f"{label} p95 (ms)", latency.get("p95_ms")),
        _line(f"{label} max (ms)", latency.get("max_ms")),
    ]


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
    lines.extend(_ceiling(cost))
    lines.extend(_value(cost.get("value")))
    lines.append("")
    return "\n".join(lines)


def _ceiling(cost: Mapping[str, object]) -> list[str]:
    """How much of the run's own dollar ceiling this run used.

    A budget only informs once somebody says what fraction of it went. Printed when both
    halves exist: a percentage of an uncapped budget is not a number.
    """
    budget = cost.get("budget")
    estimated = cost.get("estimated_usd")
    if not isinstance(budget, Mapping) or not isinstance(estimated, str):
        return []
    cap = budget.get("max_estimated_usd")
    if not isinstance(cap, str) or Decimal(cap) == 0:
        return []
    share = Decimal(estimated) / Decimal(cap) * 100
    return [f"  {'share of the dollar ceiling'.ljust(34)} {share:.2f}%  (ceiling ${cap})"]


def _value(value: object) -> list[str]:
    """What the calls bought, per dollar. An engineering efficiency figure and nothing more.

    Not a business measure: nothing here knows what a rescued sentence is worth to a bakery.
    What it answers is narrower, and is the question a later slice has to decide -- whether a
    semantic job earns the runtime cost of asking.
    """
    if not isinstance(value, Mapping):
        return []
    lines = ["", "  what the model calls bought (engineering efficiency, not business value)"]
    lines.append(
        f"    {'safe worker rescues'.ljust(32)} "
        f"{_number(value.get('safe_rescues'))} from "
        f"{_number(value.get('worker_semantic_calls'))} semantic calls"
    )
    per_rescue = value.get("usd_per_safe_rescue")
    lines.append(
        f"    {'cost per safe rescue'.ljust(32)} "
        f"{NA if per_rescue is None else '$' + str(per_rescue)}"
    )
    lines.append(
        f"    {'correct apparent intents'.ljust(32)} "
        f"{_number(value.get('correct_apparent_intents'))} from "
        f"{_number(value.get('customer_semantic_calls'))} semantic calls"
    )
    per_reply = value.get("usd_per_correct_reply")
    lines.append(
        f"    {'cost per correctly read reply'.ljust(32)} "
        f"{NA if per_reply is None else '$' + str(per_reply)}"
    )
    return lines


def _gates(gates: Sequence[GateResult]) -> str:
    lines = ["GATES"]
    for gate in gates:
        marker = {"pass": "ok  ", FAILED: "FAIL", NOT_MEASURED: "--  "}.get(gate.status, "?   ")
        suffix = "  [PROPOSED - NOT YET REVIEWED]" if gate.proposed else ""
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
