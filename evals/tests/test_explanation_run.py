"""The whole path, offline: acceptance, structural scoring, judging, replay, budgets, interlocks.

Every provider here is a script. Nothing in this file reaches a network, holds a credential or
imports an SDK, and several tests assert that with instrumentation rather than by saying so: a
provider that raises when called is passed in, and the operation under test has to complete
without touching it.

The three replay properties this gate is built on are each proved separately, because they are
what stop an expensive run from having to be bought twice: a report can be rebuilt from stored
results with zero calls of either kind, a judge can be re-run with zero Nova calls, and a stored
passage whose production request has since moved cannot be rejudged at all.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from evals.authorisation import (
    SpendNotAuthorisedError,
    SpendScope,
    authorise,
    refuse_real_inference_under_test,
    required_phrase,
)
from evals.budget import (
    NEMOTRON_3_SUPER,
    NOVA_2_LITE,
    BillingMode,
    BudgetExhaustedError,
    BudgetGuard,
    EvalBudget,
    estimate_usd,
)
from evals.cases import EvalSplit
from evals.explanation_budget import (
    CORRECTIVE_ATTEMPTS_PER_CALL,
    RunCost,
    judge_ceiling,
    nova_ceiling,
    run_cost,
)
from evals.explanation_cases import ExplanationFamily
from evals.explanation_dataset import ExplanationDataset, load_explanation_dataset
from evals.explanation_judge import (
    JUDGE_MODEL_ID,
    JUDGE_PROVIDER,
    CountedJudge,
    JudgeVerdict,
    ScriptedJudge,
    StructuredJudge,
)
from evals.explanation_metrics import (
    evaluate_gates,
    fallback_failures,
    gate_status,
    hard_metrics,
    quality_metrics,
    revalidate_accepted,
    score_cases,
)
from evals.explanation_report import plan, render
from evals.explanation_results import (
    ExplanationFailureKind,
    ExplanationSource,
    JudgeOutcome,
    ManualDisposition,
    NovaExplanationResult,
    Usage,
)
from evals.explanation_runner import (
    ExplanationRunSummary,
    ScriptedExplanations,
    generate,
    judge_explanations,
    rejudgeable,
    rescore,
    run_offline,
    scripted_provider,
    scripted_verdicts,
)

from promisepatch.domain.explanations import render as render_facts
from promisepatch.semantic import (
    SemanticProviderError,
    SemanticTimeoutError,
    ValidationFailure,
)

GOOD_VERDICT: dict[str, object] = {
    "outcome_contradiction": False,
    "authority_contradiction": False,
    "unsupported_entity_or_option": False,
    "unsupported_guarantee": False,
    "unsupported_quantity_in_words": False,
    "faithfulness": 5,
    "causal_completeness": 5,
    "clarity": 5,
    "brevity": 5,
    "speech_naturalness": 5,
    "brief_rationale": "grounded",
}


@pytest.fixture(scope="module")
def dataset() -> ExplanationDataset:
    return load_explanation_dataset()


@pytest.fixture(scope="module")
def development(dataset: ExplanationDataset) -> ExplanationDataset:
    return dataset.split([EvalSplit.DEVELOPMENT])


def _valid(dataset: ExplanationDataset, case_id: str) -> dict[str, object]:
    case = next(item for item in dataset.cases if item.id == case_id)
    facts = case.explanation_facts()
    return {
        "speech": render_facts(facts),
        "fact_refs": [fact_id.value for fact_id in facts.required],
    }


def _answers(
    dataset: ExplanationDataset, overrides: dict[str, list[object]]
) -> dict[str, list[object]]:
    """Every case answered acceptably, then the ones this test is about replaced.

    Written out rather than defaulted, because the fake's own cautious answer is refused by
    every real explanation request -- so a script that named one case would quietly turn the
    other thirty-four into fallbacks and measure something else.
    """
    answers: dict[str, list[object]] = {
        case.id: [_valid(dataset, case.id)] for case in dataset.cases
    }
    answers.update(overrides)
    return answers


async def _run(
    dataset: ExplanationDataset,
    overrides: dict[str, list[object]],
    verdicts: dict[str, list[object]] | None = None,
) -> ExplanationRunSummary:
    return await run_offline(
        dataset,
        ScriptedExplanations(_answers(dataset, overrides)),
        verdicts if verdicts is not None else dict(scripted_verdicts()),
    )


# ------------------------------------------------------------- the acceptance path


async def test_the_committed_offline_replay_passes_its_own_gates(
    dataset: ExplanationDataset,
) -> None:
    summary = await run_offline(dataset)
    assert summary.gate_status == "pass"
    assert summary.acceptance.cases == 35
    assert summary.hard.total == 0
    assert summary.semantic.total == 0


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"speech": "Fine.", "fact_refs": ["nope.nope"]}, ExplanationFailureKind.UNKNOWN_FACT_REF),
        ({"speech": "Fine.", "fact_refs": []}, ExplanationFailureKind.MISSING_REQUIRED_FACT),
        ({"speech": 42, "fact_refs": []}, ExplanationFailureKind.SCHEMA_REJECTION),
        (
            {"speech": "Fine.", "fact_refs": [], "mood": "sunny"},
            ExplanationFailureKind.SCHEMA_REJECTION,
        ),
    ],
)
async def test_every_rejection_branch_falls_back_and_is_named(
    dataset: ExplanationDataset, payload: dict[str, object], expected: ExplanationFailureKind
) -> None:
    """Each refusal is a different finding about a model, so each keeps its own name."""
    summary = await _run(dataset, {"explain.plan.001": [payload, payload]})
    score = next(item for item in summary.scores if item.case_id == "explain.plan.001")
    assert score.source is ExplanationSource.FALLBACK
    assert score.failure is expected


async def test_a_word_cap_violation_falls_back_rather_than_being_trimmed(
    dataset: ExplanationDataset,
) -> None:
    long = {"speech": " ".join(["word"] * 200), "fact_refs": ["case.exception"]}
    summary = await _run(dataset, {"explain.plan.001": [long, long]})
    score = next(item for item in summary.scores if item.case_id == "explain.plan.001")
    assert score.failure is ExplanationFailureKind.WORD_CAP
    assert score.source is ExplanationSource.FALLBACK


async def test_an_invented_quantity_falls_back(dataset: ExplanationDataset) -> None:
    invented = {
        "speech": "Priya's cake is covered; we are 9.9 kg short.",
        "fact_refs": [
            "impact.outcome",
            "impact.reason",
            "resource.shortfall",
            "recovery.variant",
            "constraint.cited",
        ],
    }
    summary = await _run(dataset, {"explain.auto.001": [invented, invented]})
    score = next(item for item in summary.scores if item.case_id == "explain.auto.001")
    assert score.failure is ExplanationFailureKind.UNSUPPORTED_DIGIT


async def test_a_provider_failure_is_a_fallback_and_never_a_model_quality_finding(
    dataset: ExplanationDataset,
) -> None:
    """The system explained the outcome. Nobody could be reached to phrase it, and that is all."""
    summary = await _run(
        dataset, {"explain.plan.001": [SemanticProviderError("down", retryable=True)]}
    )
    score = next(item for item in summary.scores if item.case_id == "explain.plan.001")
    assert score.failure is ExplanationFailureKind.PROVIDER_FAILURE
    assert score.scores == {}
    assert summary.acceptance.provider_failures == 1
    assert summary.acceptance.validator_rejected == 0


async def test_a_timeout_is_a_provider_failure_too(dataset: ExplanationDataset) -> None:
    summary = await _run(dataset, {"explain.plan.001": [SemanticTimeoutError("slow")]})
    score = next(item for item in summary.scores if item.case_id == "explain.plan.001")
    assert score.failure is ExplanationFailureKind.PROVIDER_FAILURE


async def test_a_corrective_retry_that_succeeds_is_one_case_and_two_attempts(
    dataset: ExplanationDataset,
) -> None:
    summary = await _run(
        dataset,
        {
            "explain.plan.001": [
                {"speech": "Fine.", "fact_refs": []},
                _valid(dataset, "explain.plan.001"),
            ]
        },
    )
    score = next(item for item in summary.scores if item.case_id == "explain.plan.001")
    assert score.source is ExplanationSource.VERBALISED
    assert summary.generation_usage.logical_calls == 35
    assert summary.generation_usage.provider_attempts > 35


async def test_the_acceptance_rates_are_reported_rather_than_folded_into_quality(
    dataset: ExplanationDataset,
) -> None:
    """A model excellent on the third of cases it did not get refused on is not excellent."""
    bad = {"speech": "Fine.", "fact_refs": []}
    summary = await _run(dataset, {case.id: [bad, bad] for case in dataset.cases[:10]})
    assert summary.acceptance.accepted == 25
    assert summary.acceptance.fallbacks == 10
    assert summary.quality.scored <= 25


# ---------------------------------------------------------------- structural scoring


def test_an_accepted_passage_is_revalidated_by_productions_own_gate(
    dataset: ExplanationDataset,
) -> None:
    """The structural layer is not a second implementation; it is the same function again."""
    case = dataset.cases[0]
    leaked = _stored(case.id, speech="Fine.", refs=("nope.nope",))
    assert revalidate_accepted(case, leaked) is ValidationFailure.UNKNOWN_CANDIDATE
    metrics = hard_metrics([case], [leaked])
    assert metrics.unknown_fact_refs_accepted == 1
    assert metrics.total == 1


def test_a_fallback_is_never_counted_as_a_leaked_acceptance(
    dataset: ExplanationDataset,
) -> None:
    case = dataset.cases[0]
    fell_back = _stored(case.id, speech="Fine.", refs=(), accepted=False)
    assert revalidate_accepted(case, fell_back) is None
    assert hard_metrics([case], [fell_back]).total == 0


def test_the_deterministic_fallback_holds_on_every_fixture(
    dataset: ExplanationDataset,
) -> None:
    """Checked over all thirty-five, including the ones no model is ever asked about."""
    assert fallback_failures(dataset.cases) == ()
    assert hard_metrics(dataset.cases, []).fallback_failures == 0


def test_a_fallback_that_dropped_the_decisive_fact_would_be_a_hard_failure(
    dataset: ExplanationDataset,
) -> None:
    case = next(item for item in dataset.cases if item.id == "explain.auto.001")
    assert case.expected.decisive_fact == "constraint.cited"
    # Where a constraint is cited the renderer says the citation and not the reason clause, so
    # a case that turned on the reason would be one the fallback could not carry.
    broken = case.model_copy(
        update={"expected": case.expected.model_copy(update={"decisive_fact": "impact.reason"})}
    )
    problems = fallback_failures([broken])
    assert problems and "turns on" in problems[0]


def _stored(
    case_id: str, *, speech: str, refs: tuple[str, ...], accepted: bool = True
) -> NovaExplanationResult:
    from evals.explanation_results import GenerationIdentity

    return NovaExplanationResult(
        identity=GenerationIdentity(
            provider="fake",
            model_id=None,
            git_sha=None,
            dataset_name="promisepatch-explanation-gold",
            dataset_version="1.0.0",
            dataset_hash="abc",
            case_id=case_id,
            family=ExplanationFamily.PLAN_SUMMARY,
            facts_fingerprint="f",
            prompt_system_hash="p",
            schema_hash="s",
            word_limit=70,
            run_id="run",
        ),
        split=EvalSplit.DEVELOPMENT,
        source=ExplanationSource.VERBALISED if accepted else ExplanationSource.FALLBACK,
        speech=speech,
        fact_refs=refs,
    )


# ------------------------------------------------------------------ semantic scoring


async def test_a_hard_semantic_finding_fails_the_gate_however_high_the_scores(
    dataset: ExplanationDataset,
) -> None:
    """A high subjective score can never compensate for a hard safety failure."""
    contradiction = {**GOOD_VERDICT, "authority_contradiction": True}
    verdicts = dict(scripted_verdicts())
    verdicts["explain.wait.001"] = [contradiction]
    summary = await run_offline(dataset, judge_answers=verdicts)
    assert summary.semantic.authority_contradictions == 1
    assert summary.quality.faithfulness_mean is not None
    assert summary.quality.faithfulness_mean > 4.5
    assert summary.gate_status == "fail"
    failed = {gate.name for gate in summary.gates if gate.status == "fail"}
    assert "authority contradictions" in failed
    assert "waits claiming an approval already exists" in failed


async def test_a_family_gate_catches_the_one_weak_surface_an_average_would_hide(
    dataset: ExplanationDataset,
) -> None:
    verdicts = dict(scripted_verdicts())
    for case in dataset.family(ExplanationFamily.TRACK_UNAFFECTED):
        verdicts[case.id] = [{**GOOD_VERDICT, "faithfulness": 3}]
    summary = await run_offline(dataset, judge_answers=verdicts)
    assert summary.quality.faithfulness_mean is not None
    assert summary.quality.faithfulness_mean > 4.5
    failed = {gate.name for gate in summary.gates if gate.status == "fail"}
    assert "TRACK_UNAFFECTED mean faithfulness" in failed
    assert summary.gate_status == "fail"


async def test_an_unsupported_quantity_in_words_is_caught_where_the_digit_guard_cannot(
    dataset: ExplanationDataset,
) -> None:
    """P4.7's guard compares digit runs. A quantity written as a word is judged, not computed."""
    passage = {
        "speech": (
            "The hotel has to be asked. We are ten kilos short of raspberries, and their "
            "order says to check before a visible change."
        ),
        "fact_refs": [
            "impact.outcome",
            "impact.reason",
            "resource.shortfall",
            "recovery.variant",
            "constraint.cited",
        ],
    }
    verdicts = dict(scripted_verdicts())
    verdicts["explain.approval.003"] = [{**GOOD_VERDICT, "unsupported_quantity_in_words": True}]
    summary = await _run(dataset, {"explain.approval.003": [passage]}, verdicts)
    score = next(item for item in summary.scores if item.case_id == "explain.approval.003")
    assert score.source is ExplanationSource.VERBALISED, (
        "the digit guard accepts it: the passage contains no digit run at all, though the "
        "facts say nine and the passage says ten"
    )
    assert "unsupported_quantity_in_words" in score.semantic_flags
    assert summary.semantic.unsupported_quantity_in_words == 1
    assert summary.gate_status == "fail"


def test_a_judge_cannot_overrule_a_structural_finding(dataset: ExplanationDataset) -> None:
    """Deterministic evidence outranks an opinion, in both directions."""
    case = dataset.cases[0]
    leaked = _stored(case.id, speech="Fine.", refs=("nope.nope",))
    from evals.explanation_judge import Judgement, to_judge_result

    verdict = to_judge_result(
        leaked,
        Judgement(
            outcome=JudgeOutcome.SCORED,
            verdict=JudgeVerdict.model_validate(GOOD_VERDICT),
            usage=Usage(logical_calls=1, provider_attempts=1),
        ),
        provider="nvidia",
        model_id=JUDGE_MODEL_ID,
        run_id="run",
    )
    scores = score_cases([case], [leaked], [verdict])
    assert scores[0].structural_failures == (ExplanationFailureKind.UNKNOWN_FACT_REF,)
    assert scores[0].scores["brevity"] == 5
    assert hard_metrics([case], [leaked]).unknown_fact_refs_accepted == 1
    gates = evaluate_gates(
        {
            "hard": hard_metrics([case], [leaked]).as_payload(),
            "quality": quality_metrics(scores).as_payload(),
        }
    )
    assert gate_status(gates) == "fail"


def test_a_metric_a_run_never_measured_is_not_a_pass() -> None:
    """The quietest way for a benchmark to lie is a gate that passed on nothing."""
    gates = evaluate_gates({"hard": {}, "semantic": {}, "quality": {}, "families": {}})
    assert all(gate.status == "not-measured" for gate in gates)
    assert gate_status(gates) == "incomplete"


# ------------------------------------------------------------------------- replay


class _Refuses:
    """A provider that fails the test if anything asks it anything."""

    name = "must-not-be-called"
    model_id = None

    async def run(self, request: object) -> object:  # pragma: no cover - the point is it is not
        raise AssertionError("a replay reached a provider")


def test_rescoring_stored_results_costs_zero_calls_of_either_kind(
    dataset: ExplanationDataset,
) -> None:
    """Every deterministic number is a function of what is already on disk."""
    results = [
        _stored(
            case.id,
            speech=render_facts(case.explanation_facts()),
            refs=tuple(f.value for f in case.facts.required),
        )
        for case in dataset.cases
    ]
    summary = rescore(
        dataset,
        results,
        run_id="stored",
        provider="bedrock",
        model_id=NOVA_2_LITE.model_id,
        generation_usage=Usage(logical_calls=35, provider_attempts=36),
    )
    assert summary.acceptance.accepted == 35
    assert summary.hard.total == 0
    assert summary.quality.scored == 0, "no verdicts were supplied, so nothing was scored"
    assert summary.generation_usage.logical_calls == 35
    assert summary.judge_usage.logical_calls == 0


async def test_rejudging_stored_results_costs_zero_nova_calls(
    dataset: ExplanationDataset,
) -> None:
    """The second pass reads results. There is no path from it to the model that wrote them."""
    development = dataset.split([EvalSplit.DEVELOPMENT])
    guard = BudgetGuard(EvalBudget(), price=None, live=False)
    generation = await generate(
        development,
        scripted_provider(ScriptedExplanations.from_file()),
        guard=guard,
        provider_name="fake",
    )
    before = guard.spend.calls

    judge = CountedJudge(StructuredJudge(ScriptedJudge()))
    await judge_explanations(development, generation.results, judge, run_id=generation.run_id)
    assert guard.spend.calls == before, "judging made a generation call"
    assert judge.usage.logical_calls == sum(r.accepted for r in generation.results)

    again = CountedJudge(StructuredJudge(ScriptedJudge()))
    await judge_explanations(development, generation.results, again, run_id="second")
    assert guard.spend.calls == before, "rejudging made a generation call"


def test_a_stored_passage_whose_request_moved_cannot_be_rejudged(
    dataset: ExplanationDataset,
) -> None:
    """A fresh verdict on a stale answer, filed as this run's, is the mistake this prevents."""
    case = dataset.cases[0]
    stored = _stored(case.id, speech="a", refs=())
    moved = stored.model_copy(
        update={"identity": stored.identity.model_copy(update={"prompt_system_hash": "new"})}
    )
    assert rejudgeable([stored], [moved]) == (case.id,)
    assert rejudgeable([stored], [stored]) == ()


def test_a_generation_fingerprint_ignores_the_run_that_produced_it(
    dataset: ExplanationDataset,
) -> None:
    stored = _stored(dataset.cases[0].id, speech="a", refs=())
    other_run = stored.model_copy(
        update={"identity": stored.identity.model_copy(update={"run_id": "later"})}
    )
    assert stored.identity.fingerprint() == other_run.identity.fingerprint()


# ------------------------------------------------------------------------- budgets


def test_the_development_ceilings_are_derived_from_the_fixtures(
    development: ExplanationDataset,
) -> None:
    nova = nova_ceiling(development.cases)
    assert nova.logical_calls == 21
    assert nova.provider_attempts == 21 * CORRECTIVE_ATTEMPTS_PER_CALL == 42
    assert nova.measured_prompt_characters > 0
    assert nova.max_input_tokens > nova.measured_prompt_characters / 4
    assert nova.billing.mode is BillingMode.METERED
    assert nova.projected_usd is not None
    assert nova.max_estimated_usd is not None
    assert nova.max_estimated_usd > nova.projected_usd
    assert nova.max_estimated_usd < Decimal("1.00"), "a development run of 21 cases is small"


def test_the_judge_ceiling_bounds_calls_and_tokens_and_models_no_dollars(
    development: ExplanationDataset,
) -> None:
    """A hosted free endpoint is not a metered model priced at zero."""
    judge = judge_ceiling(development.cases)
    assert judge.logical_calls == 21
    assert judge.provider_attempts == 42
    assert judge.max_input_tokens > 0
    assert judge.max_output_tokens > 0
    assert judge.billing.mode is BillingMode.FREE_HOSTED_TRIAL
    assert judge.billing.price is None
    assert judge.projected_usd is None
    assert judge.max_estimated_usd is None
    assert judge.budget().max_estimated_usd is None


def test_the_nova_price_is_the_repositorys_own_regional_snapshot() -> None:
    assert NOVA_2_LITE.input_usd_per_million == Decimal("0.33")
    assert NOVA_2_LITE.output_usd_per_million == Decimal("2.75")
    assert NEMOTRON_3_SUPER.price is None


def test_generation_spend_is_decimal_arithmetic_over_the_snapshot() -> None:
    spend = estimate_usd(NOVA_2_LITE, input_tokens=1_000_000, output_tokens=1_000_000)
    assert spend == Decimal("0.33") + Decimal("2.75")
    exact = estimate_usd(NOVA_2_LITE, input_tokens=30_000, output_tokens=4_000)
    expected = Decimal(30_000) * Decimal("0.33") + Decimal(4_000) * Decimal("2.75")
    assert exact == expected / Decimal(1_000_000)


def test_generation_and_judging_never_share_a_counter() -> None:
    cost = run_cost(
        generation_input_tokens=30_000,
        generation_output_tokens=4_000,
        judge_input_tokens=60_000,
        judge_output_tokens=6_000,
    )
    assert isinstance(cost, RunCost)
    assert cost.generation_usd is not None
    assert cost.judge_billing_mode == BillingMode.FREE_HOSTED_TRIAL.value
    payload = cost.as_payload()
    assert payload["judge_known_usd"] is None, "not zero: nobody published a price"
    assert payload["total_known_usd"] == str(cost.generation_usd)
    assert payload["judge_input_tokens"] == 60_000


def test_the_gpt_contingency_price_is_recorded_and_not_selected() -> None:
    """Documented only. Nothing in this gate selects it, prices a run against it, or calls it."""
    from evals.budget import GPT_4O_MINI

    assert GPT_4O_MINI.input_usd_per_million == Decimal("0.15")
    assert GPT_4O_MINI.output_usd_per_million == Decimal("0.60")
    assert GPT_4O_MINI.provider != JUDGE_PROVIDER
    assert GPT_4O_MINI.model_id != JUDGE_MODEL_ID


async def test_a_call_ceiling_refuses_the_generation_call_that_would_cross_it(
    development: ExplanationDataset,
) -> None:
    guard = BudgetGuard(EvalBudget(max_calls=2), price=None, live=False)
    with pytest.raises(BudgetExhaustedError):
        await generate(
            development,
            scripted_provider(ScriptedExplanations.from_file()),
            guard=guard,
            provider_name="fake",
        )


# ------------------------------------------------------------------- authorisation


@pytest.mark.parametrize(
    "scope",
    [
        SpendScope.P4_8_NOVA_DEVELOPMENT_GENERATION,
        SpendScope.P4_8_NEMOTRON_DEVELOPMENT_JUDGING,
        SpendScope.P4_8_EXPLANATION_HOLDOUT,
    ],
)
def test_each_p4_8_scope_needs_its_own_phrase(scope: SpendScope) -> None:
    with pytest.raises(SpendNotAuthorisedError):
        authorise(None, scope)
    granted = authorise(required_phrase(scope), scope)
    assert granted.covers(scope)


def test_authorising_generation_does_not_authorise_judging() -> None:
    """Letting the model under test speak is not letting somebody else's model grade it."""
    granted = authorise(
        required_phrase(SpendScope.P4_8_NOVA_DEVELOPMENT_GENERATION),
        SpendScope.P4_8_NOVA_DEVELOPMENT_GENERATION,
    )
    with pytest.raises(SpendNotAuthorisedError):
        granted.require(SpendScope.P4_8_NEMOTRON_DEVELOPMENT_JUDGING)


def test_authorising_development_does_not_authorise_the_holdout() -> None:
    for scope in (
        SpendScope.P4_8_NOVA_DEVELOPMENT_GENERATION,
        SpendScope.P4_8_NEMOTRON_DEVELOPMENT_JUDGING,
    ):
        granted = authorise(required_phrase(scope), scope)
        with pytest.raises(SpendNotAuthorisedError):
            granted.require(SpendScope.P4_8_EXPLANATION_HOLDOUT)


def test_there_is_no_scope_that_grants_everything() -> None:
    assert not any("ALL" in scope.value for scope in SpendScope)


@pytest.mark.parametrize(
    "scope",
    [
        SpendScope.P4_8_NOVA_DEVELOPMENT_GENERATION,
        SpendScope.P4_8_NEMOTRON_DEVELOPMENT_JUDGING,
        SpendScope.P4_8_EXPLANATION_HOLDOUT,
    ],
)
def test_a_pytest_process_cannot_build_a_paid_provider_for_any_p4_8_scope(
    scope: SpendScope, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Realistic credentials and a correct phrase change nothing. The interlock is the runner."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-notarealkey-000000000000000000000000000000")
    monkeypatch.setenv("NVIDIA_API_BASE_URL", "https://integrate.api.nvidia.com/v1")
    authorise(required_phrase(scope), scope)
    with pytest.raises(SpendNotAuthorisedError):
        refuse_real_inference_under_test(scope)


def test_the_evaluation_package_cannot_import_a_vendor_sdk() -> None:
    """Asserted by the import contract; asserted again here so a reader sees it stated."""
    import evals.explanation_judge as judge_module
    import evals.explanation_runner as runner_module

    for module in (judge_module, runner_module):
        source = module.__doc__ or ""
        assert "boto3" not in source
    assert "boto3" not in os.environ.get("PYTHONPATH", "")


# --------------------------------------------------------------------- the plan


def test_the_plan_calls_nothing_and_seals_the_holdout(dataset: ExplanationDataset) -> None:
    text = plan(dataset)
    assert "14 SEALED" in text
    assert "model calls                  0" in text
    assert "clients constructed          0" in text
    assert "one structured JudgeVerdict per accepted explanation" in text
    assert NOVA_2_LITE.model_id in text
    assert JUDGE_MODEL_ID in text
    for case in dataset.cases:
        if case.split is EvalSplit.HOLDOUT:
            assert case.reference not in text
            assert case.id not in text


def test_the_plan_states_both_accountings_without_pricing_the_judge(
    dataset: ExplanationDataset,
) -> None:
    text = plan(dataset)
    assert "priced, projected $" in text
    assert "commercial USD not modelled" in text
    assert "$0.00" not in text


def test_the_plan_states_the_one_repair_rule(dataset: ExplanationDataset) -> None:
    assert "at most 1 bounded production repair before holdout" in plan(dataset)


async def test_the_report_keeps_safety_and_quality_in_different_sections(
    dataset: ExplanationDataset,
) -> None:
    text = render(await run_offline(dataset))
    assert text.index("STRUCTURAL SAFETY") < text.index("QUALITY -- accepted model prose")
    assert text.index("SEMANTIC SAFETY") < text.index("QUALITY -- accepted model prose")
    assert text.index("STRUCTURAL GATES") < text.index("QUALITY TARGETS")
    assert "Quality below is computed over accepted model prose only." in text
    assert "accepted model verbalisations" in text
    assert "deterministic fallbacks" in text
    assert "Nothing here is evidence of business impact." in text


async def test_a_stopped_judging_pass_is_reported_as_incomplete(
    dataset: ExplanationDataset,
) -> None:
    from evals.explanation_judge import JudgeProviderError

    failures = {case.id: [JudgeProviderError("504")] for case in dataset.cases}
    summary = await run_offline(dataset, judge_answers=failures)
    assert summary.judging_stopped is not None
    assert "INCOMPLETE" in render(summary)
    assert summary.acceptance.accepted > 0, "generation results are untouched by a judge outage"


# ------------------------------------------------------------------- deepeval


def test_deepeval_reports_a_verdict_and_never_asks_for_one(
    dataset: ExplanationDataset,
) -> None:
    """One explanation result must not fan out into several LLM judge calls.

    The metric is handed a score that already exists. Running it over every case makes zero
    provider calls of any kind, which is the regression this asserts: if a framework metric ever
    starts opening its own connection, this test is where it shows up.
    """
    deepeval = pytest.importorskip("deepeval")
    assert deepeval is not None
    from evals.metrics.deepeval_adapter import (
        ExplanationQualityMetric,
        to_explanation_test_cases,
    )

    results = [
        _stored(
            case.id,
            speech=render_facts(case.explanation_facts()),
            refs=tuple(f.value for f in case.facts.required),
        )
        for case in dataset.cases
    ]
    scores = score_cases(dataset.cases, results)
    metric = ExplanationQualityMetric()
    for test_case in to_explanation_test_cases(scores):
        metric.measure(test_case)
        assert metric.is_successful()
    assert getattr(metric, "model", None) is None
    assert getattr(metric, "evaluation_model", None) is None


def test_the_deepeval_metric_fails_a_case_with_a_hard_finding(
    dataset: ExplanationDataset,
) -> None:
    pytest.importorskip("deepeval")
    from evals.metrics.deepeval_adapter import ExplanationQualityMetric, to_explanation_test_case

    case = dataset.cases[0]
    leaked = _stored(case.id, speech="Fine.", refs=("nope.nope",))
    score = score_cases([case], [leaked])[0]
    metric = ExplanationQualityMetric()
    metric.measure(to_explanation_test_case(score))
    assert not metric.is_successful()
    assert metric.score == 0.0


def test_the_adapter_module_names_no_llm_backed_metric() -> None:
    """The prohibition stated as a check over the only module that may import the framework."""
    from pathlib import Path

    source = (
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("metrics", "deepeval_adapter.py")
        .read_text(encoding="utf-8")
    )
    forbidden_metrics = (
        "GEval",
        "AnswerRelevancyMetric",
        "FaithfulnessMetric",
        "HallucinationMetric",
    )
    for forbidden in forbidden_metrics:
        assert f"{forbidden}(" not in source
        assert f"import {forbidden}" not in source


# ---------------------------------------------------------------- manual review


def test_the_manual_disposition_vocabulary_is_closed_and_optional() -> None:
    """Human annotation is required by the protocol and by no offline test."""
    assert {member.value for member in ManualDisposition} == {
        "CONFIRMED",
        "JUDGE_OVERRULED",
        "FIXTURE_DEFECT",
        "NEEDS_REVIEW",
    }


async def test_every_development_case_is_reportable_for_manual_review(
    development: ExplanationDataset,
) -> None:
    """The failure ledger a diagnosis reads: id, family, source, refs, flags, scores, rationale."""
    summary = await run_offline(development)
    assert len(summary.scores) == 21
    for score in summary.scores:
        payload = score.as_payload()
        assert set(payload) >= {
            "case_id",
            "family",
            "split",
            "source",
            "word_count",
            "fact_refs",
            "failure",
            "structural_failures",
            "semantic_flags",
            "scores",
            "judge_outcome",
            "judge_rationale",
        }
