"""Who said a real model may be paid to answer, and for which stage. Distinct from a budget.

A budget answers *how much*. This answers *whether at all*, and it exists because the two were
conflated once and the harness spent calls nobody had asked it to spend.

The event that made this module necessary is worth stating, because the fix only makes sense
against it. A test asserted that an unpriced model could not be benchmarked, and it asserted it
by running the real command with ``--live`` and the model id of the day. While the model had no
price the assertion held for the reason the test claimed. The day the price was added, the same
line stopped being an assertion about pricing and became a live benchmark: it built the real
provider and put three worker sentences to it. Nothing was billed, because the account had no
access to that model -- which is to say the thing that stopped it was AWS, not this repository.

So the rule here is not "another flag". It is:

**Executing the live code path and authorising external paid inference are different acts, and
the second one cannot be performed by accident.** ``--live`` says which code path to take.
:func:`authorise` says a person accepted a charge, for one named scope, once. The phrase is not
a secret and is not authentication -- publishing it costs nothing, because what it defends
against is inattention rather than an attacker. It is a deliberateness gate.

Four properties, each of which closes a way the previous guard could have been satisfied by
something other than a decision:

* **Command line only.** Never read from ``.env``, ``Settings``, or any environment variable.
  An operator who exported it last week has not authorised anything today.
* **Scope-bound.** The phrase names the stage it pays for, so a Stage-A authorisation is not a
  Stage-B authorisation. Approval for a bounded probe does not become approval for the rest.
* **Run-scoped.** :class:`SpendAuthorisation` is a value produced by one invocation and
  discarded with it. There is no persisted grant, so there is nothing to leave switched on.
* **Never a default.** No fixture grants it, no CI variable grants it, and the parser's default
  is ``None``.

And beside all of that, one interlock that does not depend on the operator at all:
:func:`refuse_real_inference_under_test`. A process running under pytest may not construct a
paid provider, whatever flags it was handed and whatever credentials it inherited. Tests that
need the orchestration pass a provider builder in; the real builder is not reachable from them.

This module is the policy and holds no client. It reaches no network, imports no SDK, and is
the reason "the harness cannot spend by accident" is a property of a value rather than a habit.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

PHRASE_PREFIX = "AUTHORISE-PAID-INFERENCE"
"""The stem every authorisation phrase is built from. Public on purpose: see the module note."""


class SpendScope(StrEnum):
    """What one authorisation pays for. A phrase names exactly one of these.

    Two of them are the challenger's stages, and they are separate values rather than one
    ``CHALLENGER`` because that separation is the point: Stage A is a bounded probe somebody
    agreed to, and Stage B is the rest of a split, agreed to afterwards or not at all.
    """

    STAGE_A = "STAGE-A"
    STAGE_B = "STAGE-B"
    SPLIT_DEVELOPMENT = "SPLIT-DEVELOPMENT"
    SPLIT_HOLDOUT = "SPLIT-HOLDOUT"


class SpendNotAuthorisedError(RuntimeError):
    """Nobody authorised paid inference for this scope, so no provider was built."""


def required_phrase(scope: SpendScope) -> str:
    """The exact value ``--authorise-paid-inference`` must carry to pay for ``scope``."""
    return f"{PHRASE_PREFIX}-{scope.value}"


@dataclass(frozen=True, slots=True)
class SpendAuthorisation:
    """One operator's deliberate consent to charge, for one scope of one invocation.

    Carries the ceilings it was granted against so a report can say what was consented to and
    not only what was spent. It authorises; it does not enforce -- :class:`evals.budget.
    BudgetGuard` still refuses the call that would cross a cap, and neither substitutes for
    the other. Deliberate intent and a hard bound are two requirements, not one twice.
    """

    scope: SpendScope
    granted_at: str
    max_calls: int | None = None
    max_estimated_usd: Decimal | None = None

    def covers(self, scope: SpendScope) -> bool:
        return self.scope is scope

    def require(self, scope: SpendScope) -> None:
        """Refuse unless this authorisation was granted for exactly ``scope``.

        Called again at the point of spending rather than trusted from the parse. A Stage-A
        authorisation reaching a Stage-B purchase is the mistake this exists to make loud.
        """
        if self.covers(scope):
            return
        raise SpendNotAuthorisedError(
            f"this run is authorised for {self.scope.value} and is about to buy "
            f"{scope.value}. An authorisation names one scope and does not carry to the next "
            f"one: re-run with --authorise-paid-inference {required_phrase(scope)!r} if that "
            f"is what was intended."
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "scope": self.scope.value,
            "granted_at": self.granted_at,
            "max_calls": self.max_calls,
            "max_estimated_usd": (
                None if self.max_estimated_usd is None else str(self.max_estimated_usd)
            ),
        }


def authorise(
    phrase: str | None,
    scope: SpendScope,
    *,
    max_calls: int | None = None,
    max_estimated_usd: Decimal | None = None,
) -> SpendAuthorisation:
    """Turn a typed phrase into an authorisation for ``scope``, or refuse.

    ``phrase`` comes from the command line and from nowhere else. ``None`` -- the parser's
    default, and what every test and every CI job passes without knowing it -- is a refusal,
    which is what makes ``--live`` alone insufficient to buy anything.
    """
    expected = required_phrase(scope)
    if phrase is None:
        raise SpendNotAuthorisedError(
            f"--live names a code path; it does not authorise a charge. Buying {scope.value} "
            f"also takes --authorise-paid-inference {expected!r}, typed at this invocation. "
            f"It is not read from the environment, not read from .env, and not defaulted."
        )
    if phrase != expected:
        raise SpendNotAuthorisedError(
            f"the authorisation phrase does not name {scope.value}. Expected {expected!r}. An "
            f"authorisation for one scope is not an authorisation for another."
        )
    return SpendAuthorisation(
        scope=scope,
        granted_at=datetime.now(tz=UTC).isoformat(),
        max_calls=max_calls,
        max_estimated_usd=max_estimated_usd,
    )


# ------------------------------------------------------------------- the process interlock


def under_test() -> bool:
    """Whether this process is a test run. Read from the runner, not guessed from a flag."""
    return "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ


def refuse_real_inference_under_test(scope: SpendScope) -> None:
    """Refuse to build a paid provider inside a test process, whatever else is true.

    The second guard, and the one that holds when the first is satisfied wrongly. Operator
    authorisation stops a person spending without meaning to; this stops a *test* spending,
    which is a different failure and was the one that actually happened. It does not care
    whether a phrase was typed, whether the model is priced, whether credentials are present
    or whether the account has access -- none of those were ever the thing keeping CI safe.

    Tests that need the orchestration hand a provider builder in instead. That is the real
    guarantee: the path from a test to a paid provider is a parameter nobody passes, and this
    check is what closes the default.
    """
    if not under_test():
        return
    raise SpendNotAuthorisedError(
        f"a test process may not construct a paid provider (scope {scope.value}). Tests pass "
        f"a provider builder in; the real one is not reachable from pytest, and no flag, "
        f"phrase, credential or model access changes that."
    )


__all__ = [
    "PHRASE_PREFIX",
    "SpendAuthorisation",
    "SpendNotAuthorisedError",
    "SpendScope",
    "authorise",
    "refuse_real_inference_under_test",
    "required_phrase",
    "under_test",
]
