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

**This is not the external order system, and nothing here is a mirror of one.** It accepts an
amendment, invents a reference for it and forgets about it. What it exists to make testable is
the distinction the honest guarantee turns on::

    the provider never applied the effect        -> retry is free
    the provider applied it and we lost the reply -> retry is a duplicate the *key* collapses

Those two look identical from our side -- both are a timeout -- and the only way to prove the
engine treats them correctly is a provider that can be told to be each of them in turn.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from promisepatch.domain.model import DeliveryOutcome, DeliveryStatus
from promisepatch.domain.outbox import EffectAdapter


class ProviderBehaviour(StrEnum):
    """What the provider does with one call, so a test can script the awkward orderings."""

    ACCEPT = "ACCEPT"
    """Apply the effect and say so. The ordinary case."""

    TIMEOUT_BEFORE_APPLYING = "TIMEOUT_BEFORE_APPLYING"
    """Nothing happened on the provider's side. A retry is free, and costs nobody anything."""

    APPLY_THEN_LOSE_RESPONSE = "APPLY_THEN_LOSE_RESPONSE"
    """The effect *did* happen, and the answer never arrived.

    Indistinguishable from a plain timeout to the caller, which is the point: the retry is a
    second transport call for one logical effect, and only the stable key keeps it that way.
    """

    REJECT = "REJECT"
    """A deterministic refusal. Retrying it would be a lie about what the provider said."""


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    """One call the dispatcher made, as the provider saw it."""

    kind: str
    payload: Mapping[str, Any]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class LogicalEffect:
    """One thing that actually happened on the provider's side, however many calls it took."""

    kind: str
    payload: Mapping[str, Any]
    provider_ref: str


@dataclass
class FakeEffectAdapter:
    """An in-memory provider that accepts everything and deduplicates by key.

    ``attempts`` records every call including redeliveries, so a test can assert that a crash
    in the uncertain window really did cause a second send. ``effects`` records the logical
    outcomes, so it can assert that the second send did not become a second effect.
    """

    attempts: list[DeliveryAttempt] = field(default_factory=list)
    effects: dict[str, LogicalEffect] = field(default_factory=dict)
    fail_with: DeliveryOutcome | None = None
    """When set, every call returns this instead of accepting. For exercising the ladder."""

    script: list[ProviderBehaviour] = field(default_factory=list)
    """Behaviours for the next calls, consumed one per call. Afterwards, ``ACCEPT``.

    A list rather than a single flag because the interesting failures are *sequences*: apply
    and lose the reply, then accept the retry. A provider that could only be in one mood for
    ever cannot express that.
    """

    async def deliver(
        self, *, kind: str, payload: Mapping[str, Any], idempotency_key: str
    ) -> DeliveryOutcome:
        self.attempts.append(
            DeliveryAttempt(kind=kind, payload=dict(payload), idempotency_key=idempotency_key)
        )
        if self.fail_with is not None:
            return self.fail_with

        behaviour = self.script.pop(0) if self.script else ProviderBehaviour.ACCEPT
        if behaviour is ProviderBehaviour.TIMEOUT_BEFORE_APPLYING:
            return DeliveryOutcome(
                status=DeliveryStatus.RETRYABLE, error="timed out before the provider applied it"
            )
        if behaviour is ProviderBehaviour.REJECT:
            return DeliveryOutcome(
                status=DeliveryStatus.TERMINAL, error="the provider refused this amendment"
            )

        effect = self._apply(kind=kind, payload=payload, idempotency_key=idempotency_key)
        if behaviour is ProviderBehaviour.APPLY_THEN_LOSE_RESPONSE:
            # Applied, and the caller will never learn that. The retry finds the same key and
            # gets the same reference back, which is the whole reason the key has to be stable.
            return DeliveryOutcome(
                status=DeliveryStatus.RETRYABLE, error="the response was lost after applying"
            )
        return DeliveryOutcome(status=DeliveryStatus.DELIVERED, provider_ref=effect.provider_ref)

    def _apply(
        self, *, kind: str, payload: Mapping[str, Any], idempotency_key: str
    ) -> LogicalEffect:
        """Do the thing once per key, and hand back what was done however often it is asked."""
        existing = self.effects.get(idempotency_key)
        if existing is not None:
            return existing
        effect = LogicalEffect(
            kind=kind, payload=dict(payload), provider_ref=f"fake-{uuid4().hex[:12]}"
        )
        self.effects[idempotency_key] = effect
        return effect

    @property
    def call_count(self) -> int:
        return len(self.attempts)

    @property
    def effect_count(self) -> int:
        """Logical effects, not calls. The difference between the two is the whole point."""
        return len(self.effects)

    def effect_for(self, idempotency_key: str) -> LogicalEffect | None:
        return self.effects.get(idempotency_key)


@dataclass(frozen=True, slots=True)
class RoutedEffectAdapter:
    """One provider per kind of effect, chosen once, at the edge.

    The dispatcher deliberately knows nothing about what an effect *means*, and the recovery
    saga deliberately knows nothing about which provider answered. Something has to know that a
    recovery amendment goes to the order system and a customer message does not, and this is it:
    one table, built where the process is composed, rather than a conditional in the transitions
    that decided on the effects.

    ``default`` is the honest answer for a kind with no configured provider yet -- today, the
    customer channel, whose real provider is a later slice. It is a fake one, it says so, and
    routing to it is a statement about this deployment rather than a claim about the effect.
    """

    routes: Mapping[str, EffectAdapter]
    default: EffectAdapter

    async def deliver(
        self, *, kind: str, payload: Mapping[str, Any], idempotency_key: str
    ) -> DeliveryOutcome:
        adapter = self.routes.get(kind, self.default)
        return await adapter.deliver(kind=kind, payload=payload, idempotency_key=idempotency_key)
