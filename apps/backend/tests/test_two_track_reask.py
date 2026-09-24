"""Two asked promises, and only one of them goes stale (ADR-0023).

§14.2 lists what one revalidation round does per track: a yes that is still valid goes on to be
applied, and a yes the world moved under goes stale and is re-planned -- "case returns to PLANNED
for that track only". Until ADR-0023 the build read that as the whole case, and a case with two
asked promises stranded one of them whichever revalidation the worker happened to claim first:

* **The stale one first.** Its re-plan was enqueued; the other's ``PROCEED``, seeing no other
  *revalidation* outstanding, moved the case to ``RECONCILING``; the re-plan then skipped, and
  the stale promise sat ``STALE`` for ever, never re-planned, re-asked or escalated.
* **The approved one first.** Its amendment was delivered to the order system; the re-plan then
  moved the case to ``PLANNED``, where the finalize skipped -- so an order the order system had
  changed stayed ``APPLYING`` for ever, and the case could never wait on anybody again.

The world is the fixture's own Proof C: ``with_charlotte_variant`` authored in advance and C's
constraint set to ask, so the canonical report asks two customers, Tomas about B and the
Okafor-Reyes wedding about C. Every workflow row below is written by the product; the only test
levers are the world itself and the claim order of two steps the product creates together.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx2
import pytest
import pytest_asyncio
from _intake_support import RASPBERRY_ONLY, TOMAS_CHANNEL, Intake, _channel_for
from _intake_support import physical as physical
from fastapi import FastAPI

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import ApprovalRequestState
from promisepatch.api.views import cases as case_views
from promisepatch.api.views.customer import Phase
from promisepatch.config import Settings, get_settings
from promisepatch.domain import analysis, approvals, cases, customer_link, recovery, status_view
from promisepatch.fixtures.projection import TableRows, project

pytestmark = pytest.mark.integration

A, B, C, D, E, F = (
    ho.PROMISE_A,
    ho.PROMISE_B,
    ho.PROMISE_C,
    ho.PROMISE_D,
    ho.PROMISE_E,
    ho.PROMISE_F,
)
OKAFOR_CHANNEL = _channel_for(C)
"""The only identity whose answer can authorise the change to promise C."""

LINK_SECRET = "a-local-customer-link-secret"
LINK_BASE_URL = "https://bakery.test"
CHANGED = "Your order now shows this change."
RE_PLANNED = "Re-planned, and waiting for you. What was done before stays done."
NO_LONGER_APPLIES = "Your order changed after you were asked, so this question no longer applies."

ORDERS = ("stale_first", "approved_first")


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
    """Whoever holds a link, and the API they reach with it."""

    def __init__(self, client: httpx2.AsyncClient) -> None:
        self.client = client

    async def open(self, token: str) -> Any:
        return (await self.client.get(f"/api/customer/approval/{token}")).json()

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
    async with httpx2.AsyncClient(transport=transport, base_url="http://api.test") as client:
        yield Customer(client)


def link(request: Any, channel: str) -> str:
    """The token a request's message carried, minted the way the worker mints it."""
    return customer_link.mint(secret=LINK_SECRET, request_id=request.id, channel=channel)


def charlotte_variant(anchor: Any) -> tuple[TableRows, ...]:
    """The rows :func:`hollow_oak.with_charlotte_variant` adds, projected, and nothing else.

    Authored in advance, as every recipe version is: a strawberry Charlotte and the policy entry
    naming it. Projected with the deployment's own projector, so no column of it is typed here.
    """

    def key(row: Any) -> str:
        return json.dumps(dict(row), sort_keys=True, default=str)

    base = ho.hollow_oak(anchor)
    before = {
        table.table: {key(row) for row in table.rows} for table in project(base, mirrored_at=anchor)
    }
    return tuple(
        TableRows(
            table=table.table,
            rows=tuple(row for row in table.rows if key(row) not in before[table.table]),
        )
        for table in project(ho.with_charlotte_variant(base), mirrored_at=anchor)
    )


@dataclass(frozen=True, slots=True)
class Round:
    """A case after one revalidation round in which B was answered and C's yes went stale."""

    case_id: UUID
    b: Any
    c: Any
    b_request: Any
    c_request: Any


async def asked_twice(intake: Intake) -> tuple[UUID, Any, Any]:
    """Proof C's world, the canonical report, one confirmation: B and C both asked."""
    await intake.author(charlotte_variant(await intake.fixture_anchor()))
    await intake.set_constraint_kind(ho.CONSTRAINT_C_NOSUB, "ASK_BEFORE_VISIBLE_CHANGE")
    opened = await intake.report()
    await intake.drain()
    await intake.answer(opened.case_id, RASPBERRY_ONLY)
    await intake.drain()
    confirmed = await intake.confirm(opened.case_id)
    await intake.drain(limit=80)

    b = await intake.track(opened.case_id, B)
    c = await intake.track(opened.case_id, C)
    assert set(confirmed.awaiting_approval) == {b.id, c.id}
    assert (b.classification, c.classification) == ("APPROVAL_REQUIRED", "APPROVAL_REQUIRED")
    assert (b.state, c.state) == (cases.TRACK_WAITING_FOR_CUSTOMER,) * 2
    assert (await intake.case(opened.case_id)).state == cases.CASE_WAITING
    return opened.case_id, b, c


async def one_round(intake: Intake, order: str, *, b_answer: str = "YES") -> Round:
    """Both customers answer, C's order moves, and the two revalidations run in ``order``.

    B's customer says ``b_answer``; C's says yes, to a world that then moves under it.

    Since ADR-0025 a yes is checked as soon as it arrives, so B's yes opens the round and C's
    joins it; a no opens nothing, and C's answer opens the round for both. B's checklist is held
    only until C's reply has been read, which is what puts both answers in one round -- the shape
    this module is about. From there the two revalidations run in ``order``: deferring one until
    the other has run is the only lever, and each order is one the worker can take on its own.
    """
    case_id, b, c = await asked_twice(intake)
    b_request = await intake.request_for(b.id)
    c_request = await intake.request_for(c.id)

    await intake.deliver_reply(b_request.id, b_answer, sender=TOMAS_CHANNEL)
    runner = intake.worker()
    for _ in range(10):
        if len(await intake.decisions()) == 1:
            break
        await runner.run_once()
    held = await intake.step_named(case_id, cases.revalidate_step_key(b.id))
    if b_answer == "YES":
        assert (await intake.case(case_id)).state == cases.CASE_REVALIDATING
        assert held is not None and held.state == "PENDING"
        await intake.defer(held.id)
    else:
        assert (await intake.case(case_id)).state == cases.CASE_WAITING
        assert held is None
    await intake.bump_order_version(ho.ORDER_C)
    await intake.deliver_reply(c_request.id, "YES", sender=OKAFOR_CHANNEL)
    for _ in range(10):
        if len(await intake.decisions()) == 2:
            break
        await runner.run_once()
    assert (await intake.case(case_id)).state == cases.CASE_REVALIDATING
    if held is not None:
        await intake.release(held.id)

    first, second = (c, b) if order == "stale_first" else (b, c)
    later = await intake.step_named(case_id, cases.revalidate_step_key(second.id))
    await intake.defer(later.id)
    for _ in range(10):
        step = await intake.step_named(case_id, cases.revalidate_step_key(first.id))
        if step.state == "DONE":
            break
        await runner.run_once()
    await intake.requeue(later.id)
    await intake.drain(limit=80)
    return Round(
        case_id=case_id,
        b=await intake.track(case_id, B),
        c=await intake.track(case_id, C),
        b_request=b_request,
        c_request=c_request,
    )


@dataclass(frozen=True, slots=True)
class ReAsk:
    """The round, and C asked again under the plan a person approved and confirmed."""

    done: Round
    new: Any
    confirmed: recovery.ConfirmationResult
    plan_id: str


async def re_asked(intake: Intake, order: str = "stale_first") -> ReAsk:
    """The same round, then a person approves and confirms C's re-plan and the worker drains."""
    done = await one_round(intake, order)
    plan_id = await intake.plan_id(done.case_id)
    confirmed = await intake.confirm(done.case_id, plan_id=plan_id)
    await intake.drain(limit=80)
    requests = await intake.requests()
    (new,) = [row for row in requests if row.id not in {done.b_request.id, done.c_request.id}]
    return ReAsk(done=done, new=new, confirmed=confirmed, plan_id=plan_id)


async def amendments(intake: Intake, track_id: UUID) -> list[Any]:
    return [
        row for row in await intake.effects_for(track_id) if row.kind == recovery.EFFECT_ORDER_AMEND
    ]


async def asks(intake: Intake, track_id: UUID) -> list[Any]:
    return [
        row
        for row in await intake.effects_for(track_id)
        if row.kind == approvals.EFFECT_MESSAGE_SEND
        and str(row.idempotency_key).startswith("pp:approval:")
    ]


def request_row(rows: list[Any], request_id: UUID) -> tuple[Any, ...]:
    row = next(row for row in rows if row.id == request_id)
    return (row.id, row.track_id, row.state, row.decided, row.deadline, row.option_id)


# =============================================================== the round, in either order


@pytest.mark.parametrize("order", ORDERS)
async def test_either_order_applies_the_approved_promise_and_re_plans_the_stale_one(
    physical: Intake, order: str
) -> None:
    """The exact defect, in both claim orders: nothing is stranded, and nothing else moves.

    Before ADR-0023, ``stale_first`` ended ``RECONCILING`` with C ``STALE`` and its re-plan
    skipped, and ``approved_first`` ended ``PLANNED`` with B ``APPLYING`` and its finalize
    skipped after the amendment had been delivered.
    """
    done = await one_round(physical, order)
    case_id = done.case_id

    # B: its own yes, revalidated as its own request, applied once and settled.
    assert done.b.state == recovery.TRACK_RECOVERED
    assert done.b.approval_request_id == done.b_request.id
    checked = await physical.step_named(case_id, cases.revalidate_step_key(done.b.id))
    assert checked.result["outcome"] == "PROCEED"
    assert checked.result["request_id"] == str(done.b_request.id)
    finalized = await physical.step_named(case_id, recovery.finalize_step_key(done.b.id))
    assert (finalized.state, finalized.result["outcome"]) == ("DONE", "RECOVERED")
    (amended,) = await amendments(physical, done.b.id)
    assert amended.state == "DELIVERED"

    # C: refused as stale, re-planned for itself only, its request superseded, nothing applied.
    refused = await physical.step_named(case_id, cases.revalidate_step_key(done.c.id))
    assert refused.result["outcome"] == "STALE"
    replanned = await physical.step_named(case_id, analysis.replan_step_key(done.c.id))
    assert (replanned.state, replanned.result["outcome"]) == ("DONE", "REPLANNED")
    assert (done.c.state, done.c.approval_request_id) == (analysis.TRACK_PENDING, None)
    superseded = await physical.request_for(done.c.id)
    assert superseded.state == ApprovalRequestState.SUPERSEDED.value
    assert await amendments(physical, done.c.id) == []

    # The case: back at PLANNED for C's sake, counting §14.1's ten minutes, nothing stranded.
    assert (await physical.case(case_id)).state == cases.CASE_PLANNED
    assert await physical.outstanding(case_id) == []
    armed = [
        row
        for row in await physical.timers()
        if row.kind == cases.TIMER_PLAN_AUTO_ESCALATION
        and row.subject_id == str(case_id)
        and row.fired_at is None
    ]
    assert len(armed) == 1

    # And it says so without claiming nothing happened: B's order has changed.
    status = await analysis.read_case_status(physical.database, case_id=case_id)
    assert status_view.project(status).sentence == RE_PLANNED
    async with physical.database.connect() as connection:
        listed = await case_views.summaries(connection, limit=10)
    (row,) = [row for row in listed.cases if row.case_id == case_id]
    assert (row.headline, row.sentence) == ("PLANNED", RE_PLANNED)


# ============================================================ only the stale one is asked again


async def test_only_the_stale_promise_is_asked_again_and_the_case_waits_on_it(
    physical: Intake,
) -> None:
    """C gets a new episode under the new plan; B is not asked, superseded or replayed."""
    asked_again = await re_asked(physical)
    done, new = asked_again.done, asked_again.new
    case_id = done.case_id
    assert asked_again.confirmed.awaiting_approval == (done.c.id,)
    assert asked_again.confirmed.applying == ()

    c = await physical.track(case_id, C)
    assert new.track_id == c.id
    assert new.id == approvals.request_id_for(c.id, new.option_id, asked_again.plan_id)
    assert (c.state, c.approval_request_id) == (cases.TRACK_WAITING_FOR_CUSTOMER, new.id)
    assert (new.state, new.decided) == (ApprovalRequestState.SENT.value, False)
    assert approvals.ask_scope(new) == new.id
    step = await physical.step_named(case_id, approvals.request_step_key(c.id, asked_again.plan_id))
    assert (step.state, step.result["request_id"]) == ("DONE", str(new.id))
    # One plan-scoped ask on C, and none on B: B's only request step is its first.
    for track_id in (done.b.id, c.id):
        assert (
            await physical.step_named(case_id, approvals.request_step_key(track_id))
        ).state == "DONE"
    assert (
        await physical.step_named(
            case_id, approvals.request_step_key(done.b.id, asked_again.plan_id)
        )
        is None
    )

    b = await physical.track(case_id, B)
    assert (b.state, b.approval_request_id) == (recovery.TRACK_RECOVERED, done.b_request.id)
    assert len(await asks(physical, b.id)) == 1
    assert len(await asks(physical, c.id)) == 2
    assert [row.request_id for row in await physical.decisions()] == [
        done.b_request.id,
        done.c_request.id,
    ]
    rows = await physical.requests()
    assert request_row(rows, done.b_request.id) == (
        done.b_request.id,
        b.id,
        ApprovalRequestState.ANSWERED.value,
        True,
        done.b_request.deadline,
        done.b_request.option_id,
    )
    assert (await physical.case(case_id)).state == cases.CASE_WAITING
    assert await physical.outstanding(case_id) == []


# ====================================================== neither answer authorises the other


async def test_neither_customer_s_answer_authorises_the_other_promise(
    physical: Intake, customer: Customer
) -> None:
    """B's link, C's old link and B's own channel all fail to answer C's new question."""
    asked_again = await re_asked(physical)
    done, new = asked_again.done, asked_again.new
    case_id = done.case_id
    b_link = link(done.b_request, TOMAS_CHANNEL)
    old_c_link = link(done.c_request, OKAFOR_CHANNEL)

    await customer.press(b_link, "APPROVE")
    await customer.press(b_link, "DECLINE")
    await customer.press(old_c_link, "APPROVE")
    await physical.deliver_reply(new.id, "YES", sender=TOMAS_CHANNEL)
    await physical.drain(limit=40)

    assert [row.request_id for row in await physical.decisions()] == [
        done.b_request.id,
        done.c_request.id,
    ]
    c = await physical.track(case_id, C)
    assert (c.state, c.approval_request_id) == (cases.TRACK_WAITING_FOR_CUSTOMER, new.id)
    fresh = next(row for row in await physical.requests() if row.id == new.id)
    assert (fresh.state, fresh.decided) == (ApprovalRequestState.SENT.value, False)
    assert await amendments(physical, c.id) == []
    assert len(await amendments(physical, done.b.id)) == 1
    assert (await physical.case(case_id)).state == cases.CASE_WAITING

    # Each page ends on its own question: B's on its change, C's first one on "no longer".
    b_page = await customer.open(b_link)
    assert (b_page["phase"], b_page["outcome"], b_page["awaiting_outcome"]) == (
        Phase.APPROVED,
        CHANGED,
        False,
    )
    c_page = await customer.open(old_c_link)
    assert (c_page["outcome"], c_page["awaiting_outcome"], c_page["answerable"]) == (
        NO_LONGER_APPLIES,
        False,
        False,
    )
    new_page = await customer.open(link(new, OKAFOR_CHANNEL))
    assert (new_page["phase"], new_page["answerable"]) == (Phase.OPEN, True)


# ============================================================ both settle on their own authority


async def test_both_promises_settle_on_their_own_authority(
    physical: Intake, customer: Customer
) -> None:
    """C's customer answers the new question; each amendment names its own request and yes."""
    asked_again = await re_asked(physical, "approved_first")
    done, new = asked_again.done, asked_again.new
    case_id = done.case_id

    await customer.press(link(new, OKAFOR_CHANNEL), "APPROVE")
    await physical.drain(limit=80)

    c = await physical.track(case_id, C)
    b = await physical.track(case_id, B)
    assert (b.state, c.state) == (recovery.TRACK_RECOVERED, recovery.TRACK_RECOVERED)
    checked = await physical.step_named(case_id, cases.revalidate_step_key(c.id, new.id))
    assert checked.result["outcome"] == "PROCEED"
    assert (await physical.case(case_id)).state == cases.CASE_RESOLVED
    assert await physical.outstanding(case_id) == []

    decisions = {row.request_id: row for row in await physical.decisions()}
    assert set(decisions) == {done.b_request.id, done.c_request.id, new.id}
    applied = {
        row.track_id: row
        for row in await physical.audits(case_id)
        if row.type == recovery.AUDIT_RECOVERY_APPLIED and row.track_id in {b.id, c.id}
    }
    assert applied[b.id].provenance["approval_request_id"] == str(done.b_request.id)
    assert applied[b.id].provenance["approval_decision_id"] == str(decisions[done.b_request.id].id)
    assert applied[c.id].provenance["approval_request_id"] == str(new.id)
    assert applied[c.id].provenance["approval_decision_id"] == str(decisions[new.id].id)
    (b_amended,) = await amendments(physical, b.id)
    (c_amended,) = await amendments(physical, c.id)
    assert c_amended.payload["option_id"] == str(new.option_id)
    assert b_amended.payload["option_id"] == str(done.b_request.option_id)


# ================================================================== replay asks nobody twice


async def test_replaying_the_round_and_the_re_ask_asks_nobody_twice(physical: Intake) -> None:
    """Every step of the round and the re-ask run again: no request, message or change doubles."""
    asked_again = await re_asked(physical, "approved_first")
    done, new = asked_again.done, asked_again.new
    case_id = done.case_id
    c = await physical.track(case_id, C)
    keys = (
        cases.revalidate_step_key(done.b.id),
        cases.revalidate_step_key(done.c.id),
        analysis.replan_step_key(done.c.id),
        recovery.apply_step_key(done.b.id),
        recovery.finalize_step_key(done.b.id),
        approvals.sent_step_key(c.id, new.id),
        approvals.request_step_key(c.id, asked_again.plan_id),
    )
    for key in keys:
        step = await physical.step_named(case_id, key)
        assert step is not None, key
        await physical.requeue(step.id)
    await physical.drain(limit=80)
    with pytest.raises(recovery.PlanNotConfirmableError):
        await physical.confirm(case_id, plan_id="a-plan-this-case-is-not-offering")

    assert len(await physical.requests()) == 3
    assert len(await asks(physical, done.b.id)) == 1
    assert len(await asks(physical, c.id)) == 2
    assert len(await amendments(physical, done.b.id)) == 1
    assert await amendments(physical, c.id) == []
    assert len(await physical.decisions()) == 2
    c = await physical.track(case_id, C)
    assert (c.state, c.approval_request_id) == (cases.TRACK_WAITING_FOR_CUSTOMER, new.id)
    assert (await physical.track(case_id, B)).state == recovery.TRACK_RECOVERED
    assert (await physical.case(case_id)).state == cases.CASE_WAITING


# ======================================================= an unconfirmed re-plan, and the rest


@pytest.mark.parametrize("order", ORDERS)
async def test_an_unconfirmed_re_plan_goes_to_the_owner_and_the_settled_promise_stays(
    physical: Intake, order: str
) -> None:
    """Nobody confirms C's re-plan: C goes to the owner, B stays changed, and the case finishes."""
    done = await one_round(physical, order)
    assert await physical.close_plan_window(done.case_id)
    await physical.drain(limit=40)

    c = await physical.track(done.case_id, C)
    assert c.state == recovery.TRACK_ESCALATED
    assert (await physical.track(done.case_id, B)).state == recovery.TRACK_RECOVERED
    # What stopped C is its own fact, beside -- never in place of -- why C was planned.
    status = await analysis.read_case_status(physical.database, case_id=done.case_id)
    line = next(track for track in status.tracks if track.promise_id == C)
    assert line.escalation is not None
    assert line.escalation.reason == recovery.ESCALATION_PLAN_UNCONFIRMED
    assert line.reason_detail == c.reason_detail
    assert line.reason_detail != recovery.ESCALATION_PLAN_UNCONFIRMED
    assert next(track for track in status.tracks if track.promise_id == B).escalation is None
    case = await physical.case(done.case_id)
    assert (case.state, case.needs_owner_attention) == (cases.CASE_RESOLVED, True)
    assert len(await physical.requests()) == 2
    assert await amendments(physical, c.id) == []
    assert len(await amendments(physical, done.b.id)) == 1


@pytest.mark.parametrize("order", ORDERS)
async def test_a_declined_sibling_goes_to_the_owner_and_the_stale_one_is_still_re_planned(
    physical: Intake, order: str
) -> None:
    """The round's other exit: a no settles B where it lands, and C is re-planned regardless.

    Before ADR-0023 the ``stale_first`` order stranded C here too, through the declined
    revalidation's own move to ``RECONCILING``.
    """
    done = await one_round(physical, order, b_answer="NO")

    assert done.b.state == recovery.TRACK_ESCALATED
    assert await amendments(physical, done.b.id) == []
    replanned = await physical.step_named(done.case_id, analysis.replan_step_key(done.c.id))
    assert (replanned.state, replanned.result["outcome"]) == ("DONE", "REPLANNED")
    assert (done.c.state, done.c.approval_request_id) == (analysis.TRACK_PENDING, None)
    assert (await physical.case(done.case_id)).state == cases.CASE_PLANNED
    assert await physical.outstanding(done.case_id) == []

    await physical.confirm(done.case_id)
    await physical.drain(limit=80)
    c = await physical.track(done.case_id, C)
    assert c.state == cases.TRACK_WAITING_FOR_CUSTOMER
    assert c.approval_request_id not in {done.b_request.id, done.c_request.id}
    assert (await physical.track(done.case_id, B)).state == recovery.TRACK_ESCALATED
    assert len(await asks(physical, done.b.id)) == 1
    assert (await physical.case(done.case_id)).state == cases.CASE_WAITING


async def test_nothing_unrelated_is_touched_by_the_round_or_the_re_ask(physical: Intake) -> None:
    """A stays changed, D escalated, E and F untouched, through the round and the re-ask."""
    case_id, _, _ = await asked_twice(physical)
    tracks = {track.promise_id: track for track in await physical.tracks(case_id)}
    before = {
        promise_id: (track.state, len(await physical.effects_for(track.id)))
        for promise_id, track in tracks.items()
        if promise_id in {A, D, E, F}
    }
    assert before[E] == (analysis.TRACK_UNAFFECTED, 0)
    assert before[F] == (analysis.TRACK_UNAFFECTED, 0)

    await physical.deliver_reply(
        (await physical.request_for(tracks[B].id)).id, "YES", sender=TOMAS_CHANNEL
    )
    await physical.bump_order_version(ho.ORDER_C)
    await physical.deliver_reply(
        (await physical.request_for(tracks[C].id)).id, "YES", sender=OKAFOR_CHANNEL
    )
    await physical.drain(limit=80)
    assert (await physical.case(case_id)).state == cases.CASE_PLANNED
    await physical.confirm(case_id)
    await physical.drain(limit=80)

    after = {
        promise_id: (track.state, len(await physical.effects_for(track.id)))
        for promise_id, track in {
            track.promise_id: track for track in await physical.tracks(case_id)
        }.items()
        if promise_id in {A, D, E, F}
    }
    assert after == before
    for promise_id in (E, F):
        assert await physical.request_for(tracks[promise_id].id) is None
