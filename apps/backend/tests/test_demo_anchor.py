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
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from promise_graph.examples import hollow_oak
from promisepatch.domain.physical import bakery_day
from promisepatch.fixtures.demo import resolve_demo_anchor

TUNIS = "Africa/Tunis"
ZONE = ZoneInfo(TUNIS)
DAY = datetime(2026, 9, 14, tzinfo=ZONE)


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
