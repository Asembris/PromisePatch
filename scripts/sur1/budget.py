"""Every ceiling, enforced in one place, before the thing that would cross it happens.

The contract gives three arms identical ceilings -- 300 s, 24 model calls, 60 tool calls,
120 000 input and 16 000 output tokens per scenario -- and says that crossing any of them ends
that attempt with ``BUDGET_EXHAUSTED``, which is a nonpass, is not ``VOID`` and is not retried.

**One ledger, not three.** If each arm enforced its own ceiling, the comparison would rest on
three implementations agreeing, and the first one to drift would be the one that spent more.
So an arm is handed a :class:`AttemptBudget` and cannot reach a model or a receiver without
asking it first. The arm decides what to do; it does not decide what it may afford.

**A cap refuses the next call.** :meth:`AttemptBudget.authorise_model_call` is asked *before*
a provider is invoked and raises rather than reporting afterwards, exactly as ``evals.budget``
does and for the same reason: a warning-only guard has already spent the money by the time
anybody reads it.

**Tokens are charged after the answer and checked before the next one.** A provider reports
usage when it replies, so the only honest enforcement is to refuse the *next* call once the
total is at or past the ceiling. An answer already paid for is recorded rather than discarded --
dropping it would hide spend that happened.

**Unknown cost is unavailable and never zero.** The contract's dollar ceiling defers to
``evals.budget``'s rule and this module does not re-implement pricing: it carries
``estimated_usd`` as an optional value and leaves it ``None`` when nothing verified it.

**Exhaustion is a terminal status, not an exception that escapes.** The driver catches
:class:`BudgetExhaustedError` and records ``BUDGET_EXHAUSTED``. It never becomes ``VOID``, because
turning a bad attempt into a void one is exactly how a comparative result gets laundered.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from decimal import Decimal

from scripts.sur1.frozen import Ceilings
from scripts.sur1.manifest import Spend


class BudgetExhaustedError(RuntimeError):
    """A ceiling would have been crossed. The attempt ends; the call does not happen."""

    def __init__(self, dimension: str, ceiling: int, would_be: int) -> None:
        super().__init__(
            f"{dimension} ceiling {ceiling} would be crossed at {would_be}; "
            f"the attempt ends BUDGET_EXHAUSTED and is not retried"
        )
        self.dimension = dimension
        self.ceiling = ceiling
        self.would_be = would_be


@dataclass(slots=True)
class AttemptBudget:
    """One scenario's worth of ceiling for one arm, spent down and never topped up.

    Deliberately mutable: it is a ledger, and a ledger that returned a new object per charge
    would let a caller keep spending against a copy that had forgotten the last call.
    """

    ceilings: Ceilings
    clock: Callable[[], float]
    """A monotonic clock, injected. Passing one is what lets wall-clock exhaustion be tested
    without waiting five minutes for it, and what keeps this module free of a hidden clock."""

    started_at: float = 0.0
    spend: Spend = field(default_factory=Spend)

    def __post_init__(self) -> None:
        self.started_at = self.clock()

    # ------------------------------------------------------------------ the ceilings

    @property
    def elapsed_seconds(self) -> float:
        return self.clock() - self.started_at

    def _refuse_if_out_of_time(self) -> None:
        elapsed = self.elapsed_seconds
        if elapsed >= self.ceilings.wall_clock_seconds:
            raise BudgetExhaustedError(
                "wall_clock_seconds", self.ceilings.wall_clock_seconds, int(elapsed)
            )

    def authorise_model_call(self) -> None:
        """Asked before a provider is invoked. Raises rather than reporting afterwards."""
        self._refuse_if_out_of_time()
        if self.spend.model_calls + 1 > self.ceilings.model_calls:
            raise BudgetExhaustedError(
                "model_calls", self.ceilings.model_calls, self.spend.model_calls + 1
            )
        if self.spend.input_tokens >= self.ceilings.input_tokens:
            raise BudgetExhaustedError(
                "input_tokens", self.ceilings.input_tokens, self.spend.input_tokens
            )
        if self.spend.output_tokens >= self.ceilings.output_tokens:
            raise BudgetExhaustedError(
                "output_tokens", self.ceilings.output_tokens, self.spend.output_tokens
            )
        self.spend = replace(self.spend, model_calls=self.spend.model_calls + 1)

    def authorise_tool_call(self) -> None:
        """Asked before a receiver is reached. A read costs the same as a write here."""
        self._refuse_if_out_of_time()
        if self.spend.tool_calls + 1 > self.ceilings.tool_calls:
            raise BudgetExhaustedError(
                "tool_calls", self.ceilings.tool_calls, self.spend.tool_calls + 1
            )
        self.spend = replace(self.spend, tool_calls=self.spend.tool_calls + 1)

    def record_tokens(self, *, input_tokens: int, output_tokens: int) -> None:
        """Charge what a provider reported. Recorded even when it takes the total past a
        ceiling: the answer was paid for, and dropping it would hide spend that happened.
        The refusal lands on the next call, which is the only place it can honestly land.
        """
        self.spend = replace(
            self.spend,
            input_tokens=self.spend.input_tokens + max(0, input_tokens),
            output_tokens=self.spend.output_tokens + max(0, output_tokens),
        )

    def record_dollars(self, estimated_usd: Decimal | None) -> None:
        """Add to the estimate, or leave it unavailable. ``None`` never becomes zero."""
        if estimated_usd is None:
            return
        current = self.spend.estimated_usd or Decimal(0)
        self.spend = replace(self.spend, estimated_usd=current + estimated_usd)

    def checkpoint(self) -> None:
        """A bare time check, for an arm doing long deterministic work between calls."""
        self._refuse_if_out_of_time()

    @property
    def exhausted(self) -> bool:
        """Whether any ceiling has been reached. A question, not an enforcement point."""
        return (
            self.elapsed_seconds >= self.ceilings.wall_clock_seconds
            or self.spend.model_calls >= self.ceilings.model_calls
            or self.spend.tool_calls >= self.ceilings.tool_calls
            or self.spend.input_tokens >= self.ceilings.input_tokens
            or self.spend.output_tokens >= self.ceilings.output_tokens
        )
