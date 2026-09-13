"""The binding between the shipped example dataset and this deployment's demo state.

Everything bakery-specific — ids, names, quantities, due times, policies, who authored what —
lives in ``promise_graph.examples.hollow_oak`` and is referenced from here by name. Nothing is
restated. If a value in this module looked like a bakery fact, it would be a second copy of one,
and the demo would eventually disagree with the engine tests that assert the same numbers.

What *is* decided here is deployment-shaped: which shipped fixture the demo loads, and which
people the demo needs a login for. The two staff members are the fixture's own attesting worker
and its own recipe author, so even their identities are read off the dataset rather than typed
in again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from promise_graph.examples import hollow_oak
from promise_graph.snapshot import GraphSnapshot
from promisepatch.fixtures.projection import StaffSeed

FIXTURE_NAME: Final = "hollow-oak"
"""Recorded on ``fixture_state`` so an operator can see which dataset is loaded."""

BAKER_ROLE: Final = "baker"
OWNER_ROLE: Final = "owner"
OBSERVER_ROLE: Final = "observer"

STAFF: Final[tuple[StaffSeed, ...]] = (
    StaffSeed(
        worker_id=hollow_oak.BAKER,
        username=hollow_oak.BAKER,
        display_name=hollow_oak.BAKER.capitalize(),
        role=BAKER_ROLE,
    ),
    StaffSeed(
        worker_id=hollow_oak.AUTHOR,
        username=hollow_oak.AUTHOR,
        display_name=hollow_oak.AUTHOR.capitalize(),
        role=OWNER_ROLE,
    ),
)
"""The two seeded logins: the worker who attests physical facts, and the owner who escalates.

Their ids are the same strings the fixture already attributes attestations and authorship to,
which is what makes an audit row naming an actor resolve to a row in ``workers``.

Only these two have a password. The observer below is deliberately not one of them.
"""

OBSERVER_ID: Final = "judge"
"""The principal a scoped demo session names. It is shown cases and may change nothing."""

OBSERVER: Final = StaffSeed(
    worker_id=OBSERVER_ID,
    username=OBSERVER_ID,
    display_name="Observer",
    role=OBSERVER_ROLE,
)
"""A worker row that exists so a read has somebody to be attributed to, and nothing else.

Not part of :data:`STAFF`, because staff is the set of people this deployment issues passwords
for and this one has none. It is seeded with :data:`UNUSABLE_PASSWORD_HASH`, so the sign-in
endpoint cannot admit it however carefully somebody guesses; the only way to hold this identity
is a session the server chose to issue.
"""

UNUSABLE_PASSWORD_HASH: Final = "!"
"""A stored value that is not an Argon2 hash, and therefore verifies against nothing.

``promisepatch.api.auth.passwords.verify`` answers ``False`` for a stored hash the library
cannot parse, which makes "no password at all" expressible in a ``NOT NULL`` column without
inventing a password nobody holds. A random hash would also be unusable in practice; this one is
unusable by construction, and says so to anybody reading the row.
"""

SEEDED_WORKERS: Final[tuple[StaffSeed, ...]] = (*STAFF, OBSERVER)
"""Every ``workers`` row a reset installs: the two logins, and the observer that is not one."""


def build_snapshot(anchor: datetime) -> GraphSnapshot:
    """The demo graph, with every instant measured from ``anchor``."""
    return hollow_oak.hollow_oak(anchor)


def _delivery_offsets() -> tuple[timedelta, timedelta]:
    """How far after the anchor the fixture's two Valley Produce deliveries fall.

    Measured off the dataset rather than written down, for this module's standing reason: a
    duration typed here would be a second copy of a bakery fact, and it would go stale the
    first time the fixture moved a delivery.
    """
    commitments = hollow_oak.hollow_oak(hollow_oak.ANCHOR).commitments
    return (
        commitments[hollow_oak.VP_TODAY].due_at - hollow_oak.ANCHOR,
        commitments[hollow_oak.VP_TOMORROW].due_at - hollow_oak.ANCHOR,
    )


def resolve_demo_anchor(now: datetime, timezone: str) -> datetime:
    """The instant to load the demo at: ``now``, unless ``now`` would break the fixture.

    The fixture states its two Valley Produce deliveries as offsets from the anchor — one an
    hour after it, one twenty-three hours after it — and the whole canonical scenario rests on
    those landing on *different* bakery days, because the clarifying question the case asks is
    "the whole delivery, or just the raspberries?" about **today's** one.

    Which day an instant belongs to is the kitchen's calendar day, and it is read from the real
    clock rather than from the anchor (:func:`promisepatch.domain.physical.bakery_day`). So an
    anchor too close to local midnight collapses the distinction, in one of two ways:

    * **within an hour of midnight**, tomorrow's delivery is still today, and the interpreter
      cannot tell which delivery "today's" names — it asks which commitment is meant, and every
      option carries the same words, so no answer resolves it;
    * **within an hour of the day ending**, today's delivery has moved into tomorrow, and there
      is no delivery today for the report to be about at all.

    Both leave a case stuck in ``CLARIFYING`` with nothing a worker can say to move it. The
    window is narrow and it is real: it is two hours out of every twenty-four, and it is why a
    reset run late at night produces a demo nobody can drive.

    So an omitted anchor is ``now`` for the twenty-two hours where ``now`` works, and the
    nearest instant that works for the two where it does not. The correction is minutes rather
    than hours — the fixture's geometry relative to the anchor is preserved, which is the whole
    reason it is anchored on ``now`` in the first place.
    """
    today_after, tomorrow_after = _delivery_offsets()
    day = timedelta(days=1)
    # Tomorrow's delivery must clear midnight; today's must not reach it.
    earliest, latest = day - tomorrow_after, day - today_after

    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):  # pragma: no cover - configuration error
        return now
    local = now.astimezone(zone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    since_midnight = local - midnight
    if earliest <= since_midnight < latest:
        return now

    # A minute inside the late edge rather than on it, because the boundary itself is the
    # first instant that fails.
    target = earliest if since_midnight < earliest else latest - timedelta(minutes=1)
    return (midnight + target).astimezone(UTC)
