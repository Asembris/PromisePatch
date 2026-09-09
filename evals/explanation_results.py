"""What a generation and a judgement each leave behind, kept apart because they are two facts.

Nova produced a passage. Nemotron formed an opinion about it. Those are separate events, bought
separately, and the schema says so:

* :class:`NovaExplanationResult` is what the system under test did. It binds to the production
  request that produced it -- the facts, the prompt, the schema, the word cap -- so a stored
  answer can never be reused under a request that has since changed.
* :class:`ExplanationJudgeResult` is one verdict about one of those, binding to *both* the judge's
  own identity and the generation it judged.

That separation buys two things the gate requires. Rejudging costs zero Nova calls, because a
judge result names the generation it is about instead of containing it. And a judge outage is
recorded as a judge outage: the passage stays, and the subjective half of the case is simply not
scored. Collapsing them into one record would make "Nemotron was down" indistinguishable from
"Nova failed", which is the exact confusion a paired report got wrong once already.

**Nothing is invented.** A provider that reports no tokens leaves them ``None``. A zero would be
a measurement, and there was no measurement.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from pydantic import Field

from evals.cases import EvalSplit, Frozen
from evals.explanation_cases import ExplanationFamily

FINGERPRINT_LENGTH = 16
"""How much of a SHA-256 identity digest is kept. Enough to distinguish, short enough to read."""

NOT_PREPARED_DETAIL_PREFIX: Final = "the AWS SDK could not be prepared for Bedrock:"
"""Production's own sentence for a Bedrock client that could not be built.

Compatibility, for records written before :data:`ExplanationFailureKind.PROVIDER_NOT_PREPARED`
existed. One such record exists -- ``p48dev-repaired``'s canary, which reached no provider
because the AWS login credential provider needed a dependency that was not installed -- and it
is stored as a plain ``PROVIDER_FAILURE`` because that was the only kind there was. The file is
append-only evidence and is not rewritten, so the sentence is what identifies it.

The literal lives here rather than being imported because the import contract keeps ``evals``
out of ``promisepatch.integrations``. ``tests/test_bedrock.py`` asserts the producer still emits
it, so a reworded message is a failing test rather than a record this stops recognising.
"""


class ExplanationSource(StrEnum):
    """Who phrased the passage. Mirrors production's own provenance vocabulary, never widens it.

    Restated rather than imported because a stored result must read back the same years after the
    enum moved, and because the harness must be able to record a source for a run in which the
    production module was a different revision. Dataset validation asserts the two agree.
    """

    VERBALISED = "VERBALISED"
    FALLBACK = "FALLBACK"


class ExplanationFailureKind(StrEnum):
    """Every way a case can end badly, in the buckets a manual diagnosis actually uses.

    The first five are production's own :class:`~promisepatch.domain.verbalisation.
    ExplanationFailure` and :class:`~promisepatch.semantic.errors.ValidationFailure` categories
    seen from the harness side -- deliberately the same concepts under the same names, because a
    second vocabulary for "the answer named a fact nobody sent" would make the report and the
    application disagree about what happened.

    The rest are content-level findings no validator produces. They exist because P4.7 does not
    claim arbitrary prose is checkable, and a failure taxonomy that stopped at what a validator
    can see would have nowhere to put the passage that was well-formed and wrong.
    """

    PROVIDER_NOT_PREPARED = "PROVIDER_NOT_PREPARED"
    """The provider could not be built, so this case was never asked. **Not terminal.**

    The one kind here that is not an observation about the model. Every other kind is something
    that happened to a request: this one is a request that never left the process, because a
    profile, a Region or a credential dependency was missing. No token was billed and no
    passage was refused -- there was nothing to refuse.

    Kept in this enum rather than thrown away because the attempt is evidence and the run file
    is append-only: an operator reading a run has to be able to see that a case was reached,
    found the environment broken, and was left outstanding. :meth:`NovaExplanationResult
    .terminal` is what stops it being mistaken for an answer.
    """

    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    SCHEMA_REJECTION = "SCHEMA_REJECTION"
    UNKNOWN_FACT_REF = "UNKNOWN_FACT_REF"
    MISSING_REQUIRED_FACT = "MISSING_REQUIRED_FACT"
    WORD_CAP = "WORD_CAP"
    UNSUPPORTED_DIGIT = "UNSUPPORTED_DIGIT"

    OUTCOME_CONTRADICTION = "OUTCOME_CONTRADICTION"
    AUTHORITY_CONTRADICTION = "AUTHORITY_CONTRADICTION"
    UNSUPPORTED_ENTITY_OR_OPTION = "UNSUPPORTED_ENTITY_OR_OPTION"
    UNSUPPORTED_GUARANTEE = "UNSUPPORTED_GUARANTEE"
    UNSUPPORTED_QUANTITY_IN_WORDS = "UNSUPPORTED_QUANTITY_IN_WORDS"
    INCOMPLETE_CAUSE = "INCOMPLETE_CAUSE"
    UNCLEAR_PROSE = "UNCLEAR_PROSE"
    WORDY = "WORDY"
    UNNATURAL_SPEECH = "UNNATURAL_SPEECH"


class ManualDisposition(StrEnum):
    """What a human concluded after reading one case. Optional everywhere, required by nobody.

    Present because the dataset is small enough to read end to end and the protocol says every
    development passage is read. Absent in CI, because requiring a human annotation to run an
    offline test would make the annotation a formality.
    """

    CONFIRMED = "CONFIRMED"
    """The reviewer agrees with the judge and the validators."""

    JUDGE_OVERRULED = "JUDGE_OVERRULED"
    """The judge was wrong about this passage, and the reviewer says which way."""

    FIXTURE_DEFECT = "FIXTURE_DEFECT"
    """The case is wrong, not the model. Fix the fixture and say so; never weaken a gate."""

    NEEDS_REVIEW = "NEEDS_REVIEW"
    """Read and not yet decided. Distinct from unread, which is the absence of a disposition."""


class Usage(Frozen):
    """What one logical call spent, as the provider reported it. Absent stays absent."""

    logical_calls: int = Field(default=0, ge=0)
    """Questions asked. One per case for generation, one per accepted passage for judging."""

    provider_attempts: int = Field(default=0, ge=0)
    """Round trips, including the single bounded corrective retry. Never the same number."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None

    def plus(self, other: Usage) -> Usage:
        """Two usages added, keeping ``None`` where neither side reported anything."""
        return Usage(
            logical_calls=self.logical_calls + other.logical_calls,
            provider_attempts=self.provider_attempts + other.provider_attempts,
            input_tokens=_add(self.input_tokens, other.input_tokens),
            output_tokens=_add(self.output_tokens, other.output_tokens),
            latency_ms=_add(self.latency_ms, other.latency_ms),
        )


NO_USAGE: Final[Usage] = Usage()
"""Nothing spent. A shared immutable value, so a default can never be a fresh allocation."""


def _add(left: int | None, right: int | None) -> int | None:
    if left is None and right is None:
        return None
    return (left or 0) + (right or 0)


def _digest(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


class GenerationIdentity(Frozen):
    """Which model was asked which question about which case, in which repository state.

    Every field is part of what would make a stored answer no longer an answer to the question
    being asked. Change the facts, the prompt, the schema or the cap and the fingerprint moves,
    and a resumed or replayed run cannot present the old passage as this run's output.
    """

    provider: str
    model_id: str | None
    git_sha: str | None
    dataset_name: str
    dataset_version: str
    dataset_hash: str
    case_id: str
    family: ExplanationFamily
    facts_fingerprint: str
    """Production's own :meth:`ExplanationFacts.fingerprint`, not a second hash of the same
    thing. The value the acceptance path compares a late answer against."""

    prompt_system_hash: str
    schema_hash: str
    word_limit: int
    run_id: str

    def fingerprint(self) -> str:
        """A stable name for "this model, this question, this case, this commit".

        Excludes ``run_id`` deliberately: two runs of the identical question are the same
        question, and a rejudge has to be able to say which generation it judged without the
        run that produced it being part of the answer.
        """
        payload = dict(self.model_dump(mode="json"))
        payload.pop("run_id", None)
        return _digest(payload)


class NovaExplanationResult(Frozen):
    """One case's passage, where it came from, and what it cost. The system under test's output.

    ``source`` is the whole difference between a model-quality measurement and an availability
    one. A ``FALLBACK`` row means PromisePatch said its own sentence -- the system explained the
    outcome successfully and the model did not write the words -- so it counts towards the
    fallback rate and towards nothing else. Quality is only ever computed over ``VERBALISED``.
    """

    identity: GenerationIdentity
    split: EvalSplit
    source: ExplanationSource
    speech: str
    fact_refs: tuple[str, ...] = ()
    failure: ExplanationFailureKind | None = None
    detail: str | None = None
    usage: Usage = NO_USAGE
    recorded_at: str | None = None

    @property
    def accepted(self) -> bool:
        """Whether a model's words survived the production acceptance path and are on screen."""
        return self.source is ExplanationSource.VERBALISED

    @property
    def terminal(self) -> bool:
        """Whether this record answers the question the case asks. A resume skips only these.

        Every outcome the model can produce is terminal, including a refused answer and a
        provider that failed mid-request: each is something that was observed about a request
        that was actually sent, and asking again would be buying a second opinion the protocol
        did not authorise.

        :data:`ExplanationFailureKind.PROVIDER_NOT_PREPARED` is the exception, because nothing
        was observed. The case is still outstanding, and a resume under the same run identity
        is what finishes it.
        """
        if self.failure is ExplanationFailureKind.PROVIDER_NOT_PREPARED:
            return False
        return not (
            self.failure is ExplanationFailureKind.PROVIDER_FAILURE
            and (self.detail or "").startswith(NOT_PREPARED_DETAIL_PREFIX)
        )

    @property
    def case_id(self) -> str:
        return self.identity.case_id

    @property
    def family(self) -> ExplanationFamily:
        return self.identity.family

    @property
    def word_count(self) -> int:
        return len(self.speech.split())


class JudgeIdentity(Frozen):
    """Which judge, under which rubric, formed which verdict about which generation.

    Separate from :class:`GenerationIdentity` rather than merged with it, because the two answer
    different questions and a single blended identity could not express the one operation this
    gate is built around: judge again without generating again.
    """

    judge_provider: str
    judge_model_id: str | None
    rubric_version: str
    judge_prompt_hash: str
    verdict_schema_hash: str
    generation_fingerprint: str
    """The generation this verdict is about. A verdict whose generation moved is not this
    passage's verdict, and rejudging is exactly the operation that keeps it that way."""

    dataset_name: str
    dataset_version: str
    dataset_hash: str
    run_id: str

    def fingerprint(self) -> str:
        payload = dict(self.model_dump(mode="json"))
        payload.pop("run_id", None)
        return _digest(payload)


class JudgeOutcome(StrEnum):
    """Whether a judgement happened, and if not, whose fault that is. Never a guessed verdict."""

    SCORED = "SCORED"
    JUDGE_PROVIDER_FAILURE = "JUDGE_PROVIDER_FAILURE"
    """Nobody was reached. The passage stands; the subjective half of this case is unscored."""

    JUDGE_RESULT_INVALID = "JUDGE_RESULT_INVALID"
    """The judge answered something the verdict contract refuses. Not repaired, not clamped,
    not partially believed -- an answer that broke the schema is not evidence of a score."""


class ExplanationJudgeResult(Frozen):
    """One verdict about one accepted passage, or the record of why there is none."""

    identity: JudgeIdentity
    case_id: str
    family: ExplanationFamily
    split: EvalSplit
    outcome: JudgeOutcome
    verdict: Mapping[str, object] | None = None
    """The validated :class:`~evals.explanation_judge.JudgeVerdict` as plain JSON, or ``None``.

    Stored as a mapping rather than the model so a result file written today reads back after
    the contract gains a field; the loader revalidates it, and a stored verdict that no longer
    satisfies the contract is reported rather than silently accepted."""

    detail: str | None = None
    usage: Usage = NO_USAGE
    recorded_at: str | None = None

    @property
    def scored(self) -> bool:
        return self.outcome is JudgeOutcome.SCORED and self.verdict is not None


class ManualReview(Frozen):
    """A reviewer's disposition for one case, kept beside the results and never inside them."""

    case_id: str
    disposition: ManualDisposition
    note: str = Field(default="", max_length=800)


__all__ = [
    "FINGERPRINT_LENGTH",
    "NO_USAGE",
    "ExplanationFailureKind",
    "ExplanationJudgeResult",
    "ExplanationSource",
    "GenerationIdentity",
    "JudgeIdentity",
    "JudgeOutcome",
    "ManualDisposition",
    "ManualReview",
    "NovaExplanationResult",
    "Usage",
]
