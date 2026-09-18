"""Arm C: PromisePatch with revalidation check 5 removed, and nothing else removed.

The contract fixes this arm down to the named check::

    Check 5 of the ten-check revalidation evaluator, 'substitute still available', implemented
    by promise_graph.revalidation._substitute_check. Nothing else.

and fixes how it is removed::

    The arm wraps promise_graph.revalidation.evaluate at the benchmark boundary. The wrapper
    calls the real evaluator unchanged, discards check 5's result from the list the outcome is
    derived from, and re-derives the outcome from the lowest-numbered remaining failing check by
    the evaluator's own published mapping. Check 5 is still reported in the result, marked
    ablated, so an audit of a run can see it was dropped rather than that it passed.

Four things follow from that text and each is implemented literally.

**The real evaluator runs, unchanged.** :func:`ablated_revalidate` calls
:func:`promise_graph.revalidation.revalidate` with the arguments it was given and edits nothing
on the way in. Checks 1--4 and 6--10 come back exactly as they came out, and
:func:`assert_only_check_five_moved` is the assertion of that rather than the claim of it.

**The mapping is imported, not restated.** ``_OUTCOME_BY_CHECK`` is the evaluator's own
published mapping from a failing check to an outcome. A copy here would be a second one, and
the first time the two disagreed the ablation would be measuring a transcription error. It is a
private name in another package and importing it is the price of not having a second copy.

**Check 5 is still reported.** ``RevalidationResult`` carries one ``checks`` tuple, which the
domain uses for two jobs: deriving the outcome, and writing the checks to the durable ledger.
The contract wants check 5 gone from the first and present in the second. So the wrapper
replaces check 5 in place with a marker that is non-decisive -- ``passed`` is what the outcome
derivation and ``result.failed[0]`` read, so a dropped check must not be in ``failed`` -- and
carries its real reading in the two fields nothing decides on. Its ``name`` says ``ABLATED`` and
its ``actual`` says whether the real check passed or failed. An audit of a run can therefore see
that check 5 was dropped, and can see what it would have said. Nothing reads ``PASSED`` for a
check that failed, because the word ``ABLATED`` is in the name that sits beside it.

**Nothing under ``packages/`` or ``apps/`` is touched.** :func:`ablation` installs the wrapper
over the name ``promisepatch.domain.revalidation.revalidate`` -- the binding the durable step
actually calls -- for the duration of one attempt, and restores it afterwards. This module lives
under ``scripts/``, which is not synced into the runtime image and is not one of import-linter's
root packages, so no deployed process can reach it.

**The ablation is recorded, not merely performed.** :class:`AblationRecord` holds the real
check-5 verdict, the outcome the real evaluator reached and the outcome the ablation reached,
for every call in an attempt. That is the audit trail the contract's ``how_it_is_removed``
sentence is asking for, and it is what a later reader uses to check that arm C differed from
arm B only where check 5 was the deciding check.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Final

from promise_graph.revalidation import (
    _OUTCOME_BY_CHECK,
    CheckResult,
    RevalidationOutcome,
    RevalidationResult,
    revalidate,
)

ABLATED_CHECK: Final = 5
ABLATED_CHECK_NAME: Final = "substitute still available"

PATCHED_NAME: Final = "revalidate"
"""The attribute rebound on ``promisepatch.domain.revalidation`` for the length of an attempt."""

ABLATED_MARK: Final = f"{ABLATED_CHECK_NAME} [ABLATED: dropped from the outcome by SUR-1 arm C]"
"""What check 5 is called in an ablated result. The word is in the name so no reader of the
durable ledger can mistake a dropped check for a passing one."""


class AblationError(RuntimeError):
    """The wrapper changed something the contract says it must not change."""


@dataclass(frozen=True, slots=True)
class AblationRecord:
    """One call to the evaluator, with what the ablation did to it."""

    check_five_really_passed: bool
    check_five_expected: str
    check_five_actual: str
    real_outcome: str
    ablated_outcome: str

    @property
    def changed_the_outcome(self) -> bool:
        return self.real_outcome != self.ablated_outcome

    def as_payload(self) -> dict[str, Any]:
        return {
            "check": ABLATED_CHECK,
            "check_name": ABLATED_CHECK_NAME,
            "check_five_really_passed": self.check_five_really_passed,
            "check_five_expected": self.check_five_expected,
            "check_five_actual": self.check_five_actual,
            "real_outcome": self.real_outcome,
            "ablated_outcome": self.ablated_outcome,
            "changed_the_outcome": self.changed_the_outcome,
        }


@dataclass(slots=True)
class AblationLog:
    """Every evaluator call one attempt made, in order. Written into the capture."""

    records: list[AblationRecord] = field(default_factory=list)

    def as_payload(self) -> list[dict[str, Any]]:
        return [record.as_payload() for record in self.records]


def _marked(real: CheckResult) -> CheckResult:
    """Check 5, present and non-decisive, carrying what it really read."""
    verdict = "PASSED" if real.passed else "FAILED"
    return CheckResult(
        index=ABLATED_CHECK,
        name=ABLATED_MARK,
        passed=True,
        expected=real.expected,
        actual=f"{verdict}(dropped): {real.actual}",
    )


def ablate(real: RevalidationResult) -> tuple[RevalidationResult, AblationRecord]:
    """Drop check 5 from the outcome derivation, keep it in the report, re-derive.

    Pure: a result in, a result and a record out. Nothing here reads a clock, a database or the
    world, which is what lets the arm's one deviation be tested without driving an arm.
    """
    checks = {check.index: check for check in real.checks}
    try:
        real_five = checks[ABLATED_CHECK]
    except KeyError:
        raise AblationError(
            f"the evaluator returned no check {ABLATED_CHECK}; this arm is defined as the "
            "removal of a check that exists"
        ) from None

    rewritten = tuple(
        _marked(check) if check.index == ABLATED_CHECK else check for check in real.checks
    )
    outcome = RevalidationOutcome.PROCEED
    for check in rewritten:
        if not check.passed:
            outcome = _OUTCOME_BY_CHECK[check.index]
            break

    record = AblationRecord(
        check_five_really_passed=real_five.passed,
        check_five_expected=real_five.expected,
        check_five_actual=real_five.actual,
        real_outcome=str(real.outcome),
        ablated_outcome=str(outcome),
    )
    result = RevalidationResult(checks=rewritten, outcome=outcome)
    assert_only_check_five_moved(real, result)
    return result, record


def assert_only_check_five_moved(real: RevalidationResult, ablated: RevalidationResult) -> None:
    """The arm's whole definition, asserted on every call rather than reviewed once.

    Checks 1--4 and 6--10 must be identical objects' worth of identical values; the check tuple
    must be the same length and in the same order; and check 5 must be present, marked, and
    absent from ``failed``. Anything else means the wrapper is doing more than the contract says
    arm C does, which would make the arm unmeasurable rather than merely wrong.
    """
    if len(real.checks) != len(ablated.checks):
        raise AblationError(
            f"the ablation returned {len(ablated.checks)} checks and the evaluator returned "
            f"{len(real.checks)}; arm C removes a check from a derivation, not from a report"
        )
    for before, after in zip(real.checks, ablated.checks, strict=True):
        if before.index != after.index:
            raise AblationError("the ablation reordered the checks")
        if before.index == ABLATED_CHECK:
            continue
        if before != after:
            raise AblationError(
                f"the ablation changed check {before.index}, {before.name!r}; arm C is defined "
                f"as the removal of check {ABLATED_CHECK} and nothing else"
            )
    five = next(check for check in ablated.checks if check.index == ABLATED_CHECK)
    if five.name != ABLATED_MARK:
        raise AblationError(f"check {ABLATED_CHECK} is not marked ablated in the reported result")
    if any(check.index == ABLATED_CHECK for check in ablated.failed):
        raise AblationError(
            f"check {ABLATED_CHECK} is still deciding the outcome, so nothing was ablated"
        )


def ablated_revalidate(log: AblationLog) -> Callable[..., RevalidationResult]:
    """The wrapper the arm installs: the real evaluator, then :func:`ablate`.

    It takes ``*args`` and ``**kwargs`` and forwards them untouched. Restating the evaluator's
    signature here would be a second copy of it, and a second copy is a place the arm could
    quietly differ from arm B by mislabelling an argument.
    """

    def wrapper(*args: Any, **kwargs: Any) -> RevalidationResult:
        real = revalidate(*args, **kwargs)
        result, record = ablate(real)
        log.records.append(record)
        return result

    return wrapper


def installed_evaluator() -> Any:
    """The callable the durable step currently resolves for the evaluator.

    Exposed so that "the wrapper is installed only while arm C is running, and is taken back out
    afterwards" is assertable rather than assumed, and so nothing has to reach into another
    module's namespace to check it.
    """
    from promisepatch.domain import revalidation as durable

    return getattr(durable, PATCHED_NAME)


@contextmanager
def ablation() -> Iterator[AblationLog]:
    """Install the wrapper for one attempt, and take it back out afterwards.

    The patched name is ``promisepatch.domain.revalidation.revalidate``: the binding the durable
    step resolves, rather than the definition in the engine, because rebinding the definition
    would change what every other importer sees. Imported inside the function so that the pure
    half of this module -- which is the half the ablation is actually defined by -- stays usable
    without the application installed.
    """
    from promisepatch.domain import revalidation as durable

    log = AblationLog()
    original = getattr(durable, PATCHED_NAME)
    setattr(durable, PATCHED_NAME, ablated_revalidate(log))
    try:
        yield log
    finally:
        setattr(durable, PATCHED_NAME, original)
