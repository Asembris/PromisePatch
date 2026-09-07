"""Deterministic scorers. Ordinary Python functions, testable without a framework.

Every correctness decision in this package is made here, by a function that takes a gold case
and an observed answer and returns booleans. Nothing is decided inside a DeepEval callback --
:mod:`evals.metrics.deepeval_adapter` calls these and reports what they said.

That order matters. A metric whose logic lives inside a third-party runner can only be checked
by running that runner, and a number nobody can reproduce by hand is not evidence.
"""

from __future__ import annotations

__all__: list[str] = []
