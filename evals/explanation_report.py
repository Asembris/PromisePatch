"""What a run says to a person, and what a plan says before there is a run.

Two outputs, and the shape of both is the argument of the gate.

**The report never averages a safety failure with a score.** Structural gates, semantic gates and
quality targets are three sections in that order, and the acceptance rates sit above all of them
so nobody reads a quality mean without seeing how many passages it was computed over. A model
whose prose is excellent on the third of cases it did not get refused on is not a model with
excellent prose.

**The plan spends nothing and says so.** It prints the dataset identity, the split balance, the
model under test, the judge, the one-call rule, the derived ceilings and the projected spend --
and it constructs no client and makes no call to do it. It prints no holdout passage: counts and
case ids are assertable, prose is sealed, and a preflight that dumped the holdout would have
unsealed it in the terminal of the person about to run against it.
"""

from __future__ import annotations

from collections.abc import Sequence

from evals.budget import NEMOTRON_3_SUPER
from evals.cases import EvalSplit
from evals.explanation_budget import DerivedCeiling, judge_ceiling, nova_ceiling
from evals.explanation_cases import ExplanationFamily
from evals.explanation_dataset import (
    CASES_PER_FAMILY,
    DATASET_NAME,
    DEVELOPMENT_PER_FAMILY,
    HOLDOUT_PER_FAMILY,
    ExplanationDataset,
)
from evals.explanation_judge import JUDGE_MODEL_ID, JUDGE_PROVIDER
from evals.explanation_metrics import GateOutcome
from evals.explanation_runner import ExplanationRunSummary
from evals.explanation_thresholds import (
    MAX_PRODUCTION_REPAIRS_BEFORE_HOLDOUT,
    RUBRIC_VERSION,
    GateKind,
)

SYSTEM_UNDER_TEST_PROVIDER = "bedrock"
SYSTEM_UNDER_TEST_MODEL = "us.amazon.nova-2-lite-v1:0"
"""The selected production semantic runtime. Named here so a plan states what it would call."""

WIDTH = 78


def _rule(title: str) -> str:
    return f"\n{title}\n{'-' * min(WIDTH, len(title))}"


def _rate(value: float | None) -> str:
    return "--" if value is None else f"{value * 100:.0f}%"


def _mean(value: float | None) -> str:
    return "not scored" if value is None else f"{value:.2f}"


def plan(dataset: ExplanationDataset, splits: Sequence[EvalSplit] | None = None) -> str:
    """The zero-call preflight. Constructs no client, calls no model, prints no holdout prose."""
    selected = dataset.split(splits)
    development = dataset.split([EvalSplit.DEVELOPMENT])
    nova = nova_ceiling(development.cases)
    judge = judge_ceiling(development.cases)
    holdout = sum(case.split is EvalSplit.HOLDOUT for case in dataset.cases)

    lines = [
        "P4.8 EXPLANATION QUALITY -- PLAN",
        _rule("DATASET"),
        f"  {DATASET_NAME}",
        f"  version        {dataset.version}",
        f"  hash           {dataset.content_hash}",
        f"  total          {len(dataset.cases)}",
        f"  development    {sum(c.split is EvalSplit.DEVELOPMENT for c in dataset.cases)}",
        f"  holdout        {holdout} SEALED",
        f"  families       {len(ExplanationFamily)}, {CASES_PER_FAMILY} each "
        f"({DEVELOPMENT_PER_FAMILY} development + {HOLDOUT_PER_FAMILY} holdout)",
        f"  selected       {len(selected.cases)} case(s)",
        _rule("SYSTEM UNDER TEST"),
        f"  provider       {SYSTEM_UNDER_TEST_PROVIDER}",
        f"  model          {SYSTEM_UNDER_TEST_MODEL}",
        _rule("JUDGE"),
        f"  provider       {JUDGE_PROVIDER}",
        f"  model          {JUDGE_MODEL_ID}",
        f"  rubric         v{RUBRIC_VERSION}",
        "  strategy       one structured JudgeVerdict per accepted explanation",
        "  fan-out        none: no per-dimension metric, no framework default judge",
        _rule("DEVELOPMENT CEILINGS"),
        *_ceiling_lines("nova", nova),
        *_ceiling_lines("judge", judge),
        _rule("USD ACCOUNTING"),
        f"  nova           priced, projected ${nova.projected_usd} "
        f"(ceiling ${nova.max_estimated_usd})",
        f"  nvidia judge   {NEMOTRON_3_SUPER.mode.value} billing; commercial USD not modelled",
        f"  repairs        at most {MAX_PRODUCTION_REPAIRS_BEFORE_HOLDOUT} bounded production "
        f"repair before holdout",
        _rule("THIS INVOCATION"),
        "  clients constructed          0",
        "  model calls                  0",
        "  judge calls                  0",
        "  holdout passages printed     0",
    ]
    return "\n".join(lines) + "\n"


def _ceiling_lines(label: str, ceiling: DerivedCeiling) -> list[str]:
    return [
        f"  {label:<14} provider {ceiling.provider}",
        f"    model                {ceiling.model_id}",
        f"    logical calls        {ceiling.logical_calls}",
        f"    provider attempts    {ceiling.provider_attempts}",
        f"    input tokens         {ceiling.max_input_tokens}",
        f"    output tokens        {ceiling.max_output_tokens}",
        f"    derived from         {ceiling.measured_prompt_characters} prompt characters",
    ]


def render(summary: ExplanationRunSummary) -> str:
    """One run, in the order a person reads it: what was shown, what was unsafe, how good."""
    lines = [
        f"P4.8 EXPLANATION QUALITY -- {summary.mode.upper()}  {summary.run_id}",
        f"  dataset        {summary.dataset_name} v{summary.dataset_version} "
        f"{summary.dataset_hash[:12]}",
        f"  splits         {', '.join(summary.splits)}",
        f"  under test     {summary.generation_provider}"
        f"{'' if summary.generation_model_id is None else '/' + summary.generation_model_id}",
        f"  judge          {summary.judge_provider or 'none'}"
        f"{'' if summary.judge_model_id is None else '/' + summary.judge_model_id}"
        f"  rubric v{summary.rubric_version}",
        *_acceptance_lines(summary),
        *_hard_lines(summary),
        *_semantic_lines(summary),
        *_quality_lines(summary),
        *_family_lines(summary),
        *_cost_lines(summary),
        *_gate_lines(summary.gates),
        "",
        f"GATE STATUS: {summary.gate_status.upper()}",
    ]
    if summary.judging_stopped is not None:
        lines.append(f"SUBJECTIVE QUALITY INCOMPLETE: {summary.judging_stopped}")
    lines.append(
        "These are hand-authored software-evaluation fixtures. Nothing here is evidence of "
        "business impact."
    )
    return "\n".join(lines) + "\n"


def _acceptance_lines(summary: ExplanationRunSummary) -> list[str]:
    rates = summary.acceptance
    return [
        _rule("WHOSE WORDS WERE SHOWN"),
        f"  accepted model verbalisations  {_rate(rates.accepted_model_verbalisation_rate)}  "
        f"({rates.accepted}/{rates.cases})",
        f"  validator rejections           {_rate(rates.validator_rejection_rate)}  "
        f"({rates.validator_rejected}/{rates.cases})",
        f"  provider failures              {_rate(rates.provider_failure_rate)}  "
        f"({rates.provider_failures}/{rates.cases})",
        f"  deterministic fallbacks        {_rate(rates.fallback_rate)}  "
        f"({rates.fallbacks}/{rates.cases})",
        "  Quality below is computed over accepted model prose only.",
    ]


def _hard_lines(summary: ExplanationRunSummary) -> list[str]:
    hard = summary.hard
    lines = [
        _rule("STRUCTURAL SAFETY -- production's own validator, zero tolerance"),
        f"  schema-invalid accepted            {hard.schema_invalid_accepted}",
        f"  unknown fact refs accepted         {hard.unknown_fact_refs_accepted}",
        f"  missing required refs accepted     {hard.missing_required_fact_refs_accepted}",
        f"  word cap violations accepted       {hard.word_cap_violations_accepted}",
        f"  unsupported digit claims accepted  {hard.unsupported_digit_claims_accepted}",
        f"  deterministic fallback failures    {hard.fallback_failures}",
    ]
    lines.extend(f"    {problem}" for problem in summary.fallback_problems)
    return lines


def _semantic_lines(summary: ExplanationRunSummary) -> list[str]:
    semantic = summary.semantic
    return [
        _rule("SEMANTIC SAFETY -- one judge verdict per passage, zero tolerance"),
        f"  outcome contradictions             {semantic.outcome_contradictions}",
        f"  authority contradictions           {semantic.authority_contradictions}",
        f"  unsupported entity or option       {semantic.unsupported_entity_or_option_claims}",
        f"  unsupported guarantees             {semantic.unsupported_guarantees}",
        f"  unsupported quantities in words    {semantic.unsupported_quantity_in_words}",
        f"  passages judged                    {semantic.judged}",
    ]


def _quality_lines(summary: ExplanationRunSummary) -> list[str]:
    quality = summary.quality
    return [
        _rule("QUALITY -- accepted model prose only"),
        f"  faithfulness         {_mean(quality.faithfulness_mean)}",
        f"  causal completeness  {_mean(quality.causal_completeness_mean)}",
        f"  clarity              {_mean(quality.clarity_mean)}",
        f"  brevity              {_mean(quality.brevity_mean)}",
        f"  speech naturalness   {_mean(quality.speech_naturalness_mean)}",
        f"  faithfulness below 3 {quality.faithfulness_below_three}",
        f"  scored               {quality.scored}",
    ]


def _family_lines(summary: ExplanationRunSummary) -> list[str]:
    lines = [
        _rule("BY FAMILY"),
        f"  {'family':<24}{'acc':>5}{'safe':>6}{'faith':>7}{'compl':>7}{'clar':>6}"
        f"{'brev':>6}{'voice':>7}",
    ]
    for metrics in summary.families:
        quality = metrics.quality
        lines.append(
            f"  {metrics.family.value:<24}"
            f"{metrics.acceptance.accepted:>3}/{metrics.acceptance.cases:<1}"
            f"{metrics.semantic.total:>6}"
            f"{_mean(quality.faithfulness_mean):>7}"
            f"{_mean(quality.causal_completeness_mean):>7}"
            f"{_mean(quality.clarity_mean):>6}"
            f"{_mean(quality.brevity_mean):>6}"
            f"{_mean(quality.speech_naturalness_mean):>7}"
        )
    return lines


def _cost_lines(summary: ExplanationRunSummary) -> list[str]:
    cost = summary.cost
    generation, judge = summary.generation_usage, summary.judge_usage
    return [
        _rule("COST -- generation and judging never share a counter"),
        "  generation",
        f"    logical calls      {generation.logical_calls}",
        f"    provider attempts  {generation.provider_attempts}",
        f"    input tokens       {generation.input_tokens if generation.input_tokens else '--'}",
        f"    output tokens      {generation.output_tokens if generation.output_tokens else '--'}",
        f"    estimated USD      "
        f"{'--' if cost.generation_usd is None else '$' + str(cost.generation_usd)}",
        "  judge",
        f"    logical calls      {judge.logical_calls}",
        f"    provider attempts  {judge.provider_attempts}",
        f"    input tokens       {judge.input_tokens if judge.input_tokens else '--'}",
        f"    output tokens      {judge.output_tokens if judge.output_tokens else '--'}",
        f"    billing mode       {cost.judge_billing_mode}",
        "    known USD          not modelled -- no published per-token price",
        f"  total known USD      {'--' if cost.known_usd is None else '$' + str(cost.known_usd)}",
    ]


def _gate_lines(gates: Sequence[GateOutcome]) -> list[str]:
    lines: list[str] = []
    for kind, title in (
        (GateKind.STRUCTURAL, "STRUCTURAL GATES"),
        (GateKind.SEMANTIC, "SEMANTIC GATES"),
        (GateKind.QUALITY, "QUALITY TARGETS"),
    ):
        selected = [gate for gate in gates if gate.kind is kind]
        if not selected:  # pragma: no cover - every kind has at least one rule
            continue
        lines.append(_rule(title))
        lines.extend(
            f"  [{gate.status:^12}] {gate.name:<46} {gate.required:>8}  {gate.observed or '--'}"
            for gate in selected
        )
    return lines


__all__ = [
    "SYSTEM_UNDER_TEST_MODEL",
    "SYSTEM_UNDER_TEST_PROVIDER",
    "plan",
    "render",
]
