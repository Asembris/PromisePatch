"""One turn of a worker's conversation: choose, check, call at most twice, say what is true.

This is the whole orchestrator. It is small deliberately -- an agent loop that could keep going
until something worked would be a loop that could work around a refusal, and every rule this
product has about authority would then have a way past it that nobody wrote down.

**What the model does.** One bounded semantic call per turn,
:class:`~promisepatch.semantic.contracts.SemanticJob.SELECT_TOOL`, which returns a verb from a
list PromisePatch computed and at most one sentence of conversational glue. It supplies no
arguments, because its answer has no field that could carry one.

**What deterministic code does.** Everything else. The phase, the offer, the arguments, whether
the worker actually said yes, which sentence the worker hears, and what the conversation
remembers afterwards -- all of it from :mod:`promisepatch.orchestrator.policy` and from tool
results the server rendered.

**The budget.** At most two calls in a turn, of which at most one may affect state; the other
is always ``status``. It is a hard count rather than a convention, and the second call exists
so a turn can end on the truth rather than on what the first call hoped.

**Failing closed.** A model that cannot be reached, answers something unusable, or writes glue
that claims an outcome ends the turn with a deterministic sentence and, when a case is open,
one read. No effecting tool is ever called on an answer that was not accepted, and nothing is
presented again in the hope of a different result: the single corrective retry this system
allows belongs to the semantic gateway, is bounded there, and is spent on a schema rather than
on a refusal.

**The glue is delivered only when the turn did what was chosen.** A blocked or refused turn
drops it entirely and says the deterministic sentence alone. Glue is written before the call
happens, so a sentence that was harmless as an introduction to an action is not necessarily
harmless as an introduction to that action not happening.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from promisepatch.mcp.envelope import ToolCode
from promisepatch.observability import get_logger
from promisepatch.orchestrator.policy import (
    BLOCKED_SENTENCES,
    MAX_TOOL_CALLS_PER_TURN,
    REFUSAL_SENTENCES,
    Action,
    Blocked,
    CaseReading,
    Conversation,
    permitted_for,
    plan,
)
from promisepatch.orchestrator.surface import ToolOutcome, ToolSurface
from promisepatch.semantic.contracts import (
    MAX_UNTRUSTED_CHARACTERS,
    ConversationPhase,
    ConversationTool,
    SelectToolRequest,
    SemanticMetadata,
    ToolSelection,
    UntrustedText,
)
from promisepatch.semantic.errors import SemanticError
from promisepatch.semantic.provider import SemanticProvider

logger = get_logger(__name__)

FOLLOW_UP_PHASES = frozenset({ConversationPhase.CLARIFYING, ConversationPhase.PLANNED})
"""Phases whose rendering is read out after an effecting call, because it asks for something.

An effecting turn answers with that tool's own sentence. The follow-up read exists to refresh
what the conversation knows, and its rendering is added only when the case has arrived
somewhere that wants the worker: a question to answer, or a plan to say yes to. Anywhere else
the read is state and not speech, and repeating "still working it out" adds nothing.
"""


@dataclass(frozen=True, slots=True)
class TurnResult:
    """What one turn did, in enough detail to assert on and to log.

    ``calls`` is the exact sequence of tool names, in order, which is what a test needs to
    prove the budget and what an operator needs to correlate a conversation with the audit
    rows it caused. ``selected`` is what the model chose, kept separately from what actually
    ran -- the two differing is the interesting case, not an inconsistency.
    """

    reply: str
    conversation: Conversation
    calls: tuple[str, ...] = ()
    selected: ConversationTool | None = None
    blocked: Blocked | None = None
    refusal: ToolCode | None = None
    preface: str | None = None

    @property
    def acted(self) -> bool:
        """Whether this turn left a durable trace. A read-only turn did not."""
        return any(name != "status" for name in self.calls)


@dataclass
class _Budget:
    """The turn's tool-call allowance, counted down. Small enough to hold in one hand."""

    remaining: int = MAX_TOOL_CALLS_PER_TURN
    spent: list[str] = field(default_factory=list)

    def spend(self, name: str) -> None:
        if self.remaining <= 0:  # pragma: no cover - the loop never asks past the budget
            raise RuntimeError("a turn tried to make more tool calls than it is allowed")
        self.remaining -= 1
        self.spent.append(name)


class Orchestrator:
    """A conversation over the MCP tool surface, with a model choosing among permitted verbs.

    Holds no case and no state between turns: a :class:`~promisepatch.orchestrator.policy.
    Conversation` goes in and a new one comes out, so the caller owns the thread and this owns
    only the rules. That is what makes a turn replayable and what stops the loop from
    accumulating a belief about a case that the case does not share.
    """

    def __init__(self, *, provider: SemanticProvider, surface: ToolSurface) -> None:
        self._provider = provider
        self._surface = surface

    async def take_turn(
        self, conversation: Conversation, turn: str, *, correlation_id: str | None = None
    ) -> TurnResult:
        """One thing a worker said, from choice through to the sentence they hear back."""
        budget = _Budget()
        if not turn.strip() or len(turn) > MAX_UNTRUSTED_CHARACTERS:
            # Refused before the boundary rather than at it. A blank turn asks nothing, and a
            # turn longer than the contract can carry would raise out of a request builder
            # whose callers only know two kinds of failure -- the P4.9 defect, in a new place.
            return await self._blocked(conversation, budget, Blocked.NOT_UNDERSTOOD)

        selection = await self._choose(conversation, turn, correlation_id=correlation_id)
        if selection is None:
            return await self._blocked(conversation, budget, Blocked.NOT_UNDERSTOOD)

        decided = plan(selection.tool, conversation, turn)
        if isinstance(decided, Blocked):
            logger.info(
                "orchestrator.turn.blocked",
                selected=selection.tool.value,
                reason=decided.value,
                phase=conversation.phase.value,
            )
            return await self._blocked(conversation, budget, decided, selected=selection.tool)
        return await self._act(conversation, budget, decided, selection)

    # ------------------------------------------------------------------------ the model

    async def _choose(
        self, conversation: Conversation, turn: str, *, correlation_id: str | None
    ) -> ToolSelection | None:
        """Ask which permitted verb this turn wants, or return nothing at all.

        ``None`` means no usable answer arrived -- unreachable, timed out, malformed, a verb
        this phase does not permit, or glue that claimed something. All of them are the same
        thing to a conversation: nobody said anything it may act on, so it does not act.
        """
        request = SelectToolRequest(
            turn=UntrustedText(text=turn),
            phase=conversation.phase,
            permitted=permitted_for(conversation.phase),
            metadata=SemanticMetadata(correlation_id=correlation_id, case_id=conversation.case_id),
        )
        try:
            result = await self._provider.run(request)
        except SemanticError as error:
            logger.warning("orchestrator.selection.unusable", error=type(error).__name__)
            return None
        value = result.value
        if not isinstance(value, ToolSelection):  # pragma: no cover - the gateway types this
            logger.error("orchestrator.selection.wrong_shape", kind=type(value).__name__)
            return None
        return value

    # ------------------------------------------------------------------------ the calls

    async def _act(
        self,
        conversation: Conversation,
        budget: _Budget,
        action: Action,
        selection: ToolSelection,
    ) -> TurnResult:
        """Make the one call this turn decided on, then tell the worker what is true."""
        budget.spend(action.name)
        outcome = await self._surface.call(action.name, action.arguments)
        if not outcome.ok:
            code = outcome.refusal or ToolCode.ENGINE_UNAVAILABLE
            logger.info("orchestrator.turn.refused", tool=action.name, code=code.value)
            return await self._refused(conversation, budget, code, selected=action.tool)

        if action.tool is ConversationTool.STATUS:
            reading = _reading(outcome.body)
            moved = conversation if reading is None else conversation.with_reading(reading)
            return TurnResult(
                reply=_say(selection.preface, outcome.speech()),
                conversation=moved,
                calls=tuple(budget.spent),
                selected=action.tool,
                preface=selection.preface,
            )

        opened = conversation
        if action.tool is ConversationTool.REPORT:
            case_id = _case_id(outcome.body)
            if case_id is not None:
                opened = conversation.with_case(case_id)

        refreshed, follow_up = await self._refresh(opened, budget)
        return TurnResult(
            reply=_say(selection.preface, outcome.speech(), follow_up),
            conversation=refreshed,
            calls=tuple(budget.spent),
            selected=action.tool,
            preface=selection.preface,
        )

    async def _refresh(
        self, conversation: Conversation, budget: _Budget
    ) -> tuple[Conversation, str | None]:
        """Read the case once more, for what the conversation knows and sometimes for speech.

        A read that fails changes nothing: the conversation keeps what it had, and the worker
        hears the effecting tool's own sentence, which is already true and already rendered.
        Nothing here invents a phase to make up for a read that did not happen.
        """
        if conversation.case_id is None or budget.remaining <= 0:
            return conversation, None
        outcome = await self._read(conversation.case_id, budget)
        reading = _reading(outcome.body) if outcome.ok else None
        if reading is None:
            return conversation, None
        moved = conversation.with_reading(reading)
        return moved, outcome.speech() if moved.phase in FOLLOW_UP_PHASES else None

    async def _read(self, case_id: str, budget: _Budget) -> ToolOutcome:
        budget.spend("status")
        return await self._surface.call("status", {"case_id": case_id})

    # ------------------------------------------------------------------- not doing things

    async def _blocked(
        self,
        conversation: Conversation,
        budget: _Budget,
        reason: Blocked,
        *,
        selected: ConversationTool | None = None,
    ) -> TurnResult:
        """Say why nothing happened, and -- when there is a case -- what is true instead."""
        return await self._deterministic(
            conversation, budget, BLOCKED_SENTENCES[reason], selected=selected, blocked=reason
        )

    async def _refused(
        self,
        conversation: Conversation,
        budget: _Budget,
        code: ToolCode,
        *,
        selected: ConversationTool | None,
    ) -> TurnResult:
        """Say what the surface refused, in this system's words rather than the engine's."""
        return await self._deterministic(
            conversation, budget, REFUSAL_SENTENCES[code], selected=selected, refusal=code
        )

    async def _deterministic(
        self,
        conversation: Conversation,
        budget: _Budget,
        sentence: str,
        *,
        selected: ConversationTool | None,
        blocked: Blocked | None = None,
        refusal: ToolCode | None = None,
    ) -> TurnResult:
        """One deterministic sentence, and the case as it currently stands if it can be read.

        The model's glue is dropped here and is not a decision to make case by case: it was
        written to introduce something that did not then happen, and the sentence it would
        introduce instead is a refusal. What a worker hears when a turn fails is written in
        :mod:`promisepatch.orchestrator.policy` and nowhere else.
        """
        current = ""
        moved = conversation
        if conversation.case_id is not None and budget.remaining > 0:
            outcome = await self._read(conversation.case_id, budget)
            reading = _reading(outcome.body) if outcome.ok else None
            if reading is not None:
                moved = conversation.with_reading(reading)
                current = outcome.speech() or ""
        return TurnResult(
            reply=_say(None, sentence, current or None),
            conversation=moved,
            calls=tuple(budget.spent),
            selected=selected,
            blocked=blocked,
            refusal=refusal,
        )


# ------------------------------------------------------------------------------- plumbing


def _say(preface: str | None, *blocks: str | None) -> str:
    """The worker's reply: accepted glue, then the sentences the server rendered.

    The glue goes first and never replaces anything. Every other block arrives already written
    by :mod:`promisepatch.domain.status_view` on the far side of the transport, and passes
    through here unchanged -- there is no branch below that edits, shortens or summarises one.
    """
    parts = [part for part in (preface, *blocks) if part]
    return "\n\n".join(parts) if parts else BLOCKED_SENTENCES[Blocked.NOT_UNDERSTOOD]


def _reading(body: Mapping[str, Any] | None) -> CaseReading | None:
    """A ``status`` payload reduced to the four things a phase depends on, or nothing.

    Read defensively at every level, for the reason the Bedrock adapter learned in P4.9: a
    body of the wrong shape is an answer this client did not get, and reaching into it
    optimistically would raise something the caller has no sentence for. A payload missing its
    case or its headline leaves the conversation exactly where it was.
    """
    if body is None:
        return None
    case_id = body.get("case_id")
    headline = body.get("headline")
    if not isinstance(case_id, str) or not isinstance(headline, str):
        return None
    plan_id = body.get("plan_id")
    question = body.get("question")
    asked = question.get("question") if isinstance(question, Mapping) else None
    return CaseReading(
        case_id=case_id,
        headline=headline,
        plan_id=plan_id if isinstance(plan_id, str) and plan_id else None,
        awaiting_confirmation=bool(body.get("awaiting_confirmation", False)),
        question=asked if isinstance(asked, str) and asked else None,
    )


def _case_id(body: Mapping[str, Any] | None) -> str | None:
    """The case a ``report`` opened, if it said which."""
    if body is None:
        return None
    value = body.get("case_id")
    return value if isinstance(value, str) and value else None


__all__ = ["FOLLOW_UP_PHASES", "Orchestrator", "TurnResult"]
