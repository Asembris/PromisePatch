"""The challenger's two reports, written so a reader can disagree with the conclusion.

Stage A is a spending decision and reads like one: every challenged case, what each model said
about it, and the five criteria that decide whether the rest of the split is worth buying.
Stage B is a model-quality comparison and reads like one: the same metrics the model being
challenged was measured on, the paired join, the clusters that motivated the challenge, and the
cost -- with quality and cost in separate sections, because they are separate decisions.

Nothing here computes a metric. Every number comes from :mod:`evals.challenger` or
:mod:`evals.metrics`, and where a number was not measured it says so rather than printing zero.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from evals.budget import Billing, ModelPrice
from evals.challenger import (
    ClusterDelta,
    MaterialityVerdict,
    PairedCase,
    PairedOutcome,
    PairedTotals,
    Role,
    StageAOutcome,
    UsageProfile,
    predicted_label,
)
from evals.results import CaseResult
from promisepatch.semantic import ApparentIntent

NA = "n/a"
NEWLINE = chr(10)


def _rate(value: float | None, digits: int = 3) -> str:
    return NA if value is None else f"{value:.{digits}f}"


def _label(value: object) -> str:
    return NA if value is None else str(value)


def render_stage_a(outcome: StageAOutcome, verdict: MaterialityVerdict) -> str:
    """The Stage-A block: the set, the paired readings, and the decision it feeds."""
    selection = outcome.selection
    lines = [
        "TARGETED CUSTOMER-INTENT CHALLENGER  --  STAGE A",
        "",
        "  SET IDENTITY",
        f"    selection algorithm        v{selection.algorithm_version}",
        f"    source run                 {selection.source_run_id}  "
        f"({_label(selection.source_model_id)})",
        f"    source results sha256      {selection.source_results_sha}",
        f"    dataset                    v{selection.dataset_version}  "
        f"{selection.dataset_hash[:12]}",
        f"    failures challenged        {len(outcome.selection.pairs)}",
        f"    matched controls           {len(outcome.selection.pairs)}",
        f"    cases in stage A           {len(selection.case_ids)}",
        "",
        "  PAIRED READINGS",
    ]
    header = (
        f"    {'case'.ljust(34)} {'role'.ljust(8)} {'gold'.ljust(17)} "
        f"{'source'.ljust(17)} {'challenger'.ljust(17)} outcome"
    )
    lines.append(header)
    for case in outcome.cases:
        flag = "  <- DIRECTIONAL INVERSION" if case.directional_inversion else ""
        if not case.comparable:
            category = "" if case.failure_category is None else f"  [{case.failure_category.value}]"
            flag = f"  <- NOT A QUALITY OBSERVATION{category}"
        lines.append(
            f"    {case.case_id.ljust(34)} {case.role.value.ljust(8)} "
            f"{case.gold.value.ljust(17)} {_label(_value(case.source_predicted)).ljust(17)} "
            f"{_label(_value(case.challenger_predicted)).ljust(17)} {case.outcome.value}{flag}"
        )
    if not outcome.complete:
        seen = {case.case_id for case in outcome.comparable}
        missing = sorted(selection.case_ids - seen)
        lines.append(f"    INCOMPLETE -- no reading for: {', '.join(missing)}")

    lines.extend(
        [
            "",
            "  EXECUTION  (whether a reading exists; nothing here is about quality)",
            f"    cases selected             {len(selection.case_ids)}",
            f"    readings obtained          {outcome.provider_completion}",
            f"    provider failures          {len(outcome.provider_failures)}",
            f"    eligible comparisons       {len(outcome.comparable)}",
            "",
            "  QUALITY  (denominators are the cases both models read, and only those)",
            f"    comparable failures        {len(outcome.comparable_failures)} "
            f"of {len(outcome.failures)} selected",
            f"    comparable controls        {len(outcome.comparable_controls)} "
            f"of {len(outcome.controls)} selected",
            f"    failure repairs            {outcome.repairs}/{len(outcome.comparable_failures)}",
            f"    unchanged failures         {outcome.unchanged_failures}/"
            f"{len(outcome.comparable_failures)}",
            f"    directional inversions     {outcome.directional_inversions}",
            f"    controls preserved         {outcome.controls_preserved}/"
            f"{len(outcome.comparable_controls)}",
            f"    control regressions        {outcome.control_regressions}/"
            f"{len(outcome.comparable_controls)}",
            f"    authority violations       {outcome.authority_violations}",
            f"    failure repair rate        {_rate(outcome.repair_rate)}",
        ]
    )
    if outcome.provider_failures:
        lines.extend(
            [
                "",
                "    A provider failure is not an unrepaired failure and not a control "
                "regression. It is",
                "    absent evidence, it is excluded from every denominator above, and it "
                "leaves this stage",
                "    incomplete -- so no materiality verdict is available and Stage B stays "
                "closed.",
            ]
        )
    lines.extend(
        [
            "",
            "  MATERIALITY  (fixed before the first challenger call; a spending decision, "
            "not an acceptance bar)",
        ]
    )
    if not outcome.complete:
        lines.append(
            "    NOT EVALUABLE -- the stage is incomplete. Each criterion below describes the "
            "partial set"
        )
        lines.append(
            "    that was read and decides nothing; a stage that did not finish has no "
            "materiality verdict."
        )
    for criterion in verdict.criteria:
        status = "pass" if criterion.passed else "FAIL"
        lines.append(
            f"    {criterion.name.ljust(32)} {criterion.required.ljust(10)} "
            f"observed {criterion.observed.ljust(8)} {status}"
        )
    lines.append("")
    return "\n".join(lines)


def _value(label: object) -> str | None:
    return None if label is None else str(getattr(label, "value", label))


def render_stage_b(
    *,
    challenger_totals: Mapping[str, object],
    source_totals: Mapping[str, object],
    paired: Sequence[PairedCase],
    totals: PairedTotals,
    clusters: Sequence[ClusterDelta],
    focus: Sequence[str],
) -> str:
    """The full-split comparison: the same metrics for both models, then the join."""
    lines = [
        "TARGETED CUSTOMER-INTENT CHALLENGER  --  STAGE B  (full development split)",
        "",
        "  CUSTOMER QUALITY  (same gold, same scorer, same cases)",
        f"    {'metric'.ljust(32)} {'source'.ljust(12)} challenger",
    ]
    for label, key in (
        ("cases", "cases"),
        ("accuracy", "accuracy"),
        ("macro F1", "macro_f1"),
        ("UNCLEAR rate", "unclear_rate"),
        ("authority violations", "authority_violations"),
    ):
        lines.append(
            f"    {label.ljust(32)} {_metric(source_totals, key).ljust(12)} "
            f"{_metric(challenger_totals, key)}"
        )

    lines.extend(["", "  PER CLASS  (precision / recall / F1)"])
    source_classes = {item["label"]: item for item in _per_class(source_totals)}
    for item in _per_class(challenger_totals):
        name = str(item["label"])
        source_item = source_classes.get(name, {})
        lines.append(f"    {name}  (support {item['support']})")
        lines.append(
            f"      source                   {_rate(_float(source_item.get('precision')))} / "
            f"{_rate(_float(source_item.get('recall')))} / "
            f"{_rate(_float(source_item.get('f1')))}"
        )
        lines.append(
            f"      challenger               {_rate(_float(item.get('precision')))} / "
            f"{_rate(_float(item.get('recall')))} / {_rate(_float(item.get('f1')))}"
        )

    lines.extend(["", "  CONFUSION  (challenger; gold row by predicted column)"])
    lines.extend(_confusion(challenger_totals))

    lines.extend(
        [
            "",
            "  FAILURE CLUSTERS  (the reason this challenge was run; counts beside every rate)",
            f"    {'tag'.ljust(24)} {'n'.ljust(4)} {'source'.ljust(14)} "
            f"{'challenger'.ljust(14)} delta",
        ]
    )
    wanted = set(focus)
    for cluster in clusters:
        marker = "*" if cluster.tag in wanted else " "
        source_cell = f"{cluster.source_hits}/{cluster.total} {cluster.source_recall:.3f}"
        challenger_cell = (
            f"{cluster.challenger_hits}/{cluster.total} {cluster.challenger_recall:.3f}"
        )
        lines.append(
            f"  {marker} {cluster.tag.ljust(24)} {str(cluster.total).ljust(4)} "
            f"{source_cell.ljust(14)} {challenger_cell.ljust(14)} {cluster.delta:+.3f}"
        )
    lines.append("    * a cluster this challenge was run because of")

    lines.extend(
        [
            "",
            "  PAIRED COMPARISON  (same case, two readings)",
            f"    cases compared             {totals.cases}",
            f"    both correct               {totals.both_correct}",
            f"    both wrong                 {totals.both_wrong}",
            f"    challenger fixes a miss    {totals.challenger_only_correct}",
            f"    source fixes a miss        {totals.source_only_correct}",
            f"    wins / losses / ties       {totals.wins} / {totals.losses} / {totals.ties}",
            f"    exact paired sign test     {_p(totals.exact_paired_p)}",
            "    NOTE  this set was built from one model's failures and is small and "
            "hand-authored;",
            "          the p-value is secondary evidence about these cases, not a claim "
            "about a population.",
            "",
            "  DISAGREEMENTS",
        ]
    )
    disagreed = [case for case in paired if case.source_correct != case.challenger_correct]
    if not disagreed:
        lines.append("    none")
    for case in disagreed:
        winner = "challenger" if case.challenger_correct else "source"
        lines.append(
            f"    {case.case_id.ljust(34)} gold {case.gold.value.ljust(17)} "
            f"source {_label(_value(case.source_predicted)).ljust(17)} "
            f"challenger {_label(_value(case.challenger_predicted)).ljust(17)} -> {winner}"
        )
    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------ several challengers, one frozen selection


@dataclass(frozen=True, slots=True)
class PriorColumn:
    """One earlier challenger's readings of the same twelve cases, for the comparison table.

    A *column*, deliberately, and not a second baseline. Every outcome in this report is still
    computed against the model being challenged, because that is what makes two challengers
    comparable with each other: they were selected from the same failures, matched to the same
    controls and judged against the same labels. Redefining "repaired" relative to whichever
    challenger ran previously would make each new model's number depend on the order the models
    happened to be run in.

    So this carries readings and nothing else. It contributes no outcome, no aggregate that
    feeds the materiality gate and no threshold of its own.
    """

    label: str
    model_id: str | None
    readings: Mapping[str, ApparentIntent | None]
    """Case id to what that model said, or absent where it produced no reading."""

    unanswered: frozenset[str] = frozenset()
    """Cases this model was asked about and did not answer. Kept apart from a wrong answer,
    because "the endpoint refused" and "the model misread the sentence" are different facts and
    only one of them is about a model."""

    def show(self, case_id: str) -> str:
        if case_id in self.unanswered:
            return "no reading"
        reading = self.readings.get(case_id)
        return NA if reading is None else reading.value

    def correct(self, cases: Sequence[PairedCase]) -> int:
        return sum(1 for case in cases if self.readings.get(case.case_id) is case.gold)

    def repairs(self, cases: Sequence[PairedCase]) -> int:
        """How many of the challenged model's failures this column read correctly.

        The same definition the paired taxonomy uses for the challenger, applied to a stored
        column: a failure case answered with the gold label. Computed here rather than lifted
        from that model's own run so both numbers mean exactly the same thing.
        """
        return sum(
            1
            for case in cases
            if case.role is Role.FAILURE and self.readings.get(case.case_id) is case.gold
        )

    def control_regressions(self, cases: Sequence[PairedCase]) -> int:
        return sum(
            1
            for case in cases
            if case.role is Role.CONTROL
            and case.case_id not in self.unanswered
            and self.readings.get(case.case_id) is not case.gold
        )


def column_from_results(
    label: str, model_id: str | None, results: Sequence[CaseResult]
) -> PriorColumn:
    """One stored challenger run as a column. Reads results and calls nothing."""
    readings: dict[str, ApparentIntent | None] = {}
    unanswered: set[str] = set()
    for result in results:
        if result.has_reading:
            readings[result.case_id] = predicted_label(result)
        else:
            unanswered.add(result.case_id)
    return PriorColumn(
        label=label, model_id=model_id, readings=readings, unanswered=frozenset(unanswered)
    )


def render_comparison(
    outcome: StageAOutcome,
    *,
    challenger_label: str,
    priors: Sequence[PriorColumn] = (),
) -> str:
    """Every challenger's reading of the same cases, side by side, with outcomes unchanged.

    One table and one aggregate block. The outcome column is the challenger's against the model
    being challenged and is the only one there is: a prior column's number appears beside it for
    a reader to compare, never as a second definition of what a repair is.
    """
    cases = outcome.cases
    source = outcome.selection.source_model_id or "source"
    heads = ["case", "gold", _short(source)]
    heads.extend(_short(column.label) for column in priors)
    heads.append(_short(challenger_label))
    lines = [
        "STAGE-A COMPARISON  -- the same frozen selection, read by every challenger so far",
        "",
        "  Outcomes are the challenger's against the model being challenged. Earlier "
        "challengers appear",
        "  as columns for comparison and define nothing: the pairing, the thresholds and the "
        "vocabulary",
        "  are the ones fixed before the first call.",
        "",
        "  " + _row(heads) + "  outcome vs " + _short(source),
    ]
    for case in cases:
        cells = [case.case_id, case.gold.value, _label(_value(case.source_predicted))]
        cells.extend(column.show(case.case_id) for column in priors)
        cells.append(case.challenger_predicted.value if case.challenger_predicted else "no reading")
        lines.append("  " + _row(cells) + "  " + case.outcome.value)

    failures = [case for case in cases if case.role is Role.FAILURE]
    controls = [case for case in cases if case.role is Role.CONTROL]
    repairs = sum(1 for case in failures if case.outcome is PairedOutcome.REPAIRED)
    regressions = sum(1 for case in controls if case.outcome is PairedOutcome.CONTROL_REGRESSION)
    total = str(len(cases))
    lines.extend(
        [
            "",
            "  AGGREGATES  (every column against the same gold labels and the same roles)",
            "    "
            + "column".ljust(28)
            + ("correct/" + total).ljust(12)
            + ("repairs/" + str(len(failures))).ljust(12)
            + "control regressions",
            "    "
            + _short(source).ljust(28)
            + str(sum(1 for case in cases if case.source_correct)).ljust(12)
            + "-".ljust(12)
            + "-",
        ]
    )
    for column in priors:
        lines.append(
            "    "
            + _short(column.label).ljust(28)
            + str(column.correct(cases)).ljust(12)
            + str(column.repairs(cases)).ljust(12)
            + str(column.control_regressions(cases))
        )
    lines.append(
        "    "
        + _short(challenger_label).ljust(28)
        + str(sum(1 for case in cases if case.challenger_correct)).ljust(12)
        + str(repairs).ljust(12)
        + str(regressions)
    )
    lines.extend(["", "  BY SIDE  (which half of the customer's answer each repair was on)"])
    for side, name in (
        (ApparentIntent.APPARENT_APPROVE, "approve-side"),
        (ApparentIntent.APPARENT_DECLINE, "decline-side"),
        (ApparentIntent.UNCLEAR, "unclear-side"),
    ):
        wanted = [case for case in failures if case.gold is side]
        repaired = sum(1 for case in wanted if case.outcome is PairedOutcome.REPAIRED)
        lines.append(
            "    " + name.ljust(28) + str(repaired) + " of " + str(len(wanted)) + " repaired"
        )
    lines.append("")
    return NEWLINE.join(lines)


_WIDTHS = (34, 17, 18, 18, 18, 18, 18)


def _row(cells: Sequence[str]) -> str:
    return " ".join(cell.ljust(width) for cell, width in zip(cells, _WIDTHS, strict=False))


def _short(value: str) -> str:
    """A model id trimmed to the column, from the right, because the tail is what differs."""
    return value if len(value) <= 18 else "..." + value[-15:]


def render_cost(
    *,
    source: UsageProfile,
    challenger: UsageProfile,
    source_price: ModelPrice | None,
    challenger_price: ModelPrice | None,
    source_latency: Mapping[str, object] | None,
    challenger_latency: Mapping[str, object] | None,
    challenger_billing: Billing | None = None,
) -> str:
    """The cost section, kept apart from quality because it is a different decision.

    ``challenger_billing`` says *why* a money figure is missing when one is. An empty column
    reads as a measurement nobody took; a challenger on a free hosted endpoint has no per-token
    price to measure, which is a different and less alarming fact, and saying which of the two
    it is costs one line.
    """
    source_k = source.usd_per_thousand(source_price)
    challenger_k = challenger.usd_per_thousand(challenger_price)
    lines = [
        "COST  (engineering estimate from observed token usage and recorded pricing "
        "snapshots; not an AWS bill)",
        "",
        f"    {'figure'.ljust(34)} {'source'.ljust(18)} challenger",
        f"    {'model'.ljust(34)} {_label(source.model_id)[:18].ljust(18)} "
        f"{_label(challenger.model_id)}",
        f"    {'logical calls'.ljust(34)} {str(source.calls).ljust(18)} {challenger.calls}",
        f"    {'attempts'.ljust(34)} {str(source.attempts).ljust(18)} {challenger.attempts}",
        f"    {'input tokens'.ljust(34)} {_label(source.input_tokens).ljust(18)} "
        f"{_label(challenger.input_tokens)}",
        f"    {'output tokens'.ljust(34)} {_label(source.output_tokens).ljust(18)} "
        f"{_label(challenger.output_tokens)}",
        f"    {'mean input tokens / call'.ljust(34)} "
        f"{_rate(source.mean_input_tokens, 1).ljust(18)} "
        f"{_rate(challenger.mean_input_tokens, 1)}",
        f"    {'mean output tokens / call'.ljust(34)} "
        f"{_rate(source.mean_output_tokens, 1).ljust(18)} "
        f"{_rate(challenger.mean_output_tokens, 1)}",
        f"    {'correct classifications'.ljust(34)} {str(source.correct).ljust(18)} "
        f"{challenger.correct}",
        f"    {'estimated spend on these cases'.ljust(34)} "
        f"{_money(source.estimated_usd).ljust(18)} {_money(challenger.estimated_usd)}",
        f"    {'estimated $ / correct answer'.ljust(34)} "
        f"{_money(source.usd_per_correct()).ljust(18)} {_money(challenger.usd_per_correct())}",
        f"    {'estimated $ / 1,000 calls'.ljust(34)} {_money(source_k).ljust(18)} "
        f"{_money(challenger_k)}",
    ]
    if challenger_billing is not None and not challenger_billing.is_metered:
        lines.extend(
            [
                "",
                f"  CHALLENGER BILLING  {challenger_billing.mode.value}",
                "    No per-token price is modelled for this endpoint, so every money figure "
                "above is absent",
                "    rather than zero. What bounded the run was its call and token ceilings. "
                "Nothing here says",
                "    this endpoint is free permanently or that production use would be.",
            ]
        )

    lines.extend(["", "  PREMIUM"])
    if source_k is None or challenger_k is None or source_k == 0:
        lines.append("    not computable -- one side has no priced token measurement")
    else:
        multiple = (challenger_k / source_k).quantize(Decimal("0.01"))
        absolute = (challenger_k - source_k).quantize(Decimal("0.000001"))
        lines.extend(
            [
                f"    cost multiple              {multiple}x",
                f"    absolute difference        ${absolute} per 1,000 customer-intent calls",
                "    The multiple alone decides nothing. The absolute figure is the one that "
                "says whether",
                "    this premium is material for this job at this volume.",
            ]
        )

    lines.extend(["", "  LATENCY  (measured in separate runs; not a controlled comparison)"])
    lines.extend(_latency("source", source_latency))
    lines.extend(_latency("challenger", challenger_latency))
    lines.append(
        "    Different runs, different credential and network conditions. A small difference "
        "here is not a finding."
    )
    lines.append("")
    return "\n".join(lines)


def _latency(who: str, latency: Mapping[str, object] | None) -> list[str]:
    if latency is None:
        return [f"    {who.ljust(12)} not reported"]
    return [
        f"    {who.ljust(12)} model p50 {_label(latency.get('p50_ms'))} ms  "
        f"p95 {_label(latency.get('p95_ms'))} ms  max {_label(latency.get('max_ms'))} ms  "
        f"(n={_label(latency.get('count'))})"
    ]


def _metric(totals: Mapping[str, object], key: str) -> str:
    value = totals.get(key)
    if value is None:
        return NA
    if isinstance(value, bool):  # pragma: no cover - no boolean metric is printed here
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _per_class(totals: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
    entries = totals.get("per_class")
    if not isinstance(entries, list):  # pragma: no cover - always a list from the aggregate
        return ()
    return [entry for entry in entries if isinstance(entry, Mapping)]


def _confusion(totals: Mapping[str, object]) -> list[str]:
    matrix = totals.get("confusion")
    if not isinstance(matrix, Mapping):  # pragma: no cover - always a mapping
        return ["    n/a"]
    columns: list[str] = []
    for row in matrix.values():
        if isinstance(row, Mapping):
            columns = list(row)
            break
    lines = [
        f"    {'gold \\ predicted'.ljust(20)} " + " ".join(name[:9].rjust(9) for name in columns)
    ]
    for gold, row in matrix.items():
        if not isinstance(row, Mapping):  # pragma: no cover - always a mapping
            continue
        lines.append(
            f"    {str(gold).ljust(20)} "
            + " ".join(str(row.get(name, 0)).rjust(9) for name in columns)
        )
    return lines


def _float(value: object) -> float | None:
    return value if isinstance(value, float) else None


def _money(value: Decimal | None) -> str:
    return NA if value is None else f"${value}"


def _p(value: float | None) -> str:
    return NA if value is None else f"p = {value:.4f}  (two-sided, exact)"


__all__ = ["NA", "render_cost", "render_stage_a", "render_stage_b"]
