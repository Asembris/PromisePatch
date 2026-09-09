"""Run the P4.8 explanation quality gate against real models, one authorised pass at a time.

The gate itself -- the dataset, the acceptance path, the scorers, the thresholds, the report --
is :mod:`evals`, and it is offline by construction: an import contract keeps every vendor SDK
out of that package's graph, so ``python -m evals`` cannot reach a model however it is invoked.
This module is the composition root that hands it one. It is the only place in the repository
where an explanation evaluation can become a charge, and it is a script rather than a
subcommand for exactly that reason.

**Four commands, and the money is in two of them.**

``plan`` prints the identity and the ceilings and calls nothing. ``generate`` buys Nova's
twenty-one development passages. ``judge`` buys one Nemotron verdict per accepted passage, from
passages already on disk. ``report`` and ``review`` rebuild everything from the file, with zero
calls of either kind -- which is the property that makes a lost terminal cheap, a metric change
free, and a manual review possible without re-buying anything.

**Generation and judging are separately authorised, and neither implies the other.** Letting
the model under test speak is not letting somebody else's model grade it. The phrases are
scope-bound, typed at the invocation, never read from the environment or from ``.env``, and
never defaulted -- and ``--live`` names a code path rather than granting permission. A process
running under pytest cannot construct a paid provider whatever it was handed.

**The holdout is not reachable from a development authorisation.** ``--split`` selects one
split, the scope it maps to is the scope that must be authorised, and the holdout maps to its
own phrase. There is no flag here that opens it as a side effect of anything else.

**Nothing is bought twice.** Every passage and every verdict is written down the moment it
exists, under a header whose identity gates the resume, so an interrupted run continues where
it stopped instead of asking again. The judge reads passages from that file and never reaches
Nova; a passage whose production request has since moved is refused rather than rejudged.

**The two providers never share a counter.** Nova is metered and carries a dollar ceiling
derived from this dataset; NVIDIA's hosted endpoint publishes no per-token price, so its usage
is bounded by calls and tokens and its dollars are absent rather than zero. They are recorded
in one ledger of their own, separate from the customer-intent gate's, because a ceiling for
this evaluation is not a ceiling on everything this account has ever spent.

Plan without calling anything::

    uv run python -m scripts.run_explanation_eval plan --split development

Buy the development passages::

    uv run python -m scripts.run_explanation_eval generate --live --split development \\
        --authorise-paid-inference AUTHORISE-PAID-INFERENCE-P4-8-NOVA-DEVELOPMENT-GENERATION

Judge the accepted ones::

    uv run python -m scripts.run_explanation_eval judge --live --split development \\
        --results .eval-results/explanation-<run>.jsonl \\
        --authorise-paid-inference AUTHORISE-PAID-INFERENCE-P4-8-NEMOTRON-DEVELOPMENT-JUDGING

Rebuild the report and the manual-review ledger, buying nothing::

    uv run python -m scripts.run_explanation_eval report --results .eval-results/<file>.jsonl
    uv run python -m scripts.run_explanation_eval review --results .eval-results/<file>.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from evals.authorisation import (
    SpendAuthorisation,
    SpendNotAuthorisedError,
    SpendScope,
    authorise,
    refuse_real_inference_under_test,
    required_phrase,
)
from evals.budget import (
    NOVA_2_LITE,
    BudgetGuard,
    CostLedgerEntry,
    EvalBudget,
    append_to_ledger,
    ledger_totals,
    price_for,
    remaining_budget,
    tightest,
    utc_now_iso,
)
from evals.cases import EvalSplit
from evals.explanation_budget import JUDGE_MAX_OUTPUT_TOKENS, judge_ceiling, nova_ceiling
from evals.explanation_cases import ExplanationEvalCase, ExplanationModelInput
from evals.explanation_dataset import DATASET_NAME, ExplanationDataset, load_explanation_dataset
from evals.explanation_judge import (
    JUDGE_MODEL_ID,
    JUDGE_PROVIDER,
    RUBRIC,
    CountedJudge,
    JudgeAttempt,
    JudgeProviderError,
    JudgeRequest,
    JudgeVerdict,
    StructuredJudge,
    stored_verdict,
)
from evals.explanation_report import plan as explanation_plan
from evals.explanation_report import render as render_explanation
from evals.explanation_results import (
    NO_USAGE,
    ExplanationJudgeResult,
    NovaExplanationResult,
    Usage,
)
from evals.explanation_runner import (
    LIVE_MODE,
    ExplanationProviderFactory,
    generate,
    judge_explanations,
    judgeable,
    rescore,
)
from evals.explanation_store import (
    ExplanationResultStore,
    ExplanationRunHeader,
    ExplanationStoreError,
    read_run,
)
from evals.prompts import prompt_identity
from evals.summary import git_sha

from promisepatch.config import LlmProvider, Settings
from promisepatch.semantic import (
    SemanticJob,
    SemanticProvider,
    SemanticRequest,
    SemanticResult,
)

RESULTS_DIR = Path(".eval-results")
"""Where run artifacts land. Git-ignored: a run is a local fact about one machine."""

LEDGER = RESULTS_DIR / "explanation-cost-ledger.jsonl"
"""This gate's own ledger, deliberately not the customer-intent one.

The two evaluations price the same Nova model, and a shared file would make one gate's
allowance depend on what the other spent last month. A ceiling derived from *this* dataset is a
statement about *this* evaluation, so the spend it is compared against has to be too.
"""

GENERATION_SCOPES: Mapping[EvalSplit, SpendScope] = {
    EvalSplit.DEVELOPMENT: SpendScope.P4_8_NOVA_DEVELOPMENT_GENERATION,
    EvalSplit.HOLDOUT: SpendScope.P4_8_EXPLANATION_HOLDOUT,
}

JUDGING_SCOPES: Mapping[EvalSplit, SpendScope] = {
    EvalSplit.DEVELOPMENT: SpendScope.P4_8_NEMOTRON_DEVELOPMENT_JUDGING,
    EvalSplit.HOLDOUT: SpendScope.P4_8_EXPLANATION_HOLDOUT,
}
"""Which phrase pays for which split, per pass. The holdout maps to its own scope in both, so
neither development authorisation can reach a sealed case by any route."""

NVIDIA_API_KEY_VARIABLE = "NVIDIA_API_KEY"
NVIDIA_BASE_URL_VARIABLE = "NVIDIA_API_BASE_URL"
"""The only names this command looks under. A key is never printed, logged or persisted."""

VERDICT_TOOL_NAME = "record_verdict"
"""The one function the judge is given, and the only shape its answer may arrive in."""


class ExplanationRunRefusedError(RuntimeError):
    """The command will not run as asked, and no provider was built."""


# --------------------------------------------------------------------- reading configuration


def read_env_value(name: str, env_file: Path = Path(".env")) -> str | None:
    """One configured value, from the process environment or the local ``.env``, or ``None``.

    Reads one named variable and returns one value. It never yields the file and never yields a
    mapping of everything in it: a caller that wants to *say* something about a key calls
    :func:`nvidia_api_key_present` and gets a boolean.
    """
    from_environment = os.environ.get(name, "").strip()
    if from_environment:
        return from_environment
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        found, _, value = stripped.partition("=")
        if found.strip() != name:
            continue
        return value.strip().strip("\"'") or None
    return None


def read_nvidia_api_key(env_file: Path = Path(".env")) -> str | None:
    """The NVIDIA key, or ``None``. Handed to exactly one constructor and to nothing else."""
    return read_env_value(NVIDIA_API_KEY_VARIABLE, env_file)


def nvidia_api_key_present(env_file: Path = Path(".env")) -> bool:
    """Whether a key is available, as a boolean and only ever as a boolean."""
    return read_nvidia_api_key(env_file) is not None


def nvidia_hosted_endpoint() -> str:
    """The endpoint this judge is defined against, read from the adapter that owns it.

    Imported inside the body so that merely importing this module loads no vendor client, and
    so the value this command validates against and the value the adapter refuses anything else
    for cannot drift apart.
    """
    from promisepatch.integrations.nvidia import HOSTED_BASE_URL

    return HOSTED_BASE_URL


def nvidia_base_url(env_file: Path = Path(".env")) -> str:
    """The configured NVIDIA endpoint, or the documented one when nothing is configured."""
    return read_env_value(NVIDIA_BASE_URL_VARIABLE, env_file) or nvidia_hosted_endpoint()


# ------------------------------------------------------------------------------- refusals


def refuse_a_missing_nvidia_key(env_file: Path = Path(".env")) -> None:
    """No key, no judge. Refused here, before an authorisation could be mistaken for one."""
    if nvidia_api_key_present(env_file):
        return
    raise ExplanationRunRefusedError(
        f"judging needs {NVIDIA_API_KEY_VARIABLE} in the environment or in .env, and this "
        f"command does not look anywhere else for one. Nothing was called."
    )


def refuse_a_foreign_nvidia_endpoint(env_file: Path = Path(".env")) -> None:
    """A configured endpoint that is not the one this gate is defined against stops the run.

    Validated here and again by the adapter as the last line before a client, because a free
    endpoint's quota and an evaluation's identity are both spent by a request to the wrong
    host, and neither is recoverable afterwards.
    """
    from promisepatch.integrations.nvidia import NvidiaEndpointError, refuse_a_foreign_endpoint

    try:
        refuse_a_foreign_endpoint(nvidia_base_url(env_file))
    except NvidiaEndpointError as wrong_host:
        raise ExplanationRunRefusedError(str(wrong_host)) from wrong_host


def refuse_an_unauthorised_holdout(split: EvalSplit, authorisation: SpendAuthorisation) -> None:
    """The holdout is opened by its own phrase or not at all.

    The scope map already refuses a development phrase against a holdout run. This is the
    second statement of the same rule at the point of use, because "the sealed split was
    opened by accident" is the one failure in this gate that cannot be undone by re-running.
    """
    if split is not EvalSplit.HOLDOUT:
        return
    if authorisation.covers(SpendScope.P4_8_EXPLANATION_HOLDOUT):
        return
    raise ExplanationRunRefusedError(  # pragma: no cover - authorise() refuses first
        "the holdout requires "
        f"{required_phrase(SpendScope.P4_8_EXPLANATION_HOLDOUT)!r} and nothing else implies it"
    )


def refuse_a_dataset_that_moved(header: ExplanationRunHeader, dataset: ExplanationDataset) -> None:
    """A stored run measured a dataset; judging a different one would judge a different gate."""
    if header.dataset_hash == dataset.content_hash and header.dataset_version == dataset.version:
        return
    raise ExplanationRunRefusedError(
        f"{header.dataset_name} has moved since this run was generated: the file names "
        f"{header.dataset_version}/{header.dataset_hash[:12]} and the working tree has "
        f"{dataset.version}/{dataset.content_hash[:12]}. A verdict on a passage written from "
        f"other facts is not this passage's verdict."
    )


def refuse_a_moved_request(results: Sequence[NovaExplanationResult]) -> None:
    """A passage written under a different prompt or schema is not rejudged under this one."""
    prompt = prompt_identity(SemanticJob.VERBALISE)
    moved = sorted(
        {
            result.case_id
            for result in results
            if result.identity.prompt_system_hash != prompt.system_hash
            or result.identity.schema_hash != prompt.schema_hash
        }
    )
    if not moved:
        return
    raise ExplanationRunRefusedError(
        f"the production verbalise prompt or schema has moved since these passages were "
        f"written, so they cannot be judged as answers to the current question: "
        f"{', '.join(moved)}. Generate again rather than putting a fresh verdict on a stale "
        f"answer."
    )


def refuse_a_split_the_file_does_not_hold(header: ExplanationRunHeader, split: EvalSplit) -> None:
    if tuple(header.splits) == (split.value,):
        return
    raise ExplanationRunRefusedError(
        f"this file holds {', '.join(header.splits) or '(nothing)'} and the command names "
        f"{split.value}. One file is one split's run."
    )


# ------------------------------------------------------------------- the generation provider


@dataclass
class CallRecord:
    """What one case's provider calls actually used, measured at the seam that made them.

    Latency and tokens are recorded here rather than inferred from a total, because a report
    that quotes a p95 has to have measured each call, and because a stored result that carries
    its own usage can be re-scored for ever without a ledger beside it.
    """

    attempts: int = 0
    """How many calls were measured. A measured nought is a measurement; nought calls is not,
    and the two must not arrive at a percentile looking the same."""

    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def measured_latency_ms(self) -> int | None:
        return self.latency_ms if self.attempts else None

    def add(self, *, latency_ms: int, result: SemanticResult | None) -> None:
        self.attempts += 1
        self.latency_ms += latency_ms
        telemetry = None if result is None else result.telemetry
        if telemetry is None:
            return
        usage = telemetry.usage
        if usage.input_tokens is not None:
            self.input_tokens = (self.input_tokens or 0) + usage.input_tokens
        if usage.output_tokens is not None:
            self.output_tokens = (self.output_tokens or 0) + usage.output_tokens


class MeasuredProvider:
    """A provider that times what it does and keeps the usage of every attempt for one case.

    Wrapping rather than threading a stopwatch through the runner, for the reason the budget
    guard wraps: there is one path to a provider call and it is measured. It changes no request
    and reads no answer -- the result it returns is the one it was handed.
    """

    def __init__(self, inner: SemanticProvider, record: CallRecord) -> None:
        self._inner = inner
        self._record = record
        self.name = inner.name

    async def run(self, request: SemanticRequest) -> SemanticResult:
        started = time.perf_counter()
        result: SemanticResult | None = None
        try:
            result = await self._inner.run(request)
            return result
        finally:
            elapsed = round((time.perf_counter() - started) * 1000)
            self._record.add(latency_ms=elapsed, result=result)


def bedrock_factory(
    settings: Settings, authorisation: SpendAuthorisation
) -> ExplanationProviderFactory:
    """Production's own provider, behind the two guards that gate paid inference.

    The authorisation is taken as an argument rather than looked up, so there is no way to
    reach this function without one having been produced by :func:`evals.authorisation
    .authorise` from a phrase somebody typed. The test interlock is checked here because this
    is the last line before money: whatever route got here, a pytest process does not pass it.

    One client for the whole run, opened lazily by the adapter on its first call.
    """
    refuse_real_inference_under_test(authorisation.scope)
    from promisepatch.integrations.semantic_provider import build_semantic_provider

    provider = build_semantic_provider(settings)

    def build(model_input: ExplanationModelInput) -> SemanticProvider:
        return provider

    return build


def measured(
    factory: ExplanationProviderFactory, records: dict[str, CallRecord]
) -> ExplanationProviderFactory:
    """The same factory, with every provider it returns timed and its usage kept per case.

    Wrapped around whichever factory a run uses rather than built into one of them, so the
    measurement a report quotes is a property of the run and not of which provider answered.
    """

    def build(model_input: ExplanationModelInput) -> SemanticProvider:
        record = records.setdefault(model_input.case_id, CallRecord())
        return MeasuredProvider(factory(model_input), record)

    return build


# ------------------------------------------------------------------------ the live judge


class NvidiaJudge:
    """One structured verdict per request, from the pinned judge on NVIDIA's hosted endpoint.

    The whole of the judge transport: it builds one Chat Completions request whose system
    message is the frozen rubric, whose user message is one passage and the facts it was
    written from, and whose single forced function is the verdict contract. It parses nothing
    and believes nothing -- the arguments come back as they arrived and
    :class:`~evals.explanation_judge.StructuredJudge` decides whether they are a verdict.

    **A refused shape is not an outage.** A response with no call to the one function that was
    forced returns ``None`` as its payload, which the contract rejects and the corrective retry
    answers. Only a transport that could not be reached raises
    :class:`~evals.explanation_judge.JudgeProviderError`, because that is the failure the judge
    stop-rule counts and it must not be reachable by a model writing something odd.
    """

    name = JUDGE_PROVIDER

    def __init__(self, *, open_transport: Callable[[], Any], model_id: str) -> None:
        self._open_transport = open_transport
        self._opened: Any | None = None
        self.model_id: str | None = model_id
        self._model_id = model_id

    @classmethod
    def with_api_key(
        cls,
        *,
        api_key: str,
        model_id: str = JUDGE_MODEL_ID,
        base_url: str | None = None,
    ) -> NvidiaJudge:
        """A judge for one pinned model on the hosted endpoint, or a refusal.

        The key is taken as an argument and never looked up. It is held in the closure below,
        reaches exactly one place -- the SDK constructor -- and is never logged, never put in
        an exception message and never written to any artifact this repository produces.

        The endpoint is validated here as well as by the composition root, and the ordering is
        the point: this is the last line before a client could exist.
        """
        from promisepatch.integrations.nvidia import HOSTED_BASE_URL, refuse_a_foreign_endpoint
        from promisepatch.integrations.openai import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT_SECONDS

        endpoint = refuse_a_foreign_endpoint(base_url or HOSTED_BASE_URL)
        if not api_key:
            raise JudgeProviderError(
                "no NVIDIA API key was supplied to the judge, and it does not look for one"
            )

        def open_transport() -> Any:
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                base_url=endpoint,
                timeout=DEFAULT_TIMEOUT_SECONDS,
                max_retries=DEFAULT_MAX_RETRIES,
            )
            return client.chat.completions

        return cls(open_transport=open_transport, model_id=model_id)

    def transport(self) -> Any:
        if self._opened is None:
            try:
                self._opened = self._open_transport()
            except Exception as error:
                raise JudgeProviderError(
                    f"the NVIDIA client could not be prepared: {type(error).__name__}"
                ) from error
        return self._opened

    async def invoke(self, request: JudgeRequest, *, correction: str | None) -> JudgeAttempt:
        payload = build_judge_chat_request(request, model_id=self._model_id, correction=correction)
        transport = self.transport()
        started = time.perf_counter()
        response = await asyncio.to_thread(self._call, transport, payload)
        elapsed = round((time.perf_counter() - started) * 1000)
        body = as_mapping(response)
        return JudgeAttempt(
            payload=extract_verdict_arguments(body),
            usage=read_judge_usage(body, latency_ms=elapsed),
        )

    def _call(self, transport: Any, request: Mapping[str, Any]) -> object:
        """One call, with every SDK failure translated into one this gate understands.

        The class name and nothing else about a fault: an exception message from a vendor SDK
        is the one place a credential or a prompt could end up in an artifact.
        """
        try:
            return transport.create(**request)
        except Exception as error:
            raise JudgeProviderError(
                f"the judge could not be reached: {type(error).__name__}"
            ) from error


def verdict_function() -> dict[str, Any]:
    """The one function the judge may call, derived from the contract that validates its answer.

    Generated from :class:`~evals.explanation_judge.JudgeVerdict` rather than hand-written, so
    the shape the judge is shown and the shape its answer is refused against cannot drift.
    """
    return {
        "type": "function",
        "function": {
            "name": VERDICT_TOOL_NAME,
            "description": "Record one verdict about one passage.",
            "parameters": JudgeVerdict.model_json_schema(),
        },
    }


def build_judge_chat_request(
    request: JudgeRequest, *, model_id: str, correction: str | None
) -> dict[str, Any]:
    """The exact payload for one judging attempt. Pure, so a test can read it in full.

    The rubric is a system message and the passage is inside a user message, the same split
    production makes: what a model wrote arrives where content arrives, never where the rules
    do. A correction is a second user turn rather than an edit of the first, so the judge can
    see what it said and why it was refused while the original question stays the question.
    """
    from promisepatch.integrations.nvidia import NEMOTRON_DECODING

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": RUBRIC},
        {"role": "user", "content": request.content()},
    ]
    if correction is not None:
        messages.append({"role": "assistant", "content": "(previous answer)"})
        messages.append({"role": "user", "content": correction})
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "tools": [verdict_function()],
        "tool_choice": {"type": "function", "function": {"name": VERDICT_TOOL_NAME}},
        "temperature": NEMOTRON_DECODING.temperature,
        "max_completion_tokens": JUDGE_MAX_OUTPUT_TOKENS,
    }
    if NEMOTRON_DECODING.top_p is not None:
        payload["top_p"] = NEMOTRON_DECODING.top_p
    if NEMOTRON_DECODING.reasoning_effort is not None:
        payload["reasoning_effort"] = NEMOTRON_DECODING.reasoning_effort
    return payload


def as_mapping(response: object) -> Mapping[str, Any]:
    """One answer as plain data, whatever object the SDK handed back."""
    if isinstance(response, Mapping):
        return response
    dump = getattr(response, "model_dump", None)
    if callable(dump):
        dumped = dump()
        if isinstance(dumped, Mapping):
            return dumped
    return {}


def extract_verdict_arguments(response: Mapping[str, Any]) -> object:
    """The verdict the judge produced, or ``None`` when it produced none.

    ``None`` rather than an exception on purpose. A model that answered in prose instead of
    calling the one function it was given has broken the contract, and the contract's own
    refusal -- and its one corrective retry -- is where that belongs. Reading the prose would
    be exactly the free-form parsing a structured verdict exists to avoid.
    """
    for choice in _sequence(response.get("choices")):
        message = choice.get("message") if isinstance(choice, Mapping) else None
        if not isinstance(message, Mapping):
            continue
        for call in _sequence(message.get("tool_calls")):
            function = call.get("function") if isinstance(call, Mapping) else None
            if not isinstance(function, Mapping) or function.get("name") != VERDICT_TOOL_NAME:
                continue
            return _decode(function.get("arguments"))
    return None


def _decode(arguments: object) -> object:
    if isinstance(arguments, Mapping):
        return arguments
    if not isinstance(arguments, str):
        return None
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return None


def _sequence(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def read_judge_usage(response: Mapping[str, Any], *, latency_ms: int) -> Usage:
    """What one attempt used, if the endpoint said. Absence stays absent, never zero."""
    usage = response.get("usage") or {}
    if not isinstance(usage, Mapping):  # pragma: no cover - the SDK types this field
        return Usage(latency_ms=latency_ms)
    return Usage(
        input_tokens=_as_int(usage.get("prompt_tokens")),
        output_tokens=_as_int(usage.get("completion_tokens")),
        latency_ms=latency_ms,
    )


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# ---------------------------------------------------------------------------- the passes


def narrow(dataset: ExplanationDataset, case_ids: frozenset[str]) -> ExplanationDataset:
    """The same dataset with only the named cases in it. Identity is unchanged and unused."""
    return ExplanationDataset(
        version=dataset.version,
        provenance=dataset.provenance,
        cases=tuple(case for case in dataset.cases if case.id in case_ids),
    )


def generation_budget(
    cases: Sequence[ExplanationEvalCase], namespace: argparse.Namespace
) -> EvalBudget:
    """The ceiling this generation run may use: the derived one, narrowed twice.

    Narrowed by anything the operator typed, and narrowed again by what this gate's own ledger
    says it has already spent. Composition only: a flag can make the bound tighter and never
    wider than the ceiling the dataset derives.
    """
    derived = nova_ceiling(cases).budget()
    typed = EvalBudget(
        max_calls=namespace.max_calls,
        max_estimated_usd=(
            None if namespace.max_estimated_usd is None else Decimal(namespace.max_estimated_usd)
        ),
    )
    spent = ledger_totals(
        LEDGER, mode=LIVE_MODE, provider=NOVA_2_LITE.provider, model_id=namespace.model
    )
    return remaining_budget(tightest(derived, typed), spent)


async def run_generation(namespace: argparse.Namespace) -> int:
    """Buy one passage per case in one split, writing each one down as it arrives."""
    dataset = load_explanation_dataset()
    split = EvalSplit(namespace.split)
    selected = dataset.split([split])
    if not selected.cases:  # pragma: no cover - the dataset always holds both splits
        raise ExplanationRunRefusedError(f"{split.value} selected no cases")

    budget = generation_budget(selected.cases, namespace)
    authorisation = authorise(
        namespace.authorise_paid_inference,
        GENERATION_SCOPES[split],
        max_calls=budget.max_calls,
        max_estimated_usd=budget.max_estimated_usd,
    )
    refuse_an_unauthorised_holdout(split, authorisation)
    authorisation.require(GENERATION_SCOPES[split])

    prompt = prompt_identity(SemanticJob.VERBALISE)
    run_id = namespace.run_id or uuid.uuid4().hex[:12]
    header = ExplanationRunHeader(
        run_id=run_id,
        started_at=utc_now_iso(),
        git_sha=git_sha(),
        dataset_name=DATASET_NAME,
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        provider=NOVA_2_LITE.provider,
        model_id=namespace.model,
        mode=LIVE_MODE,
        splits=(split.value,),
        prompt_system_hash=prompt.system_hash,
        schema_hash=prompt.schema_hash,
        region=namespace.region,
    )
    store = ExplanationResultStore(_results_path(namespace, header.run_id), header)
    outstanding = narrow(
        selected, frozenset(case.id for case in selected.cases) - store.completed()
    )
    if not outstanding.cases:
        print(f"every {split.value} case is already recorded in {store.path}. Nothing bought.")
        return 0

    guard = BudgetGuard(budget, price=price_for(NOVA_2_LITE.provider, namespace.model), live=True)
    records: dict[str, CallRecord] = {}
    chosen = namespace.factory or bedrock_factory(_settings(namespace), authorisation)
    factory = measured(chosen, records)

    def written(result: NovaExplanationResult) -> None:
        store.record_generation(_with_measured_usage(result, records))

    outcome = await generate(
        outstanding,
        factory,
        guard=guard,
        provider_name=NOVA_2_LITE.provider,
        model_id=namespace.model,
        git_sha=store.header.git_sha,
        run_id=store.header.run_id,
        mode=LIVE_MODE,
        on_result=written,
    )
    _append_generation_ledger(store, guard, namespace)
    print(render_generation(store, guard, split))
    return 0 if len(outcome.results) == len(outstanding.cases) else 1


def _with_measured_usage(
    result: NovaExplanationResult, records: Mapping[str, CallRecord]
) -> NovaExplanationResult:
    """One result with the latency and tokens its own calls used, measured at the seam.

    The runner records the logical call and the attempts, which are facts about the acceptance
    path. What a call cost and how long it took are facts about the transport, and this is
    where they are known.
    """
    record = records.get(result.case_id)
    if record is None:  # pragma: no cover - a factory that never ran
        return result
    usage = result.usage.model_copy(
        update={
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "latency_ms": record.measured_latency_ms,
        }
    )
    return result.model_copy(update={"usage": usage})


async def run_judging(namespace: argparse.Namespace) -> int:
    """Buy one verdict per accepted passage, from passages already on disk."""
    path = Path(namespace.results)
    header, generations, judgements = read_run(path)
    dataset = load_explanation_dataset()
    split = EvalSplit(namespace.split)
    refuse_a_split_the_file_does_not_hold(header, split)
    refuse_a_dataset_that_moved(header, dataset)
    refuse_a_moved_request(generations)

    selected = dataset.split([split])
    accepted = judgeable(generations)
    outstanding = tuple(
        result for result in accepted if result.case_id not in {j.case_id for j in judgements}
    )
    ceiling = judge_ceiling(selected.cases)
    if not outstanding:
        print(f"every accepted passage in {path} already has a verdict. Nothing bought.")
        return 0

    authorisation = authorise(
        namespace.authorise_paid_inference,
        JUDGING_SCOPES[split],
        max_calls=len(outstanding),
    )
    refuse_an_unauthorised_holdout(split, authorisation)
    authorisation.require(JUDGING_SCOPES[split])

    if namespace.judge is None:
        refuse_a_missing_nvidia_key()
        refuse_a_foreign_nvidia_endpoint()
        refuse_real_inference_under_test(authorisation.scope)
        key = read_nvidia_api_key()
        provider: Any = NvidiaJudge.with_api_key(
            api_key=key or "", model_id=namespace.judge_model, base_url=nvidia_base_url()
        )
    else:
        provider = namespace.judge

    store = ExplanationResultStore(path, header)
    judge = CountedJudge(
        StructuredJudge(provider),
        max_logical_calls=min(len(outstanding), ceiling.logical_calls),
    )
    outcome = await judge_explanations(
        selected,
        outstanding,
        judge,
        run_id=header.run_id,
        on_result=store.record_judgement,
    )
    print(render_judging(store, outcome.stopped, ceiling.logical_calls))
    return 1 if outcome.stopped is not None else 0


# --------------------------------------------------------------------------- zero-call output


def stored_summary(path: Path) -> tuple[ExplanationRunHeader, Any]:
    """Rebuild one run's whole summary from disk. Zero Nova calls and zero judge calls."""
    header, generations, judgements = read_run(path)
    dataset = load_explanation_dataset()
    splits = [EvalSplit(value) for value in header.splits]
    generation_usage = _total(result.usage for result in generations)
    judge_usage = _total(result.usage for result in judgements)
    summary = rescore(
        dataset.split(splits or None),
        generations,
        judgements,
        run_id=header.run_id,
        provider=header.provider,
        model_id=header.model_id,
        judge_provider=JUDGE_PROVIDER if judgements else None,
        judge_model_id=_judge_model(judgements),
        generation_usage=generation_usage,
        judge_usage=judge_usage,
        git_sha=header.git_sha,
        mode=header.mode,
    )
    return header, summary


def _judge_model(judgements: Sequence[ExplanationJudgeResult]) -> str | None:
    for judgement in judgements:
        return judgement.identity.judge_model_id
    return None


def _total(usages: Any) -> Usage:
    total = NO_USAGE
    for usage in usages:
        total = total.plus(usage)
    return total


def run_report(namespace: argparse.Namespace) -> int:
    """Print the gate's own report from stored results, and call nothing."""
    path = Path(namespace.results)
    header, summary = stored_summary(path)
    if namespace.json:
        print(json.dumps(summary.as_payload(), indent=2))
    else:
        print(render_explanation(summary))
        print(render_latency(path))
    if namespace.out:
        directory = Path(namespace.out)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"explanation-{header.run_id}-summary.json"
        target.write_text(json.dumps(summary.as_payload(), indent=2), encoding="utf-8")
        print(f"wrote {target}")
    return 0 if summary.gate_status == "pass" else 1


def percentile(values: Sequence[int], fraction: float) -> int | None:
    """The nearest-rank percentile of a measured series, or ``None`` when nothing measured."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def render_latency(path: Path) -> str:
    """p50 and p95 for each pass, over the calls that reported a latency."""
    _header, generations, judgements = read_run(path)
    lines = ["LATENCY", "-------"]
    for label, series in (
        ("nova", [r.usage.latency_ms for r in generations if r.usage.latency_ms is not None]),
        ("judge", [r.usage.latency_ms for r in judgements if r.usage.latency_ms is not None]),
    ):
        p50 = percentile(series, 0.50)
        p95 = percentile(series, 0.95)
        lines.append(f"  {label.ljust(14)} p50 {_ms(p50)}  p95 {_ms(p95)}  (n={len(series)})")
    return "\n".join(lines)


def _ms(value: int | None) -> str:
    return "--" if value is None else f"{value} ms"


def _count(value: int | None) -> str:
    """A measured count, or ``--``. Never a zero standing in for something nobody reported."""
    return "--" if value is None else str(value)


def render_generation(store: ExplanationResultStore, guard: BudgetGuard, split: EvalSplit) -> str:
    """What the generation pass did, in the terms the checkpoint after it has to check."""
    results = store.generations
    accepted = sum(1 for result in results if result.accepted)
    fallback = len(results) - accepted
    failures = sum(1 for result in results if result.failure is not None)
    provider_failures = sum(
        1 for result in results if result.failure is not None and "PROVIDER" in result.failure.value
    )
    latencies = [r.usage.latency_ms for r in results if r.usage.latency_ms is not None]
    reported = Usage(
        input_tokens=guard.spend.input_tokens if guard.spend.tokens_reported else None,
        output_tokens=guard.spend.output_tokens if guard.spend.tokens_reported else None,
    )
    return "\n".join(
        [
            "P4.8 NOVA GENERATION",
            "--------------------",
            f"  run id             {store.header.run_id}",
            f"  git sha            {store.header.git_sha}",
            f"  dataset            {store.header.dataset_name} {store.header.dataset_version} "
            f"{store.header.dataset_hash[:12]}",
            f"  split              {split.value}",
            f"  results file       {store.path}",
            "",
            f"  cases recorded     {len(results)}",
            f"  accepted prose     {accepted}",
            f"  fallback           {fallback}",
            f"  provider failures  {provider_failures}",
            f"  validator refusals {failures - provider_failures}",
            "",
            f"  logical calls      {guard.spend.calls}",
            f"  provider attempts  {guard.spend.attempts}",
            f"  input tokens       {_count(reported.input_tokens)}",
            f"  output tokens      {_count(reported.output_tokens)}",
            f"  estimated USD      "
            f"{'--' if guard.spend.estimated_usd is None else f'${guard.spend.estimated_usd}'}",
            f"  latency p50/p95    {_ms(percentile(latencies, 0.5))} / "
            f"{_ms(percentile(latencies, 0.95))}",
            "",
            f"  holdout touched    {sum(1 for r in results if r.split is EvalSplit.HOLDOUT)}",
        ]
    )


def render_judging(store: ExplanationResultStore, stopped: str | None, ceiling: int) -> str:
    judgements = store.judgements
    scored = sum(1 for judgement in judgements if judgement.scored)
    usage = _total(judgement.usage for judgement in judgements)
    latencies = [j.usage.latency_ms for j in judgements if j.usage.latency_ms is not None]
    return "\n".join(
        [
            "P4.8 NEMOTRON JUDGING",
            "---------------------",
            f"  verdicts recorded  {len(judgements)}",
            f"  scored             {scored}",
            f"  unscored           {len(judgements) - scored}",
            f"  logical calls      {usage.logical_calls} (ceiling {ceiling})",
            f"  provider attempts  {usage.provider_attempts}",
            f"  input tokens       {_count(usage.input_tokens)}",
            f"  output tokens      {_count(usage.output_tokens)}",
            "  billing mode       free_hosted_prototype",
            "  known USD          not modelled -- no published per-token price",
            f"  latency p50/p95    {_ms(percentile(latencies, 0.5))} / "
            f"{_ms(percentile(latencies, 0.95))}",
            f"  stopped            {stopped or 'no'}",
        ]
    )


def run_review(namespace: argparse.Namespace) -> int:
    """The manual-review ledger: every case, its passage, its flags and its scores.

    Printed rather than decided. Nothing here writes a disposition: the whole point of the
    ledger is that a person reads the passages and says what they think, and a column somebody
    filled in automatically would be the LLM judge's opinion wearing a reviewer's name.
    """
    path = Path(namespace.results)
    _header, generations, judgements = read_run(path)
    by_case = {judgement.case_id: judgement for judgement in judgements}
    payload = [_review_row(result, by_case.get(result.case_id)) for result in generations]
    if namespace.json:
        print(json.dumps(payload, indent=2))
        return 0
    for row in payload:
        print(f"--- {row['case_id']}  [{row['family']}]  source={row['source']}")
        print(f"    passage: {row['speech']}")
        print(f"    structural: {row['structural']}")
        print(f"    flags: {row['flags']}")
        print(f"    scores: {row['scores']}")
        print(f"    judge: {row['rationale']}")
        print("    manual_disposition: (unreviewed)")
    return 0


def _review_row(
    result: NovaExplanationResult, judgement: ExplanationJudgeResult | None
) -> dict[str, object]:
    verdict = None if judgement is None else stored_verdict(judgement)
    flags: dict[str, object] = {}
    scores: dict[str, object] = {}
    if verdict is not None:
        dumped = verdict.model_dump(mode="json")
        flags = {key: value for key, value in dumped.items() if isinstance(value, bool)}
        scores = {key: value for key, value in dumped.items() if isinstance(value, int)}
    return {
        "case_id": result.case_id,
        "family": result.family.value,
        "source": result.source.value,
        "speech": result.speech,
        "words": result.word_count,
        "structural": "accepted"
        if result.accepted
        else (result.failure.value if result.failure else "fallback"),
        "detail": result.detail,
        "flags": flags,
        "scores": scores,
        "rationale": None if verdict is None else verdict.brief_rationale,
        "outcome": None if judgement is None else judgement.outcome.value,
        "manual_disposition": None,
    }


def run_plan(namespace: argparse.Namespace) -> int:
    dataset = load_explanation_dataset()
    splits = None if namespace.split is None else [EvalSplit(namespace.split)]
    print(explanation_plan(dataset, splits))
    print()
    print("AUTHORISATION THIS COMMAND WOULD NEED")
    print("-------------------------------------")
    for split in splits or list(EvalSplit):
        print(f"  generate --split {split.value}: {required_phrase(GENERATION_SCOPES[split])}")
        print(f"  judge    --split {split.value}: {required_phrase(JUDGING_SCOPES[split])}")
    print()
    print("  clients constructed          0")
    print("  model calls                  0")
    return 0


# ------------------------------------------------------------------------------ plumbing


def _settings(namespace: argparse.Namespace) -> Settings:
    return Settings(
        llm_provider=LlmProvider.BEDROCK,
        bedrock_model_id=namespace.model,
        aws_region=namespace.region,
    )


def _results_path(namespace: argparse.Namespace, run_id: str) -> Path:
    if namespace.results:
        return Path(namespace.results)
    return RESULTS_DIR / f"explanation-{run_id}.jsonl"


def _append_generation_ledger(
    store: ExplanationResultStore, guard: BudgetGuard, namespace: argparse.Namespace
) -> None:
    """One line of what this pass cost, in the terms a later pass is measured against."""
    header = store.header
    append_to_ledger(
        LEDGER,
        CostLedgerEntry(
            run_id=header.run_id,
            recorded_at=utc_now_iso(),
            git_sha=header.git_sha,
            dataset_version=header.dataset_version,
            dataset_hash=header.dataset_hash,
            provider=header.provider,
            model_id=namespace.model,
            mode=header.mode,
            calls=guard.spend.calls,
            attempts=guard.spend.attempts,
            input_tokens=guard.spend.input_tokens if guard.spend.tokens_reported else None,
            output_tokens=guard.spend.output_tokens if guard.spend.tokens_reported else None,
            estimated_usd=(
                None if guard.spend.estimated_usd is None else str(guard.spend.estimated_usd)
            ),
            pricing_snapshot=NOVA_2_LITE.snapshot_date.isoformat(),
            jobs=(SemanticJob.VERBALISE.value,),
        ),
    )


def _add_live_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--live",
        action="store_true",
        help="name the code path that reaches a provider. Not permission to spend.",
    )
    parser.add_argument(
        "--authorise-paid-inference",
        default=None,
        help="the scope-bound phrase that pays for this pass. Never defaulted.",
    )
    parser.add_argument(
        "--split",
        required=True,
        choices=[split.value for split in EvalSplit],
        help="the one split this pass covers. The holdout maps to its own authorisation.",
    )
    parser.add_argument("--results", default=None, help="the run file to write or continue")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.run_explanation_eval",
        description=(
            "The P4.8 explanation quality gate against real models. Generation and judging are "
            "separately authorised; report and review call nothing."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="print identity, ceilings and authorisations")
    plan.add_argument("--split", default=None, choices=[split.value for split in EvalSplit])
    plan.set_defaults(handler=run_plan)

    generation = commands.add_parser("generate", help="buy one passage per case")
    _add_live_arguments(generation)
    generation.add_argument("--model", default=NOVA_2_LITE.model_id)
    generation.add_argument("--region", default="us-east-1")
    generation.add_argument("--run-id", default=None)
    generation.add_argument("--max-calls", type=int, default=None)
    generation.add_argument("--max-estimated-usd", default=None)
    generation.set_defaults(handler=run_generation, is_async=True, factory=None)

    judging = commands.add_parser("judge", help="buy one verdict per accepted passage")
    _add_live_arguments(judging)
    judging.add_argument("--judge-model", default=JUDGE_MODEL_ID)
    judging.set_defaults(handler=run_judging, is_async=True, judge=None)

    report = commands.add_parser("report", help="rebuild the gate report from a run file")
    report.add_argument("--results", required=True)
    report.add_argument("--json", action="store_true")
    report.add_argument("--out", default=None)
    report.set_defaults(handler=run_report)

    review = commands.add_parser("review", help="print the manual-review ledger for a run file")
    review.add_argument("--results", required=True)
    review.add_argument("--json", action="store_true")
    review.set_defaults(handler=run_review)

    return parser


def refuse_an_incoherent_command(namespace: argparse.Namespace) -> None:
    """``--live`` and an authorisation are two halves of one statement, and both are required."""
    if not hasattr(namespace, "live"):
        return
    if namespace.live and namespace.authorise_paid_inference is None:
        return
    if not namespace.live and namespace.authorise_paid_inference is not None:
        raise ExplanationRunRefusedError(
            "an authorisation phrase was typed without --live. Nothing was run: a command that "
            "names a charge and not the path that makes it is a command whose intent is unclear."
        )
    if not namespace.live:
        raise ExplanationRunRefusedError(
            "this pass reaches a provider and needs --live, plus the authorisation phrase for "
            "the split it names. Run the plan command to see which phrase that is."
        )


def main(argv: Sequence[str] | None = None) -> int:
    namespace = build_parser().parse_args(argv)
    try:
        refuse_an_incoherent_command(namespace)
        if getattr(namespace, "is_async", False):
            result: int = asyncio.run(namespace.handler(namespace))
            return result
        code: int = namespace.handler(namespace)
        return code
    except (
        ExplanationRunRefusedError,
        ExplanationStoreError,
        SpendNotAuthorisedError,
    ) as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
