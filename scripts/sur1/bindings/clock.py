"""Where in time a benchmark world is installed, decided once per run and recorded.

`ADR-0019 <../../../docs/adr/0019-a-benchmark-world-is-installed-at-a-run-local-anchor.md>`_ is
the decision this module implements, and the dress rehearsal's §13 is the defect it closes.

**The problem in one sentence.** Every instant in the fixture is an offset from an anchor, and
nothing in the product reads that anchor: :func:`promisepatch.domain.physical.bakery_day` buckets
a commitment as *today* or *tomorrow* against the real clock. A world installed at the fixture's
own byte-stable anchor has both Valley Produce deliveries months in the past, both clarification
options carry the identical keywords, the scope question is never asked, and no answer resolves
the case.

**Why moving the anchor changes nothing that was declared.** World identity and world placement
were being carried by one constant and they are separable. The published identity of a starting
world is its digest, and :mod:`~scripts.sur1.bindings.worldsnapshot` renders every instant as a
whole number of seconds *from the anchor*, so the digest is invariant under it by construction.
Two runs at two anchors that publish the same nine digests started from the same nine worlds.
No frozen fact is an absolute date -- verified before this module was written.

**What is arm-blind here, and why it has to be.** The anchor is decided when the run is composed,
which is before an arm exists. Nothing in this module takes an arm, a label, a token, a budget or
a model, and nothing that fires a world event consults it. Three arms receive one world at one
instant because there is no parameter by which they could receive anything else.

**Refusal, not correction.** :func:`run_anchor` refuses when the computed anchor would put today's
delivery on a different bakery day from the run. :func:`promisepatch.fixtures.demo`'s
``resolve_demo_anchor`` nudges the demo by minutes in the same situation, and that is right for a
demo, which should always be drivable. It is wrong for a benchmark: quietly moving a stipulated
fact so a run can be taken is how a number stops being about the scenario. The operator is told to
start the run at another hour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from promise_graph.examples import hollow_oak
from scripts.sur1.bindings.setup import PreparationError

STRATEGY: Final = "run-local-bakery-anchor"
"""How a ``SUR-1`` world is placed in time. Named so a capture says which rule produced it."""

STRATEGY_VERSION: Final = "1"
"""Bumped if the rule below changes, so a run taken under one rule cannot be read as the other."""

KNOWN_STRATEGIES: Final = frozenset({STRATEGY})
"""Every clock strategy a scored run may be driven under.

A frozenset rather than a check against :data:`STRATEGY` alone, so the preflight's question is
*is this one of the declared strategies* and a future second rule is added here deliberately
rather than by a world happening to carry a string nobody recognised.
"""

FIXTURE_ANCHOR: Final = "fixture-anchor"
"""What a world with no run clock reports. Never a strategy: the scored preflight refuses it."""

SETTLED_BEFORE: Final = timedelta(hours=1)
"""How far before the run's own hour the anchor is placed.

The fixture puts today's Valley Produce delivery at anchor plus sixty minutes, so that delivery
is between nought and sixty minutes in the past when the run starts -- which is what makes the
reported exception a claim about a delivery that has already failed to arrive rather than about
one still due. Tomorrow's is at anchor plus twenty-three hours and lands on the next bakery day.
"""

DEFAULT_TIMEZONE: Final = "UTC"
"""Used only when the application's settings cannot be read at all, and it is then still checked.

Never a silent substitute for a misconfigured zone: :func:`run_anchor` asks the same question of
whatever zone it ends up with, so a harness that fell back here and disagrees with the engine is
refused by the day check rather than producing a world nobody can drive.
"""


class ClockUnusableError(PreparationError):
    """This run cannot be placed in time, and no world will be installed at a guess.

    A :class:`~scripts.sur1.bindings.setup.PreparationError` on purpose: the driver already
    records a preparation that could not complete as ``HARNESS_FAILURE`` with the reason
    recorded, which is a nonpass disclosed by name and never a ``VOID``.
    """


def bakery_timezone() -> ZoneInfo:
    """The kitchen's own calendar, read from the settings the engine reads it from.

    The same ``bakery_tz`` :func:`promisepatch.domain.physical.bakery_day` uses, out of the same
    settings object, so the harness cannot disagree with the engine about which day it is. A zone
    typed here would be a second copy of a deployment's configuration and would be wrong the first
    time a deployment moved.

    Imported inside the call for this package's standing reason: the preflight and the tests
    import this module, and reading a constant should not construct an application settings
    object at import time.
    """
    try:
        from promisepatch.config import get_settings

        name = get_settings().bakery_tz
    except Exception:  # pragma: no cover - no application settings on this machine
        name = DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):  # pragma: no cover - configuration error
        return ZoneInfo(DEFAULT_TIMEZONE)


def delivery_offsets() -> tuple[timedelta, timedelta]:
    """How far after the anchor the fixture's two Valley Produce deliveries fall.

    Measured off the dataset rather than written down, so a fixture that moved a delivery moves
    this check with it instead of leaving a stale duration in a harness nobody re-reads.
    """
    commitments = hollow_oak.hollow_oak(hollow_oak.ANCHOR).commitments
    return (
        commitments[hollow_oak.VP_TODAY].due_at - hollow_oak.ANCHOR,
        commitments[hollow_oak.VP_TOMORROW].due_at - hollow_oak.ANCHOR,
    )


def run_anchor(now: datetime, *, zone: ZoneInfo | None = None) -> datetime:
    """The instant a run installs its worlds from, or a refusal naming why it cannot.

    The hour before the current one, floored, in UTC. Two facts have to hold for a scenario to be
    legible at all, and both are checked against the bakery's own calendar day rather than
    against UTC, because that is the calendar the engine buckets a commitment in:

    * **today's delivery is today** -- otherwise there is no delivery for the report to be about,
      the ``today`` narrowing selects nothing, and both commitments survive as candidates;
    * **tomorrow's delivery is not** -- otherwise two candidates both fall inside the day, the
      commitment question is asked with two options carrying the same words, and no answer
      resolves it.
    """
    zone = zone if zone is not None else bakery_timezone()
    anchor = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0) - SETTLED_BEFORE
    today_after, tomorrow_after = delivery_offsets()
    run_day = now.astimezone(zone).date()
    today_day = (anchor + today_after).astimezone(zone).date()
    tomorrow_day = (anchor + tomorrow_after).astimezone(zone).date()

    if today_day != run_day:
        raise ClockUnusableError(
            f"today's delivery would fall on {today_day} and the run is on {run_day} in {zone}. "
            "The engine buckets a commitment by the bakery's own calendar day, so a world "
            "installed here has no delivery today for the report to be about. Start the run at "
            "another hour; the world is not moved to make one fit."
        )
    if tomorrow_day == run_day:
        raise ClockUnusableError(
            f"both Valley Produce deliveries would fall on {run_day} in {zone}. The clarification "
            "would offer two options carrying the same words and no answer could resolve it. "
            "Start the run at another hour; the world is not moved to make one fit."
        )
    return anchor


@dataclass(frozen=True, slots=True)
class RunClock:
    """One run's placement in time: which rule chose it, what it chose, and in whose calendar.

    Built once per run, carried on the world, and written into ``run.json``. Frozen because an
    anchor that could be reassigned after an attempt had been driven would make the recorded one
    a description of the last attempt rather than of the run.
    """

    anchor: datetime
    timezone: str
    strategy: str = STRATEGY
    version: str = STRATEGY_VERSION

    @property
    def declared(self) -> bool:
        """Whether a scored run may be driven under this clock at all."""
        return self.strategy in KNOWN_STRATEGIES

    def describes(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "strategy_version": self.version,
            "anchor": self.anchor.astimezone(UTC).isoformat(),
            "bakery_timezone": self.timezone,
        }


def run_clock(now: datetime | None = None) -> RunClock:
    """This run's clock, decided once. The only way a ``SUR-1`` world is placed in time.

    Called from :func:`scripts.sur1.run.build`, which is where a run is composed -- before the
    preflight, before an arm is constructed and before a world is prepared.
    """
    zone = bakery_timezone()
    return RunClock(anchor=run_anchor(now or datetime.now(UTC), zone=zone), timezone=str(zone))


def strategy_of(clock: RunClock | None) -> str:
    """What a world reports as its clock, including when it has none.

    A world carrying no clock is at the fixture's own anchor, which is correct for a unit test
    and refused for a scored run. It is reported by name rather than as an absence so a capture
    and a fingerprint both say which it was.
    """
    return FIXTURE_ANCHOR if clock is None else clock.strategy


__all__ = [
    "DEFAULT_TIMEZONE",
    "FIXTURE_ANCHOR",
    "KNOWN_STRATEGIES",
    "SETTLED_BEFORE",
    "STRATEGY",
    "STRATEGY_VERSION",
    "ClockUnusableError",
    "RunClock",
    "bakery_timezone",
    "delivery_offsets",
    "run_anchor",
    "run_clock",
    "strategy_of",
]
