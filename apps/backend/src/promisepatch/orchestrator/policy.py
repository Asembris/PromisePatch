"""What a conversation is allowed to do next, decided from values and from nothing else.

This module is the deterministic half of the conversational loop. It answers three questions,
all of them before a model is asked anything and one of them again after it answers:

* **Which phase is this case in?** Derived from a case reading the server rendered, never from
  what a model said and never from what the loop hoped. An unrecognised headline lands on
  ``UNDERSTANDING``, whose only permitted verb is a read.
* **Which verbs does that phase permit?** A closed mapping. Tool availability is defence in
  depth and is stated as such: every one of these calls is checked again by the MCP surface and
  by the domain behind it, and a verb this table allowed still fails there if the case has
  moved. What the table buys is that a model is never *offered* something the case cannot do.
* **What arguments does that verb take?** Every one of them is the worker's own turn, forwarded
  verbatim, or an opaque identifier a trusted tool returned. There is no branch here that reads
  an argument out of a model's answer, because a model's answer has no field that could carry
  one.

And two rules that are not about tools at all. **A plan is confirmed by the worker or not at
all**, and **a case is withdrawn by the worker or not at all.**

:func:`reads_as_worker_confirmation` is a small literal parser over the worker's own words, and
a ``CONFIRM`` that does not pass it is refused here before the surface is touched.
It is *not* the consent parser and has nothing to do with a customer: worker plan confirmation
and customer consent are different authorities produced by different people, and this function
can no more record a customer's decision than the tool it guards can. It is the *client* half
of a gate whose other half is not in this process at all: the domain will not carry out a
confirmation that no durable human approval stands behind, whatever this loop believed. So a
conversation that bypassed this function entirely, or a client that is not this one, still
cannot turn an agreeable turn into a worker's yes -- and this check remains worth having,
because it stops the call being made at all rather than merely being refused.

:func:`reads_as_worker_withdrawal` is its counterpart, and exists for the mirrored reason. A
withdrawal stops work somebody asked for, so it must not be reachable by a model reading dismay
into a turn: the worker has to have said to stop it, in a closed list of the ways people say
that. A turn that is unhappy with the plan, or asking for a different one, is not a withdrawal
and is answered with a read.

Nothing here reaches a database, a provider, a socket, a clock or the environment. The
import-linter contract of the same name enforces it, which is what makes "the conversation
decides without doing" checkable rather than reviewed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from promisepatch.mcp.envelope import ToolCode
from promisepatch.semantic.contracts import ConversationPhase, ConversationTool

MAX_TOOL_CALLS_PER_TURN: Final = 2
"""How many tool calls one thing a worker said may cause. Hard, and small.

Two, because a useful turn is *do the thing, then read what the case now says* -- and never
more: at most one of the two may affect state, and the second is always the read. A loop
allowed a third call is a loop that can start working around a refusal, and the shape of that
is an agent retrying until something succeeds.
"""

TOOL_NAMES: Final[dict[ConversationTool, str]] = {
    ConversationTool.REPORT: "report",
    ConversationTool.CLARIFY: "clarify",
    ConversationTool.CONFIRM: "confirm",
    ConversationTool.WITHDRAW: "withdraw",
    ConversationTool.STATUS: "status",
}
"""The verb vocabulary, mapped to the frozen tool names of the MCP surface. Five, and no sixth.

``NONE`` is absent on purpose: it is a choice not to call anything, so there is nothing for it
to name. Every other entry names a tool the server actually serves; a name here for one it did
not would be a conversation that could ask for something nothing implements.
"""

EFFECTING: Final[frozenset[ConversationTool]] = frozenset(
    {
        ConversationTool.REPORT,
        ConversationTool.CLARIFY,
        ConversationTool.CONFIRM,
        ConversationTool.WITHDRAW,
    }
)
"""The verbs that leave a durable trace. At most one of these may run in a turn.

``STATUS`` is not among them, which is the whole reason the second call in a turn is safe: a
read cannot be the thing that went wrong, so a turn's budget can be spent on the truth.
"""

PERMITTED: Final[dict[ConversationPhase, tuple[ConversationTool, ...]]] = {
    ConversationPhase.NO_CASE: (ConversationTool.REPORT,),
    ConversationPhase.UNDERSTANDING: (ConversationTool.STATUS,),
    ConversationPhase.CLARIFYING: (
        ConversationTool.CLARIFY,
        ConversationTool.WITHDRAW,
        ConversationTool.STATUS,
    ),
    ConversationPhase.PLANNED: (
        ConversationTool.CONFIRM,
        ConversationTool.WITHDRAW,
        ConversationTool.STATUS,
    ),
    ConversationPhase.WORKING: (ConversationTool.STATUS,),
    ConversationPhase.NEEDS_HUMAN: (ConversationTool.STATUS,),
    ConversationPhase.SETTLED: (ConversationTool.STATUS,),
}
"""Which verbs each phase offers a model. Total over the phases, so there is no unlisted state.

Read down the right-hand column and the shape of the product is visible: every phase permits a
read or an opening report, exactly two of them permit anything else, and the one that permits a
confirmation is the one in which a plan is genuinely waiting for a yes.

**Withdrawal is offered in exactly those same two phases**, which is ARCHITECTURE_PLAN's frozen
per-phase table read literally: absent from the opening phase, where there is no case to
withdraw, and absent from every phase that table does not name. The domain is deliberately wider
-- a withdrawal is admitted from any non-terminal case -- and that difference is the
defence in depth this module keeps describing. What a phase *offers* is narrower than what the
engine would accept, and a verb this table withholds is checked again behind it anyway.
"""

HEADLINE_PHASES: Final[dict[str, ConversationPhase]] = {
    "UNDERSTANDING": ConversationPhase.UNDERSTANDING,
    "CLARIFYING": ConversationPhase.CLARIFYING,
    "NEEDS_HUMAN": ConversationPhase.NEEDS_HUMAN,
    "ANALYSED": ConversationPhase.UNDERSTANDING,
    "PLANNED": ConversationPhase.PLANNED,
    "WORKING": ConversationPhase.WORKING,
    "WAITING": ConversationPhase.WORKING,
    "SETTLED": ConversationPhase.SETTLED,
    "CANCELLED": ConversationPhase.SETTLED,
}
"""Every headline :mod:`promisepatch.domain.status_view` can render, mapped once.

``ANALYSED`` collapses into ``UNDERSTANDING`` because the difference between them is invisible
to a conversation: neither has anything for the worker to do, and both permit only a read.
"""


# ------------------------------------------------------------------- what the loop remembers


@dataclass(frozen=True, slots=True)
class CaseReading:
    """One ``status`` result, reduced to the four things a tool choice depends on.

    Built by the loop from the tool's structured content and from nowhere else. The rest of
    that payload -- the promises, the customers, the reasons, the rendered speech -- is carried
    to the worker untouched and is never something this module reasons over.
    """

    case_id: str
    headline: str
    plan_id: str | None = None
    awaiting_confirmation: bool = False
    question: str | None = None


def phase_of(reading: CaseReading) -> ConversationPhase:
    """Which phase a case reading puts the conversation in. Fail-closed on anything unknown.

    Two of the mappings are conditional, and both conditions are the server's own: a case is
    only ``CLARIFYING`` for a conversation while there is a question to ask, and only
    ``PLANNED`` while there is an identity to quote back. A headline without its evidence
    degrades to ``UNDERSTANDING``, whose single permitted verb is a read -- so the failure mode
    of every gap in this function is a conversation that can only look.
    """
    phase = HEADLINE_PHASES.get(reading.headline, ConversationPhase.UNDERSTANDING)
    if phase is ConversationPhase.CLARIFYING and not reading.question:
        return ConversationPhase.UNDERSTANDING
    if phase is ConversationPhase.PLANNED and not (
        reading.awaiting_confirmation and reading.plan_id
    ):
        return ConversationPhase.UNDERSTANDING
    return phase


@dataclass(frozen=True, slots=True)
class Conversation:
    """Everything one conversation knows, and every field of it came from a trusted tool.

    There is no history here, no transcript and no model output. A case id arrives from
    ``report``; a phase, a plan identity and an open question arrive from ``status``, which is
    the engine's own rendering. Nothing a model said is stored, because nothing a model says is
    a fact about a case -- and a loop that remembered a model's belief would eventually act on
    it after the case had moved.

    Frozen, so a turn produces a new conversation rather than mutating one. That is what makes
    "the state this tool was called against" a value a test can hold on to.
    """

    case_id: str | None = None
    phase: ConversationPhase = ConversationPhase.NO_CASE
    plan_id: str | None = None
    question: str | None = None

    def with_case(self, case_id: str) -> Conversation:
        """A case exists now. Nothing else is known about it until ``status`` is read.

        Deliberately lands on ``UNDERSTANDING`` rather than on anything a report result hints
        at: the durable state a report returns is the state *before* the interpreter ran, and
        the only honest thing to say about a case nobody has read yet is that it is being read.
        """
        return Conversation(case_id=case_id, phase=ConversationPhase.UNDERSTANDING)

    def with_reading(self, reading: CaseReading) -> Conversation:
        """The case as the server just rendered it. The only way a phase ever advances."""
        return replace(
            self,
            case_id=reading.case_id,
            phase=phase_of(reading),
            plan_id=reading.plan_id,
            question=reading.question,
        )


def permitted_for(phase: ConversationPhase) -> tuple[ConversationTool, ...]:
    """The verbs this phase offers. Never empty: every phase permits a read or a first report."""
    return PERMITTED[phase]


# --------------------------------------------------------------------- what a turn may become


class Blocked(StrEnum):
    """Why a turn caused no tool call. Each one has a sentence and none of them is an error."""

    NOT_UNDERSTOOD = "NOT_UNDERSTOOD"
    """No usable choice came back, so none was invented."""

    NOT_PERMITTED_HERE = "NOT_PERMITTED_HERE"
    """A verb that is not available in this phase. Checked again after the boundary checked it."""

    NO_CASE_YET = "NO_CASE_YET"
    """A verb that needs a case, and there is no case."""

    NO_PLAN_TO_CONFIRM = "NO_PLAN_TO_CONFIRM"
    """A confirmation with no plan identity read from ``status`` to quote back."""

    NEEDS_THE_WORKERS_YES = "NEEDS_THE_WORKERS_YES"
    """A confirmation the worker did not actually give in their own words."""

    NEEDS_THE_WORKERS_WORD = "NEEDS_THE_WORKERS_WORD"
    """A withdrawal the worker did not actually ask for in their own words."""


BLOCKED_SENTENCES: Final[dict[Blocked, str]] = {
    Blocked.NOT_UNDERSTOOD: (
        "I could not work out what you meant, and I am not going to guess. Nothing has changed."
    ),
    Blocked.NOT_PERMITTED_HERE: (
        "That is not something this case can do right now, so I have not tried it."
    ),
    Blocked.NO_CASE_YET: ("There is no case open yet. Tell me what happened and I will open one."),
    Blocked.NO_PLAN_TO_CONFIRM: (
        "I have not read you a plan for this case, so there is nothing for you to confirm yet."
    ),
    Blocked.NEEDS_THE_WORKERS_YES: (
        "I will not confirm a plan unless you say yes to it yourself. Nothing has been changed."
    ),
    Blocked.NEEDS_THE_WORKERS_WORD: (
        "I will not call this off unless you tell me to yourself. Nothing has been changed."
    ),
}
"""What a blocked turn says. Written here, so a model never phrases a refusal it caused."""

REFUSAL_SENTENCES: Final[dict[ToolCode, str]] = {
    ToolCode.OUT_OF_SCOPE: (
        "That is not something this system can act on, so I have not acted on it."
    ),
    ToolCode.INVALID_ARGUMENT: "The case engine would not accept that, so nothing has changed.",
    ToolCode.UNKNOWN_RESOURCE: "I have no case by that identity.",
    ToolCode.CASE_NOT_IN_STATE: (
        "That case has moved on since I last read it, so I have not acted on what I read. "
        "Here is where it stands now."
    ),
    ToolCode.UNAUTHORIZED_SURFACE: "I am not permitted to do that on this case.",
    ToolCode.ENGINE_UNAVAILABLE: (
        "I could not reach the system that holds this case, so nothing has changed. "
        "Ask me again in a moment."
    ),
}
"""One sentence per refusal code, deterministic and rendered here rather than by a model.

A refusal is exactly where a conversational layer is most tempted to be helpful, and the
helpful version of "that case has moved on" is a guess about what it moved to. These say what
happened and what did not, and the remedy for every one of them is the same: read the case.
"""


@dataclass(frozen=True, slots=True)
class Action:
    """One tool call the loop has decided to make, with every argument already filled in.

    ``arguments`` is built by :func:`plan` from the worker's turn and from the conversation's
    own memory of what a trusted tool returned. It is complete when this value exists: there is
    no later step at which anything is added to it, and nothing a model produced is in it.
    """

    tool: ConversationTool
    name: str
    arguments: dict[str, str]

    @property
    def effecting(self) -> bool:
        return self.tool in EFFECTING


def plan(tool: ConversationTool, conversation: Conversation, turn: str) -> Action | Blocked:
    """Turn a chosen verb into a complete call, or into the reason there will not be one.

    The second gate on availability, after the semantic boundary's. Both read the same table,
    which is the point rather than duplication: the boundary refuses an answer that named an
    unavailable verb, and this refuses one that arrived any other way -- a caller holding a
    conversation from before the case moved, a future surface that skipped the model entirely.

    Every argument below is either ``turn`` -- the worker's words, byte for byte -- or a value
    the conversation copied out of a tool result. The plan identity in particular is the one
    ``status`` handed over, so a confirmation quotes a plan back and cannot describe one.
    """
    if tool is ConversationTool.NONE:
        return Blocked.NOT_UNDERSTOOD
    if tool not in permitted_for(conversation.phase):
        return Blocked.NOT_PERMITTED_HERE
    if tool is ConversationTool.REPORT:
        return Action(tool, TOOL_NAMES[tool], {"text": turn})

    case_id = conversation.case_id
    if case_id is None:
        return Blocked.NO_CASE_YET
    if tool is ConversationTool.STATUS:
        return Action(tool, TOOL_NAMES[tool], {"case_id": case_id})
    if tool is ConversationTool.CLARIFY:
        return Action(tool, TOOL_NAMES[tool], {"case_id": case_id, "answer": turn})
    if tool is ConversationTool.WITHDRAW:
        # No plan identity, because a withdrawal is not about a plan: it stops the case, and
        # what that means for each promise is decided from rows under the case lock. The one
        # gate here is that the worker themselves asked for it.
        if not reads_as_worker_withdrawal(turn):
            return Blocked.NEEDS_THE_WORKERS_WORD
        return Action(tool, TOOL_NAMES[tool], {"case_id": case_id})

    plan_id = conversation.plan_id
    if plan_id is None:
        return Blocked.NO_PLAN_TO_CONFIRM
    if not reads_as_worker_confirmation(turn):
        return Blocked.NEEDS_THE_WORKERS_YES
    return Action(tool, TOOL_NAMES[tool], {"case_id": case_id, "plan_id": plan_id})


# ---------------------------------------------------------------------- the worker's own yes

AFFIRMATIONS: Final[frozenset[str]] = frozenset(
    {
        "affirmative",
        "confirm",
        "confirm it",
        "confirm that",
        "confirmed",
        "correct",
        "do it",
        "go ahead",
        "go for it",
        "ok",
        "okay",
        "please do",
        "sounds good",
        "thats right",
        "yeah",
        "yep",
        "yes",
        "yes please",
        "yup",
    }
)
"""The forms a worker's yes may take. Closed, and the *whole* of what they said must be one.

Not a sentiment reading and not a classifier. It is a short list of the things a person
actually says when they mean yes, and a turn made of nothing but these is a yes. Anything
else -- a question about the plan, agreement with the reasoning, a condition, an instruction to
change something first -- is not, and the worker is asked plainly to say so.

The set is unchanged from the one this module has always held. What changed is that it is now
read as an allowlist over the entire turn rather than as an opening token with a free tail.
"""

_AFFIRMATION_PHRASES: Final[frozenset[tuple[str, ...]]] = frozenset(
    tuple(phrase.split()) for phrase in AFFIRMATIONS
)
"""``AFFIRMATIONS`` as word tuples, which is the only form the grammar compares against."""

_LONGEST_AFFIRMATION: Final[int] = max(len(phrase) for phrase in _AFFIRMATION_PHRASES)
"""How far ahead the grammar ever has to look. Derived, so the set stays the single source."""

WITHDRAWALS: Final[frozenset[str]] = frozenset(
    {
        "call it off",
        "call that off",
        "cancel it",
        "cancel that",
        "cancel this",
        "disregard that",
        "drop it",
        "forget it",
        "forget that",
        "ignore that",
        "ignore this",
        "leave it",
        "never mind",
        "nevermind",
        "scrap it",
        "scrap that",
        "stop it",
        "stop this",
        "withdraw it",
        "withdraw that",
        "withdraw this",
    }
)
"""The forms a worker's "stop this" may take. Closed, and matched only at the start of a turn.

Not a sentiment reading. A worker who is unhappy with a plan, arguing with it or asking for a
different one has not withdrawn anything, and reading dissatisfaction as a withdrawal would stop
a case nobody asked to stop. The list is short on purpose: it fails towards asking again, which
costs a turn, rather than towards calling off work somebody wanted.
"""

_WORD_SEPARATORS = re.compile(r"[^a-z0-9]+")


def normalise(text: str) -> str:
    """Somebody's words with case and punctuation removed, for comparison and nothing else.

    Only ever used to *decline* to act. The words that reach the case engine are never this
    value: ``report`` and ``clarify`` forward the original string, because what was said is
    evidence and the first thing anything does to evidence must be nothing.

    It is lossy, deliberately and irreparably: ``don't`` becomes ``don t`` and ``that's right``
    becomes ``that s right``. Neither caller may rely on a negation surviving it.
    :func:`reads_as_worker_confirmation` does not -- it requires every word to be an affirmation,
    so a turn this mangles fails rather than passing with its meaning removed.
    """
    return " ".join(_WORD_SEPARATORS.sub(" ", text.lower()).split())


def reads_as_worker_confirmation(text: str) -> bool:
    """Whether the worker themselves said yes to the plan in this turn.

    One condition, and it is about the **whole** turn: every word of it, in order, must be
    spanned by phrases from the closed :data:`AFFIRMATIONS` set and nothing else. *yes*, *ok*,
    *do it*, *yes please* and *yeah go ahead* are confirmations; a turn carrying one single word
    that is not an affirmation is not one, whatever that word is and wherever it sits. A
    confirmation additionally needs a plan identity the worker was actually read, which
    :func:`plan` checks separately -- so a yes to nothing in particular confirms nothing.

    **Why an allowlist and not a list of disqualifiers.** This check used to accept an opening
    affirmation followed by anything, minus a short blacklist of words that qualify a yes. That
    is unsound in two ways at once, and both were live. A blacklist can only ever be as complete
    as the last sentence somebody thought of, so *"yes, if the customer agrees"* and *"yes, once
    the oven is fixed"* authorised a plan nobody had authorised. And :func:`normalise` turns
    punctuation into spaces, so *"yes, don't proceed"* became ``yes don t proceed`` -- the
    blacklisted ``dont`` was never there to be found, and a refusal was read as approval.

    Spanning the whole turn closes both holes structurally rather than by enumeration.
    Normalisation can no longer convert a refusal into an approval, because whatever it makes of
    *don't* -- ``don t``, ``dont``, anything at all -- those words are not affirmations, so the
    turn fails as a whole. Nothing outside the set can appear anywhere, which is why the set does
    not have to grow to stay safe. It fails towards asking again, which costs a turn, rather than
    towards confirming something nobody agreed to, which costs an order.

    Not the customer consent parser, not reachable from it, and not a substitute for it. A
    customer's agreement is a literal reply on that order's own channel, checked by
    :mod:`promisepatch.domain.consent`, which this module cannot import and does not resemble.
    """
    words = tuple(normalise(text).split())
    if not words:
        return False
    reached = [False] * (len(words) + 1)
    reached[0] = True
    for start in range(len(words)):
        if not reached[start]:
            continue
        for length in range(1, min(_LONGEST_AFFIRMATION, len(words) - start) + 1):
            if words[start : start + length] in _AFFIRMATION_PHRASES:
                reached[start + length] = True
    return reached[len(words)]


def reads_as_worker_withdrawal(text: str) -> bool:
    """Whether the worker themselves asked for this case to stop, in this turn.

    The mirror of :func:`reads_as_worker_confirmation`, and strict for the mirrored reason. A
    withdrawal stops work a person asked for, so it must not be reachable by a model reading
    frustration into a sentence: the turn has to open with one of a closed set of the ways
    people actually say "call this off".

    Matched at the start of the turn and nowhere else, which has an honest cost: "no, cancel
    it" is plainly a withdrawal and is not read as one, and the worker is asked to say it
    again. A parser that searched anywhere in the sentence would also match "what happens if I
    cancel that", and telling those two apart needs exactly the reading this module refuses to
    do. It fails towards asking, which costs a turn.
    """
    words = normalise(text).split()
    if not words:
        return False
    return any(words[: len(parts)] == parts for parts in (p.split() for p in WITHDRAWALS))


__all__ = [
    "AFFIRMATIONS",
    "BLOCKED_SENTENCES",
    "EFFECTING",
    "HEADLINE_PHASES",
    "MAX_TOOL_CALLS_PER_TURN",
    "PERMITTED",
    "REFUSAL_SENTENCES",
    "TOOL_NAMES",
    "WITHDRAWALS",
    "Action",
    "Blocked",
    "CaseReading",
    "Conversation",
    "normalise",
    "permitted_for",
    "phase_of",
    "plan",
    "reads_as_worker_confirmation",
    "reads_as_worker_withdrawal",
]
