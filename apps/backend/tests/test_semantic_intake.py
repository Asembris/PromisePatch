"""Semantic intake end to end: a worker, a database, a scripted model, and no AWS.

The rules are tested one at a time in `test_semantic_grounding.py`. This suite is about what
actually happens to a case: which steps run, whether a model is asked at all, what is written,
what is not written, what survives a crash, and who the ledger says attested what.

Two properties run through nearly every test here and are worth stating once:

**Nothing here needs a model.** The provider is scripted, reaches no network and holds no
credential, and its answers pass through the same acceptance gate a real one's do. The whole
file runs on a laptop that has never heard of AWS, and so does CI.

**Deterministic first is asserted, not assumed.** Where a sentence the lexicon understands is
involved, the test counts provider calls and expects zero. That number is the difference
between a system that uses a model where it needs one and a system that has quietly become a
model with a database attached.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from _intake_support import (
    BAKER,
    CANONICAL_REPORT,
    RASPBERRY_LINE,
    RASPBERRY_ONLY,
    STRAWBERRIES,
    STRAWBERRY_LINE,
    UNREADABLE,
    WHOLE_DELIVERY,
    Intake,
)
from _intake_support import physical as physical
from _semantic_support import (
    COLOUR_COMPLAINT,
    CREAM_TURNED,
    DECK_OVEN,
    DECK_OVEN_DOWN,
    HEAVY_CREAM,
    INJECTION,
    PARTIAL_DELIVERY,
    RASPBERRIES,
    THE_BERRIES,
    VP_TODAY_RASPBERRY,
    failing,
    reading,
    scripted,
)
from pydantic import ValidationError
from sqlalchemy import update

from promise_graph.model import ExceptionCategory
from promisepatch.db.models import CaseStep, EquipmentOutage
from promisepatch.domain import crash, retry, semantic_intake
from promisepatch.domain.observation import (
    AUDIT_NEEDS_HUMAN_INTERPRETATION,
    AUDIT_PHYSICAL_FACT_RECORDED,
    AUDIT_SEMANTIC_INTERPRETATION_REQUESTED,
    CASE_CLARIFYING,
    CASE_NEEDS_HUMAN,
    EVENT_SEMANTIC_REQUESTED,
    EVENT_SEMANTIC_RESOLVED,
    SOURCE_DETERMINISTIC,
    SOURCE_SEMANTIC_ASSISTED,
    STEP_INTERPRET_SEMANTICALLY,
    EscalationReason,
)
from promisepatch.semantic import SemanticProviderError, SemanticTimeoutError

pytestmark = pytest.mark.integration

EQUIPMENT_READING = reading(
    category=ExceptionCategory.EQUIPMENT_UNAVAILABLE, equipment=(DECK_OVEN,)
)
CREAM_READING = reading(category=ExceptionCategory.STOCK_UNUSABLE, resources=(HEAVY_CREAM,))
PARTIAL_READING = reading(
    category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
    resources=(RASPBERRIES,),
    clarification_needed=False,
    scope_hint="only the raspberries; the strawberries arrived",
)


async def semantic_step(physical: Intake, case_id: UUID) -> Any:
    """The step that asked a model about this case, or ``None`` if none was ever enqueued."""
    steps = [
        step for step in await physical.steps(case_id) if step.kind == STEP_INTERPRET_SEMANTICALLY
    ]
    return steps[-1] if steps else None


# ------------------------------------------------------- deterministic first (§30, §31, §23)


async def test_the_canonical_sentence_never_reaches_a_model(physical: Intake) -> None:
    """The one assertion that keeps this slice honest about cost, latency and determinism.

    "Today's raspberry delivery didn't arrive" is understood by the lexicon, so the model is
    not asked -- not asked and then ignored, not asked in parallel: not asked.
    """
    session = scripted(physical, EQUIPMENT_READING)
    opened = await physical.report(CANONICAL_REPORT)
    await physical.drain(worker=session.worker)

    assert session.calls == 0
    assert (await physical.case(opened.case_id)).state == CASE_CLARIFYING
    assert (await physical.clarifications(opened.case_id))[0].slot == "SCOPE"


async def test_the_canonical_settlement_is_exactly_what_it_was(physical: Intake) -> None:
    """The raspberry path, whole, with a model in the room that is never spoken to."""
    before = await physical.on_hand(STRAWBERRIES)
    session = scripted(physical, EQUIPMENT_READING)

    opened = await physical.report(CANONICAL_REPORT)
    await physical.drain_intake(opened.case_id, worker=session.worker)
    await physical.answer(opened.case_id, RASPBERRY_ONLY)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert session.calls == 0
    assert (await physical.line(RASPBERRY_LINE)).received_state == "NOT_RECEIVED"
    assert (await physical.line(STRAWBERRY_LINE)).received_state == "RECEIVED"
    assert await physical.on_hand(STRAWBERRIES) == before + Decimal("6.0")


async def test_the_whole_delivery_path_is_exactly_what_it_was(physical: Intake) -> None:
    before = await physical.on_hand(STRAWBERRIES)
    session = scripted(physical, EQUIPMENT_READING)

    opened = await physical.report(CANONICAL_REPORT)
    await physical.drain_intake(opened.case_id, worker=session.worker)
    await physical.answer(opened.case_id, WHOLE_DELIVERY)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert session.calls == 0
    assert (await physical.line(RASPBERRY_LINE)).received_state == "NOT_RECEIVED"
    assert (await physical.line(STRAWBERRY_LINE)).received_state == "NOT_RECEIVED"
    assert await physical.on_hand(STRAWBERRIES) == before


async def test_a_clarification_answer_is_never_read_by_a_model(physical: Intake) -> None:
    """Which lines arrived is a physical outcome, so that sentence never leaves the building."""
    session = scripted(physical, PARTIAL_READING)
    opened = await physical.report(CANONICAL_REPORT)
    await physical.drain_intake(opened.case_id, worker=session.worker)
    await physical.answer(opened.case_id, "the ones in the blue crate")
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert session.calls == 0


async def test_a_deterministic_escalation_that_no_reading_can_help_asks_nobody(
    physical: Intake,
) -> None:
    """Two ingredients named is not a parse failure. Nothing is bought by asking again."""
    session = scripted(physical, PARTIAL_READING)
    opened = await physical.report("the raspberries and the blueberries didn't arrive")
    await physical.drain(worker=session.worker)

    assert session.calls == 0
    assert (await physical.case(opened.case_id)).state == CASE_NEEDS_HUMAN


# --------------------------------------------------------------- grounded success (§32, §49)


async def test_equipment_language_the_lexicon_lacks_becomes_a_worker_attested_fact(
    physical: Intake,
) -> None:
    """The product improvement, in one test: a sentence that used to need a person, read.

    "packed up" is in no marker list. The reading proposes the deck oven, the deck oven is
    written in the sentence, and what follows is the deterministic equipment path -- an
    outage, a fact, and a case ready for analysis.
    """
    session = scripted(physical, EQUIPMENT_READING)
    opened = await physical.report(DECK_OVEN_DOWN)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert session.calls == 1
    exception = await physical.exception(opened.case_id)
    assert exception.category == ExceptionCategory.EQUIPMENT_UNAVAILABLE.value
    assert exception.resource_id == DECK_OVEN
    facts = await physical.facts(opened.case_id)
    assert [fact.target_kind for fact in facts] == ["equipment"]


async def test_the_worker_remains_the_attestor_of_a_semantic_assisted_fact(
    physical: Intake,
) -> None:
    """The trust line, as a row. The model is provenance; the person is authority.

    The audit row's actor is the baker who spoke, its authority is ``NONE`` because no policy
    and no customer permitted the oven to fail, and its rule id is the physical-fact rule. The
    model appears once, under provenance, described as what read the sentence.
    """
    session = scripted(physical, EQUIPMENT_READING)
    opened = await physical.report(DECK_OVEN_DOWN)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    recorded = [
        row
        for row in await physical.audits(opened.case_id)
        if row.type == AUDIT_PHYSICAL_FACT_RECORDED
    ]
    assert len(recorded) == 1
    assert recorded[0].actor_kind == "WORKER"
    assert recorded[0].actor_id == BAKER
    assert recorded[0].authority == "NONE"
    assert recorded[0].provenance["interpretation_source"] == SOURCE_SEMANTIC_ASSISTED
    assert recorded[0].provenance["semantic"]["provider"] == "fake"
    assert recorded[0].provenance["semantic"]["grounding"]["accepted"] == [DECK_OVEN]

    facts = await physical.facts(opened.case_id)
    assert {fact.attested_by for fact in facts} == {BAKER}


async def test_nothing_in_the_ledger_says_a_model_observed_anything(physical: Intake) -> None:
    """A negative assertion, deliberately blunt. No row may name a model as an authority."""
    session = scripted(physical, EQUIPMENT_READING)
    opened = await physical.report(DECK_OVEN_DOWN)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    for row in await physical.audits(opened.case_id):
        assert row.actor_kind in {"WORKER", "SYSTEM"}
        assert row.authority in {"NONE", "POLICY", "CONSTRAINT", "HUMAN_APPROVAL"}
        assert "LLM" not in str(row.authority)
        assert "BEDROCK" not in str(row.actor_id).upper()
    for fact in await physical.facts(opened.case_id):
        assert fact.attested_by == BAKER


async def test_an_alias_carries_a_reading_the_lexicon_could_not_reach(physical: Intake) -> None:
    """ "has turned" is not a spoilage marker; "cream" is an alias the bakery authored."""
    before = await physical.on_hand(HEAVY_CREAM)
    assert before > 0

    session = scripted(physical, CREAM_READING)
    opened = await physical.report(CREAM_TURNED)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert session.calls == 1
    assert (await physical.exception(opened.case_id)).category == "STOCK_UNUSABLE"
    assert await physical.on_hand(HEAVY_CREAM) == Decimal("0.000")


async def test_a_deterministic_fact_still_says_it_was_deterministic(physical: Intake) -> None:
    """The other half of the provenance: silence would be ambiguous, so it is written down."""
    case_id = await physical.attested_case()

    recorded = [
        row for row in await physical.audits(case_id) if row.type == AUDIT_PHYSICAL_FACT_RECORDED
    ]
    assert recorded[0].provenance["interpretation_source"] == SOURCE_DETERMINISTIC
    assert "semantic" not in recorded[0].provenance


# ----------------------------------------------------------- clarification, not a guess (§13)


async def test_partial_delivery_language_becomes_the_frozen_scope_question(
    physical: Intake,
) -> None:
    """The reading says which ingredient. The deterministic reader says what is still unknown.

    It is the same consequential question the canonical sentence produces, reached from a
    sentence the lexicon cannot parse -- and the strawberries stay expected until a person
    says otherwise.
    """
    session = scripted(physical, PARTIAL_READING)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert session.calls == 1
    case = await physical.case(opened.case_id)
    assert case.state == CASE_CLARIFYING
    asked = await physical.clarifications(opened.case_id)
    assert len(asked) == 1
    assert asked[0].slot == "SCOPE"
    assert {option["code"] for option in asked[0].options} == {
        "WHOLE_DELIVERY",
        "JUST_RASPBERRIES",
    }
    assert await physical.facts(opened.case_id) == []
    assert (await physical.line(STRAWBERRY_LINE)).received_state == "EXPECTED"


async def test_the_models_no_clarification_needed_is_not_a_decision(physical: Intake) -> None:
    """The advisory flag at its most assertive, overruled by a deterministic trigger.

    The scripted reading says clarification is unnecessary *and* offers the answer it would
    have given. Both are ignored, because whether to ask is not a model's to decide and what
    arrived is not a model's to say.
    """
    session = scripted(physical, PARTIAL_READING)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert PARTIAL_READING["clarification_needed"] is False
    assert (await physical.case(opened.case_id)).state == CASE_CLARIFYING
    assert await physical.facts(opened.case_id) == []


async def test_the_worker_answer_after_a_semantic_reading_settles_normally(
    physical: Intake,
) -> None:
    """And then the ordinary machinery finishes the job, with no second model call."""
    before = await physical.on_hand(STRAWBERRIES)
    session = scripted(physical, PARTIAL_READING)

    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain_intake(opened.case_id, worker=session.worker)
    await physical.answer(opened.case_id, RASPBERRY_ONLY)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert session.calls == 1
    assert (await physical.line(RASPBERRY_LINE)).received_state == "NOT_RECEIVED"
    assert (await physical.line(STRAWBERRY_LINE)).received_state == "RECEIVED"
    assert await physical.on_hand(STRAWBERRIES) == before + Decimal("6.0")


# -------------------------------------------------------------------- failing closed (§17-21)


async def test_a_confident_reading_of_words_nobody_said_settles_nothing(
    physical: Intake,
) -> None:
    """ "the berries" -- the model picks one, the bakery's vocabulary does not support it."""
    session = scripted(
        physical,
        reading(
            category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
            resources=(RASPBERRIES,),
            confidence=1.0,
            clarification_needed=False,
        ),
    )
    opened = await physical.report(THE_BERRIES)
    await physical.drain(worker=session.worker)

    assert session.calls == 1
    assert (await physical.case(opened.case_id)).state == CASE_NEEDS_HUMAN
    assert await physical.facts(opened.case_id) == []
    assert await physical.clarifications(opened.case_id) == []
    assert (await physical.line(RASPBERRY_LINE)).received_state == "EXPECTED"


async def test_an_invented_identifier_never_becomes_anything(physical: Intake) -> None:
    """Twice, because the boundary offers exactly one corrective retry and it is spent here.

    A model that invents an identifier once is told what was wrong with its answer and asked
    again; one that invents one twice is refused. Either way nothing is bound, and the
    difference is only whether the ledger records a refusal or an empty reading.
    """
    invented = reading(category=ExceptionCategory.SUPPLY_NOT_RECEIVED, resources=("res-invented",))
    session = scripted(physical, invented, invented)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain(worker=session.worker)

    assert session.calls == 2
    assert (await physical.case(opened.case_id)).state == CASE_NEEDS_HUMAN
    assert await physical.facts(opened.case_id) == []
    assert await physical.exception(opened.case_id) is None
    step = await semantic_step(physical, opened.case_id)
    assert step.result["semantic"]["failure"] == "UNKNOWN_CANDIDATE"


async def test_one_invented_identifier_is_corrected_and_still_binds_nothing(
    physical: Intake,
) -> None:
    """The corrective retry in the workflow: the second answer is honest and says nothing."""
    session = scripted(
        physical,
        reading(category=ExceptionCategory.SUPPLY_NOT_RECEIVED, resources=("res-invented",)),
    )
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain(worker=session.worker)

    assert session.calls == 2
    assert session.provider.calls[1].correction is not None
    assert (await physical.case(opened.case_id)).state == CASE_NEEDS_HUMAN
    assert await physical.facts(opened.case_id) == []


async def test_a_real_identifier_that_was_not_offered_is_refused_too(physical: Intake) -> None:
    """Existing globally is not the test. Having been offered for *this* reading is.

    ``res-deck-oven`` is a row in this database. It is offered as equipment and never as an
    ingredient, so a reading that names it as one is refused for the same reason an invented id
    is -- and the case is escalated rather than bound to a plausible-looking oven.
    """
    as_ingredient = reading(category=ExceptionCategory.SUPPLY_NOT_RECEIVED, resources=(DECK_OVEN,))
    session = scripted(physical, as_ingredient, as_ingredient)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain(worker=session.worker)

    assert (await physical.case(opened.case_id)).state == CASE_NEEDS_HUMAN
    assert await physical.facts(opened.case_id) == []
    step = await semantic_step(physical, opened.case_id)
    assert step.result["semantic"]["failure"] == "UNKNOWN_CANDIDATE"


async def test_a_settled_line_is_not_offered_to_a_later_case(physical: Intake) -> None:
    """The narrowing has teeth: yesterday's attested line cannot be named by today's reading.

    The first case settles the Valley delivery. A second case's candidate set therefore holds
    no line of it at all, so a reading naming the raspberry line -- a row that exists, with an
    id anybody could read off the first case -- is refused.
    """
    await physical.resolved_case()

    settled = reading(
        category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
        resources=(RASPBERRIES,),
        lines=(VP_TODAY_RASPBERRY,),
    )
    session = scripted(physical, settled, settled)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain(worker=session.worker)

    step = await semantic_step(physical, opened.case_id)
    assert step.result["semantic"]["failure"] == "UNKNOWN_CANDIDATE"
    assert await physical.facts(opened.case_id) == []


async def test_a_sentence_outside_the_three_categories_invents_no_fourth(
    physical: Intake,
) -> None:
    session = scripted(physical, reading(out_of_scope=True))
    opened = await physical.report(COLOUR_COMPLAINT)
    await physical.drain(worker=session.worker)

    assert (await physical.case(opened.case_id)).state == CASE_NEEDS_HUMAN
    assert await physical.exception(opened.case_id) is None
    assert await physical.facts(opened.case_id) == []
    assert await physical.postings(RASPBERRIES) == []


async def test_a_malformed_answer_writes_nothing_at_all(physical: Intake) -> None:
    """Schema-invalid, twice: the corrective retry is spent and the reading is refused.

    Nothing partial survives. No exception row, no clarification, no ledger movement, and a
    case a person can pick up with the worker's words intact.
    """
    before = await physical.on_hand(STRAWBERRIES)
    session = scripted(physical, {"category": "NOT_A_CATEGORY"}, "not an object at all")
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain(worker=session.worker)

    assert session.calls == 2
    assert (await physical.case(opened.case_id)).state == CASE_NEEDS_HUMAN
    assert await physical.exception(opened.case_id) is None
    assert await physical.facts(opened.case_id) == []
    assert await physical.clarifications(opened.case_id) == []
    assert await physical.on_hand(STRAWBERRIES) == before
    assert (await physical.line(RASPBERRY_LINE)).received_state == "EXPECTED"


async def test_a_refused_answer_is_not_asked_again(physical: Intake) -> None:
    """A model that answered something we will not accept will answer it again. Stop.

    The distinction the retry policy rests on: a refusal is about the content, and content
    repeats. Only a provider that could not be reached is worth a second attempt.
    """
    invented = reading(category=ExceptionCategory.SUPPLY_NOT_RECEIVED, resources=("res-invented",))
    session = scripted(physical, invented, invented)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain(worker=session.worker)

    step = await semantic_step(physical, opened.case_id)
    assert step.state == "DONE"
    assert step.attempts == 1


async def test_an_injected_instruction_moves_nothing(physical: Intake) -> None:
    """A worker's sentence written as an instruction, and a model that obeys it completely.

    The reading names the category the text demanded, the resource id the text spelled out,
    both commitment lines, and says no clarification is required. What the delivery held is
    still a question, so the delivery is still a question -- and both lines stay expected until
    a person answers it.
    """
    session = scripted(
        physical,
        reading(
            category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
            resources=(RASPBERRIES,),
            lines=(VP_TODAY_RASPBERRY, STRAWBERRY_LINE),
            clarification_needed=False,
            scope_hint="the whole delivery",
        ),
    )
    opened = await physical.report(INJECTION)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert (await physical.case(opened.case_id)).state == CASE_CLARIFYING
    assert await physical.facts(opened.case_id) == []
    assert (await physical.line(RASPBERRY_LINE)).received_state == "EXPECTED"
    assert (await physical.line(STRAWBERRY_LINE)).received_state == "EXPECTED"


async def test_no_semantic_reading_can_produce_a_customer_decision(physical: Intake) -> None:
    """Consent is somebody else's slice, and this one may not reach into it.

    Asserted at the outcome rather than at the import, because the property that matters is
    that no path from a worker's sentence ends at an approval, however the code is arranged.
    """
    session = scripted(physical, EQUIPMENT_READING, PARTIAL_READING, CREAM_READING)
    for sentence in (DECK_OVEN_DOWN, PARTIAL_DELIVERY, CREAM_TURNED):
        await physical.report(sentence)
        await physical.drain(worker=session.worker, limit=24)

    assert await physical.decisions() == []
    assert await physical.requests() == []


# ------------------------------------------------------- provider failure and retries (§21-22)


async def test_a_provider_outage_is_retried_rather_than_believed(physical: Intake) -> None:
    """Silence from a provider says nothing about a kitchen, so nothing is concluded from it."""
    session = failing(physical, SemanticTimeoutError("the model did not answer in time"))
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain(worker=session.worker, limit=4)

    step = await semantic_step(physical, opened.case_id)
    assert step.state == "RETRYING"
    assert step.next_attempt_at is not None
    assert (await physical.case(opened.case_id)).state != CASE_NEEDS_HUMAN
    assert await physical.facts(opened.case_id) == []


async def test_a_provider_that_comes_back_finishes_the_work(physical: Intake) -> None:
    """One 503 does not send a case to a person. The ladder is there to be climbed."""
    session = scripted(
        physical,
        SemanticProviderError("throttled", retryable=True),
        PARTIAL_READING,
    )
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain(worker=session.worker, limit=4)
    await physical.make_work_due()
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert session.calls == 2
    assert (await physical.case(opened.case_id)).state == CASE_CLARIFYING


async def test_a_provider_that_never_comes_back_escalates_under_its_own_reason(
    physical: Intake,
) -> None:
    """At the bound, a person takes over -- and the reason names the provider, not the worker.

    An operator reading ``SEMANTIC_UNAVAILABLE`` should go and look at a model endpoint. An
    operator reading ``NO_CATEGORY`` should go and read the sentence. Collapsing the two would
    send somebody to the wrong place.
    """
    session = failing(physical, SemanticTimeoutError("still nothing"))
    opened = await physical.report(PARTIAL_DELIVERY)
    for _ in range(retry.MAX_ATTEMPTS + 1):
        await physical.drain(worker=session.worker, limit=4)
        await physical.make_work_due()

    case = await physical.case(opened.case_id)
    assert case.state == CASE_NEEDS_HUMAN
    assert case.needs_owner_attention is True
    escalation = [
        row
        for row in await physical.audits(opened.case_id)
        if row.type == AUDIT_NEEDS_HUMAN_INTERPRETATION
    ][-1]
    assert escalation.after["reason"] == EscalationReason.SEMANTIC_UNAVAILABLE.value
    assert await physical.facts(opened.case_id) == []


async def test_an_ungrounded_reading_escalates_under_the_sentence_s_own_reason(
    physical: Intake,
) -> None:
    """The opposite case: a model answered, and the sentence is still unread.

    The reason is the one the lexicon stopped for, because that is what is actually wrong.
    Inventing a semantic-specific reason here would point an operator at a working provider.
    """
    opened = await physical.report(UNREADABLE)
    await physical.drain()

    escalation = [
        row
        for row in await physical.audits(opened.case_id)
        if row.type == AUDIT_NEEDS_HUMAN_INTERPRETATION
    ][-1]
    assert escalation.after["reason"] == EscalationReason.NO_CATEGORY.value
    assert escalation.provenance["raw_utterance"] == UNREADABLE
    assert escalation.provenance["semantic"]["grounding"]["failure"] == "NO_CATEGORY"


# ------------------------------------------------------------- staleness and identity (§39-41)


async def test_a_reading_produced_against_a_changed_kitchen_cannot_commit(
    physical: Intake,
) -> None:
    """The fingerprint check, forced: the reading is real and the context is not the one it saw.

    Rewriting the stored fingerprint is the same thing as the delivery having been corrected
    between the call and its consumption. The reading is discarded rather than applied, the
    step goes back on the ladder, and the sentence is read again against the kitchen as it is.
    """
    session = scripted(physical, PARTIAL_READING, PARTIAL_READING)
    opened = await physical.report(PARTIAL_DELIVERY)
    step = await _read_but_do_not_commit(physical, session, opened.case_id)

    await _corrupt_fingerprint(physical, opened.case_id)
    await physical.expire_lease(step.id)
    await physical.drain(worker=session.worker, limit=1)

    step = await semantic_step(physical, opened.case_id)
    assert step.state == "RETRYING"
    assert "since changed" in (step.error or "")
    assert await physical.facts(opened.case_id) == []
    assert await physical.clarifications(opened.case_id) == []


async def test_a_stale_reading_is_replaced_rather_than_abandoned(physical: Intake) -> None:
    """And then the work finishes correctly, because the sentence is simply read again."""
    session = scripted(physical, PARTIAL_READING, PARTIAL_READING)
    opened = await physical.report(PARTIAL_DELIVERY)
    step = await _read_but_do_not_commit(physical, session, opened.case_id)
    await _corrupt_fingerprint(physical, opened.case_id)
    await physical.expire_lease(step.id)
    await physical.drain(worker=session.worker, limit=1)
    await physical.make_work_due()
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert (await physical.case(opened.case_id)).state == CASE_CLARIFYING
    assert session.calls == 2


async def _read_but_do_not_commit(physical: Intake, session: Any, case_id: UUID) -> Any:
    """Drive the case to the instant a reading is on the row and the transition has not run.

    The crash is the mechanism rather than the subject here: it is simply the only way to stand
    between the two halves of the semantic step, which is exactly where a context change has to
    be caught.
    """
    await physical.drain(worker=session.worker, limit=2)
    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await session.worker.run_once()
    step = await semantic_step(physical, case_id)
    assert step.result["semantic"]["status"] == semantic_intake.STATUS_READ
    return step


async def _corrupt_fingerprint(physical: Intake, case_id: UUID) -> None:
    step = await semantic_step(physical, case_id)
    payload = dict(step.result)
    payload["semantic"] = {**payload["semantic"], "request_hash": "0" * 64}
    async with physical.database.begin() as connection:
        await connection.execute(
            update(CaseStep).where(CaseStep.id == step.id).values(result=payload)
        )


def test_a_stored_row_that_carries_no_reading_is_refused_rather_than_believed() -> None:
    """The durable half of the acceptance path, and it is read as strictly as the wire half.

    A reading survives a restart on ``case_steps.result``, so what comes back off that row is
    model output that has been through a database. It is re-validated through the same strict
    model on the way out -- and a payload that says a model was read while carrying nothing a
    model could have said is that same refusal rather than an exception, because a payload
    shape is not worth crashing a worker over. The consuming transition escalates the sentence
    to a person, which is where it was going before anybody was asked.
    """
    assert semantic_intake.reading_of({"status": semantic_intake.STATUS_READ}) is None
    assert semantic_intake.reading_of({"reading": None}) is None
    assert semantic_intake.reading_of({"reading": "EQUIPMENT_UNAVAILABLE"}) is None

    honest = semantic_intake.reading_of({"reading": {"category": None, "bindings": []}})
    assert honest is not None and honest.bindings == ()

    with pytest.raises(ValidationError):
        # Still strict about what it *does* carry: a shape is refused loudly, because that is a
        # payload claiming to be a reading rather than a row that has none.
        semantic_intake.reading_of({"reading": {"category": "NOT_A_CATEGORY"}})


async def test_a_replayed_report_produces_one_case_and_one_reading(physical: Intake) -> None:
    session = scripted(physical, PARTIAL_READING)
    command = uuid4()

    first = await physical.report(PARTIAL_DELIVERY, command_id=command)
    second = await physical.report(PARTIAL_DELIVERY, command_id=command)
    await physical.drain_intake(first.case_id, worker=session.worker)

    assert second.case_id == first.case_id
    assert second.created is False
    assert session.calls == 1
    assert len(await physical.clarifications(first.case_id)) == 1


# -------------------------------------------------------------------- crash safety (§50)


async def test_a_worker_that_dies_before_the_call_leaves_the_work_for_the_next_one(
    physical: Intake,
) -> None:
    session = scripted(physical, PARTIAL_READING)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain(worker=session.worker, limit=2)

    with crash.arm(crash.BEFORE_SEMANTIC_CALL), pytest.raises(crash.WorkerDied):
        await session.worker.run_once()

    assert session.calls == 0
    step = await semantic_step(physical, opened.case_id)
    assert step.state == "IN_FLIGHT"

    await physical.expire_lease(step.id)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert session.calls == 1
    assert (await physical.case(opened.case_id)).state == CASE_CLARIFYING
    assert len(await physical.clarifications(opened.case_id)) == 1


async def test_a_worker_that_dies_after_the_call_asks_again_and_still_asks_once(
    physical: Intake,
) -> None:
    """The honest window: the model may be called twice, and the workflow effect is still one.

    A model call moves nothing in anybody's world, so there is no exactly-once to fake here.
    What must hold is that two readings do not become two questions, two facts or two
    settlements -- and one clarification is what the case ends with.
    """
    session = scripted(physical, PARTIAL_READING, PARTIAL_READING)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain(worker=session.worker, limit=2)

    with crash.arm(crash.AFTER_SEMANTIC_CALL), pytest.raises(crash.WorkerDied):
        await session.worker.run_once()

    assert session.calls == 1
    step = await semantic_step(physical, opened.case_id)
    await physical.expire_lease(step.id)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert session.calls == 2
    assert len(await physical.clarifications(opened.case_id)) == 1
    assert await physical.facts(opened.case_id) == []


async def test_a_stored_reading_survives_a_crash_and_is_not_bought_twice(
    physical: Intake,
) -> None:
    """A reading already on the row is consumed after a restart, not re-fetched.

    The crash is armed at the transition commit, so the reading was stored and the transition
    was not. What the next worker finds is an answer it has already paid for.
    """
    session = scripted(physical, PARTIAL_READING)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain(worker=session.worker, limit=2)

    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await session.worker.run_once()

    assert session.calls == 1
    step = await semantic_step(physical, opened.case_id)
    assert step.result["semantic"]["status"] == semantic_intake.STATUS_READ
    await physical.expire_lease(step.id)

    await physical.drain_intake(opened.case_id, worker=physical.worker(semantic=session.provider))

    assert session.calls == 1
    assert (await physical.case(opened.case_id)).state == CASE_CLARIFYING
    assert len(await physical.clarifications(opened.case_id)) == 1


async def test_a_worker_that_dies_after_the_transition_repeats_nothing(
    physical: Intake,
) -> None:
    session = scripted(physical, EQUIPMENT_READING)
    opened = await physical.report(DECK_OVEN_DOWN)
    await physical.drain(worker=session.worker, limit=2)

    with crash.arm(crash.AFTER_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await session.worker.run_once()

    fresh = physical.worker(semantic=session.provider)
    await physical.drain_intake(opened.case_id, worker=fresh)

    assert len(await physical.facts(opened.case_id)) == 1
    assert len(await physical.rows_of(EquipmentOutage)) == 1


async def test_a_clarification_reached_semantically_resumes_after_a_restart(
    physical: Intake,
) -> None:
    session = scripted(physical, PARTIAL_READING)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    assert (await physical.case(opened.case_id)).state == CASE_CLARIFYING

    fresh = physical.worker(identity="restarted", semantic=session.provider)
    await physical.answer(opened.case_id, RASPBERRY_ONLY)
    await physical.drain_intake(opened.case_id, worker=fresh)

    assert (await physical.line(RASPBERRY_LINE)).received_state == "NOT_RECEIVED"
    assert (await physical.line(STRAWBERRY_LINE)).received_state == "RECEIVED"


# ------------------------------------------------------------- ledger and spine (§25, §26)


async def test_asking_for_a_reading_is_audited_as_the_system_asking(physical: Intake) -> None:
    session = scripted(physical, PARTIAL_READING)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    requested = [
        row
        for row in await physical.audits(opened.case_id)
        if row.type == AUDIT_SEMANTIC_INTERPRETATION_REQUESTED
    ]
    assert len(requested) == 1
    assert requested[0].actor_kind == "SYSTEM"
    assert requested[0].authority == "NONE"
    assert requested[0].after["reason"] == EscalationReason.NO_CATEGORY.value


async def test_the_spine_carries_envelopes_and_not_the_workers_words(physical: Intake) -> None:
    session = scripted(physical, PARTIAL_READING)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    types = await physical.events(opened.case_id)
    assert EVENT_SEMANTIC_REQUESTED in types
    assert EVENT_SEMANTIC_RESOLVED in types

    seq = 0
    for event in await physical.events_after(seq):
        if event.case_id == opened.case_id:
            assert PARTIAL_DELIVERY not in str(event.payload)


async def test_the_step_ledger_shows_which_model_read_the_sentence(physical: Intake) -> None:
    """§47's evidence, at the row it lives on: provider, model, candidates, what grounded."""
    session = scripted(physical, PARTIAL_READING)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    step = await semantic_step(physical, opened.case_id)
    stored = step.result["semantic"]
    assert stored["provider"] == "fake"
    assert stored["candidates"]["commitments"] >= 1
    assert stored["grounding"]["accepted"] == [RASPBERRIES]
    assert step.result["interpretation_source"] == SOURCE_SEMANTIC_ASSISTED


async def test_no_prompt_and_no_model_prose_is_persisted(physical: Intake) -> None:
    """Provenance, not a transcript. The stored reading is identifiers and a category."""
    session = scripted(physical, PARTIAL_READING)
    opened = await physical.report(PARTIAL_DELIVERY)
    await physical.drain_intake(opened.case_id, worker=session.worker)

    step = await semantic_step(physical, opened.case_id)
    stored = step.result["semantic"]
    assert set(stored["reading"]) <= {
        "category",
        "bindings",
        "scope_hint",
        "quantity_hint",
        "clarification_needed",
        "out_of_scope",
    }
    assert "CANDIDATES" not in str(step.result)
    assert "WORKER STATEMENT" not in str(step.result)


# -------------------------------------------------------------------------- isolation (§42)


async def test_a_stalled_reading_in_one_case_does_not_stall_another(physical: Intake) -> None:
    """No global semantic lock: a provider that will not answer holds up only its own case."""
    stalled = await physical.report(PARTIAL_DELIVERY)
    session = failing(physical, SemanticTimeoutError("nothing"))
    await physical.drain(worker=session.worker, limit=4)

    moving = await physical.report(CANONICAL_REPORT)
    await physical.drain_intake(moving.case_id, worker=session.worker)

    assert (await physical.case(moving.case_id)).state == CASE_CLARIFYING
    assert (await physical.case(stalled.case_id)).state != CASE_CLARIFYING


async def test_what_the_model_is_shown_is_the_bakery_and_the_sentence(
    physical: Intake,
) -> None:
    """§44: no customer, no order, no promise, no price reaches a supply interpretation."""
    session = scripted(physical, PARTIAL_READING)
    await physical.report(PARTIAL_DELIVERY)
    await physical.drain(worker=session.worker, limit=3)

    prompt = session.prompts[0]
    assert PARTIAL_DELIVERY in prompt
    assert "res-raspberries" in prompt
    for forbidden in ("Tomas", "Priya", "ord-", "pro-", "cus-", "rec-"):
        assert forbidden not in prompt
