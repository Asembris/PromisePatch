"""Run the semantic evaluation against a real model. The only thing here that can spend money.

This file exists because of two import-linter contracts that must both keep holding:
``promisepatch`` may not import ``evals``, and ``evals`` may not import an AWS SDK or
``promisepatch.integrations``. So the place where a gold dataset meets a Bedrock client cannot
be inside either of them. It is here, outside both, and it is orchestration only -- it decides
nothing about what a good answer is, computes no metric and owns no threshold. Every number in
its output is produced by :mod:`evals`.

**Spending is opt-in, explicitly and unmistakably, and ``--live`` is not the opt-in.** The flag
names a code path. Being charged for inference additionally takes a split-bound authorisation
phrase typed at the invocation -- see :mod:`evals.authorisation` -- because a flag a test can
pass is a flag a test did pass: a case asserting that an unpriced model is refused once became
a live benchmark the day that model was priced, and the only thing that stopped it was AWS
denying access. ``--provider`` and ``--model`` are required with ``--live`` and neither is
defaulted. Nothing here reads ``PP_LLM_PROVIDER`` to decide whether to call a model, and
nothing reads the authorisation from the environment or from ``.env``. A process running under
pytest cannot construct a paid provider at all, whatever it was handed.

**The model is named, never inherited.** ``Settings.bedrock_model_id`` defaults to a Claude
model, which is not the model this benchmark is about. The id is passed on the command line,
checked against the price catalog before a client is opened, and checked again against what
each answer's telemetry reports -- so a run cannot quietly measure a different model than the
one it names, in either direction.

**The ceiling is global, not per invocation.** A budget that reset with each command would let
two splits each spend the whole allowance. The caps for a run are the global ones less whatever
the local cost ledger says earlier live runs already used.

**A completed case is never bought twice.** Every result is written to a JSONL file as it
happens. Re-running the same split appends to that file and skips what it already contains, and
``--from-results`` rebuilds the summary and the report from it with no provider in the room --
so a formatting failure costs nothing and a lost terminal costs nothing.

Run the development split::

    uv run python scripts/run_semantic_benchmark.py --live \\
        --provider bedrock --model us.amazon.nova-2-lite-v1:0 --split development \\
        --authorise-paid-inference AUTHORISE-PAID-INFERENCE-SPLIT-DEVELOPMENT

Rebuild a report from what a run already paid for::

    uv run python scripts/run_semantic_benchmark.py --from-results .eval-results/<file>.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path

from evals.authorisation import (
    SpendAuthorisation,
    SpendNotAuthorisedError,
    SpendScope,
    authorise,
    refuse_real_inference_under_test,
    required_phrase,
)
from evals.budget import (
    BudgetExhaustedError,
    BudgetGuard,
    EvalBudget,
    LedgerTotals,
    append_to_ledger,
    billing_for,
    ledger_totals,
    price_for,
    remaining_budget,
    utc_now_iso,
)
from evals.cases import EvalSplit, ModelInput
from evals.dataset import GoldDataset, load_dataset, manifest_problems, validate_dataset
from evals.preflight import render_preflight
from evals.report import render
from evals.results import CaseResult, ExecutionStatus, RunSummary
from evals.runner import LIVE_MODE, RunOutcome, StopPolicy, new_run_id, run_cases
from evals.store import (
    ProviderFailureLog,
    ProviderFailureRecord,
    ResultStore,
    RunHeader,
    StoreError,
    read_run,
)
from evals.summary import build_summary, dataset_identity, git_sha, ledger_entry
from evals.thresholds import SAFETY_GATES

from promisepatch.config import LlmProvider, Settings
from promisepatch.semantic import SemanticProvider

RESULTS_DIR = Path(".eval-results")
LEDGER = RESULTS_DIR / "cost-ledger.jsonl"

GLOBAL_CEILING = EvalBudget(
    max_calls=110,
    max_input_tokens=300_000,
    max_output_tokens=30_000,
    max_estimated_usd=Decimal("0.20"),
)
"""The whole benchmark's allowance, across every live run of it on this machine.

Ceilings, not targets. A benchmark that reaches one stops; it does not warn and continue, and
it does not raise its own bound. Raising these is a conscious act by whoever runs it, made by
editing this line in a commit somebody can read.
"""

MAX_PROVIDER_FAILURES = 3
"""Transport failures tolerated in one split before it stops.

Not a retry policy -- the SDK has one and the semantic boundary has its own single corrective
retry. This is the bound on how long a benchmark keeps paying to discover that infrastructure
is not answering.
"""

SPLIT_SCOPES = {
    EvalSplit.DEVELOPMENT.value: SpendScope.SPLIT_DEVELOPMENT,
    EvalSplit.HOLDOUT.value: SpendScope.SPLIT_HOLDOUT,
}
"""Which authorisation each split costs. Approving one does not approve the other."""


class BenchmarkRefusedError(RuntimeError):
    """A precondition for spending money is not met, so nothing was spent."""


# ------------------------------------------------------------------- the live provider


type ProviderBuilder = Callable[[Settings, SpendAuthorisation], SemanticProvider]
"""How this command gets something that can be charged for. A parameter, never a branch."""


def bedrock_provider(settings: Settings, authorisation: SpendAuthorisation) -> SemanticProvider:
    """Production's own provider factory, read once, behind the guards that gate paid inference.

    One provider for the whole run rather than one per case: opening a client per case would
    resolve the credential chain fifty times and measure connection setup as model latency.
    It is production's ``build_semantic_provider``, so the request this benchmark sends is the
    request the worker sends -- prompts, tool schema, forced tool choice, temperature, output
    ceiling, corrective retry and all.

    Two things stand in front of it. The authorisation is an argument, so this cannot be
    reached without one having been produced from a phrase somebody typed. And the test
    interlock is checked on the line before the import, so a pytest process is refused here
    whatever flags, credentials or model access it happens to have -- which is the guard that
    would have stopped the accident that made this module take arguments at all.
    """
    refuse_real_inference_under_test(authorisation.scope)
    from promisepatch.integrations.semantic_provider import build_semantic_provider

    return build_semantic_provider(settings)


# ------------------------------------------------------------------------- the run


async def run_live(
    namespace: argparse.Namespace,
    *,
    provider_builder: ProviderBuilder = bedrock_provider,
) -> int:
    """Preflight, then -- only with an authorisation -- the split, one case at a time.

    ``provider_builder`` is the seam a test uses. It defaults to the one thing here that can
    be charged for, and a test that needs the orchestration passes one that cannot.
    """
    splits = [EvalSplit(namespace.split)]
    full = load_dataset()
    problems = [*validate_dataset(full), *manifest_problems(full, full.manifest())]
    if problems:
        raise BenchmarkRefusedError(
            "the dataset does not agree with production, so nothing measured against it would "
            "mean anything:\n  - " + "\n  - ".join(problems)
        )
    selected = full.split(splits)

    price = price_for(namespace.provider, namespace.model)
    if price is None:
        raise BenchmarkRefusedError(
            f"{namespace.model!r} has no verified price in evals.budget.PRICES, so a dollar "
            f"ceiling cannot be enforced for it. Add it from a current published price list, "
            f"with the day it was read, before benchmarking it."
        )

    spent = ledger_totals(LEDGER, mode=LIVE_MODE, model_id=namespace.model)
    budget = remaining_budget(GLOBAL_CEILING, spent)

    preflight = render_preflight(
        full=full,
        selected=selected,
        splits=splits,
        git_sha=git_sha(),
        provider=namespace.provider,
        model_id=namespace.model,
        region=namespace.region,
        billing=billing_for(namespace.provider, namespace.model),
        budget=budget,
        ceiling=GLOBAL_CEILING,
        already_spent=json.dumps(spent.as_payload(), sort_keys=True),
    )
    print(preflight)

    if not namespace.live:
        print(
            "DRY RUN. No provider was constructed and nothing was spent.\n"
            f"Running this split takes --live and --authorise-paid-inference "
            f"{required_phrase(SPLIT_SCOPES[namespace.split])}."
        )
        return 0

    _refuse_an_exhausted_allowance(budget, spent)
    if namespace.split == EvalSplit.HOLDOUT.value and not namespace.development_passed:
        raise BenchmarkRefusedError(
            "the holdout is opened once, after the development split has passed every gate. "
            "Pass --development-passed to say that it did, or run --split development first."
        )

    # Re-demanded at the point of spending rather than trusted from the parse: the split about
    # to be bought must be the one the phrase named.
    authorisation: SpendAuthorisation = namespace.authorisation
    authorisation.require(SPLIT_SCOPES[namespace.split])
    print(
        f"\nSPEND AUTHORISED  scope {authorisation.scope.value}  "
        f"granted {authorisation.granted_at}  "
        f"caps {authorisation.max_calls} call(s) / ${authorisation.max_estimated_usd}\n"
    )

    settings = Settings(
        llm_provider=LlmProvider.BEDROCK,
        bedrock_model_id=namespace.model,
        aws_region=namespace.region,
    )
    provider = provider_builder(settings, authorisation)
    provider_name = provider.name

    def factory(_: ModelInput) -> SemanticProvider:
        return provider

    guard = BudgetGuard(budget, price=price, live=True)
    run_id = new_run_id()
    header = RunHeader(
        run_id=run_id,
        started_at=utc_now_iso(),
        git_sha=git_sha(),
        dataset_version=full.version,
        dataset_hash=full.content_hash,
        prompts=tuple(dict(entry) for entry in _prompt_identities()),
        provider=provider_name,
        model_id=namespace.model,
        mode=LIVE_MODE,
        splits=tuple(split.value for split in splits),
        region=namespace.region,
        pricing_snapshot=price.snapshot_date.isoformat(),
    )
    path = RESULTS_DIR / f"{namespace.split}-{namespace.model.replace(':', '_')}.jsonl"
    attempts = ProviderFailureLog(_failures_path(path))
    store = ResultStore(path, header)
    (RESULTS_DIR / f"{store.header.run_id}-preflight.txt").write_text(preflight, encoding="utf-8")
    if store.existing:
        print(
            f"\nResuming {path}: {len(store.existing)} case(s) already answered and paid for. "
            f"They are read back, not asked again."
        )

    def persist(result: CaseResult) -> None:
        """Write down what was measured, and where it belongs.

        A refusal by the acceptance gate is a fact about the model and goes in the result
        file: it cost a call, it cost two attempts, and "the answer did not satisfy the schema
        twice" is a result. A transport failure is not a fact about the model at all -- nobody
        was reached -- and freezing one into that file would mean a resumed run reported an
        outage as a reading and never asked the case again.

        So it goes to the attempt log beside it instead. The case stays unanswered and will be
        asked again once the infrastructure is diagnosed, and the refusal is still on record
        rather than thrown away: "we tried and were refused" is evidence, and a run that
        discards it can only ever report model quality.
        """
        if result.execution_status is ExecutionStatus.PROVIDER_FAILURE:
            attempts.record(
                ProviderFailureRecord(
                    run_id=store.header.run_id,
                    recorded_at=utc_now_iso(),
                    git_sha=store.header.git_sha,
                    case_id=result.case_id,
                    job=result.job.value,
                    split=result.split.value,
                    provider=result.provider,
                    model_id=result.model_id or namespace.model,
                    attempt=attempts.attempts_for(result.case_id) + 1,
                    category=result.error_category,
                    e2e_latency_ms=result.e2e_latency_ms,
                )
            )
            return
        store.record(result)

    stopped_by_budget: str | None = None
    try:
        outcome = await run_cases(
            selected,
            factory,
            guard=guard,
            provider_name=provider_name,
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
        outcome = await _rescore_from_store(path, guard, provider_name, namespace.model, selected)

    summary = _summarise(
        full, selected, outcome, splits, store.header.run_id, budget, stopped_by_budget
    )
    _emit(summary, namespace)
    append_to_ledger(LEDGER, ledger_entry(summary))
    return _exit_code(summary)


def _failures_path(results: Path) -> Path:
    """Where attempts that produced no reading go: beside the readings, never among them."""
    return results.with_name(f"{results.stem}-provider-failures.jsonl")


def _refuse_an_exhausted_allowance(budget: EvalBudget, spent: LedgerTotals) -> None:
    """A run with nothing left to spend does not start and pretend to measure something."""
    if budget.max_calls == 0 or budget.max_estimated_usd == 0:
        raise BenchmarkRefusedError(
            f"the global benchmark ceiling is used up: {spent.calls} call(s) and "
            f"${spent.estimated_usd} already recorded in {LEDGER}. Raising it is a deliberate "
            f"edit to GLOBAL_CEILING, not something this command does."
        )


def _prompt_identities() -> tuple[dict[str, str], ...]:
    from evals.prompts import prompt_identity

    from promisepatch.semantic import SemanticJob

    return tuple(
        prompt_identity(job).as_payload()
        for job in (SemanticJob.INTERPRET_UTTERANCE, SemanticJob.CLASSIFY_REPLY_INTENT)
    )


async def _rescore_from_store(
    path: Path, guard: BudgetGuard, provider_name: str, model_id: str, selected: GoldDataset
) -> RunOutcome:
    """Rebuild an outcome from what is on disk, without asking a provider anything.

    The results a run did pay for are still results. Losing them because the run ended on a
    budget refusal would be the most expensive possible way to enforce a budget, and having to
    buy them again because a report failed to render would be the second most expensive.
    """
    _, results = read_run(path)
    narrowed = GoldDataset(
        version=selected.version,
        worker=tuple(
            case for case in selected.worker if case.id in {item.case_id for item in results}
        ),
        customer=tuple(
            case for case in selected.customer if case.id in {item.case_id for item in results}
        ),
        provenance=selected.provenance,
    )
    return await run_cases(
        narrowed,
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
    selected: GoldDataset,
    outcome: RunOutcome,
    splits: Sequence[EvalSplit],
    run_id: str,
    budget: EvalBudget,
    stopped_by_budget: str | None,
) -> RunSummary:
    """Judge the run. The identity is the whole dataset's; the numbers are the split's."""
    summary = build_summary(
        full,
        outcome,
        mode=LIVE_MODE,
        splits=list(splits),
        run_id=run_id,
        budget=budget,
    )
    if stopped_by_budget is None:
        return summary
    operations = {**summary.operations, "stopped": stopped_by_budget}
    return summary.model_copy(update={"operations": operations})


def _emit(summary: RunSummary, namespace: argparse.Namespace) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{summary.run_id}.json").write_text(
        json.dumps(summary.as_payload(), indent=2), encoding="utf-8"
    )
    if namespace.json:
        print(json.dumps(summary.as_payload(), indent=2))
    else:
        print("\n" + render(summary))
    print(_verdict(summary))


def _failed_safety_gates(summary: RunSummary) -> tuple[str, ...]:
    names = {gate.name for gate in SAFETY_GATES}
    return tuple(
        gate.name for gate in summary.gates if gate.name in names and gate.status == "fail"
    )


def _verdict(summary: RunSummary) -> str:
    """One sentence naming what this run decided, in the vocabulary the slice is judged in."""
    safety = _failed_safety_gates(summary)
    if safety:
        return (
            "\nSEMANTIC SAFETY GATE FAILED - REVIEW REQUIRED\n"
            f"  failed: {', '.join(safety)}\n"
            "  Do not challenge with another model. This is an architecture or evaluator "
            "question first."
        )
    quality = tuple(
        gate.name for gate in summary.gates if gate.kind == "quality" and gate.status == "fail"
    )
    split = ", ".join(split.value for split in summary.splits)
    if quality:
        return (
            f"\n{split.upper()} QUALITY GATE FAILED\n"
            f"  failed: {', '.join(quality)}\n"
            "  Do not tune, and do not open the holdout if this was development."
        )
    return f"\n{split.upper()} GATES PASSED"


def _exit_code(summary: RunSummary) -> int:
    return 0 if summary.gate_status == "pass" else 1


# ------------------------------------------------------------- rebuilding, with no model


def rebuild(namespace: argparse.Namespace) -> int:
    """Re-render a finished run from its stored results. Constructs no client, spends nothing."""
    path = Path(namespace.from_results)
    header, results = read_run(path)
    full = load_dataset()
    if header.dataset_hash != full.content_hash:
        raise BenchmarkRefusedError(
            f"{path.name} was run against dataset hash {header.dataset_hash[:12]} and the "
            f"dataset on disk hashes to {full.content_hash[:12]}. Re-scoring one run's answers "
            f"against another dataset's labels would produce a number about neither."
        )
    splits = [EvalSplit(value) for value in header.splits]
    selected = full.split(splits)
    price = price_for(header.provider, header.model_id)
    guard = BudgetGuard(EvalBudget(), price=price, live=False)
    outcome = asyncio.run(
        _rescore_from_store(path, guard, header.provider, header.model_id or "", selected)
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
        splits=splits,
        run_id=header.run_id,
        budget=GLOBAL_CEILING,
        generated_at=header.started_at,
    )
    summary = summary.model_copy(update={"model_id": header.model_id, "provider": header.provider})
    print(render(summary))
    print(_verdict(summary))
    identity = dataset_identity(full)
    print(
        f"\nRebuilt from {path} with zero provider calls "
        f"(dataset {identity.name} v{identity.version} {identity.content_hash[:12]})."
    )
    return _exit_code(summary)


# ------------------------------------------------------------------------------ the CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_semantic_benchmark",
        description=(
            "Benchmark PromisePatch's semantic jobs against a real provider. Spending requires "
            "--live, --provider and --model, all three given explicitly."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "take the live code path. Necessary and NOT sufficient: calling the provider also "
            "takes --authorise-paid-inference. Without --live this prints the preflight, "
            "constructs no client and spends nothing."
        ),
    )
    parser.add_argument(
        "--authorise-paid-inference",
        metavar="PHRASE",
        default=None,
        help=(
            "authorise external paid inference for exactly one split of this one invocation. "
            f"{required_phrase(SpendScope.SPLIT_DEVELOPMENT)} for --split development, "
            f"{required_phrase(SpendScope.SPLIT_HOLDOUT)} for --split holdout. Typed here and "
            "nowhere else: never read from the environment, never from .env, never defaulted, "
            "and never carried from one split to the other."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=[LlmProvider.BEDROCK.value],
        help="which provider to call. No default: a benchmark names what it measured.",
    )
    parser.add_argument(
        "--model",
        help=(
            "the model or cross-Region inference profile id. No default, and never taken from "
            "settings: PP_BEDROCK_MODEL_ID names a different model than this benchmark is for."
        ),
    )
    parser.add_argument("--region", default="us-east-1", help="the Region to call Bedrock in")
    parser.add_argument(
        "--split",
        choices=[split.value for split in EvalSplit],
        help="which half of the dataset to run. Exactly one, so the two are never blended.",
    )
    parser.add_argument(
        "--development-passed",
        action="store_true",
        help=(
            "confirm the development split has already passed every gate. Required for "
            "--split holdout: the holdout is read once, to decide, and never to tune against."
        ),
    )
    parser.add_argument(
        "--from-results",
        help=(
            "rebuild the summary and report from a stored run file instead of calling anything. "
            "A report that failed to render is not a reason to buy the answers again."
        ),
    )
    parser.add_argument("--json", action="store_true", help="emit the machine-readable summary")
    return parser


def _validate(namespace: argparse.Namespace) -> None:
    """Refuse an incoherent invocation before anything is loaded, let alone called.

    The authorisation is resolved here, at the very front, so an unauthorised run stops before
    the dataset is read -- long before a price is looked up, a budget is computed or a client
    could exist. "Refused before the provider factory" is then true by construction.
    """
    namespace.authorisation = None
    if namespace.from_results:
        if namespace.authorise_paid_inference:
            raise BenchmarkRefusedError(
                "--from-results rebuilds a report from stored answers and makes no provider "
                "call, so there is nothing here to authorise. Drop "
                "--authorise-paid-inference."
            )
        return
    if not namespace.split:
        raise BenchmarkRefusedError("--split is required: development or holdout, never both")
    if namespace.live and not (namespace.provider and namespace.model):
        raise BenchmarkRefusedError(
            "--live requires --provider and --model. Neither is defaulted, and neither is read "
            "from the environment: a run that inherited its model could measure one nobody "
            "chose."
        )
    if not namespace.provider:
        namespace.provider = LlmProvider.BEDROCK.value
    if not namespace.model:
        raise BenchmarkRefusedError(
            "--model is required, even for a dry run: the preflight names what it measured"
        )
    if namespace.authorise_paid_inference and not namespace.live:
        raise BenchmarkRefusedError(
            "--authorise-paid-inference without --live authorises a command that does not call "
            "anything. Say what is intended: drop the authorisation, or add --live."
        )
    if namespace.live:
        namespace.authorisation = authorise(
            namespace.authorise_paid_inference,
            SPLIT_SCOPES[namespace.split],
            max_calls=GLOBAL_CEILING.max_calls,
            max_estimated_usd=GLOBAL_CEILING.max_estimated_usd,
        )


def main(
    argv: Sequence[str] | None = None,
    *,
    provider_builder: ProviderBuilder = bedrock_provider,
) -> int:
    """Parse, refuse or run. ``provider_builder`` is the only way a paid client enters."""
    namespace = build_parser().parse_args(argv)
    try:
        _validate(namespace)
        if namespace.from_results:
            return rebuild(namespace)
        return asyncio.run(run_live(namespace, provider_builder=provider_builder))
    except (BenchmarkRefusedError, SpendNotAuthorisedError, StoreError) as error:
        # A result file that cannot be continued is a refusal like any other, not a crash, and
        # nothing was bought: the identity is checked before the first question is put.
        print(f"refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
