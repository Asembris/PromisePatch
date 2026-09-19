"""``C01``-``C09`` are temporally executable, and the March 2026 anchor is why they were not.

The dress rehearsal's §13 named this blocker and left it open. `ADR-0019
<../../docs/adr/0019-a-benchmark-world-is-installed-at-a-run-local-anchor.md>`_ decided it. This
module is the proof, and it takes **no arm, no model, no database, no order system and no AWS
call**: every assertion below is about the pure projected world and the two pure functions the
engine narrows a report with.

Those two functions are restated here rather than imported, for one reason:
:func:`promisepatch.domain.physical.bakery_day` builds an application settings object and
:func:`promisepatch.domain.interpretation._commitment_candidates` needs a hydrated
``ObservationContext`` off a live connection. What is asserted is that the *arithmetic* the engine
performs has the answer the scenario needs; :func:`test_the_restatements_agree_with_the_engine`
pins the restatements to the real ones so this file cannot quietly drift into testing itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from scripts.sur1.bindings import clock
from scripts.sur1.bindings.declaration import published
from scripts.sur1.bindings.programs import ScenarioProgram, programs
from scripts.sur1.bindings.worldsnapshot import digest_of, snapshot_of

from promise_graph.examples import hollow_oak
from promise_graph.model import ReceivedState
from promise_graph.snapshot import GraphSnapshot

ZONE = ZoneInfo("Africa/Tunis")
"""The bakery's own calendar, which is the settings default and what a local run resolves."""

DAY = datetime(2026, 9, 19, tzinfo=ZONE)
"""A fixed day to reason on, so this file does not become a test of the day it is run."""

RASPBERRIES = hollow_oak.RASPBERRIES

SCENARIOS = sorted(programs())


# ------------------------------------------------------------- the engine's own two questions


def bakery_day(now: datetime) -> tuple[datetime, datetime]:
    """``physical.bakery_day``, without constructing an application settings object."""
    local = now.astimezone(ZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(now.tzinfo), (local + timedelta(days=1)).astimezone(now.tzinfo)


def candidates(world: GraphSnapshot, now: datetime) -> tuple[str, ...]:
    """``interpretation._commitment_candidates`` for *today's raspberry delivery*.

    The sentence names no supplier, so every open raspberry commitment is a candidate and the
    only thing narrowing them is the word *today*. Note the engine's own ``if today:`` -- a
    narrowing that selects nothing is **skipped**, which is precisely why a historical world
    leaves two candidates standing rather than none.
    """
    start, end = bakery_day(now)
    open_raspberry = [
        commitment
        for commitment in world.commitments.values()
        if any(
            line.resource_id == RASPBERRIES and line.received_state is ReceivedState.EXPECTED
            for line in commitment.lines
        )
    ]
    today = [item for item in open_raspberry if start <= item.due_at < end]
    chosen = today or open_raspberry
    return tuple(sorted(item.id for item in chosen))


def option_keys(world: GraphSnapshot, now: datetime) -> tuple[tuple[str, ...], ...]:
    """The keywords each clarification option would carry, as ``_commitment_question`` builds them.

    ``normalize(supplier_name).split()`` plus ``_day_word``. Two options carrying one key is the
    collapse: no answer can match one rather than the other.
    """
    start, end = bakery_day(now)
    keys = []
    for identifier in candidates(world, now):
        commitment = world.commitments[identifier]
        supplier = world.suppliers[commitment.supplier_id].name.lower().split()
        day_word = "today" if start <= commitment.due_at < end else "tomorrow"
        keys.append((*supplier, day_word))
    return tuple(keys)


def world_at(program: ScenarioProgram, anchor: datetime) -> GraphSnapshot:
    return program.world(anchor=anchor)


def anchor_for(now: datetime) -> datetime:
    return clock.run_anchor(now, zone=ZONE)


# --------------------------------------------------------------------- the reproduced failure


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_the_frozen_fixture_anchor_collapses_every_scenario(scenario_id: str) -> None:
    """The blocker itself, reproduced. Delete this and nobody can tell the fix from decoration.

    At the fixture's own March 2026 anchor, read on any later day: both Valley Produce deliveries
    are in the past, neither falls in the bakery day, the ``today`` narrowing selects nothing and
    is skipped, and both surviving options carry the identical keywords.
    """
    now = DAY.replace(hour=9)
    world = world_at(programs()[scenario_id], hollow_oak.ANCHOR)

    start, end = bakery_day(now)
    assert not any(start <= world.commitments[item].due_at < end for item in candidates(world, now))
    assert len(candidates(world, now)) == 2
    assert len(set(option_keys(world, now))) == 1
    assert set(option_keys(world, now)) == {("valley", "produce", "tomorrow")}


# ------------------------------------------------------- C01-C09, at the run-local anchor


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_the_intended_clarification_options_stay_distinct(scenario_id: str) -> None:
    """One candidate, so the commitment question is not asked and the scope question is.

    This is the whole of what the blocker took away. Exactly one open raspberry commitment falls
    in the bakery day, so ``_commitment_candidates`` narrows to it, and the case goes on to ask
    the question the scenario was authored around.
    """
    now = DAY.replace(hour=9)
    world = world_at(programs()[scenario_id], anchor_for(now))

    assert candidates(world, now) == (hollow_oak.VP_TODAY,)
    assert len(set(option_keys(world, now))) == len(option_keys(world, now))


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_the_deliveries_land_in_the_intended_bakery_day_relation(scenario_id: str) -> None:
    """Today's delivery is today and already past; tomorrow's is not today."""
    now = DAY.replace(hour=9)
    anchor = anchor_for(now)
    world = world_at(programs()[scenario_id], anchor)
    start, end = bakery_day(now)

    today = world.commitments[hollow_oak.VP_TODAY].due_at
    tomorrow = world.commitments[hollow_oak.VP_TOMORROW].due_at

    assert start <= today < end
    assert today <= now, "the report is about a delivery that has already failed to arrive"
    assert now - today <= clock.SETTLED_BEFORE
    assert not start <= tomorrow < end
    assert tomorrow > end


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_every_relative_offset_equals_the_canonical_world(scenario_id: str) -> None:
    """Only the origin moved. Every instant keeps its exact distance from the anchor.

    Asserted over the canonical snapshot rather than over a chosen handful of fields, so a
    timestamp this test never heard of is covered by it.
    """
    program = programs()[scenario_id]
    canonical = snapshot_of(program, anchor=hollow_oak.ANCHOR)
    rebased = snapshot_of(program, anchor=anchor_for(DAY.replace(hour=9)))

    assert rebased == canonical


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_the_published_world_digest_does_not_move(scenario_id: str) -> None:
    """The freeze's own identity for this starting world, recomputed at the run-local anchor."""
    program = programs()[scenario_id]
    frozen = published()["programs"][scenario_id]["world_digest"]

    assert digest_of(program, anchor=anchor_for(DAY.replace(hour=9))) == frozen


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_different_absolute_anchors_are_the_same_world(scenario_id: str) -> None:
    """Two runs on two days start from one world, which is the claim the freeze makes."""
    program = programs()[scenario_id]
    anchors = [
        hollow_oak.ANCHOR,
        anchor_for(DAY.replace(hour=9)),
        anchor_for(DAY.replace(hour=9) + timedelta(days=97)),
        anchor_for(DAY.replace(hour=14) - timedelta(days=400)),
    ]

    assert len({digest_of(program, anchor=anchor) for anchor in anchors}) == 1


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_the_scenario_is_legible_at_every_hour_the_clock_accepts(scenario_id: str) -> None:
    """Not one convenient hour. Every accepted five-minute slot of the day, for every scenario."""
    program = programs()[scenario_id]
    moment = DAY
    broken = []
    for _ in range((24 * 60) // 5):
        try:
            anchor = anchor_for(moment)
        except clock.ClockUnusableError:
            moment += timedelta(minutes=5)
            continue
        if candidates(world_at(program, anchor), moment) != (hollow_oak.VP_TODAY,):
            broken.append(moment.astimezone(ZONE).strftime("%H:%M"))
        moment += timedelta(minutes=5)

    assert broken == []


# ------------------------------------------------------------------ the day boundary itself


def test_the_refused_window_is_exactly_the_two_hours_that_cannot_work() -> None:
    """The refusal is bounded and named, not a general reluctance to run."""
    refused = []
    moment = DAY
    for _ in range((24 * 60) // 5):
        try:
            anchor_for(moment)
        except clock.ClockUnusableError:
            refused.append(moment.astimezone(ZONE).strftime("%H:%M"))
        moment += timedelta(minutes=5)

    assert {entry[:2] for entry in refused} == {"00", "01"}
    assert len(refused) == 24


@pytest.mark.parametrize("hour", [0, 1])
def test_a_refused_hour_really_would_have_collapsed(hour: int) -> None:
    """The refusal is earned. Anchoring there puts both deliveries in one bakery day."""
    now = DAY.replace(hour=hour, minute=30)
    with pytest.raises(clock.ClockUnusableError):
        anchor_for(now)

    naive = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0) - clock.SETTLED_BEFORE
    world = world_at(programs()["C01"], naive)
    assert (
        len(set(option_keys(world, now))) < len(option_keys(world, now))
        or len(candidates(world, now)) == 2
    )


def test_the_anchor_is_utc_whatever_the_bakery_zone_is() -> None:
    anchor = anchor_for(DAY.replace(hour=9))
    assert anchor.tzinfo is UTC
    assert anchor.utcoffset() == timedelta(0)
    assert (anchor.minute, anchor.second, anchor.microsecond) == (0, 0, 0)


def test_a_run_clock_is_recorded_in_utc_and_names_its_rule() -> None:
    recorded = clock.RunClock(
        anchor=anchor_for(DAY.replace(hour=9)), timezone=str(ZONE)
    ).describes()

    assert recorded["strategy"] == clock.STRATEGY
    assert recorded["strategy_version"] == clock.STRATEGY_VERSION
    assert recorded["bakery_timezone"] == "Africa/Tunis"
    assert recorded["anchor"].endswith("+00:00")


# ------------------------------------------------------------------------- retry and isolation


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_an_attempt_and_its_retry_are_one_world(scenario_id: str) -> None:
    """The anchor is captured on the world, so nothing between attempts can move it.

    Asserted the way the driver reaches it -- through the world object -- rather than by calling
    the rule twice, because the rule called twice at two instants would give two answers and the
    point is that it is not called twice.
    """
    from scripts.sur1.bindings.world import LiveScenarioWorld

    one = clock.RunClock(anchor=anchor_for(DAY.replace(hour=9)), timezone=str(ZONE))
    world = LiveScenarioWorld(
        orders=None,  # type: ignore[arg-type]
        channel=None,  # type: ignore[arg-type]
        kitchen=None,  # type: ignore[arg-type]
        database=None,  # type: ignore[arg-type]
        ledger=None,  # type: ignore[arg-type]
        fixture={},
        clock=one,
    )

    first = world.clock
    world.scenario_id = scenario_id
    second = world.clock
    assert first is second
    assert world.clock is not None and world.clock.anchor == one.anchor


def test_a_world_with_no_clock_says_so_rather_than_pretending() -> None:
    """Reported by name rather than as an absence, so a fingerprint records which it was."""
    from dataclasses import fields

    from scripts.sur1.bindings.world import LiveScenarioWorld

    assert clock.strategy_of(None) == clock.FIXTURE_ANCHOR
    declared = next(item for item in fields(LiveScenarioWorld) if item.name == "clock")
    assert declared.default is None


# ----------------------------------------------------------------- no arm can reach the clock


def test_nothing_on_the_clock_path_names_an_arm() -> None:
    """No arm-specific branching, asserted structurally rather than by reading the module.

    The same argument the event blinding makes: a world whose anchor depended on which arm was
    driving would make every later number a comparison between three different worlds, and the
    failure would be invisible in all of them.
    """
    from pathlib import Path

    source = Path(clock.__file__).read_text(encoding="utf-8")
    body = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith(("#", '"', "*"))
    )
    for forbidden in ("BASELINE", "PROMISEPATCH", "ABLATION", "arm_token", "arm_label"):
        assert forbidden not in body


def test_the_clock_takes_nothing_that_could_identify_an_arm() -> None:
    import inspect

    for function in (clock.run_anchor, clock.run_clock, clock.delivery_offsets):
        names = set(inspect.signature(function).parameters)
        assert not names & {"arm", "arms", "label", "token", "budget", "model", "scenario"}


def test_one_anchor_serves_every_scenario() -> None:
    """No per-scenario branch: the same instant projects all nine."""
    anchor = anchor_for(DAY.replace(hour=9))
    legible = {
        scenario_id: candidates(world_at(program, anchor), DAY.replace(hour=9))
        for scenario_id, program in sorted(programs().items())
    }

    assert set(legible.values()) == {(hollow_oak.VP_TODAY,)}
    assert len(legible) == 9


# ------------------------------------------------------- this file is about the real engine


def test_the_restatements_agree_with_the_engine() -> None:
    """``bakery_day`` here is ``bakery_day`` there, and ``_day_word`` is the engine's own rule.

    Without this, every assertion above could be true of arithmetic nothing in production
    performs.
    """
    from promisepatch.domain.interpretation import _day_word
    from promisepatch.domain.physical import bakery_day as engine_bakery_day

    now = DAY.replace(hour=9).astimezone(UTC)
    if clock.bakery_timezone() == ZONE:
        assert bakery_day(now) == engine_bakery_day(now)
    else:  # pragma: no cover - a deployment configured to another kitchen's calendar
        local = now.astimezone(clock.bakery_timezone())
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        assert engine_bakery_day(now) == (
            midnight.astimezone(now.tzinfo),
            (midnight + timedelta(days=1)).astimezone(now.tzinfo),
        )

    start, end = bakery_day(now)
    world = world_at(programs()["C01"], anchor_for(now))

    class _Context:
        """Only the two fields ``_day_word`` reads. It reads no others, which is the point."""

        day_start = start
        day_end = end

    for identifier, expected in (
        (hollow_oak.VP_TODAY, "today"),
        (hollow_oak.VP_TOMORROW, "tomorrow"),
    ):
        commitment = world.commitments[identifier]
        assert _day_word(cast(Any, _Context()), cast(Any, commitment)) == expected
