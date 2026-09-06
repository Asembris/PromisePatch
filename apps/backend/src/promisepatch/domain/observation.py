"""What a worker said about the kitchen, and what a deterministic reading of it may conclude.

Pure by construction: no database, no clock, no network, no environment. Everything the
interpreter is allowed to know arrives as a value on :class:`ObservationContext`, and
everything it is allowed to conclude is one of the three outcomes below.

Three separate authorities meet in this slice and the vocabulary keeps them apart:

* **Semantic interpretation** is what this module and :mod:`~promisepatch.domain.interpretation`
  do. Resolving "the raspberries" to a resource row, or noticing that a delivery has a second
  line nobody mentioned, decides *nothing* about the world.
* **Physical-fact authority** belongs to the worker who observed it. The interpreter may
  narrow a report to one commitment and one scope; it may never conclude a physical outcome
  the worker did not attest, which is why an unresolved scope becomes a question rather than a
  guess.
* **Recovery authorization** is not in this slice at all. Nothing here classifies a promise,
  proposes an option or touches an order.

**A statement is data, never an instruction.** The raw text is matched against a fixed,
closed lexicon and against vocabulary drawn from persisted rows. There is no path by which a
phrase in a worker's sentence can name an outcome the graph does not already contain.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final
from uuid import UUID

from promise_graph.model import ExceptionCategory, ReceivedState, ResourceKind

# ------------------------------------------------------------------------------- case states

CASE_RECEIVED: Final = "RECEIVED"
CASE_INTERPRETING: Final = "INTERPRETING"
CASE_CLARIFYING: Final = "CLARIFYING"
CASE_NEEDS_HUMAN: Final = "NEEDS_HUMAN_INTERPRETATION"
"""The four intake states, restated here because this module may not reach the schema.

Intake never reaches ``ANALYZED``: that state means propagation has run and every promise
carries a classification, and no promise has been looked at yet. A resolved intake leaves the
case in ``INTERPRETING`` with its interpretation step ``DONE`` and a
:data:`EVENT_READY_FOR_ANALYSIS` event on the spine, which is what the analysis slice consumes.
A test asserts these four values are members of the schema's own vocabulary.
"""

CLARIFICATION_CEILING: Final = 2
"""How many clarifications a case may ask before the owner has to bind it by hand.

The frozen interaction contract: one clarification is the target, two is the hard ceiling, and
a third would be interrogating the worker rather than asking them something.
"""

# ------------------------------------------------------------------------------- vocabulary


class ReportKind(StrEnum):
    """Why a worker spoke, which decides what their words are allowed to mean.

    A ``REPORT`` opens the binding. A ``CLARIFICATION_ANSWER`` may only choose among options
    the system derived from stored rows. A ``CORRECTION`` may only restate the physical
    outcome of lines that are already bound -- it never rebinds the exception.
    """

    REPORT = "REPORT"
    CLARIFICATION_ANSWER = "CLARIFICATION_ANSWER"
    CORRECTION = "CORRECTION"


class ClarificationSlot(StrEnum):
    """Which part of the binding is ambiguous. The frozen deterministic triggers."""

    COMMITMENT = "COMMITMENT"
    SCOPE = "SCOPE"


class EscalationReason(StrEnum):
    """Why the deterministic reading stopped rather than choosing.

    Every member is a place where continuing would have meant inventing a physical fact. The
    case goes to a human with the raw words intact and nothing written.
    """

    NO_CATEGORY = "NO_CATEGORY"
    AMBIGUOUS_CATEGORY = "AMBIGUOUS_CATEGORY"
    NO_RESOURCE = "NO_RESOURCE"
    AMBIGUOUS_RESOURCE = "AMBIGUOUS_RESOURCE"
    RESOURCE_KIND_MISMATCH = "RESOURCE_KIND_MISMATCH"
    NO_OPEN_COMMITMENT = "NO_OPEN_COMMITMENT"
    UNKNOWN_QUANTITY = "UNKNOWN_QUANTITY"
    CLARIFICATION_UNRESOLVED = "CLARIFICATION_UNRESOLVED"
    CLARIFICATION_CEILING_REACHED = "CLARIFICATION_CEILING_REACHED"
    CORRECTION_UNRESOLVED = "CORRECTION_UNRESOLVED"
    NOT_BOUND = "NOT_BOUND"
    SEMANTIC_UNAVAILABLE = "SEMANTIC_UNAVAILABLE"
    """No model could be reached inside the retry bound, so nobody has read the sentence yet.

    The only member here that is about PromisePatch rather than about the words. It is kept
    apart from the others because an operator seeing it should go and look at a provider, not
    at what the worker said -- and because a reading that never happened must never be
    reported as a reading that found nothing.
    """


WHOLE_DELIVERY_CODE: Final = "WHOLE_DELIVERY"
"""The option code for "all of it", the same word whatever the delivery contained."""


def just_code(resource_name: str) -> str:
    """The option code for "only this one", derived from the resource's own stored name.

    ``raspberries`` becomes ``JUST_RASPBERRIES``. Derived rather than authored, so a fixture
    with different ingredients produces different codes without anybody editing this file.
    """
    slug = "".join(character if character.isalnum() else "_" for character in resource_name)
    return f"JUST_{slug.upper()}"


# ------------------------------------------------------------------------------- step naming

STEP_BEGIN_INTERPRETATION: Final = "BEGIN_INTERPRETATION"
STEP_RESOLVE_OBSERVATION: Final = "RESOLVE_OBSERVATION"
STEP_INTERPRET_SEMANTICALLY: Final = "INTERPRET_SEMANTICALLY"
"""The step that exists only because the deterministic reading could not conclude.

A third intake step rather than a branch inside the second, because the model call has to
happen with no transaction held. The step is claimed, its reading is fetched and persisted
outside the governed block, and the transaction that consumes it holds the case lock like
every other transition. A case that never needs it never grows one.
"""

INTAKE_STEP_KINDS: Final[frozenset[str]] = frozenset(
    {STEP_BEGIN_INTERPRETATION, STEP_RESOLVE_OBSERVATION, STEP_INTERPRET_SEMANTICALLY}
)
"""Step kinds the worker routes to the intake executor rather than to a pure handler.

Deliberately *not* members of :class:`~promisepatch.domain.model.StepKind`. That enum is the
set of synthetic handlers that decide from a context alone; these three need the graph, so
they are named separately and a stored step naming one is dispatched by name.
"""


def begin_step_key(command_id: UUID) -> str:
    """The step that moves a case into ``INTERPRETING``, named after the statement that caused it.

    Derived from the command id rather than invented, so a retried command proposes the
    identical key and the unique index on ``(case_id, step_key)`` refuses the second one.
    """
    return f"interpret:{command_id}"


def resolve_step_key(command_id: UUID) -> str:
    """The step that actually interprets. Successor of :func:`begin_step_key`, same identity."""
    return f"resolve:{command_id}"


def semantic_step_key(command_id: UUID) -> str:
    """The step that asks a model what the deterministic reader could not work out.

    Same identity as the two before it, so a resolve step that ran, failed to commit and ran
    again proposes the identical successor and the unique index refuses the second.
    """
    return f"semantic:{command_id}"


def statement_id_of(step_key: str) -> UUID:
    """The statement an intake step is about, read back out of its key."""
    _, _, suffix = step_key.partition(":")
    return UUID(suffix)


# ------------------------------------------------------------------------------ event names

EVENT_CASE_OPENED: Final = "case.opened"
EVENT_CLARIFICATION_REQUIRED: Final = "exception.clarification_required"
EVENT_CLARIFICATION_ANSWERED: Final = "exception.clarification_answered"
EVENT_CORRECTION_REPORTED: Final = "exception.correction_reported"
EVENT_FACT_RECORDED: Final = "physical_fact.recorded"
EVENT_FACT_CORRECTED: Final = "physical_fact.corrected"
EVENT_NEEDS_HUMAN: Final = "case.needs_human_interpretation"
EVENT_READY_FOR_ANALYSIS: Final = "case.ready_for_analysis"
EVENT_SEMANTIC_REQUESTED: Final = "exception.semantic_interpretation_requested"
EVENT_SEMANTIC_RESOLVED: Final = "exception.semantic_interpretation_resolved"
"""The spine's account of intake.

Envelopes only: the type, the case and the entities touched. The authoritative detail lives in
``exception_facts``, ``commitment_lines`` and ``inventory_ledger``, because a feed that carried
a customer's order into every signed-in browser would be publishing business detail on the
strength of a schema nobody reviewed for that purpose.
"""

# ------------------------------------------------------------------------------ audit types

AUDIT_CASE_OPENED: Final = "CASE_OPENED"
AUDIT_CLARIFICATION_REQUESTED: Final = "CLARIFICATION_REQUESTED"
AUDIT_CLARIFICATION_ANSWERED: Final = "CLARIFICATION_ANSWERED"
AUDIT_CORRECTION_REPORTED: Final = "CORRECTION_REPORTED"
AUDIT_PHYSICAL_FACT_RECORDED: Final = "PHYSICAL_FACT_RECORDED"
AUDIT_PHYSICAL_FACT_CORRECTED: Final = "PHYSICAL_FACT_CORRECTED"
AUDIT_NEEDS_HUMAN_INTERPRETATION: Final = "NEEDS_HUMAN_INTERPRETATION"
AUDIT_SEMANTIC_INTERPRETATION_REQUESTED: Final = "SEMANTIC_INTERPRETATION_REQUESTED"
"""The deterministic reading stopped and a model was asked to help read the sentence.

Its actor is the worker *process*, never the model and never the person: what happened is
that PromisePatch decided a sentence was worth a second reading. Nothing about the kitchen is
claimed by this row, and nothing downstream may treat it as evidence that anything is.
"""

SOURCE_DETERMINISTIC: Final = "DETERMINISTIC"
SOURCE_SEMANTIC_ASSISTED: Final = "SEMANTIC_ASSISTED"
"""How a binding was arrived at, recorded beside every intake outcome.

Provenance, not authority. A fact reached with a model's help is the same domain object as one
reached without: same table, same attestor, same rule id, and the same thing downstream reads.
The distinction exists so an operator can answer "who read this sentence", never so that a
rule can behave differently depending on the answer.
"""

RULE_PHYSICAL_FACT_ATTESTED: Final = "R-PHYSICAL-FACT-ATTESTED"
"""The rule a physical fact is recorded under, named by the architecture.

Not one of the twelve classification rule ids, and deliberately so: those decide what may be
done to a customer promise, and this decides nothing at all. It records that a person who was
standing in the kitchen said what they saw.
"""

FACT_TARGET_COMMITMENT_LINE: Final = "commitment_line"
FACT_TARGET_RESOURCE: Final = "resource"
FACT_TARGET_EQUIPMENT: Final = "equipment"

# ------------------------------------------------------------------- the interpreter's input


@dataclass(frozen=True, slots=True)
class ResourceView:
    """One resource, reduced to what naming it requires. No quantities, no recipes."""

    id: str
    kind: ResourceKind
    name: str
    aliases: tuple[str, ...] = ()

    @property
    def terms(self) -> tuple[str, ...]:
        """Every spoken form of this resource, longest first so the specific one wins."""
        return tuple(sorted({self.name, *self.aliases}, key=lambda term: (-len(term), term)))


@dataclass(frozen=True, slots=True)
class CommitmentLineView:
    """One expected line of a delivery, and whether it is still open."""

    id: str
    resource_id: str
    quantity: Decimal | None
    received_state: ReceivedState

    @property
    def is_open(self) -> bool:
        return self.received_state is ReceivedState.EXPECTED


@dataclass(frozen=True, slots=True)
class CommitmentView:
    """One supplier delivery. ``supplier_name`` is what a question about it is phrased with."""

    id: str
    supplier_id: str
    supplier_name: str
    due_at: datetime
    lines: tuple[CommitmentLineView, ...]

    @property
    def open_lines(self) -> tuple[CommitmentLineView, ...]:
        return tuple(line for line in self.lines if line.is_open)

    def lines_for(self, resource_id: str) -> tuple[CommitmentLineView, ...]:
        return tuple(line for line in self.lines if line.resource_id == resource_id)


@dataclass(frozen=True, slots=True)
class Statement:
    """One thing a worker said, with who said it and when they saw it.

    ``observed_at`` is when the kitchen looked like this; ``id`` is the caller's stable command
    identity, which is what makes a retried transport delivery one statement rather than two.
    """

    id: UUID
    kind: ReportKind
    raw_text: str
    reported_by: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ClarificationOption:
    """One answer the system will accept, and what choosing it would mean.

    ``scope_line_ids`` and ``commitment_id`` are the *consequence* of the option and are
    derived from stored rows when the question is asked, so answering cannot name a line that
    was not already on the delivery.
    """

    code: str
    label: str
    keywords: tuple[str, ...] = ()
    scope_line_ids: tuple[str, ...] = ()
    commitment_id: str | None = None


@dataclass(frozen=True, slots=True)
class ClarificationView:
    """A question that has been asked, the answer if one arrived, and what it was asked about.

    The last three fields are the binding the question was derived from, persisted with it. A
    question is only ever asked once the category and the resource are settled, so an answer to
    it resolves against those rather than against a fresh reading of the original sentence --
    which matters most for a sentence whose reading was hard-won in the first place.
    """

    id: UUID
    ordinal: int
    slot: ClarificationSlot
    question: str
    options: tuple[ClarificationOption, ...]
    answer_text: str | None = None
    category: ExceptionCategory | None = None
    resource_id: str | None = None
    commitment_id: str | None = None

    def option(self, code: str) -> ClarificationOption | None:
        for candidate in self.options:
            if candidate.code == code:
                return candidate
        return None


@dataclass(frozen=True, slots=True)
class BoundExceptionView:
    """What a case has already been bound to. Present only once interpretation resolved once."""

    id: UUID
    category: ExceptionCategory
    commitment_id: str | None
    scope_line_ids: tuple[str, ...]
    resource_id: str | None


@dataclass(frozen=True, slots=True)
class ObservationContext:
    """Everything the interpreter may read. Hydrated from persisted rows by the caller.

    ``now`` and the day window are passed in rather than computed: the interpreter never calls
    a clock, and "today" is a claim about the bakery's calendar day, which only the caller
    knows the timezone of.
    """

    now: datetime
    day_start: datetime
    day_end: datetime
    resources: tuple[ResourceView, ...]
    commitments: tuple[CommitmentView, ...]
    on_hand: Mapping[str, Decimal | None]
    report: Statement
    current: Statement
    open_clarification: ClarificationView | None = None
    clarifications_asked: int = 0
    bound: BoundExceptionView | None = None

    def resource(self, resource_id: str) -> ResourceView | None:
        for candidate in self.resources:
            if candidate.id == resource_id:
                return candidate
        return None

    def commitment(self, commitment_id: str) -> CommitmentView | None:
        for candidate in self.commitments:
            if candidate.id == commitment_id:
                return candidate
        return None

    @property
    def may_ask_again(self) -> bool:
        return self.clarifications_asked < CLARIFICATION_CEILING


# ------------------------------------------------------------------ the interpreter's output


@dataclass(frozen=True, slots=True)
class ResolvedObservation:
    """A binding the worker's own words support, with nothing filled in on their behalf.

    ``scope_line_ids`` names the lines that did **not** arrive. Every other open line of the
    same commitment arrived, because the worker attesting that this one is missing is
    simultaneously attesting that the rest of the crate is on the bench -- which is why the
    clarification that decides the scope is consequential rather than cosmetic.
    """

    category: ExceptionCategory
    commitment_id: str | None = None
    scope_line_ids: tuple[str, ...] = ()
    resource_id: str | None = None
    quantity: Decimal | None = None
    outage_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class ClarificationRequired:
    """A question whose candidates came from the graph, never from the sentence."""

    slot: ClarificationSlot
    question: str
    options: tuple[ClarificationOption, ...]
    category: ExceptionCategory
    commitment_id: str | None = None
    resource_id: str | None = None

    @property
    def context(self) -> dict[str, str | None]:
        """What the question was derived from, persisted so the answer resolves against it."""
        return {
            "category": self.category.value,
            "commitment_id": self.commitment_id,
            "resource_id": self.resource_id,
        }


@dataclass(frozen=True, slots=True)
class HumanInterpretationRequired:
    """The deterministic reading stopped. Nothing is written, and the words are kept."""

    reason: EscalationReason
    detail: str


@dataclass(frozen=True, slots=True)
class LineOutcome:
    """One commitment line, and the physical outcome a correction attests for it."""

    commitment_line_id: str
    received_state: ReceivedState


@dataclass(frozen=True, slots=True)
class CorrectionResolved:
    """A later attestation about lines that are already settled.

    Names only what the worker corrected. Lines they did not mention keep whatever was already
    attested about them -- a correction is a new claim, not a replacement history.
    """

    outcomes: tuple[LineOutcome, ...] = field(default_factory=tuple)


InterpretationOutcome = (
    ResolvedObservation | ClarificationRequired | CorrectionResolved | HumanInterpretationRequired
)


__all__: Sequence[str] = [
    "AUDIT_CASE_OPENED",
    "AUDIT_CLARIFICATION_ANSWERED",
    "AUDIT_CLARIFICATION_REQUESTED",
    "AUDIT_CORRECTION_REPORTED",
    "AUDIT_NEEDS_HUMAN_INTERPRETATION",
    "AUDIT_PHYSICAL_FACT_CORRECTED",
    "AUDIT_PHYSICAL_FACT_RECORDED",
    "AUDIT_SEMANTIC_INTERPRETATION_REQUESTED",
    "CASE_CLARIFYING",
    "CASE_INTERPRETING",
    "CASE_NEEDS_HUMAN",
    "CASE_RECEIVED",
    "CLARIFICATION_CEILING",
    "EVENT_CASE_OPENED",
    "EVENT_CLARIFICATION_ANSWERED",
    "EVENT_CLARIFICATION_REQUIRED",
    "EVENT_CORRECTION_REPORTED",
    "EVENT_FACT_CORRECTED",
    "EVENT_FACT_RECORDED",
    "EVENT_NEEDS_HUMAN",
    "EVENT_READY_FOR_ANALYSIS",
    "EVENT_SEMANTIC_REQUESTED",
    "EVENT_SEMANTIC_RESOLVED",
    "FACT_TARGET_COMMITMENT_LINE",
    "FACT_TARGET_EQUIPMENT",
    "FACT_TARGET_RESOURCE",
    "INTAKE_STEP_KINDS",
    "RULE_PHYSICAL_FACT_ATTESTED",
    "SOURCE_DETERMINISTIC",
    "SOURCE_SEMANTIC_ASSISTED",
    "STEP_BEGIN_INTERPRETATION",
    "STEP_INTERPRET_SEMANTICALLY",
    "STEP_RESOLVE_OBSERVATION",
    "WHOLE_DELIVERY_CODE",
    "BoundExceptionView",
    "ClarificationOption",
    "ClarificationRequired",
    "ClarificationSlot",
    "ClarificationView",
    "CommitmentLineView",
    "CommitmentView",
    "CorrectionResolved",
    "EscalationReason",
    "HumanInterpretationRequired",
    "InterpretationOutcome",
    "LineOutcome",
    "ObservationContext",
    "ReportKind",
    "ResolvedObservation",
    "ResourceView",
    "Statement",
    "begin_step_key",
    "just_code",
    "resolve_step_key",
    "semantic_step_key",
    "statement_id_of",
]
