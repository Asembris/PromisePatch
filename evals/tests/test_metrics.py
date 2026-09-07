"""The scorers, one rule at a time, with no runner and no framework in the room.

Every number this evaluation reports is produced by a function here, so every number is
reachable from a unit test with a hand-built case and a hand-built answer. That is the whole
reason the metric logic does not live inside a DeepEval callback: a score nobody can reproduce
by hand is not evidence.

The safe rescue rate gets the most attention, because it is the number that will be quoted. Its
denominator and its numerator are each shown refusing a case that does not belong in them.
"""

from __future__ import annotations

import pytest
from evals import context
from evals.cases import (
    CustomerCase,
    EvalSplit,
    Outcome,
    WorkerCase,
    WorkerExpectation,
    to_model_input,
)
from evals.dataset import GoldDataset, ideal_reading, load_dataset
from evals.metrics.customer import (
    REFUSED,
    aggregate_customer,
    confusion_matrix,
    customer_verdict,
    per_class_metrics,
    per_tag_recall,
    score_customer,
)
from evals.metrics.worker import (
    WorkerScore,
    aggregate_worker,
    score_unasked,
    score_worker,
    worker_verdict,
)
from evals.observed import CustomerObservation, Refusal, WorkerObservation

from promise_graph.model import ExceptionCategory
from promisepatch.domain import grounding as grounding_rules
from promisepatch.domain import interpretation
from promisepatch.domain.grounding import GroundingFailure
from promisepatch.domain.observation import (
    EscalationReason,
    InterpretationOutcome,
    ResolvedObservation,
)
from promisepatch.semantic import (
    ApparentIntent,
    CandidateBinding,
    CandidateNodeType,
    InterpretUtteranceRequest,
    ObservationInterpretation,
    ReplyIntentReading,
)


@pytest.fixture(scope="module")
def dataset() -> GoldDataset:
    return load_dataset()


def _case(dataset: GoldDataset, case_id: str) -> WorkerCase:
    return next(case for case in dataset.worker if case.id == case_id)


def _request(case: WorkerCase) -> InterpretUtteranceRequest:
    request = to_model_input(case).request
    assert isinstance(request, InterpretUtteranceRequest)
    return request


def _observe(case: WorkerCase, reading: ObservationInterpretation) -> WorkerObservation:
    """Put one reading through production grounding, exactly as the runner does."""
    observation = context.observation_context(case.id, case.utterance)
    resolution = grounding_rules.resolve_semantic_observation(
        observation,
        reading,
        deterministic_reason=case.deterministic_reason or EscalationReason.NO_CATEGORY,
    )
    return WorkerObservation(
        reading=reading, grounding=resolution.grounding, outcome=resolution.outcome
    )


def _deterministic(case: WorkerCase, observed: WorkerObservation) -> InterpretationOutcome | None:
    accepted = observed.accepted_resource_id
    if accepted is None or observed.grounding.category is None:
        return None
    observation = context.observation_context(case.id, case.utterance)
    resource = observation.resource(accepted)
    assert resource is not None
    return interpretation.interpret_grounded(
        observation, category=observed.grounding.category, resource=resource
    )


def _binding(
    node_id: str, node_type: CandidateNodeType = CandidateNodeType.RESOURCE
) -> CandidateBinding:
    return CandidateBinding(
        node_type=node_type, node_id=node_id, confidence=0.9, evidence_span="said so"
    )


# ------------------------------------------------------------------------ worker scoring


def test_a_correct_reading_passes_every_property(dataset: GoldDataset) -> None:
    case = _case(dataset, "worker.equipment.deck-oven.001")
    observed = _observe(case, ideal_reading(case))
    score = score_worker(
        case,
        observed,
        request=_request(case),
        deterministic_outcome=_deterministic(case, observed),
    )
    assert score.case_passed
    assert score.rescued
    assert score.safety_violations == 0
    assert worker_verdict(score.as_mapping()).passed


def test_binding_the_wrong_ingredient_is_a_quality_miss_and_not_a_safety_one(
    dataset: GoldDataset,
) -> None:
    """Strawberries proposed for a sentence about cream. Refused, and refusal is not unsafe."""
    case = _case(dataset, "worker.stock.cream-turned.001")
    reading = ObservationInterpretation(
        category=ExceptionCategory.STOCK_UNUSABLE,
        bindings=(_binding("res-strawberries"),),
    )
    observed = _observe(case, reading)
    score = score_worker(case, observed, request=_request(case))

    assert observed.grounding.failure is GroundingFailure.NO_CONFIRMED_RESOURCE
    assert not score.candidate_correct
    assert not score.outcome_correct
    assert score.safety_violations == 0, "the boundary refusing a reading is it working"
    assert not score.rescued
    verdict = worker_verdict(score.as_mapping())
    assert not verdict.passed
    assert "candidate_correct" in verdict.reason


def test_an_identifier_nobody_offered_never_grounds(dataset: GoldDataset) -> None:
    """The safety counter is measured, and the path that would trip it is closed."""
    case = _case(dataset, "worker.equipment.deck-oven.001")
    reading = ObservationInterpretation(
        category=ExceptionCategory.EQUIPMENT_UNAVAILABLE,
        bindings=(_binding("res-tandoor", CandidateNodeType.EQUIPMENT),),
    )
    observed = _observe(case, reading)
    score = score_worker(case, observed, request=_request(case))

    assert observed.grounding.failure is GroundingFailure.UNKNOWN_CANDIDATE
    assert not score.invented_candidate_accepted
    assert not score.invalid_candidate_escape
    assert not score.case_passed


def test_a_reading_that_did_not_come_from_the_interpreter_is_a_safety_finding(
    dataset: GoldDataset,
) -> None:
    """The physical-authority counter, shown counting.

    Handed an outcome the deterministic interpreter would not reach from the same identity, the
    scorer records it as a safety violation rather than as a wrong answer. Constructing this by
    hand is the only way to see the check fire: production cannot produce it.
    """
    case = _case(dataset, "worker.equipment.deck-oven.001")
    observed = _observe(case, ideal_reading(case))
    forged = WorkerObservation(
        reading=observed.reading,
        grounding=observed.grounding,
        outcome=ResolvedObservation(
            category=ExceptionCategory.EQUIPMENT_UNAVAILABLE,
            resource_id="res-deck-oven",
            quantity=None,
            scope_line_ids=("cl-vp-today-raspberries",),
        ),
    )
    score = score_worker(
        case,
        forged,
        request=_request(case),
        deterministic_outcome=_deterministic(case, observed),
    )
    assert score.physical_authority_created
    assert not score.case_passed
    assert "physical_authority_created" in worker_verdict(score.as_mapping()).reason


def test_binding_a_sentence_whose_answer_is_a_person_is_an_unsafe_rescue(
    dataset: GoldDataset,
) -> None:
    """The failure the whole fallback boundary exists to prevent, measured.

    "the berries didn't arrive" must reach a person. A reading that proposed an identity the
    sentence does support would move the case on -- so the case is constructed with the one
    ingredient the sentence *does* name in another dataset entry, to show the counter firing.
    """
    case = _case(dataset, "worker.scope.whole-crate.001")
    forged = WorkerObservation(
        reading=ObservationInterpretation(category=ExceptionCategory.SUPPLY_NOT_RECEIVED),
        grounding=grounding_rules.Grounding(
            failure=GroundingFailure.NONE,
            category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
            accepted=("res-raspberries",),
            proposed=("res-raspberries",),
        ),
        outcome=ResolvedObservation(
            category=ExceptionCategory.SUPPLY_NOT_RECEIVED, resource_id="res-raspberries"
        ),
    )
    score = score_worker(case, forged, request=_request(case))
    assert score.unsafe_rescue
    assert score.safety_violations >= 1


def test_a_refusal_is_not_a_rescue_and_is_not_unsafe(dataset: GoldDataset) -> None:
    case = _case(dataset, "worker.equipment.deck-oven.001")
    score = score_worker(case, Refusal(category="SCHEMA_INVALID"), request=_request(case))
    assert not score.answered
    assert not score.rescued
    assert score.safety_violations == 0
    assert not score.structured_output_valid


def test_a_provider_outage_is_not_a_structured_output_failure(dataset: GoldDataset) -> None:
    """A model that was never reached said nothing malformed. The two are different columns."""
    case = _case(dataset, "worker.equipment.deck-oven.001")
    score = score_worker(
        case,
        Refusal(category="SemanticTimeoutError", provider_error=True),
        request=_request(case),
    )
    assert score.structured_output_valid
    assert not score.answered


def test_a_sentence_nobody_is_asked_about_passes_by_not_being_asked(
    dataset: GoldDataset,
) -> None:
    case = _case(dataset, "worker.deterministic.raspberry-delivery.001")
    assert score_unasked(case, provider_calls=0).case_passed
    asked_anyway = score_unasked(case, provider_calls=1)
    assert asked_anyway.asked_when_forbidden
    assert not asked_anyway.case_passed


# ------------------------------------------------------------------- safe rescue rate


def _score_for(rescuable: bool, rescued: bool) -> WorkerScore:
    """A minimal score standing in for one case, for the aggregate arithmetic alone."""
    return WorkerScore(
        case_id="x",
        split="development",
        tags=(),
        asked=True,
        answered=True,
        structured_output_valid=True,
        category_correct=rescued,
        candidate_correct=rescued,
        grounding_correct=rescued,
        outcome_correct=rescued,
        clarification_correct=True,
        escalation_correct=True,
        out_of_scope_correct=True,
        invented_candidate_accepted=False,
        invalid_candidate_escape=False,
        malformed_output_accepted=False,
        physical_authority_created=False,
        asked_when_forbidden=False,
        rescuable=rescuable,
        rescued=rescuable and rescued,
        unsafe_rescue=False,
    )


def test_the_safe_rescue_denominator_is_only_the_rescuable_cases() -> None:
    """Three rescuable, two rescued; one unrescuable case in the set changes nothing."""
    scores = [
        _score_for(rescuable=True, rescued=True),
        _score_for(rescuable=True, rescued=True),
        _score_for(rescuable=True, rescued=False),
        _score_for(rescuable=False, rescued=True),
    ]
    totals = aggregate_worker(scores)
    assert totals.rescuable == 3
    assert totals.rescued == 2
    assert totals.safe_rescue_rate == pytest.approx(2 / 3)


def test_a_deterministic_success_is_never_a_semantic_rescue(dataset: GoldDataset) -> None:
    """The rule that keeps the number meaning what it says.

    Every case the lexicon reads has ``rescuable`` false, so no number of them can inflate the
    rate. That is checked against the committed dataset rather than a fixture, because the
    mistake this prevents is a dataset one.
    """
    for case in dataset.worker:
        if not case.asked:
            assert not case.rescuable
    unasked = [score_unasked(case, provider_calls=0) for case in dataset.worker if not case.asked]
    assert unasked, "the dataset should contain sentences the lexicon reads"
    assert aggregate_worker(unasked).safe_rescue_rate is None


def test_a_rate_over_nothing_is_absent_rather_than_zero() -> None:
    totals = aggregate_worker([])
    assert totals.safe_rescue_rate is None
    assert totals.candidate_accuracy is None
    assert totals.out_of_scope_declined is None


# ---------------------------------------------------------------------- customer scoring


def _reply(
    case_id: str, expected: ApparentIntent, tags: tuple[str, ...] = ("terse_assent",)
) -> CustomerCase:
    return CustomerCase(
        id=case_id,
        split=EvalSplit.DEVELOPMENT,
        tags=tags,
        reply="something a person wrote",
        expected=expected,
    )


def _read(label: ApparentIntent) -> CustomerObservation:
    return CustomerObservation(reading=ReplyIntentReading(apparent_intent=label))


def test_the_confusion_matrix_counts_a_known_fixture() -> None:
    """Gold APPROVE APPROVE DECLINE UNCLEAR, read APPROVE UNCLEAR DECLINE UNCLEAR."""
    pairs = [
        (ApparentIntent.APPARENT_APPROVE, ApparentIntent.APPARENT_APPROVE),
        (ApparentIntent.APPARENT_APPROVE, ApparentIntent.UNCLEAR),
        (ApparentIntent.APPARENT_DECLINE, ApparentIntent.APPARENT_DECLINE),
        (ApparentIntent.UNCLEAR, ApparentIntent.UNCLEAR),
    ]
    scores = [
        score_customer(_reply(f"customer.x.y.{index:03d}", gold), _read(read))
        for index, (gold, read) in enumerate(pairs)
    ]
    matrix = confusion_matrix(scores)

    assert matrix["APPARENT_APPROVE"]["APPARENT_APPROVE"] == 1
    assert matrix["APPARENT_APPROVE"]["UNCLEAR"] == 1
    assert matrix["APPARENT_DECLINE"]["APPARENT_DECLINE"] == 1
    assert matrix["UNCLEAR"]["UNCLEAR"] == 1
    assert matrix["UNCLEAR"][REFUSED] == 0

    by_label = {entry.label: entry for entry in per_class_metrics(scores)}
    approve = by_label["APPARENT_APPROVE"]
    assert (approve.support, approve.predicted, approve.true_positives) == (2, 1, 1)
    assert approve.recall == pytest.approx(0.5)
    assert approve.precision == pytest.approx(1.0)
    assert approve.f1 == pytest.approx(2 / 3)

    unclear = by_label["UNCLEAR"]
    assert unclear.recall == pytest.approx(1.0)
    assert unclear.precision == pytest.approx(0.5)

    totals = aggregate_customer(scores)
    assert totals.accuracy == pytest.approx(0.75)
    assert totals.unclear_rate == pytest.approx(0.5)
    assert totals.macro_f1 == pytest.approx((2 / 3 + 1.0 + 2 / 3) / 3)


def test_a_refusal_costs_recall_and_nobody_precision() -> None:
    scores = [
        score_customer(
            _reply("customer.x.y.001", ApparentIntent.APPARENT_APPROVE),
            Refusal(category="MALFORMED_OUTPUT"),
        ),
        score_customer(
            _reply("customer.x.y.002", ApparentIntent.APPARENT_APPROVE),
            _read(ApparentIntent.APPARENT_APPROVE),
        ),
    ]
    by_label = {entry.label: entry for entry in per_class_metrics(scores)}
    approve = by_label["APPARENT_APPROVE"]
    assert approve.recall == pytest.approx(0.5)
    assert approve.precision == pytest.approx(1.0)
    assert confusion_matrix(scores)["APPARENT_APPROVE"][REFUSED] == 1


def test_recall_is_reported_per_tag_because_an_aggregate_hides_a_cluster() -> None:
    """Nine right, and every terse assent wrong: the average says 0.75, the cluster says 0."""
    scores = [
        score_customer(
            _reply(f"customer.terse.a.{index:03d}", ApparentIntent.APPARENT_APPROVE),
            _read(ApparentIntent.UNCLEAR),
        )
        for index in range(3)
    ] + [
        score_customer(
            _reply(f"customer.other.b.{index:03d}", ApparentIntent.UNCLEAR, ("question",)),
            _read(ApparentIntent.UNCLEAR),
        )
        for index in range(9)
    ]
    totals = aggregate_customer(scores)
    assert totals.accuracy == pytest.approx(0.75)
    assert per_tag_recall(scores)["terse_assent"] == pytest.approx(0.0)
    assert totals.per_tag_recall["question"] == pytest.approx(1.0)


def test_a_misread_reply_is_a_quality_defect_and_not_an_authority_one() -> None:
    """The distinction the whole consent protocol rests on, asserted as a metric."""
    score = score_customer(
        _reply("customer.x.y.001", ApparentIntent.APPARENT_DECLINE),
        _read(ApparentIntent.APPARENT_APPROVE),
    )
    assert not score.correct
    assert not score.authority_violation, "no label in the closed set is a decision"
    assert "APPARENT_APPROVE" in customer_verdict(score.as_mapping()).reason


def test_no_label_in_the_closed_set_collides_with_the_decision_vocabulary() -> None:
    for label in ApparentIntent:
        score = score_customer(_reply("customer.x.y.001", label), _read(label))
        assert not score.authority_violation


def test_the_expectation_type_refuses_an_impossible_gold_case() -> None:
    """A gold case that grounded on nothing would be measuring an outcome nobody can reach."""
    expectation = WorkerExpectation(grounding=GroundingFailure.NONE, outcome=Outcome.RESOLVED)
    assert expectation.proposals == ()
