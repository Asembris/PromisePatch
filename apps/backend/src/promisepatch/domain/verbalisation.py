"""Asking a model to say an outcome out loud, and saying it ourselves when it cannot.

This is the only place a verbalisation is obtained, and it is built around one property:

    Explanation output is never parsed back into workflow authority.

Nothing here returns a status, a classification, a decision, an option or a permission. It
returns a passage and where the passage came from. Every consequential field a screen or a
voice turn shows is read from PromisePatch's own columns, and a passage that contradicted one
of them would be wrong on screen rather than wrong in the ledger -- which is the difference
between a presentation defect and a system that let a model decide something.

**Failure is never a stall.** A provider that times out, a provider that is down, an answer
that will not parse, an answer naming a fact nobody sent, an answer that dropped the cause, and
a set of facts that will not fit in a question at all: all six produce the deterministic
rendering of the *same* facts, immediately, with the reason recorded. There is no branch in
which the workflow waits, retries around the caller, degrades or refuses. That is what makes it
safe for a recovery to be explained at all -- the explanation cannot become a precondition of
the recovery.

**Which of the two passages ships is a configured selection, not a race.** The P4.8
explanation gate measured the model path and did not select it: it was safe and it was not
reliably complete. :func:`explain` is therefore the production route, and with
``PP_EXPLANATION_VERBALISATION`` off -- the default -- it returns the deterministic rendering
without a provider being reached at all. :func:`prepare` is the evaluated capability
underneath it, kept whole and exercised by the evaluation harness, which measures the model it
was pointed at rather than the one this deployment ships.

**Two entry points, because a durable caller needs both halves.** :func:`prepare` makes the
call with no transaction held, exactly as every other provider call in PromisePatch does.
:func:`accept` is what the transaction that consumes it runs under the lock: it compares the
outcome the passage was written about with the outcome as it now stands, and discards a
passage that has been overtaken. A sentence about the case as it was is not a sentence about
the case as it is, however well written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import pydantic

from promisepatch.config import Settings, get_settings
from promisepatch.domain.explanations import ExplanationFacts, ExplanationSurface, render
from promisepatch.observability import get_logger
from promisepatch.semantic import (
    SemanticProvider,
    SemanticProviderError,
    SemanticValidationError,
    ValidationFailure,
    Verbalisation,
)

logger = get_logger(__name__)


class ExplanationSource(StrEnum):
    """Who phrased the passage that is being shown. Provenance, never authority."""

    VERBALISED = "VERBALISED"
    """A model's passage, having passed the schema, the word cap and the fact-reference check."""

    FALLBACK = "FALLBACK"
    """PromisePatch's own rendering of the same facts. Always available, never wrong."""


class ExplanationFailure(StrEnum):
    """Why a deterministic rendering was used. Three reasons, kept apart because they differ.

    A provider outage is an operational fact about somebody else's service. A rejected answer
    is a fact about the model: it produced something this boundary will not show. A discarded
    one is a fact about the case: it moved while the answer was in flight. Collapsing the three
    into "fallback" would leave an operator unable to tell a bad afternoon from a bad model.
    """

    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    SCHEMA_REJECTED = "SCHEMA_REJECTED"
    GROUNDING_REJECTED = "GROUNDING_REJECTED"
    STALE_DISCARDED = "STALE_DISCARDED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


_GROUNDING_FAILURES = frozenset(
    {
        ValidationFailure.UNKNOWN_CANDIDATE,
        ValidationFailure.MISSING_REQUIRED_FACT,
        ValidationFailure.UNSUPPORTED_QUANTITY,
        ValidationFailure.WORD_CAP_EXCEEDED,
    }
)
"""The refusals that are about the answer's relationship to the facts, not about its shape."""


@dataclass(frozen=True, slots=True)
class Explanation:
    """One passage, and everything an operator needs in order to distrust it correctly.

    ``fingerprint`` names the outcome the passage was written about. ``fact_refs`` are the
    already-decided facts it claims to rest on, every one of them checked against what was
    sent. Neither is a decision, and there is no field on this record that is.
    """

    surface: ExplanationSurface
    speech: str
    source: ExplanationSource
    fingerprint: str
    fact_refs: tuple[str, ...] = ()
    failure: ExplanationFailure | None = None
    detail: str | None = None
    provider: str | None = None
    model_id: str | None = None
    attempts: int | None = None

    @property
    def verbalised(self) -> bool:
        return self.source is ExplanationSource.VERBALISED

    def provenance(self) -> Mapping[str, Any]:
        """The record of this passage, in the shape the step ledger and audit already hold.

        Enough to answer later which surface was asked for, against which outcome, through
        which provider and model, whether a model's words were used, and why not when they were
        not. No prompt and no rejected model prose: neither is evidence of anything, and the
        row would then hold text nobody reviewed.
        """
        return {
            "surface": self.surface.value,
            "facts_hash": self.fingerprint,
            "source": self.source.value,
            "failure": None if self.failure is None else self.failure.value,
            "detail": self.detail,
            "provider": self.provider,
            "model_id": self.model_id,
            "provider_attempts": self.attempts,
            "fact_refs": list(self.fact_refs),
        }


def fallback(
    facts: ExplanationFacts,
    *,
    failure: ExplanationFailure = ExplanationFailure.NOT_ATTEMPTED,
    detail: str | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    attempts: int | None = None,
) -> Explanation:
    """PromisePatch's own passage, rendered from the same facts a model would have been given.

    Deliberately not a second reading of the case. The renderer is handed the identical
    :class:`~promisepatch.domain.explanations.ExplanationFacts` object, so the two passages can
    differ in how well they read and cannot differ about what happened.
    """
    return Explanation(
        surface=facts.surface,
        speech=render(facts),
        source=ExplanationSource.FALLBACK,
        fingerprint=facts.fingerprint(),
        fact_refs=tuple(fact.id.value for fact in facts.facts),
        failure=failure,
        detail=detail,
        provider=provider,
        model_id=model_id,
        attempts=attempts,
    )


async def explain(
    provider: SemanticProvider,
    facts: ExplanationFacts,
    *,
    case_id: str | None = None,
    correlation_id: str | None = None,
    settings: Settings | None = None,
) -> Explanation:
    """The passage a user is shown: PromisePatch's own, unless this deployment selected a model.

    The one production route to an explanation, and the only place the selection is read. It
    exists because "which passage ships" is a decision somebody made on evidence, and a decision
    made on evidence should be a line of configuration rather than a property of whichever call
    site happened to be written first.

    With verbalisation unselected no provider is reached, no token is spent and no answer has to
    be refused, because there is no answer: the deterministic rendering of the same facts is
    returned directly, recorded as :attr:`ExplanationFailure.NOT_ATTEMPTED`. That is not a
    fallback and nothing failed. An operator reading a ledger of these rows can tell a
    deployment that never asked from one that asked and did not like the answer.
    """
    if not (settings or get_settings()).explanation_verbalisation:
        return _log(
            fallback(
                facts,
                failure=ExplanationFailure.NOT_ATTEMPTED,
                detail="model verbalisation is not the selected explanation path",
            )
        )
    return await prepare(provider, facts, case_id=case_id, correlation_id=correlation_id)


async def prepare(
    provider: SemanticProvider,
    facts: ExplanationFacts,
    *,
    case_id: str | None = None,
    correlation_id: str | None = None,
) -> Explanation:
    """Ask for a passage, and return one for every way a semantic call can fail.

    The evaluated capability rather than the production route. It always asks, because an
    evaluation of a model must not be silenced by the deployment setting that says this product
    does not ship that model's words; production reaches a passage through :func:`explain`.

    Both halves of the boundary's failure vocabulary are handled here -- the provider that
    could not be reached and the answer that will not be shown -- and so is the third way this
    can end, which is that the question could not be built at all. No caller has to know any of
    them exists. That is the contract rather than an implementation detail: a caller obliged to
    handle an exception is a caller that could be made to do something other than continue, and
    the recovery this passage describes has already been authorised.
    """
    try:
        request = facts.request(case_id=case_id, correlation_id=correlation_id)
    except pydantic.ValidationError as unaskable:
        # These facts will not fit in a question. The only values here PromisePatch did not
        # author are display labels that reached it from the order system -- a customer's name,
        # an order's own reference -- and one of them is longer than a fact may carry. Nothing
        # is truncated and nothing is dropped: the deterministic renderer says the same facts
        # in full, which is what a caller was going to be shown anyway. Recorded as
        # NOT_ATTEMPTED because that is what happened -- no request was built, so no model was
        # asked and nothing was learned about one.
        return _log(
            fallback(
                facts,
                failure=ExplanationFailure.NOT_ATTEMPTED,
                detail=(
                    "these facts cannot be put to a model: "
                    f"{unaskable.error_count()} value(s) exceed what one request may carry"
                ),
                provider=provider.name,
            )
        )

    try:
        result = await provider.run(request)
    except SemanticValidationError as rejected:
        return _refused(facts, rejected, provider=provider)
    except SemanticProviderError as unavailable:
        return _log(
            fallback(
                facts,
                failure=ExplanationFailure.PROVIDER_FAILURE,
                detail=str(unavailable),
                provider=provider.name,
            )
        )

    value = result.value
    if not isinstance(value, Verbalisation):  # pragma: no cover - the job fixes the result type
        return _log(
            fallback(
                facts,
                failure=ExplanationFailure.SCHEMA_REJECTED,
                detail="the provider answered a different job",
                provider=provider.name,
            )
        )
    return _log(
        Explanation(
            surface=facts.surface,
            speech=value.speech,
            source=ExplanationSource.VERBALISED,
            fingerprint=facts.fingerprint(),
            fact_refs=value.fact_refs,
            provider=result.telemetry.provider,
            model_id=result.telemetry.model_id,
            attempts=result.telemetry.attempts,
        )
    )


def accept(prepared: Explanation, facts: ExplanationFacts) -> Explanation:
    """The passage, if it is still about this outcome; otherwise the deterministic one.

    Run by whichever transaction is about to show or store the passage, under whatever lock it
    already holds. An amendment, a decision or a re-plan between the call and the commit moves
    the fingerprint, and a passage describing the previous plan is discarded rather than
    presented as describing this one.
    """
    if prepared.fingerprint == facts.fingerprint() and prepared.surface is facts.surface:
        return prepared
    return _log(
        fallback(
            facts,
            failure=ExplanationFailure.STALE_DISCARDED,
            detail="the outcome changed while the passage was being written",
            provider=prepared.provider,
            model_id=prepared.model_id,
        )
    )


def _refused(
    facts: ExplanationFacts, error: SemanticValidationError, *, provider: SemanticProvider
) -> Explanation:
    """A model answered, and the boundary will not show it. Which half failed is worth keeping."""
    grounding = error.category in _GROUNDING_FAILURES
    return _log(
        fallback(
            facts,
            failure=(
                ExplanationFailure.GROUNDING_REJECTED
                if grounding
                else ExplanationFailure.SCHEMA_REJECTED
            ),
            detail=f"{error.category.value}: {error}",
            provider=provider.name,
        )
    )


def _log(explanation: Explanation) -> Explanation:
    """One structured line per passage. The outcome, never the words.

    The passage itself is not logged. It is built from a case's own facts, it names a customer,
    and a log is shipped, sampled and searchable -- so what goes here is which surface, which
    outcome, who phrased it and why, which is what an operator is actually asking.
    """
    logger.info(
        "explanation.prepared",
        surface=explanation.surface.value,
        source=explanation.source.value,
        failure=None if explanation.failure is None else explanation.failure.value,
        facts_hash=explanation.fingerprint,
        provider=explanation.provider,
        model_id=explanation.model_id,
        attempts=explanation.attempts,
        fact_refs=len(explanation.fact_refs),
    )
    return explanation


__all__ = [
    "Explanation",
    "ExplanationFailure",
    "ExplanationSource",
    "accept",
    "explain",
    "fallback",
    "prepare",
]
