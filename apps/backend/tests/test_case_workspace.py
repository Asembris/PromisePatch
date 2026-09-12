"""``GET /api/cases`` and ``GET /api/cases/{id}``: the first case workspace, over real state.

The screen this feeds is the one place a person sees a whole case, so what is asserted here is
the thing a screen could most easily get wrong: saying something is done. Every value in the
response comes from the durable case, and the tests below check that by moving the case with
the real conversational surface and the real worker, and then reading the endpoint back.

Nothing here inserts a row to arrange a state. The planned case is planned because a worker
reported and answered; the recovered one is recovered because the order system said so. A
fixture that wrote a track by hand would prove the serializer works and nothing else.

The suite also covers the two questions a browser asks that a tool call does not: whether a
reload lands on the same case, and whether a second process reading the same case agrees.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import pytest_asyncio
from _intake_support import CANONICAL_REPORT, RASPBERRY_ONLY, Intake
from _intake_support import physical as physical
from _order_system_support import PROMISEPATCH_ORIGIN, Boundary, boundary, order_system_settings
from fastapi import FastAPI

from promise_graph.examples import hollow_oak as ho
from promisepatch.api.routers import auth as login_router
from promisepatch.api.schemas.cases import CaseListResponse, CaseWorkspaceResponse
from promisepatch.config import Settings
from promisepatch.main import create_app
from promisepatch.worker import Worker

pytestmark = pytest.mark.integration

AUTO, ASK = ho.PROMISE_A, ho.PROMISE_B
BLOCKED = (ho.PROMISE_C, ho.PROMISE_D)
UNTOUCHED = (ho.PROMISE_E, ho.PROMISE_F)


@pytest_asyncio.fixture
async def wired(
    physical: Intake, runtime_settings: Settings, tmp_path: Path
) -> AsyncIterator[Boundary]:
    async with boundary(
        physical.database,
        settings=runtime_settings,
        sqlite_path=tmp_path / "order-simulator.sqlite3",
    ) as running:
        yield running


@pytest_asyncio.fixture
async def browser(
    runtime_settings: Settings, physical: Intake
) -> AsyncIterator[httpx2.AsyncClient]:
    """A signed-in browser against the real application, over the seeded database.

    Deliberately not the shared ``api`` fixture: that one reseeds the demo at the suite's fixed
    March anchor, and a case about *today's* raspberry delivery cannot be opened against a
    calendar day that has not happened. This one takes the database the intake fixture left.
    """
    login_router._limiter.reset()
    async with SignedIn(create_app(order_system_settings(runtime_settings))) as client:
        yield client


async def _open_browser(app: FastAPI) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=PROMISEPATCH_ORIGIN)


class SignedIn:
    """A running application, a client for it, and a live session on that client.

    A class rather than a decorated generator because the tests need two of these at once --
    one per "browser" -- and the second one has to be opened while the first is still holding
    its own session cookies.
    """

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.client: httpx2.AsyncClient | None = None

    async def __aenter__(self) -> httpx2.AsyncClient:
        self._lifespan = self.app.router.lifespan_context(self.app)
        await self._lifespan.__aenter__()
        self.client = await _open_browser(self.app)
        response = await self.client.post(
            "/api/auth/login",
            json={"username": "maya", "password": Settings().require_demo_worker_password()},
        )
        assert response.status_code == 200, response.text
        return self.client

    async def __aexit__(self, *exc: Any) -> None:
        if self.client is not None:
            await self.client.aclose()
        await self._lifespan.__aexit__(*exc)


def worker_for(intake: Intake, wired: Boundary) -> Worker:
    return intake.worker(adapter=wired.adapter, fetch=wired.client.fetch_order)


async def workspace(client: httpx2.AsyncClient, case_id: UUID) -> CaseWorkspaceResponse:
    response = await client.get(f"/api/cases/{case_id}")
    assert response.status_code == 200, response.text
    return CaseWorkspaceResponse.model_validate(response.json())


async def planned_case(intake: Intake) -> UUID:
    opened = await intake.report(CANONICAL_REPORT)
    await intake.drain()
    await intake.answer(opened.case_id, RASPBERRY_ONLY)
    await intake.drain()
    return opened.case_id


async def settled_case(intake: Intake, wired: Boundary) -> UUID:
    """The canonical case, confirmed and carried through to its four real outcomes."""
    case_id = await planned_case(intake)
    await intake.confirm(case_id)
    for _ in range(4):
        await wired.deliver_webhooks()
        await intake.make_work_due()
        await intake.drain(worker=worker_for(intake, wired), limit=40)
    return case_id


def promise(view: CaseWorkspaceResponse, promise_id: str) -> Any:
    for band in view.authority_bands:
        for item in band.promises:
            if item.promise_id == promise_id:
                return item
    for item in view.untouched:
        if item.promise_id == promise_id:
            return item
    raise AssertionError(f"{promise_id} is on no band of this workspace")


# -------------------------------------------------------------------------------- access


async def test_an_unauthenticated_browser_cannot_read_a_case(
    runtime_settings: Settings, physical: Intake
) -> None:
    app = create_app(runtime_settings)
    async with app.router.lifespan_context(app):
        client = await _open_browser(app)
        async with client:
            response = await client.get(f"/api/cases/{uuid4()}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_a_case_id_that_names_nothing_is_a_404(browser: httpx2.AsyncClient) -> None:
    response = await browser.get(f"/api/cases/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CASE_NOT_FOUND"


# ------------------------------------------------------------------ the planned case, in bands


async def test_a_planned_case_says_nothing_has_been_done(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """Band 1 and band 2 of a case waiting for a yes. Nothing on the screen claims an outcome."""
    case_id = await planned_case(physical)

    view = await workspace(browser, case_id)

    assert view.headline == "PLANNED"
    assert "Nothing has been done yet." in view.sentence
    assert view.reported_text == CANONICAL_REPORT, "band 1 is the worker's own words"
    assert view.reported_by == "maya"
    assert view.next_action.owner == "YOU"
    assert "confirm" in view.next_action.action.lower()
    assert view.awaiting_confirmation is True
    assert view.plan_id
    assert {item.state for band in view.authority_bands for item in band.promises} == {"PLANNED"}


async def test_the_bands_carry_the_three_authorities_in_the_contract_order(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """Band 3: standing preference, then the customer, then the owner. Grouped by the backend."""
    case_id = await planned_case(physical)

    view = await workspace(browser, case_id)

    assert [band.authority for band in view.authority_bands] == [
        "STANDING_PREFERENCE",
        "CUSTOMER",
        "OWNER",
    ]
    assert [item.promise_id for item in view.authority_bands[0].promises] == [AUTO]
    assert [item.promise_id for item in view.authority_bands[1].promises] == [ASK]
    assert [item.promise_id for item in view.authority_bands[2].promises] == list(BLOCKED)
    assert all(item.reason for band in view.authority_bands for item in band.promises)
    assert [band.count for band in view.authority_bands] == [1, 1, 2]
    assert all(band.count == len(band.promises) for band in view.authority_bands)


async def test_a_case_that_has_concluded_nothing_states_no_universe_and_no_group(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """An empty authority group is never drawn, because the case has not partitioned anything.

    A backend that emitted the three contract groups unconditionally would put "Needs the
    customer: 0" on a screen beside an unanswered question, which is a partition presented as a
    conclusion. The groups arrive because the projection placed a promise in one.
    """
    opened = await physical.report(CANONICAL_REPORT)
    await physical.drain_intake(opened.case_id)

    view = await workspace(browser, opened.case_id)

    assert view.authority_bands == ()
    assert view.promise_count == 0
    assert view.threatened_count == 0
    assert view.untouched_count == 0


async def test_the_untouched_band_is_counted_by_the_backend(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """Band 4 carries the product's central claim, so the count arrives decided."""
    case_id = await planned_case(physical)

    view = await workspace(browser, case_id)

    assert view.untouched_count == 2
    assert view.promise_count == 6, "the denominator of the claim arrives from the backend"
    assert view.promise_count == view.untouched_count + view.threatened_count
    assert [item.promise_id for item in view.untouched] == list(UNTOUCHED)
    assert all(item.state == "UNTOUCHED" for item in view.untouched)
    assert all(item.phrase == "left alone" for item in view.untouched)
    assert all(item.owner == "NOBODY" for item in view.untouched)
    assert all(item.reason for item in view.untouched), "every untouched promise says why"
    assert view.untouched_effect_count == 0, "the published claim, counted by the backend"


async def test_an_open_question_appears_as_a_question_and_never_as_a_result(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """Band 1 while the case is ambiguous: the question, its options, and no outcome at all."""
    opened = await physical.report(CANONICAL_REPORT)
    await physical.drain_intake(opened.case_id)

    view = await workspace(browser, opened.case_id)

    assert view.headline == "CLARIFYING"
    assert view.question is not None
    assert view.question.question
    assert len(view.question.options) >= 2
    assert view.authority_bands == ()
    assert view.untouched_count == 0
    assert view.next_action.owner == "YOU"
    assert "answer" in view.next_action.action.lower()
    assert view.plan_id is None, "nothing is on offer while a question is open"
    assert view.awaiting_confirmation is False


# --------------------------------------------------------------- the questions, and their answers


async def test_an_open_question_is_in_the_history_with_nothing_answering_it_yet(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """The history exists from the moment the question does, and claims no answer."""
    opened = await physical.report(CANONICAL_REPORT)
    await physical.drain_intake(opened.case_id)

    view = await workspace(browser, opened.case_id)

    assert len(view.clarifications) == 1
    asked = view.clarifications[0]
    assert view.question is not None
    assert asked.clarification_id == view.question.clarification_id
    assert asked.question == view.question.question
    assert asked.ordinal == 1
    assert asked.answered is False
    assert asked.answer_text is None
    assert asked.answered_by is None
    assert asked.answered_at is None
    assert asked.resolved_option_code is None


async def test_an_answered_question_keeps_its_own_words_beside_the_answer(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """Band 1 after the answer: the question, the worker's own sentence, and who said it.

    The question is gone from ``question`` because nothing is waiting on it any more, and that
    is exactly why the history has to carry it: a screen with only the open question and the
    case's category would have to invent the sentence that was actually asked.
    """
    case_id = await planned_case(physical)

    view = await workspace(browser, case_id)

    assert view.question is None, "nothing is open once it has been answered"
    assert len(view.clarifications) == 1
    answered = view.clarifications[0]
    assert answered.answered is True
    assert answered.answer_text == RASPBERRY_ONLY, "the worker's own words, byte for byte"
    assert answered.answered_by == "maya"
    assert answered.answered_at is not None
    assert answered.asked_at <= answered.answered_at
    assert answered.question, "the question it answered is still here"
    assert len(answered.options) >= 2


async def test_a_case_nobody_has_asked_anything_has_no_history_to_show(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """No history is invented for a case that was understood first time. Empty, not absent."""
    opened = await physical.report("the deck oven is down")
    await physical.drain_intake(opened.case_id)

    view = await workspace(browser, opened.case_id)

    assert view.clarifications == ()
    assert view.question is None


# ----------------------------------------------------------- the settled case, in truthful words


async def test_the_workspace_shows_the_four_real_outcomes_after_the_work_ran(
    browser: httpx2.AsyncClient, wired: Boundary, physical: Intake
) -> None:
    """One case, four endings, each one read straight off the durable state that produced it."""
    case_id = await settled_case(physical, wired)

    view = await workspace(browser, case_id)

    assert promise(view, AUTO).state == "RECOVERED"
    assert promise(view, AUTO).phrase == "changed"
    assert promise(view, ASK).state == "REQUESTED"
    assert promise(view, ASK).phrase == "asked"
    assert [promise(view, item).state for item in BLOCKED] == ["ESCALATED", "ESCALATED"]
    assert [promise(view, item).state for item in UNTOUCHED] == ["UNTOUCHED", "UNTOUCHED"]
    assert view.untouched_count == 2
    assert view.untouched_effect_count == 0, "after the work ran, and not only before it"


async def test_a_blocked_promise_names_an_owner_a_reason_and_a_next_action(
    browser: httpx2.AsyncClient, wired: Boundary, physical: Intake
) -> None:
    """The screen must never leave a blocked promise as a colour with nobody attached to it."""
    case_id = await settled_case(physical, wired)

    view = await workspace(browser, case_id)

    for promise_id in BLOCKED:
        blocked = promise(view, promise_id)
        assert blocked.owner == "OWNER"
        assert blocked.authority == "OWNER"
        assert blocked.reason
        assert "owner" in blocked.next_action.lower()
    assert view.needs_owner_attention is True
    assert view.next_action.owner == "OWNER", "band 2 hands the case to the person who can move it"


async def test_an_effect_still_in_flight_is_not_shown_as_a_completed_one(
    browser: httpx2.AsyncClient, wired: Boundary, physical: Intake
) -> None:
    """The uncertain window on the screen: accepted by the order system, not yet observed.

    The webhook is deliberately not delivered, so PromisePatch has an acknowledgement and no
    echo. The workspace says "changing the order now", the drawer shows the delivered effect
    with its provider reference, and the word "changed" appears nowhere.
    """
    case_id = await planned_case(physical)
    await physical.confirm(case_id)
    await physical.drain(worker=worker_for(physical, wired), limit=40)

    view = await workspace(browser, case_id)

    in_flight = promise(view, AUTO)
    assert in_flight.state == "APPLYING"
    assert in_flight.phrase == "changing the order now"
    assert in_flight.owner == "SYSTEM"
    assert "changed" not in {item.phrase for band in view.authority_bands for item in band.promises}

    evidence = next(row for row in view.evidence.tracks if row.promise_id == AUTO)
    amendment = next(row for row in evidence.effects if row.kind == "ORDER_AMEND")
    assert amendment.state == "DELIVERED"
    assert amendment.provider_ref, "the drawer proves the call was accepted"
    assert evidence.track_state == "APPLYING"


async def test_the_evidence_drawer_carries_identifiers_rather_than_sentences(
    browser: httpx2.AsyncClient, wired: Boundary, physical: Intake
) -> None:
    """Band 5: the engineering vocabulary, all of it durable, none of it in bands 1-4."""
    case_id = await settled_case(physical, wired)

    view = await workspace(browser, case_id)

    assert view.evidence.case_id == case_id
    assert view.evidence.case_version >= 1
    assert view.evidence.plan_id
    assert len(view.evidence.tracks) == 6
    assert view.evidence.interpretation is not None
    assert view.evidence.interpretation.attestor == "maya"
    assert view.evidence.interpretation.source == "DETERMINISTIC"

    asked = next(row for row in view.evidence.tracks if row.promise_id == ASK)
    assert asked.approval is not None
    assert asked.approval.provider_ref, "why the product is allowed to say 'asked'"
    assert asked.rule_id and asked.fingerprint

    assert view.untouched_effect_count == sum(
        len(next(row for row in view.evidence.tracks if row.promise_id == promise_id).effects)
        for promise_id in UNTOUCHED
    ), "the count is the drawer's own rows, not a constant beside them"
    for promise_id in UNTOUCHED:
        untouched = next(row for row in view.evidence.tracks if row.promise_id == promise_id)
        assert untouched.effects == (), "an untouched promise caused nothing"
        assert untouched.approval is None
        assert untouched.track_state == "UNAFFECTED"


# ------------------------------------------------------------------ the path, promise by promise


async def test_every_threatened_promise_carries_the_path_that_reached_it(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """The judge's question -- what is the path from the delivery to the cake -- answered.

    Structural rather than word for word: the shape is what the screen depends on. The chain
    starts at what did not arrive, ends at the promise, names the deciding rule the track was
    classified under, and counts the traversals the track actually has.
    """
    case_id = await planned_case(physical)

    view = await workspace(browser, case_id)

    for band in view.authority_bands:
        for item in band.promises:
            chain = item.causal_chain
            assert chain.present is True, f"{item.promise_id} has no path"
            assert chain.absence_reason is None
            assert chain.path_count >= 1
            assert chain.deciding_rule == item.rule_id
            assert chain.steps[0].slot == "SHORTFALL"
            assert chain.steps[-1].slot == "PROMISE"
            assert chain.steps[-1].label == f"{item.customer_name} - {item.order_external_id}"


async def test_the_first_step_of_every_chain_is_the_delivery_that_did_not_arrive(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """One incident, so every threatened promise starts from the same durable delivery line."""
    case_id = await planned_case(physical)

    view = await workspace(browser, case_id)

    entries = {
        item.causal_chain.steps[0].label for band in view.authority_bands for item in band.promises
    }
    assert entries == {"Valley Produce: raspberries"}
    assert all(
        item.causal_chain.steps[0].detail for band in view.authority_bands for item in band.promises
    )


async def test_no_step_of_any_chain_puts_an_identifier_in_front_of_a_person(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """Bands 1-4 carry no engineering vocabulary, and a label is band 3 text."""
    case_id = await planned_case(physical)

    view = await workspace(browser, case_id)

    for band in view.authority_bands:
        for item in band.promises:
            for step in item.causal_chain.steps:
                assert step.node_ref, "the drawer still gets the reference"
                assert step.node_ref not in step.label
                assert str(item.track_id) not in step.label


async def test_two_promises_in_one_authority_group_each_carry_their_own_path(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """A lane is a grouping of rows. The causal column is a property of a row, never of a lane."""
    case_id = await planned_case(physical)

    view = await workspace(browser, case_id)

    owners = next(band for band in view.authority_bands if band.authority == "OWNER")
    assert owners.count == 2
    chains = [item.causal_chain for item in owners.promises]
    assert all(chain.present for chain in chains)
    assert len({chain.steps[-1].label for chain in chains}) == 2, "no shared trunk, no merge"
    assert len({chain.steps[-1].node_ref for chain in chains}) == 2


async def test_an_untouched_promise_carries_no_path_and_says_why_not(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """Band 4's empty causal column is the selectivity claim, so it arrives with a sentence."""
    case_id = await planned_case(physical)

    view = await workspace(browser, case_id)

    for item in view.untouched:
        chain = item.causal_chain
        assert chain.present is False
        assert chain.steps == ()
        assert chain.deciding_rule is None
        assert chain.absence_reason
        assert "reach" in chain.absence_reason


# ------------------------------------------------------------------- reload, reconnect, restart


async def test_a_reload_lands_on_the_same_case_in_the_same_state(
    browser: httpx2.AsyncClient, wired: Boundary, physical: Intake
) -> None:
    """Two reads of the same URL, with nothing in between, are the same answer."""
    case_id = await settled_case(physical, wired)

    first = await browser.get(f"/api/cases/{case_id}")
    second = await browser.get(f"/api/cases/{case_id}")

    assert first.json() == second.json()


async def test_a_second_application_process_reads_the_same_case(
    browser: httpx2.AsyncClient, wired: Boundary, physical: Intake, runtime_settings: Settings
) -> None:
    """Work outlives a process, and the screen must not suggest otherwise.

    The second client is a second application instance with its own lifespan, its own pool and
    its own session -- the closest a test gets to closing the browser, restarting the server and
    opening the same URL again. It sees the same case because the case is in the database.
    """
    case_id = await settled_case(physical, wired)
    first = await workspace(browser, case_id)

    login_router._limiter.reset()
    async with SignedIn(create_app(order_system_settings(runtime_settings))) as reopened:
        second = await workspace(reopened, case_id)

    assert second == first


async def test_the_case_list_offers_the_case_a_reload_should_return_to(
    browser: httpx2.AsyncClient, physical: Intake
) -> None:
    """The list is how a browser with no URL finds its way back to a case it was reading."""
    case_id = await planned_case(physical)

    response = await browser.get("/api/cases")
    assert response.status_code == 200
    listing = CaseListResponse.model_validate(response.json())

    assert [row.case_id for row in listing.cases] == [case_id]
    assert listing.cases[0].state == "PLANNED"
    assert listing.cases[0].headline == "PLANNED"
    assert listing.cases[0].reported_text == CANONICAL_REPORT
