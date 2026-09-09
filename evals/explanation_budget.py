"""What a live explanation run may spend, derived from the fixtures rather than guessed.

Two providers, two accountings, and they are never one counter. Nova is metered and priced;
NVIDIA's hosted endpoint is not billed per token at all, so its usage is bounded by calls and
tokens and its dollar figure stays *not modelled* rather than becoming a fabricated zero. A
report that added them together would be claiming a total nobody can check.

**The ceilings are computed, not typed in.** Every development case's production request is
serialised and measured here, with no inference and no provider in the room: the prompt a model
would be sent is the same string :mod:`promisepatch.semantic.prompts` builds, so the bound is a
measurement of this dataset rather than a number somebody copied from another run. Output is
bounded by the job's own ``max_tokens``, which is the ceiling the boundary already enforces.

**The bound is deliberately loose and still small.** Characters are converted to tokens at a
rate chosen to over-count, every case is assumed to take both attempts the boundary allows, and
the dollar ceiling is rounded up with headroom on top. The point is not a precise forecast. The
point is that a runaway is refused before the provider call that would cause it, and that the
number a person is asked to authorise is one this repository derived in front of them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from evals.budget import (
    NEMOTRON_3_SUPER,
    NOVA_2_LITE,
    Billing,
    BillingMode,
    EvalBudget,
    ModelPrice,
    estimate_usd,
)
from evals.explanation_cases import ExplanationEvalCase, to_model_input
from evals.explanation_judge import (
    JUDGE_MODEL_ID,
    JUDGE_PROVIDER,
    RUBRIC,
    build_judge_request,
)
from promisepatch.semantic import SemanticJob
from promisepatch.semantic.jobs import JOB_SPECS
from promisepatch.semantic.prompts import build_system_instruction, build_user_content

CHARACTERS_PER_TOKEN = Decimal(3)
"""How many characters one token is assumed to cover when bounding a prompt.

Three, where English prose through a modern tokenizer is nearer four. Deliberately pessimistic:
a ceiling derived from an optimistic ratio is a ceiling that does not hold, and the cost of
being wrong in this direction is a slightly larger number on an authorisation prompt.
"""

PROTOCOL_TOKEN_OVERHEAD = 400
"""Per attempt, for what surrounds the text: the tool schema, role framing and message envelope.

A flat allowance rather than a modelled one. The schema is small and fixed, and a bound that
tried to be exact about somebody else's wire format would be precise about the wrong thing.
"""

HEADROOM = Decimal("1.25")
"""The margin the derived ceilings carry over the measured worst case.

Sized for the failure it prevents rather than for accuracy: a ceiling that binds at exactly the
expected usage stops a legitimate run on its last case, and a ceiling with a quarter to spare
still refuses anything that has begun to run away.
"""

CORRECTIVE_ATTEMPTS_PER_CALL = 2
"""One question plus the single corrective retry the boundary permits. Never more."""


@dataclass(frozen=True, slots=True)
class DerivedCeiling:
    """One provider's bounds for one split, and the measurement each came from."""

    provider: str
    model_id: str
    logical_calls: int
    provider_attempts: int
    max_input_tokens: int
    max_output_tokens: int
    measured_prompt_characters: int
    """The serialised prompt text this ceiling was computed from. Reproducible without a model."""

    billing: Billing
    projected_usd: Decimal | None = None
    max_estimated_usd: Decimal | None = None

    @property
    def priced(self) -> bool:
        return self.billing.is_metered

    def budget(self) -> EvalBudget:
        """The ceiling in the shape :class:`~evals.budget.BudgetGuard` enforces."""
        return EvalBudget(
            max_calls=self.logical_calls,
            max_input_tokens=self.max_input_tokens,
            max_output_tokens=self.max_output_tokens,
            max_estimated_usd=self.max_estimated_usd,
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "logical_calls": self.logical_calls,
            "provider_attempts": self.provider_attempts,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "measured_prompt_characters": self.measured_prompt_characters,
            "billing_mode": self.billing.mode.value,
            "projected_usd": None if self.projected_usd is None else str(self.projected_usd),
            "max_estimated_usd": (
                None if self.max_estimated_usd is None else str(self.max_estimated_usd)
            ),
        }


def _tokens(characters: int) -> int:
    return int((Decimal(characters) / CHARACTERS_PER_TOKEN).to_integral_value(ROUND_CEILING))


def _cents(value: Decimal) -> Decimal:
    return (value * HEADROOM).quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def generation_prompt_characters(cases: Sequence[ExplanationEvalCase]) -> int:
    """Every character Nova would be sent for these cases, measured from production's builders.

    The same ``build_system_instruction`` and ``build_user_content`` the provider calls, over the
    same ``VerbaliseRequest`` the projection builds. Nothing is estimated about the content: the
    only estimate anywhere in this module is how many characters make a token.
    """
    system = build_system_instruction(SemanticJob.VERBALISE)
    return sum(
        len(system) + len(build_user_content(to_model_input(case).request)) for case in cases
    )


def judge_prompt_characters(cases: Sequence[ExplanationEvalCase]) -> int:
    """Every character the judge would be sent, assuming the longest passage each case allows.

    A passage nobody has generated yet is bounded by the cap production refuses above: the word
    limit, at a generous characters-per-word. That keeps the judge ceiling derivable now, before
    any explanation exists, which is the whole reason this gate can be authorised in advance.
    """
    total = 0
    for case in cases:
        longest = "w" * (case.word_limit * _CHARACTERS_PER_WORD)
        request = build_judge_request(case.id, case.family, to_model_input(case).request, longest)
        total += len(RUBRIC) + len(request.content())
    return total


_CHARACTERS_PER_WORD = 12
"""A generous word length for bounding a passage nobody has written yet. Pessimistic on purpose."""

JUDGE_MAX_OUTPUT_TOKENS = 512
"""What one verdict may cost to write: ten small fields and a rationale capped at 400 characters.

Bounded here rather than left to the provider, because an unbounded completion on a free
endpoint is still quota somebody else cannot use.
"""


def nova_ceiling(cases: Sequence[ExplanationEvalCase]) -> DerivedCeiling:
    """Nova's bounds for one split, and the projected spend that follows from them."""
    characters = generation_prompt_characters(cases)
    calls = len(cases)
    attempts = calls * CORRECTIVE_ATTEMPTS_PER_CALL
    input_tokens = (
        _tokens(characters) + PROTOCOL_TOKEN_OVERHEAD * calls
    ) * CORRECTIVE_ATTEMPTS_PER_CALL
    output_tokens = JOB_SPECS[SemanticJob.VERBALISE].max_tokens * attempts
    projected = estimate_usd(NOVA_2_LITE, input_tokens=input_tokens, output_tokens=output_tokens)
    return DerivedCeiling(
        provider=NOVA_2_LITE.provider,
        model_id=NOVA_2_LITE.model_id,
        logical_calls=calls,
        provider_attempts=attempts,
        max_input_tokens=int(Decimal(input_tokens) * HEADROOM),
        max_output_tokens=int(Decimal(output_tokens) * HEADROOM),
        measured_prompt_characters=characters,
        billing=_metered(NOVA_2_LITE),
        projected_usd=projected,
        max_estimated_usd=None if projected is None else _cents(projected),
    )


def judge_ceiling(cases: Sequence[ExplanationEvalCase]) -> DerivedCeiling:
    """The judge's bounds for one split. No dollar ceiling, because there is no published price.

    ``max_estimated_usd`` stays ``None`` and ``projected_usd`` stays ``None``. That is not a free
    run; it is a run whose commercial cost nobody has published, and writing ``$0.00`` here would
    both assert a rate that does not exist and switch off the dollar guard for a model that has
    one. What bounds this provider is calls and tokens, which is the resource actually at risk.
    """
    characters = judge_prompt_characters(cases)
    calls = len(cases)
    attempts = calls * CORRECTIVE_ATTEMPTS_PER_CALL
    input_tokens = (
        _tokens(characters) + PROTOCOL_TOKEN_OVERHEAD * calls
    ) * CORRECTIVE_ATTEMPTS_PER_CALL
    return DerivedCeiling(
        provider=JUDGE_PROVIDER,
        model_id=JUDGE_MODEL_ID,
        logical_calls=calls,
        provider_attempts=attempts,
        max_input_tokens=int(Decimal(input_tokens) * HEADROOM),
        max_output_tokens=JUDGE_MAX_OUTPUT_TOKENS * attempts,
        measured_prompt_characters=characters,
        billing=NEMOTRON_3_SUPER,
    )


def _metered(price: ModelPrice) -> Billing:
    return Billing(
        provider=price.provider,
        model_id=price.model_id,
        mode=BillingMode.METERED,
        source=price.source,
        price=price,
    )


@dataclass(frozen=True, slots=True)
class RunCost:
    """What one run actually used, per provider, never summed across billing modes.

    ``known_usd`` is the total that can be stated: the metered providers only. The unpriced one
    is reported beside it with its usage intact and its dollars absent, which is the honest shape
    of "we know what it did and nobody published what it costs".
    """

    generation_input_tokens: int | None
    generation_output_tokens: int | None
    generation_usd: Decimal | None
    judge_input_tokens: int | None
    judge_output_tokens: int | None
    judge_billing_mode: str

    @property
    def known_usd(self) -> Decimal | None:
        """Every dollar this run can account for. The judge contributes nothing, not zero."""
        return self.generation_usd

    def as_payload(self) -> dict[str, object]:
        return {
            "generation_input_tokens": self.generation_input_tokens,
            "generation_output_tokens": self.generation_output_tokens,
            "generation_estimated_usd": (
                None if self.generation_usd is None else str(self.generation_usd)
            ),
            "judge_input_tokens": self.judge_input_tokens,
            "judge_output_tokens": self.judge_output_tokens,
            "judge_billing_mode": self.judge_billing_mode,
            "judge_known_usd": None,
            "total_known_usd": None if self.known_usd is None else str(self.known_usd),
        }


def run_cost(
    *,
    generation_input_tokens: int | None,
    generation_output_tokens: int | None,
    judge_input_tokens: int | None,
    judge_output_tokens: int | None,
    price: ModelPrice | None = NOVA_2_LITE,
) -> RunCost:
    """Price one run's generation and leave its judging unpriced. Two accountings, never one."""
    return RunCost(
        generation_input_tokens=generation_input_tokens,
        generation_output_tokens=generation_output_tokens,
        generation_usd=estimate_usd(
            price,
            input_tokens=generation_input_tokens,
            output_tokens=generation_output_tokens,
        ),
        judge_input_tokens=judge_input_tokens,
        judge_output_tokens=judge_output_tokens,
        judge_billing_mode=NEMOTRON_3_SUPER.mode.value,
    )


__all__ = [
    "CHARACTERS_PER_TOKEN",
    "CORRECTIVE_ATTEMPTS_PER_CALL",
    "HEADROOM",
    "JUDGE_MAX_OUTPUT_TOKENS",
    "PROTOCOL_TOKEN_OVERHEAD",
    "DerivedCeiling",
    "RunCost",
    "generation_prompt_characters",
    "judge_ceiling",
    "judge_prompt_characters",
    "nova_ceiling",
    "run_cost",
]
