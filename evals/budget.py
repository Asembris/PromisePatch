"""What a live evaluation run may spend, enforced before the money is gone.

An evaluation is the one workload in PromisePatch that can spend real money on purpose and at
scale. A hundred cases is not a hundred inference attempts -- the boundary retries a
schema-invalid answer once, and the AWS SDK retries a throttled one -- so "how many cases" is
not a budget and never was.

Three rules, all of them enforced rather than warned about:

**A cap refuses the next call.** :class:`BudgetGuard` is asked *before* a provider is invoked
and raises :class:`BudgetExhaustedError` rather than letting the call happen and reporting it
afterwards. A warning-only guard is a guard that has already spent the money by the time
anybody reads it.

**Unknown pricing is never zero.** A model with no configured price has an *unavailable*
estimated cost, not a free one. If a run declares a dollar budget and the model it is about to
call has no verified price, the guard refuses before the first call: a budget that cannot be
measured cannot be enforced, and pretending otherwise is how a cheap benchmark becomes an
expensive one.

**Prices live in one place and say when they were true.** :data:`PRICES` is a catalog, not a
number scattered through the runner, and every entry carries the provider, the exact model
snapshot, the day it was recorded and where it came from. It is an estimate. The provider's own
invoice is the truth, and this is not it.

And one rule that came later, from an endpoint that has no price at all:

**Not every model is billed per token, and the ones that are not do not get a fake price.**
:class:`Billing` says which of the two a model is. A metered model carries a
:class:`ModelPrice` and a dollar ceiling; a free hosted trial carries neither, and writing
``$0.00`` for it would be a claim about a commercial rate nobody published and a permanence
nobody promised -- while also switching off the one guard the dollar cap provides for the
models that *are* metered. What protects a free endpoint is not money: it is the call and token
ceilings, which apply to every provider and are the bounds that actually bite on a run this
size. So "unpriced" and "not billed per token" stay different states, and neither of them is
zero.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from promisepatch.semantic import (
    SemanticProvider,
    SemanticRequest,
    SemanticResult,
    SemanticTelemetry,
)

TOKENS_PER_PRICE_UNIT = Decimal(1_000_000)
"""Prices are quoted per million tokens, which is how every provider publishes them."""


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """What one model costs, and the provenance that makes the number reviewable."""

    provider: str
    model_id: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    snapshot_date: date
    source: str
    unit: str = "USD per 1,000,000 tokens"

    def as_payload(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "input_usd_per_million": str(self.input_usd_per_million),
            "output_usd_per_million": str(self.output_usd_per_million),
            "unit": self.unit,
            "snapshot_date": self.snapshot_date.isoformat(),
            "source": self.source,
        }


NOVA_2_LITE = ModelPrice(
    provider="bedrock",
    model_id="us.amazon.nova-2-lite-v1:0",
    input_usd_per_million=Decimal("0.33"),
    output_usd_per_million=Decimal("2.75"),
    snapshot_date=date(2026, 9, 8),
    source=(
        "AWS Price List bulk API, offer AmazonBedrock version 20260901205051 (published "
        "2026-09-01T20:50:51Z), us-east-1, SKU FY8T82UUN7VZR55K usagetype "
        "'USE1-Nova2.0Lite-input-tokens' at $0.00033 per 1K and SKU DY69Q8C3F88CHA2Q "
        "usagetype 'USE1-Nova2.0Lite-output-tokens' at $0.00275 per 1K, both feature "
        "'On-demand Inference', read 2026-09-08"
    ),
)
"""The model this repository benchmarked, at the tier it is actually called through.

**Corrected on 2026-09-08 from $0.30 / $2.50, which was the Global tier.** The catalog is
called with ``us.amazon.nova-2-lite-v1:0``, a US geo cross-Region inference profile, and
``us-east-1`` publishes exactly two on-demand tiers for this model. The plain pair priced here
-- ``USE1-Nova2.0Lite-input-tokens`` / ``-output-tokens``, $0.33 and $2.75 per million -- is
the Region's own on-demand rate, which is what a ``us.*`` geo profile bills at. The other pair
carries ``-cross-region-global`` in its usage type, is $0.30 / $2.50, and belongs to
``global.amazon....``, which this repository does not call. There is no third, ``us``-specific
usage type; that absence is itself the evidence that a geo profile bills at the source
Region's rate.

This is the same distinction :data:`CLAUDE_HAIKU_4_5` was already recorded against, applied
consistently: the earlier entry took the cheaper of the two tiers, and the cheaper one was the
wrong one. The correction moves an estimate up by 10 %, changes arithmetic only, and changes no
model output, no reading and no quality number anywhere.

An *estimated pricing snapshot*, not billing truth. AWS Billing is the truth; this is a number
somebody read on a day, recorded with that day and with the SKU it came from, so a spend figure
computed from it can be checked rather than believed.
"""


CLAUDE_HAIKU_4_5 = ModelPrice(
    provider="bedrock",
    model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    input_usd_per_million=Decimal("1.10"),
    output_usd_per_million=Decimal("5.50"),
    snapshot_date=date(2026, 9, 7),
    source=(
        "AWS Price List bulk API, offer AmazonBedrockFoundationModels version 20260901183649 "
        "(published 2026-09-01T18:36:49Z), servicename 'Claude Haiku 4.5 (Amazon Bedrock "
        "Edition)', us-east-1, SKU JQDUC8Q4K8C6GSGH 'Million Input Tokens Regional' and SKU "
        "X629GDA2GXAP6R54 'Million Response Tokens Regional', read 2026-09-07"
    ),
)
"""The challenger's price, at the tier the challenger is actually called through.

Two tiers are published for this model in ``us-east-1`` and they are not the same money. The
*Regional* pair priced here is the one a geo cross-Region inference profile
(``us.anthropic....``) bills at; the *Global* pair is $1.00 / $5.00 and belongs to
``global.anthropic....``, which is not what this repository calls. The dearer of the two is
recorded because it is the one that applies, and because a budget that guesses low is a budget
that does not hold.

Both SKUs describe the charge as *AWS Marketplace software usage*: this is a third-party model
billed through AWS Marketplace, which is a different billing surface from
:data:`NOVA_2_LITE`'s first-party Bedrock usage. That distinction is a cost fact, not a
quality one, and it is recorded here because it is the reason a spend against this model
cannot be assumed to be covered by whatever covers the other.
"""


GPT_4O_MINI = ModelPrice(
    provider="openai",
    model_id="gpt-4o-mini-2024-07-18",
    input_usd_per_million=Decimal("0.15"),
    output_usd_per_million=Decimal("0.60"),
    snapshot_date=date(2026, 9, 8),
    source=(
        "OpenAI published API pricing for the pinned snapshot gpt-4o-mini-2024-07-18, text "
        "tokens, standard (non-batch, non-cached) tier: $0.15 per 1M input tokens and $0.60 "
        "per 1M output tokens, verified 2026-09-08"
    ),
)
"""The replacement challenger's price, against the dated model snapshot it is pinned to.

Priced by snapshot rather than by the floating ``gpt-4o-mini`` alias, and that is the whole
reason the identity is written out in full. An alias is a pointer somebody else may move: a
budget computed against one and a quality number measured against another would be two
statements about two models sharing a name.

The standard tier is the one recorded because it is the one a plain Chat Completions call
bills at. Cached input and the batch API are cheaper and are not what this experiment does, so
pricing them here would make a ceiling look satisfied by a discount the run will not get.

An *estimated pricing snapshot*, not billing truth, exactly as the two entries above it are.
OpenAI's own invoice is the truth; this is a number recorded with the day it was verified so a
spend figure computed from it can be checked rather than believed.
"""


PRICES: Mapping[tuple[str, str], ModelPrice] = {
    (NOVA_2_LITE.provider, NOVA_2_LITE.model_id): NOVA_2_LITE,
    (CLAUDE_HAIKU_4_5.provider, CLAUDE_HAIKU_4_5.model_id): CLAUDE_HAIKU_4_5,
    (GPT_4O_MINI.provider, GPT_4O_MINI.model_id): GPT_4O_MINI,
}
"""Verified prices, by ``(provider, model id)``. One entry per model somebody has run.

Nothing is written here from memory. A stale price silently understates a budget, which is the
one failure mode this whole module exists to prevent, so an unverified number is worse than no
number: with none, :func:`estimate_usd` returns ``None`` and a dollar budget refuses to start.

The catalog holds the models this repository has deliberately selected to run and nothing else.
A price for a model nobody intends to call would be a number with no experiment behind it, and
the first thing it would do is make an unbudgeted call look budgeted. That is why an SDK
supporting a hundred models does not put a hundred entries here: the challenger is one pinned
snapshot, so the catalog gains exactly one.
"""


class BillingMode(StrEnum):
    """How a model is charged for, which is a different question from how much.

    Two members, and the second exists because a hosted free endpoint is not a metered model
    with a zero rate. Conflating them would put a fabricated commercial price in the catalog
    and would silently disable the dollar guard on a run, so they are separate states and a
    caller has to look at which one it has.
    """

    METERED = "metered"
    """Charged per token, at a rate somebody read from a published price list on a given day."""

    FREE_HOSTED_TRIAL = "free_hosted_trial"
    """Offered without a per-token charge for prototype and API use, at the provider's
    discretion. No price is modelled, no dollar ceiling is enforced, and nothing here says the
    arrangement is permanent or that production use would be free."""


@dataclass(frozen=True, slots=True)
class Billing:
    """What one model costs and on what terms, with the provenance that makes it reviewable.

    ``price`` is present for a metered model and absent for a free hosted trial, and the
    invariant is checked at construction rather than trusted: a metered entry with no price
    would be an unenforceable dollar cap, and a free entry carrying one would be the fabricated
    price this type exists to prevent.
    """

    provider: str
    model_id: str
    mode: BillingMode
    source: str
    price: ModelPrice | None = None

    def __post_init__(self) -> None:
        if self.mode is BillingMode.METERED and self.price is None:
            raise ValueError(f"{self.model_id!r} is metered and has no price")
        if self.mode is BillingMode.FREE_HOSTED_TRIAL and self.price is not None:
            raise ValueError(f"{self.model_id!r} is a free hosted trial and cannot carry a price")

    @property
    def is_metered(self) -> bool:
        return self.mode is BillingMode.METERED

    def describe(self) -> str:
        """One line for a preflight, saying what the money situation actually is."""
        if self.price is not None:
            return (
                f"${self.price.input_usd_per_million} in / "
                f"${self.price.output_usd_per_million} out per 1M tokens"
            )
        return "no per-token price -- free hosted trial; call and token ceilings still apply"

    def as_payload(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "mode": self.mode.value,
            "source": self.source,
            "price": None if self.price is None else self.price.as_payload(),
        }


NEMOTRON_3_SUPER = Billing(
    provider="nvidia",
    model_id="nvidia/nemotron-3-super-120b-a12b",
    mode=BillingMode.FREE_HOSTED_TRIAL,
    source=(
        "NVIDIA build (integrate.api.nvidia.com) offers this model on a free hosted endpoint "
        "for prototype and API use; NVIDIA publishes no per-token price for it, so none is "
        "recorded here. The arrangement is the provider's to change, and nothing in this "
        "entry claims it is permanent or that any other deployment of this model is free."
    ),
)
"""The NVIDIA challenger, recorded as what it is rather than as a metered model priced at zero.

Deliberately carries no ``ModelPrice``. A ``$0.00`` entry would make :func:`estimate_usd` return
a real-looking zero for every call, make a dollar ceiling trivially satisfiable, and assert a
published commercial rate that does not exist. What bounds this challenger instead is the call
and token ceilings its composition root sets -- which is the guard that matters for a free
endpoint, because the resource at risk is quota rather than money.
"""


BILLING: Mapping[tuple[str, str], Billing] = {
    **{
        key: Billing(
            provider=price.provider,
            model_id=price.model_id,
            mode=BillingMode.METERED,
            source=price.source,
            price=price,
        )
        for key, price in PRICES.items()
    },
    (NEMOTRON_3_SUPER.provider, NEMOTRON_3_SUPER.model_id): NEMOTRON_3_SUPER,
}
"""Billing terms by ``(provider, model id)``: every priced model, plus the ones that are not.

Derived from :data:`PRICES` rather than restating it, so a price recorded in one place is the
price in both and the two catalogs cannot disagree about a model. A model absent from here has
no billing terms written down at all, which is a refusal rather than a default -- the same
posture unknown pricing already had, extended to the question of whether there is a price.
"""


def billing_for(provider: str, model_id: str | None) -> Billing | None:
    """How one model is charged for, or ``None`` when nobody has written that down."""
    if model_id is None:
        return None
    return BILLING.get((provider, model_id))


def price_for(provider: str, model_id: str | None) -> ModelPrice | None:
    """The catalog entry for one model, or ``None`` when there is no verified price.

    ``None`` for a model nobody priced and ``None`` for one that is not billed per token at
    all. Those are different facts and :func:`billing_for` is what tells them apart; this is
    the narrower question every arithmetic path already asks, and both answers mean the same
    thing to arithmetic -- there is no rate to multiply by.
    """
    if model_id is None:
        return None
    return PRICES.get((provider, model_id))


def estimate_usd(
    price: ModelPrice | None, *, input_tokens: int | None, output_tokens: int | None
) -> Decimal | None:
    """What those tokens cost, or ``None`` when that cannot be said.

    ``None`` for an unknown price and ``None`` for unreported token counts, never ``0``. A zero
    would add up across a run into a total that looked like a measurement.
    """
    if price is None or input_tokens is None or output_tokens is None:
        return None
    return (
        Decimal(input_tokens) * price.input_usd_per_million
        + Decimal(output_tokens) * price.output_usd_per_million
    ) / TOKENS_PER_PRICE_UNIT


# ----------------------------------------------------------------------------- the budget


@dataclass(frozen=True, slots=True)
class EvalBudget:
    """The ceilings one run may not cross. Every field optional; ``None`` means uncapped.

    An uncapped run is a deliberate statement by whoever started it, which is why there are no
    defaults here that quietly permit spending. The commands that exist today are offline and
    reach no provider at all.
    """

    max_calls: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_estimated_usd: Decimal | None = None

    @property
    def has_dollar_cap(self) -> bool:
        return self.max_estimated_usd is not None

    def as_payload(self) -> dict[str, object]:
        return {
            "max_calls": self.max_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_estimated_usd": (
                None if self.max_estimated_usd is None else str(self.max_estimated_usd)
            ),
        }


class BudgetExhaustedError(RuntimeError):
    """The next provider call would cross a ceiling, so it is not made."""


class PricingUnavailableError(RuntimeError):
    """A dollar budget was set for a model with no verified price. Refused before any spend."""


@dataclass
class Spend:
    """What a run has used so far. ``estimated_usd`` stays ``None`` while pricing is unknown."""

    calls: int = 0
    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tokens_reported: bool = False
    estimated_usd: Decimal | None = None

    def as_payload(self) -> dict[str, object]:
        return {
            "calls": self.calls,
            "attempts": self.attempts,
            "input_tokens": self.input_tokens if self.tokens_reported else None,
            "output_tokens": self.output_tokens if self.tokens_reported else None,
            "estimated_usd": None if self.estimated_usd is None else str(self.estimated_usd),
        }


class BudgetGuard:
    """Counts what a run has spent and refuses the call that would cross a ceiling.

    Constructed with the price of the model that is about to be called, which is what lets the
    dollar cap be checked at all. ``live`` says whether real money is at stake: an offline
    replay still counts its calls and attempts -- the accounting is exercised on every run
    rather than only on the expensive ones -- but a dollar cap on a run that cannot spend
    anything is not a reason to refuse to start.
    """

    def __init__(
        self, budget: EvalBudget, *, price: ModelPrice | None = None, live: bool = False
    ) -> None:
        if live and budget.has_dollar_cap and price is None:
            raise PricingUnavailableError(
                "this run has a dollar budget and the configured model has no verified price; "
                "add the model to evals.budget.PRICES from a current published price list, or "
                "run without --max-estimated-usd and accept an unmeasured spend"
            )
        self._budget = budget
        self._price = price
        self._live = live
        self.spend = Spend()

    @property
    def price(self) -> ModelPrice | None:
        return self._price

    def authorise(self) -> None:
        """Permit one more provider call, or refuse it. Called before the call, never after."""
        budget = self._budget
        if budget.max_calls is not None and self.spend.calls >= budget.max_calls:
            raise BudgetExhaustedError(
                f"call budget exhausted: {self.spend.calls} of {budget.max_calls} used"
            )
        if (
            budget.max_input_tokens is not None
            and self.spend.input_tokens >= budget.max_input_tokens
        ):
            raise BudgetExhaustedError(
                f"input-token budget exhausted: {self.spend.input_tokens} of "
                f"{budget.max_input_tokens} used"
            )
        if (
            budget.max_output_tokens is not None
            and self.spend.output_tokens >= budget.max_output_tokens
        ):
            raise BudgetExhaustedError(
                f"output-token budget exhausted: {self.spend.output_tokens} of "
                f"{budget.max_output_tokens} used"
            )
        if (
            budget.max_estimated_usd is not None
            and self.spend.estimated_usd is not None
            and self.spend.estimated_usd >= budget.max_estimated_usd
        ):
            raise BudgetExhaustedError(
                f"estimated spend budget exhausted: ${self.spend.estimated_usd} of "
                f"${budget.max_estimated_usd} used"
            )
        self.spend.calls += 1

    def record(self, telemetry: SemanticTelemetry | None) -> None:
        """Add what one call actually used. A provider that publishes nothing adds nothing."""
        if telemetry is None:
            self.spend.attempts += 1
            return
        self.spend.attempts += telemetry.attempts
        usage = telemetry.usage
        if usage.input_tokens is None and usage.output_tokens is None:
            return
        self.spend.tokens_reported = True
        self.spend.input_tokens += usage.input_tokens or 0
        self.spend.output_tokens += usage.output_tokens or 0
        increment = estimate_usd(
            self._price, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens
        )
        if increment is None:
            return
        self.spend.estimated_usd = (self.spend.estimated_usd or Decimal(0)) + increment

    @property
    def live(self) -> bool:
        return self._live


class BudgetedSemanticProvider:
    """A provider that must ask the guard first. Implements the production semantic port.

    Wrapping rather than threading a counter through the runner, for the same reason
    observability wraps in production: a provider cannot forget to ask, and there is no second
    path by which a call could be made without being counted.
    """

    def __init__(self, inner: SemanticProvider, guard: BudgetGuard) -> None:
        self._inner = inner
        self._guard = guard
        self.name = inner.name

    async def run(self, request: SemanticRequest) -> SemanticResult:
        self._guard.authorise()
        try:
            result = await self._inner.run(request)
        except BaseException:
            self._guard.record(None)
            raise
        self._guard.record(result.telemetry)
        return result


# ----------------------------------------------------------------------------- the ledger


@dataclass(frozen=True, slots=True)
class CostLedgerEntry:
    """One line of what a run cost, in the terms a later run can be compared against.

    Identifiers and counts only. No credential, no session token, no prompt, no reply -- there
    is no field here one could travel in.
    """

    run_id: str
    recorded_at: str
    git_sha: str | None
    dataset_version: str
    dataset_hash: str
    provider: str
    model_id: str | None
    mode: str
    calls: int
    attempts: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_usd: str | None
    pricing_snapshot: str | None
    jobs: tuple[str, ...] = field(default_factory=tuple)

    def as_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "recorded_at": self.recorded_at,
            "git_sha": self.git_sha,
            "dataset_version": self.dataset_version,
            "dataset_hash": self.dataset_hash,
            "provider": self.provider,
            "model_id": self.model_id,
            "mode": self.mode,
            "jobs": list(self.jobs),
            "calls": self.calls,
            "attempts": self.attempts,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_usd": self.estimated_usd,
            "pricing_snapshot": self.pricing_snapshot,
        }


@dataclass(frozen=True, slots=True)
class LedgerTotals:
    """What every run already in a ledger adds up to. The basis of a ceiling across runs.

    A benchmark ceiling that reset with each command would not be a ceiling: two splits run
    one after the other would each be allowed the whole budget. So the caps for a run are the
    global ones minus whatever the ledger says has already been spent under them.
    """

    runs: int = 0
    calls: int = 0
    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_usd: Decimal = Decimal(0)

    unattributed_runs: int = 0
    """Lines of this provider whose model could not be named, and so debit no model's ceiling.

    A run whose every call failed reports no model id, because the id is read from what came
    back rather than from what was asked for. Those lines are real attempts and they are not
    nothing -- but they cannot be charged to a model without guessing which one, and guessing
    would let one model's outage eat another model's allowance. So they are counted here,
    beside the totals rather than inside them, and the preflight prints the count.
    """

    unattributed_calls: int = 0

    def as_payload(self) -> dict[str, object]:
        return {
            "runs": self.runs,
            "calls": self.calls,
            "attempts": self.attempts,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_usd": str(self.estimated_usd),
            "unattributed_runs": self.unattributed_runs,
            "unattributed_calls": self.unattributed_calls,
        }


def ledger_totals(
    path: Path, *, mode: str, provider: str | None = None, model_id: str | None = None
) -> LedgerTotals:
    """Sum the ledger lines for one mode, one provider and one model. Missing file means zero.

    **Both halves of the identity, never one.** A model id alone is not a model: two providers
    may publish the same name, an alias and the snapshot it points at are different models
    wearing one, and a line that names no model at all belongs to whichever provider wrote it
    and to nothing narrower. Filtering on the pair is what keeps one challenger's history out
    of another challenger's allowance -- in both directions, which matters here because a
    discontinued attempt left lines behind and a new challenger must neither inherit them nor
    be charged for them.

    Unparseable lines are skipped rather than raising: a ledger is an append-only local
    artifact, and a run must not be blocked from starting by a line somebody's editor mangled.
    What it must not do is *understate*, and skipping a line it cannot read is the direction
    that risks that -- so a skipped line is counted and reported by the caller.
    """
    if not path.exists():
        return LedgerTotals()
    runs = calls = attempts = input_tokens = output_tokens = 0
    unattributed_runs = unattributed_calls = 0
    spend = Decimal(0)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:  # pragma: no cover - a hand-mangled ledger line
            continue
        if not isinstance(entry, dict) or entry.get("mode") != mode:
            continue
        if provider is not None and entry.get("provider") != provider:
            continue
        if model_id is not None and entry.get("model_id") != model_id:
            if entry.get("model_id") is None:
                unattributed_runs += 1
                unattributed_calls += _int(entry.get("calls"))
            continue
        runs += 1
        calls += _int(entry.get("calls"))
        attempts += _int(entry.get("attempts"))
        input_tokens += _int(entry.get("input_tokens"))
        output_tokens += _int(entry.get("output_tokens"))
        recorded = entry.get("estimated_usd")
        if isinstance(recorded, str):
            spend += Decimal(recorded)
    return LedgerTotals(
        runs=runs,
        calls=calls,
        attempts=attempts,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_usd=spend,
        unattributed_runs=unattributed_runs,
        unattributed_calls=unattributed_calls,
    )


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def remaining_budget(ceiling: EvalBudget, spent: LedgerTotals) -> EvalBudget:
    """The ceiling this run may use, given what earlier runs already used.

    Never negative: a run whose allowance is gone gets zero, and the guard refuses its first
    call rather than being handed a nonsense bound it would compare against and pass.
    """
    return EvalBudget(
        max_calls=None if ceiling.max_calls is None else max(0, ceiling.max_calls - spent.calls),
        max_input_tokens=(
            None
            if ceiling.max_input_tokens is None
            else max(0, ceiling.max_input_tokens - spent.input_tokens)
        ),
        max_output_tokens=(
            None
            if ceiling.max_output_tokens is None
            else max(0, ceiling.max_output_tokens - spent.output_tokens)
        ),
        max_estimated_usd=(
            None
            if ceiling.max_estimated_usd is None
            else max(Decimal(0), ceiling.max_estimated_usd - spent.estimated_usd)
        ),
    )


def _stricter[T: (int, Decimal)](values: Iterable[T | None]) -> T | None:
    """The smallest bound present, or ``None`` when every one of them is uncapped."""
    present = [value for value in values if value is not None]
    return min(present) if present else None


def tightest(*budgets: EvalBudget) -> EvalBudget:
    """The strictest of several ceilings, field by field. Composition, never replacement.

    ``None`` means *uncapped* and therefore always loses to a number: combining a global
    allowance with a narrower stage-specific one can only ever narrow it, never widen it, and
    a field the narrower budget says nothing about keeps the wider budget's bound rather than
    becoming unlimited.

    This exists so a stage can carry its own hard bound *in addition to* the run-wide one. Two
    ceilings that must both hold are safer than one number edited up and down between runs,
    because the edit is the thing nobody re-reads. Both remain in force, and whichever refuses
    first is the one that was strictest at that moment.
    """
    return EvalBudget(
        max_calls=_stricter(budget.max_calls for budget in budgets),
        max_input_tokens=_stricter(budget.max_input_tokens for budget in budgets),
        max_output_tokens=_stricter(budget.max_output_tokens for budget in budgets),
        max_estimated_usd=_stricter(budget.max_estimated_usd for budget in budgets),
    )


def append_to_ledger(path: Path, entry: CostLedgerEntry) -> None:
    """Append one line to a local JSONL cost ledger, creating the directory if needed.

    A local artifact. Nothing writes it to the repository, and the results directory it lives
    in is ignored by git: a committed ledger would be a record of somebody's machine.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry.as_payload(), sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def utc_now_iso() -> str:
    """The wall clock, read in exactly one place so nothing else in this package touches it."""
    return datetime.now(tz=UTC).isoformat()


__all__ = [
    "BILLING",
    "CLAUDE_HAIKU_4_5",
    "GPT_4O_MINI",
    "NEMOTRON_3_SUPER",
    "NOVA_2_LITE",
    "PRICES",
    "TOKENS_PER_PRICE_UNIT",
    "Billing",
    "BillingMode",
    "BudgetExhaustedError",
    "BudgetGuard",
    "BudgetedSemanticProvider",
    "CostLedgerEntry",
    "EvalBudget",
    "LedgerTotals",
    "ModelPrice",
    "PricingUnavailableError",
    "Spend",
    "append_to_ledger",
    "billing_for",
    "estimate_usd",
    "ledger_totals",
    "price_for",
    "remaining_budget",
    "tightest",
    "utc_now_iso",
]
