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
from _intake_support import (
    BAKER,
    CANONICAL_REPORT,
    CORRECTION,
    OWNER,
    RASPBERRY_ONLY,
    Intake,
)
from _intake_support import physical as physical
from _mcp_support import SERVICE_TOKEN, McpServer, mcp_over_http, mcp_settings, serve
from fastapi import FastAPI
from sqlalchemy import func, select

from promisepatch.config import Settings
from promisepatch.db.models import Case, CaseReport
from promisepatch.domain.observation import AUDIT_CASE_OPENED
from promisepatch.main import create_app

REPORT = "/internal/intents/report"
CLARIFY = "/internal/intents/clarify"
CONFIRM = "/internal/intents/confirm"
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

    async def clarify(
        self,
        case_id: UUID | str,
        text: str = RASPBERRY_ONLY,
        *,
        command_id: UUID | None = None,
        **kwargs: Any,
    ) -> httpx2.Response:
        body: dict[str, Any] = {
            "command_id": str(command_id or uuid4()),
            "case_id": str(case_id),
            "text": text,
        }
        body.update(kwargs.pop("extra", {}))
        return await self.client.post(CLARIFY, json=body, headers=_service(**kwargs))

    async def confirm(
        self,
        case_id: UUID | str,
        plan_id: str,
        *,
        command_id: UUID | None = None,
        **kwargs: Any,
    ) -> httpx2.Response:
        body: dict[str, Any] = {
            "command_id": str(command_id or uuid4()),
            "case_id": str(case_id),
            "plan_id": plan_id,
        }
        body.update(kwargs.pop("extra", {}))
        return await self.client.post(CONFIRM, json=body, headers=_service(**kwargs))

    async def status(self, case_id: UUID | str, **kwargs: Any) -> httpx2.Response:
        return await self.client.post(
            STATUS, json={"case_id": str(case_id)}, headers=_service(**kwargs)
        )

    async def plan_of(self, case_id: UUID) -> str:
        """The plan identity this surface would have been shown. Read, never computed here."""
        read = await self.status(case_id)
        assert read.status_code == 200, read.text
        plan_id = read.json()["plan_id"]
        assert plan_id, "a planned case has to offer something to confirm"
        return str(plan_id)


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


# ---------------------------------------------------------------------- what clarify writes


async def test_clarify_stores_the_answer_and_concludes_nothing(boundary: Boundary) -> None:
    """The answer is durable before it is read, exactly as the original statement was.

    The case is still ``CLARIFYING`` when this returns: the interpreter runs in the worker,
    and a transport that had already concluded something would have concluded it outside the
    transaction that can be rolled back.
    """
    opened = await boundary.physical.report()
    await boundary.physical.drain_intake(opened.case_id)

    said = "  just raspberries - the strawberries CAME  "
    response = await boundary.clarify(opened.case_id, said)
    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "CLARIFYING"
    assert body["created"] is True
    assert body["attested_by"] == BAKER
    assert "Nothing has changed yet" in body["speech"]

    reports = await boundary.physical.reports(opened.case_id)
    assert [row.raw_text for row in reports] == [CANONICAL_REPORT, said]
    assert reports[1].reported_by == BAKER


async def test_the_answer_is_attributed_to_the_server_s_worker_whatever_was_sent(
    boundary: Boundary,
) -> None:
    opened = await boundary.physical.report()
    await boundary.physical.drain_intake(opened.case_id)
    refused = await boundary.clarify(
        opened.case_id, RASPBERRY_ONLY, extra={"worker_id": OWNER, "observed_at": "2020-01-01"}
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "INVALID_REQUEST"


async def test_answering_a_case_that_is_not_asking_anything_is_refused(
    boundary: Boundary,
) -> None:
    """A case with no open question cannot be answered, however plausible the words are.

    This is the invented-evidence case at its most tempting: the sentence is a real thing a
    baker might say, and there is simply nothing it is an answer to.
    """
    opened = await boundary.physical.report()
    response = await boundary.clarify(opened.case_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NOT_AWAITING_CLARIFICATION"
    assert len(await boundary.physical.reports(opened.case_id)) == 1


async def test_answering_a_case_this_surface_did_not_open_is_refused(
    boundary: Boundary,
) -> None:
    opened = await boundary.physical.report(worker_id=OWNER)
    await boundary.physical.drain_intake(opened.case_id)
    response = await boundary.clarify(opened.case_id)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CASE_NOT_PERMITTED"


async def test_answering_a_case_that_does_not_exist_is_not_found(boundary: Boundary) -> None:
    response = await boundary.clarify(uuid4())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CASE_NOT_FOUND"


async def test_a_redelivered_answer_is_one_answer(boundary: Boundary) -> None:
    opened = await boundary.physical.report()
    await boundary.physical.drain_intake(opened.case_id)
    command_id = uuid4()
    first = await boundary.clarify(opened.case_id, command_id=command_id)
    second = await boundary.clarify(opened.case_id, command_id=command_id)
    assert first.json()["created"] is True
    assert second.status_code == 202
    assert second.json()["created"] is False
    assert len(await boundary.physical.reports(opened.case_id)) == 2


async def test_one_command_id_carrying_two_different_answers_is_a_conflict(
    boundary: Boundary,
) -> None:
    opened = await boundary.physical.report()
    await boundary.physical.drain_intake(opened.case_id)
    command_id = uuid4()
    await boundary.clarify(opened.case_id, RASPBERRY_ONLY, command_id=command_id)
    clash = await boundary.clarify(opened.case_id, "the whole delivery", command_id=command_id)
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "COMMAND_CONFLICT"


async def test_status_hands_over_the_question_rather_than_leaving_it_to_be_guessed(
    boundary: Boundary,
) -> None:
    """Band 1 of the workspace, through the intent API: the ambiguity is a question.

    Every value is the engine's -- the wording and the options were derived from the delivery's
    own rows when the question was asked. Nothing here is written by the test.
    """
    opened = await boundary.physical.report()
    await boundary.physical.drain_intake(opened.case_id)
    body = (await boundary.status(opened.case_id)).json()

    assert body["headline"] == "CLARIFYING"
    assert body["awaiting_confirmation"] is False
    assert body["plan_id"] is None
    assert body["question"] is not None
    assert body["question"]["question"]
    assert len(body["question"]["options"]) >= 2
    assert body["question"]["question"] in body["speech"]
    for option in body["question"]["options"]:
        assert option["label"] in body["speech"]


async def test_an_answered_question_stops_being_a_question(boundary: Boundary) -> None:
    case_id = await boundary.physical.resolved_case()
    await boundary.physical.drain()
    assert (await boundary.status(case_id)).json()["question"] is None


# --------------------------------------------------------------------- what confirm authorises


async def test_confirming_the_plan_on_offer_authorises_and_completes_nothing(
    boundary: Boundary,
) -> None:
    """The one authority in the surface that is a person's, and the line it does not cross.

    Afterwards the case is ``EXECUTING`` and every track it covers is authorised. No order has
    been amended, no customer has been asked, and the status says so in the contract's own
    words -- because the worker process has not run yet and nothing has been carried out.
    """
    case_id = await boundary.physical.resolved_case()
    await boundary.physical.drain()
    plan_id = await boundary.plan_of(case_id)

    response = await boundary.confirm(case_id, plan_id)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["state"] == "EXECUTING"
    assert body["created"] is True
    assert body["confirmed_by"] == BAKER
    assert body["applying"] + body["awaiting_approval"] + body["escalated"] > 0
    assert "Nothing has been changed yet" in body["speech"]

    after = (await boundary.status(case_id)).json()
    assert after["awaiting_confirmation"] is False
    assert after["plan_id"] is None
    for promise in after["threatened"]:
        assert promise["state"] != "RECOVERED"
        assert promise["state"] != "REQUESTED"
    assert "changed" not in after["speech"]


async def test_a_confirmation_before_there_is_a_plan_is_refused(boundary: Boundary) -> None:
    opened = await boundary.physical.report()
    response = await boundary.confirm(opened.case_id, "a" * 64)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAN_NOT_CONFIRMABLE"


async def test_a_plan_identity_this_case_never_offered_is_refused(boundary: Boundary) -> None:
    """A confirmation cannot be assembled; it can only be quoted back.

    The identity here is a real one -- another case's, for a plan that genuinely exists -- so
    what is being refused is not a malformed string but a yes to the wrong plan.
    """
    mine = await boundary.physical.resolved_case()
    theirs = await boundary.physical.resolved_case()
    await boundary.physical.drain()
    borrowed = await boundary.plan_of(theirs)

    response = await boundary.confirm(mine, borrowed)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAN_SUPERSEDED"
    assert (await boundary.physical.case(mine)).state == "PLANNED"


async def test_a_plan_that_was_re_made_after_it_was_read_cannot_be_confirmed(
    boundary: Boundary,
) -> None:
    """The staleness this binding exists for: the worker read one plan and the world moved.

    A correcting attestation re-analyses the case against the truth that now stands, so the
    plan on offer afterwards is a different plan even though the case is ``PLANNED`` again and
    looks confirmable. The yes the worker gave was to the first one.
    """
    case_id = await boundary.physical.resolved_case()
    await boundary.physical.drain()
    read = await boundary.plan_of(case_id)

    await boundary.physical.correct(case_id, CORRECTION)
    await boundary.physical.drain()
    assert (await boundary.physical.case(case_id)).state == "PLANNED"
    assert await boundary.plan_of(case_id) != read

    response = await boundary.confirm(case_id, read)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLAN_SUPERSEDED"
    assert (await boundary.physical.case(case_id)).state == "PLANNED"


async def test_a_redelivered_confirmation_confirms_once(boundary: Boundary) -> None:
    case_id = await boundary.physical.resolved_case()
    await boundary.physical.drain()
    plan_id = await boundary.plan_of(case_id)
    command_id = uuid4()

    first = await boundary.confirm(case_id, plan_id, command_id=command_id)
    second = await boundary.confirm(case_id, plan_id, command_id=command_id)
    assert first.json()["created"] is True
    assert second.status_code == 202
    assert second.json()["created"] is False
    assert "already confirmed" in second.json()["speech"]


async def test_replaying_a_confirmation_against_a_different_plan_is_a_conflict(
    boundary: Boundary,
) -> None:
    """One command id, two different plans: two things are claiming one identity.

    Not a retry, and accepting either would silently discard the other. This is the intake
    conflict rule applied to the one command that carries a human authorisation.
    """
    case_id = await boundary.physical.resolved_case()
    await boundary.physical.drain()
    plan_id = await boundary.plan_of(case_id)
    command_id = uuid4()

    await boundary.confirm(case_id, plan_id, command_id=command_id)
    clash = await boundary.confirm(case_id, "b" * 64, command_id=command_id)
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "COMMAND_CONFLICT"


async def test_confirming_a_case_twice_under_new_identities_does_not_confirm_it_twice(
    boundary: Boundary,
) -> None:
    """The second yes has nothing to confirm: the case has already left ``PLANNED``."""
    case_id = await boundary.physical.resolved_case()
    await boundary.physical.drain()
    plan_id = await boundary.plan_of(case_id)

    await boundary.confirm(case_id, plan_id)
    again = await boundary.confirm(case_id, plan_id)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "PLAN_NOT_CONFIRMABLE"


async def test_confirming_a_case_this_surface_did_not_open_is_refused(
    boundary: Boundary,
) -> None:
    """A case id is a value a model can put in an argument, so the domain answers."""
    opened = await boundary.physical.report(worker_id=OWNER)
    await boundary.physical.drain()
    await boundary.physical.answer(opened.case_id, RASPBERRY_ONLY, worker_id=OWNER)
    await boundary.physical.drain()
    plan_id = await boundary.physical.plan_id(opened.case_id)

    response = await boundary.confirm(opened.case_id, plan_id)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CASE_NOT_PERMITTED"
    assert (await boundary.physical.case(opened.case_id)).state == "PLANNED"


async def test_confirming_a_case_that_does_not_exist_is_not_found(boundary: Boundary) -> None:
    response = await boundary.confirm(uuid4(), "a" * 64)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CASE_NOT_FOUND"


async def test_a_confirmation_without_the_service_token_writes_nothing(
    boundary: Boundary,
) -> None:
    case_id = await boundary.physical.resolved_case()
    await boundary.physical.drain()
    plan_id = await boundary.plan_of(case_id)

    response = await boundary.confirm(case_id, plan_id, token=None)
    assert response.status_code == 401
    assert (await boundary.physical.case(case_id)).state == "PLANNED"


async def test_the_plan_a_surface_is_shown_is_the_plan_a_confirmation_is_measured_against(
    boundary: Boundary,
) -> None:
    """Two producers of one identity, from two different reads, asserted to agree.

    The read service joins across tracks, options and orders; the confirming transaction scans
    the locked rows. If those ever drifted apart, every honest confirmation would be refused as
    stale and the failure would look like a domain bug rather than a shape mismatch.
    """
    case_id = await boundary.physical.resolved_case()
    await boundary.physical.drain()

    from promisepatch.domain.analysis import read_case_status
    from promisepatch.domain.recovery import current_plan_id

    shown = await boundary.plan_of(case_id)
    read = await read_case_status(boundary.physical.database, case_id=case_id)
    async with boundary.physical.database.connect() as connection:
        checked = await current_plan_id(connection, case_id=case_id, case_version=read.case_version)
    assert shown == read.plan_id
    assert shown == checked


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


async def test_the_canonical_conversation_runs_over_the_real_protocol(
    chain: McpServer, physical: Intake
) -> None:
    """Report, a consequential question, an answer, a plan, an explicit yes -- all over MCP.

    The acceptance path of this slice, driven end to end by the official SDK client against
    the real Streamable HTTP endpoint: nothing is inserted into the database by the test and
    no domain service is called directly. Each turn is a tool call, and what carries the
    conversation between them is the durable case.

    The worker process runs between the turns, exactly as it does in the product. It is the
    thing that reads the words; the conversation never concludes anything itself.
    """
    async with chain.session() as session:
        opened = await session.call_tool("report", {"text": CANONICAL_REPORT})
    assert opened.structured_content is not None
    case_id = UUID(opened.structured_content["case_id"])
    assert opened.structured_content["state"] == "RECEIVED"

    # The interpreter runs and finds the sentence ambiguous. Nothing has been settled.
    await physical.drain_intake(case_id)
    async with chain.session() as session:
        asking = await session.call_tool("status", {"case_id": str(case_id)})
    assert asking.structured_content is not None
    assert asking.structured_content["headline"] == "CLARIFYING"
    question = asking.structured_content["question"]
    assert question is not None and question["question"]
    assert asking.structured_content["plan_id"] is None

    async with chain.session() as session:
        answered = await session.call_tool(
            "clarify", {"case_id": str(case_id), "answer": RASPBERRY_ONLY}
        )
    assert answered.is_error is not True
    assert answered.structured_content is not None
    assert answered.structured_content["state"] == "CLARIFYING"
    assert answered.structured_content["attested_by"] == BAKER

    # The answer resolves the scope, the case is analysed and planned, and a plan is offered.
    await physical.drain()
    async with chain.session() as session:
        planned = await session.call_tool("status", {"case_id": str(case_id)})
    assert planned.structured_content is not None
    assert planned.structured_content["headline"] == "PLANNED"
    assert planned.structured_content["awaiting_confirmation"] is True
    assert planned.structured_content["question"] is None
    plan_id = planned.structured_content["plan_id"]
    assert plan_id
    assert planned.structured_content["untouched_count"] > 0
    for promise in planned.structured_content["threatened"]:
        assert promise["state"] in {"PLANNED", "AWAITING_PLAN"}, "nothing is done before a yes"

    async with chain.session() as session:
        confirmed = await session.call_tool(
            "confirm", {"case_id": str(case_id), "plan_id": plan_id}
        )
    assert confirmed.is_error is not True, _tool_text(confirmed)
    assert confirmed.structured_content is not None
    assert confirmed.structured_content["state"] == "EXECUTING"
    assert confirmed.structured_content["confirmed_by"] == BAKER
    assert "Nothing has been changed yet" in confirmed.structured_content["speech"]

    # Authorised, and nothing carried out: the worker has still not run since the yes.
    async with chain.session() as session:
        after = await session.call_tool("status", {"case_id": str(case_id)})
    assert after.structured_content is not None
    assert after.structured_content["awaiting_confirmation"] is False
    states = {promise["state"] for promise in after.structured_content["threatened"]}
    assert "RECOVERED" not in states
    assert "REQUESTED" not in states
    assert (
        after.structured_content["untouched_count"] == planned.structured_content["untouched_count"]
    )

    # And the durable evidence is there afterwards, over a separate connection.
    reports = await physical.reports(case_id)
    assert [row.raw_text for row in reports] == [CANONICAL_REPORT, RASPBERRY_ONLY]
    assert all(row.reported_by == BAKER for row in reports)
    assert (await physical.case(case_id)).state == "EXECUTING"


async def test_a_stale_plan_confirmed_over_the_transport_is_refused_and_changes_nothing(
    chain: McpServer, physical: Intake
) -> None:
    """A confirmation quoting a plan the case has moved past, through the real tool.

    The refusal arrives as the frozen ``CASE_NOT_IN_STATE`` code with none of the engine's own
    wording, and the case is still waiting for a yes to the plan it is actually offering.
    """
    case_id = await physical.resolved_case()
    await physical.drain()
    async with chain.session() as session:
        read = await session.call_tool("status", {"case_id": str(case_id)})
    assert read.structured_content is not None
    stale = read.structured_content["plan_id"]

    await physical.correct(case_id, CORRECTION)
    await physical.drain()

    async with chain.session() as session:
        refused = await session.call_tool("confirm", {"case_id": str(case_id), "plan_id": stale})
    assert refused.is_error is True
    assert "CASE_NOT_IN_STATE" in _tool_text(refused)
    assert "PLAN_SUPERSEDED" not in _tool_text(refused)
    assert (await physical.case(case_id)).state == "PLANNED"

    # Re-read and confirm the plan that is actually on offer: the remedy is one turn.
    async with chain.session() as session:
        current = await session.call_tool("status", {"case_id": str(case_id)})
        assert current.structured_content is not None
        accepted = await session.call_tool(
            "confirm",
            {"case_id": str(case_id), "plan_id": current.structured_content["plan_id"]},
        )
    assert accepted.is_error is not True, _tool_text(accepted)
    assert (await physical.case(case_id)).state == "EXECUTING"


async def test_a_conversation_cannot_answer_a_case_that_asked_nothing(
    chain: McpServer, physical: Intake
) -> None:
    """The model has the tool and the case; it still has no question to answer."""
    async with chain.session() as session:
        opened = await session.call_tool("report", {"text": CANONICAL_REPORT})
        assert opened.structured_content is not None
        case_id = opened.structured_content["case_id"]
        result = await session.call_tool("clarify", {"case_id": case_id, "answer": RASPBERRY_ONLY})
    assert result.is_error is True
    assert "CASE_NOT_IN_STATE" in _tool_text(result)
    assert len(await physical.reports(UUID(case_id))) == 1


async def test_a_confirmation_survives_the_connection_that_gave_it(
    chain: McpServer, physical: Intake
) -> None:
    """Authority is a row. A client that vanishes after saying yes has still said it."""
    case_id = await physical.resolved_case()
    await physical.drain()
    async with chain.session() as first:
        read = await first.call_tool("status", {"case_id": str(case_id)})
        assert read.structured_content is not None
        await first.call_tool(
            "confirm",
            {"case_id": str(case_id), "plan_id": read.structured_content["plan_id"]},
        )

    async with chain.session() as second:
        seen = await second.call_tool("status", {"case_id": str(case_id)})
    assert seen.structured_content is not None
    assert seen.structured_content["headline"] == "WORKING"
    assert seen.structured_content["awaiting_confirmation"] is False


def _tool_text(result: Any) -> str:
    return "\n".join(block.text for block in result.content if block.type == "text")
