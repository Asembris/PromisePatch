"""``/api/conversation/simulated-alexa``: the bridge ADR-0028 allows, and everything it must refuse.

Every refusal below is asserted to happen **before an MCP connection is opened**, because the
bridge's whole safety argument is that a session it should not serve never reaches the surface
that attributes words to the surface worker. The positive paths run the real chain: browser
session, this API, the orchestrator, MCP 2025-11-25 Streamable HTTP on a real socket, the intent
API on another, and the domain. Only the model is scripted.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
import pytest_asyncio
from _intake_support import BAKER, CANONICAL_REPORT, CORRECTION, RASPBERRY_ONLY, Intake
from _intake_support import physical as physical
from _mcp_support import BEARER, SERVICE_TOKEN, mcp_over_http, serve
from _order_system_support import PROMISEPATCH_ORIGIN, order_system_settings
from pydantic import SecretStr
from sqlalchemy import func, select

from promisepatch.api.auth import cookies
from promisepatch.api.routers import auth as login_router
from promisepatch.api.routers import simulated_alexa
from promisepatch.config import Settings
from promisepatch.db.models import PlanApproval
from promisepatch.main import create_app
from promisepatch.mcp.envelope import ToolCode
from promisepatch.orchestrator import ToolOutcome
from promisepatch.semantic import FakeSemanticProvider, SemanticJob

pytestmark = pytest.mark.integration

OWNER = "jo"
TURN = "/api/conversation/simulated-alexa"
THE_YES = "yes, go ahead"
UNUSED_MCP_URL = "http://127.0.0.1:9/mcp"
NOTHING_DONE = {"NOT_UNDERSTOOD", "NOT_PERMITTED_HERE"}
"""A verb the phase does not offer is refused at the semantic boundary or by the policy."""


def chooses(*verbs: str) -> FakeSemanticProvider:
    """A model that names these verbs, in order, and supplies nothing else."""
    return FakeSemanticProvider({SemanticJob.SELECT_TOOL: [{"tool": verb} for verb in verbs]})


def _password(username: str) -> str:
    settings = Settings()
    if username == OWNER:
        return settings.require_demo_owner_password()
    return settings.require_demo_worker_password()


class Browser:
    """The real application in-process, and one session obtained the way a browser obtains it."""

    def __init__(self, settings: Settings, *, username: str | None, mcp_url: str) -> None:
        self.app = create_app(
            order_system_settings(settings).model_copy(
                update={
                    "demo_session_enabled": True,
                    "internal_service_token": SecretStr(SERVICE_TOKEN),
                    "surface_worker_id": BAKER,
                    "mcp_bearer_token": SecretStr(BEARER),
                    "orchestrator_mcp_url": mcp_url,
                }
            )
        )
        self.username = username
        self.client: httpx2.AsyncClient | None = None

    async def __aenter__(self) -> Browser:
        self._lifespan = self.app.router.lifespan_context(self.app)
        await self._lifespan.__aenter__()
        self.client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app), base_url=PROMISEPATCH_ORIGIN
        )
        if self.username is not None:
            response = await self.client.post(
                "/api/auth/login",
                json={"username": self.username, "password": _password(self.username)},
            )
        else:
            response = await self.client.post("/api/auth/demo-session")
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

    async def turn(
        self, body: Mapping[str, Any], *, headers: dict[str, str] | None = None
    ) -> httpx2.Response:
        assert self.client is not None
        return await self.client.post(
            TURN, json=dict(body), headers=self.csrf if headers is None else headers
        )

    async def approve(self, case_id: UUID, plan_id: str) -> httpx2.Response:
        assert self.client is not None
        return await self.client.post(
            "/api/conversation/approve",
            json={"case_id": str(case_id), "plan_id": plan_id},
            headers=self.csrf,
        )


@pytest.fixture(autouse=True)
def _fresh_limits() -> Iterator[None]:
    login_router._limiter.reset()
    login_router._demo_limiter.reset()
    simulated_alexa._limiter.reset()
    yield


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the MCP connection with one that only records that it was opened."""
    seen: list[str] = []

    @asynccontextmanager
    async def recording(url: str, **_: Any) -> AsyncIterator[Any]:
        seen.append(url)
        if seen:
            raise RuntimeError("no MCP connection may be opened here")
        yield  # pragma: no cover - unreachable once a URL is recorded

    monkeypatch.setattr(simulated_alexa, "connect_mcp", recording)
    monkeypatch.setattr(simulated_alexa, "build_semantic_provider", lambda _s: chooses("CONFIRM"))
    return seen


@pytest_asyncio.fixture
async def mcp_url(physical: Intake) -> AsyncIterator[str]:
    """The real MCP endpoint on a socket, forwarding to the real intent API on another."""
    api = create_app(Settings(internal_service_token=SERVICE_TOKEN, surface_worker_id=BAKER))
    async with serve(api) as api_base, mcp_over_http(api_base) as server:
        yield server.url


async def planned(physical: Intake) -> UUID:
    opened_case = await physical.report(CANONICAL_REPORT)
    await physical.drain()
    await physical.answer(opened_case.case_id, RASPBERRY_ONLY)
    await physical.drain()
    return opened_case.case_id


async def approvals(physical: Intake, case_id: UUID) -> int:
    async with physical.database.connect() as connection:
        query = (
            select(func.count()).select_from(PlanApproval).where(PlanApproval.case_id == case_id)
        )
        return int((await connection.execute(query)).scalar_one())


# ---------------------------------------------------------------- refused before MCP is used


async def test_no_session_is_refused_before_mcp(
    runtime_settings: Settings, physical: Intake, opened: list[str]
) -> None:
    app = Browser(runtime_settings, username=BAKER, mcp_url=UNUSED_MCP_URL).app
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url=PROMISEPATCH_ORIGIN
        ) as client,
    ):
        response = await client.post(TURN, json={"case_id": str(uuid4()), "text": THE_YES})
    assert response.status_code == 401
    assert opened == []


async def test_a_turn_without_its_csrf_token_is_refused_before_mcp(
    runtime_settings: Settings, physical: Intake, opened: list[str]
) -> None:
    async with Browser(runtime_settings, username=BAKER, mcp_url=UNUSED_MCP_URL) as browser:
        response = await browser.turn({"case_id": str(uuid4()), "text": THE_YES}, headers={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_TOKEN_INVALID"
    assert opened == []


@pytest.mark.parametrize("username", [None, OWNER], ids=["observer", "another-worker"])
async def test_anybody_but_the_surface_worker_is_refused_before_mcp(
    runtime_settings: Settings, physical: Intake, opened: list[str], username: str | None
) -> None:
    """The observer would be escalation; the owner would be attribution laundering."""
    case_id = await planned(physical)
    async with Browser(runtime_settings, username=username, mcp_url=UNUSED_MCP_URL) as browser:
        response = await browser.turn({"case_id": str(case_id), "text": THE_YES})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_THE_SURFACE_WORKER"
    assert opened == []
    assert (await physical.case(case_id)).state == "PLANNED"


@pytest.mark.parametrize(
    "extra",
    [{"worker_id": BAKER}, {"plan_id": "0" * 64}, {"tool": "confirm"}, {"observed_at": "now"}],
    ids=["actor", "plan", "tool", "clock"],
)
async def test_a_request_carrying_anything_but_case_and_text_is_rejected(
    runtime_settings: Settings, physical: Intake, opened: list[str], extra: dict[str, str]
) -> None:
    async with Browser(runtime_settings, username=BAKER, mcp_url=UNUSED_MCP_URL) as browser:
        response = await browser.turn({"case_id": str(uuid4()), "text": THE_YES, **extra})
    assert response.status_code == 422
    assert opened == []


# ----------------------------------------------------------- what a turn can and cannot reach


class Scripted:
    """A surface whose ``status`` fails and whose every other call would visibly succeed."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call(self, tool: str, arguments: Mapping[str, str]) -> ToolOutcome:
        self.calls.append(tool)
        if tool == "status":
            return ToolOutcome(tool=tool, refusal=ToolCode.ENGINE_UNAVAILABLE)
        return ToolOutcome(tool=tool, body={"speech": f"{tool} happened"})


async def test_a_failed_hydration_read_cannot_write(
    runtime_settings: Settings, physical: Intake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Status unreadable, the model chooses confirm on a planned case, and nothing is called."""
    case_id = await planned(physical)
    await physical.approve(case_id)
    surface = Scripted()

    @asynccontextmanager
    async def scripted(url: str, **_: Any) -> AsyncIterator[Scripted]:
        yield surface

    monkeypatch.setattr(simulated_alexa, "connect_mcp", scripted)
    monkeypatch.setattr(simulated_alexa, "build_semantic_provider", lambda _s: chooses("CONFIRM"))
    async with Browser(runtime_settings, username=BAKER, mcp_url=UNUSED_MCP_URL) as browser:
        response = await browser.turn({"case_id": str(case_id), "text": THE_YES})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hydrated"] is False
    assert body["blocked"] in NOTHING_DONE
    assert body["phase"] == "UNDERSTANDING"
    assert set(surface.calls) == {"status"}
    assert (await physical.case(case_id)).state == "PLANNED"


async def test_the_bridge_cannot_report(
    runtime_settings: Settings, physical: Intake, mcp_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model choosing ``REPORT`` on a case-scoped turn reaches no ``report`` tool."""
    case_id = await planned(physical)
    monkeypatch.setattr(simulated_alexa, "build_semantic_provider", lambda _s: chooses("REPORT"))
    async with Browser(runtime_settings, username=BAKER, mcp_url=mcp_url) as browser:
        response = await browser.turn({"case_id": str(case_id), "text": CANONICAL_REPORT})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hydrated"] is True
    assert "report" not in body["calls"]
    assert body["blocked"] in NOTHING_DONE
    assert len(await physical.reports(case_id)) == 2, "the report and the answer, nothing more"


# --------------------------------------------- the real chain: approval is the worker's, not MCP's


async def test_a_spoken_yes_without_a_prior_human_approval_is_refused(
    runtime_settings: Settings, physical: Intake, mcp_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = await planned(physical)
    monkeypatch.setattr(simulated_alexa, "build_semantic_provider", lambda _s: chooses("CONFIRM"))
    async with Browser(runtime_settings, username=BAKER, mcp_url=mcp_url) as browser:
        response = await browser.turn({"case_id": str(case_id), "text": THE_YES})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hydrated"] is True
    assert body["calls"] == ["confirm", "status"]
    assert body["refusal"] == "UNAUTHORIZED_SURFACE"
    assert "not permitted" in body["reply"]
    assert (await physical.case(case_id)).state == "PLANNED"
    assert await approvals(physical, case_id) == 0, "MCP wrote no approval of its own"


async def test_a_spoken_yes_after_the_browser_approval_confirms_once(
    runtime_settings: Settings,
    physical: Intake,
    mcp_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approve on the explicit control, then say yes over MCP: one confirmation, never two.

    Also the bearer check: across a real turn, the token appears in no response body, no
    response header and no line any of the three servers wrote.
    """
    case_id = await planned(physical)
    plan_id = await physical.plan_id(case_id)
    monkeypatch.setattr(
        simulated_alexa, "build_semantic_provider", lambda _s: chooses("CONFIRM", "CONFIRM")
    )
    written = _tee_output(monkeypatch)
    async with Browser(runtime_settings, username=BAKER, mcp_url=mcp_url) as browser:
        approved = await browser.approve(case_id, plan_id)
        assert approved.status_code == 201, approved.text
        first = await browser.turn({"case_id": str(case_id), "text": THE_YES})
        second = await browser.turn({"case_id": str(case_id), "text": THE_YES})

    assert first.status_code == 200, first.text
    assert first.json()["calls"] == ["confirm", "status"]
    assert first.json()["refusal"] is None
    assert "Confirmed" in first.json()["reply"]
    assert (await physical.case(case_id)).state == "EXECUTING"

    assert second.status_code == 200, second.text
    assert "confirm" not in second.json()["calls"], "the case left PLANNED; no second confirm"
    assert second.json()["blocked"] in NOTHING_DONE
    assert await approvals(physical, case_id) == 1

    for response in (approved, first, second):
        assert BEARER not in response.text
        assert all(BEARER not in value for value in response.headers.values())
    logged = "".join(written)
    assert "simulated_alexa.turn" in logged, "the tee saw the bridge's own log lines"
    assert BEARER not in logged


def _tee_output(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Everything written to the live stdout and stderr objects, which structlog prints to.

    A tee rather than ``capfd``: structlog caches its loggers on first use, and a logger cached
    on a capture stream that pytest then closes breaks every later test in the session.
    """
    written: list[str] = []
    for stream in (sys.stdout, sys.stderr):
        original = stream.write

        def tee(text: str, _original: Any = original) -> int:
            written.append(text)
            return int(_original(text))

        monkeypatch.setattr(stream, "write", tee)
    return written


async def test_a_yes_to_a_plan_that_changed_since_the_approval_is_refused(
    runtime_settings: Settings, physical: Intake, mcp_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker approved plan A; the case re-planned; the yes reaches plan B, never approved."""
    case_id = await planned(physical)
    approved_plan = await physical.plan_id(case_id)
    monkeypatch.setattr(simulated_alexa, "build_semantic_provider", lambda _s: chooses("CONFIRM"))
    async with Browser(runtime_settings, username=BAKER, mcp_url=mcp_url) as browser:
        approved = await browser.approve(case_id, approved_plan)
        assert approved.status_code == 201, approved.text
        await physical.correct(case_id, CORRECTION)
        await physical.drain()
        assert await physical.plan_id(case_id) != approved_plan
        response = await browser.turn({"case_id": str(case_id), "text": THE_YES})

    assert response.status_code == 200, response.text
    assert response.json()["calls"] == ["confirm", "status"]
    assert response.json()["refusal"] == "UNAUTHORIZED_SURFACE"
    assert (await physical.case(case_id)).state == "PLANNED", "the changed plan was not confirmed"
    assert await approvals(physical, case_id) == 1, "only the approval of the old plan exists"
