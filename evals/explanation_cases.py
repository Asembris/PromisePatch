"""What an explanation evaluation case is, and the projection that stops any of it reaching Nova.

A case is two things bolted together: one settled outcome's
:class:`~promisepatch.domain.explanations.ExplanationFacts`, and a set of claims about what a
good passage over those facts would be. Only the first half may ever be sent anywhere.

That separation is a type, not a convention. :func:`to_model_input` returns an
:class:`ExplanationModelInput` holding one
:class:`~promisepatch.semantic.contracts.VerbaliseRequest` and nothing else -- no reference
prose, no rubric, no threshold, no tag, no split, no expected verdict, and not the case id
inside the request's own metadata. There is no field on the way out that a desired answer could
travel in, which is why the leakage suite asserts absence rather than inspecting intent.

**The production contracts are used, never re-declared.** ``ExplanationSurface``, ``FactId``,
``Fact``, ``ExplanationFacts`` and ``VerbaliseRequest`` are the application's own types. A
parallel set of evaluation types would let the dataset and the thing it measures drift apart
while every test still passed -- and the request Nova is put would then be the harness's idea of
the request rather than the one production builds.

**Seven families over four surfaces.** The surface is what production distinguishes; the family
is the finer partition an evaluation has to distinguish, because ``TRACK_OUTCOME`` covers four
outcomes whose failure modes are nothing alike. A family maps onto exactly one surface and adds
no vocabulary the application does not have.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from pydantic import Field, model_validator

from evals.cases import EvalSplit, Frozen
from promisepatch.domain.explanations import (
    WORD_LIMITS,
    ExplanationFacts,
    ExplanationSurface,
    Fact,
    FactId,
)
from promisepatch.semantic import SemanticMetadata, VerbaliseRequest

SCHEMA_VERSION = "1"
"""The explanation dataset schema this module reads. A file declaring anything else is refused."""

CASE_ID_PATTERN = r"^explain\.[a-z]+\.\d{3}$"
"""``explain.blocked.001``. Deliberately says nothing about which split a case is in."""


class ExplanationFamily(StrEnum):
    """The seven things a passage is asked to say, frozen for this dataset.

    Four of them are one production surface -- ``TRACK_OUTCOME`` -- split by the outcome the
    facts carry, because the four outcomes fail in different directions and an average over
    them would hide whichever one is weak. A blocked promise's danger is invented alternatives;
    an unaffected one's is a plausible wrong reason; they are not one measurement.
    """

    PLAN_SUMMARY = "PLAN_SUMMARY"
    TRACK_AUTO_RECOVERABLE = "TRACK_AUTO_RECOVERABLE"
    TRACK_APPROVAL_REQUIRED = "TRACK_APPROVAL_REQUIRED"
    TRACK_BLOCKED = "TRACK_BLOCKED"
    TRACK_UNAFFECTED = "TRACK_UNAFFECTED"
    CUSTOMER_WAIT = "CUSTOMER_WAIT"
    REVALIDATION = "REVALIDATION"

    @property
    def surface(self) -> ExplanationSurface:
        """The production surface this family's cases are asked on."""
        return _SURFACES[self]

    @property
    def word_limit(self) -> int:
        """Spec 9.2's cap for the surface. Read from production, never restated here."""
        return WORD_LIMITS[self.surface]


_SURFACES: Final[dict[ExplanationFamily, ExplanationSurface]] = {
    ExplanationFamily.PLAN_SUMMARY: ExplanationSurface.PLAN_SUMMARY,
    ExplanationFamily.TRACK_AUTO_RECOVERABLE: ExplanationSurface.TRACK_OUTCOME,
    ExplanationFamily.TRACK_APPROVAL_REQUIRED: ExplanationSurface.TRACK_OUTCOME,
    ExplanationFamily.TRACK_BLOCKED: ExplanationSurface.TRACK_OUTCOME,
    ExplanationFamily.TRACK_UNAFFECTED: ExplanationSurface.TRACK_OUTCOME,
    ExplanationFamily.CUSTOMER_WAIT: ExplanationSurface.CUSTOMER_WAIT,
    ExplanationFamily.REVALIDATION: ExplanationSurface.REVALIDATION,
}


class ExplanationTag(StrEnum):
    """Why a case is in the dataset, from a controlled list.

    A closed vocabulary rather than free strings, because a tag is how coverage is claimed and
    a typo in a free string is a claimed dimension nobody is measuring. Tags are evaluation-only
    and are structurally unable to reach a model: see :class:`ExplanationModelInput`.
    """

    CANONICAL = "canonical"
    QUANTITY = "quantity"
    MULTIPLE_NUMBERS = "multiple_numbers"
    NUMBER_WORDS = "number_words"
    INSTRUCTION_LIKE_DATA = "instruction_like_data"
    LONG_ENTITY = "long_entity"
    PUNCTUATION = "punctuation"
    MULTIPLE_REQUIRED_FACTS = "multiple_required_facts"
    AUTHORITY_SENSITIVE = "authority_sensitive"
    UNAFFECTED_PRECISION = "unaffected_precision"
    STALE_REASON = "stale_reason"
    VOICE_BREVITY = "voice_brevity"
    SIMILAR_REASON_CODES = "similar_reason_codes"
    NEGATIVE_FACT = "negative_fact"


class FactFixture(Frozen):
    """One already-decided fact as the dataset states it, in production's own vocabulary."""

    id: FactId
    label: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=200)

    def fact(self) -> Fact:
        return Fact(id=self.id, label=self.label, value=self.value)


class FactsFixture(Frozen):
    """One settled outcome's facts, in the shape :mod:`promisepatch.domain.explanations` emits.

    Hand-authored, and then checked against production rather than believed: dataset validation
    rejects a value outside a closed vocabulary the engine draws from, a required fact that was
    not supplied, a fact count the request contract refuses, and a set of facts the deterministic
    renderer cannot phrase inside the surface's own word cap.
    """

    surface: ExplanationSurface
    facts: tuple[FactFixture, ...] = Field(min_length=1)
    required: tuple[FactId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _coherent(self) -> FactsFixture:
        ids = [fixture.id for fixture in self.facts]
        if len(set(ids)) != len(ids):
            raise ValueError("two facts share an id")
        missing = sorted({fact_id.value for fact_id in self.required} - {i.value for i in ids})
        if missing:
            raise ValueError(f"required fact(s) {', '.join(missing)} were not supplied")
        return self

    def explanation_facts(self) -> ExplanationFacts:
        """The production object. The only thing a model or the renderer is ever handed."""
        return ExplanationFacts(
            surface=self.surface,
            facts=tuple(fixture.fact() for fixture in self.facts),
            required=self.required,
        )

    def value_of(self, fact_id: FactId) -> str | None:
        for fixture in self.facts:
            if fixture.id is fact_id:
                return fixture.value
        return None

    def ids(self) -> frozenset[str]:
        return frozenset(fixture.id.value for fixture in self.facts)


_DIGITS: Final = re.compile(r"\d+(?:[.,]\d+)?")


class ExpectedHardConstraints(Frozen):
    """What must be true of any passage this case's facts are allowed to produce.

    Every field here is decidable without an opinion. The word cap and the required references
    are production's own contract restated so the manifest hashes them; the decisive fact is the
    one the outcome cannot be explained without, and it is what the unaffected and revalidation
    precision gates are read against; the two booleans are the authority claims that make one
    family's failure worse than another's.

    Nothing here is a score, a threshold or a desired verdict. Those live in
    :mod:`evals.explanation_thresholds`, apply to the run rather than to the case, and are not
    reachable from a judge request either.
    """

    word_limit: int = Field(ge=1, le=120)
    required_fact_refs: tuple[str, ...] = Field(min_length=1)
    decisive_fact: str = Field(min_length=1)
    """The already-decided cause a faithful passage has to carry. Spec 13.1's distinction.

    For an unaffected promise this is the reachability or reason fact, because "not affected"
    with the wrong cause is the failure the selectivity claim actually turns on. For a
    revalidation it is the deciding check the engine already picked.
    """

    approval_outstanding: bool = False
    """Whether the authoritative facts say a customer has not yet decided.

    ``True`` makes every claim of an existing approval, or of a change already made, a hard
    failure for this case rather than a matter of tone.
    """

    recovery_permitted: bool = False
    """Whether the facts offer any next action a passage may describe as available.

    ``False`` on a blocked promise is what makes "we can switch to strawberries" a hard failure:
    there is no such option in the facts, so the sentence invented one.
    """

    supported_numbers: tuple[str, ...] = ()
    """Every digit run the facts contain, which is the whole set a passage may state.

    Derived from the fixture and checked against it, so the manifest records the numeric surface
    of each case. It is what production's own digit guard compares against, and its known limit
    -- that a number written in words is not a digit run -- is the reason
    ``unsupported_quantity_in_words`` exists as a judged flag rather than a computed one.
    """


class ManualCalibration(Frozen):
    """A reviewer's note about what this case is for. Evaluation-only, and never sent anywhere.

    Deliberately prose rather than a score. A per-case expected score written before any model
    ran would be an opinion pretending to be data, and it would be the first thing somebody
    tuned a threshold against.
    """

    focus: str = Field(default="", max_length=400)


class ExplanationEvalCase(Frozen):
    """One settled outcome, and every evaluation-only claim made about explaining it."""

    id: str = Field(pattern=CASE_ID_PATTERN)
    split: EvalSplit
    family: ExplanationFamily
    tags: tuple[ExplanationTag, ...] = Field(min_length=1)
    facts: FactsFixture
    reference: str = Field(min_length=1, max_length=800)
    """One short hand-authored passage over these facts. A review anchor, never a gold string.

    It is not an exact answer, is not compared by similarity, is not a few-shot example, and is
    not sent to Nova or to the judge. What it is for is a human reading a live result and asking
    whether the model's passage is better or worse than one somebody wrote on purpose.
    """

    expected: ExpectedHardConstraints
    calibration: ManualCalibration = ManualCalibration()
    note: str = Field(default="", max_length=600)

    @property
    def surface(self) -> ExplanationSurface:
        return self.family.surface

    @property
    def word_limit(self) -> int:
        return self.family.word_limit

    def explanation_facts(self) -> ExplanationFacts:
        return self.facts.explanation_facts()


# ------------------------------------------------------------------- the leakage boundary


class ExplanationModelInput(Frozen):
    """Everything Nova is given for one case, and structurally nothing else.

    The only payload field is :attr:`request`, which is built by the production projection's own
    :meth:`~promisepatch.domain.explanations.ExplanationFacts.request` -- the identical object
    the workflow would send for the identical outcome. :attr:`case_id` and :attr:`family` are
    here so a runner can correlate an answer with the case it answers; neither is inside the
    request, neither is in the request's metadata, and
    :mod:`promisepatch.semantic.prompts` renders no metadata into any prompt.

    There is no reference, no rubric, no threshold, no tag, no split and no expected verdict on
    this type. That is the guarantee: an evaluation-only value cannot reach a model, because
    there is no field it could travel in.
    """

    case_id: str
    family: ExplanationFamily
    request: VerbaliseRequest


def to_model_input(case: ExplanationEvalCase) -> ExplanationModelInput:
    """Project one case into the question Nova is allowed to be asked, and nothing more."""
    request = case.explanation_facts().request()
    if request.metadata != SemanticMetadata():  # pragma: no cover - structural guard
        raise AssertionError("an explanation model input carried correlation metadata")
    return ExplanationModelInput(case_id=case.id, family=case.family, request=request)


def digits_in(text: str) -> frozenset[str]:
    """Every digit run in a string, the same way production's quantity guard reads one."""
    return frozenset(_DIGITS.findall(text))


def supported_digits(facts: FactsFixture) -> frozenset[str]:
    """The digit runs these facts supply, which is the whole set a passage may state."""
    return digits_in(" ".join(fixture.value for fixture in facts.facts))


__all__ = [
    "CASE_ID_PATTERN",
    "SCHEMA_VERSION",
    "ExpectedHardConstraints",
    "ExplanationEvalCase",
    "ExplanationFamily",
    "ExplanationModelInput",
    "ExplanationTag",
    "FactFixture",
    "FactsFixture",
    "ManualCalibration",
    "digits_in",
    "supported_digits",
    "to_model_input",
]
