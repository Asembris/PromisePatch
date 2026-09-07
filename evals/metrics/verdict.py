"""One case, scored down to a number a runner can gate on.

A verdict is what DeepEval is handed: a score in ``[0, 1]``, whether it passes, and a sentence
saying why. The judgement itself is made by :mod:`evals.metrics.worker` and
:mod:`evals.metrics.customer` before any framework is involved, so the same verdict is
reachable from a unit test with no runner in the room.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Verdict:
    """The score for one case, and the reason it is that and not something else."""

    score: float
    passed: bool
    reason: str


def failed(reason: str) -> Verdict:
    return Verdict(score=0.0, passed=False, reason=reason)


def passed(reason: str = "every checked property matched the gold case") -> Verdict:
    return Verdict(score=1.0, passed=True, reason=reason)


__all__ = ["Verdict", "failed", "passed"]
