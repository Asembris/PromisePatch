"""The live benchmark path, proved without a model, a credential or a network.

A live run differs from a replay in exactly one thing: where the answers come from. Everything
else -- the budget accounting, the persistence, the resume, the stop conditions, the identity
check on which model answered -- is the same code, and all of it is testable with a provider
that does nothing but count.

That is the point of the seam. :data:`~evals.runner.ProviderFactory` is a parameter, so the
expensive half of the benchmark can be exercised for free, and the parts that decide when to
stop spending are proved *before* anything is spent rather than discovered during it.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from evals.budget import (
    BudgetedSemanticProvider,
    BudgetExhaustedError,
    BudgetGuard,
    EvalBudget,
    LedgerTotals,
    ModelPrice,
    price_for,
    remaining_budget,
)
from evals.cases import EvalSplit, ModelInput
from evals.dataset import GoldDataset, load_dataset
from evals.runner import (
    LIVE_MODE,
    ScriptedAnswers,
    StopPolicy,
    new_run_id,
    run_cases,
    scripted_provider,
)
from evals.store import ResultStore, RunHeader, StoreError, read_run
from evals.summary import build_summary

from promise_graph.model import ExceptionCategory
from promisepatch.semantic import (
    Attempt,
    CandidateNodeType,
    JobSpec,
    SemanticJob,
    SemanticProviderError,
    SemanticTelemetry,
    SemanticUsage,
    StructuredSemanticProvider,
)
from promisepatch.semantic.fake import DEFAULT_REPLIES

NOVA = "us.amazon.nova-2-lite-v1:0"


@pytest.fixture(scope="module")
def dataset() -> GoldDataset:
    return load_dataset()


@pytest.fixture(scope="module")
def answers() -> ScriptedAnswers:
    return ScriptedAnswers.from_file()


class Recorder(StructuredSemanticProvider):
    """A provider that answers from a payload and remembers being asked. Reaches nothing.

    It subclasses the production acceptance path rather than implementing the port directly,
    which matters: its answers go through :func:`promisepatch.semantic.jobs.validate` and the
    single corrective retry exactly as a real model's would. A double that returned values past
    the gate would prove the harness handles answers no provider could actually give.
    """

    name = "recorder"

    def __init__(
        self,
        *,
        model_id: str = NOVA,
        payload: object | None = None,
        usage: SemanticUsage | None = None,
        failures: int = 0,
    ) -> None:
        self.asked: list[str] = []
        self.model_id = model_id
        self._payload = payload
        self._usage = usage or SemanticUsage(input_tokens=400, output_tokens=20, latency_ms=250)
        self._failures = failures

    async def invoke(self, spec: JobSpec, content: str, *, correction: str | None) -> Attempt:
        self.asked.append(spec.job.value)
        if self._failures > 0:
            self._failures -= 1
            raise SemanticProviderError("the endpoint did not answer", retryable=True)
        payload = self._payload if self._payload is not None else DEFAULT_REPLIES[spec.job]
        return Attempt(payload=payload, usage=self._usage)


BINDS_A_REAL_INGREDIENT = {
    "category": ExceptionCategory.SUPPLY_NOT_RECEIVED.value,
    "bindings": [
        {
            "node_type": CandidateNodeType.RESOURCE.value,
            "node_id": "res-blueberries",
            "confidence": 1.0,
            "evidence_span": "berries",
        }
    ],
    "out_of_scope": False,
}
"""A well-formed reading that names a real, offered ingredient (blueberries are stocked).

Given to a sentence whose gold answer is a person, it is the failure the fallback boundary
exists to prevent: a model talking the system into binding something it must not bind.
"""


def one_of_each(dataset: GoldDataset) -> GoldDataset:
    """A worker case a model is asked about, one it is not, and one customer reply."""
    asked = next(case for case in dataset.worker if case.asked)
    unasked = next(case for case in dataset.worker if not case.asked)
    return GoldDataset(
        version=dataset.version,
        worker=(asked, unasked),
        customer=dataset.customer[:1],
        provenance=dataset.provenance,
    )


def guard_for(budget: EvalBudget | None = None, *, live: bool = True) -> BudgetGuard:
    return BudgetGuard(budget or EvalBudget(), price=price_for("bedrock", NOVA), live=live)


def header_for(dataset: GoldDataset, *, model_id: str = NOVA) -> RunHeader:
    return RunHeader(
        run_id=new_run_id(),
        started_at="2026-09-07T00:00:00+00:00",
        git_sha="abc123",
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        prompts=({"job": "interpret_utterance", "system_hash": "aaaa", "schema_hash": "bbbb"},),
        provider="recorder",
        model_id=model_id,
        mode=LIVE_MODE,
        splits=("development",),
    )


# -------------------------------------------------------------- the budget cannot be dodged


async def test_a_factory_cannot_hand_in_a_provider_that_escapes_the_accounting(
    dataset: GoldDataset,
) -> None:
    """The wrapper is applied by the runner, so there is no unmetered path to a provider.

    This is the property the whole spending policy rests on. A caller supplies something that
    can answer; it does not supply the thing that counts, and it cannot opt out of it.
    """
    provider = Recorder()
    narrowed = one_of_each(dataset)
    guard = guard_for()

    outcome = await run_cases(
        narrowed,
        lambda _: provider,
        guard=guard,
        provider_name=provider.name,
        mode=LIVE_MODE,
        expected_model_id=NOVA,
    )

    # Two cases were asked about; the third is a sentence the lexicon reads.
    assert len(provider.asked) == 2
    assert guard.spend.calls == 2
    assert outcome.guard is guard
    assert guard.spend.input_tokens == 800
    assert guard.spend.estimated_usd is not None and guard.spend.estimated_usd > 0


async def test_the_wrapper_refuses_the_call_that_would_cross_the_cap(
    dataset: GoldDataset,
) -> None:
    """A cap raises before the provider is reached, not after it has answered."""
    provider = Recorder()
    with pytest.raises(BudgetExhaustedError):
        await run_cases(
            dataset,
            lambda _: provider,
            guard=guard_for(EvalBudget(max_calls=2)),
            provider_name=provider.name,
            mode=LIVE_MODE,
        )
    assert len(provider.asked) == 2


async def test_a_dollar_cap_on_an_unpriced_model_refuses_before_the_first_call() -> None:
    """An unpriced model cannot be run under a dollar budget, whatever else is in the catalog.

    Not Haiku 4.5 any more: it is priced, because the customer-intent challenger measures it.
    What the rule stands between a run and is every model nobody has benchmarked, which is
    every id that is not a key in the catalog.
    """
    from evals.budget import PricingUnavailableError

    unpriced = "example.unbenchmarked-model-v1:0"
    assert price_for("bedrock", unpriced) is None
    with pytest.raises(PricingUnavailableError):
        BudgetGuard(
            EvalBudget(max_estimated_usd=Decimal("0.20")),
            price=price_for("bedrock", unpriced),
            live=True,
        )


def test_a_global_ceiling_is_reduced_by_what_earlier_runs_already_spent() -> None:
    """Two splits share one allowance, so the second starts with what the first left."""
    ceiling = EvalBudget(
        max_calls=110,
        max_input_tokens=300_000,
        max_output_tokens=30_000,
        max_estimated_usd=Decimal("0.20"),
    )
    spent = LedgerTotals(
        runs=1,
        calls=50,
        attempts=51,
        input_tokens=40_000,
        output_tokens=1_200,
        estimated_usd=Decimal("0.015"),
    )
    left = remaining_budget(ceiling, spent)
    assert left.max_calls == 60
    assert left.max_input_tokens == 260_000
    assert left.max_output_tokens == 28_800
    assert left.max_estimated_usd == Decimal("0.185")


def test_an_exhausted_allowance_never_goes_negative() -> None:
    """A run with nothing left gets zero, which the guard refuses on its first call."""
    ceiling = EvalBudget(max_calls=10, max_estimated_usd=Decimal("0.02"))
    left = remaining_budget(ceiling, LedgerTotals(calls=99, estimated_usd=Decimal("1.00")))
    assert left.max_calls == 0
    assert left.max_estimated_usd == Decimal(0)


# ------------------------------------------------------------------- nothing is bought twice


async def test_each_result_is_written_down_as_it_happens(
    dataset: GoldDataset, tmp_path: Path
) -> None:
    """A crash after the last case must not lose the calls that produced the first."""
    narrowed = one_of_each(dataset)
    store = ResultStore(tmp_path / "run.jsonl", header_for(dataset))
    written: list[str] = []

    def record(result: object) -> None:
        store.record(result)  # type: ignore[arg-type]
        written.append(read_run(store.path)[0].run_id)

    provider = Recorder()
    await run_cases(
        narrowed,
        lambda _: provider,
        guard=guard_for(),
        provider_name=provider.name,
        mode=LIVE_MODE,
        on_result=record,
    )

    _, results = read_run(store.path)
    assert len(results) == len(narrowed.cases)
    assert len(written) == len(narrowed.cases)


async def test_a_resumed_run_reads_its_answers_back_instead_of_buying_them_again(
    dataset: GoldDataset, tmp_path: Path
) -> None:
    """The whole point of persisting: a second attempt costs only what the first did not."""
    narrowed = one_of_each(dataset)
    header = header_for(dataset)
    first_store = ResultStore(tmp_path / "run.jsonl", header)
    first_provider = Recorder()
    await run_cases(
        narrowed,
        lambda _: first_provider,
        guard=guard_for(),
        provider_name=first_provider.name,
        mode=LIVE_MODE,
        on_result=first_store.record,
    )
    assert len(first_provider.asked) == 2

    second_store = ResultStore(tmp_path / "run.jsonl", header)
    second_provider = Recorder()
    second_guard = guard_for()
    outcome = await run_cases(
        narrowed,
        lambda _: second_provider,
        guard=second_guard,
        provider_name=second_provider.name,
        mode=LIVE_MODE,
        reuse=second_store.existing,
        on_result=second_store.record,
    )

    assert second_provider.asked == []
    assert second_guard.spend.calls == 0
    assert outcome.reused == len(narrowed.cases)
    assert len(outcome.results) == len(narrowed.cases)
    assert len(outcome.worker_scores) + len(outcome.customer_scores) == len(narrowed.cases)


async def test_a_rebuilt_summary_matches_the_one_the_run_produced(
    dataset: GoldDataset, tmp_path: Path
) -> None:
    """A report that failed to render is recoverable, and recovers the same numbers."""
    narrowed = one_of_each(dataset)
    header = header_for(dataset)
    store = ResultStore(tmp_path / "run.jsonl", header)
    provider = Recorder()
    first = await run_cases(
        narrowed,
        lambda _: provider,
        guard=guard_for(),
        provider_name=provider.name,
        mode=LIVE_MODE,
        on_result=store.record,
    )

    reopened = ResultStore(tmp_path / "run.jsonl", header)
    rebuilt = await run_cases(
        narrowed,
        lambda _: pytest.fail("a rebuild must not ask a provider anything"),
        guard=guard_for(),
        provider_name=provider.name,
        mode=LIVE_MODE,
        reuse=reopened.existing,
    )

    assert [result.model_dump() for result in rebuilt.results] == [
        result.model_dump() for result in first.results
    ]
    original = build_summary(dataset, first, mode=LIVE_MODE)
    recovered = build_summary(dataset, rebuilt, mode=LIVE_MODE)
    assert recovered.worker == original.worker
    assert recovered.customer == original.customer
    assert recovered.gate_status == original.gate_status


def test_a_result_file_from_a_different_run_is_refused_rather_than_appended_to(
    dataset: GoldDataset, tmp_path: Path
) -> None:
    """Blending two experiments into one summary is the error this check exists to prevent."""
    ResultStore(tmp_path / "run.jsonl", header_for(dataset))
    other = header_for(dataset, model_id="some.other-model-v1:0")
    with pytest.raises(StoreError) as raised:
        ResultStore(tmp_path / "run.jsonl", other)
    assert "model_id" in str(raised.value)


# --------------------------------------------------------------------------- stopping


async def test_three_transport_failures_stop_the_split(dataset: GoldDataset) -> None:
    """Credits are not spent discovering the same outage a fourth time."""
    provider = Recorder(failures=99)
    outcome = await run_cases(
        dataset,
        lambda _: provider,
        guard=guard_for(),
        provider_name=provider.name,
        mode=LIVE_MODE,
        stop=StopPolicy(max_provider_failures=3),
    )
    assert outcome.provider_failures == 3
    assert outcome.stopped is not None and "transport failures" in outcome.stopped
    assert len(provider.asked) == 3


async def test_a_run_stops_when_a_case_breaks_a_hard_safety_gate(dataset: GoldDataset) -> None:
    """A safety finding is not something to buy more copies of.

    The violation here is a real one and the cheapest to provoke: "the berries didn't arrive"
    names no ingredient the bakery authored, its gold outcome is a person, and a reading that
    binds an ingredient anyway talks the system into progressing a case it must not progress.
    That is an *unsafe rescue*, the failure the whole fallback boundary exists to prevent.
    """

    must_not_bind = tuple(
        case
        for case in dataset.worker
        if case.asked and case.expected is not None and "must_not_bind" in case.tags
    )
    assert len(must_not_bind) > 1
    provider = Recorder(payload=BINDS_A_REAL_INGREDIENT)
    outcome = await run_cases(
        GoldDataset(
            version=dataset.version,
            worker=must_not_bind,
            customer=(),
            provenance=dataset.provenance,
        ),
        lambda _: provider,
        guard=guard_for(),
        provider_name=provider.name,
        mode=LIVE_MODE,
        stop=StopPolicy(stop_on_safety_violation=True),
    )

    assert outcome.stopped is not None
    assert "hard safety gate" in outcome.stopped
    assert outcome.results[-1].metrics["unsafe_rescue"] is True
    assert len(outcome.results) < len(must_not_bind), "the split stopped rather than finishing"


async def test_an_ordinary_quality_miss_does_not_stop_a_run(dataset: GoldDataset) -> None:
    """The stop must fire on safety and only on safety.

    A model reading every reply as UNCLEAR is wrong about most of them and dangerous about
    none: all three labels produce the same confirmation prompt, and only a literal reply
    decides anything. A run halted by that would report a fraction of a split as a benchmark.
    """
    provider = Recorder()
    customer_only = GoldDataset(
        version=dataset.version,
        worker=(),
        customer=dataset.customer[:3],
        provenance=dataset.provenance,
    )
    outcome = await run_cases(
        customer_only,
        lambda _: provider,
        guard=guard_for(),
        provider_name=provider.name,
        mode=LIVE_MODE,
        stop=StopPolicy(stop_on_safety_violation=True),
    )
    assert outcome.stopped is None
    assert len(provider.asked) == 3
    assert any(not result.passed for result in outcome.results)


async def test_a_resumed_run_stops_again_at_a_violation_it_already_recorded(
    dataset: GoldDataset, tmp_path: Path
) -> None:
    """Resuming must not walk past a stop, and a stored violation is still a violation.

    The failure this prevents is quiet and expensive: a split halted by a safety gate, re-run
    to "finish it off", reading its own recorded violation back as an ordinary result and
    carrying on paying for the rest of the dataset.
    """
    must_not_bind = tuple(
        case
        for case in dataset.worker
        if case.asked and case.expected is not None and "must_not_bind" in case.tags
    )
    header = header_for(dataset)
    store = ResultStore(tmp_path / "run.jsonl", header)
    first = await run_cases(
        GoldDataset(
            version=dataset.version,
            worker=must_not_bind,
            customer=(),
            provenance=dataset.provenance,
        ),
        lambda _: Recorder(payload=BINDS_A_REAL_INGREDIENT),
        guard=guard_for(),
        provider_name="recorder",
        mode=LIVE_MODE,
        on_result=store.record,
        stop=StopPolicy(stop_on_safety_violation=True),
    )
    assert first.stopped is not None

    reopened = ResultStore(tmp_path / "run.jsonl", header)
    resumed = await run_cases(
        GoldDataset(
            version=dataset.version,
            worker=must_not_bind,
            customer=(),
            provenance=dataset.provenance,
        ),
        lambda _: pytest.fail("the resumed run must stop before asking anything new"),
        guard=guard_for(),
        provider_name="recorder",
        mode=LIVE_MODE,
        reuse=reopened.existing,
        stop=StopPolicy(stop_on_safety_violation=True),
    )
    assert resumed.stopped is not None
    assert "hard safety gate" in resumed.stopped
    assert len(resumed.results) == len(first.results)


async def test_a_run_stops_when_a_different_model_answers(dataset: GoldDataset) -> None:
    """A benchmark that measured a model it did not name would be worse than none."""
    provider = Recorder(model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0")
    outcome = await run_cases(
        GoldDataset(
            version=dataset.version,
            worker=(),
            customer=dataset.customer[:3],
            provenance=dataset.provenance,
        ),
        lambda _: provider,
        guard=guard_for(),
        provider_name=provider.name,
        mode=LIVE_MODE,
        expected_model_id=NOVA,
    )
    assert outcome.stopped is not None
    assert "not the benchmarked" in outcome.stopped
    assert len(provider.asked) == 1


# ---------------------------------------------------------------------- what is recorded


async def test_a_live_case_records_its_own_latency_tokens_and_cost(
    dataset: GoldDataset,
) -> None:
    """Two latency series and a per-case price, so a paired comparison has columns to join."""
    provider = Recorder(usage=SemanticUsage(input_tokens=500, output_tokens=25, latency_ms=310))
    outcome = await run_cases(
        GoldDataset(
            version=dataset.version,
            worker=(),
            customer=dataset.customer[:1],
            provenance=dataset.provenance,
        ),
        lambda _: provider,
        guard=guard_for(),
        provider_name=provider.name,
        mode=LIVE_MODE,
    )
    result = outcome.results[0]
    assert result.latency_ms == 310
    assert result.e2e_latency_ms is not None
    assert result.input_tokens == 500
    assert result.output_tokens == 25
    assert result.estimated_usd is not None and Decimal(result.estimated_usd) > 0
    assert result.model_id == NOVA
    assert result.provider == "recorder"


async def test_a_sentence_the_lexicon_reads_costs_nothing_in_a_live_run(
    dataset: GoldDataset,
) -> None:
    """The 'never asked' cases, measured on the one thing that matters about them: zero calls."""
    unasked = tuple(case for case in dataset.worker if not case.asked)
    assert unasked
    provider = Recorder()
    guard = guard_for()
    outcome = await run_cases(
        GoldDataset(
            version=dataset.version, worker=unasked, customer=(), provenance=dataset.provenance
        ),
        lambda _: provider,
        guard=guard,
        provider_name=provider.name,
        mode=LIVE_MODE,
    )
    assert provider.asked == []
    assert guard.spend.calls == 0
    assert all(score.case_passed for score in outcome.worker_scores)
    summary = build_summary(dataset, outcome, mode=LIVE_MODE)
    assert summary.safety["asked_when_forbidden"] == 0
    assert summary.cost["estimated_usd"] is None


async def test_a_split_is_run_on_its_own_and_never_blended(
    dataset: GoldDataset, answers: ScriptedAnswers
) -> None:
    """Development and holdout are separate runs, which is what the protocol depends on."""
    for split in EvalSplit:
        selected = dataset.split([split])
        outcome = await run_cases(
            selected,
            scripted_provider(answers),
            guard=BudgetGuard(EvalBudget(), price=None, live=False),
            provider_name="fake",
        )
        assert {result.split for result in outcome.results} == {split}


def test_the_offline_default_is_still_a_fake_that_reaches_nothing(
    answers: ScriptedAnswers,
) -> None:
    """``scripted_provider`` is the only factory this package can build, and it is the fake."""
    from evals.cases import EvalJob

    from promisepatch.semantic import (
        ClassifyReplyIntentRequest,
        FakeSemanticProvider,
        UntrustedText,
    )

    factory = scripted_provider(answers)
    provider = factory(
        ModelInput(
            case_id="customer.approve.terse.001",
            job=EvalJob.CUSTOMER_INTENT,
            request=ClassifyReplyIntentRequest(reply=UntrustedText(text="Strawberries work")),
        )
    )
    assert isinstance(provider, FakeSemanticProvider)
    assert provider.model_id is None


def test_the_price_used_for_a_live_run_is_the_recorded_nova_snapshot() -> None:
    """The estimate a benchmark reports is computed from a dated, sourced figure."""
    price = price_for("bedrock", NOVA)
    assert isinstance(price, ModelPrice)
    guard = BudgetGuard(EvalBudget(max_estimated_usd=Decimal("0.20")), price=price, live=True)
    guard.authorise()
    guard.record(
        SemanticTelemetry(
            job=SemanticJob.CLASSIFY_REPLY_INTENT,
            provider="recorder",
            model_id=NOVA,
            attempts=1,
            usage=SemanticUsage(input_tokens=1_000_000, output_tokens=1_000_000),
        )
    )
    assert guard.spend.estimated_usd == Decimal("2.80")


def test_the_budgeted_provider_is_the_only_thing_the_runner_asks() -> None:
    """Named directly, because 'the runner wraps it' is a claim worth pinning to a symbol."""
    import inspect

    from evals import runner

    source = inspect.getsource(runner._ask)
    assert "BudgetedSemanticProvider(factory(model_input), guard)" in source
    assert issubclass(BudgetedSemanticProvider, object)
