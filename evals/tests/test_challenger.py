"""The properties that have to hold before a challenger call is worth making.

Every test here runs offline and none of them constructs a provider that could reach anything.
That is deliberate: the expensive half of a challenger run is one model answering questions,
and every decision *about* whether to ask it -- which cases, in what order, under what ceiling,
and whether to buy a second batch at all -- is decided by code that can be exercised for free.

The properties, in the order the money depends on them:

* the set is derived rather than chosen, and derived the same way twice;
* it contains every failure and no case from a split or a job this slice does not buy;
* the challenger cannot learn what it is, because a gold case cannot reach a model at all;
* nothing can be bought twice, and nothing can be bought without being counted;
* an unpriced model cannot be run under a dollar ceiling;
* a Stage A that did not clear materiality cannot open Stage B.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal

import pytest
from evals.budget import (
    BudgetedSemanticProvider,
    BudgetExhaustedError,
    BudgetGuard,
    EvalBudget,
    PricingUnavailableError,
    price_for,
)
from evals.cases import CustomerCase, EvalJob, EvalSplit, ModelInput, to_model_input
from evals.challenger import (
    MAX_STAGE_A_CASES,
    STAGE_A_MATERIALITY,
    ChallengerError,
    Role,
    SourceRun,
    build_stage_a,
    cluster_deltas,
    compare,
    customer_development,
    customer_totals,
    evaluate_materiality,
    is_directional_inversion,
    pair_all,
    scores_for,
    select_stage_a,
    usage_profile,
)
from evals.dataset import GoldDataset, load_dataset
from evals.results import CaseResult
from evals.runner import ProviderFactory, run_cases
from evals.store import ResultStore, RunHeader

from promisepatch.semantic import (
    ApparentIntent,
    FakeSemanticProvider,
    SemanticProvider,
    SemanticRequest,
)

NOVA = "us.amazon.nova-2-lite-v1:0"
HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


@pytest.fixture(scope="module")
def dataset() -> GoldDataset:
    return load_dataset()


def development(dataset: GoldDataset) -> tuple[CustomerCase, ...]:
    return tuple(case for case in dataset.customer if case.split is EvalSplit.DEVELOPMENT)


def result_for(
    case: CustomerCase,
    predicted: ApparentIntent | None,
    *,
    tokens: tuple[int, int] = (400, 12),
    model_id: str = NOVA,
) -> CaseResult:
    """One stored reading, in the shape a live run writes down.

    Built by hand rather than read from a run file, because CI has no run files: the point of
    an offline suite is that it proves these properties on a machine that has never called a
    model.
    """
    correct = predicted is case.expected
    return CaseResult(
        case_id=case.id,
        job=case.job,
        split=case.split,
        tags=case.tags,
        expected={"apparent_intent": case.expected.value},
        observed={"apparent_intent": None if predicted is None else predicted.value},
        metrics={
            "answered": predicted is not None,
            "expected": case.expected.value,
            "predicted": None if predicted is None else predicted.value,
            "correct": correct,
            "authority_violation": False,
            "refusal_category": None,
        },
        passed=correct,
        reason="read",
        provider="bedrock",
        model_id=model_id,
        attempts=1,
        latency_ms=300,
        e2e_latency_ms=380,
        input_tokens=tokens[0],
        output_tokens=tokens[1],
        estimated_usd="0.00015",
    )


def source_run(
    dataset: GoldDataset,
    wrong: Mapping[str, ApparentIntent | None],
    *,
    extra: Sequence[CaseResult] = (),
) -> SourceRun:
    """A finished run over every customer development case, wrong exactly where told."""
    results = [result_for(case, wrong.get(case.id, case.expected)) for case in development(dataset)]
    return SourceRun(
        run_id="source0000001",
        model_id=NOVA,
        provider="bedrock",
        git_sha="0" * 40,
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        results=(*results, *extra),
    )


def two_failures(dataset: GoldDataset) -> Mapping[str, ApparentIntent | None]:
    """Two misreadings, one per class, chosen by position so the fixture is not hand-picked."""
    approve = [c for c in development(dataset) if c.expected is ApparentIntent.APPARENT_APPROVE]
    decline = [c for c in development(dataset) if c.expected is ApparentIntent.APPARENT_DECLINE]
    return {approve[0].id: ApparentIntent.UNCLEAR, decline[0].id: ApparentIntent.UNCLEAR}


# ------------------------------------------------------------------ the set is derived


def test_selection_is_the_same_set_twice(dataset: GoldDataset) -> None:
    """A set that depended on iteration order would be a set nobody could reproduce."""
    source = source_run(dataset, two_failures(dataset))
    first = select_stage_a(dataset, source)
    second = select_stage_a(dataset, source)
    assert first == second
    assert first.as_payload() == second.as_payload()


def test_every_failure_is_challenged(dataset: GoldDataset) -> None:
    """The count comes from the data. Nothing is dropped for being awkward or expensive."""
    wrong = dict(two_failures(dataset))
    unclear = [c for c in development(dataset) if c.expected is ApparentIntent.UNCLEAR]
    wrong[unclear[0].id] = ApparentIntent.APPARENT_APPROVE
    selection = select_stage_a(dataset, source_run(dataset, wrong))
    assert set(selection.failure_ids) == set(wrong)


def test_a_refusal_counts_as_a_failure(dataset: GoldDataset) -> None:
    """Nothing came back, so the gold label did not. That is a case worth challenging."""
    case = development(dataset)[0]
    selection = select_stage_a(
        dataset, source_run(dataset, {case.id: None, **two_failures(dataset)})
    )
    assert case.id in selection.failure_ids


def test_every_control_is_used_once(dataset: GoldDataset) -> None:
    """A control counted twice would make one preserved case look like two."""
    approve = sorted(
        case.id for case in development(dataset) if case.expected is ApparentIntent.APPARENT_APPROVE
    )
    wrong = dict.fromkeys(approve[:8], ApparentIntent.UNCLEAR)
    selection = select_stage_a(dataset, source_run(dataset, wrong))
    assert len(selection.pairs) == len(wrong)
    assert len(set(selection.control_ids)) == len(selection.control_ids)
    assert not set(selection.control_ids) & set(selection.failure_ids)
    assert not all(pair.same_class for pair in selection.pairs), (
        "this fixture exhausts the failures' own class, so it should exercise the fallback"
    )


def test_a_control_shares_its_failure_s_class_when_one_is_left(dataset: GoldDataset) -> None:
    """Same class first, so a control watches the decision its failure is about."""
    selection = select_stage_a(dataset, source_run(dataset, two_failures(dataset)))
    assert all(pair.same_class for pair in selection.pairs)
    assert all(pair.failure_gold == pair.control_gold for pair in selection.pairs)


def test_the_control_is_the_nearest_by_tag_then_by_id(dataset: GoldDataset) -> None:
    """The tie-break is lexical, so two machines choose the same control from the same data."""
    approve = sorted(
        (c for c in development(dataset) if c.expected is ApparentIntent.APPARENT_APPROVE),
        key=lambda case: case.id,
    )
    failure = approve[0]
    selection = select_stage_a(dataset, source_run(dataset, {failure.id: ApparentIntent.UNCLEAR}))
    pair = next(item for item in selection.pairs if item.failure_case_id == failure.id)
    best = max(len(set(case.tags) & set(failure.tags)) for case in approve if case.id != failure.id)
    expected = min(
        case.id
        for case in approve
        if case.id != failure.id and len(set(case.tags) & set(failure.tags)) == best
    )
    assert pair.control_case_id == expected


def test_a_stage_a_that_would_exceed_the_bound_stops_rather_than_shrinking(
    dataset: GoldDataset,
) -> None:
    """A set trimmed to fit a cap is a set somebody chose. This raises instead."""
    wrong = {
        case.id: ApparentIntent.UNCLEAR
        for case in development(dataset)
        if case.expected is ApparentIntent.APPARENT_APPROVE
    }
    assert len(wrong) * 2 > MAX_STAGE_A_CASES
    with pytest.raises(ChallengerError, match=str(MAX_STAGE_A_CASES)):
        select_stage_a(dataset, source_run(dataset, wrong))


def test_a_source_missing_a_reading_stops_rather_than_spending_to_fill_it(
    dataset: GoldDataset,
) -> None:
    """A gap in the challenged model's answers is reported, never bought."""
    source = source_run(dataset, two_failures(dataset))
    short = SourceRun(
        run_id=source.run_id,
        model_id=source.model_id,
        provider=source.provider,
        git_sha=source.git_sha,
        dataset_version=source.dataset_version,
        dataset_hash=source.dataset_hash,
        results=source.results[1:],
    )
    with pytest.raises(ChallengerError, match="no reading"):
        select_stage_a(dataset, short)


def test_a_source_with_no_failures_has_nothing_to_challenge(dataset: GoldDataset) -> None:
    with pytest.raises(ChallengerError, match="nothing to challenge"):
        select_stage_a(dataset, source_run(dataset, {}))


# ----------------------------------------------------- what cannot enter the challenger set


def test_worker_results_never_enter_the_set(dataset: GoldDataset) -> None:
    """Worker interpretation is not being challenged, so a worker case cannot be bought."""
    worker = dataset.worker[0]
    intruder = CaseResult(
        case_id=worker.id,
        job=EvalJob.WORKER_SEMANTICS,
        split=worker.split,
        tags=worker.tags,
        expected={},
        observed={},
        metrics={},
        passed=False,
        reason="",
        provider="bedrock",
    )
    source = source_run(dataset, two_failures(dataset), extra=[intruder])
    assert all(
        result.job is EvalJob.CUSTOMER_INTENT for result in customer_development(source.results)
    )
    selection = select_stage_a(dataset, source)
    assert worker.id not in selection.case_ids


def test_holdout_results_never_enter_the_set(dataset: GoldDataset) -> None:
    """The holdout is reserved for a selected strategy's final gate, not spent comparing."""
    holdout = [case for case in dataset.customer if case.split is EvalSplit.HOLDOUT]
    assert holdout, "the dataset must contain holdout customer cases for this to prove anything"
    intruders = [result_for(case, ApparentIntent.UNCLEAR) for case in holdout]
    selection = select_stage_a(dataset, source_run(dataset, two_failures(dataset), extra=intruders))
    assert not selection.case_ids & {case.id for case in holdout}


def test_the_selection_cannot_see_a_challenger_answer(dataset: GoldDataset) -> None:
    """Structural: selection takes a dataset and the challenged run, and nothing else.

    A signature that accepted the challenger's results would be a selection somebody could
    tune after seeing them, and the repair rate it produced would mean nothing.
    """
    from inspect import signature

    assert list(signature(select_stage_a).parameters) == ["dataset", "source"]


# --------------------------------------------------------------------- gold cannot leak


def test_a_challenged_case_reaches_a_model_carrying_no_gold(dataset: GoldDataset) -> None:
    """The challenger is not told it is one: it gets the production request and nothing else."""
    selection = select_stage_a(dataset, source_run(dataset, two_failures(dataset)))
    cases = {case.id: case for case in dataset.customer}
    for case_id in sorted(selection.case_ids):
        case = cases[case_id]
        model_input = to_model_input(case)
        payload = json.dumps(json.loads(model_input.request.model_dump_json()))
        assert case.expected.value not in payload
        assert case_id not in payload
        for tag in case.tags:
            assert tag not in payload
        assert "failure" not in payload
        assert "control" not in payload


def test_the_model_input_type_has_no_field_a_role_could_travel_in() -> None:
    """Absence, not intention: there is nowhere on the way out to put "this is a control"."""
    assert set(ModelInput.model_fields) == {"case_id", "job", "request"}


# --------------------------------------------------------------------------- the taxonomy


def test_a_repair_and_an_unchanged_failure_are_told_apart(dataset: GoldDataset) -> None:
    wrong = two_failures(dataset)
    source = source_run(dataset, wrong)
    selection = select_stage_a(dataset, source)
    cases = {case.id: case for case in dataset.customer}
    challenger = []
    for index, case_id in enumerate(sorted(selection.case_ids)):
        case = cases[case_id]
        label = case.expected if index % 2 == 0 else ApparentIntent.UNCLEAR
        challenger.append(result_for(case, label, model_id=HAIKU))
    outcome = build_stage_a(dataset, selection, source, challenger)
    assert outcome.complete
    assert outcome.repairs + outcome.unchanged_failures == len(outcome.failures)
    assert outcome.controls_preserved + outcome.control_regressions == len(outcome.controls)


def test_an_inversion_is_not_the_same_miss_as_a_retreat() -> None:
    """Reading an approval as a refusal is a different failure from reading it as unclear."""
    approve, decline = ApparentIntent.APPARENT_APPROVE, ApparentIntent.APPARENT_DECLINE
    assert is_directional_inversion(approve, decline)
    assert is_directional_inversion(decline, approve)
    assert not is_directional_inversion(approve, ApparentIntent.UNCLEAR)
    assert not is_directional_inversion(ApparentIntent.UNCLEAR, approve)
    assert not is_directional_inversion(approve, None)


def test_an_incomplete_stage_a_decides_nothing(dataset: GoldDataset) -> None:
    """Partial numbers are not a smaller result, they are no result."""
    source = source_run(dataset, two_failures(dataset))
    selection = select_stage_a(dataset, source)
    cases = {case.id: case for case in dataset.customer}
    partial = [
        result_for(cases[case_id], cases[case_id].expected, model_id=HAIKU)
        for case_id in sorted(selection.case_ids)
    ][:-1]
    outcome = build_stage_a(dataset, selection, source, partial)
    assert not outcome.complete
    assert not evaluate_materiality(outcome).passed


# -------------------------------------------------------------------- the materiality gate


def _outcome(dataset: GoldDataset, labels: Mapping[str, ApparentIntent]) -> object:
    source = source_run(dataset, two_failures(dataset))
    selection = select_stage_a(dataset, source)
    cases = {case.id: case for case in dataset.customer}
    challenger = [
        result_for(cases[case_id], labels.get(case_id, cases[case_id].expected), model_id=HAIKU)
        for case_id in sorted(selection.case_ids)
    ]
    return build_stage_a(dataset, selection, source, challenger)


def test_a_challenger_that_repairs_everything_and_breaks_nothing_is_material(
    dataset: GoldDataset,
) -> None:
    verdict = evaluate_materiality(_outcome(dataset, {}))  # type: ignore[arg-type]
    assert verdict.passed
    assert not verdict.failed


def test_a_challenger_that_repairs_nothing_is_not_material(dataset: GoldDataset) -> None:
    source = source_run(dataset, two_failures(dataset))
    selection = select_stage_a(dataset, source)
    cases = {case.id: case for case in dataset.customer}
    failures = set(selection.failure_ids)
    challenger = [
        result_for(
            cases[case_id],
            ApparentIntent.UNCLEAR if case_id in failures else cases[case_id].expected,
            model_id=HAIKU,
        )
        for case_id in sorted(selection.case_ids)
    ]
    outcome = build_stage_a(dataset, selection, source, challenger)
    verdict = evaluate_materiality(outcome)
    assert not verdict.passed
    assert "failures repaired" in verdict.failed


def test_an_inversion_alone_sinks_materiality(dataset: GoldDataset) -> None:
    """A cluster repaired by flipping the stance is not a cluster repaired."""
    source = source_run(dataset, two_failures(dataset))
    selection = select_stage_a(dataset, source)
    cases = {case.id: case for case in dataset.customer}
    inverted = next(
        case_id
        for case_id in sorted(selection.control_ids)
        if cases[case_id].expected is ApparentIntent.APPARENT_APPROVE
    )
    challenger = [
        result_for(
            cases[case_id],
            ApparentIntent.APPARENT_DECLINE if case_id == inverted else cases[case_id].expected,
            model_id=HAIKU,
        )
        for case_id in sorted(selection.case_ids)
    ]
    outcome = build_stage_a(dataset, selection, source, challenger)
    assert outcome.directional_inversions == 1
    assert "directional inversions" in evaluate_materiality(outcome).failed


def test_the_materiality_floor_is_the_one_written_down() -> None:
    """Fixed before the first call. A bar set once the numbers are in is not a bar."""
    assert STAGE_A_MATERIALITY.min_repair_rate == 0.50
    assert STAGE_A_MATERIALITY.min_repairs == 2
    assert STAGE_A_MATERIALITY.max_directional_inversions == 0
    assert STAGE_A_MATERIALITY.max_control_regressions == 1
    assert STAGE_A_MATERIALITY.max_authority_violations == 0


# ------------------------------------------------------------------- the paired comparison


def test_the_comparison_uses_the_same_scorer_as_the_run_it_compares_with(
    dataset: GoldDataset,
) -> None:
    """No challenger-specific scoring system. Same gold, same scorer, same numbers."""
    source = source_run(dataset, two_failures(dataset))
    totals = customer_totals(dataset, source.results)
    scores = scores_for(dataset, source.results)
    assert totals["cases"] == len(scores)
    assert totals["accuracy"] == pytest.approx(sum(score.correct for score in scores) / len(scores))


def test_wins_losses_and_ties_add_up_to_the_cases_compared(dataset: GoldDataset) -> None:
    source = source_run(dataset, two_failures(dataset))
    cases = {case.id: case for case in dataset.customer}
    challenger = [
        result_for(cases[result.case_id], cases[result.case_id].expected, model_id=HAIKU)
        for result in source.results
    ]
    paired = pair_all(dataset, source, challenger)
    totals = compare(paired)
    assert totals.wins + totals.losses + totals.ties == totals.cases
    assert totals.wins == len(two_failures(dataset))
    assert totals.losses == 0


def test_a_cluster_carries_both_denominators(dataset: GoldDataset) -> None:
    """A rate over five hand-authored cases is four of them, and the report has to show that."""
    source = source_run(dataset, two_failures(dataset))
    cases = {case.id: case for case in dataset.customer}
    challenger = [
        result_for(cases[result.case_id], cases[result.case_id].expected, model_id=HAIKU)
        for result in source.results
    ]
    clusters = cluster_deltas(pair_all(dataset, source, challenger))
    assert clusters
    for cluster in clusters:
        assert cluster.total > 0
        assert 0.0 <= cluster.source_recall <= 1.0
        assert cluster.challenger_recall == 1.0


def test_a_paired_test_over_no_disagreement_is_not_a_number(dataset: GoldDataset) -> None:
    source = source_run(dataset, {})
    cases = {case.id: case for case in dataset.customer}
    challenger = [
        result_for(cases[result.case_id], cases[result.case_id].expected, model_id=HAIKU)
        for result in source.results
    ]
    assert compare(pair_all(dataset, source, challenger)).exact_paired_p is None


def test_the_cost_profile_is_built_from_the_readings_themselves(dataset: GoldDataset) -> None:
    source = source_run(dataset, two_failures(dataset))
    profile = usage_profile(dataset, source.results, NOVA)
    assert profile.calls == len(source.results)
    assert profile.input_tokens == 400 * len(source.results)
    assert profile.usd_per_thousand(price_for("bedrock", NOVA)) is not None
    assert profile.usd_per_thousand(None) is None


# ----------------------------------------------------------------- nothing escapes the guard


class Recorder:
    """A provider that answers ``UNCLEAR`` and remembers being asked. Reaches nothing."""

    name = "recorder"

    def __init__(self) -> None:
        self.asked: list[str] = []
        self._inner = FakeSemanticProvider({})

    async def run(self, request: SemanticRequest) -> object:
        self.asked.append(type(request).__name__)
        return await self._inner.run(request)


def _factory(provider: SemanticProvider) -> ProviderFactory:
    def build(_: ModelInput) -> SemanticProvider:
        return provider

    return build


def narrow(dataset: GoldDataset, case_ids: frozenset[str]) -> GoldDataset:
    return GoldDataset(
        version=dataset.version,
        worker=(),
        customer=tuple(case for case in dataset.customer if case.id in case_ids),
        provenance=dataset.provenance,
    )


async def test_only_the_selected_cases_are_ever_asked(dataset: GoldDataset) -> None:
    """The runner iterates what it is handed, and it is handed the set and nothing else."""
    source = source_run(dataset, two_failures(dataset))
    selection = select_stage_a(dataset, source)
    recorder = Recorder()
    guard = BudgetGuard(EvalBudget(max_calls=MAX_STAGE_A_CASES), price=None, live=False)
    outcome = await run_cases(
        narrow(dataset, selection.case_ids),
        _factory(recorder),  # type: ignore[arg-type]
        guard=guard,
        provider_name=recorder.name,
    )
    assert {result.case_id for result in outcome.results} == selection.case_ids
    assert guard.spend.calls == len(selection.case_ids)
    assert all(name == "ClassifyReplyIntentRequest" for name in recorder.asked)


async def test_the_ceiling_refuses_the_call_that_would_cross_it(dataset: GoldDataset) -> None:
    """A cap that warned would already have spent the money by the time anybody read it."""
    source = source_run(dataset, two_failures(dataset))
    selection = select_stage_a(dataset, source)
    guard = BudgetGuard(EvalBudget(max_calls=1), price=None, live=False)
    with pytest.raises(BudgetExhaustedError):
        await run_cases(
            narrow(dataset, selection.case_ids),
            _factory(Recorder()),  # type: ignore[arg-type]
            guard=guard,
            provider_name="recorder",
        )
    assert guard.spend.calls == 1


async def test_a_provider_cannot_be_asked_without_the_guard_counting_it() -> None:
    """The wrapper is applied by the runner, so a factory cannot hand in an uncounted provider."""
    guard = BudgetGuard(EvalBudget(max_calls=0), price=None, live=False)
    budgeted = BudgetedSemanticProvider(FakeSemanticProvider({}), guard)
    from promisepatch.semantic import ClassifyReplyIntentRequest, UntrustedText

    with pytest.raises(BudgetExhaustedError):
        await budgeted.run(ClassifyReplyIntentRequest(reply=UntrustedText(text="ok")))


def test_an_unpriced_model_cannot_run_under_a_dollar_ceiling() -> None:
    """Unknown pricing fails closed. It is never zero, and a zero budget is never enforceable."""
    budget = EvalBudget(max_estimated_usd=Decimal("0.15"))
    with pytest.raises(PricingUnavailableError):
        BudgetGuard(budget, price=None, live=True)


def test_the_challenger_has_a_verified_price_with_a_snapshot() -> None:
    """Nothing is written into the catalog from memory, and the entry says where it came from."""
    price = price_for("bedrock", HAIKU)
    assert price is not None
    assert price.snapshot_date.isoformat() == "2026-09-07"
    assert "AWS Price List" in price.source
    assert price.input_usd_per_million == Decimal("1.10")
    assert price.output_usd_per_million == Decimal("5.50")


# --------------------------------------------------------------------------- resuming


async def test_a_case_already_answered_is_read_back_rather_than_asked_again(
    dataset: GoldDataset, tmp_path: object
) -> None:
    """The Stage A -> Stage B transition reuses what Stage A bought. Nothing is bought twice."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    source = source_run(dataset, two_failures(dataset))
    selection = select_stage_a(dataset, source)
    cases = {case.id: case for case in dataset.customer}
    header = RunHeader(
        run_id="challenger01",
        started_at="2026-09-07T00:00:00+00:00",
        git_sha="1" * 40,
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        prompts=(),
        provider="bedrock",
        model_id=HAIKU,
        mode="live",
        splits=("development",),
    )
    store = ResultStore(tmp_path / "challenger.jsonl", header)
    for case_id in sorted(selection.case_ids):
        store.record(result_for(cases[case_id], cases[case_id].expected, model_id=HAIKU))

    reopened = ResultStore(tmp_path / "challenger.jsonl", header)
    assert reopened.completed() == selection.case_ids

    recorder = Recorder()
    guard = BudgetGuard(EvalBudget(), price=None, live=False)
    outcome = await run_cases(
        narrow(dataset, selection.case_ids),
        _factory(recorder),  # type: ignore[arg-type]
        guard=guard,
        provider_name="recorder",
        reuse=reopened.existing,
    )
    assert outcome.reused == len(selection.case_ids)
    assert recorder.asked == []
    assert guard.spend.calls == 0


def test_stage_a_results_rebuild_the_outcome_with_no_model_in_the_room(
    dataset: GoldDataset,
) -> None:
    """A lost terminal costs nothing: the decision is rebuildable from the stored readings."""
    source = source_run(dataset, two_failures(dataset))
    selection = select_stage_a(dataset, source)
    cases = {case.id: case for case in dataset.customer}
    stored = [
        result_for(cases[case_id], cases[case_id].expected, model_id=HAIKU)
        for case_id in sorted(selection.case_ids)
    ]
    first = build_stage_a(dataset, selection, source, stored)
    second = build_stage_a(dataset, select_stage_a(dataset, source), source, stored)
    assert first.as_payload() == second.as_payload()
    assert {case.role for case in first.cases} == {Role.FAILURE, Role.CONTROL}
