"""The scorer, behind a name, so a rehearsal can be scored without the frozen one moving.

``SUR-1``'s scorer loads its ground truth out of the frozen manifest by scenario identifier and
asserts that manifest's published hash on every call. That is the property the benchmark is
built on and it is not negotiable: a scenario the frozen document does not hold cannot be
scored by it, and the honest answer to that is a different scorer rather than a softer one.

So the driver asks for a :class:`Scorer` and is handed :data:`FROZEN` unless a caller says
otherwise -- and :func:`~scripts.sur1.driver.drive` refuses to be told otherwise for
``kind="scored"``. A scored run is therefore scored by the published scorer, by construction,
and a development or rehearsal run may be scored by one written for a scenario the frozen
contract never held.

**Three members and no more.** A scorer is its version, the safety dimensions its verdicts
carry, and one pure function from a bundle to a verdict. There is deliberately nowhere on this
protocol to put an arm name, a latency, a cost or a ground-truth override, because the blind
handoff is the thing a substitute scorer must not be able to widen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Scorer(Protocol):
    """One pure function from a blind bundle to a verdict, plus what it calls itself."""

    @property
    def version(self) -> str: ...

    @property
    def safety_dimensions(self) -> tuple[str, ...]: ...

    def score(self, bundle: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class FrozenScorer:
    """The published ``SUR-1`` scorer, reached through the seam rather than around it.

    Imports inside the members on purpose: this module is imported by the capture layer, which
    is used by paths that have not decided to score anything yet.
    """

    @property
    def version(self) -> str:
        from scripts.score_safe_useful_recovery import SCORER_VERSION

        return str(SCORER_VERSION)

    @property
    def safety_dimensions(self) -> tuple[str, ...]:
        from scripts.score_safe_useful_recovery import SAFETY_DIMENSIONS

        return tuple(SAFETY_DIMENSIONS)

    def score(self, bundle: Any) -> Any:
        from scripts.score_safe_useful_recovery import score

        return score(bundle)


FROZEN: Scorer = FrozenScorer()
"""The default everywhere. A scored run is refused any other."""


__all__ = ["FROZEN", "FrozenScorer", "Scorer"]
