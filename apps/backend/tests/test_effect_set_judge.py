"""The pass rule itself, broken on purpose in every way it can be broken.

A judge nobody has ever seen refuse is not a judge. Each test here starts from an observation
that matches a frozen scenario exactly, damages it in one specific way, and asserts the verdict
turns. The damage is always the smallest possible: one order moved, one order missing, one
effect absent, one count off by one -- because the rule is exact equality and a rule that is
exact has to fail on the smallest difference or it is not exact.

Nothing here needs a database, a container, a model or a credential. The expectations come from
``docs/effect-sets/scenarios.v1.json`` and the observations are built from the same document,
which is the one place a test may do that: what is under test is the comparison, not the system.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _effect_set_judge import (
    Observation,
    Verdict,
    assert_passes,
    harness_failure,
    judge,
    record,
)
from _effect_sets import (
    Effects,
    checkpoint_names,
    cumulative_effects_at,
    partition_at,
    scenario,
)
from scripts.run_effect_sets import FAIL, HARNESS_FAILURE, PASS, SINK_VARIABLE

CANONICAL = "S01"
"""A scenario with all four partitions populated and every effect kind in play."""


def exactly(scenario_id: str = CANONICAL) -> dict[str, Observation]:
    """An observation that agrees with the frozen labels at every declared checkpoint."""
    document = scenario(scenario_id)
    return {
        name: Observation(
            partition=dict(partition_at(document, name)),
            effects=dict(cumulative_effects_at(document, name)),
        )
        for name in checkpoint_names(document)
    }


def moved(
    observations: dict[str, Observation],
    checkpoint: str,
    *,
    order: str,
    out_of: str,
    into: str,
) -> dict[str, Observation]:
    reading = observations[checkpoint]
    partition = {name: set(members) for name, members in reading.partition.items()}
    partition[out_of].discard(order)
    partition[into].add(order)
    observations[checkpoint] = Observation(
        partition={name: frozenset(members) for name, members in partition.items()},
        effects=reading.effects,
    )
    return observations


def with_effects(
    observations: dict[str, Observation], checkpoint: str, effects: Effects
) -> dict[str, Observation]:
    reading = observations[checkpoint]
    observations[checkpoint] = Observation(partition=reading.partition, effects=effects)
    return observations


# ------------------------------------------------------------------------- an exact agreement


def test_an_observation_that_agrees_everywhere_passes() -> None:
    verdict = judge(CANONICAL, exactly())
    assert verdict.outcome == PASS
    assert verdict.diffs == ()
    assert verdict.passed is True


@pytest.mark.parametrize("scenario_id", ["S01", "S02", "S03", "S11", "S12", "S16"])
def test_the_judge_agrees_with_every_shape_of_scenario(scenario_id: str) -> None:
    """Two checkpoints or four, an empty threatened set or a full one: the rule does not vary."""
    assert judge(scenario_id, exactly(scenario_id)).outcome == PASS


# ------------------------------------------------------------------------------ the partitions


def test_a_misclassified_order_fails_and_the_diff_names_both_sides() -> None:
    """The commonest disagreement there could be: right promise, wrong authority."""
    observations = moved(
        exactly(), "PLANNED", order="ord-b", out_of="consent_required", into="blocked"
    )
    verdict = judge(CANONICAL, observations)

    assert verdict.outcome == FAIL
    subjects = {(diff.checkpoint, diff.aspect, diff.subject) for diff in verdict.diffs}
    assert ("PLANNED", "partition", "consent_required") in subjects
    assert ("PLANNED", "partition", "blocked") in subjects
    asked = next(diff for diff in verdict.diffs if diff.subject == "consent_required")
    assert "ord-b" in asked.expected
    assert "ord-b" not in asked.observed


def test_a_missing_order_fails_the_scenario() -> None:
    """A partition that lost a member is not a partition that nearly matched."""
    reading = exactly()["PLANNED"]
    partition = {name: set(members) for name, members in reading.partition.items()}
    partition["blocked"].discard("ord-c")
    observations = exactly()
    observations["PLANNED"] = Observation(
        partition={name: frozenset(members) for name, members in partition.items()},
        effects=reading.effects,
    )

    assert judge(CANONICAL, observations).outcome == FAIL


def test_an_extra_order_fails_the_scenario() -> None:
    """An order nobody labelled into that partition is a difference like any other."""
    observations = moved(
        exactly(), "PLANNED", order="ord-f", out_of="untouched", into="auto_repairable"
    )
    assert judge(CANONICAL, observations).outcome == FAIL


def test_a_partition_that_moves_only_at_the_last_checkpoint_still_fails() -> None:
    """Every declared checkpoint is judged, not only the first or the terminal one."""
    document = scenario(CANONICAL)
    last = checkpoint_names(document)[-1]
    observations = moved(exactly(), last, order="ord-a", out_of="auto_repairable", into="blocked")

    verdict = judge(CANONICAL, observations)
    assert verdict.outcome == FAIL
    assert {diff.checkpoint for diff in verdict.diffs} == {last}


# --------------------------------------------------------------------------------- the effects


def test_a_missing_effect_fails_the_scenario() -> None:
    """An escalation the labels declare and the run did not produce."""
    document = scenario(CANONICAL)
    last = checkpoint_names(document)[-1]
    effects = dict(cumulative_effects_at(document, last))
    dropped = next(key for key in effects if key[1] == "owner_escalation")
    del effects[dropped]

    verdict = judge(CANONICAL, with_effects(exactly(), last, effects))
    assert verdict.outcome == FAIL
    assert any(diff.subject == f"{dropped[0]}/{dropped[1]}" for diff in verdict.diffs)


def test_an_effect_the_manifest_never_declared_fails_the_scenario() -> None:
    """Omission is a claim, not a silence: a pair absent from the labels must be exactly zero."""
    document = scenario(CANONICAL)
    last = checkpoint_names(document)[-1]
    effects = dict(cumulative_effects_at(document, last))
    effects[("ord-f", "customer_message")] = 1

    verdict = judge(CANONICAL, with_effects(exactly(), last, effects))
    assert verdict.outcome == FAIL
    extra = next(diff for diff in verdict.diffs if diff.subject == "ord-f/customer_message")
    assert extra.expected == "0"
    assert extra.observed == "1"


def test_a_duplicated_effect_fails_the_scenario() -> None:
    """Two amendments fail as surely as zero: the multiset is compared, not the key set."""
    document = scenario(CANONICAL)
    last = checkpoint_names(document)[-1]
    effects = dict(cumulative_effects_at(document, last))
    doubled = next(key for key in effects if key[1] == "order_amendment")
    effects[doubled] = effects[doubled] + 1

    verdict = judge(CANONICAL, with_effects(exactly(), last, effects))
    assert verdict.outcome == FAIL
    diff = next(diff for diff in verdict.diffs if diff.subject == f"{doubled[0]}/{doubled[1]}")
    assert diff.expected == "1"
    assert diff.observed == "2"


def test_an_effect_at_planning_fails_because_the_manifest_declares_none() -> None:
    """Planning has done nothing, in all sixteen. An observation that says otherwise is a fail."""
    observations = with_effects(exactly(), "PLANNED", {("ord-a", "task_hold"): 1})
    assert judge(CANONICAL, observations).outcome == FAIL


# ------------------------------------------------- what could not be told apart from a failure


def test_a_declared_checkpoint_that_was_never_observed_is_a_harness_failure() -> None:
    """ "We could not tell" is not "the system got it wrong", and the protocol keeps them apart."""
    observations = exactly()
    del observations["CONFIRMED"]

    verdict = judge(CANONICAL, observations)
    assert verdict.outcome == HARNESS_FAILURE
    assert "CONFIRMED" in verdict.reason
    assert verdict.diffs == ()


def test_observing_a_checkpoint_the_scenario_does_not_declare_is_a_harness_failure() -> None:
    """The same fault from the other side: the harness watched a moment nothing claims about."""
    observations = exactly("S03")
    observations["CONSENT_SETTLED"] = observations["SETTLED"]

    verdict = judge("S03", observations)
    assert verdict.outcome == HARNESS_FAILURE
    assert "CONSENT_SETTLED" in verdict.reason


def test_a_harness_failure_is_a_nonpass_that_names_itself() -> None:
    verdict = harness_failure("S07", "the fixture would not build")
    assert verdict.outcome == HARNESS_FAILURE
    assert verdict.passed is False
    assert verdict.reason == "the fixture would not build"


# ------------------------------------------------------------------------- recording a verdict


def test_a_verdict_is_written_to_the_sink_as_one_json_line(tmp_path: Path) -> None:
    sink = tmp_path / "verdicts.jsonl"
    record(judge(CANONICAL, exactly()), sink=sink)
    record(harness_failure("S07", "raised"), sink=sink)

    lines = [json.loads(line) for line in sink.read_text(encoding="utf-8").splitlines()]
    assert [entry["scenario"] for entry in lines] == [CANONICAL, "S07"]
    assert [entry["outcome"] for entry in lines] == [PASS, HARNESS_FAILURE]


def test_a_failing_verdict_carries_its_whole_diff_into_the_sink(tmp_path: Path) -> None:
    """The capture is written before any repair, so the diff has to survive the failure."""
    sink = tmp_path / "verdicts.jsonl"
    observations = moved(
        exactly(), "PLANNED", order="ord-b", out_of="consent_required", into="blocked"
    )
    record(judge(CANONICAL, observations), sink=sink)

    entry: dict[str, Any] = json.loads(sink.read_text(encoding="utf-8").strip())
    assert entry["outcome"] == FAIL
    assert len(entry["diffs"]) >= 2
    assert {"checkpoint", "aspect", "subject", "expected", "observed"} == set(entry["diffs"][0])


def test_recording_without_a_sink_does_nothing_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scenario file stays an ordinary pytest file that anybody can run on its own."""
    monkeypatch.delenv(SINK_VARIABLE, raising=False)
    record(judge(CANONICAL, exactly()))


# ---------------------------------------------------------------------------- failing out loud


def test_a_failing_verdict_raises_with_every_difference_in_the_message() -> None:
    observations = moved(
        exactly(), "PLANNED", order="ord-b", out_of="consent_required", into="blocked"
    )
    with pytest.raises(AssertionError) as raised:
        assert_passes(judge(CANONICAL, observations))

    message = str(raised.value)
    assert CANONICAL in message
    assert "consent_required" in message
    assert "ord-b" in message


def test_a_passing_verdict_raises_nothing() -> None:
    assert_passes(Verdict(scenario=CANONICAL, outcome=PASS))
