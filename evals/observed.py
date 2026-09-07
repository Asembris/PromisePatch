"""What came back for one case: a validated reading, or a named refusal, and never both.

An observation is the whole of what the acceptance path produced. It is deliberately *not* the
raw payload a provider emitted: the thing worth measuring is what PromisePatch would have gone
on to do, and that is decided by :func:`promisepatch.semantic.jobs.validate` and then by
:mod:`promisepatch.domain.grounding`. A metric reading the raw payload would be scoring a model
against a schema nobody enforces.

Two shapes and no third:

* a value survived validation, and for a worker case it has also been put through production
  grounding, so the observation carries what deterministic code decided;
* nothing survived, and the observation carries which category of refusal happened.

``telemetry`` is whatever the provider published. In replay it is a fake's telemetry: one
provider, no model id, no tokens, no latency. Those stay absent rather than becoming zero.
"""

from __future__ import annotations

from dataclasses import dataclass

from evals.cases import Outcome
from promisepatch.domain.grounding import Grounding
from promisepatch.domain.observation import (
    ClarificationRequired,
    ClarificationSlot,
    EscalationReason,
    HumanInterpretationRequired,
    InterpretationOutcome,
    ResolvedObservation,
)
from promisepatch.semantic import (
    ApparentIntent,
    ObservationInterpretation,
    ReplyIntentReading,
    SemanticTelemetry,
)


@dataclass(frozen=True, slots=True)
class WorkerObservation:
    """One reading of a worker sentence, and what deterministic grounding made of it."""

    reading: ObservationInterpretation
    grounding: Grounding
    outcome: InterpretationOutcome

    @property
    def outcome_kind(self) -> Outcome:
        if isinstance(self.outcome, ResolvedObservation):
            return Outcome.RESOLVED
        if isinstance(self.outcome, ClarificationRequired):
            return Outcome.CLARIFICATION
        return Outcome.ESCALATED

    @property
    def clarification_slot(self) -> ClarificationSlot | None:
        if isinstance(self.outcome, ClarificationRequired):
            return self.outcome.slot
        return None

    @property
    def escalation_reason(self) -> EscalationReason | None:
        if isinstance(self.outcome, HumanInterpretationRequired):
            return self.outcome.reason
        return None

    @property
    def accepted_resource_id(self) -> str | None:
        return self.grounding.accepted[0] if self.grounding.accepted else None


@dataclass(frozen=True, slots=True)
class CustomerObservation:
    """One reading of a customer reply. A label from the closed set, and nothing else."""

    reading: ReplyIntentReading

    @property
    def apparent_intent(self) -> ApparentIntent:
        return self.reading.apparent_intent


@dataclass(frozen=True, slots=True)
class Refusal:
    """Nothing usable came back, and this is the category of why.

    ``category`` is a :class:`~promisepatch.semantic.errors.ValidationFailure` value when the
    model answered something the boundary refused, and the exception class name when the
    provider could not be reached. Kept as a string so a summary can count both kinds in one
    column without pretending they are the same thing -- the ``provider_error`` flag says
    which.
    """

    category: str
    provider_error: bool = False


type Observed = WorkerObservation | CustomerObservation | Refusal


def is_refusal(observed: Observed) -> bool:
    return isinstance(observed, Refusal)


@dataclass(frozen=True, slots=True)
class CaseObservation:
    """One case's answer plus the telemetry the provider published about producing it."""

    observed: Observed
    telemetry: SemanticTelemetry | None = None


__all__ = [
    "CaseObservation",
    "CustomerObservation",
    "Observed",
    "Refusal",
    "WorkerObservation",
    "is_refusal",
]
