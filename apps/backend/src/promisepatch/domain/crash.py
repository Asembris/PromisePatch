"""Deterministic process death, at named persistence boundaries.

A durable workflow's guarantees are all claims about what happens when a process stops
existing at the worst possible moment. Those moments are not reachable by ordinary error
injection, because ordinary errors are *handled* -- a retryable failure schedules a retry, and
the thing being tested is what happens when nothing gets to schedule anything.

So this raises :class:`WorkerDied`, which inherits :class:`BaseException`. Every ``except
Exception`` in the worker lets it through, the transaction it was inside rolls back, and the
test observes exactly what a ``SIGKILL`` between two statements would have left behind.

**No hook is installed unless something installs one.** :func:`at` is a dictionary lookup on an
empty dictionary in every process that has not called :func:`arm`, and nothing reads the
environment: there is no fault-injection setting, because nothing in production would consume
one. The mechanism is internal, the boundaries are named constants, and arming one is
something a test does to a worker it owns.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Final

BEFORE_CLAIM: Final = "before_claim"
AFTER_CLAIM_COMMIT: Final = "after_claim_commit"
BEFORE_CONFIRMATION_COMMIT: Final = "before_confirmation_commit"
AFTER_CONFIRMATION_COMMIT: Final = "after_confirmation_commit"
DURING_HANDLER: Final = "during_handler"
BEFORE_TRANSITION_COMMIT: Final = "before_transition_commit"
AFTER_TRANSITION_COMMIT: Final = "after_transition_commit"
DURING_RETRY_BOOKKEEPING: Final = "during_retry_bookkeeping"
TIMER_ARMED: Final = "timer_armed"
BEFORE_TIMER_COMMIT: Final = "before_timer_commit"
AFTER_OUTBOX_CLAIM: Final = "after_outbox_claim"
AFTER_EXTERNAL_SUCCESS: Final = "after_external_success"
DURING_INBOX_PROCESSING: Final = "during_inbox_processing"
"""The boundaries a worker can be killed at.

Each one is a point where the durable state on either side differs, so each is a distinct
recovery story: a claim that committed but whose work never ran, a transition that ran but
never committed, an external call the provider accepted but that we never recorded.
"""

ALL_BOUNDARIES: Final[tuple[str, ...]] = (
    BEFORE_CLAIM,
    AFTER_CLAIM_COMMIT,
    BEFORE_CONFIRMATION_COMMIT,
    AFTER_CONFIRMATION_COMMIT,
    DURING_HANDLER,
    BEFORE_TRANSITION_COMMIT,
    AFTER_TRANSITION_COMMIT,
    DURING_RETRY_BOOKKEEPING,
    TIMER_ARMED,
    BEFORE_TIMER_COMMIT,
    AFTER_OUTBOX_CLAIM,
    AFTER_EXTERNAL_SUCCESS,
    DURING_INBOX_PROCESSING,
)


class WorkerDied(BaseException):
    """The process is gone. Not an error to handle -- an absence to recover from.

    Deriving from :class:`BaseException` rather than :class:`Exception` is the entire point: a
    worker that caught this and marked the step failed would be proving that its error handling
    works, when the property under test is what survives its error handling never running.
    """

    def __init__(self, boundary: str) -> None:
        super().__init__(f"worker died at {boundary}")
        self.boundary = boundary


_HOOKS: Final[dict[str, Callable[[], None]]] = {}


def at(boundary: str) -> None:
    """Run whatever is armed at ``boundary``. Nothing, in every ordinary process."""
    hook = _HOOKS.get(boundary)
    if hook is not None:
        hook()


@contextmanager
def arm(boundary: str, action: Callable[[], None] | None = None) -> Iterator[None]:
    """Install a hook for the duration of the block, and remove it afterwards.

    Defaults to killing the worker, because that is what almost every caller wants. The hook is
    removed on the way out whether the block returned or raised, so one test's armed boundary
    can never leak into the next.
    """
    if boundary not in ALL_BOUNDARIES:
        raise ValueError(f"unknown crash boundary {boundary!r}")

    def die() -> None:
        raise WorkerDied(boundary)

    previous = _HOOKS.get(boundary)
    _HOOKS[boundary] = action or die
    try:
        yield
    finally:
        if previous is None:
            _HOOKS.pop(boundary, None)
        else:
            _HOOKS[boundary] = previous


def clear() -> None:
    """Disarm everything. For a test fixture's teardown, never for production code."""
    _HOOKS.clear()
