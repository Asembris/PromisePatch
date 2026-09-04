"""Physical exception intake against a real database: what is written, and what is not.

The shape of these tests follows the shape of the guarantee. A worker says something, the
words become a row, a worker process reads them under a lease, and *only then* does anything
physical change -- once, atomically, with the person who saw it named on the record.

The assertions that matter most are negative ones. Before the clarification is answered there
must be no fact, no settled line and no posted stock, because the system genuinely does not
know yet; after a correction the original fact and the original ledger row must still be
there, because they are the record of what somebody said at the time.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from _intake_support import (
    BAKER,
    CANONICAL_REPORT,
    CORRECTION,
    OWNER,
    RASPBERRIES,
    RASPBERRY_LINE,
    RASPBERRY_ONLY,
    STRAWBERRIES,
    STRAWBERRY_LINE,
    UNREADABLE,
    WHOLE_DELIVERY,
    Intake,
)
from _intake_support import physical as physical

from promise_graph.model import ExceptionCategory
from promisepatch.db.uow import Actor
from promisepatch.domain import intake
from promisepatch.domain.model import StepResult
from promisepatch.domain.observation import (
    AUDIT_CASE_OPENED,
    AUDIT_CLARIFICATION_ANSWERED,
    AUDIT_CLARIFICATION_REQUESTED,
    AUDIT_NEEDS_HUMAN_INTERPRETATION,
    AUDIT_PHYSICAL_FACT_CORRECTED,
    AUDIT_PHYSICAL_FACT_RECORDED,
    CASE_CLARIFYING,
    CASE_INTERPRETING,
    CASE_NEEDS_HUMAN,
    CASE_RECEIVED,
    EVENT_CASE_OPENED,
    EVENT_CLARIFICATION_ANSWERED,
    EVENT_CLARIFICATION_REQUIRED,
    EVENT_FACT_CORRECTED,
    EVENT_FACT_RECORDED,
    EVENT_NEEDS_HUMAN,
    EVENT_READY_FOR_ANALYSIS,
    RULE_PHYSICAL_FACT_ATTESTED,
    WHOLE_DELIVERY_CODE,
)

pytestmark = pytest.mark.integration

SIX_KILOS = Decimal("6.000")


# ------------------------------------------------------------------- opening a case (§22)


async def test_a_report_opens_a_case_that_has_concluded_nothing(physical: Intake) -> None:
    opened = await physical.report()
    case = await physical.case(opened.case_id)

    assert case.state == CASE_RECEIVED
    assert case.opened_by == BAKER
    assert case.exception_id is None


async def test_the_words_are_stored_before_anything_is_read_into_them(
    physical: Intake,
) -> None:
    opened = await physical.report()
    (stored,) = await physical.reports(opened.case_id)

    assert stored.raw_text == CANONICAL_REPORT
    assert stored.kind == "REPORT"
    assert stored.reported_by == BAKER
    assert await physical.facts(opened.case_id) == []


async def test_opening_a_case_creates_exactly_one_piece_of_durable_work(
    physical: Intake,
) -> None:
    opened = await physical.report()
    outstanding = await physical.outstanding(opened.case_id)

    assert [step.kind for step in outstanding] == ["BEGIN_INTERPRETATION"]
    assert outstanding[0].state == "PENDING"


async def test_the_same_command_delivered_twice_is_one_case_and_one_step(
    physical: Intake,
) -> None:
    """The retry that opens "a second case" is not a thing that can happen."""
    command = uuid4()
    first = await physical.report(command_id=command)
    second = await physical.report(command_id=command)

    assert second.case_id == first.case_id
    assert second.created is False
    assert len(await physical.reports(first.case_id)) == 1
    assert len(await physical.steps(first.case_id)) == 1


async def test_the_same_command_carrying_different_words_is_refused(
    physical: Intake,
) -> None:
    """Two different statements claiming one identity; choosing either would discard the other."""
    command = uuid4()
    await physical.report(command_id=command)

    with pytest.raises(intake.IntakeConflictError):
        await physical.report("the deck oven is down", command_id=command)


async def test_a_statement_needs_an_attestor_who_exists(physical: Intake) -> None:
    with pytest.raises(intake.UnknownWorkerError):
        await physical.report(worker_id="nobody")


async def test_the_worker_moves_the_case_into_interpreting(physical: Intake) -> None:
    opened = await physical.report()
    worker = physical.worker()

    await worker.run_once()
    case = await physical.case(opened.case_id)

    assert case.state == CASE_INTERPRETING
    assert case.version > 1


async def test_opening_a_case_goes_through_the_audited_boundary(physical: Intake) -> None:
    opened = await physical.report()
    audits = await physical.audits(opened.case_id)

    assert [row.type for row in audits] == [AUDIT_CASE_OPENED]
    assert audits[0].actor_kind == "WORKER"
    assert audits[0].actor_id == BAKER
    assert audits[0].authority == "NONE"


async def test_a_case_opened_but_never_worked_leaves_its_work_recoverable(
    physical: Intake,
) -> None:
    """Nothing was held in the process that opened it: the outstanding work is a row."""
    opened = await physical.report()
    outstanding = await physical.outstanding(opened.case_id)
    assert outstanding

    await physical.drain(worker=physical.worker(identity="a-quite-different-process"))
    case = await physical.case(opened.case_id)
    assert case.state == CASE_CLARIFYING


# ------------------------------------------------------- the consequential question (§23)


async def test_the_canonical_report_reaches_clarifying(physical: Intake) -> None:
    opened = await physical.report()
    await physical.drain()

    case = await physical.case(opened.case_id)
    assert case.state == CASE_CLARIFYING


async def test_the_question_distinguishes_the_whole_delivery_from_the_raspberries(
    physical: Intake,
) -> None:
    opened = await physical.report()
    await physical.drain()
    (question,) = await physical.clarifications(opened.case_id)

    assert question.slot == "SCOPE"
    assert question.question == (
        "The Valley Produce delivery also includes strawberries. "
        "Did the whole delivery fail, or just the raspberries?"
    )
    codes = [option["code"] for option in question.options]
    assert codes == [WHOLE_DELIVERY_CODE, "JUST_RASPBERRIES"]


async def test_the_options_name_lines_this_delivery_actually_has(physical: Intake) -> None:
    opened = await physical.report()
    await physical.drain()
    (question,) = await physical.clarifications(opened.case_id)

    by_code = {option["code"]: option for option in question.options}
    assert set(by_code[WHOLE_DELIVERY_CODE]["scope_line_ids"]) == {
        RASPBERRY_LINE,
        STRAWBERRY_LINE,
    }
    assert by_code["JUST_RASPBERRIES"]["scope_line_ids"] == [RASPBERRY_LINE]


async def test_nothing_physical_moves_while_the_question_is_open(physical: Intake) -> None:
    """The whole point of asking. Guessing either way would settle a line nobody attested."""
    opened = await physical.report()
    await physical.drain()

    assert await physical.facts(opened.case_id) == []
    assert (await physical.line(RASPBERRY_LINE)).received_state == "EXPECTED"
    assert (await physical.line(STRAWBERRY_LINE)).received_state == "EXPECTED"
    assert await physical.postings(STRAWBERRIES) == []
    assert await physical.postings(RASPBERRIES) == []
    assert (await physical.case(opened.case_id)).exception_id is None


async def test_asking_the_question_is_audited_and_announced(physical: Intake) -> None:
    opened = await physical.report()
    await physical.drain()

    assert AUDIT_CLARIFICATION_REQUESTED in {
        row.type for row in await physical.audits(opened.case_id)
    }
    assert EVENT_CLARIFICATION_REQUIRED in await physical.events(opened.case_id)


async def test_the_question_keeps_the_words_that_produced_it(physical: Intake) -> None:
    opened = await physical.report()
    await physical.drain()
    (question,) = await physical.clarifications(opened.case_id)

    assert question.context["category"] == ExceptionCategory.SUPPLY_NOT_RECEIVED.value
    assert question.context["commitment_id"] == "com-vp-today"
    assert (await physical.reports(opened.case_id))[0].raw_text == CANONICAL_REPORT


# --------------------------------------------------------- just the raspberries (§24)


async def test_the_raspberry_answer_settles_both_lines_the_way_the_worker_described(
    physical: Intake,
) -> None:
    await physical.resolved_case()

    assert (await physical.line(RASPBERRY_LINE)).received_state == "NOT_RECEIVED"
    assert (await physical.line(STRAWBERRY_LINE)).received_state == "RECEIVED"


async def test_the_strawberries_are_posted_on_hand_exactly_once(physical: Intake) -> None:
    before = await physical.on_hand(STRAWBERRIES)
    await physical.resolved_case()
    postings = await physical.postings(STRAWBERRIES)

    assert [posting.delta for posting in postings] == [SIX_KILOS]
    assert postings[0].source_kind == "COMMITMENT_RECEIPT"
    assert postings[0].source_id == STRAWBERRY_LINE
    assert await physical.on_hand(STRAWBERRIES) == before + SIX_KILOS


async def test_a_settled_line_stops_being_expected_supply(physical: Intake) -> None:
    """Received stock lives in on-hand and is never counted a second time as still coming."""
    await physical.resolved_case()
    line = await physical.line(STRAWBERRY_LINE)

    assert line.received_state == "RECEIVED"
    assert line.settled_at is not None
    assert line.received_qty is None


async def test_the_raspberries_that_never_came_post_nothing(physical: Intake) -> None:
    await physical.resolved_case()

    assert await physical.postings(RASPBERRIES) == []
    assert (await physical.line(RASPBERRY_LINE)).received_state == "NOT_RECEIVED"


async def test_both_facts_name_the_worker_who_saw_them(physical: Intake) -> None:
    case_id = await physical.resolved_case()
    facts = await physical.facts(case_id)

    assert {fact.target_id for fact in facts} == {RASPBERRY_LINE, STRAWBERRY_LINE}
    assert {fact.attested_by for fact in facts} == {BAKER}
    assert all(fact.source_report_id is not None for fact in facts)
    assert all(fact.supersedes_fact_id is None for fact in facts)


async def test_a_fact_records_what_it_changed(physical: Intake) -> None:
    case_id = await physical.resolved_case()
    facts = {fact.target_id: fact for fact in await physical.facts(case_id)}

    assert facts[STRAWBERRY_LINE].before == {"received_state": "EXPECTED"}
    assert facts[STRAWBERRY_LINE].after["received_state"] == "RECEIVED"
    assert facts[STRAWBERRY_LINE].posted_ledger_ids
    assert facts[RASPBERRY_LINE].posted_ledger_ids == []


async def test_the_exception_is_bound_to_the_delivery_and_the_scope(physical: Intake) -> None:
    case_id = await physical.resolved_case()
    exception = await physical.exception(case_id)

    assert exception.category == ExceptionCategory.SUPPLY_NOT_RECEIVED.value
    assert exception.commitment_id == "com-vp-today"
    assert exception.scope_line_ids == [RASPBERRY_LINE]
    assert exception.raw_utterance == CANONICAL_REPORT
    assert exception.reported_by == BAKER


async def test_the_interpretation_step_finishes(physical: Intake) -> None:
    case_id = await physical.resolved_case()
    steps = await physical.steps(case_id)

    assert {step.state for step in steps} == {"DONE"}
    resolve = [step for step in steps if step.kind == "RESOLVE_OBSERVATION"][-1]
    assert resolve.result["outcome"] == "RESOLVED"
    assert resolve.result["ready_for_analysis"] is True


async def test_the_case_is_ready_for_analysis_without_claiming_to_be_analysed(
    physical: Intake,
) -> None:
    """``ANALYZED`` means every promise has a classification. None has been looked at.

    Driven to the end of intake and no further: a resolved intake enqueues analysis, and this
    is an assertion about the boundary between the two rather than about the whole workflow.
    """
    case_id = await physical.attested_case()
    case = await physical.case(case_id)

    assert case.state == CASE_INTERPRETING
    assert case.state != "ANALYZED"
    assert EVENT_READY_FOR_ANALYSIS in await physical.events(case_id)


async def test_recording_the_facts_is_audited_under_the_attesting_worker(
    physical: Intake,
) -> None:
    """Two authorities, two rows: the person who saw it, and the process that executed it."""
    case_id = await physical.resolved_case()
    audits = await physical.audits(case_id)
    recorded = [row for row in audits if row.type == AUDIT_PHYSICAL_FACT_RECORDED]

    assert len(recorded) == 1
    assert recorded[0].actor_kind == "WORKER"
    assert recorded[0].actor_id == BAKER
    assert recorded[0].authority == "NONE"
    assert recorded[0].rule_id == RULE_PHYSICAL_FACT_ATTESTED
    assert recorded[0].provenance["raw_utterance"] == CANONICAL_REPORT
    assert recorded[0].provenance["clarified"] is True

    executed = [row for row in audits if row.type == "WORKFLOW_STEP_EXECUTED"]
    assert executed
    assert {row.actor_kind for row in executed} == {"SYSTEM"}


async def test_the_whole_intake_appears_on_the_spine_in_order(physical: Intake) -> None:
    case_id = await physical.resolved_case()
    events = await physical.events(case_id)

    assert events[0] == EVENT_CASE_OPENED
    assert events.index(EVENT_CLARIFICATION_REQUIRED) < events.index(EVENT_CLARIFICATION_ANSWERED)
    assert events.index(EVENT_CLARIFICATION_ANSWERED) < events.index(EVENT_FACT_RECORDED)
    assert events.index(EVENT_FACT_RECORDED) < events.index(EVENT_READY_FOR_ANALYSIS)


async def test_answering_is_idempotent_under_a_redelivered_command(physical: Intake) -> None:
    opened = await physical.report()
    await physical.drain()

    command = uuid4()
    await physical.answer(opened.case_id, RASPBERRY_ONLY, command_id=command)
    again = await physical.answer(opened.case_id, RASPBERRY_ONLY, command_id=command)

    assert again.created is False
    assert len(await physical.reports(opened.case_id)) == 2

    await physical.drain()
    assert [posting.delta for posting in await physical.postings(STRAWBERRIES)] == [SIX_KILOS]


async def test_replaying_the_worker_after_resolution_posts_nothing_further(
    physical: Intake,
) -> None:
    """Every step is settled, so another sweep has nothing to claim and nothing to repeat."""
    case_id = await physical.resolved_case()
    facts_before = len(await physical.facts(case_id))

    await physical.drain()
    await physical.drain()

    assert len(await physical.facts(case_id)) == facts_before
    assert [posting.delta for posting in await physical.postings(STRAWBERRIES)] == [SIX_KILOS]


async def test_intake_proposes_no_recovery_of_any_kind(physical: Intake) -> None:
    """Nothing here classifies a promise, names a recipe version or reserves substitute stock."""
    case_id = await physical.attested_case()
    events = await physical.events(case_id)

    assert not any("track" in event or "option" in event for event in events)
    assert not any("approval" in event or "recovery" in event for event in events)


# --------------------------------------------------------------- the whole delivery (§25)


async def test_the_whole_delivery_answer_settles_every_line_as_missing(
    physical: Intake,
) -> None:
    opened = await physical.report()
    await physical.drain()
    await physical.answer(opened.case_id, WHOLE_DELIVERY)
    await physical.drain()

    assert (await physical.line(RASPBERRY_LINE)).received_state == "NOT_RECEIVED"
    assert (await physical.line(STRAWBERRY_LINE)).received_state == "NOT_RECEIVED"


async def test_the_whole_delivery_answer_posts_no_strawberries(physical: Intake) -> None:
    """The reason the question is consequential: this is a different amount of stock."""
    before = await physical.on_hand(STRAWBERRIES)
    opened = await physical.report()
    await physical.drain()
    await physical.answer(opened.case_id, WHOLE_DELIVERY)
    await physical.drain()

    assert await physical.postings(STRAWBERRIES) == []
    assert await physical.on_hand(STRAWBERRIES) == before


async def test_the_two_answers_leave_genuinely_different_physical_state(
    physical: Intake,
) -> None:
    opened = await physical.report()
    await physical.drain()
    await physical.answer(opened.case_id, WHOLE_DELIVERY)
    await physical.drain()
    whole = (
        (await physical.line(STRAWBERRY_LINE)).received_state,
        await physical.on_hand(STRAWBERRIES),
    )

    assert whole[0] == "NOT_RECEIVED"
    facts = {
        fact.target_id: fact.after["received_state"]
        for fact in await physical.facts(opened.case_id)
    }
    assert facts == {RASPBERRY_LINE: "NOT_RECEIVED", STRAWBERRY_LINE: "NOT_RECEIVED"}


async def test_no_classification_is_produced_by_either_answer(physical: Intake) -> None:
    opened = await physical.report()
    await physical.drain_intake(opened.case_id)
    await physical.answer(opened.case_id, WHOLE_DELIVERY)
    await physical.drain_intake(opened.case_id)
    case = await physical.case(opened.case_id)

    assert case.state == CASE_INTERPRETING
    assert case.needs_owner_attention is False


# ---------------------------------------------------------------------- corrections (§26)


async def test_a_correction_leaves_the_original_attestation_exactly_where_it_was(
    physical: Intake,
) -> None:
    case_id = await physical.resolved_case()
    original = {fact.id: fact.after for fact in await physical.facts(case_id)}

    await physical.correct(case_id)
    await physical.drain()

    after = {fact.id: fact.after for fact in await physical.facts(case_id)}
    for identifier, value in original.items():
        assert after[identifier] == value


async def test_a_correction_is_a_new_fact_that_cites_the_one_it_supersedes(
    physical: Intake,
) -> None:
    case_id = await physical.resolved_case()
    before = {fact.id for fact in await physical.facts(case_id)}

    await physical.correct(case_id)
    await physical.drain()

    facts = await physical.facts(case_id)
    fresh = [fact for fact in facts if fact.id not in before]
    assert len(fresh) == 1
    assert fresh[0].target_id == STRAWBERRY_LINE
    assert fresh[0].after["received_state"] == "NOT_RECEIVED"
    assert fresh[0].supersedes_fact_id in before


async def test_the_original_ledger_row_survives_and_a_compensating_one_is_appended(
    physical: Intake,
) -> None:
    case_id = await physical.resolved_case()
    await physical.correct(case_id)
    await physical.drain()

    postings = await physical.postings(STRAWBERRIES)
    assert [(item.source_kind, item.delta) for item in postings] == [
        ("COMMITMENT_RECEIPT", SIX_KILOS),
        ("CORRECTION", -SIX_KILOS),
    ]


async def test_the_net_physical_effect_of_a_corrected_delivery_is_nothing(
    physical: Intake,
) -> None:
    before = await physical.on_hand(STRAWBERRIES)
    case_id = await physical.resolved_case()
    await physical.correct(case_id)
    await physical.drain()

    assert await physical.on_hand(STRAWBERRIES) == before


async def test_the_line_reflects_the_latest_physical_truth(physical: Intake) -> None:
    case_id = await physical.resolved_case()
    await physical.correct(case_id)
    await physical.drain()

    assert (await physical.line(STRAWBERRY_LINE)).received_state == "NOT_RECEIVED"


async def test_a_redelivered_correction_cannot_compensate_twice(physical: Intake) -> None:
    case_id = await physical.resolved_case()
    command = uuid4()

    await physical.correct(case_id, command_id=command)
    await physical.drain()
    await physical.correct(case_id, command_id=command)
    await physical.drain()

    assert len(await physical.postings(STRAWBERRIES)) == 2


async def test_a_second_distinct_correction_saying_the_same_thing_changes_nothing(
    physical: Intake,
) -> None:
    """Compensation is driven by the difference from current truth, not by the sentence."""
    case_id = await physical.resolved_case()
    await physical.correct(case_id)
    await physical.drain()
    await physical.correct(case_id, command_id=uuid4())
    await physical.drain()

    assert len(await physical.postings(STRAWBERRIES)) == 2
    assert await physical.on_hand(STRAWBERRIES) == Decimal("2.000")


async def test_both_operations_are_in_the_audit_and_domain_history(physical: Intake) -> None:
    case_id = await physical.resolved_case()
    await physical.correct(case_id)
    await physical.drain()

    types = {row.type for row in await physical.audits(case_id)}
    assert {AUDIT_PHYSICAL_FACT_RECORDED, AUDIT_PHYSICAL_FACT_CORRECTED} <= types

    events = await physical.events(case_id)
    assert events.index(EVENT_FACT_RECORDED) < events.index(EVENT_FACT_CORRECTED)


async def test_a_correction_is_audited_under_the_worker_who_made_it(physical: Intake) -> None:
    case_id = await physical.resolved_case()
    await physical.correct(case_id)
    await physical.drain()

    corrected = [
        row for row in await physical.audits(case_id) if row.type == AUDIT_PHYSICAL_FACT_CORRECTED
    ]
    assert len(corrected) == 1
    assert corrected[0].actor_kind == "WORKER"
    assert corrected[0].actor_id == BAKER
    assert corrected[0].provenance["raw_utterance"] == CORRECTION


async def test_a_stored_fact_cannot_be_edited_even_inside_an_authorised_transaction(
    physical: Intake,
) -> None:
    """Immutability is not something an authorisation can buy.

    Two layers refuse this and either is enough: the runtime role holds no ``UPDATE`` on an
    append-only ledger, and the ``trg_00_append_only`` trigger refuses the statement regardless
    of who issues it. The privilege is what bites first, which is the right order -- the trigger
    is there for the day somebody grants a privilege they should not have.
    """
    from sqlalchemy import update

    from promisepatch.db.models import ExceptionFact
    from promisepatch.db.uow import UnitOfWork

    case_id = await physical.resolved_case()
    fact = (await physical.facts(case_id))[0]

    with pytest.raises(Exception, match=r"permission denied|immutable|append-only"):
        async with physical.database.begin() as connection:
            unit_of_work = UnitOfWork(connection)
            async with unit_of_work.governed(
                event_type="TAMPER_ATTEMPT",
                actor=Actor(kind="SYSTEM", id="intake-tests"),
                authority="NONE",
                case_id=case_id,
            ) as write:
                await write.execute(
                    update(ExceptionFact)
                    .where(ExceptionFact.id == fact.id)
                    .values(attested_by="somebody-else")
                )


async def test_a_correction_needs_something_to_correct(physical: Intake) -> None:
    opened = await physical.report()
    await physical.drain()

    with pytest.raises(intake.NothingToCorrectError):
        await physical.correct(opened.case_id)


# ------------------------------------------------------------------------ needs human (§27)


async def test_an_unreadable_report_escalates_instead_of_guessing(physical: Intake) -> None:
    opened = await physical.report(UNREADABLE)
    await physical.drain()
    case = await physical.case(opened.case_id)

    assert case.state == CASE_NEEDS_HUMAN
    assert case.needs_owner_attention is True


async def test_an_escalated_case_invents_nothing_and_moves_nothing(physical: Intake) -> None:
    before = await physical.on_hand(STRAWBERRIES)
    opened = await physical.report(UNREADABLE)
    await physical.drain()

    assert await physical.facts(opened.case_id) == []
    assert await physical.exception(opened.case_id) is None
    assert (await physical.line(RASPBERRY_LINE)).received_state == "EXPECTED"
    assert (await physical.line(STRAWBERRY_LINE)).received_state == "EXPECTED"
    assert await physical.on_hand(STRAWBERRIES) == before
    assert await physical.clarifications(opened.case_id) == []


async def test_an_escalation_is_recorded_with_the_words_that_caused_it(
    physical: Intake,
) -> None:
    opened = await physical.report(UNREADABLE)
    await physical.drain()

    escalations = [
        row
        for row in await physical.audits(opened.case_id)
        if row.type == AUDIT_NEEDS_HUMAN_INTERPRETATION
    ]
    assert len(escalations) == 1
    assert escalations[0].provenance["raw_utterance"] == UNREADABLE
    assert escalations[0].after["reason"] == "NO_CATEGORY"
    assert EVENT_NEEDS_HUMAN in await physical.events(opened.case_id)
    assert (await physical.reports(opened.case_id))[0].raw_text == UNREADABLE


async def test_the_nearest_resource_is_never_chosen_for_the_worker(physical: Intake) -> None:
    opened = await physical.report("the raspberries and the blueberries didn't arrive")
    await physical.drain()

    assert (await physical.case(opened.case_id)).state == CASE_NEEDS_HUMAN
    assert (await physical.line(RASPBERRY_LINE)).received_state == "EXPECTED"


# ------------------------------------------------------------------ crash safety (§28)


async def test_a_worker_that_dies_after_claiming_leaves_the_work_for_the_next_one(
    physical: Intake,
) -> None:
    from promisepatch.domain import crash

    opened = await physical.report()
    first = physical.worker(identity="dies-after-claiming")

    with crash.arm(crash.AFTER_CLAIM_COMMIT), pytest.raises(crash.WorkerDied):
        await first.run_once()

    (claimed,) = await physical.outstanding(opened.case_id)
    assert claimed.state == "IN_FLIGHT"

    await physical.expire_lease(claimed.id)
    await physical.drain(worker=physical.worker(identity="picks-it-up"))

    assert (await physical.case(opened.case_id)).state == CASE_CLARIFYING


async def test_a_death_before_the_transition_commits_leaves_no_physical_trace(
    physical: Intake,
) -> None:
    from promisepatch.domain import crash

    opened = await physical.report()
    await physical.drain()
    await physical.answer(opened.case_id, RASPBERRY_ONLY)

    worker = physical.worker(identity="dies-mid-resolution")
    await worker.run_once()  # BEGIN_INTERPRETATION
    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await worker.run_once()

    assert await physical.facts(opened.case_id) == []
    assert (await physical.line(RASPBERRY_LINE)).received_state == "EXPECTED"
    assert (await physical.line(STRAWBERRY_LINE)).received_state == "EXPECTED"
    assert await physical.postings(STRAWBERRIES) == []


async def test_the_work_survives_that_death_and_completes_on_the_next_attempt(
    physical: Intake,
) -> None:
    from promisepatch.domain import crash

    opened = await physical.report()
    await physical.drain()
    await physical.answer(opened.case_id, RASPBERRY_ONLY)

    worker = physical.worker(identity="dies-mid-resolution")
    await worker.run_once()
    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await worker.run_once()

    for step in await physical.outstanding(opened.case_id):
        await physical.expire_lease(step.id)
    await physical.drain(worker=physical.worker(identity="finishes-the-job"))

    assert (await physical.line(STRAWBERRY_LINE)).received_state == "RECEIVED"
    assert [posting.delta for posting in await physical.postings(STRAWBERRIES)] == [SIX_KILOS]


async def test_a_death_after_the_transition_commits_leaves_the_facts_standing(
    physical: Intake,
) -> None:
    from promisepatch.domain import crash

    opened = await physical.report()
    await physical.drain()
    await physical.answer(opened.case_id, RASPBERRY_ONLY)

    worker = physical.worker(identity="dies-after-committing")
    await worker.run_once()
    with crash.arm(crash.AFTER_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await worker.run_once()

    assert (await physical.line(STRAWBERRY_LINE)).received_state == "RECEIVED"

    await physical.drain(worker=physical.worker(identity="tries-again"))
    assert [posting.delta for posting in await physical.postings(STRAWBERRIES)] == [SIX_KILOS]
    assert len(await physical.facts(opened.case_id)) == 2


async def test_a_worker_that_lost_its_lease_cannot_overwrite_the_one_that_did_the_work(
    physical: Intake,
) -> None:
    """A stalled claim names an attempt that no longer exists, and matches no row."""
    from promisepatch.domain import steps

    opened = await physical.report()
    await physical.drain()
    await physical.answer(opened.case_id, RASPBERRY_ONLY)
    await physical.drain(limit=1)  # BEGIN_INTERPRETATION only

    stale = await steps.claim_step(physical.database, worker="worker-a")
    assert stale is not None
    await physical.expire_lease(stale.step_id)

    await physical.drain(worker=physical.worker(identity="worker-b"))
    assert (await physical.line(STRAWBERRY_LINE)).received_state == "RECEIVED"
    facts_after_b = len(await physical.facts(opened.case_id))

    result = await steps.execute_step(
        physical.database, claim=stale, actor=Actor(kind="SYSTEM", id="worker-a")
    )
    assert result in (StepResult.LEASE_LOST, StepResult.STALE)
    assert len(await physical.facts(opened.case_id)) == facts_after_b
    assert [posting.delta for posting in await physical.postings(STRAWBERRIES)] == [SIX_KILOS]


# ------------------------------------------------------------------- concurrency (§29)


async def test_two_workers_sweeping_at_once_execute_the_step_once_between_them(
    physical: Intake,
) -> None:
    import asyncio

    opened = await physical.report()
    await physical.drain(limit=1)
    await physical.drain(limit=1)
    await physical.answer(opened.case_id, RASPBERRY_ONLY)
    await physical.drain(limit=1)

    a = physical.worker(identity="sweeper-a")
    b = physical.worker(identity="sweeper-b")
    await asyncio.gather(a.run_once(), b.run_once())

    assert [posting.delta for posting in await physical.postings(STRAWBERRIES)] == [SIX_KILOS]
    assert len(await physical.facts(opened.case_id)) == 2


async def test_the_same_answer_arriving_twice_at_once_produces_one_statement(
    physical: Intake,
) -> None:
    import asyncio

    opened = await physical.report()
    await physical.drain()
    command = uuid4()

    results = await asyncio.gather(
        physical.answer(opened.case_id, RASPBERRY_ONLY, command_id=command),
        physical.answer(opened.case_id, RASPBERRY_ONLY, command_id=command),
        return_exceptions=True,
    )
    accepted = [item for item in results if isinstance(item, intake.IntakeResult)]
    assert accepted

    await physical.drain()
    assert len(await physical.reports(opened.case_id)) == 2
    assert [posting.delta for posting in await physical.postings(STRAWBERRIES)] == [SIX_KILOS]


async def test_answering_a_case_that_is_not_waiting_is_refused(physical: Intake) -> None:
    opened = await physical.report()

    with pytest.raises(intake.NotAwaitingClarificationError):
        await physical.answer(opened.case_id, RASPBERRY_ONLY)


async def test_a_worker_who_did_not_open_the_case_may_not_answer_for_it(
    physical: Intake,
) -> None:
    """A physical attestation is only worth anything if the person was there to see it."""
    opened = await physical.report()
    await physical.drain()

    async with physical.another_baker() as stranger:
        with pytest.raises(intake.NotPermittedError):
            await physical.answer(opened.case_id, RASPBERRY_ONLY, worker_id=stranger)

    assert await physical.clarifications(opened.case_id)
    assert (await physical.clarifications(opened.case_id))[0].answered_at is None


async def test_an_owner_may_answer_any_case(physical: Intake) -> None:
    opened = await physical.report()
    await physical.drain()
    await physical.answer(opened.case_id, RASPBERRY_ONLY, worker_id=OWNER)
    await physical.drain()

    assert (await physical.line(STRAWBERRY_LINE)).received_state == "RECEIVED"
    answered = [
        row
        for row in await physical.audits(opened.case_id)
        if row.type == AUDIT_CLARIFICATION_ANSWERED
    ]
    assert answered[0].actor_kind == "OWNER"


# ----------------------------------------------------------------- event ordering (§30)


async def test_two_contending_intake_transactions_cannot_hide_an_event_from_a_reader(
    physical: Intake,
) -> None:
    """The spine's forward-only cursor must not step over a committed case event.

    Two independent cases are opened concurrently, so two transactions draw sequence numbers
    and commit in whichever order the database settles on. A reader that walks forward from a
    sequence taken before either of them must still see both.
    """
    import asyncio

    cursor = await physical.latest_event_seq()
    first, second = await asyncio.gather(
        physical.report(), physical.report("the deck oven is down")
    )

    seen = await physical.events_after(cursor)
    opened = [event.case_id for event in seen if event.type == EVENT_CASE_OPENED]
    assert first.case_id in opened
    assert second.case_id in opened

    sequences = [event.seq for event in seen]
    assert sequences == sorted(sequences)


async def test_a_reader_walking_forward_one_event_at_a_time_misses_nothing(
    physical: Intake,
) -> None:
    cursor = await physical.latest_event_seq()
    case_id = await physical.resolved_case()

    collected: list[str] = []
    position = cursor
    while True:
        batch = await physical.events_after(position)
        if not batch:
            break
        collected.append(batch[0].type)
        position = batch[0].seq

    for event in await physical.events(case_id):
        assert event in collected


# ------------------------------------------------------- the other exception categories


async def test_equipment_down_records_an_outage_without_asking_anything(
    physical: Intake,
) -> None:
    from sqlalchemy import select

    from promisepatch.db.models import EquipmentOutage

    opened = await physical.report("the deck oven is down")
    await physical.drain_intake(opened.case_id)

    case = await physical.case(opened.case_id)
    assert case.state == CASE_INTERPRETING
    assert await physical.clarifications(opened.case_id) == []

    async with physical.database.connect() as connection:
        outages = (
            await connection.execute(
                select(EquipmentOutage).where(EquipmentOutage.equipment_id == "res-deck-oven")
            )
        ).all()
    assert len(outages) == 1
    assert outages[0].ends_at is None

    facts = await physical.facts(opened.case_id)
    assert [fact.target_kind for fact in facts] == ["equipment"]


async def test_spoiled_stock_removes_exactly_what_is_on_hand(physical: Intake) -> None:
    before = await physical.on_hand("res-heavy-cream")
    await physical.report("the cream in the walk-in went off")
    await physical.drain()

    assert await physical.on_hand("res-heavy-cream") == Decimal("0.000")
    postings = await physical.postings("res-heavy-cream")
    assert [posting.delta for posting in postings] == [-before]
    assert postings[0].source_kind == "EXCEPTION_FACT"


async def test_a_partial_spoilage_with_no_number_never_invents_one(physical: Intake) -> None:
    before = await physical.on_hand("res-heavy-cream")
    opened = await physical.report("some of the cream went off")
    await physical.drain()

    assert (await physical.case(opened.case_id)).state == CASE_NEEDS_HUMAN
    assert await physical.on_hand("res-heavy-cream") == before
