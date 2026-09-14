"""What may be asked of a model, and what it is allowed to answer. Values only, no I/O.

This module is the trust line written down as types. Everything above it in PromisePatch
decides; everything the model produces arrives here first and is nothing but a proposal until
a deterministic caller has looked at it.

Four properties are structural rather than remembered:

* **Untrusted text is a different type.** A worker's sentence and a customer's reply are
  :class:`UntrustedText`, never a bare ``str`` on a request. A test walks every request model
  and asserts it, so "we forgot this field was somebody's words" cannot happen quietly, and
  the prompt builder has one obvious thing to fence.
* **Identifiers are chosen, never written.** Every job that refers to an entity carries the
  candidates with it, and the reading is checked against them. A model cannot name a resource
  by being confident about it.
* **The vocabulary contains no authority.** ``APPARENT_APPROVE`` is the strongest thing a
  reading of a customer's reply can say, and it is not ``APPROVE``: it is not a member of the
  same enum, does not share a value with one, and cannot be handed to anything that records a
  decision. A test asserts the two vocabularies stay disjoint.
* **Results are strict.** Every model here forbids unknown fields, so an answer carrying
  something nobody asked for is rejected rather than partially believed.

Nothing in this module reaches a database, a provider, a clock or the environment.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from promise_graph.model import ExceptionCategory

MAX_UNTRUSTED_CHARACTERS = 4_000
"""How much of somebody's words one semantic request may carry.

A bound rather than a budget. Anything longer than this is not a worker reporting a delivery
or a customer answering a message, and sending it would be paying to have a model read
something that arrived at the wrong door.
"""

MAX_EVIDENCE_FACTS = 16
"""How many already-decided facts one verbalisation may be built from.

Small on purpose. A passage of forty spoken words cannot honestly rest on more than a handful
of facts, and a caller that wanted to send a whole case would be sending state rather than a
conclusion -- which is the shape this job exists to refuse.
"""

MAX_FACT_ID_CHARACTERS = 64
MAX_FACT_TEXT_CHARACTERS = 200
"""Bounds on one fact's name, label and rendered value. Values, not essays."""

MAX_PREFACE_CHARACTERS = 200
"""How long the one piece of model-written conversational glue may be.

Small because it is not carrying anything. Everything a worker is *told* is rendered
deterministically; this is the sentence in front of it, and a paragraph's worth of room would
be room to start explaining.
"""

FACT_ID_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$"
"""The shape of a fact identifier: dotted, lowercase, ``resource.shortfall``.

Enforced on the request rather than on the answer, because the request is the side
PromisePatch writes. What the model returns is checked against the ids that were actually
sent, which is a stronger question than whether a string looks like one.
"""


class Strict(BaseModel):
    """Frozen, extra-forbidding base for every contract in this module.

    ``extra="forbid"`` is what makes "the model returned a field the schema does not declare"
    a rejection instead of a silently ignored surprise.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


# ----------------------------------------------------------------------------------- jobs


class SemanticJob(StrEnum):
    """The bounded set of things a model is asked to do, named as the architecture names them.

    There is no general "ask the model" job and there is no room to add one without adding a
    contract, a schema and a validator beside it. That is the point: the surface a model can
    reach is enumerable, and each entry is small enough to read in one sitting.
    """

    INTERPRET_UTTERANCE = "interpret_utterance"
    """Read a worker's sentence against the graph's own vocabulary."""

    CLASSIFY_REPLY_INTENT = "classify_reply_intent"
    """Read a customer's free text into one of three non-authoritative labels."""

    VERBALISE = "verbalise"
    """Say deterministic evidence in a sentence. Concludes nothing and may add nothing."""

    SELECT_TOOL = "select_tool"
    """Choose which of the tools already permitted here a worker's turn is asking for.

    A choice among things the caller has already decided are allowed, never a proposal of an
    action. The answer carries no arguments -- there is no field on it for a case, a plan, a
    quantity or a person -- so the strongest thing it can do is name one of a handful of verbs
    the deterministic caller was going to allow anyway.
    """


# ------------------------------------------------------------------------- untrusted input


class UntrustedText(Strict):
    """Something a person wrote, carried as data and never as instruction.

    A wrapper rather than a naming convention, because the difference between "the operator
    configured this" and "somebody typed this at us" is the difference the whole
    prompt-injection posture rests on, and a convention is not checkable.
    """

    text: str = Field(max_length=MAX_UNTRUSTED_CHARACTERS)


class SemanticMetadata(Strict):
    """Correlation for the log line, and nothing the model is shown.

    Deliberately absent from every prompt: a case id is data the model does not need in order
    to do its job, and could repeat back as though it meant something.
    """

    correlation_id: str | None = None
    case_id: str | None = None


# ------------------------------------------------------------------------------ candidates


class CandidateNodeType(StrEnum):
    """The kinds of thing a binding may point at. Closed, because the validator is a lookup."""

    RESOURCE = "RESOURCE"
    COMMITMENT = "COMMITMENT"
    COMMITMENT_LINE = "COMMITMENT_LINE"
    EQUIPMENT = "EQUIPMENT"


class CandidateResource(Strict):
    """One resource the model may name, with the words a person would use for it."""

    id: str
    name: str
    aliases: tuple[str, ...] = ()


class CandidateCommitmentLine(Strict):
    """One open line of a delivery. Quantities are deliberately absent.

    The model is being asked which line somebody meant, not how much of it there was. A
    quantity it was never shown is a quantity it cannot repeat back as though it were a fact.
    """

    id: str
    resource_id: str


class CandidateCommitment(Strict):
    """One supplier delivery the model may name, and the lines inside it."""

    id: str
    supplier_name: str
    due_at: datetime
    lines: tuple[CandidateCommitmentLine, ...] = ()


class CandidateEquipment(Strict):
    """One piece of equipment the model may name."""

    id: str
    name: str


class ConversationTool(StrEnum):
    """The finite verbs a conversational turn can be a request for. Closed, and closed early.

    These are the frozen tool names of the MCP surface, plus ``NONE``. A model choosing among
    them is choosing among things PromisePatch already listed as permitted for the state the
    case is actually in -- so the vocabulary itself carries no reach: there is no member here
    that edits an order, records a consent decision, names a recipe version or attests a
    physical fact, because there is no such tool to name.

    ``WITHDRAW`` is the only member that can stop a case, and stopping is all it does: it
    carries no reason, reverses nothing already applied and makes no claim about the kitchen,
    because none of those is a thing this vocabulary can express.

    ``NONE`` is always available and is the right answer whenever a turn is not a request for
    any of the others. It exists so that "say nothing and change nothing" is inside the
    vocabulary rather than something a model has to fail in order to express.
    """

    REPORT = "REPORT"
    CLARIFY = "CLARIFY"
    CONFIRM = "CONFIRM"
    WITHDRAW = "WITHDRAW"
    STATUS = "STATUS"
    NONE = "NONE"


class ConversationPhase(StrEnum):
    """How far the durable case has got, in the only detail a tool choice depends on.

    Derived by deterministic code from a case reading the server rendered, and sent to the
    model as one closed label rather than as a case. A model is not shown the state machine
    and cannot argue with the phase: it is told which phase it is in and which verbs that
    phase permits, and both were decided before it was asked anything.
    """

    NO_CASE = "NO_CASE"
    UNDERSTANDING = "UNDERSTANDING"
    CLARIFYING = "CLARIFYING"
    PLANNED = "PLANNED"
    WORKING = "WORKING"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    SETTLED = "SETTLED"


class ClarificationContext(Strict):
    """What was already asked, and which answers are on offer.

    Present only when the worker is answering a question PromisePatch asked. The option codes
    were derived from stored rows by deterministic code; the model may recognise one, and it
    may not invent one.
    """

    slot: str
    option_codes: tuple[str, ...]


# -------------------------------------------------------------------------------- requests


class InterpretUtteranceRequest(Strict):
    """Read one worker sentence against the vocabulary the graph actually contains.

    Everything the model is allowed to know arrives on this object. There is no retrieval step
    and no second lookup: the bakery's vocabulary is small enough to state outright, which is
    what makes the reading checkable against the same list the caller sent.
    """

    job: Literal[SemanticJob.INTERPRET_UTTERANCE] = SemanticJob.INTERPRET_UTTERANCE
    utterance: UntrustedText
    categories: tuple[ExceptionCategory, ...]
    resources: tuple[CandidateResource, ...] = ()
    commitments: tuple[CandidateCommitment, ...] = ()
    equipment: tuple[CandidateEquipment, ...] = ()
    clarification: ClarificationContext | None = None
    metadata: SemanticMetadata = SemanticMetadata()


class ClassifyReplyIntentRequest(Strict):
    """Read one customer reply. The text, and nothing else at all.

    No order, no option, no case, no history. A classifier that knew which answer would be
    convenient is a classifier with a reason to give it -- and this one is only ever allowed
    to cause a confirmation prompt in the first place.
    """

    job: Literal[SemanticJob.CLASSIFY_REPLY_INTENT] = SemanticJob.CLASSIFY_REPLY_INTENT
    reply: UntrustedText
    metadata: SemanticMetadata = SemanticMetadata()


class EvidenceFact(Strict):
    """One deterministic fact, already decided and already rendered, offered for phrasing.

    ``id`` is the whole reason this is a record rather than a sentence. A fact the caller can
    name is a fact the answer can be checked against: the passage that comes back says which
    ids it rests on, and an id nobody sent is an answer about something PromisePatch did not
    say. Without it the only available check would be reading the prose, which is the thing
    this boundary exists not to have to do.
    """

    id: str = Field(max_length=MAX_FACT_ID_CHARACTERS, pattern=FACT_ID_PATTERN)
    label: str = Field(max_length=MAX_FACT_TEXT_CHARACTERS)
    value: str = Field(max_length=MAX_FACT_TEXT_CHARACTERS)


class VerbaliseRequest(Strict):
    """Say what deterministic code has already concluded, in a bounded number of words.

    The facts are the whole input. Nothing here is a question, so there is nothing for the
    model to work out -- which is exactly why a sentence it produces can be thrown away and
    replaced by a template without changing anything the system did.

    ``required_fact_ids`` is the application saying which of those facts the passage may not
    leave out. Deterministic code decides that, because which cause matters is a property of
    the outcome and not of the phrasing: a blocked promise whose passage never mentions the
    rule that blocked it is a fluent answer to a different question.
    """

    job: Literal[SemanticJob.VERBALISE] = SemanticJob.VERBALISE
    subject: str = Field(max_length=MAX_FACT_TEXT_CHARACTERS)
    facts: tuple[EvidenceFact, ...] = Field(min_length=1, max_length=MAX_EVIDENCE_FACTS)
    required_fact_ids: tuple[str, ...] = ()
    word_limit: int = Field(ge=1, le=120)
    metadata: SemanticMetadata = SemanticMetadata()

    @model_validator(mode="after")
    def _requirements_are_offered(self) -> VerbaliseRequest:
        """A required fact must be one of the facts sent, and the ids must be distinct.

        An invariant of the *caller*, checked here so it cannot be got wrong quietly: a
        request demanding a fact it never supplied could only ever be refused, and two facts
        sharing an id would make a reference ambiguous.
        """
        ids = [fact.id for fact in self.facts]
        if len(set(ids)) != len(ids):
            raise ValueError("two facts share an id")
        missing = [fact_id for fact_id in self.required_fact_ids if fact_id not in set(ids)]
        if missing:
            raise ValueError(f"required fact(s) {', '.join(sorted(missing))} were not supplied")
        return self


class SelectToolRequest(Strict):
    """Which permitted verb this turn is asking for. The turn, the phase, and the offer.

    Everything on this request was decided before the model was asked. ``permitted`` is
    computed from a case reading the server rendered; ``phase`` is the label that computation
    produced. The model is not shown the case, the plan, the promises, the customers or the
    identifiers -- choosing a verb needs none of them, and each one would be something to
    repeat back as though it were a fact.

    There is no field here a model could fill in, because a request is not something a model
    produces. What it produces is :class:`ToolSelection`, which carries a verb and no
    arguments at all.
    """

    job: Literal[SemanticJob.SELECT_TOOL] = SemanticJob.SELECT_TOOL
    turn: UntrustedText
    phase: ConversationPhase
    permitted: tuple[ConversationTool, ...] = Field(min_length=1, max_length=4)
    metadata: SemanticMetadata = SemanticMetadata()

    @model_validator(mode="after")
    def _offer_is_a_real_offer(self) -> SelectToolRequest:
        """The offered verbs must be distinct and must be verbs.

        ``NONE`` is not offered because it is never withheld: it is available in every phase,
        so listing it would suggest a phase could exist in which a model was obliged to pick
        something. A repeated member would mean the caller built the offer twice.
        """
        if ConversationTool.NONE in self.permitted:
            raise ValueError("NONE is always available and is not an offer")
        if len(set(self.permitted)) != len(self.permitted):
            raise ValueError("a tool was offered twice")
        return self


type SemanticRequest = Annotated[
    InterpretUtteranceRequest | ClassifyReplyIntentRequest | VerbaliseRequest | SelectToolRequest,
    Field(discriminator="job"),
]
"""Every question that may be put to a model, discriminated by the job that owns it."""


# --------------------------------------------------------------------------------- results


class CandidateBinding(Strict):
    """One thing in the sentence, pointed at one identifier the caller supplied.

    ``confidence`` is the model's own opinion of its own reading, and authorises nothing. It
    exists so a deterministic caller can prefer one candidate over another -- and can decline
    to prefer any of them.
    """

    node_type: CandidateNodeType
    node_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_span: str = Field(max_length=200)


class ObservationInterpretation(Strict):
    """A reading of a worker's sentence. It proposes; it concludes nothing.

    There is no field here for a physical outcome, and that is deliberate rather than an
    omission. Whether the raspberries arrived is a fact a person standing in the kitchen
    attested. A model reading the sentence may say which delivery was being talked about, and
    the vocabulary lets it say nothing further.
    """

    category: ExceptionCategory | None = None
    bindings: tuple[CandidateBinding, ...] = ()
    scope_hint: str | None = Field(default=None, max_length=200)
    quantity_hint: str | None = Field(default=None, max_length=100)
    clarification_needed: bool = False
    """Whether the sentence looked ambiguous to the model. Advice, never a trigger.

    The clarification protocol's triggers are deterministic and its candidates come from the
    resolver. This flag can make a caller look harder; it cannot make it ask.
    """

    out_of_scope: bool = False


class ApparentIntent(StrEnum):
    """The three readings of a customer's free text. The frozen closed vocabulary.

    Every member says *apparent* or says nothing, and none of them is a member of
    ``ApprovalDecisionKind``. A caller holding one of these cannot pass it where a decision is
    expected, because it is not that type and does not carry that word. That is what makes
    "the model never produces a consent decision" a property of the code rather than a
    convention somebody has to keep remembering.
    """

    APPARENT_APPROVE = "APPARENT_APPROVE"
    APPARENT_DECLINE = "APPARENT_DECLINE"
    UNCLEAR = "UNCLEAR"


class ReplyIntentReading(Strict):
    """What a customer's reply appeared to mean. One label, and nothing else.

    No confidence, no rationale, no quoted text. Each of those would be a reason for somebody
    downstream to treat this as more than it is, and the protocol's answer to all three labels
    is the same single confirmation prompt anyway.
    """

    apparent_intent: ApparentIntent


class Verbalisation(Strict):
    """One passage saying what was already decided, and the facts it rests on.

    There is no field here for an outcome, a status, a decision or a recommendation, and that
    is the whole design. The passage is presentation: PromisePatch already knows what happened
    and displays it from its own columns, so a sentence claiming something else is a sentence
    that is wrong on screen rather than a sentence that changed anything.

    ``fact_refs`` is what makes an answer checkable without reading it. Every reference must be
    one of the ids the caller supplied, and every id the caller marked required must appear --
    so an answer that reached past its facts, or quietly dropped the cause, is refused and the
    deterministic rendering of the same facts is used instead.
    """

    speech: str = Field(max_length=1_000)
    fact_refs: tuple[str, ...] = Field(default=(), max_length=MAX_EVIDENCE_FACTS)


class ToolSelection(Strict):
    """One verb, and at most one sentence of glue in front of it. No arguments, ever.

    The whole authority argument for the conversational loop is the shape of this class.
    There is no ``case_id`` here, no ``plan_id``, no ``text``, no ``answer``, no worker and no
    customer: a model cannot supply an argument to a tool because there is nowhere on its
    answer to put one. Every argument that reaches the MCP surface is either the worker's own
    turn, forwarded verbatim, or an opaque identifier a trusted tool returned -- and both are
    filled in by deterministic code after this value has been validated.

    ``preface`` is conversational glue and nothing else. It is placed *before* the
    deterministically rendered sentence, never instead of it, and it is checked against a
    closed list of words that would make it a claim about the world. A preface that cannot be
    accepted fails the whole answer rather than being quietly trimmed, because a repaired
    sentence is one nobody wrote.
    """

    tool: ConversationTool
    preface: str | None = Field(default=None, max_length=MAX_PREFACE_CHARACTERS)


type SemanticValue = ObservationInterpretation | ReplyIntentReading | Verbalisation | ToolSelection
"""Everything a validated semantic call may hand back. None of it authorises anything."""


__all__ = [
    "FACT_ID_PATTERN",
    "MAX_EVIDENCE_FACTS",
    "MAX_FACT_ID_CHARACTERS",
    "MAX_FACT_TEXT_CHARACTERS",
    "MAX_PREFACE_CHARACTERS",
    "MAX_UNTRUSTED_CHARACTERS",
    "ApparentIntent",
    "CandidateBinding",
    "CandidateCommitment",
    "CandidateCommitmentLine",
    "CandidateEquipment",
    "CandidateNodeType",
    "CandidateResource",
    "ClarificationContext",
    "ClassifyReplyIntentRequest",
    "ConversationPhase",
    "ConversationTool",
    "EvidenceFact",
    "InterpretUtteranceRequest",
    "ObservationInterpretation",
    "ReplyIntentReading",
    "SelectToolRequest",
    "SemanticJob",
    "SemanticMetadata",
    "SemanticRequest",
    "SemanticValue",
    "Strict",
    "ToolSelection",
    "UntrustedText",
    "Verbalisation",
    "VerbaliseRequest",
]
