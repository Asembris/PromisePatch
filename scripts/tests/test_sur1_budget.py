"""Every ceiling refuses the next call, and exhaustion is a nonpass that stays a nonpass.

The contract's budget block says two things this file exists to hold: crossing any ceiling ends
the attempt with ``BUDGET_EXHAUSTED``, and ``BUDGET_EXHAUSTED`` is explicitly not ``VOID`` and is
not retried. The second sentence is the load-bearing one. ``VOID`` is excluded from the
denominator and capped at two; if a crossed ceiling could become one, an arm that ran out of
budget on three scenarios would publish a comparison over six.

No model is called. The clock is a value a test advances by hand, which is the only reason a
300-second ceiling can be exercised without waiting 300 seconds.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from scripts.sur1.budget import AttemptBudget, BudgetExhaustedError
from scripts.sur1.doubles import FakeClock
from scripts.sur1.frozen import Contract

CEILINGS = Contract.load().ceilings


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def budget(clock: FakeClock) -> AttemptBudget:
    return AttemptBudget(ceilings=CEILINGS, clock=clock)


# ------------------------------------------------------------------------ the frozen ceilings


def test_the_ledger_spends_the_contract_s_ceilings_and_not_its_own() -> None:
    assert CEILINGS.wall_clock_seconds == 300
    assert CEILINGS.model_calls == 24
    assert CEILINGS.tool_calls == 60
    assert CEILINGS.input_tokens == 120_000
    assert CEILINGS.output_tokens == 16_000


def test_the_model_call_ceiling_refuses_the_call_that_would_cross_it(
    budget: AttemptBudget,
) -> None:
    for _ in range(CEILINGS.model_calls):
        budget.authorise_model_call()
    assert budget.spend.model_calls == CEILINGS.model_calls
    with pytest.raises(BudgetExhaustedError) as exhausted:
        budget.authorise_model_call()
    assert exhausted.value.dimension == "model_calls"
    assert budget.spend.model_calls == CEILINGS.model_calls


def test_the_tool_call_ceiling_refuses_the_call_that_would_cross_it(
    budget: AttemptBudget,
) -> None:
    for _ in range(CEILINGS.tool_calls):
        budget.authorise_tool_call()
    with pytest.raises(BudgetExhaustedError) as exhausted:
        budget.authorise_tool_call()
    assert exhausted.value.dimension == "tool_calls"


def test_the_wall_clock_ceiling_ends_the_attempt(budget: AttemptBudget, clock: FakeClock) -> None:
    clock.advance(CEILINGS.wall_clock_seconds - 1)
    budget.authorise_model_call()
    clock.advance(1)
    with pytest.raises(BudgetExhaustedError) as exhausted:
        budget.authorise_model_call()
    assert exhausted.value.dimension == "wall_clock_seconds"


def test_a_token_ceiling_is_charged_after_the_answer_and_refuses_the_next_call(
    budget: AttemptBudget,
) -> None:
    """A provider reports usage when it replies, so the refusal can only land on the next call."""
    budget.authorise_model_call()
    budget.record_tokens(input_tokens=CEILINGS.input_tokens + 5_000, output_tokens=10)
    assert budget.spend.input_tokens == CEILINGS.input_tokens + 5_000
    with pytest.raises(BudgetExhaustedError) as exhausted:
        budget.authorise_model_call()
    assert exhausted.value.dimension == "input_tokens"


def test_an_answer_already_paid_for_is_recorded_rather_than_dropped(
    budget: AttemptBudget,
) -> None:
    """Dropping it would hide spend that happened, which is the one thing a ledger must not do."""
    budget.authorise_model_call()
    budget.record_tokens(input_tokens=200_000, output_tokens=40_000)
    assert budget.spend.input_tokens == 200_000
    assert budget.spend.output_tokens == 40_000


def test_the_output_token_ceiling_also_refuses(budget: AttemptBudget) -> None:
    budget.authorise_model_call()
    budget.record_tokens(input_tokens=0, output_tokens=CEILINGS.output_tokens)
    with pytest.raises(BudgetExhaustedError) as exhausted:
        budget.authorise_model_call()
    assert exhausted.value.dimension == "output_tokens"


def test_a_checkpoint_is_a_bare_time_check(budget: AttemptBudget, clock: FakeClock) -> None:
    budget.checkpoint()
    clock.advance(CEILINGS.wall_clock_seconds)
    with pytest.raises(BudgetExhaustedError):
        budget.checkpoint()


# ------------------------------------------------------------------------------- the dollars


def test_unknown_cost_stays_unavailable_and_never_becomes_zero(budget: AttemptBudget) -> None:
    budget.record_dollars(None)
    assert budget.spend.estimated_usd is None
    assert budget.spend.as_payload()["estimated_usd"] == "unavailable"


def test_a_known_cost_accumulates(budget: AttemptBudget) -> None:
    budget.record_dollars(Decimal("0.0004"))
    budget.record_dollars(Decimal("0.0006"))
    assert budget.spend.estimated_usd == Decimal("0.0010")


# --------------------------------------------------------------------- one ledger, not three


def test_each_attempt_gets_its_own_ceiling_and_nothing_is_carried_over(
    clock: FakeClock,
) -> None:
    first = AttemptBudget(ceilings=CEILINGS, clock=clock)
    for _ in range(CEILINGS.model_calls):
        first.authorise_model_call()
    second = AttemptBudget(ceilings=CEILINGS, clock=clock)
    second.authorise_model_call()
    assert second.spend.model_calls == 1


def test_a_ledger_cannot_be_topped_up_by_spending_against_a_copy(budget: AttemptBudget) -> None:
    """``spend`` is replaced in place, so a caller holding the old value cannot keep spending."""
    budget.authorise_model_call()
    stale = budget.spend
    budget.authorise_model_call()
    assert stale.model_calls == 1
    assert budget.spend.model_calls == 2
