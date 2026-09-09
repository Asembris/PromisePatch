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

And one distinction, which arrived with an endpoint that has no price at all: *unpriced* and
*not billed per token* are different states, and neither of them is zero. The last section
below is about keeping them apart -- because collapsing them would put a fabricated commercial
rate in the catalog, and would switch off the dollar guard for every model that really has one.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from evals.budget import (
    BILLING,
    PRICES,
    Billing,
    BillingMode,
    BudgetedSemanticProvider,
    BudgetExhaustedError,
    BudgetGuard,
    CostLedgerEntry,
    EvalBudget,
    ModelPrice,
    PricingUnavailableError,
    append_to_ledger,
    billing_for,
    estimate_usd,
    ledger_runs,
    ledger_totals,
    price_for,
    tightest,
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
    half. Haiku 4.5 is priced because the customer-intent challenger measures it -- and
    ADR-0004's configured escalation is not, so escalating to it under a dollar ceiling still
    refuses rather than proceeding unmeasured. `Settings.bedrock_model_id` defaults to Nova 2
    Lite per ADR-0007, which is priced for the same reason: it was benchmarked.

    The OpenAI entry is the replacement challenger and it is exactly one: an SDK that supports
    a hundred models does not put a hundred rows here, and the floating `gpt-4o-mini` alias is
    deliberately absent so that a run naming it fails closed rather than being priced against
    whichever snapshot the alias points at today.
    """
    assert set(PRICES) == {
        ("bedrock", "us.amazon.nova-2-lite-v1:0"),
        ("bedrock", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
        ("openai", "gpt-4o-mini-2024-07-18"),
    }
    assert not [key for key in PRICES if "sonnet" in key[1]]
    assert price_for("bedrock", "example.model-v1:0") is None
    assert price_for("bedrock", None) is None
    assert price_for("openai", "gpt-4o-mini") is None
    # The pair is the key, so neither half identifies a model on its own.
    assert price_for("bedrock", "gpt-4o-mini-2024-07-18") is None
    assert price_for("openai", "us.anthropic.claude-haiku-4-5-20251001-v1:0") is None


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
    """The figures the Nova benchmark's spend is computed from, and where they came from.

    The Regional pair, not the Global one. ``us.amazon.nova-2-lite-v1:0`` is a US geo
    cross-Region inference profile and bills at the source Region's own on-demand rate;
    ``us-east-1`` publishes a second, cheaper pair whose usage type says
    ``-cross-region-global`` and which belongs to ``global.amazon....``. The entry held that
    cheaper pair until 2026-09-08 and now holds the one that applies. Pinned here with the
    SKU in the source string so a future correction has to be a deliberate edit.
    """
    price = price_for("bedrock", "us.amazon.nova-2-lite-v1:0")
    assert price is not None
    assert price.input_usd_per_million == Decimal("0.33")
    assert price.output_usd_per_million == Decimal("2.75")
    assert price.snapshot_date == date(2026, 9, 8)
    assert "FY8T82UUN7VZR55K" in price.source
    assert "DY69Q8C3F88CHA2Q" in price.source


def test_the_replacement_challenger_is_priced_against_its_pinned_snapshot() -> None:
    """The figures the OpenAI challenger's spend is computed from, and what they are pinned to.

    The dated snapshot, never the floating alias. A price recorded against ``gpt-4o-mini``
    would be a price against whichever model that name resolved to on the day, so a budget and
    a quality number computed a week apart could describe two different models.
    """
    price = price_for("openai", "gpt-4o-mini-2024-07-18")
    assert price is not None
    assert price.provider == "openai"
    assert price.model_id == "gpt-4o-mini-2024-07-18"
    assert price.input_usd_per_million == Decimal("0.15")
    assert price.output_usd_per_million == Decimal("0.60")
    assert price.snapshot_date == date(2026, 9, 8)
    assert "gpt-4o-mini-2024-07-18" in price.source


def test_the_openai_token_ceilings_cost_less_than_the_openai_dollar_ceiling() -> None:
    """The arithmetic the OpenAI ceilings were chosen from, in decimals rather than floats.

    100k input at $0.15/M is $0.015 and 10k output at $0.60/M is $0.006, so the token bounds
    permit $0.021 in total and a three-cent dollar cap sits above them. That ordering is the
    intended one: the dollar cap is a backstop for arithmetic nobody re-checked, not the bound
    expected to bite, and Stage A's own cent is stricter than either.
    """
    price = price_for("openai", "gpt-4o-mini-2024-07-18")
    ceiling_cost = estimate_usd(price, input_tokens=100_000, output_tokens=10_000)
    assert ceiling_cost == Decimal("0.021")
    assert ceiling_cost < Decimal("0.03")

    twelve_stage_a_calls = estimate_usd(price, input_tokens=12 * 900, output_tokens=12 * 12)
    assert twelve_stage_a_calls is not None
    assert twelve_stage_a_calls < Decimal("0.01")


# ------------------------------------------------- one ledger, two challengers, no crossover


def _ledger_line(
    *, provider: str, model_id: str | None, calls: int, usd: str | None
) -> CostLedgerEntry:
    return CostLedgerEntry(
        run_id=f"{provider}-{model_id}-{calls}",
        recorded_at="2026-09-08T00:00:00+00:00",
        git_sha="0" * 40,
        dataset_version="1.0.0",
        dataset_hash="hash",
        provider=provider,
        model_id=model_id,
        mode="live",
        calls=calls,
        attempts=calls,
        input_tokens=None,
        output_tokens=None,
        estimated_usd=usd,
        pricing_snapshot="2026-09-08",
    )


def test_one_challengers_history_does_not_debit_another_challengers_allowance(
    tmp_path: Path,
) -> None:
    """The ledger is one file and the ceilings are not one ceiling.

    Two challengers share a cost ledger, and each has its own allowance because their prices
    are an order of magnitude apart. A total that ignored the provider would let a Bedrock
    run's dollars eat an OpenAI run's cent, and a spend nobody made would refuse a call nobody
    had budgeted against.
    """
    path = tmp_path / "cost-ledger.jsonl"
    append_to_ledger(
        path, _ledger_line(provider="bedrock", model_id="haiku", calls=9, usd="0.0900")
    )
    append_to_ledger(
        path,
        _ledger_line(provider="openai", model_id="gpt-4o-mini-2024-07-18", calls=4, usd="0.0010"),
    )

    openai_spend = ledger_totals(
        path, mode="live", provider="openai", model_id="gpt-4o-mini-2024-07-18"
    )
    assert openai_spend.runs == 1
    assert openai_spend.calls == 4
    assert openai_spend.estimated_usd == Decimal("0.0010")

    bedrock_spend = ledger_totals(path, mode="live", provider="bedrock", model_id="haiku")
    assert bedrock_spend.calls == 9
    assert bedrock_spend.estimated_usd == Decimal("0.0900")


def test_the_same_model_name_under_two_providers_is_two_models(tmp_path: Path) -> None:
    """Half an identity identifies nothing.

    Both halves are matched, or the line does not belong to this run.
    """
    path = tmp_path / "cost-ledger.jsonl"
    append_to_ledger(
        path, _ledger_line(provider="bedrock", model_id="shared-name", calls=7, usd="0.0700")
    )

    assert ledger_totals(path, mode="live", provider="openai", model_id="shared-name").calls == 0
    assert ledger_totals(path, mode="live", provider="bedrock", model_id="shared-name").calls == 7


def test_an_alias_and_its_snapshot_do_not_share_a_ledger_total(tmp_path: Path) -> None:
    """A floating name and the snapshot it points at are two models, and bill as two."""
    path = tmp_path / "cost-ledger.jsonl"
    append_to_ledger(
        path,
        _ledger_line(provider="openai", model_id="gpt-4o-mini", calls=5, usd="0.0050"),
    )

    pinned = ledger_totals(path, mode="live", provider="openai", model_id="gpt-4o-mini-2024-07-18")
    assert pinned.calls == 0
    assert pinned.estimated_usd == Decimal(0)


def test_a_run_that_named_no_model_debits_no_models_ceiling(tmp_path: Path) -> None:
    """The lines a wholly failed run leaves behind, and why they are counted separately.

    A run whose every call failed reports no model id, because the id is read from what came
    back. Those attempts are real and they are not attributable: charging them to whichever
    model asks next would let one challenger's outage eat another challenger's allowance. So
    they are reported beside the totals and are in none of them.
    """
    path = tmp_path / "cost-ledger.jsonl"
    append_to_ledger(path, _ledger_line(provider="bedrock", model_id=None, calls=3, usd=None))
    append_to_ledger(
        path,
        _ledger_line(provider="openai", model_id="gpt-4o-mini-2024-07-18", calls=2, usd="0.0004"),
    )

    openai_spend = ledger_totals(
        path, mode="live", provider="openai", model_id="gpt-4o-mini-2024-07-18"
    )
    assert openai_spend.calls == 2
    assert openai_spend.unattributed_calls == 0

    bedrock_spend = ledger_totals(path, mode="live", provider="bedrock", model_id="haiku")
    assert bedrock_spend.calls == 0
    assert bedrock_spend.runs == 0
    assert bedrock_spend.unattributed_runs == 1
    assert bedrock_spend.unattributed_calls == 3
    assert "unattributed_calls" in bedrock_spend.as_payload()


def test_neither_benchmarked_model_is_priced_at_its_global_tier() -> None:
    """Both catalog entries are called through a ``us.`` profile, so both take the dearer pair.

    The two mistakes are the same mistake, and one of them was made: a published price list
    shows two figures for one model in one Region, and the cheaper is the one for a profile
    this repository does not call. A budget that guesses low is a budget that does not hold.
    """
    nova = price_for("bedrock", "us.amazon.nova-2-lite-v1:0")
    haiku = price_for("bedrock", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert nova is not None and haiku is not None
    assert (nova.input_usd_per_million, nova.output_usd_per_million) != (
        Decimal("0.30"),
        Decimal("2.50"),
    )
    assert (haiku.input_usd_per_million, haiku.output_usd_per_million) != (
        Decimal("1.00"),
        Decimal("5.00"),
    )


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


# ------------------------------------------------- two ceilings, and both of them in force


def test_the_tightest_of_two_budgets_takes_the_smaller_of_each_field() -> None:
    """A stage bound composes with the run-wide one rather than replacing it."""
    wide = EvalBudget(
        max_calls=30,
        max_input_tokens=100_000,
        max_output_tokens=10_000,
        max_estimated_usd=Decimal("0.15"),
    )
    narrow = EvalBudget(max_calls=12, max_estimated_usd=Decimal("0.03"))

    combined = tightest(wide, narrow)

    assert combined.max_calls == 12
    assert combined.max_estimated_usd == Decimal("0.03")
    # Silence about a field is not permission: the wider budget's token caps carry through.
    assert combined.max_input_tokens == 100_000
    assert combined.max_output_tokens == 10_000


def test_an_uncapped_field_never_widens_a_capped_one() -> None:
    """``None`` is uncapped and always loses. Composing can only ever narrow."""
    assert tightest(EvalBudget(max_calls=5), EvalBudget()).max_calls == 5
    assert tightest(EvalBudget(), EvalBudget(max_calls=5)).max_calls == 5
    assert tightest(EvalBudget(), EvalBudget()).max_calls is None


def test_composition_is_order_independent_and_binds_at_least_as_hard_as_either_input() -> None:
    """The property that matters, stated as one: the result is never looser than a source."""
    wide = EvalBudget(max_calls=30, max_estimated_usd=Decimal("0.15"))
    narrow = EvalBudget(max_calls=12, max_estimated_usd=Decimal("0.03"))

    assert tightest(wide, narrow) == tightest(narrow, wide)

    combined = tightest(wide, narrow)
    for source in (wide, narrow):
        assert combined.max_calls is not None
        assert source.max_calls is not None
        assert combined.max_calls <= source.max_calls
        assert combined.max_estimated_usd is not None
        assert source.max_estimated_usd is not None
        assert combined.max_estimated_usd <= source.max_estimated_usd


# ------------------------------------------------ billed per token, or not billed per token


NEMOTRON = "nvidia/nemotron-3-super-120b-a12b"


def test_every_priced_model_is_metered_and_carries_the_price_it_was_priced_at() -> None:
    """The billing catalog is derived from the price catalog, so the two cannot disagree."""
    for (provider, model_id), price in PRICES.items():
        billing = billing_for(provider, model_id)
        assert billing is not None
        assert billing.mode is BillingMode.METERED
        assert billing.is_metered
        assert billing.price is price
        assert billing.source == price.source


def test_a_free_hosted_endpoint_is_recorded_as_one_rather_than_priced_at_zero() -> None:
    """A zero rate would assert a published price that does not exist, and would make every
    dollar ceiling trivially satisfiable for that model for ever.
    """
    billing = billing_for("nvidia", NEMOTRON)
    assert billing is not None
    assert billing.mode is BillingMode.FREE_HOSTED_TRIAL
    assert billing.price is None
    assert not billing.is_metered
    assert price_for("nvidia", NEMOTRON) is None
    assert "no per-token price" in billing.describe()


def test_the_free_entry_makes_no_claim_about_permanence_or_production_use() -> None:
    billing = billing_for("nvidia", NEMOTRON)
    assert billing is not None
    assert "not claim it is permanent" in billing.source or "permanent" in billing.source


def test_a_model_nobody_recorded_terms_for_has_none_rather_than_a_default() -> None:
    """The same posture unknown pricing already had, extended to "is there a price at all"."""
    assert billing_for("nvidia", "nvidia/nemotron-3-nano-30b") is None
    assert billing_for("openai", "gpt-4o-mini") is None
    assert billing_for("bedrock", NEMOTRON) is None
    assert billing_for("nvidia", None) is None


def test_the_two_invalid_billing_records_cannot_be_constructed() -> None:
    """A metered entry with no price is an unenforceable ceiling; a free entry with a price is
    the fabrication this type exists to prevent. Both are refused at construction.
    """
    price = PRICES[("openai", "gpt-4o-mini-2024-07-18")]
    with pytest.raises(ValueError, match="metered"):
        Billing(
            provider="openai",
            model_id="x",
            mode=BillingMode.METERED,
            source="none",
            price=None,
        )
    with pytest.raises(ValueError, match="free hosted trial"):
        Billing(
            provider="nvidia",
            model_id="y",
            mode=BillingMode.FREE_HOSTED_TRIAL,
            source="none",
            price=price,
        )


def test_a_free_endpoint_still_starts_under_call_and_token_ceilings() -> None:
    """No dollar meter is not no bound. What is at risk is quota, and quota is calls and tokens."""
    ceiling = EvalBudget(max_calls=12, max_input_tokens=100_000, max_output_tokens=10_000)
    assert not ceiling.has_dollar_cap
    guard = BudgetGuard(ceiling, price=None, live=True)
    for _ in range(12):
        guard.authorise()
    with pytest.raises(BudgetExhaustedError, match="call budget exhausted"):
        guard.authorise()


def test_a_metered_model_with_no_price_still_refuses_to_start_a_live_run() -> None:
    """The guard the dollar cap gives the paid providers is untouched by the free one."""
    with pytest.raises(PricingUnavailableError):
        BudgetGuard(EvalBudget(max_estimated_usd=Decimal("1")), price=None, live=True)


def test_an_unpriced_call_adds_no_money_rather_than_adding_zero() -> None:
    """A zero would sum across a run into a total that looked like a measurement."""
    guard = BudgetGuard(EvalBudget(max_calls=5), price=None, live=True)
    guard.authorise()
    guard.record(
        SemanticTelemetry(
            job=SemanticJob.CLASSIFY_REPLY_INTENT,
            provider="nvidia",
            model_id=NEMOTRON,
            attempts=1,
            usage=SemanticUsage(input_tokens=400, output_tokens=8),
        )
    )
    assert guard.spend.input_tokens == 400
    assert guard.spend.estimated_usd is None


def test_the_billing_catalog_holds_exactly_the_models_somebody_chose_to_run() -> None:
    """One entry per model this repository has deliberately selected. An SDK supporting a
    hundred does not put a hundred here: an entry is a decision, not a capability.
    """
    assert set(BILLING) == set(PRICES) | {("nvidia", NEMOTRON)}


def test_ledger_runs_groups_lines_by_run_identity_and_keeps_the_splits_they_named(
    tmp_path: Path,
) -> None:
    """A continued run is several lines and one run; the sum over runs is the model's total."""
    path = tmp_path / "cost-ledger.jsonl"
    canary = replace(
        _ledger_line(provider="bedrock", model_id="nova", calls=1, usd="0.0007"),
        run_id="first",
        splits=("development",),
    )
    resume = replace(canary, calls=20, attempts=20, estimated_usd="0.0152")
    other = replace(canary, run_id="second", splits=())
    append_to_ledger(path, canary)
    append_to_ledger(path, resume)
    append_to_ledger(path, other)
    append_to_ledger(path, _ledger_line(provider="bedrock", model_id=None, calls=3, usd=None))
    append_to_ledger(path, _ledger_line(provider="openai", model_id="nova", calls=9, usd="0.09"))

    runs = ledger_runs(path, mode="live", provider="bedrock", model_id="nova")
    assert [run.run_id for run in runs] == ["first", "second"]
    first, second = runs
    assert first.totals.runs == 2
    assert first.totals.calls == 21
    assert first.totals.estimated_usd == Decimal("0.0159")
    assert first.splits == ("development",)
    assert second.splits == ()

    totals = ledger_totals(path, mode="live", provider="bedrock", model_id="nova")
    assert sum(run.totals.calls for run in runs) == totals.calls == 22
    assert totals.unattributed_calls == 3

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["splits"] == ["development"]
    assert "splits" not in lines[2]
