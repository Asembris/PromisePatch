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
number scattered through the runner, and every entry carries the day it was recorded and where
it came from. It is an estimate. AWS Billing is the truth, and this is not it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
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


PRICES: Mapping[tuple[str, str], ModelPrice] = {}
"""Verified prices, by ``(provider, model id)``. Deliberately empty.

Nothing is written here from memory. A stale price silently understates a budget, which is the
one failure mode this whole module exists to prevent, so an unverified number is worse than no
number: with none, :func:`estimate_usd` returns ``None`` and a dollar budget refuses to start.

This slice makes zero provider calls, so nothing here is needed to run anything. Entries are
added from a current published price list before the first live benchmark, each with the day it
was read and the page it was read from.
"""


def price_for(provider: str, model_id: str | None) -> ModelPrice | None:
    """The catalog entry for one model, or ``None`` when there is no verified price."""
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
    "PRICES",
    "TOKENS_PER_PRICE_UNIT",
    "BudgetExhaustedError",
    "BudgetGuard",
    "BudgetedSemanticProvider",
    "CostLedgerEntry",
    "EvalBudget",
    "ModelPrice",
    "PricingUnavailableError",
    "Spend",
    "append_to_ledger",
    "estimate_usd",
    "price_for",
    "utc_now_iso",
]
