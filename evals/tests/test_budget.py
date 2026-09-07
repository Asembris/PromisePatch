"""Money, and the rules that stop an evaluation spending it by accident.

Nothing here calls a provider. Every usage number is a synthetic
:class:`~promisepatch.semantic.provider.SemanticUsage`, because the thing under test is the
accounting and the refusals, and proving a cost collector works by spending money would be a
strange way to make that argument.

The four refusals are the point:

* a dollar budget on a model with no verified price refuses **before** the first call;
* an exhausted call cap refuses **before** the next call;
* an exhausted token cap refuses **before** the next call;
* an unknown price produces an *unavailable* cost, never a free one.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from evals.budget import (
    PRICES,
    BudgetedSemanticProvider,
    BudgetExhaustedError,
    BudgetGuard,
    CostLedgerEntry,
    EvalBudget,
    ModelPrice,
    PricingUnavailableError,
    append_to_ledger,
    estimate_usd,
    price_for,
)

from promisepatch.semantic import (
    ApparentIntent,
    ClassifyReplyIntentRequest,
    ReplyIntentReading,
    SemanticJob,
    SemanticRequest,
    SemanticResult,
    SemanticTelemetry,
    SemanticUsage,
    UntrustedText,
)

NOVA_LIKE = ModelPrice(
    provider="bedrock",
    model_id="example.model-v1:0",
    input_usd_per_million=Decimal("0.06"),
    output_usd_per_million=Decimal("0.24"),
    snapshot_date=date(2026, 1, 1),
    source="fixture price, not a real published figure",
)
"""A price that exists only in this file. The catalog itself is deliberately empty."""


class CountingProvider:
    """A provider that records how often it was actually asked. Reaches nothing."""

    name = "counting"

    def __init__(self, usage: SemanticUsage | None = None, attempts: int = 1) -> None:
        self.calls = 0
        self._usage = usage or SemanticUsage()
        self._attempts = attempts

    async def run(self, request: SemanticRequest) -> SemanticResult:
        self.calls += 1
        return SemanticResult(
            value=ReplyIntentReading(apparent_intent=ApparentIntent.UNCLEAR),
            telemetry=SemanticTelemetry(
                job=SemanticJob.CLASSIFY_REPLY_INTENT,
                provider=self.name,
                model_id="example.model-v1:0",
                attempts=self._attempts,
                usage=self._usage,
            ),
        )


def _request() -> ClassifyReplyIntentRequest:
    return ClassifyReplyIntentRequest(reply=UntrustedText(text="anything at all"))


# ------------------------------------------------------------------------- the catalog


def test_the_catalog_holds_only_the_models_that_have_actually_been_benchmarked() -> None:
    """One entry per model somebody is about to measure, and a run behind each.

    The catalog shipped empty while nothing had been priced, because an unverified number is
    worse than none: it makes an unbudgeted call look budgeted. Populating it is the same rule
    kept, not relaxed -- a price is added when a model is about to be measured against it, and
    a price for a model nobody has run would be a number with nothing behind it.

    Naming the whole key set rather than only the entry that was added is the load-bearing
    half. `Settings.bedrock_model_id` defaults to Haiku 4.5, which is now priced because the
    customer-intent challenger measures it -- and ADR-0004's configured escalation is not, so
    escalating to it under a dollar ceiling still refuses rather than proceeding unmeasured.
    """
    assert set(PRICES) == {
        ("bedrock", "us.amazon.nova-2-lite-v1:0"),
        ("bedrock", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    }
    assert not [key for key in PRICES if "sonnet" in key[1]]
    assert price_for("bedrock", "example.model-v1:0") is None
    assert price_for("bedrock", None) is None


def test_the_challenger_is_priced_from_a_dated_published_snapshot() -> None:
    """The figures the challenger's spend is computed from, and where they came from.

    The *Regional* tier, because a ``us.`` geo inference profile bills at it and the Global
    tier ($1.00 / $5.00) belongs to a profile this repository does not call. Recording the
    dearer of the two is the direction a budget has to err in.
    """
    price = price_for("bedrock", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert price is not None
    assert price.input_usd_per_million == Decimal("1.10")
    assert price.output_usd_per_million == Decimal("5.50")
    assert price.snapshot_date == date(2026, 9, 7)
    assert "AWS Price List" in price.source


def test_the_benchmarked_model_is_priced_from_a_dated_published_snapshot() -> None:
    """The figures the Nova benchmark's spend is computed from, and where they came from."""
    price = price_for("bedrock", "us.amazon.nova-2-lite-v1:0")
    assert price is not None
    assert price.input_usd_per_million == Decimal("0.30")
    assert price.output_usd_per_million == Decimal("2.50")
    assert price.snapshot_date == date(2026, 9, 7)
    assert "Nova 2 Lite" in price.source


def test_an_unknown_price_makes_cost_unavailable_and_never_zero() -> None:
    assert estimate_usd(None, input_tokens=1_000, output_tokens=500) is None


def test_unreported_tokens_make_cost_unavailable_and_never_zero() -> None:
    assert estimate_usd(NOVA_LIKE, input_tokens=None, output_tokens=None) is None
    assert estimate_usd(NOVA_LIKE, input_tokens=1_000, output_tokens=None) is None


def test_a_known_price_computes_from_the_token_counts() -> None:
    cost = estimate_usd(NOVA_LIKE, input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == Decimal("0.30")


def test_a_price_says_when_it_was_true_and_where_it_came_from() -> None:
    payload = NOVA_LIKE.as_payload()
    assert payload["snapshot_date"] == "2026-01-01"
    assert payload["source"]
    assert payload["unit"] == "USD per 1,000,000 tokens"


# ---------------------------------------------------------------------- the accounting


async def test_calls_attempts_and_tokens_aggregate() -> None:
    """A hundred cases is not a hundred attempts, and the ledger has to be able to say so."""
    guard = BudgetGuard(EvalBudget(), price=NOVA_LIKE)
    inner = CountingProvider(SemanticUsage(input_tokens=800, output_tokens=40), attempts=2)
    provider = BudgetedSemanticProvider(inner, guard)

    for _ in range(3):
        await provider.run(_request())

    assert guard.spend.calls == 3
    assert guard.spend.attempts == 6
    assert guard.spend.input_tokens == 2_400
    assert guard.spend.output_tokens == 120
    assert guard.spend.estimated_usd == estimate_usd(
        NOVA_LIKE, input_tokens=2_400, output_tokens=120
    )


async def test_a_provider_that_publishes_nothing_leaves_tokens_absent() -> None:
    """The replay case. Absent, not zero: nothing was measured."""
    guard = BudgetGuard(EvalBudget(), price=NOVA_LIKE)
    provider = BudgetedSemanticProvider(CountingProvider(), guard)
    await provider.run(_request())

    payload = guard.spend.as_payload()
    assert payload["input_tokens"] is None
    assert payload["output_tokens"] is None
    assert payload["estimated_usd"] is None


async def test_a_failed_call_still_counts_as_a_call() -> None:
    """A provider that raised was still reached, and a budget that forgot that is not a budget."""

    class Failing(CountingProvider):
        async def run(self, request: SemanticRequest) -> SemanticResult:
            self.calls += 1
            raise RuntimeError("the provider fell over")

    guard = BudgetGuard(EvalBudget(), price=NOVA_LIKE)
    provider = BudgetedSemanticProvider(Failing(), guard)
    with pytest.raises(RuntimeError):
        await provider.run(_request())
    assert guard.spend.calls == 1
    assert guard.spend.attempts == 1


# -------------------------------------------------------------------------- fail closed


def test_a_dollar_budget_on_an_unpriced_model_refuses_before_any_call() -> None:
    """The mandatory one. No price means no measurable budget means no run."""
    with pytest.raises(PricingUnavailableError, match="no verified price"):
        BudgetGuard(EvalBudget(max_estimated_usd=Decimal("5.00")), price=None, live=True)


def test_a_dollar_budget_with_a_price_starts() -> None:
    guard = BudgetGuard(EvalBudget(max_estimated_usd=Decimal("5.00")), price=NOVA_LIKE, live=True)
    assert guard.live
    assert guard.price is NOVA_LIKE


def test_an_offline_run_is_not_refused_for_want_of_a_price() -> None:
    """Nothing can be spent, so nothing needs pricing to be bounded."""
    guard = BudgetGuard(EvalBudget(max_estimated_usd=Decimal("5.00")), price=None, live=False)
    guard.authorise()
    assert guard.spend.calls == 1


async def test_an_exhausted_call_cap_refuses_before_the_provider_is_reached() -> None:
    guard = BudgetGuard(EvalBudget(max_calls=2), price=NOVA_LIKE)
    inner = CountingProvider()
    provider = BudgetedSemanticProvider(inner, guard)

    await provider.run(_request())
    await provider.run(_request())
    with pytest.raises(BudgetExhaustedError, match="call budget exhausted"):
        await provider.run(_request())

    assert inner.calls == 2, "the third call never reached the provider"


async def test_an_exhausted_input_token_cap_refuses_before_the_provider_is_reached() -> None:
    guard = BudgetGuard(EvalBudget(max_input_tokens=1_000), price=NOVA_LIKE)
    inner = CountingProvider(SemanticUsage(input_tokens=900, output_tokens=10))
    provider = BudgetedSemanticProvider(inner, guard)

    await provider.run(_request())
    await provider.run(_request())
    with pytest.raises(BudgetExhaustedError, match="input-token budget exhausted"):
        await provider.run(_request())

    assert inner.calls == 2


async def test_an_exhausted_output_token_cap_refuses_before_the_provider_is_reached() -> None:
    guard = BudgetGuard(EvalBudget(max_output_tokens=50), price=NOVA_LIKE)
    inner = CountingProvider(SemanticUsage(input_tokens=10, output_tokens=40))
    provider = BudgetedSemanticProvider(inner, guard)

    await provider.run(_request())
    await provider.run(_request())
    with pytest.raises(BudgetExhaustedError, match="output-token budget exhausted"):
        await provider.run(_request())

    assert inner.calls == 2


async def test_an_exhausted_dollar_cap_refuses_before_the_provider_is_reached() -> None:
    guard = BudgetGuard(EvalBudget(max_estimated_usd=Decimal("0.0001")), price=NOVA_LIKE, live=True)
    inner = CountingProvider(SemanticUsage(input_tokens=1_000_000, output_tokens=1_000))
    provider = BudgetedSemanticProvider(inner, guard)

    await provider.run(_request())
    with pytest.raises(BudgetExhaustedError, match="estimated spend budget exhausted"):
        await provider.run(_request())

    assert inner.calls == 1


async def test_an_unpriced_model_cannot_silently_pass_a_dollar_cap() -> None:
    """Without a price the spend stays ``None``, so the cap can never be satisfied by a zero."""
    guard = BudgetGuard(EvalBudget(max_estimated_usd=Decimal("0.01")), price=None, live=False)
    provider = BudgetedSemanticProvider(
        CountingProvider(SemanticUsage(input_tokens=10_000, output_tokens=1_000)), guard
    )
    await provider.run(_request())
    assert guard.spend.estimated_usd is None
    assert guard.spend.as_payload()["estimated_usd"] is None


# ------------------------------------------------------------------------------ ledger


def test_a_ledger_line_carries_identity_and_counts_and_no_credential(tmp_path: Path) -> None:
    entry = CostLedgerEntry(
        run_id="abc123",
        recorded_at="2026-09-07T09:00:00+00:00",
        git_sha="0" * 40,
        dataset_version="1.0.0",
        dataset_hash="deadbeef",
        provider="fake",
        model_id=None,
        mode="replay",
        calls=92,
        attempts=93,
        input_tokens=None,
        output_tokens=None,
        estimated_usd=None,
        pricing_snapshot=None,
    )
    path = tmp_path / "nested" / "cost-ledger.jsonl"
    append_to_ledger(path, entry)
    append_to_ledger(path, entry)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    text = lines[0]
    for forbidden in ("aws_", "secret", "token=", "session"):
        assert forbidden not in text.casefold()
    assert '"calls":92' in text.replace(" ", "")
    assert '"estimated_usd":null' in text.replace(" ", "")


def test_the_budget_reports_itself_without_inventing_a_default() -> None:
    payload = EvalBudget().as_payload()
    assert payload == {
        "max_calls": None,
        "max_input_tokens": None,
        "max_output_tokens": None,
        "max_estimated_usd": None,
    }
