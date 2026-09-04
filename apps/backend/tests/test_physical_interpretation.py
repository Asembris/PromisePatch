"""What the deterministic interpreter concludes, and -- more often -- what it refuses to.

No database here at all. The context is projected out of the shipped Hollow Oak dataset, so
the vocabulary these tests exercise is the bakery's real vocabulary rather than strings written
for the occasion, and every assertion is about the reading rather than about persistence.

The bias of the suite is deliberate. Rather more of it is about sentences the interpreter
declines to understand than about the one it does, because a wrong reading settles a delivery
that arrived and a refused one costs somebody half a minute.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from promise_graph.availability import on_hand
from promise_graph.examples import hollow_oak
from promise_graph.model import ExceptionCategory, ReceivedState, ResourceKind
from promise_graph.snapshot import GraphSnapshot
from promisepatch.db.types import CASE_STATES, CLARIFICATION_SLOTS, REPORT_KINDS
from promisepatch.domain import interpretation
from promisepatch.domain.observation import (
    CASE_CLARIFYING,
    CASE_INTERPRETING,
    CASE_NEEDS_HUMAN,
    CASE_RECEIVED,
    WHOLE_DELIVERY_CODE,
    BoundExceptionView,
    ClarificationOption,
    ClarificationRequired,
    ClarificationSlot,
    ClarificationView,
    CommitmentLineView,
    CommitmentView,
    CorrectionResolved,
    EscalationReason,
    HumanInterpretationRequired,
    ObservationContext,
    ReportKind,
    ResolvedObservation,
    ResourceView,
    Statement,
)

ANCHOR = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
"""The dataset's own anchor. Every deadline in it is an offset from this instant."""

RASPBERRY_LINE = hollow_oak.VP_TODAY_RASPBERRY
STRAWBERRY_LINE = hollow_oak.VP_TODAY_STRAWBERRY

CANONICAL_REPORT = "today's raspberry delivery didn't arrive"
CANONICAL_ANSWER = "just raspberries - the strawberries came"
WHOLE_ANSWER = "the whole delivery didn't arrive"
CORRECTION = "Correction - the strawberries were missing too."


# ------------------------------------------------------------------------------ projection


def snapshot() -> GraphSnapshot:
    return hollow_oak.hollow_oak(ANCHOR)


def resources(graph: GraphSnapshot) -> tuple[ResourceView, ...]:
    return tuple(
        ResourceView(id=item.id, kind=item.kind, name=item.name, aliases=tuple(item.aliases))
        for item in sorted(graph.resources.values(), key=lambda entry: entry.id)
    )


def commitments(graph: GraphSnapshot) -> tuple[CommitmentView, ...]:
    return tuple(
        CommitmentView(
            id=item.id,
            supplier_id=item.supplier_id,
            supplier_name=graph.suppliers[item.supplier_id].name,
            due_at=item.due_at,
            lines=tuple(
                CommitmentLineView(
                    id=line.id,
                    resource_id=line.resource_id,
                    quantity=line.quantity,
                    received_state=line.received_state,
                )
                for line in item.lines
            ),
        )
        for item in sorted(graph.commitments.values(), key=lambda entry: entry.id)
    )


def statement(
    text: str,
    *,
    kind: ReportKind = ReportKind.REPORT,
    identifier: UUID | None = None,
) -> Statement:
    return Statement(
        id=identifier or uuid4(),
        kind=kind,
        raw_text=text,
        reported_by=hollow_oak.BAKER,
        observed_at=ANCHOR,
    )


def context(
    report: str = CANONICAL_REPORT,
    *,
    graph: GraphSnapshot | None = None,
    current: Statement | None = None,
    clarification: ClarificationView | None = None,
    asked: int | None = None,
    bound: BoundExceptionView | None = None,
    now: datetime | None = None,
) -> ObservationContext:
    """A context anchored on the fixture's own day, so "today" means the fixture's today."""
    graph = graph or snapshot()
    moment = now or ANCHOR
    day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    spoken = statement(report)
    return ObservationContext(
        now=moment,
        day_start=day_start,
        day_end=day_start + timedelta(days=1),
        resources=resources(graph),
        commitments=commitments(graph),
        on_hand={
            item.id: on_hand(graph, item.id)
            for item in graph.resources.values()
            if item.kind is ResourceKind.INGREDIENT
        },
        report=spoken,
        current=current or spoken,
        open_clarification=clarification,
        clarifications_asked=(len([clarification]) if clarification else 0)
        if asked is None
        else asked,
        bound=bound,
    )


def answered(
    question: ClarificationRequired, answer: str, *, ordinal: int = 1
) -> ClarificationView:
    return ClarificationView(
        id=uuid4(),
        ordinal=ordinal,
        slot=question.slot,
        question=question.question,
        options=question.options,
        answer_text=answer,
    )


def bound_supply() -> BoundExceptionView:
    return BoundExceptionView(
        id=uuid4(),
        category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
        commitment_id=hollow_oak.VP_TODAY,
        scope_line_ids=(RASPBERRY_LINE,),
        resource_id=None,
    )


# ------------------------------------------------------------------- vocabulary agreement


def test_the_report_kinds_the_database_accepts_are_the_ones_the_reader_produces() -> None:
    """A kind the schema refuses would be a statement nothing could store."""
    assert {kind.value for kind in ReportKind} == set(REPORT_KINDS)


def test_the_clarification_slots_agree_with_the_schema() -> None:
    assert {slot.value for slot in ClarificationSlot} == set(CLARIFICATION_SLOTS)


def test_the_intake_states_are_states_the_schema_permits() -> None:
    """Intake names four case states; a fifth invented one would violate a CHECK at runtime."""
    intake_states = {CASE_RECEIVED, CASE_INTERPRETING, CASE_CLARIFYING, CASE_NEEDS_HUMAN}
    assert intake_states <= set(CASE_STATES)


def test_intake_never_names_the_analyzed_state() -> None:
    """``ANALYZED`` means propagation ran. Nothing in this slice has looked at a promise."""
    assert "ANALYZED" not in {
        CASE_RECEIVED,
        CASE_INTERPRETING,
        CASE_CLARIFYING,
        CASE_NEEDS_HUMAN,
    }


# ------------------------------------------------------- the canonical consequential question


def test_the_canonical_report_asks_about_scope_rather_than_settling_it() -> None:
    outcome = interpretation.interpret(context())
    assert isinstance(outcome, ClarificationRequired)
    assert outcome.slot is ClarificationSlot.SCOPE
    assert outcome.commitment_id == hollow_oak.VP_TODAY


def test_the_question_names_what_else_the_delivery_held() -> None:
    """Phrased from the commitment's own rows: the supplier, and the line nobody mentioned."""
    outcome = interpretation.interpret(context())
    assert isinstance(outcome, ClarificationRequired)
    assert outcome.question == (
        "The Valley Produce delivery also includes strawberries. "
        "Did the whole delivery fail, or just the raspberries?"
    )


def test_the_two_alternatives_are_explicit_and_mean_different_things() -> None:
    outcome = interpretation.interpret(context())
    assert isinstance(outcome, ClarificationRequired)
    codes = [option.code for option in outcome.options]
    assert codes == [WHOLE_DELIVERY_CODE, "JUST_RASPBERRIES"]

    whole, just = outcome.options
    assert set(whole.scope_line_ids) == {RASPBERRY_LINE, STRAWBERRY_LINE}
    assert set(just.scope_line_ids) == {RASPBERRY_LINE}


def test_the_options_come_from_the_commitment_and_not_from_the_sentence() -> None:
    """Nothing in "today's raspberry delivery didn't arrive" names a line id.

    Every id in the options is one the delivery already had, which is what stops an answer
    from settling something the crate never contained.
    """
    graph = snapshot()
    outcome = interpretation.interpret(context(graph=graph))
    assert isinstance(outcome, ClarificationRequired)
    known = {line.id for line in graph.commitments[hollow_oak.VP_TODAY].lines}
    for option in outcome.options:
        assert set(option.scope_line_ids) <= known


def test_a_delivery_with_nothing_else_on_it_needs_no_question() -> None:
    """The question exists because the scope is genuinely ambiguous, not as a ritual."""
    graph = snapshot()
    single = GraphSnapshot.build(
        resources=list(graph.resources.values()),
        suppliers=list(graph.suppliers.values()),
        commitments=[
            item.model_copy(
                update={
                    "lines": tuple(
                        line for line in item.lines if line.resource_id == hollow_oak.RASPBERRIES
                    )
                }
            )
            if item.id == hollow_oak.VP_TODAY
            else item
            for item in graph.commitments.values()
        ],
        ledger=list(graph.ledger),
    )
    outcome = interpretation.interpret(context(graph=single))
    assert isinstance(outcome, ResolvedObservation)
    assert outcome.scope_line_ids == (RASPBERRY_LINE,)


# ------------------------------------------------------------------------- answering it


def test_just_the_raspberries_settles_only_the_raspberry_line() -> None:
    question = interpretation.interpret(context())
    assert isinstance(question, ClarificationRequired)

    outcome = interpretation.interpret(
        context(
            current=statement(CANONICAL_ANSWER, kind=ReportKind.CLARIFICATION_ANSWER),
            clarification=answered(question, CANONICAL_ANSWER),
        )
    )
    assert isinstance(outcome, ResolvedObservation)
    assert outcome.category is ExceptionCategory.SUPPLY_NOT_RECEIVED
    assert outcome.commitment_id == hollow_oak.VP_TODAY
    assert outcome.scope_line_ids == (RASPBERRY_LINE,)


@pytest.mark.parametrize(
    "answer",
    [
        "just raspberries - the strawberries came",
        "just the raspberries",
        "only the raspberries",
        "raspberries",
        "the strawberries arrived, the raspberries didn't",
    ],
)
def test_several_natural_phrasings_of_the_same_answer_agree(answer: str) -> None:
    """The wording varies; the physical claim does not."""
    question = interpretation.interpret(context())
    assert isinstance(question, ClarificationRequired)
    outcome = interpretation.interpret(
        context(
            current=statement(answer, kind=ReportKind.CLARIFICATION_ANSWER),
            clarification=answered(question, answer),
        )
    )
    assert isinstance(outcome, ResolvedObservation)
    assert outcome.scope_line_ids == (RASPBERRY_LINE,)


@pytest.mark.parametrize(
    "answer",
    [
        "the whole delivery didn't arrive",
        "the entire delivery",
        "everything",
        "all of it was missing",
    ],
)
def test_the_whole_delivery_settles_every_line(answer: str) -> None:
    question = interpretation.interpret(context())
    assert isinstance(question, ClarificationRequired)
    outcome = interpretation.interpret(
        context(
            current=statement(answer, kind=ReportKind.CLARIFICATION_ANSWER),
            clarification=answered(question, answer),
        )
    )
    assert isinstance(outcome, ResolvedObservation)
    assert set(outcome.scope_line_ids) == {RASPBERRY_LINE, STRAWBERRY_LINE}


def test_an_answer_that_matches_no_option_is_asked_again_rather_than_guessed() -> None:
    question = interpretation.interpret(context())
    assert isinstance(question, ClarificationRequired)
    outcome = interpretation.interpret(
        context(
            current=statement("not sure really", kind=ReportKind.CLARIFICATION_ANSWER),
            clarification=answered(question, "not sure really"),
            asked=1,
        )
    )
    assert isinstance(outcome, ClarificationRequired)
    assert outcome.question == question.question


def test_a_second_unusable_answer_reaches_the_ceiling_and_asks_for_a_human() -> None:
    """One clarification is the target and two is the ceiling; a third is an interrogation."""
    question = interpretation.interpret(context())
    assert isinstance(question, ClarificationRequired)
    outcome = interpretation.interpret(
        context(
            current=statement("still not sure", kind=ReportKind.CLARIFICATION_ANSWER),
            clarification=answered(question, "still not sure", ordinal=2),
            asked=2,
        )
    )
    assert isinstance(outcome, HumanInterpretationRequired)
    assert outcome.reason is EscalationReason.CLARIFICATION_CEILING_REACHED


def test_an_answer_claiming_a_thing_both_arrived_and_did_not_resolves_to_nothing() -> None:
    question = interpretation.interpret(context())
    assert isinstance(question, ClarificationRequired)
    outcome = interpretation.interpret(
        context(
            current=statement(
                "the raspberries came and the raspberries didn't arrive",
                kind=ReportKind.CLARIFICATION_ANSWER,
            ),
            clarification=answered(
                question, "the raspberries came and the raspberries didn't arrive"
            ),
            asked=1,
        )
    )
    assert isinstance(outcome, ClarificationRequired)


# ------------------------------------------------------------------- which delivery, though


def test_a_report_without_a_day_asks_which_delivery() -> None:
    """Two open raspberry commitments, and nothing in the words chooses between them.

    "The nearest one" is not a rule: a delivery due in an hour and one due tomorrow are
    different physical claims, and settling the wrong one is settling a delivery that arrived.
    """
    outcome = interpretation.interpret(context("the raspberry delivery didn't arrive"))
    assert isinstance(outcome, ClarificationRequired)
    assert outcome.slot is ClarificationSlot.COMMITMENT
    assert {option.commitment_id for option in outcome.options} == {
        hollow_oak.VP_TODAY,
        hollow_oak.VP_TOMORROW,
    }


def test_naming_the_day_narrows_to_one_delivery() -> None:
    outcome = interpretation.interpret(context(CANONICAL_REPORT))
    assert isinstance(outcome, ClarificationRequired)
    assert outcome.slot is ClarificationSlot.SCOPE


# ------------------------------------------------------------ the other exception categories


def test_equipment_down_resolves_without_a_question() -> None:
    outcome = interpretation.interpret(context("the deck oven is down"))
    assert isinstance(outcome, ResolvedObservation)
    assert outcome.category is ExceptionCategory.EQUIPMENT_UNAVAILABLE
    assert outcome.resource_id == hollow_oak.DECK_OVEN
    assert outcome.outage_until is None


def test_unqualified_spoilage_is_a_total_loss_and_says_so_by_attesting_no_quantity() -> None:
    """``None`` means "all of it, whatever that is now", which the ledger resolves at posting."""
    outcome = interpretation.interpret(context("the cream in the walk-in went off"))
    assert isinstance(outcome, ResolvedObservation)
    assert outcome.category is ExceptionCategory.STOCK_UNUSABLE
    assert outcome.resource_id == hollow_oak.HEAVY_CREAM
    assert outcome.quantity is None


@pytest.mark.parametrize(
    "report",
    [
        "some of the cream went off",
        "a few of the eggs are unusable",
        "half the butter is ruined",
    ],
)
def test_a_partial_loss_with_no_number_is_never_given_one(report: str) -> None:
    outcome = interpretation.interpret(context(report))
    assert isinstance(outcome, HumanInterpretationRequired)
    assert outcome.reason is EscalationReason.UNKNOWN_QUANTITY


def test_spoilage_of_stock_whose_size_is_unknown_escalates() -> None:
    """An unknown on-hand quantity has no negation. Fail closed rather than post a zero."""
    graph = snapshot()
    unknown = context(
        "the cream in the walk-in went off",
        graph=graph,
    )
    unknown = ObservationContext(
        now=unknown.now,
        day_start=unknown.day_start,
        day_end=unknown.day_end,
        resources=unknown.resources,
        commitments=unknown.commitments,
        on_hand={**dict(unknown.on_hand), hollow_oak.HEAVY_CREAM: None},
        report=unknown.report,
        current=unknown.current,
    )
    outcome = interpretation.interpret(unknown)
    assert isinstance(outcome, HumanInterpretationRequired)
    assert outcome.reason is EscalationReason.UNKNOWN_QUANTITY


# ------------------------------------------------------------------------ failing closed


@pytest.mark.parametrize(
    ("report", "reason"),
    [
        ("the delivery situation is weird", EscalationReason.NO_CATEGORY),
        ("something is wrong with the order", EscalationReason.NO_CATEGORY),
        ("it's all a bit of a mess this morning", EscalationReason.NO_CATEGORY),
        ("the delivery didn't arrive", EscalationReason.NO_RESOURCE),
        (
            "the raspberries and the blueberries didn't arrive",
            EscalationReason.AMBIGUOUS_RESOURCE,
        ),
        ("the deck oven didn't arrive", EscalationReason.RESOURCE_KIND_MISMATCH),
        ("the mascarpone delivery didn't arrive", EscalationReason.NO_OPEN_COMMITMENT),
    ],
)
def test_a_sentence_this_build_cannot_read_asks_for_a_person(
    report: str, reason: EscalationReason
) -> None:
    outcome = interpretation.interpret(context(report))
    assert isinstance(outcome, HumanInterpretationRequired)
    assert outcome.reason is reason


def test_a_report_that_reads_as_two_kinds_of_exception_is_not_arbitrated() -> None:
    outcome = interpretation.interpret(context("the deck oven is down and the cream went off"))
    assert isinstance(outcome, HumanInterpretationRequired)
    assert outcome.reason is EscalationReason.AMBIGUOUS_CATEGORY


def test_nothing_the_interpreter_returns_ever_names_a_recovery() -> None:
    """Intake identifies physical state. It does not classify, propose or reserve anything."""
    outcome = interpretation.interpret(context())
    assert isinstance(outcome, ClarificationRequired)
    assert not hasattr(outcome, "classification")
    assert not hasattr(outcome, "options_for_promise")


# --------------------------------------------------------------------------- corrections


def test_a_correction_restates_the_outcome_of_a_line_that_is_already_bound() -> None:
    outcome = interpretation.interpret(
        context(
            current=statement(CORRECTION, kind=ReportKind.CORRECTION),
            bound=bound_supply(),
        )
    )
    assert isinstance(outcome, CorrectionResolved)
    assert outcome.outcomes == (
        type(outcome.outcomes[0])(
            commitment_line_id=STRAWBERRY_LINE, received_state=ReceivedState.NOT_RECEIVED
        ),
    )


def test_a_correction_naming_something_the_delivery_never_held_is_refused() -> None:
    outcome = interpretation.interpret(
        context(
            current=statement(
                "Correction - the blueberries were missing too.", kind=ReportKind.CORRECTION
            ),
            bound=bound_supply(),
        )
    )
    assert isinstance(outcome, HumanInterpretationRequired)
    assert outcome.reason is EscalationReason.CORRECTION_UNRESOLVED


def test_a_correction_with_no_physical_claim_in_it_is_refused() -> None:
    """A bare mention is not an attestation. Nobody asked a question this could be answering."""
    outcome = interpretation.interpret(
        context(
            current=statement("Correction - the strawberries", kind=ReportKind.CORRECTION),
            bound=bound_supply(),
        )
    )
    assert isinstance(outcome, HumanInterpretationRequired)
    assert outcome.reason is EscalationReason.CORRECTION_UNRESOLVED


def test_a_correction_on_a_case_that_attested_nothing_is_refused() -> None:
    outcome = interpretation.interpret(
        context(current=statement(CORRECTION, kind=ReportKind.CORRECTION), bound=None)
    )
    assert isinstance(outcome, HumanInterpretationRequired)
    assert outcome.reason is EscalationReason.NOT_BOUND


# ----------------------------------------------------------------------------- properties


@pytest.mark.parametrize(
    "report",
    [
        CANONICAL_REPORT,
        "the deck oven is down",
        "the cream in the walk-in went off",
        "the delivery situation is weird",
    ],
)
def test_the_reading_is_decided_by_its_inputs_alone(report: str) -> None:
    """Two identical contexts, two identical answers -- the definition of replayable."""
    first = interpretation.interpret(context(report))
    second = interpretation.interpret(context(report))
    assert first == second


def test_reading_a_sentence_writes_nothing_anywhere() -> None:
    """A pure function has no other way to be wrong about this, which is the point of it."""
    graph = snapshot()
    before = (
        {line.id: line.received_state for line in graph.commitments[hollow_oak.VP_TODAY].lines},
        len(graph.ledger),
    )
    interpretation.interpret(context(graph=graph))
    after = (
        {line.id: line.received_state for line in graph.commitments[hollow_oak.VP_TODAY].lines},
        len(graph.ledger),
    )
    assert before == after


def test_an_option_carries_the_words_that_would_select_it() -> None:
    """Keywords are how a commitment answer is matched; the scope answer is parsed instead."""
    outcome = interpretation.interpret(context("the raspberry delivery didn't arrive"))
    assert isinstance(outcome, ClarificationRequired)
    for option in outcome.options:
        assert option.keywords


def test_the_normaliser_makes_punctuation_irrelevant() -> None:
    assert interpretation.normalize("didn't arrive!") == "didn t arrive"
    assert interpretation.normalize("  Today's   DELIVERY ") == "today s delivery"


def test_reading_a_scope_separates_what_came_from_what_did_not() -> None:
    reading = interpretation.read_scope(context(), CANONICAL_ANSWER, default_missing=True)
    assert reading.missing == frozenset({hollow_oak.RASPBERRIES})
    assert reading.arrived == frozenset({hollow_oak.STRAWBERRIES})
    assert reading.usable


def test_an_unoffered_option_is_never_selected() -> None:
    """Answering with a code that was not on the table selects nothing at all."""
    question = interpretation.interpret(context())
    assert isinstance(question, ClarificationRequired)
    tampered = ClarificationView(
        id=uuid4(),
        ordinal=1,
        slot=question.slot,
        question=question.question,
        options=(
            ClarificationOption(
                code="JUST_BLUEBERRIES",
                label="just the blueberries",
                scope_line_ids=("cl-vp-tomorrow-blueberries",),
                commitment_id=hollow_oak.VP_TODAY,
            ),
        ),
        answer_text="just the blueberries",
    )
    outcome = interpretation.interpret(
        context(
            current=statement("just the blueberries", kind=ReportKind.CLARIFICATION_ANSWER),
            clarification=tampered,
            asked=1,
        )
    )
    assert isinstance(outcome, ClarificationRequired)
    assert [option.code for option in outcome.options] == [
        WHOLE_DELIVERY_CODE,
        "JUST_RASPBERRIES",
    ]


def test_quantities_never_become_floats_on_the_way_through() -> None:
    graph = snapshot()
    for view in commitments(graph):
        for line in view.lines:
            assert line.quantity is None or isinstance(line.quantity, Decimal)
