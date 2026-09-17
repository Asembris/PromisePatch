"""The canonical worker conversation, driven by the orchestrator over the real MCP surface.

``test_orchestrator.py`` proves the loop's rules against a scripted surface. This proves the
whole thing: a model chooses a verb, an MCP client calls that tool over Streamable HTTP, the
MCP server forwards it to the intent API, the domain writes rows, the worker process runs
between the turns, and the sentences the worker hears are the ones
:mod:`promisepatch.domain.status_view` rendered on the far side of two hops.

Nothing here inserts a row, and no domain service is called to move the conversation along.
Every turn is a thing somebody said; the only direct database access is the reads at the end,
over a separate connection, that check what the conversation left behind.

**No model is called.** The provider is the scripted fake, which reaches the same
:func:`~promisepatch.semantic.jobs.validate` gate a real one does -- so what is under test is
the loop and the transport, with the model's contribution reduced to the one thing it actually
contributes: a verb. The one bounded live conversation is
``test_orchestrator_live.py``, opt-in and deselected by default.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest_asyncio
from _intake_support import BAKER, CANONICAL_REPORT, CORRECTION, RASPBERRY_ONLY, Intake
from _intake_support import physical as physical
from _mcp_support import BEARER, SERVICE_TOKEN, mcp_over_http, serve
from sqlalchemy import select

from promisepatch.config import Settings
from promisepatch.db.models import PlanApproval
from promisepatch.main import create_app
from promisepatch.orchestrator import Conversation, Orchestrator, TurnResult, connect
from promisepatch.orchestrator.policy import BLOCKED_SENTENCES, MAX_TOOL_CALLS_PER_TURN, Blocked
from promisepatch.semantic import FakeSemanticProvider, SemanticJob
from promisepatch.semantic.contracts import ConversationPhase

WHAT_NOW = "what do you need from me?"
WHAT_IS_THE_PLAN = "so what's the plan?"
THE_YES = "yes, go ahead"
WHERE_ARE_WE = "where does that leave us?"


def api_settings(**overrides: Any) -> Settings:
    """The API's configuration. The attesting worker is server-side and nothing can name it."""
    values: dict[str, Any] = {
        "internal_service_token": SERVICE_TOKEN,
        "surface_worker_id": BAKER,
    }
    values.update(overrides)
    return Settings(**values)


def chooses(*verbs: str) -> FakeSemanticProvider:
    """A provider that names these verbs, in order, and supplies nothing else.

    Every entry is the raw tool input a model would have returned. It carries a verb and, where
    the conversation would naturally have one, a sentence of glue -- which is the entire surface
    a model has in this loop.
    """
    return FakeSemanticProvider({SemanticJob.SELECT_TOOL: [{"tool": verb} for verb in verbs]})


@pytest_asyncio.fixture
async def chain(physical: Intake) -> AsyncIterator[str]:
    """Two servers on two sockets -- the MCP endpoint and the real API -- and the client's URL."""
    async with serve(create_app(api_settings())) as api_base, mcp_over_http(api_base) as server:
        yield server.url


async def test_the_model_choosing_confirm_on_an_unapproved_plan_changes_nothing(
    chain: str, physical: Intake
) -> None:
    """The loop's own gate removed, and the case still does not move.

    The model is scripted to choose ``CONFIRM``, the worker's turn is a plain yes so the client
    grammar passes it, the phase permits it, and the conversation is holding the real plan
    identity ``status`` returned. Every client-side condition is satisfied. The one thing that
    has not happened is the worker agreeing anywhere this system authenticated them, and that is
    sufficient: the call is refused on the server, the worker is told deterministically that the
    conversation may not do it, and the case is exactly where it was.

    This is the defence the loop's own literal rule is *not*. That rule stops an agreeable
    conversation making the call; this stops a conversation that makes the call anyway.
    """
    conversation = Conversation()
    provider = chooses("REPORT", "STATUS", "CLARIFY", "STATUS", "CONFIRM", "STATUS")

    async with connect(chain, token=BEARER, timeout_seconds=30.0) as surface:
        loop = Orchestrator(provider=provider, surface=surface)
        opened = await loop.take_turn(conversation, CANONICAL_REPORT, correlation_id=str(uuid4()))
        conversation = opened.conversation
        case_id = UUID(str(conversation.case_id))
        await physical.drain_intake(case_id)
        conversation = (await loop.take_turn(conversation, WHAT_NOW)).conversation
        conversation = (await loop.take_turn(conversation, RASPBERRY_ONLY)).conversation
        await physical.drain()
        planned = await loop.take_turn(conversation, WHAT_IS_THE_PLAN)
        conversation = planned.conversation
        assert conversation.phase is ConversationPhase.PLANNED
        assert conversation.plan_id, "the loop is holding the real identity, not a guess"

        refused = await loop.take_turn(conversation, THE_YES)

    assert refused.calls == ("confirm", "status")
    assert "not permitted" in refused.reply
    assert (await physical.case(case_id)).state == "PLANNED"
    assert await physical.effects() == []
    async with physical.database.connect() as connection:
        approvals = list(
            (
                await connection.execute(
                    select(PlanApproval).where(PlanApproval.case_id == case_id)
                )
            ).all()
        )
    assert approvals == [], "a refused tool call left no authority behind either"


async def test_the_canonical_conversation_is_carried_by_the_orchestrator(
    chain: str, physical: Intake
) -> None:
    """Report, question, answer, plan, an explicit yes, and a truthful closing status.

    Six turns, each one a thing a worker said, each one going through a model that may only
    choose a verb. What carries the conversation between turns is the durable case; what the
    worker hears at every step is a sentence the engine rendered.
    """
    turns: list[TurnResult] = []
    conversation = Conversation()
    provider = chooses("REPORT", "STATUS", "CLARIFY", "STATUS", "CONFIRM", "STATUS")

    async with connect(chain, token=BEARER, timeout_seconds=30.0) as surface:
        loop = Orchestrator(provider=provider, surface=surface)

        # 1. The worker reports something physical. A case opens; nothing is concluded.
        opened = await loop.take_turn(conversation, CANONICAL_REPORT, correlation_id=str(uuid4()))
        conversation = opened.conversation
        turns.append(opened)
        assert opened.calls == ("report", "status")
        assert conversation.case_id is not None
        case_id = UUID(conversation.case_id)
        assert "Noted" in opened.reply

        # The interpreter runs and finds the sentence ambiguous.
        await physical.drain_intake(case_id)

        # 2. The worker asks what is needed. The question is read out as the engine asked it.
        asking = await loop.take_turn(conversation, WHAT_NOW)
        conversation = asking.conversation
        turns.append(asking)
        assert asking.calls == ("status",)
        assert conversation.phase is ConversationPhase.CLARIFYING
        assert conversation.question
        assert conversation.question in asking.reply
        assert conversation.plan_id is None, "nothing to confirm while a question is open"

        # 3. The worker answers it, in their own words.
        answered = await loop.take_turn(conversation, RASPBERRY_ONLY)
        conversation = answered.conversation
        turns.append(answered)
        assert answered.calls == ("clarify", "status")
        assert "written that down exactly as you said it" in answered.reply

        # The answer resolves the scope; the case is analysed and planned.
        await physical.drain()

        # 4. The worker asks for the plan, and is read one with an identity behind it.
        planned = await loop.take_turn(conversation, WHAT_IS_THE_PLAN)
        conversation = planned.conversation
        turns.append(planned)
        assert conversation.phase is ConversationPhase.PLANNED
        assert conversation.plan_id
        assert "Nothing has been done yet." in planned.reply
        assert "left alone" in planned.reply, "the untouched band is not decoration"

        # The worker approves the plan they have just been read, on their own signed-in
        # workspace. This is not a step the conversation can perform for them and not one it can
        # skip: the tool it is about to call spends this approval and cannot create one, so
        # without this line turn 5 is refused and the case stays where it is.
        await physical.approve(case_id, plan_id=conversation.plan_id)

        # 5. The worker says yes, and the conversation carries out what they approved.
        confirmed = await loop.take_turn(conversation, THE_YES)
        conversation = confirmed.conversation
        turns.append(confirmed)
        assert confirmed.calls == ("confirm", "status")
        assert "Confirmed" in confirmed.reply
        assert "Nothing has been changed yet" in confirmed.reply

        # 6. And the truthful current status: authorised, with nothing carried out.
        after = await loop.take_turn(conversation, WHERE_ARE_WE)
        conversation = after.conversation
        turns.append(after)
        assert after.calls == ("status",)

    assert [turn.selected.value for turn in turns if turn.selected] == [
        "REPORT",
        "STATUS",
        "CLARIFY",
        "STATUS",
        "CONFIRM",
        "STATUS",
    ]
    assert all(len(turn.calls) <= MAX_TOOL_CALLS_PER_TURN for turn in turns)
    assert [
        turn.calls.count("report") + turn.calls.count("clarify") + turn.calls.count("confirm")
        for turn in turns
    ] == [1, 0, 1, 0, 1, 0]
    assert not any(turn.blocked or turn.refusal for turn in turns)

    # Nothing anywhere in the conversation says a promise reached a state it has not reached.
    # ``: changed`` and ``: asked`` are how ``status_view`` renders RECOVERED and REQUESTED, so
    # their absence is the claim -- checked against the words the product actually uses rather
    # than against a substring that "nothing has changed yet" would trip over.
    for turn in turns:
        assert ": changed" not in turn.reply
        assert ": asked" not in turn.reply
    assert "Nothing has been changed yet" in confirmed.reply
    assert "covered by a standing preference" in after.reply, "authorised, and said as such"

    # The durable evidence: two statements, in the worker's own words, attributed by the server.
    reports = await physical.reports(case_id)
    assert [row.raw_text for row in reports] == [CANONICAL_REPORT, RASPBERRY_ONLY]
    assert all(row.reported_by == BAKER for row in reports)
    assert (await physical.case(case_id)).state == "EXECUTING"


async def test_a_conversation_cannot_confirm_a_plan_the_case_has_moved_past(
    chain: str, physical: Intake
) -> None:
    """Stale between the read and the yes, over the real transport and through the loop.

    The worker was read one plan, the physical facts were corrected, and the case re-planned
    before the yes landed. The domain refuses the confirmation; the conversation says the case
    moved on rather than guessing what it moved to, and leaves the worker holding the plan that
    is actually on offer.
    """
    case_id = await physical.resolved_case()
    await physical.drain()

    async with connect(chain, token=BEARER, timeout_seconds=30.0) as surface:
        loop = Orchestrator(provider=chooses("STATUS", "CONFIRM"), surface=surface)
        read = await loop.take_turn(Conversation().with_case(str(case_id)), WHAT_IS_THE_PLAN)
        assert read.conversation.phase is ConversationPhase.PLANNED
        stale = read.conversation.plan_id
        assert stale

        await physical.correct(case_id, CORRECTION)
        await physical.drain()

        refused = await loop.take_turn(read.conversation, THE_YES)

    assert refused.calls == ("confirm", "status")
    assert refused.refusal is not None
    assert "moved on" in refused.reply
    assert refused.conversation.plan_id != stale, "the worker now holds the plan on offer"
    assert (await physical.case(case_id)).state == "PLANNED", "no yes was recorded"


async def test_a_conversation_cannot_answer_a_case_that_asked_nothing(
    chain: str, physical: Intake
) -> None:
    """The model picks the answering verb on a case with no open question.

    It never reaches the tool: the phase permits only a read, so the boundary refuses the
    choice and the loop says so. One statement exists afterwards -- the report -- and no
    second one arrived from a conversation that was willing to answer a question nobody asked.
    """
    async with connect(chain, token=BEARER, timeout_seconds=30.0) as surface:
        loop = Orchestrator(provider=chooses("REPORT", "CLARIFY", "CLARIFY"), surface=surface)
        opened = await loop.take_turn(Conversation(), CANONICAL_REPORT)
        case_id = UUID(str(opened.conversation.case_id))
        answered = await loop.take_turn(opened.conversation, RASPBERRY_ONLY)

    assert "clarify" not in answered.calls
    assert answered.blocked is Blocked.NOT_UNDERSTOOD
    assert answered.reply.startswith(BLOCKED_SENTENCES[Blocked.NOT_UNDERSTOOD])
    assert len(await physical.reports(case_id)) == 1


async def test_a_conversation_without_the_bearer_credential_reaches_no_tool(
    chain: str, physical: Intake
) -> None:
    """The credential is the transport's, checked before the protocol -- so this fails to open.

    Included here rather than left to the protocol suite because the orchestrator is where a
    credential could plausibly be treated as optional. It is not: an unauthenticated loop never
    completes a handshake, so it never discovers a tool, let alone calls one.
    """
    opened = False
    try:
        async with connect(chain, token="a-token-nobody-issued", timeout_seconds=10.0):
            opened = True
    except Exception:  # any failure to complete a handshake is the assertion
        opened = False
    assert opened is False
