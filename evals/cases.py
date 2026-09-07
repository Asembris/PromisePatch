"""What a gold case is, and the projection that stops any of it reaching a model.

A gold case is two things bolted together: an utterance somebody would really say, and a claim
about what PromisePatch would do with it. Only the first half may ever be sent anywhere.

That separation is a type, not a convention. :func:`to_model_input` takes a case and returns a
:class:`ModelInput` holding one semantic request and nothing else -- no expected label, no
rationale, no tag, no split, not even the case id inside the request's own metadata. There is
no field on the way out that could carry an answer, which is why the leakage suite can assert
absence rather than inspect intent.

The vocabulary is imported from production rather than restated. ``ExceptionCategory``,
``ApparentIntent``, ``GroundingFailure``, ``EscalationReason`` and ``ClarificationSlot`` are
the enums the application decides with, so a label in this dataset is the same value the code
under measurement produces. A second, parallel set of strings would let the dataset and the
system drift apart while every test still passed.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evals import context
from promise_graph.model import ExceptionCategory
from promisepatch.domain import grounding as grounding_rules
from promisepatch.domain.grounding import FALLBACK_REASONS, GroundingFailure
from promisepatch.domain.observation import ClarificationSlot, EscalationReason
from promisepatch.semantic import (
    ApparentIntent,
    ClassifyReplyIntentRequest,
    InterpretUtteranceRequest,
    SemanticJob,
    SemanticMetadata,
    SemanticRequest,
    UntrustedText,
)

SCHEMA_VERSION = "1"
"""The dataset schema this module reads. A file declaring anything else is refused."""


class Frozen(BaseModel):
    """Frozen, extra-forbidding base. An unrecognised key in a dataset file is an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class EvalJob(StrEnum):
    """The two semantic jobs this dataset measures, named for the files that hold them."""

    WORKER_SEMANTICS = "worker_semantics"
    CUSTOMER_INTENT = "customer_intent"

    @property
    def semantic_job(self) -> SemanticJob:
        """The production job this evaluation job puts questions to."""
        return _SEMANTIC_JOBS[self]


_SEMANTIC_JOBS = {
    EvalJob.WORKER_SEMANTICS: SemanticJob.INTERPRET_UTTERANCE,
    EvalJob.CUSTOMER_INTENT: SemanticJob.CLASSIFY_REPLY_INTENT,
}


class EvalSplit(StrEnum):
    """Which half of the dataset a case belongs to. Written down, never drawn at random.

    ``DEVELOPMENT`` is for debugging and for whatever prompt iteration comes later.
    ``HOLDOUT`` is the evidence half, and its results are read once rather than tuned against.

    This is an engineering holdout, not a blind external benchmark: the cases live in this
    repository and anyone may read them. What the split buys is a rule -- prompt changes are
    judged on development results -- and a rule is only worth anything if it is stated.
    """

    DEVELOPMENT = "development"
    HOLDOUT = "holdout"


class Outcome(StrEnum):
    """What an interpretation ended as, in the three shapes intake can reach.

    The same vocabulary describes what the deterministic lexicon does with a sentence on its
    own and what deterministic grounding does with a model's reading of it. Keeping one
    vocabulary is what makes "the lexicon escalated and the semantic layer resolved it" a
    comparison rather than a translation.
    """

    RESOLVED = "RESOLVED"
    CLARIFICATION = "CLARIFICATION"
    ESCALATED = "ESCALATED"


# --------------------------------------------------------------------------- worker cases


class WorkerExpectation(Frozen):
    """What a correct reading of one worker sentence is, and what must become of it.

    Two layers, deliberately named apart, because conflating them is the easy mistake:

    * :attr:`category` and :attr:`resource_id` describe the **semantic provider's output** --
      the one category and the one identity a model is asked for.
    * :attr:`grounding`, :attr:`outcome`, :attr:`clarification_slot` and
      :attr:`escalation_reason` describe **what deterministic code then does with it**, which
      is decided by :mod:`promisepatch.domain.grounding` and never by a model.

    A case may expect a perfect reading that still escalates, and several do. That is not a
    contradiction; it is the design.
    """

    category: ExceptionCategory | None = None
    resource_id: str | None = None
    """The identity deterministic grounding must accept, or ``None`` when it must accept none."""

    out_of_scope: bool = False
    """Whether a correct reading declares the sentence outside supply, stock and equipment."""

    proposed_resource_ids: tuple[str, ...] = ()
    """Every identity a correct reading names, which is not always the one that is accepted.

    A sentence naming two of the bakery's ingredients has a correct reading that proposes both
    and a correct outcome that binds neither: deterministic grounding refuses an ambiguous
    identity, and that refusal is the gold answer. Empty means "whatever :attr:`resource_id`
    says", which is the ordinary one-identity case.
    """

    grounding: GroundingFailure
    outcome: Outcome
    clarification_slot: ClarificationSlot | None = None
    escalation_reason: EscalationReason | None = None

    @property
    def proposals(self) -> tuple[str, ...]:
        """The identities a correct reading names, defaulting to the accepted one."""
        if self.proposed_resource_ids:
            return self.proposed_resource_ids
        return () if self.resource_id is None else (self.resource_id,)


class WorkerCase(Frozen):
    """One worker sentence, what the lexicon alone does with it, and what should follow."""

    id: str = Field(pattern=r"^worker\.[a-z0-9-]+\.[a-z0-9-]+\.\d{3}$")
    split: EvalSplit
    tags: tuple[str, ...] = Field(min_length=1)
    utterance: str = Field(min_length=1, max_length=400)

    deterministic: Outcome
    """What :func:`promisepatch.domain.interpretation.interpret` does with this sentence alone.

    Verified against production code by dataset validation rather than believed. A case that
    claims the lexicon cannot read a sentence the lexicon reads perfectly well would measure
    the semantic layer on work it never does.
    """

    deterministic_reason: EscalationReason | None = None

    expected: WorkerExpectation | None = None
    """What a correct reading is, or ``None`` when no model is ever asked about this sentence.

    Absent exactly when the deterministic reading did not stop at one of the four parse
    failures the fallback permits -- because it resolved, because it asked a question, or
    because it stopped somewhere a second reading would have to invent rather than read. Those
    cases are in the dataset to be measured on one thing: that nothing was asked. Dataset
    validation checks the two halves agree, so a case cannot carry an expectation the boundary
    would never reach.
    """

    note: str = ""

    @property
    def job(self) -> Literal[EvalJob.WORKER_SEMANTICS]:
        return EvalJob.WORKER_SEMANTICS

    @property
    def semantic_eligible(self) -> bool:
        """Whether this sentence is one a model is allowed to be asked about at all.

        The condition is production's own: the deterministic reading stopped, and it stopped
        for one of the four parse failures in
        :data:`promisepatch.domain.grounding.FALLBACK_REASONS`. Every other stop is a place
        where a second reading would have to invent something rather than read it, and no
        amount of dataset design turns those into semantic work.
        """
        return (
            self.deterministic is Outcome.ESCALATED
            and self.deterministic_reason is not None
            and self.deterministic_reason in FALLBACK_REASONS
        )

    @property
    def asked(self) -> bool:
        """Whether a runner puts this case to a provider at all. The production condition."""
        return self.semantic_eligible

    @property
    def rescuable(self) -> bool:
        """Whether a correct reading of this sentence gets the case moving again.

        The denominator of the safe rescue rate. A fallback-eligible sentence whose correct
        outcome is still an escalation cannot be rescued by anybody: "the berries didnt
        arrive" names no ingredient the bakery authored, and the right answer is a person.
        """
        return (
            self.semantic_eligible
            and self.expected is not None
            and self.expected.outcome is not Outcome.ESCALATED
        )


# ------------------------------------------------------------------------- customer cases


class CustomerCase(Frozen):
    """One customer reply, and the single non-authoritative label it should read as.

    There is no expected decision here and there cannot be one. All three labels produce the
    same confirmation prompt, and only a later literal ``YES`` or ``NO`` decides anything --
    so a wrong label on this page is a quality defect and never, by itself, an authority one.
    """

    id: str = Field(pattern=r"^customer\.[a-z0-9-]+\.[a-z0-9-]+\.\d{3}$")
    split: EvalSplit
    tags: tuple[str, ...] = Field(min_length=1)
    reply: str = Field(min_length=1, max_length=2_000)
    expected: ApparentIntent
    note: str = ""

    @property
    def job(self) -> Literal[EvalJob.CUSTOMER_INTENT]:
        return EvalJob.CUSTOMER_INTENT


type GoldCase = WorkerCase | CustomerCase


# ------------------------------------------------------------------- the leakage boundary


class ModelInput(Frozen):
    """Everything a provider is given for one case, and structurally nothing else.

    The only payload field is :attr:`request`, which is the same
    :class:`~promisepatch.semantic.contracts.SemanticRequest` production would build for the
    same sentence. :attr:`case_id` is here so a runner can correlate an answer with the case
    it answers; it is not inside the request, is not in the request's metadata, and is never
    rendered into a prompt -- ``SemanticMetadata`` is deliberately absent from every prompt
    builder in :mod:`promisepatch.semantic.prompts`.

    There is no expected label on this type, no rationale, no tag and no split. That is the
    guarantee: gold information cannot reach a model because there is no field it could
    travel in.
    """

    case_id: str
    job: EvalJob
    request: SemanticRequest


def to_model_input(case: GoldCase) -> ModelInput:
    """Project one gold case into the question a provider is allowed to be asked.

    For a worker case the request is built by
    :func:`promisepatch.domain.grounding.build_request` -- production's own candidate
    construction, against the frozen evaluation kitchen. The candidate set is therefore the
    same one the workflow would send, not one narrowed towards the answer, which is what stops
    a dataset from flattering the model it measures.
    """
    if isinstance(case, WorkerCase):
        request: SemanticRequest = grounding_rules.build_request(
            context.observation_context(case.id, case.utterance)
        )
    else:
        request = ClassifyReplyIntentRequest(reply=UntrustedText(text=case.reply))
    if request.metadata != SemanticMetadata():  # pragma: no cover - structural guard
        raise AssertionError("a model input carried correlation metadata")
    return ModelInput(case_id=case.id, job=case.job, request=request)


def is_interpret_request(request: SemanticRequest) -> bool:
    """Whether this is the worker job's request. A narrow helper, kept out of the runner."""
    return isinstance(request, InterpretUtteranceRequest)


__all__ = [
    "SCHEMA_VERSION",
    "CustomerCase",
    "EvalJob",
    "EvalSplit",
    "Frozen",
    "GoldCase",
    "ModelInput",
    "Outcome",
    "WorkerCase",
    "WorkerExpectation",
    "is_interpret_request",
    "to_model_input",
]
