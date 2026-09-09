"""One judge call per passage, a contract that refuses a broken verdict, and no authority at all.

Three properties are asserted here over and over, because between them they are the whole of what
makes a subjective number in this gate trustworthy:

* **Exactly one logical call per accepted passage.** Twenty-one accepted explanations cost at
  most twenty-one ordinary judge calls -- never a hundred and five, never one per dimension, and
  never one a framework opened on its own.
* **A broken verdict is not a score.** Strict Pydantic refuses a 0, a 6, a float, a missing field,
  an unknown field and a string where a boolean belongs. Nothing is clamped, defaulted or
  partially believed; an answer that will not validate produces ``JUDGE_RESULT_INVALID``.
* **The judge decides nothing.** It cannot promote a passage production refused, cannot lower a
  structural finding, and its outage is recorded as its own outage rather than as a failure of
  the model it was going to grade.
"""

from __future__ import annotations

import pytest
from evals.cases import EvalSplit
from evals.explanation_cases import ExplanationFamily, to_model_input
from evals.explanation_dataset import ExplanationDataset, load_explanation_dataset
from evals.explanation_judge import (
    JUDGE_CORRECTIVE_RETRIES,
    JUDGE_MODEL_ID,
    JUDGE_PROVIDER,
    CountedJudge,
    JudgeCallCeilingError,
    JudgeContractError,
    Judgement,
    JudgeNotConfiguredError,
    JudgeProviderError,
    JudgeVerdict,
    ScriptedJudge,
    StructuredJudge,
    build_judge_request,
    judge_prompt_hash,
    parse_verdict,
    stored_verdict,
    to_judge_result,
    verdict_schema_hash,
)
from evals.explanation_metrics import score_cases, semantic_metrics
from evals.explanation_results import (
    ExplanationSource,
    GenerationIdentity,
    JudgeOutcome,
    NovaExplanationResult,
    Usage,
)
from evals.explanation_runner import judge_explanations, run_offline
from evals.explanation_thresholds import MAX_JUDGE_PROVIDER_FAILURES

GOOD: dict[str, object] = {
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
    "brief_rationale": "grounded and short",
}


@pytest.fixture(scope="module")
def dataset() -> ExplanationDataset:
    return load_explanation_dataset()


def _result(case_id: str, *, accepted: bool = True) -> NovaExplanationResult:
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
        speech="a passage",
        fact_refs=("case.exception",),
    )


# ----------------------------------------------------------------- the verdict contract


def test_a_verdict_carries_every_flag_and_every_score_in_one_object() -> None:
    """One call answers the whole question, which is why one call is enough."""
    verdict = JudgeVerdict.model_validate(GOOD)
    assert set(verdict.scores) == {
        "faithfulness",
        "causal_completeness",
        "clarity",
        "brevity",
        "speech_naturalness",
    }
    assert verdict.safe
    assert verdict.safety_flags == ()


@pytest.mark.parametrize("score", [0, 6, -1, 100])
def test_a_score_outside_one_to_five_is_refused_and_never_clamped(score: int) -> None:
    with pytest.raises(JudgeContractError):
        parse_verdict({**GOOD, "faithfulness": score})


def test_a_float_is_refused_rather_than_truncated_to_an_integer() -> None:
    """``4.7`` becoming ``4`` would be the harness inventing a score nobody gave."""
    with pytest.raises(JudgeContractError):
        parse_verdict({**GOOD, "clarity": 4.7})


def test_a_string_where_a_boolean_belongs_is_refused() -> None:
    with pytest.raises(JudgeContractError):
        parse_verdict({**GOOD, "authority_contradiction": "false"})


def test_a_missing_score_is_refused_rather_than_defaulted() -> None:
    payload = dict(GOOD)
    del payload["brevity"]
    with pytest.raises(JudgeContractError):
        parse_verdict(payload)


def test_a_missing_hard_flag_is_refused_rather_than_read_as_no_finding() -> None:
    """A default of ``False`` here would read as "checked, and found nothing"."""
    payload = dict(GOOD)
    del payload["authority_contradiction"]
    with pytest.raises(JudgeContractError):
        parse_verdict(payload)


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(JudgeContractError):
        parse_verdict({**GOOD, "confidence": 0.9})


def test_a_rationale_longer_than_the_bound_is_refused() -> None:
    with pytest.raises(JudgeContractError):
        parse_verdict({**GOOD, "brief_rationale": "x" * 401})


def test_an_empty_rationale_is_refused() -> None:
    with pytest.raises(JudgeContractError):
        parse_verdict({**GOOD, "brief_rationale": ""})


def test_an_empty_or_non_object_payload_is_refused() -> None:
    with pytest.raises(JudgeContractError):
        parse_verdict({})
    with pytest.raises(JudgeContractError):
        parse_verdict("looks good to me")
    with pytest.raises(JudgeContractError):
        parse_verdict(None)


def test_the_flags_a_verdict_raises_are_named_back(dataset: ExplanationDataset) -> None:
    verdict = parse_verdict(
        {**GOOD, "authority_contradiction": True, "unsupported_quantity_in_words": True}
    )
    assert verdict.safety_flags == (
        "authority_contradiction",
        "unsupported_quantity_in_words",
    )
    assert not verdict.safe


# ---------------------------------------------------------------- one call per passage


async def test_one_accepted_passage_costs_exactly_one_logical_judge_call(
    dataset: ExplanationDataset,
) -> None:
    provider = ScriptedJudge()
    judge = CountedJudge(StructuredJudge(provider))
    case = dataset.cases[0]
    request = build_judge_request(case.id, case.family, to_model_input(case).request, "a passage")
    await judge.judge(request)
    assert judge.usage.logical_calls == 1
    assert judge.usage.provider_attempts == 1
    assert provider.seen == [case.id]


async def test_twenty_one_accepted_passages_cost_twenty_one_judge_calls(
    dataset: ExplanationDataset,
) -> None:
    """The cost boundary, proved with instrumentation rather than asserted in a comment.

    Not five per case, not one per quality dimension, not one extra because a framework metric
    wanted its own opinion. One question is asked about one passage.
    """
    development = dataset.split([EvalSplit.DEVELOPMENT])
    summary = await run_offline(development)
    accepted = summary.acceptance.accepted
    assert accepted == summary.semantic.judged
    assert summary.judge_usage.logical_calls == accepted
    assert summary.judge_usage.logical_calls <= 21
    assert summary.judge_usage.logical_calls * 5 != summary.judge_usage.logical_calls, (
        "a per-dimension judge would have made five times this many calls"
    )


async def test_a_fallback_is_never_judged(dataset: ExplanationDataset) -> None:
    """PromisePatch wrote it. Grading our own template against our own facts scores the harness."""
    provider = ScriptedJudge()
    judge = CountedJudge(StructuredJudge(provider))
    outcome = await judge_explanations(
        dataset,
        [_result("explain.plan.001"), _result("explain.plan.002", accepted=False)],
        judge,
        run_id="run",
    )
    assert [result.case_id for result in outcome.results] == ["explain.plan.001"]
    assert judge.usage.logical_calls == 1


async def test_a_bounded_correction_is_one_logical_call_and_two_attempts(
    dataset: ExplanationDataset,
) -> None:
    """The retry is a fact about the transport. The passage was judged once."""
    provider = ScriptedJudge({"c": [{"faithfulness": 9}, GOOD]})
    judge = CountedJudge(StructuredJudge(provider))
    request = build_judge_request(
        "c", ExplanationFamily.PLAN_SUMMARY, to_model_input(dataset.cases[0]).request, "passage"
    )
    judgement = await judge.judge(request)
    assert judgement.outcome is JudgeOutcome.SCORED
    assert judge.usage.logical_calls == 1
    assert judge.usage.provider_attempts == 1 + JUDGE_CORRECTIVE_RETRIES


async def test_a_second_broken_answer_is_not_a_third_attempt(
    dataset: ExplanationDataset,
) -> None:
    provider = ScriptedJudge({"c": [{"faithfulness": 9}, {"faithfulness": 0}, GOOD]})
    judge = CountedJudge(StructuredJudge(provider))
    request = build_judge_request(
        "c", ExplanationFamily.PLAN_SUMMARY, to_model_input(dataset.cases[0]).request, "passage"
    )
    judgement = await judge.judge(request)
    assert judgement.outcome is JudgeOutcome.JUDGE_RESULT_INVALID
    assert judgement.verdict is None
    assert judge.usage.provider_attempts == 2


async def test_a_call_ceiling_refuses_the_call_that_would_cross_it(
    dataset: ExplanationDataset,
) -> None:
    judge = CountedJudge(StructuredJudge(ScriptedJudge()), max_logical_calls=1)
    request = build_judge_request(
        "c", ExplanationFamily.PLAN_SUMMARY, to_model_input(dataset.cases[0]).request, "passage"
    )
    await judge.judge(request)
    with pytest.raises(JudgeCallCeilingError):
        await judge.judge(request)


# ------------------------------------------------------------------------- failures


async def test_a_judge_outage_is_recorded_as_a_judge_outage(
    dataset: ExplanationDataset,
) -> None:
    """The passage stands. There is no reading of an outage in which Nova did anything wrong."""
    provider = ScriptedJudge({"explain.plan.001": [JudgeProviderError("504")]})
    judge = CountedJudge(StructuredJudge(provider))
    generation = _result("explain.plan.001")
    outcome = await judge_explanations(dataset, [generation], judge, run_id="run")
    verdict = outcome.results[0]
    assert verdict.outcome is JudgeOutcome.JUDGE_PROVIDER_FAILURE
    assert verdict.verdict is None
    assert generation.source is ExplanationSource.VERBALISED
    assert generation.failure is None


async def test_three_judge_outages_stop_judging_and_leave_quality_incomplete(
    dataset: ExplanationDataset,
) -> None:
    failures = {f"explain.plan.00{index}": [JudgeProviderError("504")] for index in range(1, 6)}
    judge = CountedJudge(StructuredJudge(ScriptedJudge(failures)))
    results = [_result(f"explain.plan.00{index}") for index in range(1, 6)]
    outcome = await judge_explanations(dataset, results, judge, run_id="run")
    assert not outcome.complete
    assert "INCOMPLETE" in (outcome.stopped or "")
    assert judge.provider_failures == MAX_JUDGE_PROVIDER_FAILURES
    assert len(outcome.results) == MAX_JUDGE_PROVIDER_FAILURES


async def test_judging_refuses_rather_than_choosing_a_default_model(
    dataset: ExplanationDataset,
) -> None:
    """A framework quietly selecting its own evaluation model is the failure this closes."""
    with pytest.raises(JudgeNotConfiguredError):
        await judge_explanations(dataset, [_result("explain.plan.001")], None, run_id="run")


def test_an_unscored_case_contributes_nothing_rather_than_a_zero(
    dataset: ExplanationDataset,
) -> None:
    generation = _result("explain.plan.001")
    judgement = to_judge_result(
        generation,
        _failed_judgement(),
        provider="nvidia",
        model_id=JUDGE_MODEL_ID,
        run_id="run",
    )
    scores = score_cases(dataset.cases, [generation], [judgement])
    assert scores[0].scores == {}
    assert semantic_metrics(scores).judged == 0


def _failed_judgement() -> Judgement:
    return Judgement(
        outcome=JudgeOutcome.JUDGE_PROVIDER_FAILURE,
        verdict=None,
        usage=Usage(logical_calls=1, provider_attempts=1),
        detail="504",
    )


# ------------------------------------------------------------------------- identity


def test_the_judge_is_pinned_and_independent_of_the_model_under_test() -> None:
    assert JUDGE_PROVIDER == "nvidia"
    assert JUDGE_MODEL_ID == "nvidia/nemotron-3-super-120b-a12b"


def test_a_judge_result_binds_to_its_rubric_its_schema_and_the_generation_it_judged() -> None:
    generation = _result("explain.plan.001")
    judgement = _scored()
    result = to_judge_result(
        generation, judgement, provider="nvidia", model_id=JUDGE_MODEL_ID, run_id="run"
    )
    assert result.identity.generation_fingerprint == generation.identity.fingerprint()
    assert result.identity.judge_prompt_hash == judge_prompt_hash()
    assert result.identity.verdict_schema_hash == verdict_schema_hash()
    assert result.identity.rubric_version
    assert stored_verdict(result) is not None


def test_a_judge_identity_is_not_a_generation_identity() -> None:
    """Two records, because rejudging without regenerating needs them to be separable."""
    generation = _result("explain.plan.001")
    result = to_judge_result(
        generation, _scored(), provider="nvidia", model_id=JUDGE_MODEL_ID, run_id="run"
    )
    assert result.identity.fingerprint() != generation.identity.fingerprint()


def test_a_stored_verdict_is_revalidated_rather_than_trusted() -> None:
    generation = _result("explain.plan.001")
    result = to_judge_result(
        generation, _scored(), provider="nvidia", model_id=JUDGE_MODEL_ID, run_id="run"
    )
    tampered = result.model_copy(update={"verdict": {**GOOD, "faithfulness": 9}})
    with pytest.raises(JudgeContractError):
        stored_verdict(tampered)


def _scored() -> Judgement:
    return Judgement(
        outcome=JudgeOutcome.SCORED,
        verdict=JudgeVerdict.model_validate(GOOD),
        usage=Usage(logical_calls=1, provider_attempts=1),
    )
