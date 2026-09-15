"""The pass rule, implemented once, reading its expectations only from the frozen manifest.

The manifest's own ``pass_rule`` field says it:

    A scenario passes only on exact order-set equality for all four partitions at every
    declared checkpoint AND exact equality of the cumulative effect multiset at every declared
    checkpoint, including the zeros implied by absence. A missing, extra or misclassified order
    or effect fails the entire scenario. Rationale, notes and refusal fields are diagnostic, not
    pass criteria.

That is what :func:`judge` implements and it is the only thing it implements. There is no
partial credit, no tolerance, no "close enough" partition and no diff that is merely advisory.
A scenario is ``PASS`` when it produced no difference at all and a nonpass otherwise.

**The expectation is read, never passed in.** :func:`judge` takes a scenario *identifier* and
loads that scenario out of ``docs/effect-sets/scenarios.v1.json`` itself, after asserting the
document's published identity. A caller therefore cannot hand it a hand-typed expectation, and a
test that wanted to soften a label would have to edit the frozen manifest and break its hash.

**It observes nothing.** Everything it judges arrives as an :class:`Observation` the caller read
off the real system. This module imports no engine, no backend, no database and no fixture, so
there is no path by which the expectation and the observation could come from the same place.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from _effect_sets import (
    PARTITIONS,
    PUBLISHED_SHA,
    Effects,
    Partition,
    checkpoint_names,
    cumulative_effects_at,
    identity,
    partition_at,
    scenario,
)
from scripts.run_effect_sets import FAIL, HARNESS_FAILURE, PASS, SINK_VARIABLE


@dataclass(frozen=True, slots=True)
class Observation:
    """What the real system held at one checkpoint, as whole sets and a whole multiset.

    ``effects`` is the *cumulative* incident-caused count per ``(order, kind)`` up to and
    including this checkpoint, and it is a complete mapping: a pair the observer did not record
    is an observation of zero, exactly as a pair the manifest does not declare is a claim of
    zero. Both sides are therefore total, and the comparison is equality rather than containment.
    """

    partition: Mapping[str, frozenset[str]]
    effects: Effects


@dataclass(frozen=True, slots=True)
class Diff:
    """One difference between a frozen label and what the run produced, in publishable form."""

    checkpoint: str
    aspect: str
    subject: str
    expected: str
    observed: str

    def as_dict(self) -> dict[str, str]:
        return {
            "checkpoint": self.checkpoint,
            "aspect": self.aspect,
            "subject": self.subject,
            "expected": self.expected,
            "observed": self.observed,
        }


@dataclass(frozen=True, slots=True)
class Verdict:
    """One scenario's result: the outcome, and every difference that produced it."""

    scenario: str
    outcome: str
    reason: str = ""
    diffs: tuple[Diff, ...] = field(default=())

    @property
    def passed(self) -> bool:
        return self.outcome == PASS

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "outcome": self.outcome,
            "reason": self.reason,
            "diffs": [diff.as_dict() for diff in self.diffs],
        }


def _members(members: frozenset[str]) -> str:
    return "{" + ", ".join(sorted(members)) + "}" if members else "{}"


def _partition_diffs(
    checkpoint: str, expected: Partition, observed: Mapping[str, frozenset[str]]
) -> list[Diff]:
    """Exact order-set equality, one partition at a time, reported as whole sets.

    Reported per partition rather than per order on purpose: an order that moved from
    ``consent_required`` to ``blocked`` is one misclassification, and a reader of the diff needs
    to see both sides of it rather than two unrelated lines saying "missing" and "extra".
    """
    diffs: list[Diff] = []
    for name in PARTITIONS:
        want = expected[name]
        got = frozenset(observed.get(name, frozenset()))
        if want != got:
            diffs.append(
                Diff(
                    checkpoint=checkpoint,
                    aspect="partition",
                    subject=name,
                    expected=_members(want),
                    observed=_members(got),
                )
            )
    return diffs


def _effect_diffs(checkpoint: str, expected: Effects, observed: Effects) -> list[Diff]:
    """Exact equality of the cumulative multiset, including every zero implied by absence."""
    diffs: list[Diff] = []
    for key in sorted(set(expected) | set(observed)):
        want = expected.get(key, 0)
        got = observed.get(key, 0)
        if want != got:
            order, kind = key
            diffs.append(
                Diff(
                    checkpoint=checkpoint,
                    aspect="effects",
                    subject=f"{order}/{kind}",
                    expected=str(want),
                    observed=str(got),
                )
            )
    return diffs


def judge(scenario_id: str, observed: Mapping[str, Observation]) -> Verdict:
    """Compare one scenario's observations with its frozen labels at every declared checkpoint.

    The manifest decides which checkpoints matter and in what order. A declared checkpoint the
    caller did not observe is a ``HARNESS_FAILURE``, not a ``FAIL``: the scenario did not reach
    a verdict there, and the protocol keeps "the system got it wrong" and "we could not tell"
    apart. An observation of a checkpoint the manifest does not declare is the same fault from
    the other side -- the harness watched something this scenario makes no claim about.
    """
    assert identity() == PUBLISHED_SHA, "the frozen manifest is not the document that was published"

    document = scenario(scenario_id)
    declared = checkpoint_names(document)

    undeclared = sorted(set(observed) - set(declared))
    if undeclared:
        return Verdict(
            scenario=scenario_id,
            outcome=HARNESS_FAILURE,
            reason=f"observed checkpoints this scenario does not declare: {', '.join(undeclared)}",
        )

    diffs: list[Diff] = []
    for checkpoint in declared:
        reading = observed.get(checkpoint)
        if reading is None:
            return Verdict(
                scenario=scenario_id,
                outcome=HARNESS_FAILURE,
                reason=f"declared checkpoint {checkpoint} was never observed",
            )
        diffs += _partition_diffs(checkpoint, partition_at(document, checkpoint), reading.partition)
        diffs += _effect_diffs(
            checkpoint, cumulative_effects_at(document, checkpoint), reading.effects
        )

    return Verdict(
        scenario=scenario_id,
        outcome=PASS if not diffs else FAIL,
        diffs=tuple(diffs),
    )


def harness_failure(scenario_id: str, reason: str) -> Verdict:
    """A scenario that could not be executed to a verdict at all. A nonpass, disclosed by name."""
    return Verdict(scenario=scenario_id, outcome=HARNESS_FAILURE, reason=reason)


def record(verdict: Verdict, *, sink: Path | None = None) -> None:
    """Append one verdict to the run's sink, if this process was given one.

    A no-op when no sink is named, so the scenario suite is an ordinary pytest file that anybody
    can run on its own. The runner supplies the sink; nothing here decides what the verdicts add
    up to, and nothing here can see the other scenarios' results.
    """
    destination = sink or (
        Path(os.environ[SINK_VARIABLE]) if os.environ.get(SINK_VARIABLE) else None
    )
    if destination is None:
        return
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(verdict.as_dict(), sort_keys=True) + "\n")


def assert_passes(verdict: Verdict) -> None:
    """Fail the test that produced this verdict, with the whole diff in the message.

    The verdict is recorded first by the caller, so a failure is captured before it is raised:
    a run whose assertion aborted the session still leaves the diff behind for the capture.
    """
    if verdict.passed:
        return
    lines: Sequence[str] = [
        f"{verdict.scenario}: {verdict.outcome}"
        + (f" -- {verdict.reason}" if verdict.reason else ""),
        *(
            f"  {diff.checkpoint}/{diff.aspect} {diff.subject}: "
            f"expected {diff.expected}, observed {diff.observed}"
            for diff in verdict.diffs
        ),
    ]
    raise AssertionError("\n".join(lines))


PROTOCOL: Final = "docs/effect-set-run-protocol.md"
"""Named here so a reader of a failing scenario finds the rule that governs what happens next."""
