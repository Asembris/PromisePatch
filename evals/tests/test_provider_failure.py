"""A call nobody answered is not a model that answered badly.

A challenger run once put three questions to a model, was refused by the provider on all
three, and reported two of them as ``UNCHANGED_FAILURE`` and one as ``CONTROL_REGRESSION``.
Every one of those words asserts that a model read a sentence and read it wrongly. None of
them had been read. The report looked like evidence about a model and was evidence about an
account, and the numbers in it -- a repair rate, a regression count -- were arithmetic over
absences.

These tests fix the boundary. The four model-quality outcomes require two readings. A missing
reading has its own outcome, is excluded from every denominator, leaves the stage incomplete,
and therefore cannot open Stage B. And the whole of it is reconstructible from what a failed
run wrote down, with nothing called.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from evals.cases import CustomerCase, EvalJob, EvalSplit
from evals.challenger import (
    FAILURE_CATEGORIES,
    SEMANTIC_OUTCOMES,
    PairedOutcome,
    ProviderFailureCategory,
    Role,
    SourceRun,
    build_stage_a,
    cluster_deltas,
    compare,
    customer_totals,
    evaluate_materiality,
    pair_case,
    provider_failure_category,
    scores_for,
    select_stage_a,
    unread_result,
    usage_profile,
)
from evals.dataset import GoldDataset, load_dataset
from evals.results import CaseResult, ExecutionStatus
from evals.store import ProviderFailureLog, ProviderFailureRecord

from promisepatch.semantic import ApparentIntent

NOVA = "us.amazon.nova-2-lite-v1:0"
HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


@pytest.fixture(scope="module")
def dataset() -> GoldDataset:
    return load_dataset()


def development(dataset: GoldDataset) -> tuple[CustomerCase, ...]:
    return tuple(case for case in dataset.customer if case.split is EvalSplit.DEVELOPMENT)


def reading(
    case: CustomerCase, predicted: ApparentIntent | None, *, model_id: str = NOVA
) -> CaseResult:
    """One stored reading: a model was reached and said something."""
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
        input_tokens=400,
        output_tokens=12,
        estimated_usd="0.00015",
    )


def refusal(case: CustomerCase, *, category: str = "SemanticProviderError") -> CaseResult:
    """One attempt that produced nothing: the provider was asked and did not answer.

    Shaped exactly as the runner shapes it -- no attempts, no telemetry, no tokens, no cost,
    ``provider_error`` set. Nothing is invented, because nothing was measured.
    """
    return CaseResult(
        case_id=case.id,
        job=case.job,
        split=case.split,
        tags=case.tags,
        expected={"apparent_intent": case.expected.value},
        observed={"apparent_intent": None},
        metrics={
            "answered": False,
            "expected": case.expected.value,
            "predicted": None,
            "correct": False,
            "authority_violation": False,
            "refusal_category": category,
        },
        passed=False,
        reason=f"no usable answer ({category})",
        provider="bedrock",
        model_id=None,
        attempts=None,
        e2e_latency_ms=167,
        error_category=category,
        provider_error=True,
    )


def source_run(dataset: GoldDataset, wrong: Mapping[str, ApparentIntent | None]) -> SourceRun:
    results = [reading(case, wrong.get(case.id, case.expected)) for case in development(dataset)]
    return SourceRun(
        run_id="source0000001",
        model_id=NOVA,
        provider="bedrock",
        git_sha="0" * 40,
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        results=tuple(results),
    )


def two_failures(dataset: GoldDataset) -> Mapping[str, ApparentIntent | None]:
    approve = [c for c in development(dataset) if c.expected is ApparentIntent.APPARENT_APPROVE]
    decline = [c for c in development(dataset) if c.expected is ApparentIntent.APPARENT_DECLINE]
    return {approve[0].id: ApparentIntent.UNCLEAR, decline[0].id: ApparentIntent.UNCLEAR}


def case_by_id(dataset: GoldDataset, case_id: str) -> CustomerCase:
    return next(case for case in dataset.customer if case.id == case_id)


def correct(dataset: GoldDataset, case_id: str) -> CaseResult:
    """A challenger reading of one case that got it right."""
    case = case_by_id(dataset, case_id)
    return reading(case, case.expected, model_id=HAIKU)


# ------------------------------------------------------------------ the execution status


def test_a_refusal_by_the_provider_is_not_an_answer(dataset: GoldDataset) -> None:
    case = development(dataset)[0]
    assert refusal(case).execution_status is ExecutionStatus.PROVIDER_FAILURE
    assert not refusal(case).has_reading


def test_an_answer_the_gate_rejected_is_still_an_answer(dataset: GoldDataset) -> None:
    """The model was reached and it spoke. That its answer was unusable is a fact about it."""
    case = development(dataset)[0]
    rejected = reading(case, None).model_copy(
        update={"error_category": "SCHEMA_INVALID", "attempts": 2}
    )
    assert rejected.execution_status is ExecutionStatus.ANSWERED
    assert rejected.has_reading


def test_a_sentence_the_boundary_never_asks_about_is_neither(dataset: GoldDataset) -> None:
    """Its score is the assertion that nothing was asked, which is not a model outcome."""
    forbidden = next(
        result
        for result in [
            CaseResult(
                case_id="worker.deterministic.eggs.001",
                job=EvalJob.WORKER_SEMANTICS,
                split=EvalSplit.DEVELOPMENT,
                tags=(),
                expected={"asked": False},
                observed={},
                metrics={"asked": False},
                passed=True,
                reason="no model is asked about this sentence, and none was",
                provider="live",
            )
        ]
    )
    assert forbidden.execution_status is ExecutionStatus.NOT_INVOKED
    assert not forbidden.has_reading


def test_the_category_is_coarse_and_carries_no_provider_message(dataset: GoldDataset) -> None:
    case = development(dataset)[0]
    assert (
        provider_failure_category(refusal(case, category="SemanticTimeoutError"))
        is ProviderFailureCategory.TIMEOUT
    )
    assert (
        provider_failure_category(refusal(case, category="SemanticProviderError"))
        is ProviderFailureCategory.PROVIDER_UNREACHABLE
    )
    assert (
        provider_failure_category(refusal(case, category="SomethingElse"))
        is ProviderFailureCategory.UNKNOWN_PROVIDER_FAILURE
    )
    assert provider_failure_category(reading(case, case.expected)) is None


def test_a_boundary_that_names_its_faults_gets_named_categories(dataset: GoldDataset) -> None:
    """Resolution follows the exception type, because that is all a stored result may keep.

    A provider's own message can carry an account id, an organisation or a fragment of the
    request, so none of it is persisted. A boundary that wants "the key was rejected" told apart
    from "we could not connect" therefore has to raise two types, and the OpenAI adapter does.
    The Bedrock adapter raises one, so its faults stay collapsed -- which is honest rather than
    unfortunate: inventing the distinction from a stored result would be a guess.
    """
    case = development(dataset)[0]
    expected = {
        "OpenAiAuthenticationError": ProviderFailureCategory.AUTHENTICATION,
        "OpenAiPermissionError": ProviderFailureCategory.PERMISSION,
        "OpenAiRateLimitError": ProviderFailureCategory.RATE_LIMITED,
        "OpenAiInvalidRequestError": ProviderFailureCategory.INVALID_REQUEST,
        "OpenAiUnavailableError": ProviderFailureCategory.PROVIDER_UNAVAILABLE,
    }
    for class_name, category in expected.items():
        assert provider_failure_category(refusal(case, category=class_name)) is category


def test_no_category_is_ever_a_semantic_label(dataset: GoldDataset) -> None:
    """The whole reason these exist. Not one member of this enum is a reading of a sentence.

    ``UNCLEAR`` is a thing a model said. Every value below is a thing that happened instead of a
    model saying anything, and a report that let one stand in for the other would describe an
    account as if it were a model.
    """
    case = development(dataset)[0]
    labels = {intent.value for intent in ApparentIntent}
    for category in ProviderFailureCategory:
        assert category.value not in labels

    for class_name in (*FAILURE_CATEGORIES, "SomethingNobodyHasSeen"):
        result = refusal(case, category=class_name)
        assert provider_failure_category(result) is not None
        assert result.observed.get("apparent_intent") is None
        assert not result.has_reading


# ------------------------------------------------------- a failure is not a quality outcome


def test_a_nova_failure_with_no_haiku_reading_is_not_an_unchanged_failure(
    dataset: GoldDataset,
) -> None:
    """The exact mislabel a report made. ``UNCHANGED_FAILURE`` claims the challenger read it."""
    case = development(dataset)[0]
    paired = pair_case(case, Role.FAILURE, reading(case, ApparentIntent.UNCLEAR), refusal(case))
    assert paired.outcome is PairedOutcome.PROVIDER_FAILURE
    # Not UNCHANGED_FAILURE, which is what this case was reported as, and not REPAIRED.
    assert paired.outcome not in SEMANTIC_OUTCOMES
    assert not paired.comparable
    assert paired.challenger_predicted is None
    assert not paired.challenger_correct
    assert not paired.directional_inversion
    assert not paired.authority_violation
    assert paired.execution_status is ExecutionStatus.PROVIDER_FAILURE


def test_a_control_with_no_haiku_reading_is_not_a_control_regression(
    dataset: GoldDataset,
) -> None:
    """The other half of the same mislabel. Nothing regressed; nothing was measured."""
    case = development(dataset)[0]
    paired = pair_case(case, Role.CONTROL, reading(case, case.expected), refusal(case))
    assert paired.outcome is PairedOutcome.PROVIDER_FAILURE
    # Not CONTROL_REGRESSION, which is what this case was reported as.
    assert paired.outcome not in SEMANTIC_OUTCOMES


def test_the_four_quality_outcomes_still_hold_when_both_models_read(
    dataset: GoldDataset,
) -> None:
    """Normal behaviour, unchanged: two readings produce exactly the verdict they used to."""
    approve = next(c for c in development(dataset) if c.expected is ApparentIntent.APPARENT_APPROVE)
    wrong, right = ApparentIntent.UNCLEAR, approve.expected
    table = (
        (Role.FAILURE, right, PairedOutcome.REPAIRED),
        (Role.FAILURE, wrong, PairedOutcome.UNCHANGED_FAILURE),
        (Role.CONTROL, right, PairedOutcome.CONTROL_PRESERVED),
        (Role.CONTROL, wrong, PairedOutcome.CONTROL_REGRESSION),
    )
    for role, challenger_label, expected in table:
        source_label = wrong if role is Role.FAILURE else right
        paired = pair_case(
            approve,
            role,
            reading(approve, source_label),
            reading(approve, challenger_label, model_id=HAIKU),
        )
        assert paired.outcome is expected
        assert paired.comparable
        assert paired.execution_status is ExecutionStatus.ANSWERED


def test_a_failure_is_never_a_win_a_loss_or_a_tie(dataset: GoldDataset) -> None:
    """A case only one model spoke about supports none of the three, least of all a loss."""
    case = development(dataset)[0]
    only_failures = [
        pair_case(case, Role.FAILURE, reading(case, ApparentIntent.UNCLEAR), refusal(case))
    ]
    totals = compare(only_failures)
    assert (totals.cases, totals.wins, totals.losses, totals.ties) == (0, 0, 0, 0)
    assert totals.exact_paired_p is None


def test_a_failure_contributes_to_no_cluster_recall(dataset: GoldDataset) -> None:
    case = next(c for c in development(dataset) if c.tags)
    assert cluster_deltas([pair_case(case, Role.FAILURE, reading(case, None), refusal(case))]) == ()


def test_a_failure_is_not_scored_against_the_customer_metrics(dataset: GoldDataset) -> None:
    """A quality aggregate over a case nobody answered would put an outage into an accuracy."""
    case = development(dataset)[0]
    assert scores_for(dataset, [refusal(case)]) == ()
    totals = customer_totals(dataset, [reading(case, case.expected), refusal(case)])
    assert totals["cases"] == 1
    assert totals["accuracy"] == 1.0


def test_a_failure_costs_nothing_measurable_and_invents_nothing(dataset: GoldDataset) -> None:
    """AWS reported no usage, so no token count and no dollar figure are claimed."""
    case = development(dataset)[0]
    profile = usage_profile(dataset, [refusal(case)], HAIKU)
    assert profile.calls == 0
    assert profile.attempts == 0
    assert profile.input_tokens is None
    assert profile.output_tokens is None
    assert profile.estimated_usd is None
    assert profile.usd_per_correct() is None


# ------------------------------------------------------------------ the denominators


def test_the_repair_rate_denominator_is_the_failures_that_were_read(
    dataset: GoldDataset,
) -> None:
    """Six selected, three read, one repaired: the rate is 1/3 and the coverage is stated.

    Dividing by six would report 1/6 and would be a claim that five failures went unrepaired.
    Three of them were never put to the model at all.
    """
    source = source_run(dataset, two_failures(dataset))
    selection = select_stage_a(dataset, source)
    failures = list(selection.failure_ids)
    controls = list(selection.control_ids)

    results = [
        correct(dataset, failures[0]),
        refusal(case_by_id(dataset, failures[1])),
        *(correct(dataset, cid) for cid in controls),
    ]
    outcome = build_stage_a(dataset, selection, source, results)

    assert len(outcome.failures) == 2
    assert len(outcome.comparable_failures) == 1
    assert outcome.repairs == 1
    assert outcome.repair_rate == 1.0
    assert len(outcome.provider_failures) == 1
    assert outcome.provider_completion == f"{len(outcome.comparable)}/{len(selection.case_ids)}"
    payload = outcome.as_payload()
    assert payload["eligible_semantic_comparisons"] == len(outcome.comparable)
    assert payload["provider_failures"] == 1


def test_a_provider_failure_leaves_the_stage_incomplete(dataset: GoldDataset) -> None:
    source = source_run(dataset, two_failures(dataset))
    selection = select_stage_a(dataset, source)
    every = sorted(selection.case_ids)
    results = [correct(dataset, cid) for cid in every[1:]]
    results.append(refusal(case_by_id(dataset, every[0])))
    outcome = build_stage_a(dataset, selection, source, results)
    assert not outcome.complete


def test_materiality_cannot_pass_a_stage_stopped_by_provider_failures(
    dataset: GoldDataset,
) -> None:
    """Stage B is closed by the incompleteness, not by a partial number happening to be low.

    Every reading that did arrive is a repair, so the partial figures look excellent. They
    decide nothing: the verdict is unavailable rather than favourable.
    """
    source = source_run(dataset, two_failures(dataset))
    selection = select_stage_a(dataset, source)
    failures = list(selection.failure_ids)
    controls = list(selection.control_ids)
    results = [
        *(correct(dataset, cid) for cid in failures),
        *(refusal(case_by_id(dataset, cid)) for cid in controls),
    ]
    outcome = build_stage_a(dataset, selection, source, results)

    assert outcome.repairs == len(failures)
    assert outcome.repair_rate == 1.0
    assert outcome.control_regressions == 0
    verdict = evaluate_materiality(outcome)
    assert not verdict.complete
    assert not verdict.passed


def test_three_provider_failures_leave_no_quality_verdict(dataset: GoldDataset) -> None:
    """The historical shape: the stop policy fires and nothing about the model is known."""
    source = source_run(dataset, two_failures(dataset))
    selection = select_stage_a(dataset, source)
    results = [refusal(case_by_id(dataset, cid)) for cid in sorted(selection.case_ids)[:3]]
    outcome = build_stage_a(dataset, selection, source, results)

    assert len(outcome.provider_failures) == 3
    assert outcome.comparable == ()
    assert outcome.repair_rate is None
    assert outcome.repairs == 0
    assert outcome.unchanged_failures == 0
    assert outcome.control_regressions == 0
    assert not evaluate_materiality(outcome).passed


def test_a_source_run_whose_case_has_no_reading_is_not_a_challengeable_run(
    dataset: GoldDataset,
) -> None:
    """The source is evidence. A case it never answered cannot be one half of a pair."""
    source = source_run(dataset, two_failures(dataset))
    broken = SourceRun(
        run_id=source.run_id,
        model_id=source.model_id,
        provider=source.provider,
        git_sha=source.git_sha,
        dataset_version=source.dataset_version,
        dataset_hash=source.dataset_hash,
        results=(refusal(development(dataset)[0]), *source.results[1:]),
    )
    with pytest.raises(Exception) as error:
        select_stage_a(dataset, broken)
    assert "no reading" in str(error.value)
    assert "execution fact and not an answer" in str(error.value)


# ------------------------------------------------------ the attempt log, and rebuilding


def failure_record(case: CustomerCase, attempt: int = 1) -> ProviderFailureRecord:
    return ProviderFailureRecord(
        run_id="8c78170b6bf4",
        recorded_at="2026-09-07T22:03:27+00:00",
        git_sha="7ef11cb4e0ab54bfa6e561c8941b1898aabd771b",
        case_id=case.id,
        job=case.job.value,
        split=case.split.value,
        provider="bedrock",
        model_id=HAIKU,
        attempt=attempt,
        category="SemanticProviderError",
        e2e_latency_ms=167,
    )


def test_the_attempt_log_round_trips_and_counts_attempts(
    dataset: GoldDataset, tmp_path: Path
) -> None:
    case = development(dataset)[0]
    log = ProviderFailureLog(tmp_path / "failures.jsonl")
    assert log.records == ()
    log.record(failure_record(case, attempt=1))
    log.record(failure_record(case, attempt=2))

    reopened = ProviderFailureLog(tmp_path / "failures.jsonl")
    assert len(reopened.records) == 2
    assert reopened.attempts_for(case.id) == 2
    assert reopened.case_ids() == frozenset({case.id})
    assert reopened.records[0].git_sha == "7ef11cb4e0ab54bfa6e561c8941b1898aabd771b"


def test_the_attempt_log_holds_no_credential_no_token_and_no_message(
    dataset: GoldDataset,
) -> None:
    """Identifiers, a coarse category and timings. Usage and cost are absent, never zero."""
    payload = failure_record(development(dataset)[0]).as_payload()
    assert payload["input_tokens"] is None
    assert payload["output_tokens"] is None
    assert payload["estimated_usd"] is None
    assert payload["category"] == "SemanticProviderError"
    forbidden = ("secret", "token", "session", "header", "prompt", "message", "credential")
    keys = " ".join(payload).lower()
    assert not any(word in keys for word in forbidden if word != "token")
    assert "session" not in keys and "secret" not in keys


def test_a_logged_attempt_rebuilds_as_an_execution_failure_and_never_a_reading(
    dataset: GoldDataset,
) -> None:
    """The reconstruction path: stored evidence in, the right classification out, nothing called."""
    case = development(dataset)[0]
    rebuilt = unread_result(failure_record(case), case)
    assert rebuilt.provider_error
    assert rebuilt.execution_status is ExecutionStatus.PROVIDER_FAILURE
    assert not rebuilt.has_reading
    assert rebuilt.attempts is None
    assert rebuilt.input_tokens is None and rebuilt.output_tokens is None
    assert rebuilt.estimated_usd is None
    paired = pair_case(case, Role.FAILURE, reading(case, ApparentIntent.UNCLEAR), rebuilt)
    assert paired.outcome is PairedOutcome.PROVIDER_FAILURE


def test_a_rebuilt_stage_reports_the_same_execution_picture(dataset: GoldDataset) -> None:
    """Readings plus logged failures reproduce the run's own counts, with zero calls."""
    source = source_run(dataset, two_failures(dataset))
    selection = select_stage_a(dataset, source)
    every = sorted(selection.case_ids)
    live = [
        *(correct(dataset, cid) for cid in every[3:]),
        *(refusal(case_by_id(dataset, cid)) for cid in every[:3]),
    ]
    from_disk = [
        *(correct(dataset, cid) for cid in every[3:]),
        *(
            unread_result(failure_record(case_by_id(dataset, cid)), case_by_id(dataset, cid))
            for cid in every[:3]
        ),
    ]
    live_outcome = build_stage_a(dataset, selection, source, live)
    disk_outcome = build_stage_a(dataset, selection, source, from_disk)

    for key in (
        "eligible_semantic_comparisons",
        "provider_failures",
        "provider_completion",
        "repairs",
        "unchanged_failures",
        "control_regressions",
        "repair_rate",
        "complete",
    ):
        assert live_outcome.as_payload()[key] == disk_outcome.as_payload()[key]
