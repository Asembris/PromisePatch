"""The customer's own surface, against a real database, a real worker and a real HTTP hop.

``test_customer_approval`` proves the consent protocol. This proves that a *transport* was added
to it and that nothing about it moved. Every guarantee asserted here already held for a reply
arriving on a channel; the question this file answers is whether it still holds when the reply
arrives from a browser nobody authenticated.

The shape is four parts.

The first is **that a link is a door to one question**. It opens the request it was minted for,
shows the differences that exist, and shows nothing at all when it does not match -- a forged
link, a link minted for another request and a link minted for another channel are one answer,
because telling them apart tells whoever is holding it which they have found.

The second is **that pressing a button is not deciding anything**. The press writes the record a
customer channel writes; the worker is what turns it into a decision, under the case lock, past
the sender check, the state check and the deadline check that already existed. Between those two
moments the page says it has the answer and does not say what the answer did.

The third is **that a second press changes nothing, ever**. Approve then Approve is one decision.
Decline then Approve is a decline, and it is a decline because a unique index refuses the second
record rather than because a branch remembered to.

The fourth is **that the worker's screen tells the truth about it afterwards**. Consent, decline,
expiry and a re-planned supersede each reach the worker's own vocabulary, and an approval that
later fails revalidation does not become a recovered order.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import pytest_asyncio
from _intake_support import BAKER, RASPBERRY_ONLY, TOMAS_CHANNEL, Intake
from _intake_support import physical as physical
from fastapi import FastAPI

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import ApprovalRequestState
from promisepatch.api.views import cases as case_views
from promisepatch.api.views import customer as customer_view
from promisepatch.api.views.customer import Phase
from promisepatch.config import Settings, get_settings
from promisepatch.db.models import ApprovalDecision, InboundReply
from promisepatch.domain import (
    analysis,
    approvals,
    cases,
    customer_link,
    recovery,
    status_view,
    withdrawal,
)
from promisepatch.domain.adapters import FakeEffectAdapter
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

LINK_SECRET = "a-local-customer-link-secret"
LINK_BASE_URL = "https://bakery.test"
BASE = "http://api.test"


# ------------------------------------------------------------------------------------ driving


@pytest.fixture(autouse=True)
def configured_links(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Configure the deployment to sign links, for the process as well as the app.

    The process matters because the link in the outbound message is composed by the *worker*, in
    the transaction that creates the request, where there is no request and no app to read a
    setting off. Setting it here is how a real deployment configures it.
    """
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
    api = _served(physical.database)
    transport = httpx2.ASGITransport(app=api)
    async with httpx2.AsyncClient(transport=transport, base_url=BASE) as client:
        yield Customer(client)


def _served(database: object) -> FastAPI:
    """The real application over the handle the fixture already opened, lifespan not run."""
    from promisepatch.main import create_app

    api = create_app(
        Settings(customer_link_secret=LINK_SECRET, customer_link_base_url=LINK_BASE_URL)
    )
    api.state.database = database
    return api


async def waiting_case(intake: Intake, *, adapter: FakeEffectAdapter | None = None) -> UUID:
    """The canonical case: A recovered, B waiting on Tomas, C/D escalated, E/F untouched."""
    opened = await intake.report()
    await intake.drain()
    await intake.answer(opened.case_id, RASPBERRY_ONLY)
    await intake.drain()
    await intake.confirm(opened.case_id)
    await intake.drain(worker=intake.worker(adapter=adapter), limit=40)
    return opened.case_id


async def the_request(intake: Intake) -> Any:
    requests = await intake.requests()
    assert len(requests) == 1
    return requests[0]


def link_for(request: Any, *, channel: str = TOMAS_CHANNEL) -> str:
    """The token the message carried, minted the way the worker mints it."""
    return customer_link.mint(secret=LINK_SECRET, request_id=request.id, channel=channel)


async def track_of(intake: Intake, case_id: UUID, promise_id: str) -> Any:
    row = await intake.track(case_id, promise_id)
    assert row is not None
    return row


async def workspace_line(intake: Intake, case_id: UUID, promise_id: str) -> Any:
    """One promise as the worker's own screen shows it, through the projection the screen uses.

    Read through ``status_view.project`` rather than off the track row, because the point of
    these assertions is the *vocabulary* a worker is shown -- "asked", "said yes", "changed" --
    and a test that read ``WAITING_FOR_CUSTOMER`` would be asserting the durable state the
    screen is not allowed to print.
    """
    view = status_view.project(await analysis.read_case_status(intake.database, case_id=case_id))
    return next(row for row in view.threatened + view.untouched if row.promise_id == promise_id)


async def promise_state(intake: Intake, case_id: UUID, promise_id: str) -> Any:
    return (await workspace_line(intake, case_id, promise_id)).state


# ============================================================== the link opens one question


async def test_the_message_carries_a_link_to_the_customers_own_channel(
    physical: Intake,
) -> None:
    """Where a customer gets one at all: beside the words, on the channel they were sent to.

    Asserted on the outbox payload rather than on a screen, because that is the only place the
    link exists. Nothing stores it, no worker surface renders it and no endpoint hands one out
    -- so there is no path by which somebody who did not receive the message can be given the
    link, which is the whole of what keeps possession meaningful.
    """
    await waiting_case(physical)
    request = await the_request(physical)
    sent = [row for row in await physical.effects() if row.kind == approvals.EFFECT_MESSAGE_SEND]

    url = sent[0].payload["approval_url"]

    assert url.startswith(LINK_BASE_URL)
    token = url.partition(f"?{customer_link.PARAM}=")[2]
    possession = customer_link.verify(secret=LINK_SECRET, token=token)
    assert possession.request_id == request.id
    assert possession.channel == request.customer_channel
    # The frozen wording is untouched: the link travels beside the text, never inside it.
    assert url not in sent[0].payload["text"]


async def test_no_worker_surface_carries_the_link_the_message_took(physical: Intake) -> None:
    """The other half of possession, asserted rather than only stated.

    The test above proves the link reaches the customer's channel. This one proves it reaches
    nowhere else -- because a link a worker could read is a link a worker could open, and
    possession would stop meaning anything the moment one screen rendered it.

    What is searched is the whole workspace response as the wire carries it: every band, every
    promise, the evidence drawer, the spoken and written renderings, all of it, projected by the
    same function ``GET /api/cases/{id}`` returns and serialised the same way. ``may_speak`` is
    ``True`` on purpose -- that is the most permissive projection this product builds, so a field
    that leaked the link to anybody would leak it here.

    Neither the token nor the base URL it hangs off appears, and the token is read off the
    outbox first so that a future case which minted no link cannot make this pass by having
    nothing to find.
    """
    case_id = await waiting_case(physical)
    sent = [row for row in await physical.effects() if row.kind == approvals.EFFECT_MESSAGE_SEND]
    token = sent[0].payload["approval_url"].partition(f"?{customer_link.PARAM}=")[2]
    assert customer_link.verify(secret=LINK_SECRET, token=token)

    status = await analysis.read_case_status(physical.database, case_id=case_id)
    served = case_views.build(status, opening=None, may_speak=True).model_dump_json()

    assert token not in served
    assert LINK_BASE_URL not in served


async def test_the_link_shows_the_change_that_is_actually_proposed(
    physical: Intake, customer: Customer
) -> None:
    """Every line is a column value, and the ones with no column are absent rather than blank."""
    await waiting_case(physical)
    request = await the_request(physical)

    body = (await customer.open(link_for(request))).json()

    assert body["phase"] == Phase.OPEN
    assert body["answerable"] is True
    assert body["order_reference"] == "EXT-B"
    assert body["customer_name"] and body["customer_name"].startswith("Tomas")
    assert body["option_code"] == request.option_code
    assert body["from_product"] and body["to_product"]
    assert body["from_product"] != body["to_product"]
    assert body["affected_resource"] == "raspberries"
    assert body["substitute_resource"]
    assert body["answer_by"] is not None


async def test_the_page_states_no_price_because_nothing_holds_one(
    physical: Intake, customer: Customer
) -> None:
    """The "invent no difference that does not exist" rule, at its sharpest.

    PromisePatch models no price on an order, an order line, a recipe version or a recovery
    option. So there is no price difference to state, and a page that carried a money field --
    even an empty one -- would be inviting somebody to fill it with a number nothing computed.
    """
    await waiting_case(physical)
    request = await the_request(physical)

    body = (await customer.open(link_for(request))).json()

    assert not {key for key in body if "price" in key or "cost" in key or "total" in key}


async def test_a_forged_link_opens_nothing_and_says_nothing(customer: Customer) -> None:
    response = await customer.open("v1.forged.signature")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LINK_NOT_FOUND"


async def test_a_link_for_a_request_that_does_not_exist_is_the_closed_view(
    customer: Customer,
) -> None:
    """Validly signed, and about nothing. It closes rather than 404s: the link is ours."""
    token = customer_link.mint(secret=LINK_SECRET, request_id=uuid4(), channel=TOMAS_CHANNEL)

    body = (await customer.open(token)).json()

    assert body["phase"] == Phase.CLOSED
    assert body["answerable"] is False
    assert body["order_reference"] is None


async def test_a_link_minted_for_another_channel_reads_nothing_about_this_order(
    physical: Intake, customer: Customer
) -> None:
    """The read half of "a wrong token cannot answer another request".

    A link is signed over its channel, so this one is genuinely ours -- and it still shows
    nothing, because the channel it names is not the channel this request was sent to. An
    order's approval channel can move after a request goes out, and a link minted for the old
    address must not keep reading somebody's order back to whoever holds that address now.
    """
    await waiting_case(physical)
    request = await the_request(physical)
    stranger = link_for(request, channel="telegram:999999")

    body = (await customer.open(stranger)).json()

    assert body["phase"] == Phase.CLOSED
    assert body["order_reference"] is None
    assert body["from_product"] is None


# ================================================================ pressing a button records


async def test_a_press_records_a_reply_and_decides_nothing_yet(
    physical: Intake, customer: Customer
) -> None:
    """The moment that matters: durable, and not yet authority.

    The worker has not run, so there is no decision -- and the page says exactly that. A
    transport that reported "approved" here would be reporting the one thing in this system
    that may never be reported before the protocol writes it.
    """
    await waiting_case(physical)
    request = await the_request(physical)

    response = await customer.press(link_for(request), "APPROVE")

    assert response.status_code == 202
    assert response.json()["phase"] == Phase.RECEIVED
    assert await physical.decisions() == []


async def test_a_pressed_approval_becomes_one_literal_yes(
    physical: Intake, customer: Customer
) -> None:
    """What the button actually sends: the word the message invited, not a sentence."""
    await waiting_case(physical)
    request = await the_request(physical)

    await customer.press(link_for(request), "APPROVE")
    await physical.drain_until_decided()

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "APPROVE"
    assert decisions[0].parser == "LITERAL"
    assert decisions[0].sender_identity == TOMAS_CHANNEL
    assert decisions[0].raw_text.casefold() == "yes"


async def test_a_pressed_decline_becomes_one_literal_no(
    physical: Intake, customer: Customer
) -> None:
    await waiting_case(physical)
    request = await the_request(physical)

    await customer.press(link_for(request), "DECLINE")
    await physical.drain_until_decided()

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "DECLINE"
    assert decisions[0].parser == "LITERAL"


async def test_the_page_reports_the_decision_only_once_the_protocol_wrote_it(
    physical: Intake, customer: Customer
) -> None:
    await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)

    await customer.press(token, "APPROVE")
    assert (await customer.open(token)).json()["phase"] == Phase.RECEIVED

    await physical.drain_until_decided()

    settled = (await customer.open(token)).json()
    assert settled["phase"] == Phase.APPROVED
    assert settled["answerable"] is False
    assert settled["answered_at"] is not None


async def test_an_open_question_and_a_stored_answer_differ_in_whether_the_page_waits(
    physical: Intake, customer: Customer
) -> None:
    """An open question waits for the customer; a stored answer waits for the bakery.

    The page re-reads only while the server says something is still going to happen, so an
    open question -- whose next move is the customer's press -- asks for no re-reading at all.
    """
    await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)

    assert (await customer.open(token)).json()["awaiting_outcome"] is False

    await customer.press(token, "APPROVE")

    stored = (await customer.open(token)).json()
    assert stored["phase"] == Phase.RECEIVED
    assert stored["awaiting_outcome"] is True
    assert stored["outcome"] is None


async def test_a_recorded_yes_says_the_order_is_checked_again_before_it_changes(
    physical: Intake, customer: Customer
) -> None:
    """The instant the page used to stop at: a decision written, nothing revalidated yet.

    A yes is not a change. Between the decision and the amendment the worker re-reads the order
    as it now stands, so this is what the page says -- and it keeps reading, because the answer
    to "did it change?" has not been decided yet. Stopping here left a customer holding "your
    answer is on the record" and nothing else, however long they looked.
    """
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)

    await customer.press(token, "APPROVE")
    await physical.drain_until_decided()

    body = (await customer.open(token)).json()
    assert body["phase"] == Phase.APPROVED
    assert body["outcome"] == (
        "Before anything changes, the bakery checks that your order can still be made this way."
    )
    assert body["awaiting_outcome"] is True
    # Still a yes and nothing more: no amendment has been made on the strength of it.
    assert await promise_state(physical, case_id, B) == status_view.PromiseState.CONSENTED


async def test_the_page_stops_waiting_once_the_approved_change_has_settled(
    physical: Intake, customer: Customer
) -> None:
    await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)

    await customer.press(token, "APPROVE")
    await physical.drain(limit=60)

    body = (await customer.open(token)).json()
    assert body["outcome"] == "Your order now shows this change."
    assert body["awaiting_outcome"] is False


async def test_a_decline_leaves_the_page_nothing_to_wait_for(
    physical: Intake, customer: Customer
) -> None:
    await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)

    await customer.press(token, "DECLINE")
    await physical.drain(limit=60)

    body = (await customer.open(token)).json()
    assert body["phase"] == Phase.DECLINED
    assert body["awaiting_outcome"] is False


# ============================================ one tab, read at every boundary as the work runs
#
# The page re-reads while ``awaiting_outcome`` is true, and never decides that for itself. Each
# test below holds one link and reads it the way an open tab does -- before the press, after it,
# after the decision, and after whatever the workflow did next -- so what is proved is the
# sequence a customer actually watches, not a page opened once everything had settled.

CHECKED_FIRST = (
    "Before anything changes, the bakery checks that your order can still be made this way."
)
CHANGED = "Your order now shows this change."
FOLLOW_UP = "The bakery will follow up with you about this order."
STOOD_DOWN = "This request was stood down. Nothing was done to your order because of it."
NO_LONGER_APPLIES = "Your order changed after you were asked, so this question no longer applies."


async def reading(customer: Customer, token: str) -> tuple[str, str | None, bool]:
    body = (await customer.open(token)).json()
    return body["phase"], body["outcome"], body["awaiting_outcome"]


async def escalation_of(intake: Intake, case_id: UUID, promise_id: str) -> str | None:
    reason: str | None = (await workspace_line(intake, case_id, promise_id)).escalation_reason
    return reason


async def request_by_id(intake: Intake, request_id: UUID) -> Any:
    return next(row for row in await intake.requests() if row.id == request_id)


async def amendments_of(intake: Intake, case_id: UUID, promise_id: str) -> list[Any]:
    track = await track_of(intake, case_id, promise_id)
    return [
        row for row in await intake.effects_for(track.id) if row.kind == recovery.EFFECT_ORDER_AMEND
    ]


async def test_one_tab_follows_a_yes_from_the_question_to_the_changed_order(
    physical: Intake, customer: Customer
) -> None:
    await waiting_case(physical)
    token = link_for(await the_request(physical))

    assert await reading(customer, token) == (Phase.OPEN, None, False)
    await customer.press(token, "APPROVE")
    assert await reading(customer, token) == (Phase.RECEIVED, None, True)
    await physical.drain_until_decided()
    assert await reading(customer, token) == (Phase.APPROVED, CHECKED_FIRST, True)
    await physical.drain(limit=60)
    assert await reading(customer, token) == (Phase.APPROVED, CHANGED, False)


async def test_one_tab_follows_a_no_to_the_bakery_s_follow_up(
    physical: Intake, customer: Customer
) -> None:
    case_id = await waiting_case(physical)
    token = link_for(await the_request(physical))

    await customer.press(token, "DECLINE")
    assert await reading(customer, token) == (Phase.RECEIVED, None, True)
    await physical.drain(limit=60)

    assert await reading(customer, token) == (Phase.DECLINED, FOLLOW_UP, False)
    assert await escalation_of(physical, case_id, B) == approvals.ESCALATION_APPROVAL_DECLINED


async def test_one_tab_stops_when_nobody_answered_before_the_window_closed(
    physical: Intake, customer: Customer
) -> None:
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)

    assert await reading(customer, token) == (Phase.OPEN, None, False)
    await physical.close_window(request.id)
    await physical.drain(limit=60)

    assert await reading(customer, token) == (Phase.EXPIRED, FOLLOW_UP, False)
    assert await escalation_of(physical, case_id, B) == approvals.ESCALATION_APPROVAL_EXPIRED


async def test_one_tab_stops_when_the_window_closed_before_a_yes_was_carried_out(
    physical: Intake, customer: Customer
) -> None:
    """Revalidation's check 7: the yes is real and on time, and the authority to act on it is not.

    The page stops re-reading and does not say the order changed; the customer's answer stays
    theirs on the page, and the worker's row says why the bakery did not act on it.
    """
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)

    await customer.press(token, "APPROVE")
    await physical.drain_until_decided()
    assert await reading(customer, token) == (Phase.APPROVED, CHECKED_FIRST, True)
    await physical.close_window(request.id)
    await physical.drain(limit=60)

    assert await reading(customer, token) == (Phase.APPROVED, FOLLOW_UP, False)
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED
    assert await escalation_of(physical, case_id, B) == approvals.ESCALATION_APPROVAL_EXPIRED
    assert await amendments_of(physical, case_id, B) == []


async def test_one_tab_stops_when_the_order_system_refuses_an_approved_change(
    physical: Intake, customer: Customer
) -> None:
    case_id = await waiting_case(physical)
    token = link_for(await the_request(physical))
    refusing = FakeEffectAdapter(
        fail_with=DeliveryOutcome(status=DeliveryStatus.TERMINAL, error="the provider refused it")
    )

    await customer.press(token, "APPROVE")
    await physical.drain_until_decided()
    assert await reading(customer, token) == (Phase.APPROVED, CHECKED_FIRST, True)
    await physical.drain(worker=physical.worker(adapter=refusing), limit=60)

    assert await reading(customer, token) == (Phase.APPROVED, FOLLOW_UP, False)
    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_ESCALATED
    assert await escalation_of(physical, case_id, B) is not None


async def test_one_tab_stops_when_the_bakery_withdraws_after_a_yes(
    physical: Intake, customer: Customer
) -> None:
    """A withdrawal is never an undo: the answer stands on the page, and nothing more is coming."""
    case_id = await waiting_case(physical)
    token = link_for(await the_request(physical))

    await customer.press(token, "APPROVE")
    await physical.drain_until_decided()
    await withdrawal.withdraw_exception(
        physical.database, case_id=case_id, command_id=uuid4(), worker_id=BAKER
    )
    await physical.drain(limit=60)

    phase, outcome, awaiting = await reading(customer, token)
    assert (phase, awaiting) == (Phase.APPROVED, False)
    assert outcome in {FOLLOW_UP, STOOD_DOWN}
    assert await amendments_of(physical, case_id, B) == []


async def test_one_tab_stops_when_the_bakery_withdraws_before_an_answer(
    physical: Intake, customer: Customer
) -> None:
    case_id = await waiting_case(physical)
    token = link_for(await the_request(physical))

    assert await reading(customer, token) == (Phase.OPEN, None, False)
    await withdrawal.withdraw_exception(
        physical.database, case_id=case_id, command_id=uuid4(), worker_id=BAKER
    )
    await physical.drain(limit=60)

    phase, outcome, awaiting = await reading(customer, token)
    assert (phase, awaiting) == (Phase.SUPERSEDED, False)
    assert outcome in {None, FOLLOW_UP, STOOD_DOWN}


async def test_a_yes_that_went_stale_is_never_told_the_next_plan_s_progress(
    physical: Intake, customer: Customer
) -> None:
    """The customer said yes to one change; the world moved; the re-plan is not theirs.

    Revalidation refuses the yes, the promise is re-planned, the old request is superseded and
    the track stops carrying it. A worker then confirms the new plan. The old link says its
    question no longer applies and stops re-reading, at every point after the supersede -- where
    it used to fall silent the moment the re-plan left the track ``PENDING``, and would have
    reported whatever the next plan did to the track as though it were this customer's change.
    """
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)

    await customer.press(token, "APPROVE")
    await physical.drain_until_decided()
    assert await reading(customer, token) == (Phase.APPROVED, CHECKED_FIRST, True)
    await physical.bump_order_version(ho.ORDER_B)
    await physical.drain(limit=40)

    superseded = await request_by_id(physical, request.id)
    assert superseded.state == ApprovalRequestState.SUPERSEDED.value
    assert await reading(customer, token) == (Phase.APPROVED, NO_LONGER_APPLIES, False)

    await physical.confirm(case_id)
    await physical.drain(limit=60)

    assert (await track_of(physical, case_id, B)).state != recovery.TRACK_STALE
    assert await reading(customer, token) == (Phase.APPROVED, NO_LONGER_APPLIES, False)
    decisions = await physical.decisions()
    assert len(decisions) == 1 and decisions[0].request_id == request.id


@pytest.mark.parametrize("track_state", ["WAITING_FOR_CUSTOMER", "APPLYING", "RECOVERED"])
def test_a_track_that_no_longer_carries_the_request_is_never_reported_as_its_change(
    track_state: str,
) -> None:
    """The rule behind the test above, for the states a later plan could move the track into.

    Today's fixture re-plans the canonical promise back to needing its customer, and the case
    does not ask again, so these are not reached live. They are what a re-plan to an automatic
    change, or a second ask, would put in front of a superseded link: none of them may speak for
    it, and none of them may keep the page re-reading.
    """
    for phase in (Phase.APPROVED, Phase.SUPERSEDED):
        assert customer_view._awaiting_outcome(phase, track_state, carried=False) is False
        outcome = customer_view._outcome(phase, track_state, carried=False)
        assert outcome != CHANGED and outcome != CHECKED_FIRST
    assert customer_view._outcome(Phase.APPROVED, track_state, carried=False) == NO_LONGER_APPLIES
    assert customer_view._outcome(Phase.SUPERSEDED, track_state, carried=False) is None


def test_a_track_still_carrying_the_request_reports_it_exactly_as_before() -> None:
    assert customer_view._outcome(Phase.APPROVED, "RECOVERED", carried=True) == CHANGED
    assert customer_view._outcome(Phase.APPROVED, "WAITING_FOR_CUSTOMER", carried=True) == (
        CHECKED_FIRST
    )
    assert customer_view._awaiting_outcome(Phase.APPROVED, "APPLYING", carried=True) is True
    assert customer_view._awaiting_outcome(Phase.RECEIVED, None, carried=False) is True


def test_a_question_withdrawn_before_an_answer_still_says_it_was_stood_down() -> None:
    """Withdrawal unbinds the track too, and the sentences about the order itself survive it."""
    assert customer_view._outcome(Phase.SUPERSEDED, "WITHDRAWN", carried=False) == STOOD_DOWN
    assert customer_view._outcome(Phase.SUPERSEDED, "ESCALATED", carried=False) == FOLLOW_UP


async def test_the_drawer_says_what_revalidation_concluded_in_words_beside_the_token(
    physical: Intake, customer: Customer
) -> None:
    """Layer 3 used to print ``PROCEED``. It prints the explanation layer's verdict, token kept."""
    case_id = await waiting_case(physical)
    await customer.press(link_for(await the_request(physical)), "APPROVE")
    await physical.drain(limit=60)

    status = await analysis.read_case_status(physical.database, case_id=case_id)
    served = case_views.build(status, opening=None, may_speak=False)
    evidence = next(row for row in served.evidence.tracks if row.promise_id == B)
    assert evidence.revalidation is not None
    assert evidence.revalidation.outcome == "PROCEED"
    assert evidence.revalidation.outcome_phrase == "the plan is still valid"
    assert "applied" not in (evidence.revalidation.outcome_phrase or "")


async def test_a_link_that_opens_nothing_waits_for_nothing(customer: Customer) -> None:
    token = customer_link.mint(secret=LINK_SECRET, request_id=uuid4(), channel=TOMAS_CHANNEL)

    body = (await customer.open(token)).json()

    assert body["phase"] == Phase.CLOSED
    assert body["awaiting_outcome"] is False


async def test_the_body_carries_no_sender_no_clock_and_no_text(customer: Customer) -> None:
    """The authority model on the wire: there is no field a caller could answer *as* somebody.

    Refused by the schema before a handler runs, so the check is structural rather than a
    validation somebody has to keep writing.
    """
    token = customer_link.mint(secret=LINK_SECRET, request_id=uuid4(), channel=TOMAS_CHANNEL)

    for body in (
        {"answer": "APPROVE", "sender": "telegram:999999"},
        {"answer": "APPROVE", "received_at": "2026-01-01T00:00:00Z"},
        {"answer": "yes"},
        {"answer": "Strawberries work"},
        {"text": "YES"},
    ):
        response = await customer.client.post(f"/api/customer/approval/{token}", json=body)
        assert response.status_code == 422, body


# =========================================================== a second press changes nothing


async def test_a_second_identical_press_is_absorbed(physical: Intake, customer: Customer) -> None:
    """Every double-click, every retry and every impatient refresh is one reply."""
    await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)

    first = await customer.press(token, "APPROVE")
    second = await customer.press(token, "APPROVE")
    await physical.drain_until_decided()

    assert first.status_code == 202
    assert second.status_code == 200
    assert len(await physical.replies()) == 1
    assert len(await physical.decisions()) == 1


async def test_a_decline_is_never_pressed_into_an_approval(
    physical: Intake, customer: Customer
) -> None:
    """The property the record's derived id exists for.

    The id is derived from the request and the channel and *not* from the answer, so the second
    press proposes a key the database already holds and writes nothing at all. A decline stands
    because a unique index refuses the second record -- not because a branch remembered to.
    """
    await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)

    await customer.press(token, "DECLINE")
    await customer.press(token, "APPROVE")
    await physical.drain_until_decided()

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "DECLINE"
    assert (await customer.open(token)).json()["phase"] == Phase.DECLINED


async def test_a_press_after_the_protocol_decided_adds_no_second_decision(
    physical: Intake, customer: Customer
) -> None:
    await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)
    await customer.press(token, "APPROVE")
    await physical.drain_until_decided()

    await customer.press(token, "DECLINE")
    await physical.drain(limit=30)

    decisions = await physical.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "APPROVE"


# ================================================================ what a link cannot authorise


async def test_a_link_for_another_channel_is_recorded_as_unauthorised_not_as_consent(
    physical: Intake, customer: Customer
) -> None:
    """The write half of "a wrong token cannot answer another request".

    It is deliberately *not* refused at the transport. Letting it through puts the attempt in
    front of the one check in PromisePatch that can refuse a reply because of who sent it, which
    turns an impersonation into an audited record and an owner's attention -- where a quiet 404
    would have turned it into nothing anybody could later see.
    """
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    stranger = link_for(request, channel="telegram:999999")

    response = await customer.press(stranger, "APPROVE")
    await physical.drain(limit=30)

    assert response.status_code == 202
    assert await physical.decisions() == []
    assert (await physical.request_for(request.track_id)).decided is False
    assert approvals.AUDIT_UNAUTHORIZED_APPROVAL in [
        row.type for row in await physical.audits(case_id)
    ]


async def test_a_worker_holding_the_endpoint_cannot_answer_for_a_customer(
    physical: Intake, customer: Customer
) -> None:
    """The endpoint's address is not a credential, and neither is any header a worker holds.

    The only thing that opens this surface is an HMAC over the request and the channel. A
    session cookie, a role, the internal service token and the MCP bearer token are all
    irrelevant here -- there is no code path on which any of them is read.
    """
    await waiting_case(physical)
    request = await the_request(physical)

    for forged in (
        str(request.id),
        f"v1.{request.id}.signature",
        customer_link.mint(secret="a-worker-guess", request_id=request.id, channel=TOMAS_CHANNEL),
    ):
        response = await customer.client.post(
            f"/api/customer/approval/{forged}",
            json={"answer": "APPROVE"},
            headers={
                "X-Service-Token": "an-internal-service-token",
                "Authorization": "Bearer an-mcp-bearer-token",
            },
        )
        assert response.status_code == 404, forged

    assert await physical.decisions() == []
    assert await physical.replies() == []


async def test_an_answer_after_the_window_closed_authorises_nothing(
    physical: Intake, customer: Customer
) -> None:
    """The deadline is the database's, compared under the request's own lock as it always was."""
    await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)
    await physical.close_window(request.id)

    assert (await customer.open(token)).json()["phase"] == Phase.EXPIRED
    await customer.press(token, "APPROVE")
    await physical.drain(limit=30)

    assert await physical.decisions() == []


async def test_a_superseded_request_cannot_be_answered_into_a_recovery(
    physical: Intake, customer: Customer
) -> None:
    """Their order moved after they were asked, so the question does not stand and says so."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)
    await physical.supersede_request(request.id)

    assert (await customer.open(token)).json()["phase"] == Phase.SUPERSEDED
    await customer.press(token, "APPROVE")
    await physical.drain(limit=30)

    track_b = await track_of(physical, case_id, B)
    assert await physical.decisions() == []
    assert (
        len(
            [
                row
                for row in await physical.effects_for(track_b.id)
                if row.kind == recovery.EFFECT_ORDER_AMEND
            ]
        )
        == 0
    )


async def test_an_approval_that_fails_revalidation_changes_no_order(
    physical: Intake, customer: Customer
) -> None:
    """Consent is necessary authority. It is never evidence the plan is still valid.

    The order is amended externally while the customer is deciding, so the yes is real, arrives
    in time, and is refused by check 2 before anything is written. The customer's words are kept
    exactly as they were -- a refusal is ours, and must never read as though they said no.
    """
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    track_b = await track_of(physical, case_id, B)

    await customer.press(link_for(request), "APPROVE")
    await physical.drain_until_decided()
    await physical.bump_order_version(ho.ORDER_B)
    await physical.drain(limit=40)

    step = await physical.step_named(case_id, cases.revalidate_step_key(track_b.id))
    assert step is not None
    assert step.result["deciding_check"] == 2
    assert [
        row
        for row in await physical.effects_for(track_b.id)
        if row.kind == recovery.EFFECT_ORDER_AMEND
    ] == []
    decisions = await physical.decisions()
    assert len(decisions) == 1 and decisions[0].decision == "APPROVE"


# ================================================================ the worker's screen after


async def test_the_workspace_says_asked_while_the_customer_has_not_answered(
    physical: Intake, customer: Customer
) -> None:
    case_id = await waiting_case(physical)

    assert await promise_state(physical, case_id, B) == status_view.PromiseState.REQUESTED


async def test_the_workspace_says_the_customer_said_yes_and_then_what_happened(
    physical: Intake, customer: Customer
) -> None:
    """``RECOVERED`` is reached only once the order system's own version carried the change."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await customer.press(link_for(request), "APPROVE")
    await physical.drain(limit=60)

    assert await promise_state(physical, case_id, B) == status_view.PromiseState.RECOVERED


async def test_the_workspace_says_the_customer_said_no_and_hands_it_to_the_owner(
    physical: Intake, customer: Customer
) -> None:
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await customer.press(link_for(request), "DECLINE")
    await physical.drain(limit=60)

    line = await workspace_line(physical, case_id, B)
    assert line.state == status_view.PromiseState.DECLINED
    assert line.phrase == "said no"
    assert line.owner == status_view.ActionOwner.OWNER


async def test_a_yes_stays_on_the_worker_s_row_after_the_order_system_carried_it(
    physical: Intake, customer: Customer
) -> None:
    """The answer a person gave outlives the state it moved the promise to.

    ``RECOVERED`` / "changed" is the truth about the order, and it says nothing about who
    permitted the change. A worker reading the row afterwards is still told that Tomas was asked
    and agreed, off the approval record rather than off the state beside it.
    """
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await customer.press(link_for(request), "APPROVE")
    await physical.drain(limit=60)

    line = await workspace_line(physical, case_id, B)
    assert line.state == status_view.PromiseState.RECOVERED
    assert line.consent == "the customer said yes"


async def test_a_no_is_stated_on_the_row_as_well_as_in_the_state_it_settled(
    physical: Intake, customer: Customer
) -> None:
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await customer.press(link_for(request), "DECLINE")
    await physical.drain(limit=60)

    line = await workspace_line(physical, case_id, B)
    assert line.state == status_view.PromiseState.DECLINED
    assert line.consent == "the customer said no"


async def test_a_promise_nobody_was_asked_about_claims_no_answer_on_the_same_case(
    physical: Intake, customer: Customer
) -> None:
    """The selectivity claim, applied to consent. Only one of these six was ever asked."""
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await customer.press(link_for(request), "APPROVE")
    await physical.drain(limit=60)

    for promise_id in (A, C, D, E, F):
        assert (await workspace_line(physical, case_id, promise_id)).consent is None


async def test_the_workspace_says_no_answer_by_the_deadline_when_nobody_pressed(
    physical: Intake,
) -> None:
    case_id = await waiting_case(physical)
    request = await the_request(physical)
    await physical.close_window(request.id)

    await physical.drain(limit=60)

    assert (
        await physical.request_for(request.track_id)
    ).state == ApprovalRequestState.EXPIRED.value
    assert await promise_state(physical, case_id, B) == status_view.PromiseState.EXPIRED
    # Never "said no": nobody said anything, and the row says the window closed.
    line = await workspace_line(physical, case_id, B)
    assert line.consent == "the window closed with no answer"
    assert "said" not in (line.consent or "")


async def test_the_customer_is_told_the_truthful_outcome_afterwards(
    physical: Intake, customer: Customer
) -> None:
    """The last thing the page is for: what actually happened, not what was agreed to."""
    await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)

    await customer.press(token, "APPROVE")
    await physical.drain(limit=60)

    body = (await customer.open(token)).json()
    assert body["phase"] == Phase.APPROVED
    assert body["outcome"] == "Your order now shows this change."


async def test_a_declining_customer_is_promised_a_follow_up_and_not_their_original(
    physical: Intake, customer: Customer
) -> None:
    """Declining does not un-spoil an ingredient, so nothing here says the order is unchanged."""
    await waiting_case(physical)
    request = await the_request(physical)
    token = link_for(request)

    await customer.press(token, "DECLINE")
    await physical.drain(limit=60)

    body = (await customer.open(token)).json()
    assert body["phase"] == Phase.DECLINED
    assert body["outcome"] == "The bakery will follow up with you about this order."


# =============================================================== nothing else is touched by it


async def test_the_whole_link_journey_touches_no_unreachable_promise(
    physical: Intake, customer: Customer
) -> None:
    """The product's central claim, re-asserted across the new surface.

    A customer answering on a web page must not become a reason for anything to happen to a
    promise the exception never reached.
    """
    case_id = await waiting_case(physical)
    request = await the_request(physical)

    await customer.press(link_for(request), "APPROVE")
    await physical.drain(limit=60)

    view = status_view.project(await analysis.read_case_status(physical.database, case_id=case_id))
    untouched = {row.promise_id for row in view.untouched}
    assert {E, F} <= untouched
    assert view.untouched_effect_count == 0
    for promise_id in (E, F):
        track = await track_of(physical, case_id, promise_id)
        assert await physical.effects_for(track.id) == []


async def test_one_press_is_one_reply_row_bound_to_the_request_it_named(
    physical: Intake, customer: Customer
) -> None:
    await waiting_case(physical)
    request = await the_request(physical)

    await customer.press(link_for(request), "APPROVE")
    await physical.drain_until_decided()

    replies = await physical.replies()
    assert len(replies) == 1
    assert replies[0].request_id == request.id
    assert replies[0].sender_identity == TOMAS_CHANNEL
    assert replies[0].apparent_intent is None


async def test_the_reply_and_the_decision_agree_on_the_message_that_carried_it(
    physical: Intake, customer: Customer
) -> None:
    """One provider message id, derived on the server, joining the two records."""
    await waiting_case(physical)
    request = await the_request(physical)

    await customer.press(link_for(request), "APPROVE")
    await physical.drain_until_decided()

    async with physical.database.connect() as connection:
        from sqlalchemy import select

        reply = (await connection.execute(select(InboundReply))).one()
        decision = (await connection.execute(select(ApprovalDecision))).one()

    expected = approvals.link_message_id(request.id, TOMAS_CHANNEL)
    assert reply.provider_message_id == expected
    assert decision.provider_message_id == expected


async def test_a_case_that_never_asked_anybody_exposes_no_link(physical: Intake) -> None:
    """No request, no link. The surface exists only where the protocol created a question."""
    opened = await physical.report()
    await physical.drain()

    assert await physical.requests() == []
    assert [
        row for row in await physical.effects() if row.kind == approvals.EFFECT_MESSAGE_SEND
    ] == []
    assert (await physical.case(opened.case_id)).state != cases.CASE_WAITING
