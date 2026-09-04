"""The only provider this slice has: one that does nothing, and remembers that it did.

Telegram, the order simulator and everything else with a real consequence are later slices. A
worker still needs *an* adapter to run against, and a fake one is the right thing here for a
reason beyond convenience: the property under test is that our side sends the same idempotency
key every time, and only a provider that records what it received can demonstrate that a
duplicate send under one key collapsed to one effect on its side.

Deliberately honest about what it models. It behaves the way a provider *with* idempotency-key
support behaves: a repeated key returns the original acceptance rather than acting twice. A
provider without that support would produce two real effects in the same situation, and no
amount of care on this side would prevent it -- which is why the guarantee is stated as
at-least-once delivery with a stable key rather than as exactly-once anything.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from promisepatch.domain.model import DeliveryOutcome, DeliveryStatus


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    """One call the dispatcher made, as the provider saw it."""

    kind: str
    payload: Mapping[str, Any]
    idempotency_key: str


@dataclass
class FakeEffectAdapter:
    """An in-memory provider that accepts everything and deduplicates by key.

    ``attempts`` records every call including redeliveries, so a test can assert that a crash
    in the uncertain window really did cause a second send. ``effects`` records the logical
    outcomes, so it can assert that the second send did not become a second effect.
    """

    attempts: list[DeliveryAttempt] = field(default_factory=list)
    effects: dict[str, str] = field(default_factory=dict)
    fail_with: DeliveryOutcome | None = None
    """When set, every call returns this instead of accepting. For exercising the ladder."""

    async def deliver(
        self, *, kind: str, payload: Mapping[str, Any], idempotency_key: str
    ) -> DeliveryOutcome:
        self.attempts.append(
            DeliveryAttempt(kind=kind, payload=dict(payload), idempotency_key=idempotency_key)
        )
        if self.fail_with is not None:
            return self.fail_with
        provider_ref = self.effects.setdefault(idempotency_key, f"fake-{uuid4().hex[:12]}")
        return DeliveryOutcome(status=DeliveryStatus.DELIVERED, provider_ref=provider_ref)

    @property
    def call_count(self) -> int:
        return len(self.attempts)

    @property
    def effect_count(self) -> int:
        """Logical effects, not calls. The difference between the two is the whole point."""
        return len(self.effects)
