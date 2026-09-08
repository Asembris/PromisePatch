"""What is about to be measured, said in full before the first call rather than after it.

A benchmark's identity is not something to reconstruct afterwards from a terminal buffer. Which
commit, which dataset, which prompts, which model, which prices, which thresholds -- all of it
is fixed the moment before any money is spent, printed where whoever started the run can read
it, and written into the run artifact. A result whose identity was assembled later is a result
somebody could have assembled differently.

The projection is deliberately labelled an estimate. The exact bytes each request will carry
are known here, because the prompt builders are production's own and are pure -- but how a
model's tokenizer counts those bytes is not, so what this prints is a bound and a rough range
rather than a figure dressed up as arithmetic. The output half *is* a real ceiling: every job
declares ``max_tokens``, so the most a split can emit is a number rather than a hope.

Nothing here calls anything. It reads the dataset, the prompt builders and the price catalog,
and it returns text.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from evals.budget import EvalBudget, ModelPrice, estimate_usd
from evals.cases import EvalJob, EvalSplit, WorkerCase, to_model_input
from evals.dataset import GoldDataset
from evals.prompts import prompt_identity
from evals.thresholds import ALL_THRESHOLDS
from promisepatch.semantic import SemanticJob
from promisepatch.semantic.jobs import JOB_SPECS
from promisepatch.semantic.prompts import build_system_instruction, build_user_content

CHARS_PER_TOKEN_LOW: Final = Decimal("3.0")
CHARS_PER_TOKEN_HIGH: Final = Decimal("4.5")
"""The band a character count is turned into a token range with.

Two numbers rather than one, because a single divisor would read as a calculation. English
prose and identifier-dense JSON do not tokenize at the same rate, and this request is both.
"""


@dataclass(frozen=True, slots=True)
class Projection:
    """A rough size for one split, from the exact bytes it would send.

    ``input_chars`` is exact: the system instruction plus the user content for every case that
    would be asked, built by production's own prompt code. Everything derived from it is an
    estimate and is named one.
    """

    calls: int
    input_chars: int
    max_output_tokens: int

    @property
    def input_tokens_low(self) -> int:
        return int(Decimal(self.input_chars) / CHARS_PER_TOKEN_HIGH)

    @property
    def input_tokens_high(self) -> int:
        return int(Decimal(self.input_chars) / CHARS_PER_TOKEN_LOW)


def project(dataset: GoldDataset) -> Projection:
    """Size one split by building every request it would send and measuring them.

    The requests are built and thrown away. That is the point: the bytes are known before the
    money is, so the projection is about this dataset and this prompt rather than about a
    remembered figure from another run.
    """
    calls = 0
    chars = 0
    output_ceiling = 0
    for case in dataset.cases:
        if isinstance(case, WorkerCase) and not case.asked:
            continue
        model_input = to_model_input(case)
        spec = JOB_SPECS[model_input.job.semantic_job]
        calls += 1
        chars += len(build_system_instruction(spec.job)) + len(
            build_user_content(model_input.request)
        )
        output_ceiling += spec.max_tokens
    return Projection(calls=calls, input_chars=chars, max_output_tokens=output_ceiling)


def eligible_calls(dataset: GoldDataset) -> dict[str, int]:
    """How many cases in this dataset a provider is allowed to be asked about, by job.

    The worker figure is production's own condition, not a count of worker cases: a sentence
    the deterministic lexicon reads is never asked about, and the difference between the two
    numbers is money not spent.
    """
    asked = sum(case.asked for case in dataset.worker)
    return {
        EvalJob.WORKER_SEMANTICS.value: asked,
        EvalJob.WORKER_SEMANTICS.value + ".never_asked": len(dataset.worker) - asked,
        EvalJob.CUSTOMER_INTENT.value: len(dataset.customer),
        "total": asked + len(dataset.customer),
    }


def render_preflight(
    *,
    full: GoldDataset,
    selected: GoldDataset,
    splits: Sequence[EvalSplit],
    git_sha: str | None,
    provider: str,
    model_id: str,
    region: str,
    price: ModelPrice | None,
    budget: EvalBudget,
    ceiling: EvalBudget,
    already_spent: object = None,
) -> str:
    """The block printed, and stored, before the first live call of a split."""
    manifest = full.manifest()
    eligible = eligible_calls(selected)
    projection = project(selected)
    lines = [
        "PREFLIGHT  -- benchmark identity, fixed before the first call",
        "",
        "  IDENTITY",
        f"    commit                     {git_sha or 'unknown'}",
        f"    dataset                    {manifest.name} v{manifest.version} "
        f"(schema {manifest.schema_version})",
        f"    dataset hash               {manifest.content_hash}",
        f"    cases                      {manifest.cases} "
        f"({manifest.by_job.get(EvalJob.WORKER_SEMANTICS.value)} worker, "
        f"{manifest.by_job.get(EvalJob.CUSTOMER_INTENT.value)} customer)",
        f"    split counts               "
        f"{manifest.by_split.get(EvalSplit.DEVELOPMENT.value)} development, "
        f"{manifest.by_split.get(EvalSplit.HOLDOUT.value)} holdout",
        "",
        "  PROMPTS  (system / tool schema, sha256 truncated)",
    ]
    for job in (SemanticJob.INTERPRET_UTTERANCE, SemanticJob.CLASSIFY_REPLY_INTENT):
        identity = prompt_identity(job)
        lines.append(
            f"    {identity.job.ljust(26)} {identity.system_hash} / {identity.schema_hash}"
            f"  tool {identity.tool_name}"
        )
    lines.extend(
        [
            "",
            "  MODEL",
            f"    provider                   {provider}",
            f"    model / inference profile  {model_id}",
            f"    region                     {region}",
        ]
    )
    if price is None:
        lines.append("    pricing                    UNAVAILABLE -- a dollar cap cannot start")
    else:
        lines.extend(
            [
                f"    pricing (estimate)         ${price.input_usd_per_million} in / "
                f"${price.output_usd_per_million} out per 1M tokens",
                f"    pricing snapshot           {price.snapshot_date.isoformat()}  {price.source}",
            ]
        )

    lines.extend(
        [
            "",
            "  THIS RUN",
            f"    split                      {', '.join(split.value for split in splits)}",
            f"    cases in split             {len(selected.cases)}",
            f"    model-eligible calls       {eligible['total']} "
            f"({eligible[EvalJob.WORKER_SEMANTICS.value]} worker, "
            f"{eligible[EvalJob.CUSTOMER_INTENT.value]} customer)",
            f"    never asked (0 calls)      "
            f"{eligible[EvalJob.WORKER_SEMANTICS.value + '.never_asked']} worker cases",
            "",
            "  CEILINGS  (in force for this run, across every live run of this benchmark)",
            f"    max logical calls          {ceiling.max_calls}",
            f"    max input tokens           {ceiling.max_input_tokens}",
            f"    max output tokens          {ceiling.max_output_tokens}",
            f"    max estimated spend        ${ceiling.max_estimated_usd}",
        ]
    )
    if already_spent is not None:
        lines.append(f"    already spent by earlier runs  {already_spent}")
    lines.extend(
        [
            "",
            "  ALLOWANCE FOR THIS RUN  (the ceiling, less what earlier runs used)",
            f"    max logical calls          {budget.max_calls}",
            f"    max input tokens           {budget.max_input_tokens}",
            f"    max output tokens          {budget.max_output_tokens}",
            f"    max estimated spend        ${budget.max_estimated_usd}",
            "",
            "  PROJECTION  (estimate; the exact request bytes are known, the tokenizer is not)",
            f"    logical calls              {projection.calls}",
            f"    request characters         {projection.input_chars}",
            f"    input tokens (rough)       ~{projection.input_tokens_low}-"
            f"{projection.input_tokens_high}",
            f"    output tokens (hard cap)   <= {projection.max_output_tokens} "
            f"(sum of each job's max_tokens)",
        ]
    )
    lines.append(f"    estimated spend            {_projected_cost(price, projection)}")
    lines.extend(["", "  THRESHOLD POLICY  (fixed before any result was seen)"])
    for threshold in ALL_THRESHOLDS:
        suffix = "  [approved for this benchmark]" if threshold.proposed else "  [authoritative]"
        lines.append(
            f"    {threshold.kind.value.ljust(8)} {threshold.name.ljust(38)} "
            f"{threshold.describe()}{suffix}"
        )
    lines.append("")
    return "\n".join(lines)


def _projected_cost(price: ModelPrice | None, projection: Projection) -> str:
    """A range, or the statement that there is no price to compute one from."""
    if price is None:
        return "unavailable (no verified price)"
    low = estimate_usd(
        price, input_tokens=projection.input_tokens_low, output_tokens=projection.max_output_tokens
    )
    high = estimate_usd(
        price,
        input_tokens=projection.input_tokens_high,
        output_tokens=projection.max_output_tokens,
    )
    if low is None or high is None:  # pragma: no cover - both token counts are always present
        return "unavailable"
    return (
        f"~${low.quantize(Decimal('0.000001'))}-${high.quantize(Decimal('0.000001'))} "
        f"(worst case: every job emits its whole output ceiling)"
    )


__all__ = [
    "CHARS_PER_TOKEN_HIGH",
    "CHARS_PER_TOKEN_LOW",
    "Projection",
    "eligible_calls",
    "project",
    "render_preflight",
]
