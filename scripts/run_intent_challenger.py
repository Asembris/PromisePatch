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

**``--live`` is not permission to spend.** It names a code path. Buying inference additionally
takes a scope-bound authorisation phrase typed at the invocation, and the stage it names is the
stage it pays for: an operator who approved Stage A has not approved Stage B. Nothing here
reads that phrase from the environment or from ``.env``, no default supplies it, and a process
running under pytest cannot construct a paid provider whatever it was handed. See
:mod:`evals.authorisation`.

**A call nobody answered is not a reading.** A provider failure is written to a separate
attempt log rather than into the results file, so a resumed run asks the case again instead of
reading an outage back as an answer -- and the paired taxonomy classifies it as
``PROVIDER_FAILURE`` rather than as an unrepaired failure or a control regression.

Plan the set without calling anything::

    uv run python -m scripts.run_intent_challenger --stage a --model <id> --plan

Run Stage A::

    uv run python -m scripts.run_intent_challenger --live --provider bedrock --model <id> \\
        --stage a --authorise-paid-inference AUTHORISE-PAID-INFERENCE-STAGE-A

Rebuild any report from what a run already paid for::

    uv run python -m scripts.run_intent_challenger --from-results .eval-results/<file>.jsonl
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
    ledger_totals,
    price_for,
    remaining_budget,
    utc_now_iso,
)
from evals.cases import EvalJob, EvalSplit, ModelInput
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
    unread_result,
    usage_profile,
)
from evals.challenger_report import render_cost, render_stage_a, render_stage_b
from evals.dataset import GoldDataset, load_dataset, manifest_problems, validate_dataset
from evals.preflight import render_preflight
from evals.report import render
from evals.results import CaseResult, RunSummary
from evals.runner import LIVE_MODE, RunOutcome, StopPolicy, run_cases
from evals.store import (
    ProviderFailureLog,
    ProviderFailureRecord,
    ResultStore,
    RunHeader,
    StoreError,
    read_run,
)
from evals.summary import build_summary, git_sha, ledger_entry

from promisepatch.config import LlmProvider, Settings
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


STAGE_SCOPES = {"a": SpendScope.STAGE_A, "b": SpendScope.STAGE_B}
"""Which authorisation each stage costs. Two entries, and no key that opens both."""


class ChallengerRefusedError(RuntimeError):
    """A precondition for spending is not met, so nothing was spent."""


# ------------------------------------------------------------------ the paid provider seam


type ProviderBuilder = Callable[[Settings, SpendAuthorisation], SemanticProvider]
"""How this command gets something that can be charged for. A parameter, never a branch."""


def bedrock_provider(settings: Settings, authorisation: SpendAuthorisation) -> SemanticProvider:
    """Production's own provider factory, behind the two guards that gate paid inference.

    The authorisation is taken as an argument rather than looked up, so there is no way to
    reach this function without one having been produced by :func:`evals.authorisation
    .authorise` from a phrase somebody typed. The test interlock is checked here rather than
    at the call site because this is the last line before money: whatever route got here, a
    pytest process does not pass it.

    The Bedrock import is deferred into the body for the same reason it is in production --
    so that merely importing this module pulls in no AWS SDK -- and now for a second one: a
    test that never reaches this line never even loads the integration package.
    """
    refuse_real_inference_under_test(authorisation.scope)
    from promisepatch.integrations.semantic_provider import build_semantic_provider

    return build_semantic_provider(settings)


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


def refuse_ineligible_cases(selected: GoldDataset) -> None:
    """Refuse before the provider exists unless every case is a customer development case.

    :func:`narrow` already builds a dataset that cannot contain anything else, so this should
    never fire. It is here because "should never fire" is what was believed about the path
    that put three worker sentences to a model: the guarantee was a property of one function
    nobody re-read, and there was no check standing between a mistake in it and a purchase.

    Checked on the value actually handed to the runner, and raised rather than filtered. A
    filter would make an ineligible case cheap to introduce and invisible once introduced;
    a refusal makes it a stop.
    """
    if selected.worker:
        offenders = ", ".join(case.id for case in selected.worker[:5])
        raise ChallengerRefusedError(
            f"{len(selected.worker)} worker case(s) reached the challenger set ({offenders}). "
            f"This slice buys customer-intent readings only, and a worker call here would be "
            f"spend nobody authorised on a job nobody is comparing."
        )
    wrong_job = [case.id for case in selected.customer if case.job is not EvalJob.CUSTOMER_INTENT]
    if wrong_job:
        raise ChallengerRefusedError(
            f"case(s) outside the customer-intent job reached the challenger set: "
            f"{', '.join(wrong_job)}."
        )
    holdout = [case.id for case in selected.customer if case.split is not EvalSplit.DEVELOPMENT]
    if holdout:
        raise ChallengerRefusedError(
            f"{len(holdout)} case(s) outside the development split reached the challenger set: "
            f"{', '.join(holdout)}. The holdout is read once, to decide, and nothing here "
            f"opens it."
        )
    if not selected.customer:
        raise ChallengerRefusedError(
            "the challenger set is empty, so there is nothing to buy and nothing to compare"
        )


def refuse_challenging_a_model_with_itself(source: SourceRun, model: str) -> None:
    """The source model is evidence, not a participant. It is never called from here.

    Its answers come from a file. Re-running it would buy a second reading of cases that
    already have one, and comparing a model with itself would be an expensive way to measure
    sampling noise.
    """
    if source.model_id is not None and source.model_id == model:
        raise ChallengerRefusedError(
            f"{model!r} is the model this comparison is challenging. Its readings are read "
            f"from {DEFAULT_SOURCE.name} and it is never called from here: a challenger has "
            f"to be a different model for the comparison to mean anything."
        )


def results_path(model: str) -> Path:
    return RESULTS_DIR / f"challenger-{model.replace(':', '_')}.jsonl"


def failures_path(model: str) -> Path:
    """Where attempts that produced no reading are kept, beside the readings and not among them."""
    return RESULTS_DIR / f"challenger-{model.replace(':', '_')}-provider-failures.jsonl"


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


async def run(
    namespace: argparse.Namespace,
    *,
    provider_builder: ProviderBuilder = bedrock_provider,
) -> int:
    """Plan, preflight, and -- only with an authorisation -- buy the stage that was asked for.

    ``provider_builder`` is the seam. It defaults to the one thing here that can be charged
    for, and a test that needs the orchestration passes a builder that cannot: there is no
    branch to set, no environment to arrange and no mock to install over a real client,
    because the real client is a value this function was handed rather than one it makes.
    """
    full = load_dataset()
    problems = [*validate_dataset(full), *manifest_problems(full, full.manifest())]
    if problems:
        raise ChallengerRefusedError(
            "the dataset does not agree with production, so nothing measured against it would "
            "mean anything:\n  - " + "\n  - ".join(problems)
        )

    source = load_source(Path(namespace.source), full)
    refuse_challenging_a_model_with_itself(source, namespace.model)
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

    attempts = ProviderFailureLog(failures_path(namespace.model))
    stored = _stored_results(results_path(namespace.model))
    stage_a = build_stage_a(full, selection, source, _with_attempts(full, stored, attempts))
    verdict = evaluate_materiality(stage_a)

    if namespace.stage == "b":
        _refuse_an_unearned_stage_b(stage_a, verdict)
        wanted = frozenset(case.id for case in full.customer if case.split is EvalSplit.DEVELOPMENT)
    else:
        wanted = selection.case_ids

    selected = narrow(full, wanted)
    refuse_ineligible_cases(selected)
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
            f"Buying the stage above takes --live and --authorise-paid-inference "
            f"{required_phrase(STAGE_SCOPES[namespace.stage])}."
        )
        return 0

    _refuse_an_exhausted_allowance(budget, spent)

    # Re-demanded at the point of spending rather than trusted from the parse. The phrase was
    # checked once already; this is the assertion that the stage about to be bought is the one
    # it named, and it is what stops a Stage-A approval paying for Stage B.
    authorisation: SpendAuthorisation = namespace.authorisation
    authorisation.require(STAGE_SCOPES[namespace.stage])
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
        """A refused answer is a fact about the model; an outage is a fact about the weather.

        Both are written down and they go to different files. The reading file is what a
        resumed run reads back to avoid buying a case twice, so nothing without a reading may
        enter it -- an outage recorded there would be replayed for ever as an answer. The
        attempt log is where the outage goes instead: kept as evidence, never scored, and
        leaving the case eligible to be asked again once the infrastructure is fixed.
        """
        if not result.has_reading:
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


def _with_attempts(
    full: GoldDataset,
    stored: Sequence[CaseResult],
    attempts: ProviderFailureLog,
) -> tuple[CaseResult, ...]:
    """Stored readings, plus one no-reading record for every case whose only history is a refusal.

    The join a report needs. A case that was asked and not answered has to appear in the
    comparison -- leaving it out would make the stage look merely unfinished rather than
    blocked -- but it appears carrying its execution status, so the taxonomy classifies it as
    an execution failure and no quality number counts it. Reading the log calls nothing.
    """
    cases = {case.id: case for case in full.customer}
    known = {result.case_id for result in stored}
    latest: dict[str, ProviderFailureRecord] = {}
    for record in attempts.records:
        if record.case_id in known or record.case_id not in cases:
            continue
        latest[record.case_id] = record
    return (
        *stored,
        *(unread_result(record, cases[case_id]) for case_id, record in sorted(latest.items())),
    )


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
    """Print whichever report the evidence on disk can support, and name the outcome.

    Reads files and renders. It builds no provider, opens no client and makes no call, which
    is why a report that failed to render is a formatting problem rather than a second bill.
    """
    attempts = ProviderFailureLog(failures_path(namespace.model))
    joined = _with_attempts(full, results, attempts)
    selection = select_stage_a(full, source)
    stage_a = build_stage_a(full, selection, source, joined)
    verdict = evaluate_materiality(stage_a)
    print("\n" + render_stage_a(stage_a, verdict))
    results = joined

    development = frozenset(
        case.id for case in full.customer if case.split is EvalSplit.DEVELOPMENT
    )
    answered = {result.case_id for result in results if result.has_reading}
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
        unanswered = len(development - answered)
        blocked = len(stage_a.provider_failures)
        print(
            f"STAGE B NOT OPENED. {unanswered} customer development case(s) have no challenger "
            f"reading"
            + (
                "."
                if blocked == 0
                else (
                    f", of which {blocked} in the Stage-A set were asked and not answered. "
                    f"Those are execution failures, recorded in "
                    f"{failures_path(namespace.model)}. They are not model-quality evidence "
                    f"and are not counted as unrepaired failures."
                )
            )
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
    """One sentence naming what this run decided, in the vocabulary the slice is judged in.

    The first thing it separates is whether anything was measured at all. A stage stopped by
    provider failures has no quality verdict to report, and saying "not material" about it
    would be a claim about a model derived from an account.
    """
    materiality = evaluate_materiality(stage_a)
    if stage_a.authority_violations:
        return (
            "\nSEMANTIC SAFETY GATE FAILED - REVIEW REQUIRED\n"
            "  A label outside the closed non-authoritative set was accepted. This is an "
            "architecture or evaluator question first, not a model one."
        )
    if stage_a.provider_failures:
        blocked = len(stage_a.provider_failures)
        return (
            "\nSTAGE A INVALID FOR A QUALITY DECISION - EXECUTION FAILURE\n"
            f"  {blocked} of {len(stage_a.selection.case_ids)} selected case(s) were asked and "
            f"produced no reading.\n"
            f"  Readings obtained: {stage_a.provider_completion}. Challenger quality: NOT "
            f"MEASURED.\n"
            "  This is an infrastructure outcome, not a model outcome. Stage B is closed, no "
            "materiality\n"
            "  verdict is available, and nothing here says the challenger is or is not "
            "material."
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
    if not namespace.model:
        raise ChallengerRefusedError(
            f"{path.name} names no model and none was given, so the attempt log and the price "
            f"for this run cannot be identified. Pass --model."
        )
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
            "take the live code path. Necessary and NOT sufficient: buying inference also "
            "takes --authorise-paid-inference. Without --live this prints the plan, "
            "constructs no client and spends nothing."
        ),
    )
    parser.add_argument(
        "--authorise-paid-inference",
        metavar="PHRASE",
        default=None,
        help=(
            "authorise external paid inference for exactly one stage of this one invocation. "
            f"{required_phrase(SpendScope.STAGE_A)} for --stage a, "
            f"{required_phrase(SpendScope.STAGE_B)} for --stage b. Typed here and nowhere "
            "else: never read from the environment, never from .env, never defaulted, and "
            "never carried from one stage to the next. It is not a secret and not "
            "authentication -- it is the difference between running the live code path and "
            "deciding to be charged."
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
    """Refuse an incoherent invocation before anything is loaded, let alone called.

    The authorisation is resolved here, at the very front of the command, so a run that may
    not spend stops before the dataset is read -- long before a price is looked up, a budget
    is computed or a client could exist. That ordering is the point: "refused before the
    provider factory" should be true by construction rather than by careful sequencing later.
    """
    namespace.authorisation = None
    if namespace.from_results:
        if not namespace.provider:
            namespace.provider = LlmProvider.BEDROCK.value
        if namespace.authorise_paid_inference:
            raise ChallengerRefusedError(
                "--from-results rebuilds a report from stored evidence and makes no provider "
                "call, so there is nothing here to authorise. Drop "
                "--authorise-paid-inference."
            )
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
    if namespace.authorise_paid_inference and not namespace.live:
        raise ChallengerRefusedError(
            "--authorise-paid-inference without --live authorises a command that does not "
            "call anything. Say what is intended: drop the authorisation, or add --live."
        )
    if namespace.live:
        namespace.authorisation = authorise(
            namespace.authorise_paid_inference,
            STAGE_SCOPES[namespace.stage],
            max_calls=CHALLENGER_CEILING.max_calls,
            max_estimated_usd=CHALLENGER_CEILING.max_estimated_usd,
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
        return asyncio.run(run(namespace, provider_builder=provider_builder))
    except (
        ChallengerRefusedError,
        ChallengerError,
        SpendNotAuthorisedError,
        StoreError,
    ) as error:
        # A result file that cannot be continued is a refusal like any other, not a crash. It
        # is reported the same way and, like every refusal here, no case was bought: the
        # identity is checked before the first question is put to anything.
        print(f"refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
