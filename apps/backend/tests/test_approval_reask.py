"""A promise re-planned after a stale yes is asked again, as a new request (ADR-0022).

§14.4: when the world moves under a customer's yes, the old request is superseded, the promise
is re-planned, and "a new request (if any) follows". Until ADR-0022 it never did. Every approval
identity was derived from the track alone, so a re-planned promise that still needed its
customer was confirmed, listed under ``awaiting_approval`` -- and never asked. The case sat at
``EXECUTING`` with nothing outstanding and nothing armed to wake it.

Against a real database, a real worker and the real HTTP hop a link answer takes, this file
proves the four things the repair has to be:

**Live.** The re-planned promise is asked again, exactly once, and the case waits on the
customer rather than on nothing. A request that goes stale in its turn is re-planned and asked
in its turn.

**New.** The second request has its own id, deadline, message and link, even though the re-plan
chose the very option the first one asked about. Nothing about it is derivable from the first.

**Separate.** The first request and its decision stay exactly as they were, as history. Neither
its link nor its decision can say anything about the second request, and only a yes to the
second request, revalidated as that request, reaches the order.

**Idempotent.** Replaying the confirmation, the request work, the delivery acknowledgement or the
re-plan, and killing the worker either side of the commit, still yields one logical request and
one message. And the re-ask is authorised by a person's approval of the new plan, never by a
service credential or by the approval the first plan spent.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import pytest_asyncio
from _intake_support import RASPBERRY_ONLY, TOMAS_CHANNEL, Intake
from _intake_support import physical as physical
from fastapi import FastAPI
from sqlalchemy import select

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import ApprovalRequestState
from promisepatch.config import Settings, get_settings
from promisepatch.db.models import PlanApproval
from promisepatch.domain import (
    analysis,
    approvals,
    cases,
    crash,
    customer_link,
    recovery,
)

pytestmark = pytest.mark.integration

A, B, C, D, E, F = (
    ho.PROMISE_A,
    ho.PROMISE_B,
    ho.PROMISE_C,
    ho.PROMISE_D,
    ho.PROMISE_E,
    ho.PROMISE_F,
)

LINK_SECRET = "a-local-customer-link-secret"
LINK_BASE_URL = "https://bakery.test"
BASE = "http://api.test"


# ------------------------------------------------------------------------------------ driving


@pytest.fixture(autouse=True)
def configured_links(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Sign links, for the worker that mints them as well as the app that opens them."""
    monkeypatch.setenv("PP_CUSTOMER_LINK_SECRET", LINK_SECRET)
    monkeypatch.setenv("PP_CUSTOMER_LINK_BASE_URL", LINK_BASE_URL)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class Customer:
    """The person holding a link, and the API they reach with it."""

    def __init__(self, client: httpx2.AsyncClient) -> None:
        self.client = client

    async def open(self, token: str) -> httpx2.Response:
        return await self.client.get(f"/api/customer/approval/{token}")

    async def press(self, token: str, answer: str) -> httpx2.Response:
        return await self.client.post(f"/api/customer/approval/{token}", json={"answer": answer})


@pytest_asyncio.fixture
async def customer(physical: Intake) -> AsyncIterator[Customer]:
    from promisepatch.main import create_app

    api: FastAPI = create_app(
        Settings(customer_link_secret=LINK_SECRET, customer_link_base_url=LINK_BASE_URL)
    )
    api.state.database = physical.database
    transport = httpx2.ASGITransport(app=api)
    async with httpx2.AsyncClient(transport=transport, base_url=BASE) as client:
        yield Customer(client)


def link_for(request: Any) -> str:
    """The token a request's message carried, minted the way the worker mints it."""
    return customer_link.mint(secret=LINK_SECRET, request_id=request.id, channel=TOMAS_CHANNEL)


async def track_b(intake: Intake, case_id: UUID) -> Any:
    row = await intake.track(case_id, B)
    assert row is not None
    return row


async def states(intake: Intake, case_id: UUID) -> dict[str, str]:
    return {track.promise_id: track.state for track in await intake.tracks(case_id)}


async def asks(intake: Intake) -> list[Any]:
    """Every approval message ever queued, by the §12.3 key shape only an ask carries."""
    return [
        row
        for row in await intake.effects()
        if row.kind == approvals.EFFECT_MESSAGE_SEND
        and str(row.idempotency_key).startswith("pp:approval:")
    ]


async def amendments(intake: Intake, track_id: UUID) -> list[Any]:
    return [
        row for row in await intake.effects_for(track_id) if row.kind == recovery.EFFECT_ORDER_AMEND
    ]


async def drain_until_answered(intake: Intake, request_id: UUID, *, limit: int = 30) -> None:
    """Run cycles until *this* request has a decision, and stop on that boundary.

    ``Intake.drain_until_decided`` stops at the first decision anywhere, and a re-asked case
    already has one -- the first request's. The instant between the second yes and its
    revalidation is the one a second stale test has to move the world in.
    """
    runner = intake.worker()
    for _ in range(limit):
        if any(row.request_id == request_id for row in await intake.decisions()):
            return
        if not await runner.run_once():
            return


async def re_planned_case(intake: Intake) -> tuple[UUID, Any]:
    """The canonical case, B's customer says a literal yes, and then the order moves.

    Revalidation refuses the yes at check 2, the re-plan supersedes the request and unbinds the
    track, and the case is back at ``PLANNED`` with B needing its customer again.
    """
    opened = await intake.report()
    await intake.drain()
    await intake.answer(opened.case_id, RASPBERRY_ONLY)
    await intake.drain()
    await intake.confirm(opened.case_id)
    await intake.drain(limit=40)
    (first,) = await intake.requests()
    await intake.deliver_reply(first.id, "YES")
    await intake.drain_until_decided()
    await intake.bump_order_version(ho.ORDER_B)
    await intake.drain(limit=40)

    assert (await intake.case(opened.case_id)).state == cases.CASE_PLANNED
    track = await track_b(intake, opened.case_id)
    assert (track.state, track.approval_request_id) == (analysis.TRACK_PENDING, None)
    return opened.case_id, first


async def re_asked_case(intake: Intake) -> tuple[UUID, Any, Any, str]:
    """The same case, with the re-plan confirmed by a person and the worker drained."""
    case_id, first = await re_planned_case(intake)
    plan_id = await intake.plan_id(case_id)
    await intake.confirm(case_id, plan_id=plan_id)
    await intake.drain(limit=60)
    requests = await intake.requests()
    assert len(requests) == 2
    second = next(row for row in requests if row.id != first.id)
    return case_id, first, second, plan_id


# ============================================================================ the defect, live


async def test_a_promise_re_planned_after_a_stale_yes_is_asked_again(physical: Intake) -> None:
    """The exact sequence that used to stop: re-confirmed, listed as awaiting, never asked.

    Before ADR-0022 the confirmation reported B under ``awaiting_approval`` and enqueued
    ``approval:<track>`` -- a key the first ask had already settled -- so the index declined it,
    no step ran, and the case stood at ``EXECUTING`` with B ``PENDING`` and nothing outstanding.
    """
    case_id, first = await re_planned_case(physical)
    track = await track_b(physical, case_id)
    plan_id = await physical.plan_id(case_id)

    confirmed = await physical.confirm(case_id, plan_id=plan_id)
    assert confirmed.awaiting_approval == (track.id,)
    await physical.drain(limit=60)

    requests = await physical.requests()
    assert len(requests) == 2
    second = next(row for row in requests if row.id != first.id)
    track = await track_b(physical, case_id)
    assert track.state == cases.TRACK_WAITING_FOR_CUSTOMER
    assert track.approval_request_id == second.id
    assert second.state == ApprovalRequestState.SENT.value
    assert second.decided is False
    assert (await physical.case(case_id)).state == cases.CASE_WAITING
    assert await physical.outstanding(case_id) == []

    step = await physical.step_named(case_id, approvals.request_step_key(track.id, plan_id))
    assert step is not None
    assert step.state == "DONE"
    assert step.result["request_id"] == str(second.id)


async def test_the_second_request_has_its_own_identity_deadline_message_and_link(
    physical: Intake,
) -> None:
    """A new episode, even for the same option: nothing about it is derivable from the first."""
    case_id, first, second, plan_id = await re_asked_case(physical)
    track = await track_b(physical, case_id)

    # The precondition for the collision: the re-plan re-chose the option first asked about.
    assert second.option_id == first.option_id == track.chosen_option_id
    assert second.id != first.id
    assert second.id == approvals.request_id_for(track.id, second.option_id, plan_id)
    assert first.id == approvals.request_id_for(track.id, first.option_id)
    assert second.captured_order_version == first.captured_order_version + 1

    timers = [row for row in await physical.timers() if row.subject_id == str(second.id)]
    assert [row.kind for row in timers] == [approvals.TIMER_APPROVAL_DEADLINE]

    by_key = {row.idempotency_key: row for row in await asks(physical)}
    assert set(by_key) == {
        approvals.message_idempotency_key(first.id),
        approvals.message_idempotency_key(second.id),
    }
    message = by_key[approvals.message_idempotency_key(second.id)]
    assert message.state == "DELIVERED"
    assert message.payload["request_id"] == str(second.id)
    token = message.payload["approval_url"].partition(f"?{customer_link.PARAM}=")[2]
    assert customer_link.verify(secret=LINK_SECRET, token=token).request_id == second.id
    old = by_key[approvals.message_idempotency_key(first.id)].payload["approval_url"]
    assert message.payload["approval_url"] != old


async def test_the_first_request_and_its_decision_stay_exactly_as_they_were(
    physical: Intake,
) -> None:
    """History, not working state: superseded, answered, and keeping the per-track identity."""
    case_id, first, second, _ = await re_asked_case(physical)
    track = await track_b(physical, case_id)

    kept = next(row for row in await physical.requests() if row.id == first.id)
    assert kept.state == ApprovalRequestState.SUPERSEDED.value
    assert kept.decided is True
    assert kept.captured_order_version == first.captured_order_version
    assert kept.captured_fingerprint == first.captured_fingerprint
    decisions = await physical.decisions()
    assert [(row.request_id, row.decision, row.raw_text) for row in decisions] == [
        (first.id, "APPROVE", "YES")
    ]
    # The first ask's steps are the per-track ones it always had, settled once, untouched.
    first_ask = await physical.step_named(case_id, approvals.request_step_key(track.id))
    assert first_ask is not None
    assert first_ask.result["request_id"] == str(first.id)
    assert approvals.ask_scope(kept) is None
    assert approvals.ask_scope(second) == second.id


# ======================================================================= the old link and yes


async def test_the_old_link_answers_nothing_about_the_new_request(
    physical: Intake, customer: Customer
) -> None:
    """Possession of the first link is possession of the first question, and nothing more."""
    case_id, first, second, _ = await re_asked_case(physical)
    old = link_for(first)

    for answer in ("APPROVE", "DECLINE"):
        await customer.press(old, answer)
    await physical.deliver_reply(first.id, "YES")
    await physical.drain(limit=40)

    body = (await customer.open(old)).json()
    assert body["answerable"] is False
    assert [row.request_id for row in await physical.decisions()] == [first.id]
    now = next(row for row in await physical.requests() if row.id == second.id)
    assert (now.state, now.decided) == (ApprovalRequestState.SENT.value, False)
    track = await track_b(physical, case_id)
    assert (track.state, track.approval_request_id) == (
        cases.TRACK_WAITING_FOR_CUSTOMER,
        second.id,
    )
    assert (await physical.case(case_id)).state == cases.CASE_WAITING
    assert not [row for row in await physical.replies() if row.request_id == second.id]
    assert await amendments(physical, track.id) == []


async def test_the_old_yes_never_carries_into_the_new_request(physical: Intake) -> None:
    """The first request was approved. Let the second one lapse: nothing may be applied.

    Had the first decision carried, the lapse would still have found an ``APPROVE`` and a
    revalidation to run. It finds neither, and the promise goes to the owner unchanged.
    """
    case_id, _, second, _ = await re_asked_case(physical)
    track = await track_b(physical, case_id)
    assert (await physical.case(case_id)).state == cases.CASE_WAITING
    assert (
        await physical.step_named(case_id, cases.revalidate_step_key(track.id, second.id)) is None
    )

    await physical.close_window(second.id)
    await physical.drain(limit=40)

    lapsed = next(row for row in await physical.requests() if row.id == second.id)
    assert (lapsed.state, lapsed.decided) == (ApprovalRequestState.EXPIRED.value, False)
    assert (await track_b(physical, case_id)).state == recovery.TRACK_ESCALATED
    assert await amendments(physical, track.id) == []
    assert len(await physical.decisions()) == 1


async def test_a_yes_to_the_new_request_is_revalidated_and_applied_as_that_request(
    physical: Intake, customer: Customer
) -> None:
    """The loop closes on the second request's own authority, and its provenance names it."""
    case_id, first, second, _ = await re_asked_case(physical)
    track = await track_b(physical, case_id)

    await customer.press(link_for(second), "APPROVE")
    await physical.drain(limit=60)

    step = await physical.step_named(case_id, cases.revalidate_step_key(track.id, second.id))
    assert step is not None
    assert step.result["outcome"] == "PROCEED"
    assert (await track_b(physical, case_id)).state == recovery.TRACK_RECOVERED
    assert (await physical.case(case_id)).state == cases.CASE_RESOLVED
    (amendment,) = await amendments(physical, track.id)
    assert amendment.payload["option_id"] == str(second.option_id)

    decisions = {row.request_id: row for row in await physical.decisions()}
    assert set(decisions) == {first.id, second.id}
    (applied,) = [
        row
        for row in await physical.audits(case_id)
        if row.type == recovery.AUDIT_RECOVERY_APPLIED and row.track_id == track.id
    ]
    assert applied.authority == "HUMAN_APPROVAL"
    assert applied.provenance["approval_request_id"] == str(second.id)
    assert applied.provenance["approval_decision_id"] == str(decisions[second.id].id)


# =================================================================== replay, crash, and stale


async def test_replaying_the_confirmation_and_the_re_ask_work_asks_no_third_time(
    physical: Intake,
) -> None:
    """Every piece of the second episode run again: one request, one message, no decision."""
    case_id, _ = await re_planned_case(physical)
    track = await track_b(physical, case_id)
    plan_id = await physical.plan_id(case_id)
    approval = await physical.approve(case_id, plan_id=plan_id)
    command_id = uuid4()

    async def confirm(command: UUID) -> recovery.ConfirmationResult:
        return await recovery.confirm_plan(
            physical.database,
            case_id=case_id,
            command_id=command,
            approval_id=approval.id,
            plan_id=plan_id,
        )

    assert (await confirm(command_id)).created is True
    await physical.drain(limit=60)

    assert (await confirm(command_id)).created is False
    with pytest.raises(recovery.PlanNotConfirmableError):
        await confirm(uuid4())
    second = (await track_b(physical, case_id)).approval_request_id
    assert second is not None
    for key in (
        approvals.request_step_key(track.id, plan_id),
        approvals.sent_step_key(track.id, second),
        analysis.replan_step_key(track.id),
    ):
        step = await physical.step_named(case_id, key)
        assert step is not None, key
        await physical.requeue(step.id)
    await physical.drain(limit=60)

    assert len(await physical.requests()) == 2
    assert len(await asks(physical)) == 2
    assert len(await physical.decisions()) == 1
    track = await track_b(physical, case_id)
    assert (track.state, track.approval_request_id) == (cases.TRACK_WAITING_FOR_CUSTOMER, second)
    assert (await physical.case(case_id)).state == cases.CASE_WAITING


async def test_a_worker_that_dies_before_the_re_ask_commits_leaves_nothing_behind(
    physical: Intake,
) -> None:
    """Before the boundary no second request and no message; the next worker asks once."""
    case_id, _ = await re_planned_case(physical)
    track = await track_b(physical, case_id)
    plan_id = await physical.plan_id(case_id)
    await physical.confirm(case_id, plan_id=plan_id)

    with crash.arm(crash.BEFORE_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.worker(identity="worker-that-dies").run_once()

    assert len(await physical.requests()) == 1
    assert len(await asks(physical)) == 1
    step = await physical.step_named(case_id, approvals.request_step_key(track.id, plan_id))
    assert step is not None
    await physical.expire_lease(step.id)
    await physical.drain(worker=physical.worker(identity="after-the-crash"), limit=60)

    assert len(await physical.requests()) == 2
    assert len(await asks(physical)) == 2
    assert (await track_b(physical, case_id)).state == cases.TRACK_WAITING_FOR_CUSTOMER


async def test_a_worker_that_dies_after_the_re_ask_commits_asks_exactly_once(
    physical: Intake,
) -> None:
    """After the boundary the request and its message are durable, and nobody asks twice."""
    case_id, _ = await re_planned_case(physical)
    track = await track_b(physical, case_id)
    plan_id = await physical.plan_id(case_id)
    await physical.confirm(case_id, plan_id=plan_id)

    with crash.arm(crash.AFTER_TRANSITION_COMMIT), pytest.raises(crash.WorkerDied):
        await physical.worker(identity="worker-that-dies").run_once()

    assert len(await physical.requests()) == 2
    step = await physical.step_named(case_id, approvals.request_step_key(track.id, plan_id))
    assert step is not None and step.state == "DONE"
    await physical.drain(worker=physical.worker(identity="after-the-crash"), limit=60)

    assert len(await physical.requests()) == 2
    assert len(await asks(physical)) == 2
    assert (await track_b(physical, case_id)).state == cases.TRACK_WAITING_FOR_CUSTOMER


async def test_a_re_asked_promise_that_goes_stale_again_is_re_planned_and_asked_again(
    physical: Intake,
) -> None:
    """The chain is live at every link, not only the first: a third request for a third world."""
    case_id, first, second, _ = await re_asked_case(physical)
    track = await track_b(physical, case_id)
    await physical.deliver_reply(second.id, "YES")
    await drain_until_answered(physical, second.id)
    decisions = await physical.decisions()
    assert {row.request_id for row in decisions} == {first.id, second.id}
    await physical.bump_order_version(ho.ORDER_B)
    await physical.drain(limit=40)

    refused = await physical.step_named(case_id, cases.revalidate_step_key(track.id, second.id))
    assert refused is not None and refused.result["outcome"] == "STALE"
    replan = await physical.step_named(case_id, analysis.replan_step_key(track.id, second.id))
    assert replan is not None and replan.result["outcome"] == "REPLANNED"
    assert (await physical.case(case_id)).state == cases.CASE_PLANNED

    await physical.confirm(case_id)
    await physical.drain(limit=60)

    requests = {row.id: row for row in await physical.requests()}
    assert len(requests) == 3
    third = next(row for key, row in requests.items() if key not in {first.id, second.id})
    assert requests[second.id].state == ApprovalRequestState.SUPERSEDED.value
    assert third.captured_order_version == second.captured_order_version + 1
    assert (await track_b(physical, case_id)).approval_request_id == third.id
    assert len(await physical.decisions()) == 2
    assert await amendments(physical, track.id) == []


# ============================================================== authority and selectivity


async def test_a_re_ask_is_authorised_by_a_person_approving_the_new_plan(
    physical: Intake,
) -> None:
    """A service credential cannot open the second episode, and neither can the first approval."""
    case_id, _ = await re_planned_case(physical)
    track = await track_b(physical, case_id)
    plan_id = await physical.plan_id(case_id)
    async with physical.database.connect() as connection:
        spent = (
            await connection.execute(select(PlanApproval).where(PlanApproval.case_id == case_id))
        ).one()

    with pytest.raises(recovery.HumanApprovalMissingError):
        await recovery.confirm_plan(
            physical.database,
            case_id=case_id,
            command_id=uuid4(),
            approval_id=None,
            plan_id=plan_id,
        )
    with pytest.raises(recovery.HumanApprovalMissingError):
        await recovery.confirm_plan(
            physical.database,
            case_id=case_id,
            command_id=uuid4(),
            approval_id=spent.id,
            plan_id=plan_id,
        )
    await physical.drain(limit=40)

    assert len(await physical.requests()) == 1
    assert await physical.step_named(case_id, approvals.request_step_key(track.id, plan_id)) is None
    assert (await physical.case(case_id)).state == cases.CASE_PLANNED


async def test_nothing_unrelated_is_touched_by_the_re_ask(physical: Intake) -> None:
    """Only B is asked again. A stays recovered, C and D escalated, E and F untouched."""
    case_id, _ = await re_planned_case(physical)
    before = await states(physical, case_id)
    others = {track.promise_id: track.id for track in await physical.tracks(case_id)}
    effects_before = {
        promise_id: len(await physical.effects_for(track_id))
        for promise_id, track_id in others.items()
        if promise_id != B
    }

    await physical.confirm(case_id)
    await physical.drain(limit=60)

    after = await states(physical, case_id)
    assert {key: value for key, value in after.items() if key != B} == {
        key: value for key, value in before.items() if key != B
    }
    for promise_id, count in effects_before.items():
        assert len(await physical.effects_for(others[promise_id])) == count, promise_id
    for promise_id in (E, F):
        assert await physical.effects_for(others[promise_id]) == []
        assert await physical.request_for(others[promise_id]) is None
