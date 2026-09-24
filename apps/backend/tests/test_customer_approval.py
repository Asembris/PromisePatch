"""The consent protocol, against a real database, a real worker and a fake customer channel.

The shape of these tests is the shape of the guarantee, and it has four parts.

The first is **that a request is real before anybody waits on one**. A row is not a
conversation: the track becomes ``WAITING_FOR_CUSTOMER`` when the provider has accepted the
message and not before, and a message that could not be delivered -- or whose window closed
while it queued -- never produces a case that claims to be waiting on somebody nobody reached.

The second is **that the wait is durable**. The case is parked in PostgreSQL, the deadline is a
row, and the worker is killed and replaced between every interesting pair of steps. Nothing here
depends on a process staying alive, and nothing depends on a test sleeping.

The third is **that only a literal reply authorises anything**. ``Strawberries work`` is the
canonical proof and it is asserted as hard as ``YES`` is: the reply persists, the sender is
checked, and the decision count does not move. Wrong sender, late reply, duplicate delivery and
a ``YES``/``NO`` race are each proved to leave at most one decision, for ever. The parser itself
is proved without any of this, in ``test_consent_parser``, because a rule that decides whether
somebody consented should be explainable without a database.

The fourth is **that approval is not application**. Even after a literal ``YES``, B has no
recovery effect, is not ``RECOVERED``, and the case hands itself to ``REVALIDATING`` rather than
pretending the ten checks have run. Consent is necessary authority; it is not proof that the
plan is still valid.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from _intake_support import (
    BAKER,
    RASPBERRY_ONLY,
    TOMAS_CHANNEL,
    UNREADABLE,
    Intake,
)
from _intake_support import physical as physical

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import ApprovalRequestState, ParserKind
from promisepatch.db.models import ApprovalDecision, ApprovalRequest, InboundReply
from promisepatch.domain import analysis, approvals, cases, crash, messaging, recovery
from promisepatch.domain.adapters import FakeEffectAdapter, ProviderBehaviour
from promisepatch.domain.model import DeliveryOutcome, DeliveryStatus

pytestmark = pytest.mark.integration

A, B, C, D, E, F = (
    ho.PROMISE_A,
    ho.PROMISE_B,
    ho.PROMISE_C,
    ho.PROMISE_D,
    ho.PROMISE_E,
    ho.PROMISE_F,
)

NON_LITERAL = "Strawberries work"
"""The canonical sentence that must never become consent, quoted from the frozen spec."""


# ------------------------------------------------------------------------------------ driving


async def planned_case(intake_fixture: Intake) -> UUID:
    opened = await intake_fixture.report()
    await intake_fixture.drain()
    await intake_fixture.answer(opened.case_id, RASPBERRY_ONLY)
    await intake_fixture.drain()
    return opened.case_id


async def confirmed_case(intake_fixture: Intake) -> UUID:
    case_id = await planned_case(intake_fixture)
    await intake_fixture.confirm(case_id)
    return case_id


async def waiting_case(intake_fixture: Intake, *, adapter: FakeEffectAdapter | None = None) -> UUID:
    """The canonical case driven all the way to a durable wait on promise B's customer."""
    case_id = await confirmed_case(intake_fixture)
    await intake_fixture.drain(worker=intake_fixture.worker(adapter=adapter), limit=40)
    return case_id


async def track_of(intake_fixture: Intake, case_id: UUID, promise_id: str) -> Any:
    row = await intake_fixture.track(case_id, promise_id)
    assert row is not None
    return row


async def states(intake_fixture: Intake, case_id: UUID) -> dict[str, str]:
    return {track.promise_id: track.state for track in await intake_fixture.tracks(case_id)}


async def the_request(intake_fixture: Intake) -> Any:
    """The one approval request the canonical case produces. Its uniqueness is the assertion."""
    requests = await intake_fixture.requests()
    assert len(requests) == 1
    return requests[0]


async def audit_types(intake_fixture: Intake, case_id: UUID) -> list[str]:
    return [row.type for row in await intake_fixture.audits(case_id)]


async def amendments_for(intake_fixture: Intake, track_id: UUID) -> list[Any]:
    """Order-system effects for one track, which is what "B executed nothing" means.

    The approval message names the track too, so the assertion has to be about amendments
    specifically -- otherwise "no effect for B" would be false the moment we asked its customer
    anything, and the interesting claim would be untestable.
    """
    return [
        row
        for row in await intake_fixture.effects_for(track_id)
        if row.kind == recovery.EFFECT_ORDER_AMEND
    ]


# ==================================================================== creating the request


async def test_an_approval_required_track_earns_durable_approval_work(physical: Intake) -> None:
    """A worker's yes authorises the asking, and enqueues it as a row rather than a message."""
    case_id = await confirmed_case(physical)
    track_b = await track_of(physical, case_id, B)

    step = await physical.step_named(case_id, approvals.request_step_key(track_b.id))

    assert step is not None
    assert step.kind == approvals.STEP_REQUEST_APPROVAL
    assert step.state == "PENDING"
    assert step.track_id == track_b.id
    # Confirmation itself sends nothing at all.
    assert await physical.requests() == []
    assert await physical.effects() == []


async def test_only_the_approval_required_track_earns_approval_work(physical: Intake) -> None:
    """A, C, D, E and F are not asked about. Selectivity is asserted as hard as coverage."""
    case_id = await confirmed_case(physical)
    tracks = {track.promise_id: track.id for track in await physical.tracks(case_id)}

    keys = {step.step_key for step in await physical.steps(case_id)}

    assert approvals.request_step_key(tracks[B]) in keys
    for promise_id in (A, C, D, E, F):
        assert approvals.request_step_key(tracks[promise_id]) not in keys


async def test_the_request_binds_the_track_option_customer_and_world(physical: Intake) -> None:
    """§13.6's binding, persisted: one option, one channel, and the state it was asked against."""
    case_id = await waiting_case(physical)
    track_b = await track_of(physical, case_id, B)
    request = await the_request(physical)

    assert request.track_id == track_b.id
    assert request.promise_id == B
    assert request.option_id == track_b.chosen_option_id
    assert request.customer_channel == TOMAS_CHANNEL
    assert request.captured_fingerprint == track_b.fingerprint
    assert request.captured_order_version >= 1
    assert request.captured_constraint_hash
    assert request.captured_recipe_version_id
    assert request.deadline == track_b.deadline_at
    assert request.option_code == approvals.option_code_for(track_b.chosen_option_id)


async def test_the_request_names_only_a_pre_authored_version(physical: Intake) -> None:
    """Nothing at runtime invents a version; the request points at the row planning chose."""
    case_id = await waiting_case(physical)
    track_b = await track_of(physical, case_id, B)
    option = next(
        row for row in await physical.options(track_b.id) if row.id == track_b.chosen_option_id
    )

    request = await the_request(physical)

    assert request.option_id == option.id
    assert option.requires_approval is True
    assert option.to_version_id is not None


async def test_the_request_identity_is_derived_rather_than_minted(physical: Intake) -> None:
    """One logical ask has one primary key, whichever process happens to compute it."""
    case_id = await waiting_case(physical)
    track_b = await track_of(physical, case_id, B)
    request = await the_request(physical)

    assert request.id == approvals.request_id_for(track_b.id, track_b.chosen_option_id)


async def test_one_logical_request_survives_a_replayed_step(physical: Intake) -> None:
    """Running the same piece of work twice writes one request, not two conversations."""
    case_id = await waiting_case(physical)
    track_b = await track_of(physical, case_id, B)
    request_step = await physical.step_named(case_id, approvals.request_step_key(track_b.id))
    assert request_step is not None
    before = await physical.requests()

    await physical.requeue(request_step.id)
    await physical.drain(limit=20)

    assert len(before) == 1
    assert [row.id for row in await physical.requests()] == [row.id for row in before]
    assert (await track_of(physical, case_id, B)).state == cases.TRACK_WAITING_FOR_CUSTOMER
    messages = [
        row for row in await physical.effects() if row.kind == approvals.EFFECT_MESSAGE_SEND
    ]
    assert len(messages) == 1


async def test_a_closed_window_is_never_asked_about(physical: Intake) -> None:
    """§13.6: deadline at or before now means no request, no message, and an escalation."""
    case_id = await confirmed_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.close_planning_window(track_b.id)

    await physical.drain(limit=40)

    assert await physical.requests() == []
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED
    # §14.2: a case with nothing left to apply and nobody left to ask never waits. It
    # reconciles and finishes, carrying the escalation to the owner with it.
    assert (await physical.case(case_id)).state == cases.CASE_RESOLVED
    assert (await physical.case(case_id)).needs_owner_attention is True
    assert approvals.AUDIT_APPROVAL_NOT_SENT in await audit_types(physical, case_id)


async def test_a_closed_window_holds_the_kitchen_work(physical: Intake) -> None:
    """The one write a refusal to ask performs, so nobody starts a cake nobody can ask about."""
    case_id = await confirmed_case(physical)
    track_b = await track_of(physical, case_id, B)
    before = await physical.tasks()
    await physical.close_planning_window(track_b.id)

    await physical.drain(limit=40)

    after = await physical.tasks()
    moved = {task: after[task] for task in after if before[task] != after[task]}
    assert f"task-{ho.LINE_B}" in moved
    assert moved[f"task-{ho.LINE_B}"] == ("HELD", case_id)


async def test_a_closed_window_sends_no_message(physical: Intake) -> None:
    """No outbound approval effect at all: the customer is never contacted."""
    case_id = await confirmed_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.close_planning_window(track_b.id)
    adapter = FakeEffectAdapter()

    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)

    assert [call.kind for call in adapter.attempts] == [recovery.EFFECT_ORDER_AMEND]


# ======================================================================= sending the message


async def test_the_message_is_one_outbox_row_under_a_derived_key(physical: Intake) -> None:
    """§12.3's ``pp:approval:{request_id}``: server-side identity, no attempt, no clock."""
    await waiting_case(physical)
    request = await the_request(physical)

    effects = [row for row in await physical.effects() if row.kind == approvals.EFFECT_MESSAGE_SEND]

    assert len(effects) == 1
    assert effects[0].idempotency_key == approvals.message_idempotency_key(request.id)
    assert effects[0].state == "DELIVERED"
    assert effects[0].payload["request_id"] == str(request.id)


async def test_the_message_says_what_changes_and_how_to_answer(physical: Intake) -> None:
    """Derived from persisted rows: the customer's name, their order, the exact substitution."""
    await waiting_case(physical)
    request = await the_request(physical)
    effects = [row for row in await physical.effects() if row.kind == approvals.EFFECT_MESSAGE_SEND]
    text = effects[0].payload["text"]

    # That it carries *an* answering instruction, rather than which one. Which one is decided
    # by the deployment's link configuration, is unit-tested in ``test_consent_parser.py``, and
    # is enforced on this very path by ``carries_required_literals`` -- which the workflow runs
    # before enqueueing anything and which refuses the instruction this deployment did not owe.
    # So a wrong choice does not fall through to a laxer assertion here; it raises before the
    # row exists at all.
    assert any(instruction in text for instruction in messaging.CONSENT_INSTRUCTIONS)
    assert request.option_code in text
    assert "Tomas" in text
    assert "EXT-B" in text
    assert effects[0].payload["channel_address"] == TOMAS_CHANNEL.partition(":")[2]


CHAT = "1234567890"
"""A chat id of the shape a real one has, for the provider below to stamp a reference with."""


class TelegramShapedAdapter(FakeEffectAdapter):
    """The fake provider, answering a customer message the way the Telegram adapter does.

    Subclassed rather than mocked so everything else about the flow stays real: the outbox, the
    continuation, the request row and the case transitions are the ones the ordinary tests
    drive. The single difference is the string the provider hands back for a message, which is
    where a customer's address enters this system -- ``telegram:<chat id>:<message id>``.

    Without this the whole suite runs on ``fake-<hex>`` references, which carry no address and
    so could never have caught the disclosure this exists to prove is closed.
    """

    async def deliver(self, *, kind: str, payload: Any, idempotency_key: str) -> DeliveryOutcome:
        outcome = await super().deliver(kind=kind, payload=payload, idempotency_key=idempotency_key)
        if kind != approvals.EFFECT_MESSAGE_SEND or outcome.status is not DeliveryStatus.DELIVERED:
            return outcome
        return DeliveryOutcome(
            status=DeliveryStatus.DELIVERED, provider_ref=f"telegram:{CHAT}:4242"
        )


async def test_a_customers_chat_id_never_reaches_the_status_projection(
    physical: Intake,
) -> None:
    """The surface ``pp case-status`` and ``GET /api/cases/{id}`` are both built from.

    Until this was closed, a Telegram receipt reached three readers: the operator terminal, an
    HTTP response served over the public internet, and the evidence drawer the deployed SPA
    renders it into. All three read this one projection, so masking it here is what closes all
    three -- and asserting it here is what proves they stay closed.

    The durable rows are deliberately *not* asserted to be masked. They keep the whole
    reference, because that is what a redelivery is reasoned about against and what lets a
    reader who is entitled to ask learn which chat was reached. The rule is about boundaries,
    not about storage, and this test is both halves of it.
    """
    adapter = TelegramShapedAdapter()
    case_id = await waiting_case(physical, adapter=adapter)

    status = await analysis.read_case_status(physical.database, case_id=case_id)
    rendered = [
        track for track in status.tracks if track.approval is not None and track.approval.sent_at
    ]
    assert rendered, "the case must really have asked somebody for this to prove anything"

    for track in status.tracks:
        if track.approval is not None:
            assert track.approval.provider_ref == "telegram:***"
        for effect in track.effects:
            assert CHAT not in str(effect.provider_ref)

    # And the row underneath still holds it, which is the other half of the same rule.
    request = await the_request(physical)
    assert request.provider_ref == f"telegram:{CHAT}:4242"


async def test_the_message_promises_a_link_exactly_when_one_is_attached(
    physical: Intake,
) -> None:
    """The regression that would replace the one ADR-0021 removed, on the row really written.

    A message reading "open the secure link below" with nothing below it would be the same
    defect in a new spelling: an instruction naming a way to answer that the message does not
    provide. The wording and the URL are decided from one reading of one setting -- in
    ``approvals._draft`` and ``approvals._approval_url`` -- and this says so about the payload.

    It asserts an equivalence rather than a value, so it holds whichever way the environment
    running it is configured, and fails the moment the two sides stop agreeing.
    """
    await waiting_case(physical)
    effects = [row for row in await physical.effects() if row.kind == approvals.EFFECT_MESSAGE_SEND]
    payload = effects[0].payload
    text = payload["text"]

    promises_a_link = messaging.CONSENT_INSTRUCTION in text
    carries_a_link = bool(payload.get("approval_url"))
    assert promises_a_link is carries_a_link

    if not promises_a_link:
        assert messaging.CONSENT_WITHOUT_LINK_INSTRUCTION in text


async def test_no_customer_message_ever_asks_for_a_reply(physical: Intake) -> None:
    """There is no inbound path, so nothing written to a customer may tell them to use one.

    Asserted over the text of every customer-facing effect this case produced rather than over
    a builder, because a builder is not what reaches a phone. A real customer followed the old
    instruction into the bot's chat on 2026-09-22 and reached nothing.
    """
    await waiting_case(physical)
    effects = [row for row in await physical.effects() if row.kind == approvals.EFFECT_MESSAGE_SEND]
    assert effects

    for effect in effects:
        lowered = str(effect.payload["text"]).lower()
        for forbidden in ("reply", "respond", "text back", "send yes"):
            assert forbidden not in lowered


async def test_the_track_waits_only_once_the_message_was_accepted(physical: Intake) -> None:
    """A row is not a conversation. The request exists first; the wait starts on acceptance."""
    case_id = await confirmed_case(physical)
    await track_of(physical, case_id, B)
    # Hold the dispatcher off by failing every send retryably, so the request exists unsent.
    adapter = FakeEffectAdapter(
        fail_with=DeliveryOutcome(status=DeliveryStatus.RETRYABLE, error="provider is slow")
    )

    await physical.drain(worker=physical.worker(adapter=adapter), limit=6)

    assert len(await physical.requests()) == 1
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_PENDING
    assert (await physical.case(case_id)).state == cases.CASE_EXECUTING


async def test_an_ordinary_send_is_one_call_and_one_message(physical: Intake) -> None:
    """The baseline the uncertain-window test is measured against."""
    case_id = await confirmed_case(physical)
    adapter = FakeEffectAdapter()

    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)
    request = await the_request(physical)
    key = approvals.message_idempotency_key(request.id)

    assert len([call for call in adapter.attempts if call.idempotency_key == key]) == 1
    assert adapter.effect_for(key) is not None
    assert (await track_of(physical, case_id, B)).state == cases.TRACK_WAITING_FOR_CUSTOMER


async def test_a_lost_acknowledgement_resends_under_the_same_key(physical: Intake) -> None:
    """Two transport attempts, one logical customer message, one approval request."""
    case_id = await confirmed_case(physical)
    # A's recovery runs first and on its own, so the scripted behaviour lands on the message
    # rather than on whichever of the two independent effects the worker happened to claim.
    await physical.defer_approvals(case_id)
    await physical.drain(limit=40)
    adapter = FakeEffectAdapter(script=[ProviderBehaviour.APPLY_THEN_LOSE_RESPONSE])
    await physical.release_approvals(case_id)

    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)
    request = await the_request(physical)
    key = approvals.message_idempotency_key(request.id)
    effects = [row for row in await physical.effects() if row.idempotency_key == key]
    await physical.make_effect_due(effects[0].id)
    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)

    calls = [call for call in adapter.attempts if call.idempotency_key == key]
    assert len(calls) == 2
    assert len(adapter.effects) == 1  # one logical message, however many transport calls
    assert len(await physical.requests()) == 1
    assert (await track_of(physical, case_id, B)).state == cases.TRACK_WAITING_FOR_CUSTOMER


async def test_a_terminally_undeliverable_message_never_becomes_a_wait(physical: Intake) -> None:
    """§29: a case must not claim to be waiting on a customer who was never reached."""
    case_id = await confirmed_case(physical)
    adapter = FakeEffectAdapter(
        fail_with=DeliveryOutcome(status=DeliveryStatus.TERMINAL, error="the provider refused it")
    )

    await physical.drain(worker=physical.worker(adapter=adapter), limit=60)

    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED
    request = await the_request(physical)
    assert request.state == ApprovalRequestState.EXPIRED.value
    assert request.decided is False
    assert (await physical.case(case_id)).state != cases.CASE_WAITING
    assert (await physical.case(case_id)).needs_owner_attention is True
    assert approvals.AUDIT_APPROVAL_DELIVERY_FAILED in await audit_types(physical, case_id)


async def test_a_message_whose_window_closed_while_queued_is_never_delivered(
    physical: Intake,
) -> None:
    """§13.6 and the deadline/send race: no late approval message becomes a waiting state."""
    case_id = await confirmed_case(physical)
    adapter = FakeEffectAdapter(
        fail_with=DeliveryOutcome(status=DeliveryStatus.RETRYABLE, error="provider is slow")
    )
    await physical.drain(worker=physical.worker(adapter=adapter), limit=6)
    request = await the_request(physical)
    key = approvals.message_idempotency_key(request.id)
    effect = next(row for row in await physical.effects() if row.idempotency_key == key)

    await physical.close_window(request.id)
    await physical.make_effect_due(effect.id)
    delivering = FakeEffectAdapter()
    await physical.drain(worker=physical.worker(adapter=delivering), limit=40)

    assert [
        call.idempotency_key for call in delivering.attempts if call.idempotency_key == key
    ] == []
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED
    assert (await physical.request_for((await track_of(physical, case_id, B)).id)).state == (
        ApprovalRequestState.EXPIRED.value
    )
    assert (await physical.case(case_id)).state != cases.CASE_WAITING


async def test_a_message_refused_at_its_first_claim_says_it_was_not_sent(physical: Intake) -> None:
    """The request step commits the message and the worker dies; the window closes; one claim.

    A claim at one attempt is provably the first, so the refusal may say the message was not
    sent -- and the customer's provider saw no call carrying its key.
    """
    case_id = await confirmed_case(physical)
    await physical.defer_approvals(case_id)
    await physical.drain(limit=40)
    await physical.release_approvals(case_id)
    with crash.arm(crash.AFTER_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.worker(identity="died").run_once()
    request = await the_request(physical)
    key = approvals.message_idempotency_key(request.id)
    (queued,) = [row for row in await physical.effects() if row.idempotency_key == key]
    assert (queued.state, queued.attempts) == ("PENDING", 0)

    await physical.close_window(request.id)
    adapter = FakeEffectAdapter()
    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)

    assert [call for call in adapter.attempts if call.idempotency_key == key] == []
    (refused,) = [row for row in await physical.effects() if row.idempotency_key == key]
    assert (refused.state, refused.attempts) == ("FAILED", 1)
    assert refused.last_error == "the approval window closed before the message was sent"
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED


async def test_a_window_closing_after_an_uncertain_attempt_claims_nothing_it_cannot_know(
    physical: Intake,
) -> None:
    """The provider took the message and the answer was lost; the window closed before the retry.

    The retry is refused, as it should be -- nobody can answer a closed question -- but the row
    must not say the window closed "before the message could be delivered": it was delivered.
    """
    case_id = await confirmed_case(physical)
    await physical.defer_approvals(case_id)
    await physical.drain(limit=40)
    adapter = FakeEffectAdapter(script=[ProviderBehaviour.APPLY_THEN_LOSE_RESPONSE])
    await physical.release_approvals(case_id)
    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)
    request = await the_request(physical)
    key = approvals.message_idempotency_key(request.id)
    (uncertain,) = [row for row in await physical.effects() if row.idempotency_key == key]
    assert (uncertain.state, uncertain.attempts) == ("PENDING", 1)
    assert adapter.effect_for(key) is not None  # the customer has it

    await physical.close_window(request.id)
    await physical.make_effect_due(uncertain.id)
    await physical.drain(worker=physical.worker(adapter=adapter), limit=40)

    assert len([call for call in adapter.attempts if call.idempotency_key == key]) == 1
    (refused,) = [row for row in await physical.effects() if row.idempotency_key == key]
    assert (refused.state, refused.attempts) == ("FAILED", 2)
    assert "could be delivered" not in refused.last_error
    assert refused.last_error == (
        "the approval window closed before this attempt; an earlier attempt may already have "
        "reached the customer"
    )
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED


# =========================================================================== the case waits


async def test_the_canonical_case_waits_on_its_one_customer(physical: Intake) -> None:
    """A recovered, B waiting, C and D escalated, E and F untouched, and the case parked."""
    case_id = await waiting_case(physical)

    assert await states(physical, case_id) == {
        A: recovery.TRACK_RECOVERED,
        B: cases.TRACK_WAITING_FOR_CUSTOMER,
        C: recovery.TRACK_ESCALATED,
        D: recovery.TRACK_ESCALATED,
        E: "UNAFFECTED",
        F: "UNAFFECTED",
    }
    assert (await physical.case(case_id)).state == cases.CASE_WAITING


async def test_the_case_does_not_wait_while_the_recovery_is_still_applying(
    physical: Intake,
) -> None:
    """The approval message goes first, A finishes later, and the wait starts only at the end."""
    case_id = await confirmed_case(physical)
    track_a = await track_of(physical, case_id, A)
    apply_step = await physical.step_named(case_id, recovery.apply_step_key(track_a.id))
    assert apply_step is not None

    await physical.defer(apply_step.id)
    await physical.drain(limit=40)

    assert (await track_of(physical, case_id, B)).state == cases.TRACK_WAITING_FOR_CUSTOMER
    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_PENDING
    assert (await physical.case(case_id)).state == cases.CASE_EXECUTING

    await physical.release(apply_step.id)
    await physical.drain(limit=40)

    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED
    assert (await physical.case(case_id)).state == cases.CASE_WAITING


async def test_the_case_waits_whichever_transition_finishes_last(physical: Intake) -> None:
    """The other order: A recovers first, the approval message goes out afterwards."""
    case_id = await confirmed_case(physical)
    track_b = await track_of(physical, case_id, B)
    request_step = await physical.step_named(case_id, approvals.request_step_key(track_b.id))
    assert request_step is not None

    await physical.defer(request_step.id)
    await physical.drain(limit=40)

    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED
    assert (await physical.case(case_id)).state == cases.CASE_EXECUTING

    await physical.release(request_step.id)
    await physical.drain(limit=40)

    assert (await track_of(physical, case_id, B)).state == cases.TRACK_WAITING_FOR_CUSTOMER
    assert (await physical.case(case_id)).state == cases.CASE_WAITING


async def test_a_waiting_case_has_nothing_left_to_run(physical: Intake) -> None:
    """No busy loop, no outstanding step, and an armed deadline that is a row."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    assert await physical.outstanding(case_id) == []
    armed = [row for row in await physical.timers() if row.subject_id == str(request.id)]
    assert [row.kind for row in armed] == [approvals.TIMER_APPROVAL_DEADLINE]
    assert armed[0].fired_at is None
    assert armed[0].due_at == request.deadline


async def test_a_waiting_case_survives_a_worker_that_stops_and_restarts(physical: Intake) -> None:
    """Kill the worker, start a fresh one, and nothing about the wait has moved."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    fresh = physical.worker(identity="restarted-worker")
    for _ in range(5):
        await fresh.run_once()

    assert (await physical.case(case_id)).state == cases.CASE_WAITING
    assert (await track_of(physical, case_id, B)).state == cases.TRACK_WAITING_FOR_CUSTOMER
    after = await the_request(physical)
    assert after.id == request.id
    assert after.decided is False
    assert after.state == ApprovalRequestState.SENT.value
    armed = [row for row in await physical.timers() if row.subject_id == str(request.id)]
    assert armed and armed[0].fired_at is None


async def test_a_waiting_case_does_not_stall_unrelated_work(physical: Intake) -> None:
    """Selective continuation: one case parked on a customer, another running normally."""
    waiting_id = await waiting_case(physical)
    other = await physical.report(UNREADABLE)

    await physical.drain(limit=40)

    assert (await physical.case(waiting_id)).state == cases.CASE_WAITING
    assert (await physical.case(other.case_id)).state not in ("RECEIVED", "INTERPRETING")
    assert await physical.steps(other.case_id)
    assert await physical.outstanding(other.case_id) == []


# ================================================================= replies that decide nothing


async def test_a_non_literal_reply_decides_nothing(physical: Intake) -> None:
    """The canonical proof. ``Strawberries work`` is a sentence about strawberries.

    The request moves to ``CONFIRMATION_PENDING`` because §13.6 answers an unreadable reply
    with one prompt asking for a word that counts. That is a change to the *conversation* and
    to nothing else: no decision exists, the track is still waiting on its customer, and the
    case has not left ``WAITING``. What a model made of the sentence is asserted in
    ``test_customer_intent``; what matters here is that none of it is consent.
    """
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await physical.deliver_reply(request.id, NON_LITERAL)
    await physical.drain(limit=20)

    assert await physical.decisions() == []
    after = await the_request(physical)
    assert after.decided is False
    assert after.state == ApprovalRequestState.CONFIRMATION_PENDING.value
    assert (await track_of(physical, case_id, B)).state == cases.TRACK_WAITING_FOR_CUSTOMER
    assert (await physical.case(case_id)).state == cases.CASE_WAITING


async def test_a_non_literal_reply_is_kept_exactly_as_it_was_written(physical: Intake) -> None:
    """Stored as data, read as data, and never as an instruction.

    The row carries the words, the sender and the request, and no reading of any of them: per
    ADR-0008 nothing asks a model what the sentence looked like, so ``apparent_intent`` is the
    column nothing writes. That is the whole of what the protocol has to go on, and it is
    enough, because none of it is an answer.
    """
    await waiting_case(physical)
    request = await the_request(physical)

    await physical.deliver_reply(request.id, NON_LITERAL)
    await physical.drain(limit=20)

    replies = await physical.replies()
    assert len(replies) == 1
    assert replies[0].raw_text == NON_LITERAL
    assert replies[0].request_id == request.id
    assert replies[0].sender_identity == TOMAS_CHANNEL
    assert replies[0].apparent_intent is None
    assert await physical.decisions() == []


async def test_a_non_literal_reply_is_announced_as_unrecognised(physical: Intake) -> None:
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    seq = await physical.latest_event_seq()

    await physical.deliver_reply(request.id, NON_LITERAL)
    await physical.drain(limit=20)

    types = [event.type for event in await physical.events_after(seq)]
    assert approvals.EVENT_APPROVAL_REPLY_UNRECOGNIZED in types
    assert approvals.EVENT_APPROVAL_DECIDED not in types
    assert approvals.AUDIT_APPROVAL_REPLY_RECORDED in await audit_types(physical, case_id)


async def test_a_reply_from_the_wrong_sender_authorises_nothing(physical: Intake) -> None:
    """§14.3 check 8. A literal YES from anybody else is not this customer's consent."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await physical.deliver_reply(request.id, "YES", sender="tg:9999")
    await physical.drain(limit=20)

    assert await physical.decisions() == []
    after = await the_request(physical)
    assert after.decided is False
    assert after.state == ApprovalRequestState.SENT.value
    assert (await track_of(physical, case_id, B)).state == cases.TRACK_WAITING_FOR_CUSTOMER
    assert (await physical.case(case_id)).state == cases.CASE_WAITING
    assert approvals.AUDIT_UNAUTHORIZED_APPROVAL in await audit_types(physical, case_id)


async def test_an_unauthorised_reply_is_kept_and_put_on_the_owners_desk(
    physical: Intake,
) -> None:
    """Discarded as authority, kept as evidence: who sent it, and what they said."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await physical.deliver_reply(request.id, "YES", sender="tg:9999")
    await physical.drain(limit=20)

    replies = await physical.replies()
    assert [row.sender_identity for row in replies] == ["tg:9999"]
    assert (await physical.case(case_id)).needs_owner_attention is True
    row = next(
        audit
        for audit in await physical.audits(case_id)
        if audit.type == approvals.AUDIT_UNAUTHORIZED_APPROVAL
    )
    assert row.authority == "NONE"
    assert row.provenance["sender_identity"] == "tg:9999"
    assert row.provenance["expected_channel"] == TOMAS_CHANNEL


async def test_a_worker_cannot_approve_on_the_customers_behalf(physical: Intake) -> None:
    """There is no operator path to consent, and a reply wearing a worker's name is not one."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await physical.deliver_reply(request.id, "YES", sender=f"tg:{BAKER}")
    await physical.drain(limit=20)

    assert await physical.decisions() == []
    assert (await track_of(physical, case_id, B)).state == cases.TRACK_WAITING_FOR_CUSTOMER
    assert [command for command in _cli_command_names() if "approve" in command] == []


def _cli_command_names() -> list[str]:
    """Every command the operator CLI exposes. The assertion is what is *not* here."""
    from promisepatch.cli import app

    return [command.name or "" for command in app.registered_commands]


async def test_a_duplicate_provider_delivery_is_absorbed(physical: Intake) -> None:
    """§12.2: one logical event, one wake-up, one decision at most."""
    await waiting_case(physical)
    request = await the_request(physical)
    delivery = await physical.deliver_reply(request.id, "YES", event_id="repeat-1")

    await physical.deliver_reply(request.id, "YES", event_id=delivery)
    await physical.drain(limit=20)

    assert len(await physical.decisions()) == 1
    assert len(await physical.replies()) == 1


async def test_a_late_reply_cannot_approve_even_before_the_timer_runs(physical: Intake) -> None:
    """§19: worker backlog must never extend a customer's authority."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    await physical.close_window(request.id)

    # Deliver the reply and process only the inbox and the reply step, never the timer: the
    # decision path itself has to compare the deadline, not rely on expiry having happened.
    await physical.deliver_reply(request.id, "YES")
    await _drain_replies_only(physical)

    assert await physical.decisions() == []
    after = await the_request(physical)
    assert after.decided is False
    assert approvals.AUDIT_APPROVAL_REPLY_LATE in await audit_types(physical, case_id)


async def _drain_replies_only(intake_fixture: Intake) -> None:
    """Run the inbox and the step it creates, with every armed timer pushed out of reach.

    Deliberate rather than convenient: the point of the late-reply rule is that it holds when
    the deadline timer has *not* been processed, so the test has to be able to keep it unfired.
    """
    from sqlalchemy import text as sql_text
    from sqlalchemy import update as sa_update

    from promisepatch.db.models import Timer

    async with intake_fixture.database.begin() as connection:
        await connection.execute(
            sa_update(Timer)
            .where(Timer.fired_at.is_(None))
            .values(due_at=sql_text("now() + interval '1 hour'"))
        )
    await intake_fixture.drain(limit=20)


# ======================================================================== the literal decision


async def test_a_literal_yes_records_exactly_one_approval(physical: Intake) -> None:
    """The central acceptance proof: one decision, from the customer, by the literal parser."""
    await waiting_case(physical)
    request = await the_request(physical)

    await physical.deliver_reply(request.id, NON_LITERAL)
    await physical.drain(limit=20)
    assert await physical.decisions() == []

    await physical.deliver_reply(request.id, "YES")
    await physical.drain(limit=20)

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "APPROVE"
    assert decisions[0].parser == ParserKind.LITERAL.value
    assert decisions[0].request_id == request.id
    assert decisions[0].sender_identity == TOMAS_CHANNEL
    assert decisions[0].raw_text == "YES"


async def test_an_approval_is_bound_to_the_reply_that_carried_it(physical: Intake) -> None:
    """Request, sender, inbound event, parser and instant -- the whole provenance chain."""
    await waiting_case(physical)
    request = await the_request(physical)

    delivery = await physical.deliver_reply(request.id, "YES")
    await physical.drain(limit=20)

    decision = (await physical.decisions())[0]
    reply = next(row for row in await physical.replies() if row.provider_message_id == delivery)
    assert decision.provider_message_id == delivery
    assert reply.request_id == request.id
    assert decision.received_at is not None
    after = await the_request(physical)
    assert after.decided is True
    assert after.state == ApprovalRequestState.ANSWERED.value


async def test_an_approval_does_not_execute_the_recovery(physical: Intake) -> None:
    """Approval is necessary authority; it is not proof the plan is still valid.

    Asserted at the instant the decision commits, which is the moment the claim is about. What
    the customer's yes buys is a revalidation, and until those ten checks have run there is no
    amendment, no applying track and nothing sent -- however long the worker is left running.
    """
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    track_b = await track_of(physical, case_id, B)

    await physical.deliver_reply(request.id, "YES")
    await physical.drain_until_decided()

    assert len(await physical.decisions()) == 1
    assert await amendments_for(physical, track_b.id) == []
    after = await track_of(physical, case_id, B)
    assert after.state == cases.TRACK_WAITING_FOR_CUSTOMER
    assert after.state != recovery.TRACK_RECOVERED
    assert after.state != recovery.TRACK_APPLYING


async def test_an_approved_case_hands_itself_to_revalidation(physical: Intake) -> None:
    """§14.2: a literal decision is what takes a case out of WAITING, and only to REVALIDATING.

    The decision does not resolve the case, execute anything, or skip a state on the way. It
    hands the case to the checklist -- and it does so durably, as a step somebody else runs.
    """
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    seq = await physical.latest_event_seq()

    await physical.deliver_reply(request.id, "YES")
    await physical.drain_until_decided()

    assert (await physical.case(case_id)).state == cases.CASE_REVALIDATING
    types = [event.type for event in await physical.events_after(seq)]
    assert approvals.EVENT_APPROVAL_DECIDED in types
    assert cases.EVENT_CASE_REVALIDATION_READY in types


async def test_a_literal_no_records_exactly_one_decline(physical: Intake) -> None:
    """The other ending, and it executes nothing either."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    track_b = await track_of(physical, case_id, B)

    await physical.deliver_reply(request.id, "NO")
    await physical.drain(limit=30)

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "DECLINE"
    assert decisions[0].parser == ParserKind.LITERAL.value
    assert await amendments_for(physical, track_b.id) == []


async def test_a_decline_escalates_the_track_to_the_owner(physical: Intake) -> None:
    """§13.4's decline transition, and nothing invented about refunds or cancellation."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    before = await physical.order_book()

    await physical.deliver_reply(request.id, "NO")
    await physical.drain(limit=30)

    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED
    assert (await physical.case(case_id)).needs_owner_attention is True
    # A declined approval still has to reach an ending: §14.2 takes the case through
    # REVALIDATING and RECONCILING to RESOLVED, without executing anything on the way.
    assert (await physical.case(case_id)).state == cases.CASE_RESOLVED
    after = await physical.order_book()
    assert after["orders"] == before["orders"]
    assert after["order_lines"] == before["order_lines"]


async def test_a_decided_request_cannot_be_answered_twice(physical: Intake) -> None:
    """A second distinct reply is acknowledged in the ledger and never applied."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    await physical.deliver_reply(request.id, "YES")
    await physical.drain(limit=30)

    await physical.deliver_reply(request.id, "NO")
    await physical.drain(limit=30)

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "APPROVE"
    assert approvals.AUDIT_APPROVAL_ALREADY_DECIDED in await audit_types(physical, case_id)


async def test_a_yes_and_a_no_racing_leave_exactly_one_decision(physical: Intake) -> None:
    """Two workers, two replies, one request. The first valid commit wins for ever."""
    await waiting_case(physical)
    request = await the_request(physical)
    await physical.deliver_reply(request.id, "YES", event_id="race-yes")
    await physical.deliver_reply(request.id, "NO", event_id="race-no")

    first, second = physical.worker(identity="racer-one"), physical.worker(identity="racer-two")
    await asyncio.gather(
        physical.drain(worker=first, limit=20), physical.drain(worker=second, limit=20)
    )

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision in ("APPROVE", "DECLINE")
    assert len(await physical.replies()) == 2


async def test_the_decision_that_won_is_never_overwritten(physical: Intake) -> None:
    """Append-only and unique per request: there is no code path that could revise consent."""
    await waiting_case(physical)
    request = await the_request(physical)
    await physical.deliver_reply(request.id, "YES")
    await physical.drain(limit=30)
    first = (await physical.decisions())[0]

    for text_said in ("NO", "YES", NON_LITERAL):
        await physical.deliver_reply(request.id, text_said)
        await physical.drain(limit=30)

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].id == first.id
    assert decisions[0].decision == first.decision


# ================================================================== the deadline, and the race


async def test_an_unanswered_request_expires_when_its_timer_fires(physical: Intake) -> None:
    """§38: a fresh worker, a durable timer, an expiry, and no fabricated decision."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    await physical.close_window(request.id)

    fresh = physical.worker(identity="worker-after-the-deadline")
    await physical.drain(worker=fresh, limit=30)

    assert await physical.decisions() == []
    after = await the_request(physical)
    assert after.state == ApprovalRequestState.EXPIRED.value
    assert after.decided is False
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED
    assert (await physical.case(case_id)).needs_owner_attention is True
    assert approvals.AUDIT_APPROVAL_EXPIRED in await audit_types(physical, case_id)


async def test_an_expired_request_hands_the_case_on_as_well(physical: Intake) -> None:
    """Nothing is outstanding any more, so the case stops waiting -- without a decision."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    seq = await physical.latest_event_seq()
    await physical.close_window(request.id)

    await physical.drain(limit=30)

    types = [event.type for event in await physical.events_after(seq)]
    assert cases.EVENT_CASE_REVALIDATION_READY in types
    assert approvals.EVENT_APPROVAL_EXPIRED in types
    assert approvals.EVENT_APPROVAL_DECIDED not in types
    # And having handed itself on, it finishes: an expiry needs no approved execution to end.
    assert (await physical.case(case_id)).state == cases.CASE_RESOLVED


async def test_an_expired_request_holds_the_kitchen_work(physical: Intake) -> None:
    """§23 answers "customer does not reply" with "EXPIRED -> ESCALATED; task HELD".

    The escalation is only half of that row. A customer who was asked and let the deadline pass
    and a customer who could not be asked at all are in the same position -- nobody is coming,
    and no answer that arrives later can authorise anything -- so the kitchen stops either way.
    Without the hold the bakery may finish a raspberry cake the case has already concluded it
    cannot make correctly and cannot get permission to change.
    """
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    before = await physical.tasks()
    await physical.close_window(request.id)

    await physical.drain(worker=physical.worker(identity="worker-after-the-deadline"), limit=30)

    after = await physical.tasks()
    moved = {task: after[task] for task in after if before[task] != after[task]}
    assert moved.get(f"task-{ho.LINE_B}") == ("HELD", case_id)


async def test_an_undeliverable_message_inside_an_open_window_holds_nothing(
    physical: Intake,
) -> None:
    """The other half of the same decision, pinned so it cannot drift into the hold.

    Expiry and undeliverable transport share one ending, and §23 states the hold for the first
    of them only. A window that is still open has not reached the spec's row: the deadline has
    not passed, so this escalation is not the one §23 answers with a held task, and it takes no
    write on the kitchen.
    """
    case_id = await confirmed_case(physical)
    before = await physical.tasks()
    adapter = FakeEffectAdapter(
        fail_with=DeliveryOutcome(status=DeliveryStatus.TERMINAL, error="the provider refused it")
    )

    await physical.drain(worker=physical.worker(adapter=adapter), limit=60)

    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED
    after = await physical.tasks()
    assert after[f"task-{ho.LINE_B}"] == before[f"task-{ho.LINE_B}"]


async def test_a_decision_that_committed_first_makes_the_timer_a_no_op(physical: Intake) -> None:
    """Scenario A of the reply/timer race: the answer wins, and the deadline changes nothing."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await physical.deliver_reply(request.id, "YES")
    await physical.drain(limit=30)
    await physical.close_window(request.id)
    await physical.drain(limit=30)

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "APPROVE"
    after = await the_request(physical)
    assert after.state == ApprovalRequestState.ANSWERED.value
    # The deadline did nothing: the request was never expired and the track was never
    # escalated for want of an answer -- it went on to be revalidated and recovered.
    assert after.state != ApprovalRequestState.EXPIRED.value
    assert approvals.AUDIT_APPROVAL_EXPIRED not in await audit_types(physical, case_id)
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_RECOVERED


async def test_an_expiry_that_committed_first_refuses_a_later_yes(physical: Intake) -> None:
    """Scenario B: the window closed first, so a literal YES cannot authorise anything."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    await physical.close_window(request.id)
    await physical.drain(limit=30)

    await physical.deliver_reply(request.id, "YES")
    await physical.drain(limit=30)

    assert await physical.decisions() == []
    assert (await the_request(physical)).state == ApprovalRequestState.EXPIRED.value
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED
    assert approvals.AUDIT_APPROVAL_ALREADY_DECIDED in await audit_types(physical, case_id)


# ================================================================== authority, audit and events


async def test_the_decision_audit_names_the_customer_and_not_the_worker(physical: Intake) -> None:
    """§22: the worker executed the transition; it did not supply the consent."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await physical.deliver_reply(request.id, "YES")
    await physical.drain(limit=30)

    row = next(
        audit
        for audit in await physical.audits(case_id)
        if audit.type == approvals.AUDIT_APPROVAL_DECISION
    )
    assert row.actor_kind == "CUSTOMER"
    assert row.authority == "HUMAN_APPROVAL"
    assert row.after["decision"] == "APPROVE"
    assert row.after["parser"] == ParserKind.LITERAL.value
    assert row.provenance["sender_identity"] == TOMAS_CHANNEL
    assert row.provenance["executed_by"]
    assert row.provenance["provider_message_id"]


async def test_asking_is_audited_as_the_system_and_not_as_consent(physical: Intake) -> None:
    """Sending a request is a system action taken on the plan's authority, and says so."""
    case_id = await waiting_case(physical)

    rows = {audit.type: audit for audit in await physical.audits(case_id)}

    requested = rows[approvals.AUDIT_APPROVAL_REQUESTED]
    assert requested.actor_kind == "SYSTEM"
    assert requested.authority in ("POLICY", "CONSTRAINT")
    assert requested.authority != "HUMAN_APPROVAL"
    sent = rows[approvals.AUDIT_APPROVAL_SENT]
    assert sent.actor_kind == "SYSTEM"
    assert sent.authority == "NONE"


async def test_the_evidence_chain_answers_every_question_about_the_ask(physical: Intake) -> None:
    """§23: what did we ask, who did we ask, where, when, what came back, who authorised it."""
    await waiting_case(physical)
    request = await the_request(physical)
    await physical.deliver_reply(request.id, NON_LITERAL)
    await physical.drain(limit=20)
    await physical.deliver_reply(request.id, "YES")
    await physical.drain(limit=30)

    stored = await the_request(physical)
    assert stored.option_code and stored.option_id  # what did we ask
    assert stored.customer_channel == TOMAS_CHANNEL  # who did we ask, and where
    assert stored.provider_ref  # the provider's own reference
    assert stored.sent_at and stored.deadline  # when, and until when
    assert [row.raw_text for row in await physical.replies()] == [NON_LITERAL, "YES"]
    assert [row.parser for row in await physical.decisions()] == [ParserKind.LITERAL.value]


async def test_the_request_and_its_history_are_never_deleted(physical: Intake) -> None:
    """Expiry closes a request; it does not erase what was asked or who was asked."""
    await waiting_case(physical)
    request = await the_request(physical)
    await physical.deliver_reply(request.id, NON_LITERAL)
    await physical.drain(limit=20)
    await physical.close_window(request.id)

    await physical.drain(limit=30)

    stored = await the_request(physical)
    assert stored.id == request.id
    assert stored.option_code == request.option_code
    assert stored.customer_channel == request.customer_channel
    assert len(await physical.replies()) == 1


async def test_the_spine_tells_the_waiting_story_in_order(physical: Intake) -> None:
    """One committed sequence, and no customer detail anywhere in the envelopes."""
    await confirmed_case(physical)
    seq = await physical.latest_event_seq()

    await physical.drain(limit=40)
    request = await the_request(physical)
    await physical.deliver_reply(request.id, "YES")
    await physical.drain(limit=30)

    events = await physical.events_after(seq)
    types = [event.type for event in events]
    assert types.index(approvals.EVENT_APPROVAL_REQUESTED) < types.index(
        approvals.EVENT_APPROVAL_SENT
    )
    assert types.index(approvals.EVENT_APPROVAL_SENT) < types.index(cases.EVENT_CASE_WAITING)
    assert types.index(cases.EVENT_CASE_WAITING) < types.index(approvals.EVENT_APPROVAL_DECIDED)
    rendered = repr([event.entity_refs for event in events])
    assert TOMAS_CHANNEL not in rendered
    assert NON_LITERAL not in rendered


async def test_a_rolled_back_reply_leaves_no_decision_and_no_event(physical: Intake) -> None:
    """Either the whole consent transaction commits, or the database looks untouched."""
    from promisepatch.domain import crash

    case_id = await waiting_case(physical)
    request = await the_request(physical)
    await physical.deliver_reply(request.id, "YES")
    audit_seq = await physical.latest_audit_seq()

    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.drain(limit=20)

    assert await physical.decisions() == []
    assert await physical.replies() == []
    assert (await physical.case(case_id)).state == cases.CASE_WAITING
    assert await physical.latest_audit_seq() == audit_seq

    reply_step = next(
        step
        for step in await physical.steps(case_id)
        if step.kind == approvals.STEP_RECEIVE_CUSTOMER_REPLY
    )
    await physical.expire_lease(reply_step.id)
    await physical.drain(worker=physical.worker(identity="after-the-crash"), limit=30)

    assert len(await physical.decisions()) == 1
    assert len(await physical.replies()) == 1


# ================================================================= the canonical acceptance run


async def test_the_canonical_trace_from_confirmation_to_approval(physical: Intake) -> None:
    """The whole slice, with a worker that is stopped and replaced in the middle of it.

    Confirmation, execution, a real wait, a restart, a sentence that decides nothing, and then
    one word that does -- stopped at the boundary the consent protocol owns. What the yes has
    bought at that point is a revalidation and nothing else; where the checklist takes it from
    there is proved in ``test_recovery_revalidation``.
    """
    case_id = await confirmed_case(physical)
    adapter = FakeEffectAdapter()

    await physical.drain(worker=physical.worker(identity="worker-one", adapter=adapter), limit=40)

    assert await states(physical, case_id) == {
        A: recovery.TRACK_RECOVERED,
        B: cases.TRACK_WAITING_FOR_CUSTOMER,
        C: recovery.TRACK_ESCALATED,
        D: recovery.TRACK_ESCALATED,
        E: "UNAFFECTED",
        F: "UNAFFECTED",
    }
    assert (await physical.case(case_id)).state == cases.CASE_WAITING
    request = await the_request(physical)

    # The worker is gone. Everything outstanding is a row.
    restarted = physical.worker(identity="worker-two")
    for _ in range(3):
        await restarted.run_once()
    assert (await physical.case(case_id)).state == cases.CASE_WAITING

    await physical.deliver_reply(request.id, NON_LITERAL)
    await physical.drain(worker=restarted, limit=30)

    assert await physical.decisions() == []
    assert (await physical.case(case_id)).state == cases.CASE_WAITING
    assert (await track_of(physical, case_id, B)).state == cases.TRACK_WAITING_FOR_CUSTOMER

    await physical.deliver_reply(request.id, "YES")
    await physical.drain_until_decided(worker=restarted)

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "APPROVE"
    assert decisions[0].parser == ParserKind.LITERAL.value
    track_b = await track_of(physical, case_id, B)
    assert track_b.state == cases.TRACK_WAITING_FOR_CUSTOMER
    assert await amendments_for(physical, track_b.id) == []
    assert (await physical.case(case_id)).state == cases.CASE_REVALIDATING


async def test_nothing_unrelated_is_touched_by_the_whole_consent_run(physical: Intake) -> None:
    """E and F are never messaged, never written and never mentioned in the ledger."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    await physical.deliver_reply(request.id, "YES")
    await physical.drain(limit=30)

    tracks = {track.promise_id: track.id for track in await physical.tracks(case_id)}
    for promise_id in (E, F):
        assert await physical.effects_for(tracks[promise_id]) == []
        assert await amendments_for(physical, tracks[promise_id]) == []
        assert await physical.request_for(tracks[promise_id]) is None
    assert [row.track_id for row in await physical.requests()] == [tracks[B]]
    assert {row.request_id for row in await physical.replies()} == {request.id}


# ==================================================================== the schema's own guarantees


async def test_the_decision_row_is_the_last_word_in_the_database(physical: Intake) -> None:
    """The tables the consent model rests on, asserted through the runtime connection."""
    await waiting_case(physical)
    request = await the_request(physical)
    await physical.deliver_reply(request.id, "YES")
    await physical.drain(limit=30)

    assert len(await physical.rows_of(ApprovalDecision)) == 1
    assert len(await physical.rows_of(ApprovalRequest)) == 1
    assert len(await physical.rows_of(InboundReply)) == 1


async def test_the_operator_view_shows_the_ask_and_its_answer(physical: Intake) -> None:
    """One read service, so the CLI, the API and the demo trace describe a wait the same way."""
    from promisepatch.domain import analysis

    case_id = await waiting_case(physical)
    request = await the_request(physical)

    waiting = await analysis.read_case_status(physical.database, case_id=case_id)
    track_b = next(track for track in waiting.tracks if track.promise_id == B)
    assert waiting.state == cases.CASE_WAITING
    assert track_b.approval is not None
    assert track_b.approval.request_id == request.id
    assert track_b.approval.state == ApprovalRequestState.SENT.value
    assert track_b.approval.decided is False
    assert track_b.approval.provider_ref
    assert track_b.approval.decision is None

    await physical.deliver_reply(request.id, NON_LITERAL)
    await physical.drain(limit=20)
    await physical.deliver_reply(request.id, "YES")
    await physical.drain(limit=30)

    decided = await analysis.read_case_status(physical.database, case_id=case_id)
    answered = next(track for track in decided.tracks if track.promise_id == B)
    assert answered.approval is not None
    assert answered.approval.decision == "APPROVE"
    assert answered.approval.parser == ParserKind.LITERAL.value
    assert answered.approval.replies == 2
    assert decided.state == cases.CASE_RESOLVED
    # Tracks the exception never reached carry no approval at all.
    assert all(
        track.approval is None for track in decided.tracks if track.promise_id in (A, C, D, E, F)
    )


async def test_a_rolled_back_request_leaves_no_row_no_effect_and_no_event(
    physical: Intake,
) -> None:
    """Either the whole ask commits, or the customer was never going to be contacted.

    The dangerous half-state is an outbox row without its request: a message would go out that
    nothing on our side could match a reply to. One transaction makes that unreachable.
    """
    from promisepatch.domain import crash

    case_id = await confirmed_case(physical)
    track_a = await track_of(physical, case_id, A)
    apply_step = await physical.step_named(case_id, recovery.apply_step_key(track_a.id))
    assert apply_step is not None
    await physical.defer(apply_step.id)
    audit_seq, event_seq = await physical.latest_audit_seq(), await physical.latest_event_seq()

    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.drain(limit=10)

    assert await physical.requests() == []
    assert await physical.effects() == []
    assert await physical.latest_audit_seq() == audit_seq
    assert await physical.latest_event_seq() == event_seq
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_PENDING

    track_b = await track_of(physical, case_id, B)
    request_step = await physical.step_named(case_id, approvals.request_step_key(track_b.id))
    assert request_step is not None
    await physical.expire_lease(request_step.id)
    await physical.release(apply_step.id)
    await physical.drain(worker=physical.worker(identity="after-the-crash"), limit=40)

    assert len(await physical.requests()) == 1
    assert (await physical.case(case_id)).state == cases.CASE_WAITING
