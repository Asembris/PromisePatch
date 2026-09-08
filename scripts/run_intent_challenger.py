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

**Two providers, two ceilings, one experiment.** A challenger may be reached through Bedrock or
through OpenAI, and each carries its own global and stage allowances because the two are an
order of magnitude apart in price -- a dollar cap sized for the dearer one is not a cap on the
cheaper one. Nothing else about the comparison changes with the provider: the same frozen
dataset, the same stored source run, the same deterministic selection, the same production
prompt and schema, the same scorer and the same materiality floor. Only the model differs, which
is the whole point of a challenger.

Plan the set without calling anything::

    uv run python -m scripts.run_intent_challenger --stage a --model <id> --plan

Run Stage A::

    uv run python -m scripts.run_intent_challenger --live --provider bedrock --model <id> \\
        --stage a --authorise-paid-inference AUTHORISE-PAID-INFERENCE-STAGE-A

    uv run python -m scripts.run_intent_challenger --live --provider openai \\
        --model gpt-4o-mini-2024-07-18 --stage a \\
        --authorise-paid-inference AUTHORISE-PAID-INFERENCE-STAGE-A

Rebuild any report from what a run already paid for::

    uv run python -m scripts.run_intent_challenger --from-results .eval-results/<file>.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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
    tightest,
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

BEDROCK = LlmProvider.BEDROCK.value
OPENAI = "openai"
"""The two providers a challenger may be reached through, by the name a result file records.

``openai`` is a literal rather than a :class:`~promisepatch.config.LlmProvider` member on
purpose. That enum is the runtime's routing surface, and adding to it would widen what a
deployment can be configured to do -- which is a production change, and this gate makes none.
The OpenAI adapter is reachable from here, from a composition root that has to be handed an
authorisation and a key, and from nowhere a running worker can get to.
"""

GPT_4O_MINI = "gpt-4o-mini-2024-07-18"
"""The pinned challenger snapshot. The dated id, never the floating ``gpt-4o-mini`` alias.

A benchmark identity has to survive the provider changing what an alias points at. The two are
different models for every purpose here: different price lookups, different result files,
different run headers, and a run started against one may not be continued against the other.
"""

OPENAI_ALIASES: Mapping[str, str] = {"gpt-4o-mini": GPT_4O_MINI}
"""Floating names this command refuses, and the pinned snapshot to use instead.

Refused by name rather than merely left unpriced. Unknown pricing would already stop the run --
the alias is not in the catalog and never will be -- but "no verified price" is the wrong
sentence for this mistake, and an operator who reads it looks for a pricing bug instead of
typing the date.
"""

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

STAGE_A_CEILING = EvalBudget(
    max_calls=12,
    max_estimated_usd=Decimal("0.03"),
)
"""Stage A's own allowance, enforced *as well as* :data:`CHALLENGER_CEILING`, never instead.

Stage A is a bounded probe: six of the challenged model's customer-intent failures and their
six matched controls, which is twelve logical calls and cannot become a thirteenth by any
route that does not also change the selection. The bound is written here so that number is a
property of the experiment rather than a figure an operator retypes correctly each time. A
flag would put the ceiling in the hands of whoever is tired at the keyboard; this puts it in a
commit somebody reviews, which is where the global ceiling already lives.

Only the two fields the stage is bounded on are set. The token caps stay ``None`` -- uncapped
*here*, which under :func:`~evals.budget.tightest` means the global ceiling's own token bounds
carry through untouched. That is the intended shape: a stage bound narrows, and a field it is
silent about keeps the wider protection rather than losing it.

Stage B has no entry in :data:`STAGE_CEILINGS` and is therefore bounded by the global ceiling
exactly as before. It is separately authorised, separately approved, and nothing here changes
what it may spend.
"""

STAGE_CEILINGS: Mapping[str, EvalBudget] = {"a": STAGE_A_CEILING}
"""Stage-specific bounds, by ``--stage``. A stage absent from this map keeps the global one."""


OPENAI_CHALLENGER_CEILING = EvalBudget(
    max_calls=30,
    max_input_tokens=100_000,
    max_output_tokens=10_000,
    max_estimated_usd=Decimal("0.03"),
)
"""The OpenAI challenger's whole allowance, across Stage A, Stage B and any resumed attempt.

Its own ceiling rather than the Bedrock one reused, because the two models are an order of
magnitude apart in price and a dollar cap sized for the dearer one is not a cap on the cheaper
one at all. At the recorded snapshot price, the token ceilings above come to $0.021 --
100k input at $0.15/M is $0.015, 10k output at $0.60/M is $0.006 -- so three cents sits above
what the token bounds already permit. That is the intended shape: the dollar cap is a backstop
for arithmetic nobody re-checked, not the bound expected to bite.

The call and token bounds are deliberately the same numbers the Bedrock ceiling carries. The
experiment is the same size whichever model answers it; only the money differs.
"""

OPENAI_STAGE_A_CEILING = EvalBudget(
    max_calls=12,
    max_estimated_usd=Decimal("0.01"),
)
"""OpenAI Stage A's own allowance, enforced *as well as* :data:`OPENAI_CHALLENGER_CEILING`.

Twelve is the selection's own size -- six of the challenged model's customer-intent failures
and their six matched controls -- so the call cap and the experiment are one number rather than
two that have to be kept in step. One cent is far above what twelve calls of this shape can
cost and far below anything worth noticing, which is what a probe's ceiling should be.

Only the two fields the stage is bounded on are set, exactly as :data:`STAGE_A_CEILING` is: the
token caps stay ``None`` here so :func:`~evals.budget.tightest` carries the global ceiling's own
token bounds through untouched.
"""

PROVIDER_CEILINGS: Mapping[str, EvalBudget] = {
    BEDROCK: CHALLENGER_CEILING,
    OPENAI: OPENAI_CHALLENGER_CEILING,
}
"""The global allowance per provider. Separate entries, never one number shared between them.

A shared ceiling would make one challenger's history debit another's allowance, and a
discontinued attempt would keep paying for itself for ever. Keeping them apart is also what
lets the Bedrock figures stay exactly as they were recorded: this gate adds a provider, it does
not reprice one.
"""

PROVIDER_STAGE_CEILINGS: Mapping[str, Mapping[str, EvalBudget]] = {
    BEDROCK: STAGE_CEILINGS,
    OPENAI: {"a": OPENAI_STAGE_A_CEILING},
}
"""Stage bounds per provider. A stage absent from a provider's map keeps that provider's global
ceiling -- which is how Stage B stays bounded exactly as it was, for both of them."""


def global_ceiling(provider: str) -> EvalBudget:
    """One provider's whole challenger allowance. Unknown providers get no allowance at all."""
    ceiling = PROVIDER_CEILINGS.get(provider)
    if ceiling is None:  # pragma: no cover - argparse closes the choice set first
        raise ChallengerRefusedError(
            f"{provider!r} has no challenger ceiling written down, so nothing bounds a run "
            f"against it. A provider without a ceiling is a provider that cannot be run."
        )
    return ceiling


def stage_ceiling(stage: str, provider: str = BEDROCK) -> EvalBudget:
    """The ceiling one stage may not cross: that provider's allowance, tightened by its own bound.

    Both ceilings remain in force and whichever is strictest refuses first, so the global cap
    is defence in depth rather than something this replaced.
    """
    stage_bound = PROVIDER_STAGE_CEILINGS.get(provider, {}).get(stage)
    if stage_bound is None:
        return global_ceiling(provider)
    return tightest(global_ceiling(provider), stage_bound)


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


@dataclass(frozen=True, slots=True)
class ChallengerTarget:
    """Which model this invocation would pay to ask, and everything needed to reach it.

    A value rather than four arguments, because "which provider, which model" is one decision
    and splitting it across a signature is how a run ends up naming one provider and calling
    another. It carries no credential: the key, when there is one, is resolved by the
    composition root immediately before the builder is called and handed to the adapter that
    needs it, so nothing that gets written down or printed has ever held it.
    """

    provider: str
    model_id: str
    region: str | None
    settings: Settings
    """Production's settings object, for the provider that has one. OpenAI does not appear in
    it at all -- there is no runtime routing to OpenAI, and this gate adds none."""

    api_key: str | None = None


type ProviderBuilder = Callable[[ChallengerTarget, SpendAuthorisation], SemanticProvider]
"""How this command gets something that can be charged for. A parameter, never a branch."""


def bedrock_provider(
    target: ChallengerTarget, authorisation: SpendAuthorisation
) -> SemanticProvider:
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

    return build_semantic_provider(target.settings)


def openai_provider(
    target: ChallengerTarget, authorisation: SpendAuthorisation
) -> SemanticProvider:
    """The OpenAI transport adapter, behind the same two guards and one more.

    The same shape as the Bedrock builder above and for the same reasons: an authorisation is
    an argument, the test interlock is checked on the last line before money, and the SDK
    import is deferred so that importing this module loads no vendor client.

    The third guard is the key. It is not read here and it is not read by the adapter -- both
    of them take it -- so a missing credential is a refusal the composition root already made
    before this function existed in the call stack. The check below is the assertion that it
    did, not the place the decision is taken.
    """
    refuse_real_inference_under_test(authorisation.scope)
    if not target.api_key:  # pragma: no cover - the composition root refuses first
        raise ChallengerRefusedError(
            "no OpenAI API key reached the provider builder. A run that got this far without "
            "one is a run whose preflight did not check, which is a defect in the ordering."
        )
    from promisepatch.integrations.openai import OpenAiSemanticProvider

    return OpenAiSemanticProvider.with_api_key(api_key=target.api_key, model_id=target.model_id)


PROVIDER_BUILDERS: Mapping[str, ProviderBuilder] = {
    BEDROCK: bedrock_provider,
    OPENAI: openai_provider,
}


def paid_provider(target: ChallengerTarget, authorisation: SpendAuthorisation) -> SemanticProvider:
    """The default builder: whichever vendor client this target names, and no other.

    A lookup rather than a chain of ``if``s, so adding a provider cannot quietly change what
    happens for an existing one. It is still the seam -- a test passes its own builder in and
    never reaches this function at all.
    """
    builder = PROVIDER_BUILDERS.get(target.provider)
    if builder is None:  # pragma: no cover - argparse closes the choice set first
        raise ChallengerRefusedError(f"{target.provider!r} has no provider builder")
    return builder(target, authorisation)


# ------------------------------------------------------------------- the OpenAI credential


API_KEY_VARIABLE = "OPENAI_API_KEY"
"""The one name this command will look under. Never printed, never logged, never persisted."""


def read_openai_api_key(env_file: Path = Path(".env")) -> str | None:
    """The key, from the process environment or the local ``.env``, or ``None``.

    Two places because both are real: an operator may export it for one command, and this
    repository's convention -- the one pydantic-settings already follows for everything else --
    is that local configuration lives in an ignored ``.env``. Neither is a secret store and
    neither is treated as one; this returns the value to exactly one caller, which hands it to
    exactly one constructor.

    The value is never returned to anything that prints, formats or serialises. Everything a
    report, a preflight, a result file, a ledger line or an error message sees is the boolean
    from :func:`openai_api_key_present`.
    """
    from_environment = os.environ.get(API_KEY_VARIABLE, "").strip()
    if from_environment:
        return from_environment
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        if name.strip() != API_KEY_VARIABLE:
            continue
        return value.strip().strip("\"'") or None
    return None


def openai_api_key_present(env_file: Path = Path(".env")) -> bool:
    """Whether a key is available, as a boolean and only ever as a boolean."""
    return read_openai_api_key(env_file) is not None


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


def refuse_a_floating_model_alias(provider: str, model: str) -> None:
    """Refuse an alias, before a plan is written and long before anything is bought.

    A benchmark's model identity has to be the thing that was actually measured. An alias is a
    pointer the provider may repoint without telling anybody, so a number recorded against one
    describes whichever snapshot answered that day -- and the next run under the same name is
    not a comparison, it is two experiments sharing a label.
    """
    pinned = OPENAI_ALIASES.get(model) if provider == OPENAI else None
    if pinned is None:
        return
    raise ChallengerRefusedError(
        f"{model!r} is a floating alias, not a model. A benchmark result has to name the "
        f"snapshot that produced it, because an alias may point somewhere else next week and "
        f"the two results would not be comparable. Use --model {pinned}."
    )


def refuse_a_missing_openai_key(provider: str) -> None:
    """Refuse before the provider builder when the credential is not there. Never prints it.

    Ordered here rather than left to the SDK on purpose. A client constructed without a key
    fails at the first request, which is a failure that has already left the machine and has
    already been counted as an attempt; a check before construction is a refusal that costs
    nothing and cannot be mistaken for a provider outage.

    There is no fallback. Not to Bedrock, not to another model, not to another variable: a run
    that quietly measured something else would answer a question nobody asked.
    """
    if provider != OPENAI or openai_api_key_present():
        return
    raise ChallengerRefusedError(
        f"{API_KEY_VARIABLE} is not set and no local .env supplies it, so the OpenAI "
        f"challenger cannot be reached. Nothing was constructed and nothing was spent. This "
        f"command does not fall back to another provider or another model."
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
    provider_builder: ProviderBuilder = paid_provider,
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

    # Pricing after eligibility and before any budget arithmetic, which is the order the two
    # questions actually depend on each other in: what may be asked is a property of the
    # dataset, and what it may cost is only worth computing once the set is legal.
    price = price_for(namespace.provider, namespace.model)
    if price is None:
        raise ChallengerRefusedError(
            f"{namespace.model!r} has no verified price in evals.budget.PRICES for provider "
            f"{namespace.provider!r}, so a dollar ceiling cannot be enforced for it. Add it "
            f"from a current published price list, with the day it was read, before "
            f"challenging with it."
        )

    ceiling = stage_ceiling(namespace.stage, namespace.provider)
    spent = ledger_totals(
        LEDGER, mode=LIVE_MODE, provider=namespace.provider, model_id=namespace.model
    )
    budget = remaining_budget(ceiling, spent)
    region = _region_for(namespace)

    preflight = render_preflight(
        full=full,
        selected=selected,
        splits=[EvalSplit.DEVELOPMENT],
        git_sha=git_sha(),
        provider=namespace.provider,
        model_id=namespace.model,
        region=region,
        price=price,
        budget=budget,
        ceiling=ceiling,
        already_spent=json.dumps(spent.as_payload(), sort_keys=True),
    )
    print(preflight)
    print(_stage_budget_block(namespace.stage, ceiling, namespace.provider))
    print(_selection_block(selection, stage_a, namespace.stage, len(stored)))
    write_selection(selection_path(namespace.model), selection, namespace.model, region)

    if namespace.plan or not namespace.live:
        print(_zero_call_block(selected, namespace))
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

    # The last gate before a client can exist, and the only one about a credential. Everything
    # above it -- authorisation, dataset identity, eligibility, pricing, budget -- has already
    # held; this asks whether the run can even reach the provider it is allowed to pay.
    refuse_a_missing_openai_key(namespace.provider)

    settings = _settings_for(namespace)
    target = ChallengerTarget(
        provider=namespace.provider,
        model_id=namespace.model,
        region=region,
        settings=settings,
        api_key=read_openai_api_key() if namespace.provider == OPENAI else None,
    )
    provider = provider_builder(target, authorisation)

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
                    # Both halves of the identity, for the same reason the model id is
                    # substituted here: a call nobody answered carries no telemetry, so the
                    # runner has neither to read off the answer. A failure record that named
                    # only the mode would not say which challenger was refused, and two
                    # challengers now share this log.
                    provider=result.provider if result.model_id else namespace.provider,
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


def _settings_for(namespace: argparse.Namespace) -> Settings:
    """Production settings for the provider that has some; a bare object for the one that has none.

    OpenAI appears nowhere in :class:`~promisepatch.config.Settings`, because the runtime has no
    route to it and this gate adds none. Handing the OpenAI builder a settings object configured
    for Bedrock would be a small lie in the one value that says what a deployment is, so it is
    handed an unconfigured one it does not read.
    """
    if namespace.provider != BEDROCK:
        return Settings()
    return Settings(
        llm_provider=LlmProvider.BEDROCK,
        bedrock_model_id=namespace.model,
        aws_region=namespace.region,
    )


def _region_for(namespace: argparse.Namespace) -> str:
    """Where the model is called, for the provider where that is a fact.

    ``--region`` is a Bedrock concept: an inference profile is Region-scoped and the Region is
    part of what a Bedrock result measured. OpenAI's API is not addressed that way, so recording
    ``us-east-1`` against an OpenAI run would put a fact in a result file that is not one.
    """
    return namespace.region if namespace.provider == BEDROCK else "not applicable"


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
        f"{', '.join(materiality.failed)}. TARGETED CHALLENGE NOT MATERIAL -- STOPPED EARLY "
        "is a valid outcome, and this is it."
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


def _stage_budget_block(stage: str, effective: EvalBudget, provider: str = BEDROCK) -> str:
    """Name both ceilings and the one actually in force, before anything is bought.

    Printed rather than inferred because "which bound refused" has to be answerable from the
    stored preflight alone, months later, by somebody who was not at the keyboard -- and now
    also which provider's ceilings those were, because the two are different money.
    """
    ceiling = global_ceiling(provider)
    stage_bound = PROVIDER_STAGE_CEILINGS.get(provider, {}).get(stage)
    label = f"stage {stage.upper()} ceiling".ljust(28)
    lines = [
        "",
        f"STAGE BUDGET  -- stage {stage.upper()} is bounded by the stricter of both ceilings",
        f"  {'provider'.ljust(28)} {provider}",
        f"  {'global challenger ceiling'.ljust(28)} {ceiling.max_calls} call(s) / "
        f"${ceiling.max_estimated_usd}",
    ]
    if stage_bound is None:
        lines.append(f"  {label} none -- this stage keeps the global ceiling")
    else:
        lines.append(
            f"  {label} {stage_bound.max_calls} call(s) / ${stage_bound.max_estimated_usd}"
        )
    lines.append(
        f"  {'effective ceiling'.ljust(28)} {effective.max_calls} call(s) / "
        f"${effective.max_estimated_usd}"
    )
    lines.append("  both remain in force; the guard refuses the call that would cross either one")
    return "\n".join(lines)


def _zero_call_block(selected: GoldDataset, namespace: argparse.Namespace) -> str:
    """What a plan proves it did not do, as counts rather than as a promise.

    Every line here is read off the value the runner would have been handed, or off a code path
    this invocation demonstrably did not take. A plan that merely said "nothing was called"
    would be an assertion about intent; these are the numbers somebody can check.

    The credential line is a boolean and is a boolean everywhere else too. Whether a key is
    present changes whether a live run could start, so an operator needs to know it -- and the
    value itself is never read by anything that prints.
    """
    holdout = sum(case.split is not EvalSplit.DEVELOPMENT for case in selected.customer)
    return "\n".join(
        [
            "ZERO-CALL PLAN  -- what this invocation did not do, counted",
            f"  {'challenger provider'.ljust(32)} {namespace.provider}",
            f"  {'challenger model'.ljust(32)} {namespace.model}",
            f"  {'stage A cases'.ljust(32)} {len(selected.customer)}",
            f"  {'worker cases'.ljust(32)} {len(selected.worker)}",
            f"  {'holdout cases'.ljust(32)} {holdout}",
            f"  {'challenger model calls'.ljust(32)} 0",
            f"  {'source (challenged) model calls'.ljust(32)} 0",
            f"  {'provider clients constructed'.ljust(32)} 0",
            f"  {(API_KEY_VARIABLE + ' present').ljust(32)} "
            f"{str(openai_api_key_present()).lower()}",
            "",
        ]
    )


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
        budget=global_ceiling(header.provider),
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
        choices=[BEDROCK, OPENAI],
        help="which provider to call. No default: a comparison names what it measured.",
    )
    parser.add_argument(
        "--model",
        help=(
            "the challenger's model id, cross-Region inference profile or pinned snapshot. No "
            "default, never taken from settings, and never a floating alias: "
            f"{GPT_4O_MINI} rather than gpt-4o-mini."
        ),
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="the Region to call Bedrock in. Not applicable to OpenAI and not recorded for it.",
    )
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
            namespace.provider = BEDROCK
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
        namespace.provider = BEDROCK
    if not namespace.model:
        raise ChallengerRefusedError(
            "--model is required, even for a plan: the preflight names what it would measure"
        )
    refuse_a_floating_model_alias(namespace.provider, namespace.model)
    if namespace.authorise_paid_inference and not namespace.live:
        raise ChallengerRefusedError(
            "--authorise-paid-inference without --live authorises a command that does not "
            "call anything. Say what is intended: drop the authorisation, or add --live."
        )
    if namespace.live:
        ceiling = stage_ceiling(namespace.stage, namespace.provider)
        namespace.authorisation = authorise(
            namespace.authorise_paid_inference,
            STAGE_SCOPES[namespace.stage],
            max_calls=ceiling.max_calls,
            max_estimated_usd=ceiling.max_estimated_usd,
        )


def main(
    argv: Sequence[str] | None = None,
    *,
    provider_builder: ProviderBuilder = paid_provider,
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
