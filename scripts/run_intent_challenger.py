"""Challenge one model's customer-intent failures with another, in two bounded stages.

The question this answers is narrow on purpose: **does the challenger repair the specific
failure clusters that motivated challenging, without breaking what already worked, at a cost
that could justify using it for this one job?** Not "which model is better". Not "how does it
do on everything". A broad sweep would answer a question nobody asked and bill for it.

So the spending is staged. Stage A buys one call per failure of the model being challenged plus
one per matched control -- a set built by :func:`evals.challenger.select_stage_a` from stored
results, before the challenger has said anything. If it clears the materiality floor fixed in
:data:`evals.challenger.STAGE_A_MATERIALITY`, Stage B completes the rest of the customer
development split and the two models are compared over all of it. If it does not, Stage B is
refused and the remaining cases are never bought.

**The model being challenged is never re-run.** Its answers come from the result file it wrote,
which is what makes this comparison cost one model's calls rather than two.

**Worker cases cannot enter.** The dataset this hands the runner has no worker cases in it at
all, so "no worker call was made" is a property of the value passed in rather than a flag that
could be set wrongly.

**The holdout cannot enter.** Selection filters to the development split before anything else
looks at the results, and there is no flag here that opens the holdout.

**Code is frozen at the first call.** The result store refuses to continue a file whose header
names a different commit, so a tracked change between Stage A and Stage B stops the run rather
than blending two versions of the harness into one comparison.

Plan the set without calling anything::

    uv run python -m scripts.run_intent_challenger --stage a --model <id> --plan

Run Stage A::

    uv run python -m scripts.run_intent_challenger --live --provider bedrock --model <id> \\
        --stage a

Rebuild any report from what a run already paid for::

    uv run python -m scripts.run_intent_challenger --from-results .eval-results/<file>.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from evals.budget import (
    BudgetExhaustedError,
    BudgetGuard,
    EvalBudget,
    LedgerTotals,
    append_to_ledger,
    ledger_totals,
    price_for,
    remaining_budget,
    utc_now_iso,
)
from evals.cases import EvalSplit, ModelInput
from evals.challenger import (
    ChallengerError,
    SourceRun,
    StageAOutcome,
    StageASelection,
    build_stage_a,
    cluster_deltas,
    compare,
    customer_development,
    customer_totals,
    evaluate_materiality,
    latency_profile,
    pair_all,
    select_stage_a,
    usage_profile,
)
from evals.challenger_report import render_cost, render_stage_a, render_stage_b
from evals.dataset import GoldDataset, load_dataset, manifest_problems, validate_dataset
from evals.preflight import render_preflight
from evals.report import render
from evals.results import CaseResult, RunSummary
from evals.runner import LIVE_MODE, RunOutcome, StopPolicy, run_cases
from evals.store import ResultStore, RunHeader, read_run
from evals.summary import build_summary, git_sha, ledger_entry

from promisepatch.config import LlmProvider, Settings
from promisepatch.integrations.semantic_provider import build_semantic_provider
from promisepatch.semantic import SemanticJob, SemanticProvider

RESULTS_DIR = Path(".eval-results")
LEDGER = RESULTS_DIR / "cost-ledger.jsonl"
DEFAULT_SOURCE = RESULTS_DIR / "development-us.amazon.nova-2-lite-v1_0.jsonl"

CHALLENGER_CEILING = EvalBudget(
    max_calls=30,
    max_input_tokens=100_000,
    max_output_tokens=10_000,
    max_estimated_usd=Decimal("0.15"),
)
"""The whole challenger's allowance, across Stage A, Stage B and any resumed attempt.

Ceilings, not targets, and global rather than per invocation: the caps a run gets are these
less whatever the local cost ledger says this model already used. Expected use is well under
them. Raising one is an edit to this line in a commit somebody can read.
"""

MAX_PROVIDER_FAILURES = 3
"""Transport failures tolerated before the run stops rather than paying to rediscover them."""

FOCUS_TAGS = (
    "terse_assent",
    "indirect_refusal",
    "prompt_injection",
    "hedging",
    "question",
    "indirect_assent",
)
"""The clusters this challenge exists to ask about, marked in the report.

Named here rather than derived, because "which weaknesses motivated spending" is a statement
about the decision and not a property of the data. A tag the dataset does not carry simply
never appears.
"""


class ChallengerRefusedError(RuntimeError):
    """A precondition for spending is not met, so nothing was spent."""


# ------------------------------------------------------------------------ reading the source


def load_source(path: Path, dataset: GoldDataset) -> SourceRun:
    """Read the finished run being challenged, and refuse one measured against other labels."""
    if not path.exists():
        raise ChallengerRefusedError(
            f"{path} does not exist. The challenged model's stored results are the whole "
            f"input to this comparison; this command does not re-run it to produce them."
        )
    header, results = read_run(path)
    if header.dataset_hash != dataset.content_hash:
        raise ChallengerRefusedError(
            f"{path.name} was run against dataset hash {header.dataset_hash[:12]} and the "
            f"dataset on disk hashes to {dataset.content_hash[:12]}. Comparing two models "
            f"across two datasets would produce a number about neither."
        )
    return SourceRun(
        run_id=header.run_id,
        model_id=header.model_id,
        provider=header.provider,
        git_sha=header.git_sha,
        dataset_version=header.dataset_version,
        dataset_hash=header.dataset_hash,
        results=customer_development(results),
    )


def narrow(dataset: GoldDataset, case_ids: frozenset[str]) -> GoldDataset:
    """The dataset reduced to these customer cases and no worker case at all.

    The worker tuple is emptied rather than filtered. That is the structural guarantee behind
    "no worker call was made in this slice": the runner iterates what it is given, and it is
    given nothing to ask about.
    """
    return GoldDataset(
        version=dataset.version,
        worker=(),
        customer=tuple(
            case
            for case in dataset.customer
            if case.id in case_ids and case.split is EvalSplit.DEVELOPMENT
        ),
        provenance=dataset.provenance,
    )


def _prompt_identities() -> tuple[dict[str, str], ...]:
    from evals.prompts import prompt_identity

    return tuple(
        prompt_identity(job).as_payload()
        for job in (SemanticJob.INTERPRET_UTTERANCE, SemanticJob.CLASSIFY_REPLY_INTENT)
    )


def results_path(model: str) -> Path:
    return RESULTS_DIR / f"challenger-{model.replace(':', '_')}.jsonl"


def selection_path(model: str) -> Path:
    return RESULTS_DIR / f"challenger-set-{model.replace(':', '_')}.json"


def write_selection(path: Path, selection: StageASelection, model: str, region: str) -> None:
    """Persist the challenger set's identity before the first call, so it can be re-derived."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **selection.as_payload(),
        "challenger_model_id": model,
        "region": region,
        "git_sha": git_sha(),
        "prompts": [dict(entry) for entry in _prompt_identities()],
        "recorded_at": utc_now_iso(),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# -------------------------------------------------------------------------------- the run


async def run(namespace: argparse.Namespace) -> int:
    """Plan, preflight, and -- only with ``--live`` -- buy the stage that was asked for."""
    full = load_dataset()
    problems = [*validate_dataset(full), *manifest_problems(full, full.manifest())]
    if problems:
        raise ChallengerRefusedError(
            "the dataset does not agree with production, so nothing measured against it would "
            "mean anything:\n  - " + "\n  - ".join(problems)
        )

    source = load_source(Path(namespace.source), full)
    try:
        selection = select_stage_a(full, source)
    except ChallengerError as error:
        raise ChallengerRefusedError(str(error)) from error

    price = price_for(namespace.provider, namespace.model)
    if price is None:
        raise ChallengerRefusedError(
            f"{namespace.model!r} has no verified price in evals.budget.PRICES, so a dollar "
            f"ceiling cannot be enforced for it. Add it from a current published price list, "
            f"with the day it was read, before challenging with it."
        )

    stored = _stored_results(results_path(namespace.model))
    stage_a = build_stage_a(full, selection, source, stored)
    verdict = evaluate_materiality(stage_a)

    if namespace.stage == "b":
        _refuse_an_unearned_stage_b(stage_a, verdict)
        wanted = frozenset(case.id for case in full.customer if case.split is EvalSplit.DEVELOPMENT)
    else:
        wanted = selection.case_ids

    selected = narrow(full, wanted)
    spent = ledger_totals(LEDGER, mode=LIVE_MODE, model_id=namespace.model)
    budget = remaining_budget(CHALLENGER_CEILING, spent)

    preflight = render_preflight(
        full=full,
        selected=selected,
        splits=[EvalSplit.DEVELOPMENT],
        git_sha=git_sha(),
        provider=namespace.provider,
        model_id=namespace.model,
        region=namespace.region,
        price=price,
        budget=budget,
        ceiling=CHALLENGER_CEILING,
        already_spent=json.dumps(spent.as_payload(), sort_keys=True),
    )
    print(preflight)
    print(_selection_block(selection, stage_a, namespace.stage, len(stored)))
    write_selection(selection_path(namespace.model), selection, namespace.model, namespace.region)

    if namespace.plan or not namespace.live:
        print(
            "PLAN ONLY. No provider was constructed and nothing was spent.\n"
            f"The challenger set is written to {selection_path(namespace.model)} and is "
            f"reproducible from stored results with zero model calls.\n"
            "Add --live to buy the stage named above."
        )
        return 0

    _refuse_an_exhausted_allowance(budget, spent)

    settings = Settings(
        llm_provider=LlmProvider.BEDROCK,
        bedrock_model_id=namespace.model,
        aws_region=namespace.region,
    )
    provider = build_semantic_provider(settings)

    def factory(_: ModelInput) -> SemanticProvider:
        return provider

    guard = BudgetGuard(budget, price=price, live=True)
    header = RunHeader(
        run_id=_new_run_id(),
        started_at=utc_now_iso(),
        git_sha=git_sha(),
        dataset_version=full.version,
        dataset_hash=full.content_hash,
        prompts=tuple(dict(entry) for entry in _prompt_identities()),
        provider=provider.name,
        model_id=namespace.model,
        mode=LIVE_MODE,
        splits=(EvalSplit.DEVELOPMENT.value,),
        region=namespace.region,
        pricing_snapshot=price.snapshot_date.isoformat(),
    )
    store = ResultStore(results_path(namespace.model), header)
    (RESULTS_DIR / f"{store.header.run_id}-challenger-preflight.txt").write_text(
        preflight, encoding="utf-8"
    )
    if store.existing:
        print(
            f"\nResuming {store.path}: {len(store.existing)} case(s) already answered and paid "
            f"for. They are read back, not asked again."
        )

    def persist(result: CaseResult) -> None:
        """A refused answer is a fact about the model and is kept; an outage is not."""
        if result.provider_error:
            return
        store.record(result)

    stopped_by_budget: str | None = None
    try:
        outcome = await run_cases(
            selected,
            factory,
            guard=guard,
            provider_name=provider.name,
            mode=LIVE_MODE,
            expected_model_id=namespace.model,
            reuse=store.existing,
            on_result=persist,
            stop=StopPolicy(
                max_provider_failures=MAX_PROVIDER_FAILURES, stop_on_safety_violation=True
            ),
        )
    except BudgetExhaustedError as error:
        stopped_by_budget = str(error)
        print(f"\nBUDGET REACHED: {error}", file=sys.stderr)
        outcome = await _rescore_from_store(store.path, guard, provider.name, namespace.model, full)

    summary = _summarise(full, outcome, store.header.run_id, budget, stopped_by_budget)
    append_to_ledger(LEDGER, ledger_entry(summary))
    return _emit(full, source, summary, namespace, price)


def _new_run_id() -> str:
    from evals.runner import new_run_id

    return new_run_id()


def _stored_results(path: Path) -> tuple[CaseResult, ...]:
    """What this challenger has already been asked, or nothing. Never a reason to re-ask."""
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return ()
    _, results = read_run(path)
    return results


def _refuse_an_unearned_stage_b(stage_a: StageAOutcome, verdict: object) -> None:
    """Stage B is opened by Stage A's result, not by a flag somebody typed."""
    materiality = evaluate_materiality(stage_a)
    if materiality.passed:
        return
    if not stage_a.complete:
        raise ChallengerRefusedError(
            "Stage A has no reading for every selected case, so it has decided nothing. Run "
            "--stage a to completion first; Stage B is not opened on a partial result."
        )
    raise ChallengerRefusedError(
        "Stage A did not clear the materiality floor, so the rest of the split is not bought: "
        f"{', '.join(materiality.failed)}. HAIKU TARGETED CHALLENGE NOT MATERIAL -- STOPPED "
        "EARLY is a valid outcome, and this is it."
    )


def _refuse_an_exhausted_allowance(budget: EvalBudget, spent: LedgerTotals) -> None:
    """A run with nothing left to spend does not start and pretend to measure something."""
    if budget.max_calls == 0 or budget.max_estimated_usd == 0:
        raise ChallengerRefusedError(
            f"the challenger ceiling is used up: {spent.calls} call(s) and "
            f"${spent.estimated_usd} already recorded in {LEDGER}. Raising it is a deliberate "
            f"edit to CHALLENGER_CEILING, not something this command does."
        )


async def _rescore_from_store(
    path: Path, guard: BudgetGuard, provider_name: str, model_id: str, full: GoldDataset
) -> RunOutcome:
    """Rebuild an outcome from what is on disk, without asking a provider anything."""
    _, results = read_run(path)
    answered = {result.case_id for result in results}
    return await run_cases(
        narrow(full, frozenset(answered)),
        _never_called,
        guard=guard,
        provider_name=provider_name,
        mode=LIVE_MODE,
        expected_model_id=model_id,
        reuse=results,
    )


def _never_called(_: ModelInput) -> SemanticProvider:  # pragma: no cover - reuse covers every case
    raise AssertionError("rebuilding a stopped run must not ask a provider anything")


def _summarise(
    full: GoldDataset,
    outcome: RunOutcome,
    run_id: str,
    budget: EvalBudget,
    stopped_by_budget: str | None,
) -> RunSummary:
    summary = build_summary(
        full,
        outcome,
        mode=LIVE_MODE,
        splits=[EvalSplit.DEVELOPMENT],
        run_id=run_id,
        budget=budget,
    )
    if stopped_by_budget is None:
        return summary
    operations = {**summary.operations, "stopped": stopped_by_budget}
    return summary.model_copy(update={"operations": operations})


def _selection_block(
    selection: StageASelection, stage_a: StageAOutcome, stage: str | None, stored: int
) -> str:
    """What this invocation is about to buy, named before it buys it."""
    lines = [
        "CHALLENGER SET  -- derived from stored results, before any challenger call",
        f"  selection algorithm          v{selection.algorithm_version}",
        f"  source run                   {selection.source_run_id} ({selection.source_model_id})",
        f"  source results sha256        {selection.source_results_sha[:16]}...",
        f"  failures challenged          {len(selection.pairs)}",
        f"  stage A cases                {len(selection.case_ids)}",
        f"  stage requested              {stage or 'rebuild'}",
        f"  challenger readings on disk  {stored}  (never bought twice)",
        f"  stage A complete             {stage_a.complete}",
        "",
        "  FAILURE -> MATCHED CONTROL",
    ]
    for pair in selection.pairs:
        note = "" if pair.same_class else "  [cross-class fallback]"
        shared = ",".join(pair.shared_tags) or "-"
        lines.append(
            f"    {pair.failure_case_id.ljust(34)} ({pair.failure_gold} read as "
            f"{pair.failure_predicted})"
        )
        lines.append(f"      -> {pair.control_case_id.ljust(32)} shared tags {shared}{note}")
    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------------------ reporting


def _emit(
    full: GoldDataset,
    source: SourceRun,
    summary: RunSummary,
    namespace: argparse.Namespace,
    price: object,
) -> int:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{summary.run_id}-challenger.json").write_text(
        json.dumps(summary.as_payload(), indent=2), encoding="utf-8"
    )
    if namespace.json:
        print(json.dumps(summary.as_payload(), indent=2))
        return 0
    return report(full, source, summary.results, namespace)


def report(
    full: GoldDataset,
    source: SourceRun,
    results: Sequence[CaseResult],
    namespace: argparse.Namespace,
    summary: RunSummary | None = None,
) -> int:
    """Print whichever report the readings on disk can support, and name the outcome."""
    selection = select_stage_a(full, source)
    stage_a = build_stage_a(full, selection, source, results)
    verdict = evaluate_materiality(stage_a)
    print("\n" + render_stage_a(stage_a, verdict))

    development = frozenset(
        case.id for case in full.customer if case.split is EvalSplit.DEVELOPMENT
    )
    answered = {result.case_id for result in results}
    complete = development <= answered

    if complete:
        paired = pair_all(full, source, results)
        print(
            render_stage_b(
                challenger_totals=customer_totals(full, results),
                source_totals=customer_totals(full, source.results),
                paired=paired,
                totals=compare(paired),
                clusters=cluster_deltas(paired),
                focus=FOCUS_TAGS,
            )
        )
        if summary is not None:
            print(render(summary))
        print(_cost_block(full, source, results, namespace))
    else:
        print(_cost_block(full, source, results, namespace))
        print(
            f"STAGE B NOT OPENED. {len(development - answered)} customer development case(s) "
            f"have no challenger reading."
        )

    print(_verdict(stage_a, verdict, complete, summary))
    return 0 if verdict.passed else 1


def _cost_block(
    full: GoldDataset,
    source: SourceRun,
    results: Sequence[CaseResult],
    namespace: argparse.Namespace,
) -> str:
    shared = {result.case_id for result in results}
    source_subset = tuple(result for result in source.results if result.case_id in shared)
    return render_cost(
        source=usage_profile(full, source_subset, source.model_id),
        challenger=usage_profile(full, results, namespace.model),
        source_price=price_for(source.provider, source.model_id),
        challenger_price=price_for(namespace.provider, namespace.model),
        source_latency=latency_profile(source_subset, "latency_ms"),
        challenger_latency=latency_profile(results, "latency_ms"),
    )


def _verdict(
    stage_a: StageAOutcome, verdict: object, complete: bool, summary: RunSummary | None
) -> str:
    """One sentence naming what this run decided, in the vocabulary the slice is judged in."""
    materiality = evaluate_materiality(stage_a)
    if stage_a.authority_violations:
        return (
            "\nSEMANTIC SAFETY GATE FAILED - REVIEW REQUIRED\n"
            "  A label outside the closed non-authoritative set was accepted. This is an "
            "architecture or evaluator question first, not a model one."
        )
    if not materiality.passed:
        if not stage_a.complete:
            return "\nSTAGE A INCOMPLETE - NOTHING DECIDED"
        return (
            "\nTARGETED CHALLENGER STOPPED - CHALLENGER NOT MATERIAL\n"
            f"  failed: {', '.join(materiality.failed)}\n"
            "  Stage B was not opened and the remaining cases were not bought."
        )
    if not complete:
        return (
            "\nSTAGE A PASSED - STAGE B AUTHORISED\n"
            "  Run --stage b to complete the customer development split."
        )
    failed_quality = _failed_customer_gates(summary)
    if failed_quality:
        return (
            "\nCHALLENGER CUSTOMER-INTENT GATE FAILED - ARCHITECTURE REVIEW REQUIRED\n"
            f"  failed: {', '.join(failed_quality)}"
        )
    return (
        "\nCHALLENGER CUSTOMER-INTENT QUALITY GATE PASSED - COST DECISION REQUIRED\n"
        "  Development evidence only. No production routing changes here, and the holdout "
        "stays unopened."
    )


def _failed_customer_gates(summary: RunSummary | None) -> tuple[str, ...]:
    if summary is None:
        return ()
    return tuple(
        gate.name
        for gate in summary.gates
        if gate.kind == "quality" and gate.status == "fail" and gate.name.startswith("customer")
    )


# ---------------------------------------------------------- rebuilding, with no model


def rebuild(namespace: argparse.Namespace) -> int:
    """Re-render from stored results. Constructs no client, spends nothing."""
    path = Path(namespace.from_results)
    header, results = read_run(path)
    full = load_dataset()
    if header.dataset_hash != full.content_hash:
        raise ChallengerRefusedError(
            f"{path.name} was run against dataset hash {header.dataset_hash[:12]} and the "
            f"dataset on disk hashes to {full.content_hash[:12]}."
        )
    source = load_source(Path(namespace.source), full)
    namespace.model = header.model_id or namespace.model
    namespace.provider = header.provider
    price = price_for(header.provider, header.model_id)
    guard = BudgetGuard(EvalBudget(), price=price, live=False)
    outcome = asyncio.run(
        _rescore_from_store(path, guard, header.provider, header.model_id or "", full)
    )
    for result in results:
        guard.spend.attempts += result.attempts or 0
        if result.input_tokens is not None or result.output_tokens is not None:
            guard.spend.tokens_reported = True
            guard.spend.input_tokens += result.input_tokens or 0
            guard.spend.output_tokens += result.output_tokens or 0
        if result.estimated_usd is not None:
            guard.spend.estimated_usd = (guard.spend.estimated_usd or Decimal(0)) + Decimal(
                result.estimated_usd
            )
    guard.spend.calls = sum(1 for result in results if result.attempts is not None)
    summary = build_summary(
        full,
        outcome,
        mode=header.mode,
        splits=[EvalSplit.DEVELOPMENT],
        run_id=header.run_id,
        budget=CHALLENGER_CEILING,
        generated_at=header.started_at,
    )
    summary = summary.model_copy(update={"model_id": header.model_id, "provider": header.provider})
    code = report(full, source, results, namespace, summary)
    print(f"\nRebuilt from {path} with zero provider calls.")
    return code


# ------------------------------------------------------------------------------ the CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_intent_challenger",
        description=(
            "Challenge a model's customer-intent failures with another model, in two bounded "
            "stages. Spending requires --live, --provider and --model, all given explicitly."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "actually call the challenger. Without it this prints the plan, constructs no "
            "client and spends nothing."
        ),
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="write the challenger set and stop, even with --live",
    )
    parser.add_argument(
        "--provider",
        choices=[LlmProvider.BEDROCK.value],
        help="which provider to call. No default: a comparison names what it measured.",
    )
    parser.add_argument(
        "--model",
        help=(
            "the challenger's model or cross-Region inference profile id. No default, and "
            "never taken from settings."
        ),
    )
    parser.add_argument("--region", default="us-east-1", help="the Region to call Bedrock in")
    parser.add_argument(
        "--stage",
        choices=["a", "b"],
        help=(
            "a: the failures and their matched controls. b: the rest of the customer "
            "development split, opened only by a Stage A that cleared materiality."
        ),
    )
    parser.add_argument(
        "--source",
        default=str(DEFAULT_SOURCE),
        help="the stored results of the model being challenged. It is never re-run.",
    )
    parser.add_argument(
        "--from-results",
        help="rebuild the reports from a stored challenger run instead of calling anything",
    )
    parser.add_argument("--json", action="store_true", help="emit the machine-readable summary")
    return parser


def _validate(namespace: argparse.Namespace) -> None:
    """Refuse an incoherent invocation before anything is loaded, let alone called."""
    if namespace.from_results:
        if not namespace.provider:
            namespace.provider = LlmProvider.BEDROCK.value
        return
    if not namespace.stage:
        raise ChallengerRefusedError("--stage is required: a or b, never both")
    if namespace.live and not (namespace.provider and namespace.model):
        raise ChallengerRefusedError(
            "--live requires --provider and --model. Neither is defaulted, and neither is read "
            "from the environment: a run that inherited its model could measure one nobody "
            "chose."
        )
    if not namespace.provider:
        namespace.provider = LlmProvider.BEDROCK.value
    if not namespace.model:
        raise ChallengerRefusedError(
            "--model is required, even for a plan: the preflight names what it would measure"
        )


def main(argv: Sequence[str] | None = None) -> int:
    namespace = build_parser().parse_args(argv)
    try:
        _validate(namespace)
        if namespace.from_results:
            return rebuild(namespace)
        return asyncio.run(run(namespace))
    except (ChallengerRefusedError, ChallengerError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
