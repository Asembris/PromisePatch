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

from pydantic import BaseModel, ConfigDict, Field

from promise_graph.model import ExceptionCategory

MAX_UNTRUSTED_CHARACTERS = 4_000
"""How much of somebody's words one semantic request may carry.

A bound rather than a budget. Anything longer than this is not a worker reporting a delivery
or a customer answering a message, and sending it would be paying to have a model read
something that arrived at the wrong door.
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
    """One deterministic fact, already decided and already rendered, offered for phrasing."""

    label: str
    value: str


class VerbaliseRequest(Strict):
    """Say what deterministic code has already concluded, in a bounded number of words.

    The facts are the whole input. Nothing here is a question, so there is nothing for the
    model to work out -- which is exactly why a sentence it produces can be thrown away and
    replaced by a template without changing anything the system did.
    """

    job: Literal[SemanticJob.VERBALISE] = SemanticJob.VERBALISE
    subject: str
    facts: tuple[EvidenceFact, ...]
    word_limit: int = Field(ge=1, le=120)
    metadata: SemanticMetadata = SemanticMetadata()


type SemanticRequest = Annotated[
    InterpretUtteranceRequest | ClassifyReplyIntentRequest | VerbaliseRequest,
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
    """One sentence saying what was already decided."""

    speech: str = Field(max_length=1_000)


type SemanticValue = ObservationInterpretation | ReplyIntentReading | Verbalisation
"""Everything a validated semantic call may hand back. None of it authorises anything."""


__all__ = [
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
    "EvidenceFact",
    "InterpretUtteranceRequest",
    "ObservationInterpretation",
    "ReplyIntentReading",
    "SemanticJob",
    "SemanticMetadata",
    "SemanticRequest",
    "SemanticValue",
    "Strict",
    "UntrustedText",
    "Verbalisation",
    "VerbaliseRequest",
]
