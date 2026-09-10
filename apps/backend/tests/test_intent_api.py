"""The conversation's entrance to the case engine, against a real database.

``test_mcp_protocol.py`` proves the transport. This proves the consequence: that a tool call
arriving over that transport becomes rows somebody can point at afterwards -- a case, a
statement in the worker's own words, an audit entry carrying the correlation id the tool
returned -- and that the things a conversation must not decide are still not decidable when the
call is real.

Two levels are exercised deliberately. The intent API is called directly, because that is where
the credential and the identity rule live. Then the whole chain is driven end to end -- SDK
client, Streamable HTTP, MCP server, HTTP hop, intent API, domain service, PostgreSQL -- because
a boundary that is only tested from the middle is a boundary nobody has stood at.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest_asyncio
from _intake_support import BAKER, CANONICAL_REPORT, OWNER, RASPBERRY_ONLY, Intake
from _intake_support import physical as physical
from _mcp_support import SERVICE_TOKEN, McpServer, mcp_over_http, mcp_settings, serve
from fastapi import FastAPI
from sqlalchemy import func, select

from promisepatch.config import Settings
from promisepatch.db.models import Case, CaseReport
from promisepatch.domain.observation import AUDIT_CASE_OPENED
from promisepatch.main import create_app

REPORT = "/internal/intents/report"
STATUS = "/internal/intents/status"
BASE = "http://api.test"


@dataclass
class Boundary:
    """A seeded database, the real API serving it, and a client that speaks to it."""

    physical: Intake
    api: FastAPI
    client: httpx2.AsyncClient

    async def report(
        self, text: str = CANONICAL_REPORT, *, command_id: UUID | None = None, **kwargs: Any
    ) -> httpx2.Response:
        body: dict[str, Any] = {"command_id": str(command_id or uuid4()), "text": text}
        body.update(kwargs.pop("extra", {}))
        return await self.client.post(REPORT, json=body, headers=_service(**kwargs))

    async def status(self, case_id: UUID | str, **kwargs: Any) -> httpx2.Response:
        return await self.client.post(
            STATUS, json={"case_id": str(case_id)}, headers=_service(**kwargs)
        )


def _service(
    *, token: str | None = SERVICE_TOKEN, correlation: str | None = None
) -> dict[str, str]:
    headers = {}
    if token is not None:
        headers["X-Service-Token"] = token
    if correlation is not None:
        headers["X-Correlation-ID"] = correlation
    return headers


def api_settings(**overrides: Any) -> Settings:
    """The API's configuration, with the conversational surface configured on the server.

    ``surface_worker_id`` is the whole identity story in one line: it is here, in settings, and
    there is no request field anywhere in the chain that could contradict it.
    """
    values: dict[str, Any] = {
        "internal_service_token": SERVICE_TOKEN,
        "surface_worker_id": BAKER,
    }
    values.update(overrides)
    return Settings(**values)


def _served(settings: Settings, database: object) -> FastAPI:
    """The real application, with the engine handle the fixture already opened.

    The lifespan is not run: it would open a second pool and a LISTEN connection this test has
    no use for. Everything the intent router touches reads ``app.state.database``, which is set
    here to the same handle the domain services use, so the code path under test is the
    deployed one.
    """
    api = create_app(settings)
    api.state.database = database
    return api


@pytest_asyncio.fixture
async def boundary(physical: Intake) -> AsyncIterator[Boundary]:
    api = _served(api_settings(), physical.database)
    transport = httpx2.ASGITransport(app=api)
    async with httpx2.AsyncClient(transport=transport, base_url=BASE) as client:
        yield Boundary(physical=physical, api=api, client=client)


# ------------------------------------------------------------------------ what report writes


async def test_report_stores_the_worker_s_words_exactly(boundary: Boundary) -> None:
    """The statement is durable before anything is concluded, and it is not tidied on the way.

    Leading and trailing whitespace survive on purpose. A transport that trimmed would be
    editing an attestation, and afterwards the only record of the original would be the one it
    changed.
    """
    said = "  today's raspberry delivery didn't arrive  "
    response = await boundary.report(said)
    assert response.status_code == 202
    case_id = UUID(response.json()["case_id"])

    reports = await boundary.physical.reports(case_id)
    assert [row.raw_text for row in reports] == [said]
    assert reports[0].reported_by == BAKER


async def test_the_case_is_received_and_nothing_has_been_concluded(boundary: Boundary) -> None:
    response = await boundary.report()
    body = response.json()
    assert body["state"] == "RECEIVED"
    assert body["created"] is True
    case = await boundary.physical.case(UUID(body["case_id"]))
    assert case.state == "RECEIVED"
    assert case.exception_id is None


async def test_the_attestor_comes_from_configuration_not_from_the_request(
    boundary: Boundary,
) -> None:
    response = await boundary.report()
    assert response.json()["attested_by"] == BAKER


async def test_a_request_that_names_a_worker_is_refused_outright(boundary: Boundary) -> None:
    """The schema forbids extra fields, so a caller under that misunderstanding finds out.

    Silently dropping the field would work too, and would leave an orchestrator believing it
    had chosen an actor. An error is the only answer that corrects the belief.
    """
    response = await boundary.report(extra={"worker_id": "owner", "observed_at": "2020-01-01"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


async def test_a_redelivered_command_returns_the_same_case(boundary: Boundary) -> None:
    command_id = uuid4()
    first = await boundary.report(command_id=command_id)
    second = await boundary.report(command_id=command_id)
    assert second.status_code == 202
    assert second.json()["case_id"] == first.json()["case_id"]
    assert second.json()["created"] is False
    assert len(await boundary.physical.reports(UUID(first.json()["case_id"]))) == 1


async def test_one_command_id_carrying_two_different_statements_is_a_conflict(
    boundary: Boundary,
) -> None:
    command_id = uuid4()
    await boundary.report("the raspberries did not arrive", command_id=command_id)
    clash = await boundary.report("the oven is out", command_id=command_id)
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "COMMAND_CONFLICT"


async def test_the_correlation_id_reaches_the_audit_ledger(boundary: Boundary) -> None:
    """The tool call and the rows it caused are findable from one another.

    This is what makes "durable evidence" a claim a person can check rather than a phrase in a
    document: the identifier the conversation was handed is on the audit row for the case it
    opened.
    """
    correlation = uuid4()
    response = await boundary.report(correlation=str(correlation))
    case_id = UUID(response.json()["case_id"])

    audits = await boundary.physical.audits(case_id)
    opened = [row for row in audits if row.type == AUDIT_CASE_OPENED]
    assert opened
    assert all(row.correlation_id == correlation for row in opened)


# ------------------------------------------------------------------------- who may call at all


async def test_without_the_service_token_nothing_is_written(boundary: Boundary) -> None:
    response = await boundary.report(token=None)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SERVICE_TOKEN_INVALID"
    async with boundary.physical.database.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(Case)) == 0


async def test_a_wrong_service_token_is_the_same_rejection(boundary: Boundary) -> None:
    response = await boundary.report(token="not-the-token")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SERVICE_TOKEN_INVALID"


async def test_a_deployment_with_no_surface_configured_refuses_to_serve_intents(
    physical: Intake,
) -> None:
    """No attestor, no intake. An intake with nobody on the record is a claim nobody made."""
    api = _served(api_settings(surface_worker_id=None), physical.database)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=api), base_url=BASE) as client:
        response = await client.post(
            REPORT, json={"command_id": str(uuid4()), "text": "anything"}, headers=_service()
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INTENTS_NOT_CONFIGURED"


# ------------------------------------------------------------------------------ what status reads


async def test_status_reads_the_case_this_surface_opened(boundary: Boundary) -> None:
    response = await boundary.report()
    case_id = UUID(response.json()["case_id"])
    read = await boundary.status(case_id)
    assert read.status_code == 200
    body = read.json()
    assert body["headline"] == "UNDERSTANDING"
    assert "Nothing has changed yet." in body["speech"]


async def test_status_refuses_a_case_this_surface_did_not_open(boundary: Boundary) -> None:
    """A case id is a value a model can put in a tool argument, so the domain answers, not us."""
    opened = await boundary.physical.report(worker_id=OWNER)
    read = await boundary.status(opened.case_id)
    assert read.status_code == 403
    assert read.json()["error"]["code"] == "CASE_NOT_PERMITTED"


async def test_status_of_a_case_that_does_not_exist_is_not_found(boundary: Boundary) -> None:
    read = await boundary.status(uuid4())
    assert read.status_code == 404
    assert read.json()["error"]["code"] == "CASE_NOT_FOUND"


async def test_status_describes_a_planned_case_from_real_state(boundary: Boundary) -> None:
    """The canonical path, read back through the intent API rather than through a fixture.

    Every number here is computed by the engine and the workflow: the untouched count, the
    authority bands and the sentences. Nothing in the answer is written by the test, which is
    the point -- a status that agreed with a hardcoded expectation would agree with it whatever
    the engine had concluded.
    """
    case_id = await boundary.physical.resolved_case()
    await boundary.physical.drain()

    read = await boundary.status(case_id)
    assert read.status_code == 200
    body = read.json()
    assert body["headline"] == "PLANNED"
    assert body["threatened"], "the canonical exception threatens at least one promise"
    assert body["untouched_count"] == len(body["untouched"])
    assert body["untouched_count"] > 0, "the demo's selectivity claim needs an untouched promise"
    for promise in body["threatened"]:
        assert promise["state"] in {"PLANNED", "AWAITING_PLAN"}, "nothing is done before a yes"
    for promise in body["untouched"]:
        assert promise["state"] == "UNTOUCHED"
        assert promise["authority"] == "NONE"
    assert "Nothing has been done yet." in body["speech"]
    assert "was left alone" in body["speech"] or "were left alone" in body["speech"]


async def test_a_clarifying_case_says_it_is_waiting_for_an_answer(boundary: Boundary) -> None:
    opened = await boundary.physical.report()
    await boundary.physical.drain_intake(opened.case_id)
    read = await boundary.status(opened.case_id)
    assert read.json()["headline"] == "CLARIFYING"


# ------------------------------------------------------- the whole chain, end to end


@pytest_asyncio.fixture
async def chain(physical: Intake) -> AsyncIterator[McpServer]:
    """Two servers on two sockets: the MCP endpoint, and the real API behind it.

    The API is served with its own lifespan here rather than handed the fixture's database
    handle. An asyncpg pool belongs to the loop that drives it, so an application served in one
    thread and asserted against from another needs a pool of its own -- which is what a second
    process has anyway. The test then reads the same database over its own connection, which is
    the honest way to check that a tool call left something behind rather than that it returned
    something.
    """
    async with serve(create_app(api_settings())) as api_base, mcp_over_http(api_base) as server:
        yield server


async def test_a_tool_call_becomes_durable_evidence(chain: McpServer, physical: Intake) -> None:
    """One call, over the real protocol, and the rows it left behind.

    The correlation id in the envelope the model was handed is the one on the audit row for the
    case, and the statement stored is the sentence that went in. That chain -- conversation to
    ledger -- is what "correlate tool calls with durable evidence" has to mean.
    """
    said = "today's raspberry delivery didn't arrive"
    async with chain.session() as session:
        result = await session.call_tool("report", {"text": said})

    assert result.is_error is not True
    envelope = result.structured_content
    assert envelope is not None
    case_id = UUID(envelope["case_id"])
    assert envelope["attested_by"] == BAKER
    assert envelope["state"] == "RECEIVED"

    reports = await physical.reports(case_id)
    assert [row.raw_text for row in reports] == [said]
    audits = await physical.audits(case_id)
    opened = [row for row in audits if row.type == AUDIT_CASE_OPENED]
    assert opened
    assert str(opened[0].correlation_id) == envelope["correlation_id"]


async def test_status_through_the_transport_is_the_engine_s_own_rendering(
    chain: McpServer, physical: Intake
) -> None:
    """What the tool returns is what the engine rendered, not a second description of it."""
    case_id = await physical.resolved_case()
    await physical.drain()

    async with chain.session() as session:
        result = await session.call_tool("status", {"case_id": str(case_id)})

    body = result.structured_content
    assert body is not None
    assert body["headline"] == "PLANNED"
    assert body["untouched_count"] > 0
    assert "Nothing has been done yet." in body["speech"]
    assert body["speech"].startswith("Planned, and waiting for you.")


async def test_the_case_outlives_the_connection_that_opened_it(
    chain: McpServer, physical: Intake
) -> None:
    """Reconnect, honestly: nothing is held by the transport, so nothing is lost when it goes.

    The first session opens a case and its connection is then closed completely. A second
    session -- new handshake, no session id, nothing carried over -- reads the same case and is
    told what the durable state now says, including work a worker process did in between.
    """
    async with chain.session() as first:
        opened = await first.call_tool("report", {"text": CANONICAL_REPORT})
    assert opened.structured_content is not None
    case_id = UUID(opened.structured_content["case_id"])
    assert opened.structured_content["state"] == "RECEIVED"

    await physical.drain_intake(case_id)
    await physical.answer(case_id, RASPBERRY_ONLY)
    await physical.drain()

    async with chain.session() as second:
        seen = await second.call_tool("status", {"case_id": str(case_id)})
    assert seen.is_error is not True
    assert seen.structured_content is not None
    assert seen.structured_content["case_id"] == str(case_id)
    assert seen.structured_content["headline"] == "PLANNED"


async def test_a_tool_call_from_another_surface_reaches_nothing(physical: Intake) -> None:
    """A running MCP process with the wrong service credential is refused by the engine.

    Defence in depth with the point of it made explicit: the intent API does not trust the MCP
    process because of what it is, it trusts it because of what it presents.
    """
    async with serve(create_app(api_settings())) as api_base:
        settings = mcp_settings(
            mcp_intent_api_base_url=api_base, internal_service_token="a-token-nobody-issued"
        )
        async with (
            mcp_over_http(api_base, settings=settings) as server,
            server.session() as session,
        ):
            result = await session.call_tool("report", {"text": CANONICAL_REPORT})

    assert result.is_error is True
    assert "UNAUTHORIZED_SURFACE" in "\n".join(
        block.text for block in result.content if block.type == "text"
    )
    async with physical.database.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(CaseReport)) == 0
