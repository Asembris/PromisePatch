"""``/api/conversation/*``: what a person can say to a case from a browser, and what they cannot.

These three routes are the first mutations in this product that a browser can cause, so the suite
is written around the things that would make that unsafe rather than around the happy path. Every
test below is one of:

* **the actor is the server's**, never a field of the request;
* **the credential is a session**, never the internal service token, and never absent;
* **a mutation needs its CSRF token**, checked against the session row;
* **an observer is refused by the domain**, on routes that contain no check for one;
* **a yes is bound to the plan that was read out**, and a stale or replayed one is refused;
* **the two transports answer a refusal identically**, because they share the mapping.

Nothing here inserts a row to arrange a state. The planned case is planned because a worker
reported and answered through the real services, so what is asserted is a real case moving.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import pytest_asyncio
from _intake_support import CANONICAL_REPORT, RASPBERRY_ONLY, Intake
from _intake_support import physical as physical
from _mcp_support import SERVICE_TOKEN
from _order_system_support import PROMISEPATCH_ORIGIN, order_system_settings
from fastapi import FastAPI
from pydantic import SecretStr

from promisepatch.api.auth import cookies
from promisepatch.api.routers import auth as login_router
from promisepatch.api.routers import intents as intents_router
from promisepatch.api.schemas.cases import CaseWorkspaceResponse
from promisepatch.config import Settings
from promisepatch.domain.physical import case_id_for
from promisepatch.main import create_app

pytestmark = pytest.mark.integration

BAKER = "maya"
OWNER = "jo"


def application(settings: Settings) -> FastAPI:
    """The real application, with both doors open: a demo session, and the intent API.

    The service token is configured because two tests below compare the two transports' answers,
    and one asserts that holding the token buys nothing on a browser route. A deployment that had
    not configured it would refuse the intent API for a different reason and prove neither.
    """
    return create_app(
        order_system_settings(settings).model_copy(
            update={
                "demo_session_enabled": True,
                "internal_service_token": SecretStr(SERVICE_TOKEN),
                "surface_worker_id": BAKER,
            }
        )
    )


class Browser:
    """A running application, a client for it, and one live session on that client.

    The session is obtained the way the browser really obtains it -- a sign-in, or the scoped
    demo endpoint -- rather than by writing a row, so what the tests exercise is the whole chain
    from cookie to domain.
    """

    def __init__(self, settings: Settings, *, username: str | None) -> None:
        self.app = application(settings)
        self.username = username
        self.client: httpx2.AsyncClient | None = None

    async def __aenter__(self) -> Browser:
        self._lifespan = self.app.router.lifespan_context(self.app)
        await self._lifespan.__aenter__()
        self.client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app), base_url=PROMISEPATCH_ORIGIN
        )
        if self.username is None:
            response = await self.client.post("/api/auth/demo-session")
        else:
            response = await self.client.post(
                "/api/auth/login",
                json={"username": self.username, "password": _password(self.username)},
            )
        assert response.status_code == 200, response.text
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self.client is not None:
            await self.client.aclose()
        await self._lifespan.__aexit__(*exc)

    @property
    def csrf(self) -> dict[str, str]:
        assert self.client is not None
        return {cookies.CSRF_HEADER: self.client.cookies[cookies.CSRF_COOKIE]}

    async def say(
        self, verb: str, body: dict[str, Any], *, headers: dict[str, str] | None = None
    ) -> httpx2.Response:
        assert self.client is not None
        return await self.client.post(
            f"/api/conversation/{verb}",
            json=body,
            headers=self.csrf if headers is None else headers,
        )

    async def workspace(self, case_id: UUID) -> CaseWorkspaceResponse:
        assert self.client is not None
        response = await self.client.get(f"/api/cases/{case_id}")
        assert response.status_code == 200, response.text
        return CaseWorkspaceResponse.model_validate(response.json())


def _password(username: str) -> str:
    settings = Settings()
    if username == OWNER:
        return settings.require_demo_owner_password()
    return settings.require_demo_worker_password()


@pytest_asyncio.fixture
async def worker(runtime_settings: Settings, physical: Intake) -> AsyncIterator[Browser]:
    """A signed-in baker. The intake fixture owns the database this reads."""
    login_router._limiter.reset()
    async with Browser(runtime_settings, username=BAKER) as browser:
        yield browser


@pytest_asyncio.fixture
async def observer(runtime_settings: Settings, physical: Intake) -> AsyncIterator[Browser]:
    """A scoped demo session. The domain admits it to reads and to nothing else."""
    login_router._limiter.reset()
    login_router._demo_limiter.reset()
    async with Browser(runtime_settings, username=None) as browser:
        yield browser


async def planned(physical: Intake) -> UUID:
    """The canonical case, carried to the point where a plan is waiting for a yes."""
    opened = await physical.report(CANONICAL_REPORT)
    await physical.drain()
    await physical.answer(opened.case_id, RASPBERRY_ONLY)
    await physical.drain()
    return opened.case_id


async def clarifying(physical: Intake) -> UUID:
    """The canonical case, stopped at the one open question."""
    opened = await physical.report(CANONICAL_REPORT)
    await physical.drain()
    return opened.case_id


# ------------------------------------------------------------------------- who is speaking


async def test_a_report_is_attributed_to_the_session_and_not_to_the_request(
    worker: Browser, physical: Intake
) -> None:
    """The only name on the record is the one the server read off its own session row."""
    response = await worker.say("report", {"command_id": str(uuid4()), "text": CANONICAL_REPORT})

    assert response.status_code == 202, response.text
    assert response.json()["attested_by"] == BAKER
    case_id = UUID(response.json()["case_id"])
    reports = await physical.reports(case_id)
    assert [row.reported_by for row in reports] == [BAKER]


async def test_a_request_carrying_an_actor_is_rejected_rather_than_ignored(
    worker: Browser,
) -> None:
    """``extra="forbid"``: somebody labouring under that misunderstanding finds out at once."""
    for extra in ("worker_id", "actor", "reported_by", "attested_by", "observed_at"):
        response = await worker.say(
            "report",
            {"command_id": str(uuid4()), "text": CANONICAL_REPORT, extra: OWNER},
        )
        assert response.status_code == 422, extra


async def test_the_words_are_stored_byte_for_byte(worker: Browser, physical: Intake) -> None:
    """A statement is evidence, and the first thing anything does to evidence must be nothing."""
    spoken = "  Today's RASPBERRY delivery didn't arrive... again!!  "
    response = await worker.say("report", {"command_id": str(uuid4()), "text": spoken})

    case_id = UUID(response.json()["case_id"])
    assert (await physical.reports(case_id))[0].raw_text == spoken


async def test_a_redelivered_command_is_the_same_statement_arriving_twice(
    worker: Browser, physical: Intake
) -> None:
    """One case, one statement, and the second answer says it was not created again."""
    command_id = str(uuid4())
    body = {"command_id": command_id, "text": CANONICAL_REPORT}

    first = await worker.say("report", body)
    second = await worker.say("report", body)

    assert first.json()["case_id"] == second.json()["case_id"]
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert len(await physical.reports(UUID(first.json()["case_id"]))) == 1


async def test_a_used_command_id_carrying_different_words_is_a_conflict(
    worker: Browser,
) -> None:
    """Two different things said under one identity, and only one of them can be what happened."""
    command_id = str(uuid4())
    await worker.say("report", {"command_id": command_id, "text": CANONICAL_REPORT})

    clash = await worker.say(
        "report", {"command_id": command_id, "text": "the whole delivery didn't arrive"}
    )

    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "COMMAND_CONFLICT"


# ------------------------------------------------------------------------ the credential


async def test_a_browser_with_no_session_can_say_nothing(runtime_settings: Settings) -> None:
    app = application(runtime_settings)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url=PROMISEPATCH_ORIGIN
        ) as client,
    ):
        for verb, body in (
            ("report", {"command_id": str(uuid4()), "text": CANONICAL_REPORT}),
            ("clarify", {"command_id": str(uuid4()), "case_id": str(uuid4()), "text": "x"}),
            ("confirm", {"command_id": str(uuid4()), "case_id": str(uuid4()), "plan_id": "abc"}),
        ):
            response = await client.post(f"/api/conversation/{verb}", json=body)
            assert response.status_code == 401, verb
            assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_the_internal_service_token_buys_nothing_on_a_browser_route(
    runtime_settings: Settings,
) -> None:
    """The credential the MCP process holds is not a session, and these routes want a session.

    It is never sent to a browser in the first place. This asserts the other half: even holding
    one, a caller with no session is refused here exactly as an anonymous caller is.
    """
    app = application(runtime_settings)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url=PROMISEPATCH_ORIGIN
        ) as client,
    ):
        response = await client.post(
            "/api/conversation/report",
            json={"command_id": str(uuid4()), "text": CANONICAL_REPORT},
            headers={intents_router.SERVICE_TOKEN_HEADER: SERVICE_TOKEN},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_the_internal_intent_api_still_refuses_a_browser_session(
    worker: Browser, physical: Intake
) -> None:
    """The two doors stay separate: a cookie is not a service token either."""
    assert worker.client is not None

    response = await worker.client.post(
        "/internal/intents/report",
        json={"command_id": str(uuid4()), "text": CANONICAL_REPORT},
        headers=worker.csrf,
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SERVICE_TOKEN_INVALID"


async def test_a_mutation_without_its_csrf_token_is_refused(worker: Browser) -> None:
    """The first browser mutations in this product, so this check is load-bearing here."""
    response = await worker.say(
        "report", {"command_id": str(uuid4()), "text": CANONICAL_REPORT}, headers={}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_TOKEN_INVALID"


async def test_a_mutation_with_somebody_elses_csrf_token_is_refused(worker: Browser) -> None:
    """Compared against the session row, so a token a caller could write is worth nothing."""
    response = await worker.say(
        "report",
        {"command_id": str(uuid4()), "text": CANONICAL_REPORT},
        headers={cookies.CSRF_HEADER: "a-token-somebody-made-up"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_TOKEN_INVALID"


# ---------------------------------------------------------------------------- the observer


async def test_an_observer_can_read_a_case_and_change_nothing(
    observer: Browser, physical: Intake
) -> None:
    """The whole judge capability, asserted as one sentence: everything to read, nothing to do."""
    case_id = await planned(physical)
    view = await observer.workspace(case_id)
    assert view.may_speak is False

    refusals = [
        await observer.say("report", {"command_id": str(uuid4()), "text": CANONICAL_REPORT}),
        await observer.say(
            "clarify",
            {"command_id": str(uuid4()), "case_id": str(case_id), "text": RASPBERRY_ONLY},
        ),
        await observer.say(
            "confirm",
            {"command_id": str(uuid4()), "case_id": str(case_id), "plan_id": view.plan_id},
        ),
    ]

    assert all(response.status_code >= 400 for response in refusals)
    assert (await physical.case(case_id)).state == "PLANNED"


async def test_the_observers_refusal_comes_from_the_domain(
    observer: Browser, physical: Intake
) -> None:
    """The routes contain no observer check. What refuses is ``require_permitted`` itself."""
    case_id = await planned(physical)
    view = await observer.workspace(case_id)

    response = await observer.say(
        "confirm",
        {"command_id": str(uuid4()), "case_id": str(case_id), "plan_id": view.plan_id},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CASE_NOT_PERMITTED"


async def test_an_observer_holding_a_valid_csrf_token_is_still_refused(
    observer: Browser, physical: Intake
) -> None:
    """CSRF is not the control here. The session is genuine and the domain refuses it anyway.

    On a case that really is waiting for an answer, so the refusal is the permission one rather
    than the state one -- the domain checks the state first, which is right and would otherwise
    hide what this test is about.
    """
    case_id = await clarifying(physical)

    response = await observer.say(
        "clarify",
        {"command_id": str(uuid4()), "case_id": str(case_id), "text": RASPBERRY_ONLY},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CASE_NOT_PERMITTED"
    assert (await physical.clarifications(case_id))[0].answered_at is None


async def test_an_observer_cannot_open_a_case_of_its_own(observer: Browser) -> None:
    """The one path that would otherwise have made an observer a case's own opener.

    Opening a case is the single intake path with no case to be permitted on, so
    ``require_permitted`` cannot be its gate -- and the worker who opened a case is exactly whom
    ``require_permitted`` admits to it afterwards. A principal that could open one would
    therefore have granted itself every subsequent write on it. ``require_attestor`` refuses.
    """
    response = await observer.say("report", {"command_id": str(uuid4()), "text": CANONICAL_REPORT})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CASE_NOT_PERMITTED"


async def test_an_observers_refused_report_leaves_no_case_behind(
    observer: Browser, physical: Intake
) -> None:
    """Refused before the case row, not after it: the id derived from the command names nothing."""
    command_id = uuid4()

    response = await observer.say(
        "report", {"command_id": str(command_id), "text": CANONICAL_REPORT}
    )

    assert response.status_code == 403
    assert await physical.case(case_id_for(command_id)) is None


# -------------------------------------------------------------- unchanged for a real worker


async def test_a_worker_answers_the_open_question_in_their_own_words(
    worker: Browser, physical: Intake
) -> None:
    case_id = await clarifying(physical)

    response = await worker.say(
        "clarify",
        {"command_id": str(uuid4()), "case_id": str(case_id), "text": RASPBERRY_ONLY},
    )

    assert response.status_code == 202, response.text
    assert response.json()["attested_by"] == BAKER
    answered = (await physical.clarifications(case_id))[0]
    assert answered.answer_text == RASPBERRY_ONLY


async def test_answering_a_case_that_is_not_asking_is_refused(
    worker: Browser, physical: Intake
) -> None:
    case_id = await planned(physical)

    response = await worker.say(
        "clarify",
        {"command_id": str(uuid4()), "case_id": str(case_id), "text": RASPBERRY_ONLY},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NOT_AWAITING_CLARIFICATION"


async def test_an_owner_may_speak_on_a_case_they_did_not_open(
    runtime_settings: Settings, physical: Intake
) -> None:
    """Escalation is the owner's to resolve, and the browser transport does not narrow that."""
    case_id = await clarifying(physical)
    login_router._limiter.reset()

    async with Browser(runtime_settings, username=OWNER) as owner:
        response = await owner.say(
            "clarify",
            {"command_id": str(uuid4()), "case_id": str(case_id), "text": RASPBERRY_ONLY},
        )

    assert response.status_code == 202, response.text
    assert response.json()["attested_by"] == OWNER


# ------------------------------------------------------------------- a yes, bound to a plan


async def test_a_confirmation_authorises_the_plan_that_was_read_out(
    worker: Browser, physical: Intake
) -> None:
    case_id = await planned(physical)
    view = await worker.workspace(case_id)
    assert view.awaiting_confirmation is True

    response = await worker.say(
        "confirm",
        {"command_id": str(uuid4()), "case_id": str(case_id), "plan_id": view.plan_id},
    )

    assert response.status_code == 202, response.text
    assert response.json()["attested_by"] == BAKER
    assert (await physical.case(case_id)).state == "EXECUTING"


async def test_a_confirmation_quoting_a_plan_the_case_is_not_offering_is_refused(
    worker: Browser, physical: Intake
) -> None:
    """Never applied to whatever the case happens to hold when it arrives."""
    case_id = await planned(physical)

    response = await worker.say(
        "confirm",
        {
            "command_id": str(uuid4()),
            "case_id": str(case_id),
            "plan_id": "0000000000000000",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAN_SUPERSEDED"
    assert (await physical.case(case_id)).state == "PLANNED"


async def test_a_confirmation_replayed_after_the_case_moved_is_refused(
    worker: Browser, physical: Intake
) -> None:
    """The second yes quotes a plan that is no longer on offer, and is refused as stale."""
    case_id = await planned(physical)
    view = await worker.workspace(case_id)
    first = await worker.say(
        "confirm",
        {"command_id": str(uuid4()), "case_id": str(case_id), "plan_id": view.plan_id},
    )
    assert first.status_code == 202, first.text

    replay = await worker.say(
        "confirm",
        {"command_id": str(uuid4()), "case_id": str(case_id), "plan_id": view.plan_id},
    )

    assert replay.status_code == 409
    assert replay.json()["error"]["code"] in {"PLAN_SUPERSEDED", "PLAN_NOT_CONFIRMABLE"}


async def test_the_same_confirmation_redelivered_is_one_confirmation(
    worker: Browser, physical: Intake
) -> None:
    """A retry of one yes is that yes arriving twice, and is not a second authorisation."""
    case_id = await planned(physical)
    view = await worker.workspace(case_id)
    body = {"command_id": str(uuid4()), "case_id": str(case_id), "plan_id": view.plan_id}

    first = await worker.say("confirm", body)
    again = await worker.say("confirm", body)

    assert first.status_code == 202
    assert again.status_code == 202
    assert first.json()["created"] is True
    assert again.json()["created"] is False


async def test_confirming_a_case_with_no_plan_on_offer_is_refused(
    worker: Browser, physical: Intake
) -> None:
    case_id = await clarifying(physical)

    response = await worker.say(
        "confirm",
        {"command_id": str(uuid4()), "case_id": str(case_id), "plan_id": "0000000000000000"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] in {"PLAN_SUPERSEDED", "PLAN_NOT_CONFIRMABLE"}


async def test_a_confirmation_reports_permission_and_never_completion(
    worker: Browser, physical: Intake
) -> None:
    """The sentence a person is handed says what may now happen. Nothing has happened."""
    case_id = await planned(physical)
    view = await worker.workspace(case_id)

    response = await worker.say(
        "confirm",
        {"command_id": str(uuid4()), "case_id": str(case_id), "plan_id": view.plan_id},
    )

    speech = response.json()["speech"].lower()
    assert "nothing has been changed yet" in speech
    for claimed in ("done", "completed", "sent", "changed the order", "recovered"):
        assert claimed not in speech.replace("nothing has been changed yet", "")


async def test_a_confirmation_is_never_rendered_in_consents_language(
    worker: Browser, physical: Intake
) -> None:
    """Worker plan confirmation is a different authority from a customer's own agreement."""
    case_id = await planned(physical)
    view = await worker.workspace(case_id)

    response = await worker.say(
        "confirm",
        {"command_id": str(uuid4()), "case_id": str(case_id), "plan_id": view.plan_id},
    )

    speech = response.json()["speech"].lower()
    for consent_word in ("consent", "agreed", "approved", "the customer said", "on behalf of"):
        assert consent_word not in speech


# --------------------------------------------------- a withdrawal, and what it cannot undo


async def test_a_worker_withdraws_a_planned_case_from_their_own_browser(
    worker: Browser, physical: Intake
) -> None:
    """The fifth verb over the session credential, attributed to the session and nothing else."""
    case_id = await planned(physical)

    response = await worker.say("withdraw", {"command_id": str(uuid4()), "case_id": str(case_id)})

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["withdrawn_by"] == BAKER
    assert body["state"] == "CANCELLED"
    assert (await physical.case(case_id)).state == "CANCELLED"


async def test_a_withdrawal_without_its_csrf_token_is_refused(
    worker: Browser, physical: Intake
) -> None:
    """The newest mutation is not the one that forgot the check."""
    case_id = await planned(physical)

    response = await worker.say(
        "withdraw",
        {"command_id": str(uuid4()), "case_id": str(case_id)},
        headers={},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_TOKEN_INVALID"
    assert (await physical.case(case_id)).state == "PLANNED"


async def test_an_observer_may_not_withdraw_a_case(observer: Browser, physical: Intake) -> None:
    """Read-only means read-only, and the refusal is the domain's rather than this route's."""
    case_id = await planned(physical)

    response = await observer.say("withdraw", {"command_id": str(uuid4()), "case_id": str(case_id)})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CASE_NOT_PERMITTED"
    assert (await physical.case(case_id)).state == "PLANNED"


async def test_a_withdrawal_cannot_name_the_worker_who_made_it(
    worker: Browser, physical: Intake
) -> None:
    case_id = await planned(physical)

    response = await worker.say(
        "withdraw",
        {"command_id": str(uuid4()), "case_id": str(case_id), "worker_id": OWNER},
    )

    assert response.status_code == 422, response.text
    assert (await physical.case(case_id)).state == "PLANNED"


async def test_a_withdrawal_after_a_confirmation_never_reads_as_an_undo(
    worker: Browser, physical: Intake
) -> None:
    """The sentence a person sees says what stands, not that everything was rolled back."""
    case_id = await planned(physical)
    view = await worker.workspace(case_id)
    confirmed = await worker.say(
        "confirm",
        {"command_id": str(uuid4()), "case_id": str(case_id), "plan_id": view.plan_id},
    )
    assert confirmed.status_code == 202, confirmed.text

    body = (
        await worker.say("withdraw", {"command_id": str(uuid4()), "case_id": str(case_id)})
    ).json()

    assert body["state"] != "CANCELLED"
    assert body["escalated"] >= 1
    assert "undone" not in body["speech"]
    assert "rolled back" not in body["speech"]


async def test_a_withdrawn_case_cannot_be_withdrawn_again(
    worker: Browser, physical: Intake
) -> None:
    case_id = await planned(physical)
    first = await worker.say("withdraw", {"command_id": str(uuid4()), "case_id": str(case_id)})
    assert first.status_code == 202, first.text

    again = await worker.say("withdraw", {"command_id": str(uuid4()), "case_id": str(case_id)})

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "CASE_NOT_WITHDRAWABLE"


# --------------------------------------------------------- the two transports say one thing


async def test_both_transports_answer_a_stale_plan_with_the_same_code(
    worker: Browser, physical: Intake
) -> None:
    """One shared mapping, so a client that learned one transport is right about the other."""
    browser_case = await planned(physical)
    tool_case = await planned(physical)
    assert worker.client is not None

    over_the_browser = await worker.say(
        "confirm",
        {
            "command_id": str(uuid4()),
            "case_id": str(browser_case),
            "plan_id": "0000000000000000",
        },
    )
    over_the_tools = await worker.client.post(
        "/internal/intents/confirm",
        json={
            "command_id": str(uuid4()),
            "case_id": str(tool_case),
            "plan_id": "0000000000000000",
        },
        headers={intents_router.SERVICE_TOKEN_HEADER: SERVICE_TOKEN},
    )

    assert over_the_browser.status_code == over_the_tools.status_code
    assert over_the_browser.json()["error"]["code"] == over_the_tools.json()["error"]["code"]


async def test_both_transports_answer_a_closed_question_with_the_same_code(
    worker: Browser, physical: Intake
) -> None:
    browser_case = await planned(physical)
    tool_case = await planned(physical)
    assert worker.client is not None

    over_the_browser = await worker.say(
        "clarify",
        {"command_id": str(uuid4()), "case_id": str(browser_case), "text": RASPBERRY_ONLY},
    )
    over_the_tools = await worker.client.post(
        "/internal/intents/clarify",
        json={
            "command_id": str(uuid4()),
            "case_id": str(tool_case),
            "text": RASPBERRY_ONLY,
        },
        headers={intents_router.SERVICE_TOKEN_HEADER: SERVICE_TOKEN},
    )

    assert over_the_browser.status_code == over_the_tools.status_code
    assert over_the_browser.json()["error"]["code"] == over_the_tools.json()["error"]["code"]
