"""How a semantic call fails, and why the difference between the two kinds matters.

There are exactly two ways to not get an answer, and they are separated here because the
right response to them is opposite.

*The provider could not be reached.* A timeout, a throttle, a service error. Nothing is known
about what the model would have said, and asking again may well work.

*The model answered something PromisePatch will not accept.* Malformed output, a field that
is not in the schema, an identifier nobody offered it, a word outside the closed vocabulary.
Asking the same question again is not a fix; the answer was wrong in a way that repeats.

Neither one produces a value. That is the whole point of naming them: a semantic failure that
could be turned into a plausible default would be a model deciding something by failing, and
the deterministic protocol would never see that it had.
"""

from __future__ import annotations

from enum import StrEnum


class SemanticError(Exception):
    """Base of every way a semantic call can end without a validated result."""


class SemanticProviderError(SemanticError):
    """The provider could not be reached, or answered something that is not a response.

    ``retryable`` says whether presenting the same request again could plausibly succeed. It
    describes the transport, never the content: a throttle is retryable because the request
    was never read, and a malformed answer is not a provider error at all.
    """

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class SemanticTimeoutError(SemanticProviderError):
    """The model did not answer inside the configured bound.

    Retryable in the transport sense and still a failure here: a caller that waited longer
    would be a voice turn that never ends, and a caller that guessed would be a model
    deciding by silence.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class ValidationFailure(StrEnum):
    """Why a model's answer was not accepted, in the categories worth counting separately.

    These are the observable shape of "the model is not authoritative". Each one is a place
    where a system that trusted structured output would have written something.
    """

    MISSING_TOOL_USE = "MISSING_TOOL_USE"
    """The model answered in prose instead of calling the one tool it was given."""

    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    """The tool input was not a JSON object at all."""

    SCHEMA_INVALID = "SCHEMA_INVALID"
    """Missing a required field, wrong type, or a field the schema does not declare."""

    UNKNOWN_CANDIDATE = "UNKNOWN_CANDIDATE"
    """An identifier PromisePatch did not offer. Plausible, well-formed, and not real."""

    UNSUPPORTED_VOCABULARY = "UNSUPPORTED_VOCABULARY"
    """A closed label outside the set this job's request allowed."""

    WORD_CAP_EXCEEDED = "WORD_CAP_EXCEEDED"
    """Longer than the caller said it could be. A cap is part of the contract, not advice."""


class SemanticValidationError(SemanticError):
    """The model answered, and the answer is not usable. Carries no partial value.

    Deliberately not a subclass of :class:`SemanticProviderError`: the provider did its job.
    Whatever the caller does about this, it is not "try the same call again and hope".
    """

    def __init__(self, message: str, *, category: ValidationFailure) -> None:
        super().__init__(message)
        self.category = category


__all__ = [
    "SemanticError",
    "SemanticProviderError",
    "SemanticTimeoutError",
    "SemanticValidationError",
    "ValidationFailure",
]
