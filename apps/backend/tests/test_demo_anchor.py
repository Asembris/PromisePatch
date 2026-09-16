"""The anchor a reset loads the demo at, across every hour of the clock.

The demo fixture states its two Valley Produce deliveries as offsets from the anchor — one an
hour after it, one twenty-three hours after it — and the canonical scenario depends on those
landing on **different** bakery days: the clarifying question a case asks is "the whole
delivery, or just the raspberries?" about *today's* one.

Which day an instant belongs to is read from the real clock, not from the anchor, so an anchor
too near local midnight collapses that distinction and leaves a case stuck in ``CLARIFYING``
with nothing a worker can say to move it. This suite walks the whole day at five-minute steps
and asserts the property directly rather than trusting an hour range somebody typed.

Nothing here is time-dependent: every ``now`` is constructed, so the suite answers the same at
three in the afternoon and at midnight — which is the point, because the defect it covers was
found by CI running at half past midnight and by nothing else.

The second half asks the other question about the same rule: not *what hour* a seed is taken at
but *what date*. The demo is loaded once and then lived in, and a world whose story depended on
the calendar would stop telling it between the day it was recorded and the day it is watched. So
the whole canonical partition — one promise repaired, one asked about, two escalated, two never
touched — and the futurity of every deadline are asserted at seeds sixty days and a year out,
and against the real clock as well, so a run in November answers for November.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from promise_graph.availability import apply_exception_facts
from promise_graph.classification import analyze
from promise_graph.examples import hollow_oak
from promise_graph.model import Classification
from promise_graph.snapshot import GraphSnapshot
from promisepatch.domain.physical import bakery_day
from promisepatch.fixtures.demo import resolve_demo_anchor

TUNIS = "Africa/Tunis"
ZONE = ZoneInfo(TUNIS)
DAY = datetime(2026, 9, 14, tzinfo=ZONE)

STEP: Final = timedelta(minutes=5)

CANONICAL_BANDS: Final[dict[str, Classification]] = {
    hollow_oak.PROMISE_A: Classification.AUTO_RECOVERABLE,
    hollow_oak.PROMISE_B: Classification.APPROVAL_REQUIRED,
    hollow_oak.PROMISE_C: Classification.BLOCKED,
    hollow_oak.PROMISE_D: Classification.BLOCKED,
    hollow_oak.PROMISE_E: Classification.UNAFFECTED,
    hollow_oak.PROMISE_F: Classification.UNAFFECTED,
}
"""The heterogeneous-authority story the demo exists to show, by promise.

One promise the system repairs on its own, one it must ask a customer about, two it hands to an
owner, and two it never touches. Written out here rather than imported because this suite is
asking whether a *seed date* can move it, and a shared constant that moved with the code under
test would answer its own question.
"""


def at(hour: int, minute: int = 0) -> datetime:
    """A wall-clock moment in the kitchen, as the instant it really is."""
    return DAY.replace(hour=hour, minute=minute).astimezone(UTC)


def deliveries(anchor: datetime) -> tuple[datetime, datetime]:
    """When the fixture's two Valley Produce deliveries fall, for this anchor."""
    commitments = hollow_oak.hollow_oak(anchor).commitments
    return (
        commitments[hollow_oak.VP_TODAY].due_at,
        commitments[hollow_oak.VP_TOMORROW].due_at,
    )


def drivable(now: datetime) -> bool:
    """Can a worker answer the question this demo asks?

    Only if today's delivery is in the bakery day the report is made in, and tomorrow's is not.
    Otherwise the interpreter cannot tell which commitment "today's" names, or there is no
    delivery today for the report to be about, and every clarification option carries the same
    words.
    """
    anchor = resolve_demo_anchor(now, TUNIS)
    today_due, tomorrow_due = deliveries(anchor)
    start, end = bakery_day(now)
    return (start <= today_due < end) and not (start <= tomorrow_due < end)


# ------------------------------------------------------------------- the property, every hour


def test_every_five_minutes_of_the_day_produces_a_drivable_demo() -> None:
    broken = []
    moment = at(0, 0)
    for _ in range((24 * 60) // 5):
        if not drivable(moment):
            broken.append(moment.astimezone(ZONE).strftime("%H:%M"))
        moment += timedelta(minutes=5)
    assert broken == []


@pytest.mark.parametrize("hour", [23, 0])
def test_the_two_hours_that_were_broken_are_the_ones_this_exists_for(hour: int) -> None:
    """Anchoring on ``now`` unchanged really does fail here — the fix is not decoration.

    At 23:xx today's delivery has moved past midnight into tomorrow; at 00:xx tomorrow's has
    not yet cleared it. Both leave the two on one bakery day.
    """
    now = at(hour, 30)
    today_due, tomorrow_due = deliveries(now)
    start, end = bakery_day(now)
    today_is_today = start <= today_due < end
    tomorrow_is_today = start <= tomorrow_due < end
    assert not today_is_today or tomorrow_is_today
    assert drivable(now)


# --------------------------------------------------------------- what it does and does not move


@pytest.mark.parametrize("hour", [1, 6, 12, 18, 22])
def test_an_hour_that_already_works_is_left_exactly_alone(hour: int) -> None:
    now = at(hour, 17)
    assert resolve_demo_anchor(now, TUNIS) == now


@pytest.mark.parametrize(("hour", "minute"), [(23, 0), (23, 59), (0, 0), (0, 59)])
def test_a_refused_hour_is_moved_by_minutes_rather_than_by_hours(hour: int, minute: int) -> None:
    """The fixture's geometry relative to the anchor is why it is anchored on ``now`` at all."""
    now = at(hour, minute)
    moved = resolve_demo_anchor(now, TUNIS)
    assert moved != now
    assert abs(moved - now) <= timedelta(hours=1)


def test_the_correction_stays_inside_the_day_the_report_is_made_in() -> None:
    now = at(0, 30)
    moved = resolve_demo_anchor(now, TUNIS)
    assert moved.astimezone(ZONE).date() == now.astimezone(ZONE).date()


def test_an_unknown_timezone_returns_the_moment_untouched() -> None:
    """A misconfigured zone is not a reason to invent an anchor nobody asked for."""
    now = at(12, 0)
    assert resolve_demo_anchor(now, "Mars/Olympus_Mons") == now


def test_the_offsets_are_read_off_the_fixture_rather_than_written_down() -> None:
    """If the fixture moves a delivery, the safe window moves with it and nothing is restated."""
    today_due, tomorrow_due = deliveries(hollow_oak.ANCHOR)
    assert today_due - hollow_oak.ANCHOR == timedelta(hours=1)
    assert tomorrow_due - hollow_oak.ANCHOR == timedelta(hours=23)


# ----------------------------------------------------------- the same story, whatever the date


def todays_raspberry_delivery(snapshot: GraphSnapshot, now: datetime) -> str:
    """Which commitment "today's raspberry delivery" names, narrowed the way the reading is.

    The sentence names no supplier, so every open raspberry commitment is a candidate and the
    only thing that narrows them is the word *today*: the interpreter keeps the candidates due
    inside the bakery's own calendar day (``promisepatch.domain.interpretation``'s
    ``_commitment_candidates``, against ``bakery_day``). This is the step that a world seeded on
    an earlier day loses, and it is why the band tests below resolve the commitment rather than
    pinning it -- pinning it would assert the classification of a delivery no reading would have
    chosen, and a fixed-date fixture would sail through.

    Anything other than exactly one candidate is a failure and not a different set of bands. No
    candidate means there is no delivery for the canonical report to be about; more than one
    means the case stops to ask which was meant, and every option carries the same words.
    """
    start, end = bakery_day(now)
    today = [
        commitment.id
        for commitment in snapshot.commitments.values()
        if any(line.resource_id == hollow_oak.RASPBERRIES for line in commitment.lines)
        and start <= commitment.due_at < end
    ]
    if len(today) != 1:
        raise AssertionError(
            f"{len(today)} raspberry deliveries fall in the bakery day containing "
            f"{now.astimezone(ZONE).isoformat()}; the canonical report is unanswerable"
        )
    return today[0]


def bands(now: datetime) -> dict[str, Classification]:
    """How a seed taken at ``now`` classifies every promise, read off the engine itself.

    The canonical report is performed rather than described: the fixture is built at the anchor
    a reset would choose, the delivery the words name is resolved, the raspberry-only facts are
    attested against it, and the result is whatever the engine says. Nothing here decides a
    band.
    """
    return bands_of(hollow_oak.hollow_oak(resolve_demo_anchor(now, TUNIS)), now)


def bands_of(snapshot: GraphSnapshot, now: datetime) -> dict[str, Classification]:
    """The same reading against a world that may have been seeded earlier than ``now``."""
    commitment_id = todays_raspberry_delivery(snapshot, now)
    lines = tuple(
        line.id
        for line in snapshot.commitments[commitment_id].lines
        if line.resource_id == hollow_oak.RASPBERRIES
    )
    exception = hollow_oak.raspberry_only(now).model_copy(
        update={"commitment_id": commitment_id, "scope_line_ids": lines}
    )
    settled = apply_exception_facts(snapshot, exception, now).snapshot
    return {
        promise_id: result.classification
        for promise_id, result in analyze(settled, exception, now).classifications.items()
    }


def deadlines(now: datetime) -> tuple[datetime, ...]:
    """Every customer promise's due time, for a seed taken at ``now``."""
    snapshot = hollow_oak.hollow_oak(resolve_demo_anchor(now, TUNIS))
    return tuple(promise.due_at for promise in snapshot.promises.values())


def seeds(day: datetime) -> list[datetime]:
    """Every five-minute moment of one bakery day, as the instants they really are."""
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return [(start + STEP * step).astimezone(UTC) for step in range((24 * 60) // 5)]


LATER: Final[dict[str, datetime]] = {
    "sixty days out": DAY + timedelta(days=60),
    "a year out": DAY + timedelta(days=365),
}
"""Two dates far enough from the suite's own day that a calendar dependency could not hide.

Sixty days is the distance between recording a demo and being judged on it; a year is the
distance at which anything tied to a month, a quarter or a year number has certainly moved.
"""


@pytest.mark.parametrize("when", sorted(LATER), ids=sorted(LATER))
def test_the_three_authority_bands_render_at_a_much_later_seed(when: str) -> None:
    """The product's whole claim is the *heterogeneity*, so all six promises are asserted.

    A seed that produced four blocked promises would still be a working case and a useless
    demo: the auto-repaired band and the consent band are what make this more than a workflow
    engine, and a date must not be able to take either away.
    """
    wrong = [
        moment.astimezone(ZONE).strftime("%Y-%m-%d %H:%M")
        for moment in seeds(LATER[when])
        if bands(moment) != CANONICAL_BANDS
    ]
    assert wrong == []


@pytest.mark.parametrize("when", sorted(LATER), ids=sorted(LATER))
def test_every_deadline_is_still_ahead_of_a_much_later_seed(when: str) -> None:
    """A promise due in the past reads as a missed one, whatever the case says about it."""
    past = [
        moment.astimezone(ZONE).strftime("%Y-%m-%d %H:%M")
        for moment in seeds(LATER[when])
        if any(due_at <= moment for due_at in deadlines(moment))
    ]
    assert past == []


@pytest.mark.parametrize("when", sorted(LATER), ids=sorted(LATER))
def test_a_much_later_seed_is_still_drivable_at_every_hour(when: str) -> None:
    """The midnight property is a property of the rule, not of one day in September."""
    broken = [
        moment.astimezone(ZONE).strftime("%Y-%m-%d %H:%M")
        for moment in seeds(LATER[when])
        if not drivable(moment)
    ]
    assert broken == []


@pytest.mark.parametrize("days_out", [0, 60, 365])
def test_a_seed_taken_from_the_real_clock_tells_the_same_story(days_out: int) -> None:
    """The one test here that is deliberately not hermetic.

    Every other test in this file constructs its ``now`` so that the suite answers the same at
    any hour, which is what makes it a statement about the rule. This one asks the question the
    rule exists for: is the demo, seeded *today*, the demo the product describes? A constructed
    clock cannot answer that, because a calendar dependency would be constructed away with it.
    """
    moment = datetime.now(UTC) + timedelta(days=days_out)
    assert bands(moment) == CANONICAL_BANDS
    assert all(due_at > moment for due_at in deadlines(moment))
    assert drivable(moment)


# ------------------------------------------------ how long one seed keeps telling the story


def test_a_seeded_world_stops_telling_the_story_at_the_next_bakery_midnight() -> None:
    """A seed is good for the rest of its own bakery day, and that is the whole of it.

    Nothing here is a defect to fix: a demo world is durable rows, the anchor that wrote them
    cannot follow the clock afterwards, and the rows cannot be moved under the cases that
    reference them. What this pins is the operator fact that follows, so the cost of seeding
    early is a number rather than a memory.

    The decay is worse than going quiet, which is why it is asserted rather than described.
    Today's delivery is due an hour after the anchor, so it stops being *today* at the next
    local midnight -- and what takes its place inside that day is **tomorrow's** Valley Produce
    delivery, which also carries raspberries. The reading does not stop to ask; it resolves
    confidently to a delivery no promise is waiting on, and every promise the exception does
    reach falls to ``BLOCKED``. Both bands the product exists to show -- the one it repairs by
    itself and the one it must ask about -- are gone one day after the seed. Only from the day
    after that is there no raspberry delivery left to name at all.
    """
    seeded_at = at(9, 0)
    snapshot = hollow_oak.hollow_oak(resolve_demo_anchor(seeded_at, TUNIS))

    assert todays_raspberry_delivery(snapshot, at(23, 55)) == hollow_oak.VP_TODAY
    assert bands_of(snapshot, seeded_at) == CANONICAL_BANDS

    next_day = seeded_at + timedelta(days=1)
    assert todays_raspberry_delivery(snapshot, next_day) == hollow_oak.VP_TOMORROW
    assert bands_of(snapshot, next_day) == {
        hollow_oak.PROMISE_A: Classification.BLOCKED,
        hollow_oak.PROMISE_B: Classification.BLOCKED,
        hollow_oak.PROMISE_C: Classification.BLOCKED,
        hollow_oak.PROMISE_D: Classification.BLOCKED,
        hollow_oak.PROMISE_E: Classification.UNAFFECTED,
        hollow_oak.PROMISE_F: Classification.UNAFFECTED,
    }

    with pytest.raises(AssertionError, match="unanswerable"):
        todays_raspberry_delivery(snapshot, seeded_at + timedelta(days=2))
