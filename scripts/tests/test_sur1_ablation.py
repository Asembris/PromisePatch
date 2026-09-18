"""Arm C removes revalidation check 5 and removes nothing else.

The contract fixes this arm down to the named check, and an ablation that quietly removed a
second protection would make the comparison unreadable in the direction that flatters
PromisePatch: arm C would look worse for a reason nobody declared. So the claim is asserted
here, on every check position, rather than reviewed once.

No arm is driven, no model is reached, no database is opened and no ``SUR-1`` scenario is
executed. Every result below is built by hand from the evaluator's own types.
"""

from __future__ import annotations

import pytest
from scripts.sur1.ablation import (
    ABLATED_CHECK,
    ABLATED_MARK,
    AblationError,
    ablate,
    ablated_revalidate,
    ablation,
    assert_only_check_five_moved,
    installed_evaluator,
)
from scripts.sur1.ablation import AblationLog as Log

from promise_graph.revalidation import (
    _OUTCOME_BY_CHECK,
    CheckResult,
    RevalidationOutcome,
    RevalidationResult,
)

CHECK_NAMES = {
    1: "case is waiting",
    2: "order version unchanged",
    3: "recipe pin unchanged",
    4: "constraint snapshot unchanged",
    5: "substitute still available",
    6: "production task not started and still ahead",
    7: "approval deadline not passed",
    8: "sender is the order's approval channel",
    9: "decision came from the literal parser",
    10: "decision binds this request",
}


def result(*failing: int) -> RevalidationResult:
    """A ten-check result in which exactly the named checks failed."""
    checks = tuple(
        CheckResult(
            index=index,
            name=CHECK_NAMES[index],
            passed=index not in failing,
            expected=f"expected-{index}",
            actual=f"actual-{index}",
        )
        for index in range(1, 11)
    )
    outcome = RevalidationOutcome.PROCEED
    for check in checks:
        if not check.passed:
            outcome = _OUTCOME_BY_CHECK[check.index]
            break
    return RevalidationResult(checks=checks, outcome=outcome)


# ------------------------------------------------------------------- exactly check five


@pytest.mark.parametrize("failing", range(1, 11))
def test_only_check_five_stops_deciding_the_outcome(failing: int) -> None:
    """Every other check decides exactly what it decided before."""
    real = result(failing)
    ablated, record = ablate(real)
    if failing == ABLATED_CHECK:
        assert real.outcome is RevalidationOutcome.STALE
        assert ablated.outcome is RevalidationOutcome.PROCEED
        assert record.changed_the_outcome
    else:
        assert ablated.outcome == real.outcome
        assert not record.changed_the_outcome


def test_a_lower_failing_check_still_decides_over_an_ablated_five() -> None:
    """Checks 1 through 4 are untouched, so one of them still names the outcome."""
    ablated, _ = ablate(result(2, 5))
    assert ablated.outcome is RevalidationOutcome.STALE
    assert ablated.failed[0].index == 2


def test_the_outcome_is_re_derived_from_the_lowest_remaining_failing_check() -> None:
    """The contract's own sentence: check 5 drops out and 7 becomes the deciding check."""
    real = result(5, 7)
    assert real.outcome is RevalidationOutcome.STALE
    ablated, record = ablate(real)
    assert ablated.outcome is RevalidationOutcome.EXPIRED
    assert ablated.failed[0].index == 7
    assert record.real_outcome == str(RevalidationOutcome.STALE)
    assert record.ablated_outcome == str(RevalidationOutcome.EXPIRED)


def test_every_other_check_survives_byte_for_byte() -> None:
    real = result(5)
    ablated, _ = ablate(real)
    survivors = {check.index: check for check in ablated.checks if check.index != ABLATED_CHECK}
    originals = {check.index: check for check in real.checks if check.index != ABLATED_CHECK}
    assert survivors == originals
    assert len(ablated.checks) == len(real.checks) == 10


# ------------------------------------------------------------- dropped, and seen to be dropped


def test_check_five_is_still_reported_and_marked_ablated() -> None:
    """An audit has to see that it was dropped, not that it passed."""
    ablated, _ = ablate(result(5))
    five = next(check for check in ablated.checks if check.index == ABLATED_CHECK)
    assert five.name == ABLATED_MARK
    assert "ABLATED" in five.name
    assert five.actual.startswith("FAILED(dropped): ")
    assert "actual-5" in five.actual


def test_a_check_five_that_really_passed_says_so() -> None:
    ablated, record = ablate(result())
    five = next(check for check in ablated.checks if check.index == ABLATED_CHECK)
    assert five.actual.startswith("PASSED(dropped): ")
    assert record.check_five_really_passed


def test_a_dropped_check_never_appears_among_the_failures() -> None:
    """``result.failed[0]`` is what the durable refusal path names as the deciding check."""
    ablated, _ = ablate(result(5))
    assert ablated.failed == ()


def test_the_record_carries_what_check_five_really_read() -> None:
    _, record = ablate(result(5))
    payload = record.as_payload()
    assert payload["check"] == 5
    assert payload["check_five_really_passed"] is False
    assert payload["check_five_actual"] == "actual-5"
    assert payload["changed_the_outcome"] is True


# ------------------------------------------------------------------------ the guard itself


def test_a_second_removal_is_refused() -> None:
    """The guard is what stops the ablation quietly becoming two ablations."""
    real = result(5, 6)
    tampered = RevalidationResult(
        checks=tuple(
            check if check.index != 6 else CheckResult(6, check.name, True, "", "")
            for check in real.checks
        ),
        outcome=RevalidationOutcome.PROCEED,
    )
    with pytest.raises(AblationError, match="changed check 6"):
        assert_only_check_five_moved(real, tampered)


def test_a_result_without_check_five_is_refused() -> None:
    real = result()
    without = RevalidationResult(
        checks=tuple(check for check in real.checks if check.index != ABLATED_CHECK),
        outcome=real.outcome,
    )
    with pytest.raises(AblationError, match="no check 5"):
        ablate(without)


def test_a_reported_result_must_keep_every_check() -> None:
    real = result()
    short = RevalidationResult(checks=real.checks[:9], outcome=real.outcome)
    with pytest.raises(AblationError, match="removes a check from a derivation"):
        assert_only_check_five_moved(real, short)


# ---------------------------------------------------------------------- the wrapper and log


def test_the_wrapper_forwards_to_the_real_evaluator_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wrapper calls the evaluator unchanged and records what it did to the answer."""
    seen: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake(*args: object, **kwargs: object) -> RevalidationResult:
        seen.append((args, dict(kwargs)))
        return result(5)

    monkeypatch.setattr("scripts.sur1.ablation.revalidate", fake)
    log = Log()
    wrapper = ablated_revalidate(log)
    answer = wrapper("snapshot", "request", holding_case_id="case-1")

    assert seen == [(("snapshot", "request"), {"holding_case_id": "case-1"})]
    assert answer.outcome is RevalidationOutcome.PROCEED
    assert len(log.records) == 1
    assert log.records[0].changed_the_outcome


def test_the_arm_installs_over_the_durable_binding_and_takes_it_back_out() -> None:
    """The name patched is the one the durable step actually calls."""
    original = installed_evaluator()
    with ablation() as log:
        assert installed_evaluator() is not original
        assert log.records == []
    assert installed_evaluator() is original


def test_the_arm_restores_the_binding_even_when_the_attempt_raises() -> None:
    original = installed_evaluator()
    with pytest.raises(ValueError, match="the attempt fell over"), ablation():
        raise ValueError("the attempt fell over")
    assert installed_evaluator() is original
