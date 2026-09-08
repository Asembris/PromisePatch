"""One specification per semantic job, and the single gate every answer passes through.

A job spec is the whole of what a model is given and what it is held to: the tool it must
call, the schema that tool's input has to satisfy, the output ceiling, and the check that the
answer refers only to things PromisePatch offered it.

**Every provider validates here.** The fake and the Bedrock client do not each have their own
idea of what a good answer looks like -- they produce a payload and hand it to
:func:`validate`. That is what makes a test written against the fake mean something about the
real one, and what stops a second acceptance path from appearing the next time somebody adds
a provider.

**Validation is two questions, not one.** *Is this the shape we asked for* is Pydantic's, and
a strict schema answers it. *Is this about things that exist* is ours, and no schema can
answer it: ``res-blueberry`` is a perfectly well-formed identifier and there is no such
resource. The second check is the one that matters, because a model's failure mode is not
malformed JSON -- it is confident, plausible, well-typed invention.

For ``verbalise`` the second question has three parts, because a passage can go wrong in three
directions: it can reach past the facts it was given, fall short of the ones the application
said it could not leave out, or state a number that appears in none of them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import pydantic

from promisepatch.semantic.contracts import (
    CandidateNodeType,
    InterpretUtteranceRequest,
    ObservationInterpretation,
    ReplyIntentReading,
    SemanticJob,
    SemanticRequest,
    SemanticValue,
    Verbalisation,
    VerbaliseRequest,
)
from promisepatch.semantic.errors import SemanticValidationError, ValidationFailure
from promisepatch.semantic.prompts import build_system_instruction


@dataclass(frozen=True, slots=True)
class JobSpec:
    """Everything one job needs, in one place a reviewer can read end to end."""

    job: SemanticJob
    tool_name: str
    tool_description: str
    result_model: type[pydantic.BaseModel]
    max_tokens: int
    """The output ceiling for this job. Bounded per job, because these answers are small.

    A cap is a cost control and a safety property at once: a job that can only emit a few
    hundred tokens cannot emit an essay arguing for itself.
    """

    @property
    def system_instruction(self) -> str:
        return build_system_instruction(self.job)

    def tool_schema(self) -> dict[str, Any]:
        """The JSON Schema the model's tool input must satisfy, derived from the result model.

        Generated rather than hand-written, so the schema the model is shown and the schema
        the answer is validated against cannot drift apart.

        Stripped of the prose Pydantic lifts out of docstrings. Those paragraphs are written
        for whoever maintains this and explain what the boundary refuses and why; sending them
        to a model would pay per token to narrate our own defences to the thing they defend
        against.
        """
        pruned: dict[str, Any] = _without_prose(self.result_model.model_json_schema())
        return pruned


def _without_prose(schema: object) -> Any:
    """The same schema with every ``title`` and ``description`` removed, recursively.

    Structure and vocabulary survive -- types, enums, required fields, ``additionalProperties``
    -- because those are what the model has to satisfy and what the validator checks.
    """
    if isinstance(schema, Mapping):
        return {
            key: _without_prose(value)
            for key, value in schema.items()
            if key not in {"title", "description"}
        }
    if isinstance(schema, list):
        return [_without_prose(item) for item in schema]
    return schema


JOB_SPECS: Final[Mapping[SemanticJob, JobSpec]] = {
    SemanticJob.INTERPRET_UTTERANCE: JobSpec(
        job=SemanticJob.INTERPRET_UTTERANCE,
        tool_name="record_interpretation",
        tool_description=(
            "Record which of the listed candidates the worker's sentence referred to. "
            "Records nothing in any system; it is how you return your reading."
        ),
        result_model=ObservationInterpretation,
        max_tokens=512,
    ),
    SemanticJob.CLASSIFY_REPLY_INTENT: JobSpec(
        job=SemanticJob.CLASSIFY_REPLY_INTENT,
        tool_name="record_apparent_intent",
        tool_description=(
            "Record how the customer's message reads. This is not a consent decision and "
            "cannot approve or decline anything."
        ),
        result_model=ReplyIntentReading,
        max_tokens=64,
    ),
    SemanticJob.VERBALISE: JobSpec(
        job=SemanticJob.VERBALISE,
        tool_name="record_speech",
        tool_description=(
            "Record the spoken phrasing of the facts you were given, and the ids of the "
            "facts it rests on. Records nothing in any system and changes no outcome."
        ),
        result_model=Verbalisation,
        max_tokens=256,
    ),
}
"""The jobs that exist. A model reaches nothing that is not in this mapping."""


def spec_for(request: SemanticRequest) -> JobSpec:
    """The specification governing one request."""
    return JOB_SPECS[request.job]


def validate(request: SemanticRequest, payload: object) -> SemanticValue:
    """Turn a model's raw tool input into a typed value, or fail closed saying why.

    Never returns a partial or repaired result. There is no branch here that drops an
    offending field and keeps the rest: an answer containing one identifier nobody offered is
    an answer from a model that was willing to invent one, and the rest of it is not evidence
    of anything.
    """
    spec = spec_for(request)
    if not isinstance(payload, Mapping):
        raise SemanticValidationError(
            f"{spec.job.value}: the model's answer is not an object",
            category=ValidationFailure.MALFORMED_OUTPUT,
        )
    data = dict(payload)

    if isinstance(request, InterpretUtteranceRequest):
        return _ground_interpretation(request, _parse(spec, ObservationInterpretation, data))
    if isinstance(request, VerbaliseRequest):
        return _ground_verbalisation(request, _parse(spec, Verbalisation, data))
    return _parse(spec, ReplyIntentReading, data)


def _parse[Result: pydantic.BaseModel](
    spec: JobSpec, model: type[Result], data: dict[str, Any]
) -> Result:
    """Strict schema validation, with the failure named in the category the telemetry counts."""
    try:
        return model.model_validate(data)
    except pydantic.ValidationError as error:
        raise SemanticValidationError(
            f"{spec.job.value}: {error.error_count()} field(s) do not match the schema",
            category=_schema_failure(error),
        ) from error


def _schema_failure(error: pydantic.ValidationError) -> ValidationFailure:
    """Whether the schema was violated by shape or by a word outside a closed set.

    Worth separating in the telemetry: a wrong type is a model having a bad day, and a value
    like ``APPROVE`` where only ``APPARENT_APPROVE`` exists is a model reaching for authority.
    """
    kinds = {detail["type"] for detail in error.errors()}
    if kinds & {"enum", "literal_error"}:
        return ValidationFailure.UNSUPPORTED_VOCABULARY
    return ValidationFailure.SCHEMA_INVALID


def _ground_interpretation(
    request: InterpretUtteranceRequest, value: ObservationInterpretation
) -> ObservationInterpretation:
    """Every identifier and every category must have come from the request.

    The enum alone is not enough for the category: ``STOCK_UNUSABLE`` is a real member and may
    still not be one of the categories this caller was willing to consider.
    """
    if value.category is not None and value.category not in request.categories:
        raise SemanticValidationError(
            f"category {value.category.value} was not offered to the model",
            category=ValidationFailure.UNSUPPORTED_VOCABULARY,
        )

    allowed = _allowed_ids(request)
    for binding in value.bindings:
        if binding.node_id not in allowed[binding.node_type]:
            raise SemanticValidationError(
                f"{binding.node_type.value} {binding.node_id!r} is not a candidate "
                f"PromisePatch supplied",
                category=ValidationFailure.UNKNOWN_CANDIDATE,
            )
    return value


def _allowed_ids(
    request: InterpretUtteranceRequest,
) -> Mapping[CandidateNodeType, frozenset[str]]:
    """The only identifiers this request permits, by kind.

    Built from the request rather than from the database, and that is the point: the set the
    answer is checked against is exactly the set the model was shown, so a candidate list that
    was narrowed for a reason stays narrowed.
    """
    return {
        CandidateNodeType.RESOURCE: frozenset(item.id for item in request.resources),
        CandidateNodeType.COMMITMENT: frozenset(item.id for item in request.commitments),
        CandidateNodeType.COMMITMENT_LINE: frozenset(
            line.id for commitment in request.commitments for line in commitment.lines
        ),
        CandidateNodeType.EQUIPMENT: frozenset(item.id for item in request.equipment),
    }


def _ground_verbalisation(request: VerbaliseRequest, value: Verbalisation) -> Verbalisation:
    """Four questions, and any of them failing means the caller renders its own sentence.

    *Is it short enough.* A word cap is part of the contract, so exceeding it is a rejection
    and never a trim: truncating would produce a sentence nobody wrote, which is worse than
    falling back to the deterministic rendering the caller already holds.

    *Is it about facts we supplied.* Every reference must be one of the ids on the request.
    This is the verbalisation half of the rule that governs every other job here -- a model
    names things PromisePatch offered it, and nothing else.

    *Does it account for the facts that matter.* The application marked some of them required,
    because which cause matters is a property of the outcome. A passage that dropped one is
    refused rather than shown, since the sentence that survives would be true and beside the
    point.

    *Are its numbers ours.* Digits in the passage are compared with digits in the facts, and a
    figure that appears in none of them is refused. Narrow on purpose -- it understands nothing
    and a number written in words slips past it -- but "three kilograms short" where the engine
    computed 2.1 is the invention that actually costs somebody a cake.

    None of this claims the prose is faithful. It cannot: no check over free text proves that,
    and pretending otherwise would be the boundary overstating itself. What it does establish
    is that the passage refers to nothing invented and omits nothing mandatory -- and that the
    outcome on screen never comes from the passage at all.
    """
    words = len(value.speech.split())
    if words > request.word_limit:
        raise SemanticValidationError(
            f"the model returned {words} words against a limit of {request.word_limit}",
            category=ValidationFailure.WORD_CAP_EXCEEDED,
        )

    offered = {fact.id for fact in request.facts}
    unknown = sorted(set(value.fact_refs) - offered)
    if unknown:
        raise SemanticValidationError(
            f"the answer refers to {', '.join(unknown)}, which PromisePatch did not supply",
            category=ValidationFailure.UNKNOWN_CANDIDATE,
        )

    missing = sorted(set(request.required_fact_ids) - set(value.fact_refs))
    if missing:
        raise SemanticValidationError(
            f"the answer accounts for none of {', '.join(missing)}, which this outcome requires",
            category=ValidationFailure.MISSING_REQUIRED_FACT,
        )

    supplied = _numbers(" ".join(fact.value for fact in request.facts))
    invented = sorted(_numbers(value.speech) - supplied)
    if invented:
        raise SemanticValidationError(
            f"the answer states {', '.join(invented)}, which is in none of the facts it was given",
            category=ValidationFailure.UNSUPPORTED_QUANTITY,
        )
    return value


_DIGITS = re.compile(r"\d+(?:[.,]\d+)?")
"""Runs of digits, and nothing cleverer.

Deliberately not a natural-language number reader. This compares the digits in the passage with
the digits in the facts and refuses a passage that introduced one, which catches the failure
that matters -- a quantity the engine never computed -- without pretending to understand
anything. A number written in words passes it, so it is a floor and not a guarantee, and the
docstring on ``UNSUPPORTED_QUANTITY`` says so.
"""


def _numbers(text: str) -> set[str]:
    return set(_DIGITS.findall(text))


__all__ = ["JOB_SPECS", "JobSpec", "spec_for", "validate"]
