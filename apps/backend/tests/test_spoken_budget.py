"""What a worker hears, and how many words of it.

G7 gives a spoken reply **40 words** and a spoken plan **70** (``new_roadmap.md``, G7;
``docs/p7.1-judge-ux-contract.md`` section 7). These tests hold
:func:`promisepatch.domain.status_view.render_spoken` to those numbers across promise counts and
every case headline, and hold it to the harder rule beside them: shortening removes *detail*,
never *certainty*. A reply that fits by claiming more than it knows is worse than one that does
not fit, so several tests here assert what the short rendering still says rather than how short
it is.

No timing is measured here and no voice turn is recorded. This is a word count over pure
functions -- no database, no transport, no clock and no provider.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from test_status_view import approval, case, pending, track

from promisepatch.domain.analysis import TrackStatus
from promisepatch.domain.status_view import (
    CASE_HEADLINES,
    CaseHeadline,
    PromiseState,
    project,
    render,
    render_clarification_receipt,
    render_confirmation_spoken,
    render_report_receipt,
    render_spoken,
)

REPLY_BUDGET: Final = 40
"""Words a spoken reply may have. G7."""

PLAN_BUDGET: Final = 70
"""Words a spoken plan may have. G7, and the only rendering that gets the larger one."""

TRACKED_STATES: Final[tuple[str, ...]] = (
    "ANALYZED",
    "PLANNED",
    "EXECUTING",
    "REVALIDATING",
    "RECONCILING",
    "WAITING",
    "RESOLVED",
    "CANCELLED",
)
"""The case states in which a promise exists at all.

Intake never reaches ``ANALYZED`` -- :mod:`promisepatch.domain.observation` says so in as many
words -- so ``RECEIVED``, ``INTERPRETING``, ``CLARIFYING`` and ``NEEDS_HUMAN_INTERPRETATION``
carry no tracks. :func:`test_a_case_before_analysis_has_no_promise_to_count` pins that, because
the budget claim below is scoped by it.
"""

NAMES: Final[tuple[str, ...]] = (
    "Tomas",
    "Lena",
    "Priya",
    "Mo",
    "Ines",
    "Karl",
    "Ada",
    "Nils",
    "Rosa",
    "Bea",
    "Cato",
    "Dov",
)


def words(text: str) -> int:
    """How the budget is counted: whitespace-separated tokens, punctuation included.

    The same count ``docs/voice-audible-surface-and-timing.md`` section 7 used, so the before and
    after numbers in ``docs/spoken-word-budget.md`` are comparable rather than two rulers.
    """
    return len(text.split())


def budget(state: str) -> int:
    return PLAN_BUDGET if CASE_HEADLINES[state] is CaseHeadline.PLANNED else REPLY_BUDGET


def threatened(
    index: int, classification: str, state: str = "PENDING", **extra: Any
) -> TrackStatus:
    return track(
        customer=NAMES[index % len(NAMES)],
        order=f"HO-1{index:03d}",
        state=state,
        classification=classification,
        reason="NOSUB_CONSTRAINT",
        **extra,
    )


def untouched(index: int) -> TrackStatus:
    return track(
        customer=NAMES[index % len(NAMES)],
        order=f"HO-1{index:03d}",
        state="UNAFFECTED",
        classification="UNAFFECTED",
        reason="SUPPLY_NOT_RECEIVED",
    )


def canonical(state: str) -> Any:
    """The frozen manifest's six-promise demo shape: four threatened across all three bands."""
    return case(
        state,
        threatened(0, "AUTO_RECOVERABLE"),
        threatened(1, "APPROVAL_REQUIRED"),
        threatened(2, "APPROVAL_REQUIRED"),
        threatened(3, "BLOCKED"),
        untouched(4),
        untouched(5),
    )


# ----------------------------------------------------------------------------- the two budgets


@pytest.mark.parametrize("state", TRACKED_STATES)
def test_the_canonical_six_promise_case_is_inside_its_budget_in_every_state(state: str) -> None:
    """The demo shape, in every state it can reach. This is the case the gate is read against."""
    spoken = render_spoken(project(canonical(state)))

    assert words(spoken) <= budget(state), f"{state}: {words(spoken)} words\n{spoken}"


@pytest.mark.parametrize("state", TRACKED_STATES)
@pytest.mark.parametrize("count", range(1, 13))
@pytest.mark.parametrize("left_alone", (0, 1, 2, 6))
def test_the_budget_holds_however_many_promises_a_case_holds(
    state: str, count: int, left_alone: int
) -> None:
    """The whole point of counting rather than naming: length stops tracking promise count.

    ``render`` spends about thirteen words per promise, so this sweep runs it past 240. The
    spoken rendering pays for *distinct postures*, of which there are three here whatever
    ``count`` is.
    """
    subject = case(
        state,
        *(
            threatened(index, ("AUTO_RECOVERABLE", "APPROVAL_REQUIRED", "BLOCKED")[index % 3])
            for index in range(count)
        ),
        *(untouched(count + offset) for offset in range(left_alone)),
    )
    spoken = render_spoken(project(subject))

    assert words(spoken) <= budget(state), f"{state} {count}+{left_alone}\n{spoken}"


@pytest.mark.parametrize("state", CASE_HEADLINES)
def test_every_case_headline_is_inside_its_budget(state: str) -> None:
    """All twelve durable states, each in the shape it is actually reachable in."""
    if state == "CLARIFYING":
        subject = case(state, question=pending())
    elif state not in TRACKED_STATES:
        subject = case(state)
    else:
        subject = canonical(state)
    spoken = render_spoken(project(subject))

    assert words(spoken) <= budget(state), f"{state}: {words(spoken)} words\n{spoken}"


def test_a_case_before_analysis_has_no_promise_to_count() -> None:
    """The scope of the budget claim above, asserted rather than assumed.

    ``CLARIFYING`` is the one that matters: its spoken form carries a question and its options,
    and a band of counted promises on top of that would not fit. It never has one, because
    propagation has not run when the question is asked.
    """
    for state in ("RECEIVED", "INTERPRETING", "CLARIFYING", "NEEDS_HUMAN_INTERPRETATION"):
        assert state not in TRACKED_STATES


@pytest.mark.parametrize(
    ("applying", "awaiting", "escalated"),
    [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1), (2, 3, 1)],
)
@pytest.mark.parametrize("already", (False, True))
def test_a_confirmation_is_inside_the_reply_budget_in_every_branch(
    applying: int, awaiting: int, escalated: int, already: bool
) -> None:
    """The long one reaches 41 in its fullest branch, which is the whole reason this one exists."""
    spoken = render_confirmation_spoken(
        applying=applying,
        awaiting_approval=awaiting,
        escalated=escalated,
        already_confirmed=already,
    )

    assert words(spoken) <= REPLY_BUDGET, spoken


def test_a_short_confirmation_still_counts_all_three_bands_and_claims_nothing_done() -> None:
    """The counts are the whole content. The last clause is the whole point."""
    spoken = render_confirmation_spoken(
        applying=2, awaiting_approval=3, escalated=1, already_confirmed=False
    )

    assert "2 orders covered by a standing preference" in spoken
    assert "3 orders where I still have to ask the customer" in spoken
    assert "1 order that need the owner" in spoken
    assert "Nothing has been changed yet." in spoken


def test_both_receipts_are_already_inside_the_reply_budget() -> None:
    """Said as a test rather than left to a reader, so a longer receipt fails here first."""
    assert words(render_report_receipt()) <= REPLY_BUDGET
    assert words(render_clarification_receipt()) <= REPLY_BUDGET


# -------------------------------------------------------- what shortening is not allowed to cost


def test_the_short_plan_still_separates_the_three_authorities() -> None:
    """The distinction the plan exists to draw. Counted, but never merged."""
    spoken = render_spoken(project(canonical("PLANNED")))

    assert "1 covered by a standing preference" in spoken
    assert "2 needs the customer" in spoken
    assert "1 needs the owner" in spoken


def test_the_short_status_keeps_planned_requested_and_recovered_apart() -> None:
    """Three different truths about three promises, and no count that rolls them together."""
    subject = case(
        "EXECUTING",
        threatened(0, "AUTO_RECOVERABLE", state="RECOVERED"),
        threatened(1, "APPROVAL_REQUIRED", state="WAITING_FOR_CUSTOMER", approval=approval()),
        threatened(
            2,
            "APPROVAL_REQUIRED",
            state="WAITING_FOR_CUSTOMER",
            approval=approval(provider_ref=None),
        ),
        untouched(3),
    )
    spoken = render_spoken(project(subject))

    assert "1 changed" in spoken
    assert "1 asked" in spoken
    assert "1 planned - waiting for you" in spoken
    assert words(spoken) <= REPLY_BUDGET, spoken


def test_the_short_status_never_loses_an_escalation() -> None:
    """One blocked promise among eleven that are fine is still said out loud."""
    subject = case(
        "EXECUTING",
        *(threatened(index, "AUTO_RECOVERABLE", state="RECOVERED") for index in range(11)),
        threatened(11, "BLOCKED", state="ESCALATED"),
    )
    spoken = render_spoken(project(subject))

    assert "1 needs you" in spoken
    assert words(spoken) <= REPLY_BUDGET, spoken


@pytest.mark.parametrize("left_alone", range(0, 7))
def test_the_untouched_claim_is_counted_in_the_short_rendering_too(left_alone: int) -> None:
    """The product's central claim survives the shortening, as a number rather than a list."""
    subject = case(
        "PLANNED",
        threatened(0, "AUTO_RECOVERABLE"),
        *(untouched(1 + offset) for offset in range(left_alone)),
    )
    spoken = render_spoken(project(subject))

    if left_alone == 0:
        assert "No promise in this case was left alone." in spoken
    elif left_alone == 1:
        assert "1 promise was left alone." in spoken
    else:
        assert f"{left_alone} promises were left alone." in spoken


def test_the_short_rendering_reads_the_open_question_out_and_its_options() -> None:
    """A worker told only that an answer is wanted would have to guess what was asked."""
    subject = case("CLARIFYING", question=pending())
    spoken = render_spoken(project(subject))

    assert "Whole delivery, or only the raspberries?" in spoken
    assert "the whole delivery" in spoken
    assert "only the raspberries" in spoken
    assert words(spoken) <= REPLY_BUDGET, spoken


def test_every_promise_phrase_a_case_can_reach_is_spoken_by_the_short_rendering() -> None:
    """No state in the vocabulary is silently unsayable once counted."""
    reachable: dict[PromiseState, tuple[str, str, Any]] = {
        PromiseState.RECOVERED: ("AUTO_RECOVERABLE", "RECOVERED", None),
        PromiseState.APPLYING: ("AUTO_RECOVERABLE", "APPLYING", None),
        PromiseState.ESCALATED: ("BLOCKED", "ESCALATED", None),
        PromiseState.STALE: ("APPROVAL_REQUIRED", "STALE", None),
        PromiseState.LINKED: ("AUTO_RECOVERABLE", "LINKED", None),
        PromiseState.WITHDRAWN: ("AUTO_RECOVERABLE", "WITHDRAWN", None),
        PromiseState.REQUESTED: ("APPROVAL_REQUIRED", "WAITING_FOR_CUSTOMER", approval()),
        PromiseState.CONSENTED: (
            "APPROVAL_REQUIRED",
            "WAITING_FOR_CUSTOMER",
            approval(decision="APPROVE"),
        ),
        PromiseState.DECLINED: (
            "APPROVAL_REQUIRED",
            "WAITING_FOR_CUSTOMER",
            approval(decision="DECLINE"),
        ),
        PromiseState.EXPIRED: (
            "APPROVAL_REQUIRED",
            "WAITING_FOR_CUSTOMER",
            approval(state="EXPIRED"),
        ),
        PromiseState.AUTHORIZED: ("AUTO_RECOVERABLE", "PENDING", None),
        PromiseState.PLANNED: ("APPROVAL_REQUIRED", "PENDING", None),
    }
    for state, (classification, track_state, pending_approval) in reachable.items():
        case_state = "PLANNED" if state is PromiseState.PLANNED else "EXECUTING"
        view = project(
            case(
                case_state,
                threatened(0, classification, state=track_state, approval=pending_approval),
            )
        )
        assert view.threatened[0].state is state, state
        spoken = render_spoken(view)
        assert view.threatened[0].phrase in spoken, state
        assert words(spoken) <= budget(case_state), f"{state}: {spoken}"


# ------------------------------------------------------------------- shorter, never cut or vague


@pytest.mark.parametrize("state", TRACKED_STATES)
def test_nothing_in_the_short_rendering_is_truncated(state: str) -> None:
    """No ellipsis, no cut word, no trailing marker. Shorter is composed, not clipped."""
    spoken = render_spoken(project(canonical(state)))

    assert "..." not in spoken
    assert "…" not in spoken
    for line in spoken.splitlines():
        assert line.endswith((".", "?")), line


def test_the_short_rendering_is_the_same_every_time() -> None:
    """Deterministic in the sense that matters: no clock, no provider, no ordering surprise."""
    subject = canonical("PLANNED")

    assert render_spoken(project(subject)) == render_spoken(project(subject))


@pytest.mark.parametrize("state", TRACKED_STATES)
def test_the_short_rendering_says_nothing_the_long_one_does_not(state: str) -> None:
    """Every state phrase it speaks is a phrase the long rendering speaks about the same case."""
    view = project(canonical(state))
    spoken, shown = render_spoken(view), render(view)

    for promise in view.threatened:
        assert promise.phrase in spoken
        assert promise.phrase in shown


@pytest.mark.parametrize("state", TRACKED_STATES)
def test_the_short_rendering_is_shorter_than_the_long_one_on_the_demo_shape(state: str) -> None:
    """The premise of this whole change, measured rather than assumed."""
    view = project(canonical(state))

    assert words(render_spoken(view)) < words(render(view))


def test_the_long_rendering_is_untouched_by_any_of_this() -> None:
    """The per-promise line is the evidence four recovery tests read. It still names people."""
    shown = render(project(canonical("PLANNED")))

    assert "Tomas (HO-1000)" in shown
    assert "Covered by a standing preference:" in shown
    assert "Needs the customer:" in shown
    assert "Needs the owner:" in shown
