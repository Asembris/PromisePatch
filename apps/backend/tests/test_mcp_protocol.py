"""The MCP boundary as a protocol, not as a list of registered functions.

Every test here talks to the server ``pp mcp`` runs, over a loopback socket, with the official
SDK's client or with a plain HTTP client -- because ``tools/list`` returning two names proves
nothing about initialization, negotiation, framing, credentials or ``Origin``, and those are
what a transport boundary is for.

The suite is offline by construction: no database, no AWS account, no model, no credential of
anybody's. The hop behind the server is a recording intent API answering the real wire shape,
so what a tool *forwarded* is assertable without one. What a tool *caused* is a different
question, answered against a real database in ``test_intent_api.py``.

The order of the sections is the order a caller meets them: the pin, the handshake, discovery,
the four tools, the ways a call is refused, and the checks that happen before any of that.
"""

from __future__ import annotations

import json
from importlib.metadata import version
from typing import Any
from uuid import UUID, uuid4

import pytest
from _mcp_support import (
    ALLOWED_ORIGIN,
    APPROVING_WORKER,
    BEARER,
    JSON_RPC_HEADERS,
    PLAN_ID,
    SERVICE_TOKEN,
    SURFACE_WORKER,
    McpServer,
    RecordingIntents,
    mcp_against,
    mcp_with_no_engine_listening,
)
from _mcp_support import mcp as mcp
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, LATEST_HANDSHAKE_VERSION

from promisepatch.mcp import PROTOCOL_REVISION, ToolCode, command_id_for

CANONICAL = "today's raspberry delivery didn't arrive"
SERVICE_TOKEN_HEADER_LOWER = "x-service-token"


def _text(result: object) -> str:
    """The text a tool result carries, joined. Refusals travel here and nowhere else."""
    return "\n".join(block.text for block in result.content if block.type == "text")  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- the pin


def test_the_pinned_sdk_speaks_the_revision_we_claim() -> None:
    """The claim is a protocol revision, so the assertion is about the revision.

    A pinned package and a pinned protocol are different things, and the SDK proves it: this
    release also speaks a later revision, reached by a different entry point. What matters is
    that the ``initialize`` handshake this server serves settles on 2025-11-25 -- so that is
    what is asserted, and an SDK bump that moved it fails here rather than quietly changing
    what a judge would find on the wire.
    """
    assert version("mcp") == "2.2.0"
    assert version("mcp-types") == "2.2.0"
    assert PROTOCOL_REVISION == "2025-11-25"
    assert LATEST_HANDSHAKE_VERSION == PROTOCOL_REVISION
    assert PROTOCOL_REVISION in HANDSHAKE_PROTOCOL_VERSIONS


# ------------------------------------------------------------------- initialize and negotiate


async def test_initialization_negotiates_the_required_revision(mcp: McpServer) -> None:
    async with mcp.raw() as client:
        response = await client.post(
            mcp.url,
            headers={"Authorization": f"Bearer {BEARER}", **JSON_RPC_HEADERS},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_REVISION,
                    "capabilities": {},
                    "clientInfo": {"name": "protocol-test", "version": "1"},
                },
            },
        )
    assert response.status_code == 200
    body = _sse_result(response.text)
    assert body["protocolVersion"] == PROTOCOL_REVISION
    assert body["serverInfo"]["name"] == "promisepatch"
    assert "tools" in body["capabilities"]


async def test_a_client_offering_an_unknown_revision_gets_a_counter_offer(mcp: McpServer) -> None:
    """Negotiation, not rejection. The server answers with a revision it actually speaks."""
    async with mcp.raw() as client:
        response = await client.post(
            mcp.url,
            headers={"Authorization": f"Bearer {BEARER}", **JSON_RPC_HEADERS},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "1999-01-01",
                    "capabilities": {},
                    "clientInfo": {"name": "protocol-test", "version": "1"},
                },
            },
        )
    assert _sse_result(response.text)["protocolVersion"] == PROTOCOL_REVISION


async def test_the_instructions_state_the_boundary(mcp: McpServer) -> None:
    """A model is told what it cannot do here, not only which verbs exist.

    The instructions are part of the authority posture: "you cannot confirm a plan or record
    consent" belongs where the model reads it, rather than only in a document nobody ships.
    """
    async with mcp.raw() as client:
        response = await client.post(
            mcp.url,
            headers={"Authorization": f"Bearer {BEARER}", **JSON_RPC_HEADERS},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_REVISION,
                    "capabilities": {},
                    "clientInfo": {"name": "protocol-test", "version": "1"},
                },
            },
        )
    instructions = _sse_result(response.text)["instructions"]
    assert isinstance(instructions, str)
    assert "verbatim" in instructions
    # The sentences that are the authority posture, not the verb list. A model that reads only
    # these still cannot decide who is speaking, turn its own call into a worker's agreement,
    # confirm a plan it never read, or mistake a worker's yes for a customer's.
    assert "Calling it is not the worker agreeing" in instructions
    assert "can only spend one, never create one" in instructions
    assert "already given on their own screen" in instructions
    assert "Worker confirmation is not customer consent." in instructions
    assert "cannot record a customer's consent, choose who is speaking" in instructions


# ------------------------------------------------------------------------------- discovery


async def test_discovery_offers_exactly_the_five_frozen_tools(mcp: McpServer) -> None:
    """Five, which is the whole frozen surface, and nothing beyond it.

    No order, resource, recipe, reservation or consent verb appears -- not disabled and not
    present-and-refusing. A surface that can only do five things is a surface a model cannot be
    talked into doing a sixth with.
    """
    async with mcp.session() as session:
        tools = await session.list_tools()
    assert sorted(tool.name for tool in tools.tools) == [
        "clarify",
        "confirm",
        "report",
        "status",
        "withdraw",
    ]


async def test_a_withdrawal_can_name_a_case_and_nothing_else(mcp: McpServer) -> None:
    """No reason, no actor, and above all no field that could claim a physical fact.

    Withdrawing a plan is a decision about what may be done to a customer promise. Correcting
    the kitchen is a separate attestation under a separate authority, and an argument here that
    could carry one would put both in a single call.
    """
    async with mcp.session() as session:
        tools = await session.list_tools()
    withdraw = next(tool for tool in tools.tools if tool.name == "withdraw")
    assert sorted(withdraw.input_schema["properties"]) == ["case_id", "client_request_id"]
    assert sorted(withdraw.input_schema["required"]) == ["case_id"]


async def test_no_tool_lets_a_caller_choose_a_plan_it_was_not_shown(mcp: McpServer) -> None:
    """``confirm`` takes a plan *identity*, and nothing that could describe a plan instead.

    The distinction is the whole binding. An argument naming a track, an option or a recipe
    version would let a confirmation assemble a plan of its own; an opaque identity can only
    ever quote back one the engine rendered.
    """
    async with mcp.session() as session:
        tools = await session.list_tools()
    confirm = next(tool for tool in tools.tools if tool.name == "confirm")
    assert sorted(confirm.input_schema["properties"]) == [
        "case_id",
        "client_request_id",
        "plan_id",
    ]
    assert sorted(confirm.input_schema["required"]) == ["case_id", "plan_id"]


async def test_no_tool_argument_can_carry_an_actor_a_time_or_a_version(mcp: McpServer) -> None:
    """The surface has no field for the things a conversation must not decide.

    Not "the field is validated" -- the field does not exist. A schema with no actor in it is
    an authority a model was never offered, which is a stronger guarantee than one it is
    offered and refused.
    """
    async with mcp.session() as session:
        tools = await session.list_tools()
    forbidden = {
        "worker",
        "worker_id",
        "actor",
        "attested_by",
        "on_behalf_of",
        "observed_at",
        "timestamp",
        "recipe_version",
        "version_id",
        "customer",
        "consent",
        "decision",
    }
    for tool in tools.tools:
        assert not forbidden & set(tool.input_schema.get("properties", {}))


async def test_each_tool_publishes_an_output_schema(mcp: McpServer) -> None:
    """A client can validate a result before repeating it to anybody."""
    async with mcp.session() as session:
        tools = await session.list_tools()
    for tool in tools.tools:
        assert tool.output_schema is not None
        assert "correlation_id" in tool.output_schema["properties"]


# ---------------------------------------------------------------------------------- report


async def test_report_answers_in_the_envelope(mcp: McpServer) -> None:
    async with mcp.session() as session:
        result = await session.call_tool("report", {"text": CANONICAL})
    assert result.is_error is not True
    body = result.structured_content
    assert body is not None
    assert body["ok"] is True
    assert body["intent"] == "report"
    assert body["state"] == "RECEIVED"
    assert UUID(body["correlation_id"])
    assert UUID(body["case_id"])


async def test_report_forwards_the_sentence_byte_for_byte(mcp: McpServer) -> None:
    """What was said is evidence, and the first thing a transport does to evidence is nothing.

    Leading and trailing whitespace, the apostrophe and the accents all survive. A transport
    that trimmed would be editing an attestation, and the trim would be invisible afterwards
    because the only record of the original would be the one it changed.
    """
    said = "  today's raspberry delivery didn't arrive — crème pâtissière is fine  "
    assert mcp.intents is not None
    async with mcp.session() as session:
        await session.call_tool("report", {"text": said})
    assert mcp.intents.last.body["text"] == said


async def test_report_carries_the_service_credential_and_its_correlation_id(
    mcp: McpServer,
) -> None:
    assert mcp.intents is not None
    async with mcp.session() as session:
        result = await session.call_tool("report", {"text": CANONICAL})
    forwarded = mcp.intents.last
    assert forwarded.headers["x-service-token"] == SERVICE_TOKEN
    assert result.structured_content is not None
    assert forwarded.headers["x-correlation-id"] == result.structured_content["correlation_id"]


async def test_a_tool_argument_naming_a_worker_changes_nothing(mcp: McpServer) -> None:
    """A call that names an actor is naming a value the server ignores.

    It is not an error -- a model that guesses a field is not attacking anything -- and it is
    not honoured either. The forwarded request carries no actor at all, and the attestor on the
    answer is the one this deployment configured.
    """
    assert mcp.intents is not None
    async with mcp.session() as session:
        result = await session.call_tool(
            "report", {"text": CANONICAL, "worker_id": "owner", "attested_by": "owner"}
        )
    assert result.is_error is not True
    forwarded = mcp.intents.last
    assert set(forwarded.body) == {"command_id", "text"}
    assert result.structured_content is not None
    assert result.structured_content["attested_by"] == SURFACE_WORKER


async def test_a_repeated_client_request_id_reaches_the_same_command(mcp: McpServer) -> None:
    """Idempotency is a value the caller controls, and it identifies one call rather than a case."""
    assert mcp.intents is not None
    async with mcp.session() as session:
        await session.call_tool("report", {"text": CANONICAL, "client_request_id": "turn-7"})
        first = mcp.intents.last.body["command_id"]
        await session.call_tool("report", {"text": CANONICAL, "client_request_id": "turn-7"})
        second = mcp.intents.last.body["command_id"]
        await session.call_tool("report", {"text": CANONICAL})
        third = mcp.intents.last.body["command_id"]
    assert first == second
    assert third != first


def test_an_idempotency_key_cannot_reach_another_caller_s_case() -> None:
    """The derived command id is namespaced by the authenticated principal.

    Without that, an idempotency key would be an addressing scheme: send somebody else's key
    and land on their case. It is minted from the credential's own digest, so the same key from
    two clients is two different commands.
    """
    ours = command_id_for("bearer:aaaaaaaaaaaa", "turn-7")
    theirs = command_id_for("bearer:bbbbbbbbbbbb", "turn-7")
    assert ours != theirs
    assert ours == command_id_for("bearer:aaaaaaaaaaaa", "turn-7")
    assert command_id_for("bearer:aaaaaaaaaaaa", None) != command_id_for(
        "bearer:aaaaaaaaaaaa", None
    )


async def test_a_report_with_nothing_in_it_is_refused(mcp: McpServer) -> None:
    async with mcp.session() as session:
        result = await session.call_tool("report", {"text": "   "})
    assert result.is_error is True
    assert ToolCode.INVALID_ARGUMENT.value in _text(result)


# --------------------------------------------------------------------------------- clarify


async def test_clarify_forwards_the_answer_byte_for_byte(mcp: McpServer) -> None:
    """An answer is another thing somebody said, and the first thing a transport does is nothing."""
    assert mcp.intents is not None
    said = "  just raspberries - the strawberries CAME  "
    case_id = str(uuid4())
    async with mcp.session() as session:
        result = await session.call_tool("clarify", {"case_id": case_id, "answer": said})
    assert result.is_error is not True
    assert mcp.intents.last.path == "clarify"
    assert mcp.intents.last.body["text"] == said
    assert mcp.intents.last.body["case_id"] == case_id
    body = result.structured_content
    assert body is not None
    assert body["intent"] == "clarify"
    assert body["state"] == "CLARIFYING"
    assert body["attested_by"] == SURFACE_WORKER


async def test_an_answer_that_names_a_worker_is_still_attested_by_the_server(
    mcp: McpServer,
) -> None:
    """An answer is an attestation, and who made it is not a thing the wire can carry.

    Same rule as ``report``, asserted separately because ``clarify`` is where a conversation
    would most plausibly try to answer *for* somebody: the question is already on the screen
    and the answer is one word long.
    """
    assert mcp.intents is not None
    async with mcp.session() as session:
        result = await session.call_tool(
            "clarify",
            {"case_id": str(uuid4()), "answer": "just raspberries", "worker_id": "owner"},
        )
    assert set(mcp.intents.last.body) == {"command_id", "case_id", "text"}
    assert result.structured_content is not None
    assert result.structured_content["attested_by"] == SURFACE_WORKER


async def test_a_confirmation_that_names_a_worker_names_nobody(mcp: McpServer) -> None:
    """ "Confirm on Maya's behalf" names a value the server ignores. Nothing else is forwarded.

    And the answer names somebody the caller never mentioned: the worker whose recorded approval
    the engine spent, with the channel that authenticated them. A surface that reported back the
    identity it was configured with would be telling a conversation that a person had agreed on
    the strength of a setting in a file.
    """
    assert mcp.intents is not None
    async with mcp.session() as session:
        result = await session.call_tool(
            "confirm",
            {"case_id": str(uuid4()), "plan_id": PLAN_ID, "on_behalf_of": "owner"},
        )
    assert set(mcp.intents.last.body) == {"command_id", "case_id", "plan_id"}
    assert result.structured_content is not None
    assert result.structured_content["confirmed_by"] == APPROVING_WORKER
    assert result.structured_content["confirmed_by"] != SURFACE_WORKER
    assert result.structured_content["approved_via"] == "BROWSER_SESSION"


async def test_an_empty_answer_is_refused_before_the_engine(mcp: McpServer) -> None:
    assert mcp.intents is not None
    async with mcp.session() as session:
        result = await session.call_tool("clarify", {"case_id": str(uuid4()), "answer": "  "})
    assert result.is_error is True
    assert ToolCode.INVALID_ARGUMENT.value in _text(result)
    assert mcp.intents.calls == []


async def test_clarifying_a_case_that_is_not_asking_is_refused(mcp: McpServer) -> None:
    """The engine's 409 becomes the stable code, and the engine's own words stay behind."""
    assert mcp.intents is not None
    mcp.intents.clarify_status = 409
    mcp.intents.clarify_body = {"error": {"code": "NOT_AWAITING_CLARIFICATION"}}
    async with mcp.session() as session:
        result = await session.call_tool(
            "clarify", {"case_id": str(uuid4()), "answer": "just raspberries"}
        )
    assert result.is_error is True
    assert ToolCode.CASE_NOT_IN_STATE.value in _text(result)
    assert "NOT_AWAITING_CLARIFICATION" not in _text(result)


async def test_a_repeated_clarify_key_reaches_one_command(mcp: McpServer) -> None:
    assert mcp.intents is not None
    case_id = str(uuid4())
    async with mcp.session() as session:
        await session.call_tool(
            "clarify",
            {"case_id": case_id, "answer": "just raspberries", "client_request_id": "turn-4"},
        )
        await session.call_tool(
            "clarify",
            {"case_id": case_id, "answer": "just raspberries", "client_request_id": "turn-4"},
        )
    commands = {call.body["command_id"] for call in mcp.intents.calls}
    assert len(commands) == 1


# --------------------------------------------------------------------------------- confirm


async def test_confirm_forwards_the_plan_identity_it_was_given(mcp: McpServer) -> None:
    """The transport quotes; it does not compute. It has no rows, so it cannot mint one."""
    assert mcp.intents is not None
    case_id = str(uuid4())
    async with mcp.session() as session:
        result = await session.call_tool("confirm", {"case_id": case_id, "plan_id": PLAN_ID})
    assert result.is_error is not True
    assert mcp.intents.last.path == "confirm"
    assert mcp.intents.last.body["plan_id"] == PLAN_ID
    assert mcp.intents.last.body["case_id"] == case_id
    assert mcp.intents.last.headers[SERVICE_TOKEN_HEADER_LOWER] == SERVICE_TOKEN


async def test_confirm_reports_permission_and_never_completion(mcp: McpServer) -> None:
    """Counts, and no field anywhere in the result that could say an order was changed."""
    async with mcp.session() as session:
        result = await session.call_tool("confirm", {"case_id": str(uuid4()), "plan_id": PLAN_ID})
    body = result.structured_content
    assert body is not None
    assert body["intent"] == "confirm"
    assert body["state"] == "EXECUTING"
    assert body["applying"] == 1
    assert body["awaiting_approval"] == 1
    assert body["escalated"] == 1
    assert body["confirmed_by"] == APPROVING_WORKER
    assert body["approved_via"] == "BROWSER_SESSION"
    assert "changed" not in body["speech"].replace("has been changed yet", "")
    assert not {"recovered", "applied", "sent", "amended"} & set(body)


async def test_a_confirmation_without_a_plan_identity_is_refused(mcp: McpServer) -> None:
    """A yes that names only a case is the blanket authorisation this binding exists to stop."""
    assert mcp.intents is not None
    async with mcp.session() as session:
        missing = await session.call_tool("confirm", {"case_id": str(uuid4())})
        blank = await session.call_tool("confirm", {"case_id": str(uuid4()), "plan_id": "   "})
    assert missing.is_error is True
    assert "plan_id" in _text(missing)
    assert blank.is_error is True
    assert ToolCode.INVALID_ARGUMENT.value in _text(blank)
    assert mcp.intents.calls == []


async def test_a_superseded_plan_is_refused_and_says_so_in_the_frozen_vocabulary(
    mcp: McpServer,
) -> None:
    """The engine's ``PLAN_SUPERSEDED`` arrives as ``CASE_NOT_IN_STATE``, with no internals."""
    assert mcp.intents is not None
    mcp.intents.confirm_status = 409
    mcp.intents.confirm_body = {"error": {"code": "PLAN_SUPERSEDED"}}
    async with mcp.session() as session:
        result = await session.call_tool("confirm", {"case_id": str(uuid4()), "plan_id": PLAN_ID})
    assert result.is_error is True
    assert ToolCode.CASE_NOT_IN_STATE.value in _text(result)
    assert "PLAN_SUPERSEDED" not in _text(result)


async def test_a_confirmation_for_a_case_this_surface_may_not_touch_is_refused(
    mcp: McpServer,
) -> None:
    assert mcp.intents is not None
    mcp.intents.confirm_status = 403
    mcp.intents.confirm_body = {"error": {"code": "CASE_NOT_PERMITTED"}}
    async with mcp.session() as session:
        result = await session.call_tool("confirm", {"case_id": str(uuid4()), "plan_id": PLAN_ID})
    assert result.is_error is True
    assert ToolCode.UNAUTHORIZED_SURFACE.value in _text(result)


# -------------------------------------------------------------------------------- withdraw


async def test_withdraw_forwards_the_case_and_invents_nothing_beside_it(mcp: McpServer) -> None:
    """A case and a command identity reach the engine, and no third thing does."""
    assert mcp.intents is not None
    case_id = str(uuid4())
    async with mcp.session() as session:
        result = await session.call_tool("withdraw", {"case_id": case_id})
    assert result.is_error is not True
    assert mcp.intents.last.path == "withdraw"
    assert sorted(mcp.intents.last.body) == ["case_id", "command_id"]
    assert mcp.intents.last.body["case_id"] == case_id


async def test_a_withdrawal_delivers_what_it_could_not_stop_word_for_word(
    mcp: McpServer,
) -> None:
    """The half that makes the answer honest travels intact through this process.

    The engine said an order had already been changed. A transport that dropped, trimmed or
    summarised that sentence would hand a conversation a clean withdrawal to describe, and the
    conversation would describe one.
    """
    assert mcp.intents is not None
    case_id = str(uuid4())
    already = "1 order had already been changed in the order system, and that change stands"
    mcp.intents.withdraw_body = {
        "case_id": case_id,
        "command_id": str(uuid4()),
        "state": "RECONCILING",
        "created": True,
        "withdrawn_by": SURFACE_WORKER,
        "withdrawn": 0,
        "escalated": 2,
        "reversed_writes": ["released 1 production task this case had put on hold"],
        "applied": [already],
        "speech": f"Withdrawn. I could not undo what had already happened: {already}.",
    }
    async with mcp.session() as session:
        result = await session.call_tool("withdraw", {"case_id": case_id})
    body = result.structured_content
    assert body is not None
    assert body["applied"] == [already]
    assert body["escalated"] == 2
    assert body["speech"].endswith(f"{already}.")


async def test_a_withdrawal_the_engine_refused_is_not_reported_as_one(mcp: McpServer) -> None:
    """A case that has already finished is a refusal, never a quietly successful withdrawal."""
    assert mcp.intents is not None
    mcp.intents.withdraw_status = 409
    mcp.intents.withdraw_body = {"error": {"code": "CASE_NOT_WITHDRAWABLE"}}
    async with mcp.session() as session:
        result = await session.call_tool("withdraw", {"case_id": str(uuid4())})
    assert result.is_error is True
    assert ToolCode.CASE_NOT_IN_STATE.value in _text(result)


async def test_the_same_withdrawal_key_reaches_one_command(mcp: McpServer) -> None:
    """A retry of one withdrawal is that withdrawal arriving twice, not a second one."""
    assert mcp.intents is not None
    case_id = str(uuid4())
    async with mcp.session() as session:
        await session.call_tool("withdraw", {"case_id": case_id, "client_request_id": "turn-9"})
        first = mcp.intents.last.body["command_id"]
        await session.call_tool("withdraw", {"case_id": case_id, "client_request_id": "turn-9"})
        second = mcp.intents.last.body["command_id"]
    assert first == second


async def test_a_withdrawal_of_something_that_is_not_a_case_troubles_no_engine(
    mcp: McpServer,
) -> None:
    assert mcp.intents is not None
    async with mcp.session() as session:
        result = await session.call_tool("withdraw", {"case_id": "the raspberry one"})
    assert result.is_error is True
    assert ToolCode.INVALID_ARGUMENT.value in _text(result)
    assert mcp.intents.calls == []


# ---------------------------------------------------------------------------------- status


async def test_status_delivers_the_engine_s_own_sentences(mcp: McpServer) -> None:
    """Deterministic status is delivered, not restated. This is that rule as an assertion."""
    assert mcp.intents is not None
    case_id = str(uuid4())
    mcp.intents.status_body = {
        "case_id": case_id,
        "headline": "PLANNED",
        "speech": "Planned, and waiting for you. Nothing has been done yet.",
        "needs_owner_attention": False,
        "exception_category": "DELIVERY_NOT_RECEIVED",
        "threatened": [],
        "untouched": [],
        "untouched_count": 3,
    }
    async with mcp.session() as session:
        result = await session.call_tool("status", {"case_id": case_id})
    body = result.structured_content
    assert body is not None
    assert body["speech"] == "Planned, and waiting for you. Nothing has been done yet."
    assert body["headline"] == "PLANNED"
    assert body["untouched_count"] == 3


async def test_status_hands_over_the_question_and_the_plan_the_engine_reported(
    mcp: McpServer,
) -> None:
    """A surface asks the engine's question and quotes the engine's plan; it invents neither.

    The two halves of P5.2's conversation, both delivered rather than derived. A ``status``
    that only said "waiting for your answer" would leave the question to be reconstructed from
    the original sentence, and one that withheld the plan identity would leave a confirmation
    with nothing to bind to.
    """
    assert mcp.intents is not None
    case_id = str(uuid4())
    mcp.intents.status_body = {
        "case_id": case_id,
        "headline": "CLARIFYING",
        "speech": "Waiting for your answer before anything is decided.",
        "needs_owner_attention": False,
        "exception_category": "DELIVERY_NOT_RECEIVED",
        "threatened": [],
        "untouched": [],
        "untouched_count": 0,
        "question": {
            "clarification_id": str(uuid4()),
            "question": "Was it the whole Valley Produce delivery, or only the raspberries?",
            "options": [
                {"code": "WHOLE_DELIVERY", "label": "the whole delivery"},
                {"code": "LINE-RASP", "label": "only the raspberries"},
            ],
        },
        "plan_id": None,
        "awaiting_confirmation": False,
    }
    async with mcp.session() as session:
        result = await session.call_tool("status", {"case_id": case_id})
    body = result.structured_content
    assert body is not None
    assert body["awaiting_confirmation"] is False
    assert body["plan_id"] is None
    assert body["question"]["question"].startswith("Was it the whole Valley Produce delivery")
    assert [option["code"] for option in body["question"]["options"]] == [
        "WHOLE_DELIVERY",
        "LINE-RASP",
    ]


async def test_a_planned_case_hands_back_a_plan_identity_to_quote(mcp: McpServer) -> None:
    async with mcp.session() as session:
        result = await session.call_tool("status", {"case_id": str(uuid4())})
    body = result.structured_content
    assert body is not None
    assert body["awaiting_confirmation"] is True
    assert body["plan_id"] == PLAN_ID
    assert body["question"] is None


async def test_an_identifier_that_is_not_one_is_refused_before_the_engine(
    mcp: McpServer,
) -> None:
    assert mcp.intents is not None
    async with mcp.session() as session:
        result = await session.call_tool("status", {"case_id": "not-a-case"})
    assert result.is_error is True
    assert ToolCode.INVALID_ARGUMENT.value in _text(result)
    assert mcp.intents.calls == []


async def test_a_missing_argument_is_a_tool_error_not_a_crash(mcp: McpServer) -> None:
    async with mcp.session() as session:
        result = await session.call_tool("report", {})
    assert result.is_error is True
    assert "text" in _text(result)


async def test_an_unknown_tool_is_refused(mcp: McpServer) -> None:
    async with mcp.session() as session:
        result = await session.call_tool("amend_order", {"case_id": str(uuid4())})
    assert result.is_error is True


# ------------------------------------------------------------------------- refusing honestly


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, ToolCode.UNAUTHORIZED_SURFACE),
        (403, ToolCode.UNAUTHORIZED_SURFACE),
        (404, ToolCode.UNKNOWN_RESOURCE),
        (409, ToolCode.CASE_NOT_IN_STATE),
        (422, ToolCode.INVALID_ARGUMENT),
        (500, ToolCode.ENGINE_UNAVAILABLE),
        (503, ToolCode.ENGINE_UNAVAILABLE),
    ],
)
async def test_an_engine_refusal_becomes_its_stable_code(status: int, code: ToolCode) -> None:
    intents = RecordingIntents(status_status=status, status_body={"error": "internal detail"})
    async with mcp_against(intents.app()) as server, server.session() as session:
        result = await session.call_tool("status", {"case_id": str(uuid4())})
    assert result.is_error is True
    assert code.value in _text(result)
    assert "internal detail" not in _text(result)


async def test_an_unreachable_engine_is_an_unavailable_answer_not_an_answer() -> None:
    """A provider that was never reached is reported as silence, never filled in.

    The tool refuses. It does not return an empty case, a hopeful ``PLANNED``, or a sentence
    the model could deliver as though somebody had checked.
    """
    async with mcp_with_no_engine_listening() as server, server.session() as session:
        result = await session.call_tool("status", {"case_id": str(uuid4())})
    assert result.is_error is True
    assert ToolCode.ENGINE_UNAVAILABLE.value in _text(result)


async def test_an_answer_of_the_wrong_shape_is_unavailability() -> None:
    """An envelope missing a field it promised is a system that did not answer the question."""
    intents = RecordingIntents(status_body={"case_id": str(uuid4())})
    async with mcp_against(intents.app()) as server, server.session() as session:
        result = await session.call_tool("status", {"case_id": str(uuid4())})
    assert result.is_error is True
    assert ToolCode.ENGINE_UNAVAILABLE.value in _text(result)


# -------------------------------------------------------------------- before the protocol


async def test_without_a_credential_the_tool_surface_does_not_exist(mcp: McpServer) -> None:
    """Authentication is outside the protocol, so an anonymous caller learns nothing at all.

    Not "the tools are there but refuse" -- the JSON-RPC layer is never reached, so the reply
    contains no tool name, no schema and no hint about whether an identifier was real.
    """
    async with mcp.raw() as client:
        response = await client.post(
            mcp.url,
            headers=JSON_RPC_HEADERS,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer ")
    assert "report" not in response.text


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Bearer",
        "Bearer wrong-token",
        "Basic dXNlcjpwYXNz",
        f"Token {BEARER}",
        BEARER,
    ],
)
async def test_every_way_of_not_having_the_credential_is_one_rejection(
    mcp: McpServer, header: str | None
) -> None:
    headers = dict(JSON_RPC_HEADERS)
    if header is not None:
        headers["Authorization"] = header
    async with mcp.raw() as client:
        response = await client.post(
            mcp.url, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
    assert response.status_code == 401


async def test_an_unlisted_origin_is_rejected(mcp: McpServer) -> None:
    """A page on another origin must not be able to drive a locally bound MCP server."""
    async with mcp.raw() as client:
        response = await client.post(
            mcp.url,
            headers={
                "Authorization": f"Bearer {BEARER}",
                "Origin": "http://evil.example",
                **JSON_RPC_HEADERS,
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert response.status_code == 403


async def test_a_listed_origin_is_served(mcp: McpServer) -> None:
    async with mcp.raw() as client:
        response = await client.post(
            mcp.url,
            headers={
                "Authorization": f"Bearer {BEARER}",
                "Origin": ALLOWED_ORIGIN,
                **JSON_RPC_HEADERS,
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert response.status_code == 200
    assert "report" in response.text


async def test_an_unlisted_host_is_rejected(mcp: McpServer) -> None:
    async with mcp.raw() as client:
        response = await client.post(
            mcp.url,
            headers={
                "Authorization": f"Bearer {BEARER}",
                "Host": "evil.example",
                **JSON_RPC_HEADERS,
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert response.status_code == 421


# ------------------------------------------------------------------------- protocol errors


async def test_an_unknown_method_is_a_json_rpc_error(mcp: McpServer) -> None:
    async with mcp.raw() as client:
        response = await client.post(
            mcp.url,
            headers={"Authorization": f"Bearer {BEARER}", **JSON_RPC_HEADERS},
            json={"jsonrpc": "2.0", "id": 2, "method": "cases/delete"},
        )
    assert response.status_code == 200
    assert _sse_error(response.text)["code"] == -32601


async def test_malformed_json_never_reaches_a_tool(mcp: McpServer) -> None:
    assert mcp.intents is not None
    async with mcp.raw() as client:
        response = await client.post(
            mcp.url,
            headers={"Authorization": f"Bearer {BEARER}", **JSON_RPC_HEADERS},
            content=b"{ not json",
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32700
    assert mcp.intents.calls == []


async def test_a_post_that_will_not_accept_an_event_stream_is_rejected(mcp: McpServer) -> None:
    """The spec requires a POST to accept both media types, because the answer may be either."""
    async with mcp.raw() as client:
        response = await client.post(
            mcp.url,
            headers={
                "Authorization": f"Bearer {BEARER}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert response.status_code == 406


# ------------------------------------------------------------------- reconnect and resume


async def test_the_server_issues_no_session_to_lose(mcp: McpServer) -> None:
    """Stateless: there is no ``Mcp-Session-Id``, so there is no conversation to strand.

    This is the honest form of the reconnect guarantee. Nothing is held here, so nothing is
    lost when a connection drops -- and equally, ``Last-Event-ID`` stream resumption is not on
    offer, because there is no session to resume. What survives is the case, in the database.
    """
    async with mcp.raw() as client:
        response = await client.post(
            mcp.url,
            headers={"Authorization": f"Bearer {BEARER}", **JSON_RPC_HEADERS},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_REVISION,
                    "capabilities": {},
                    "clientInfo": {"name": "protocol-test", "version": "1"},
                },
            },
        )
    assert response.status_code == 200
    assert "mcp-session-id" not in response.headers


async def test_a_fabricated_session_id_grants_nothing_and_breaks_nothing(
    mcp: McpServer,
) -> None:
    """A session id nobody issued is neither honoured nor a way in: it is simply not consulted."""
    async with mcp.raw() as client:
        response = await client.post(
            mcp.url,
            headers={
                "Authorization": f"Bearer {BEARER}",
                "Mcp-Session-Id": "a-session-that-never-existed",
                **JSON_RPC_HEADERS,
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert response.status_code == 200


async def test_a_second_connection_picks_the_case_up_where_the_first_left_it(
    mcp: McpServer,
) -> None:
    """The reconnect that matters: a new client, a new handshake, the same case.

    The first session opens a case and its transport is then closed completely. A second
    session -- a different connection, a different handshake, nothing carried over -- asks for
    that case and is served. Continuity is a property of the durable case, not of anything the
    transport remembered.
    """
    assert mcp.intents is not None
    async with mcp.session() as first:
        opened = await first.call_tool("report", {"text": CANONICAL})
    assert opened.structured_content is not None
    case_id = opened.structured_content["case_id"]

    async with mcp.session() as second:
        seen = await second.call_tool("status", {"case_id": case_id})
    assert seen.is_error is not True
    assert seen.structured_content is not None
    assert seen.structured_content["case_id"] == case_id
    assert mcp.intents.last.body == {"case_id": case_id}


# ------------------------------------------------------------------------------- plumbing


def _sse_result(payload: str) -> dict[str, Any]:
    """The ``result`` object out of one event-stream response.

    The tests read the framing rather than a convenience wrapper, because the framing is part
    of what is being claimed: this server answers a POST with ``text/event-stream``, which is
    what a Streamable HTTP client meets.
    """
    return _sse_body(payload)["result"]  # type: ignore[no-any-return]


def _sse_error(payload: str) -> dict[str, Any]:
    return _sse_body(payload)["error"]  # type: ignore[no-any-return]


def _sse_body(payload: str) -> dict[str, Any]:
    for line in payload.splitlines():
        if line.startswith("data:"):
            parsed: dict[str, Any] = json.loads(line[len("data:") :].strip())
            return parsed
    raise AssertionError(f"no event-stream data frame in {payload!r}")
