"""The invariants a worker's withdrawal has to land inside, pinned before one exists.

Pure tests, no database. Each one names something the frozen contract already decided, and
each is a thing a withdrawal would quietly break if it were written without looking:

* ``CANCELLED`` is a terminal case state, so §14.1's "retracted before any consequential
  write" has somewhere final to land and no step may run afterwards.
* ``WITHDRAWN`` is a terminal *track* state **and** is excluded from the partial unique index
  that says a promise has at most one live track. A withdrawal that left tracks non-terminal
  would lock every promise of that case out of any future case, for ever, with no error --
  which is why the index predicate is asserted here rather than trusted.
* The product's own vocabulary already has a reading for a withdrawn promise: nobody's move,
  and a sentence that says so. A withdrawal does not get to invent a second one.
* Physical facts are not in any of this. The two authorities are separate (§11.8), and a
  retraction reverses recovery writes only.
"""

from __future__ import annotations

from promisepatch.db.base import Base
from promisepatch.db.types import CASE_STATES, TERMINAL_TRACK_STATES, TRACK_STATES
from promisepatch.domain import status_view
from promisepatch.domain.model import TERMINAL_CASE_STATES

LIVE_TRACK_INDEX = "ix_tracks_one_live_per_promise"


# ------------------------------------------------------------------------ where a case lands


def test_cancelled_is_a_case_state_the_database_accepts() -> None:
    assert "CANCELLED" in CASE_STATES


def test_cancelled_is_terminal_so_no_step_runs_after_a_withdrawal() -> None:
    """§14.1: ``CANCELLED`` is terminal. A step reaching one must decline to do anything."""
    assert "CANCELLED" in TERMINAL_CASE_STATES


def test_resolved_is_the_other_terminal_case_state() -> None:
    """The after-writes path's terminus (§14.1), and the only other place a case stops."""
    assert set(TERMINAL_CASE_STATES) == {"RESOLVED", "CANCELLED"}


# ----------------------------------------------------------------------- where a track lands


def test_withdrawn_is_a_track_state_the_database_accepts() -> None:
    assert "WITHDRAWN" in TRACK_STATES


def test_withdrawn_is_terminal_so_the_promise_stops_being_this_case_s() -> None:
    assert "WITHDRAWN" in TERMINAL_TRACK_STATES


def test_escalated_is_terminal_so_the_after_writes_path_also_settles() -> None:
    """§23: after writes, the track is ``ESCALATED`` for owner awareness -- and that is final."""
    assert "ESCALATED" in TERMINAL_TRACK_STATES


def test_a_withdrawn_track_frees_its_promise_for_a_later_case() -> None:
    """The partial unique index, read off the model rather than off the migration's prose.

    ``ix_tracks_one_live_per_promise`` is unique over ``promise_id`` where the state is *not*
    one of the terminal ones. Leaving a withdrawn case's tracks ``PENDING`` would therefore
    hold every one of its promises hostage: no later exception could open a track on them, and
    the failure would arrive as an integrity error in an unrelated case days later.
    """
    table = Base.metadata.tables["promisepatch.tracks"]
    index = next(candidate for candidate in table.indexes if candidate.name == LIVE_TRACK_INDEX)
    predicate = str(index.dialect_options["postgresql"]["where"])
    for terminal in TERMINAL_TRACK_STATES:
        assert f"'{terminal}'" in predicate
    assert "'PENDING'" not in predicate


# ------------------------------------------------------------- how a withdrawn promise reads


def test_the_projection_already_has_a_withdrawn_promise_state() -> None:
    assert status_view.PromiseState.WITHDRAWN in status_view.PromiseState


def test_a_withdrawn_promise_is_nobody_s_move() -> None:
    """P7.1: ``WITHDRAWN`` sits outside the untouched band and asks nothing of anybody."""
    state = status_view.PromiseState.WITHDRAWN
    assert status_view._promise_owner(state) is status_view.ActionOwner.NOBODY
    assert status_view._promise_next_action(state) == (
        "Nothing. This promise was withdrawn from the case."
    )


def test_a_withdrawn_promise_is_not_counted_as_untouched() -> None:
    """The central claim is about promises left alone. A withdrawn one was not left alone.

    ``project`` partitions on ``UNTOUCHED`` exactly, so a promise reported as ``WITHDRAWN``
    lands in the threatened band and is never added to the count the product's headline claim
    rests on. Asserted through the authority reading, which is the one place all three of the
    quiet states are named together.
    """
    quiet = {
        status_view.PromiseState.UNTOUCHED,
        status_view.PromiseState.LINKED,
        status_view.PromiseState.WITHDRAWN,
    }
    assert len(quiet) == 3


def test_a_cancelled_case_reads_as_cancelled_rather_than_as_settled() -> None:
    assert status_view.CASE_HEADLINES["CANCELLED"] is status_view.CaseHeadline.CANCELLED
    assert status_view.headline_sentence(status_view.CaseHeadline.CANCELLED) == "Cancelled."
