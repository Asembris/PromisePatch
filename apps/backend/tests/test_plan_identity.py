"""What a plan identity has to be, for a worker's yes to mean the plan they read.

Pure tests over a pure function. The property being pinned is narrow and load-bearing: two
plans are the same identity exactly when the things a worker was shown are the same, and a
different identity the moment any of them moves. Everything else about a confirmation --
who may give it, when it is accepted, what it enqueues -- is somebody else's test.
"""

from __future__ import annotations

from promisepatch.domain.plan_identity import PlanEntry, plan_id

CASE = "11111111-1111-4111-8111-111111111111"


def entry(
    track: str = "aaaaaaaa-0000-4000-8000-000000000001",
    *,
    state: str = "PENDING",
    classification: str | None = "AUTO_RECOVERABLE",
    option: str | None = "bbbbbbbb-0000-4000-8000-000000000001",
    version: str | None = "RV-SUB-STRAWBERRY",
    fingerprint: str | None = "f0",
) -> PlanEntry:
    return PlanEntry(
        track_id=track,
        track_state=state,
        classification=classification,
        chosen_option_id=option,
        to_version_id=version,
        fingerprint=fingerprint,
    )


def identity(*entries: PlanEntry, version: int = 4) -> str:
    return plan_id(case_id=CASE, case_version=version, entries=entries)


# ------------------------------------------------------------------- the same plan is the same


def test_the_same_plan_read_twice_is_the_same_identity() -> None:
    assert identity(entry()) == identity(entry())


def test_the_order_the_tracks_were_read_in_does_not_change_the_identity() -> None:
    """The read service orders by priority; the confirming scan orders by id.

    A plan whose identity depended on the ``ORDER BY`` of whichever query produced it would be
    a plan nobody could confirm -- the two would disagree on every case with two tracks.
    """
    first = entry("aaaaaaaa-0000-4000-8000-000000000001")
    second = entry("aaaaaaaa-0000-4000-8000-000000000002", classification="BLOCKED")
    assert identity(first, second) == identity(second, first)


def test_a_plan_with_no_tracks_still_has_an_identity() -> None:
    """A case that threatens nothing is still a plan somebody can be shown and say yes to."""
    assert identity() != ""
    assert identity() == identity()


# --------------------------------------------------------------- a changed plan is a new plan


def test_re_planning_a_track_changes_the_identity() -> None:
    """Revalidation refusing and a re-plan is the staleness case, in one assertion."""
    assert identity(entry(version="RV-SUB-STRAWBERRY")) != identity(entry(version="RV-SUB-CHERRY"))


def test_a_track_changing_posture_changes_the_identity() -> None:
    assert identity(entry(state="PENDING")) != identity(entry(state="STALE"))


def test_a_track_changing_authority_changes_the_identity() -> None:
    """Band 3 is the thing a worker is agreeing to: who decides each promise.

    A track that moved from "covered by a standing preference" to "needs the customer" is a
    materially different agreement even though the promise and the option are unchanged.
    """
    assert identity(entry(classification="AUTO_RECOVERABLE")) != identity(
        entry(classification="APPROVAL_REQUIRED")
    )


def test_a_different_chosen_option_changes_the_identity() -> None:
    assert identity(entry(option="bbbbbbbb-0000-4000-8000-000000000001")) != identity(
        entry(option="bbbbbbbb-0000-4000-8000-000000000002")
    )


def test_the_world_moving_under_a_track_changes_the_identity() -> None:
    """The fingerprint is what planning watches, so it belongs in what a yes is bound to."""
    assert identity(entry(fingerprint="f0")) != identity(entry(fingerprint="f1"))


def test_a_promise_joining_the_case_changes_the_identity() -> None:
    """Including untouched tracks is the point: "these are left alone" is part of the plan."""
    only = entry("aaaaaaaa-0000-4000-8000-000000000001")
    also = entry(
        "aaaaaaaa-0000-4000-8000-000000000002",
        state="UNAFFECTED",
        classification=None,
        option=None,
        version=None,
    )
    assert identity(only) != identity(only, also)


def test_the_case_moving_at_all_changes_the_identity() -> None:
    """The case version bumps on every consequential execution, so it fails closed.

    A confirmation is refused after *any* committed change to the case, not only after one
    this digest would otherwise have noticed. Re-reading the status is cheap; authorising a
    plan somebody has not seen is not.
    """
    assert identity(entry(), version=4) != identity(entry(), version=5)


def test_two_cases_holding_identical_plans_are_not_one_plan() -> None:
    mine = plan_id(case_id=CASE, case_version=1, entries=[entry()])
    theirs = plan_id(
        case_id="22222222-2222-4222-8222-222222222222", case_version=1, entries=[entry()]
    )
    assert mine != theirs


# --------------------------------------------------------------------------------- the shape


def test_the_identity_is_opaque_and_carries_nothing_it_was_made_of() -> None:
    """A caller can quote it and cannot read anything out of it or build one to order."""
    value = identity(entry())
    assert len(value) == 64
    assert set(value) <= set("0123456789abcdef")
    assert CASE not in value
    assert "RV-SUB-STRAWBERRY" not in value
