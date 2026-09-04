"""The retry ladder, as arithmetic rather than as a schedule somebody runs.

There is no timer thread and no queue behind this. A retry is ``next_attempt_at`` on the step
row, so a worker that dies mid-ladder loses nothing: the next worker's claim sweep finds the
row when the database's own clock says it is due, whether that is in five seconds or after an
hour of downtime.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

BACKOFF_LADDER: Final[tuple[timedelta, ...]] = (
    timedelta(seconds=1),
    timedelta(seconds=5),
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
)
"""1 s, 5 s, 30 s, 2 min, 10 min -- the ladder the architecture fixes."""

MAX_ATTEMPTS: Final = 5
"""How many times a step may run at all, counting the first.

The bound bites before the ladder is exhausted, which is deliberate rather than an oversight:
the architecture states both numbers, and a step that has failed five times is telling us
something a sixth attempt will not change. Raising the bound is what reaches the last rung.
"""


def backoff_after(attempts: int) -> timedelta | None:
    """How long to wait before attempt ``attempts + 1``, or ``None`` when there is not one.

    ``attempts`` is the value *after* the claim incremented it, so the first failure passes 1
    and waits a second. ``None`` means the bound has been reached and the failure is terminal:
    the caller escalates rather than scheduling a retry nothing will ever pick up.
    """
    if attempts < 1:
        raise ValueError(f"attempts must be at least 1; got {attempts}")
    if attempts >= MAX_ATTEMPTS:
        return None
    return BACKOFF_LADDER[min(attempts - 1, len(BACKOFF_LADDER) - 1)]


def is_exhausted(attempts: int) -> bool:
    """Whether this attempt was the last one the policy permits."""
    return backoff_after(attempts) is None
