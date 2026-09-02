"""The ten-check revalidation evaluator (spec §14.3), as a pure function.

Every check is always evaluated and reported with the values it compared, because the Audit
screen shows all ten. The *outcome* is the mapping of the lowest-numbered failing check, so a
multi-failure case is deterministic:

===== ================= ==========================================================
check failure outcome   meaning
===== ================= ==========================================================
1     ``NOOP``          the track or case is not waiting
2-6   ``STALE``         the world moved; re-plan
7     ``EXPIRED``       the approval window closed
8     ``UNAUTHORIZED``  the reply did not come from the order's approval channel
9     ``NOOP``          not produced by the literal parser (unreachable by construction)
10    ``NOOP``          this request was already decided
===== ================= ==========================================================
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from promise_graph.availability import Claim, allocate
from promise_graph.fingerprint import constraint_hash
from promise_graph.model import (
    ApprovalDecisionRecord,
    ApprovalRequestRecord,
    OrderState,
    ParserKind,
    TaskState,
)
from promise_graph.snapshot import GraphSnapshot

_ACCEPTABLE_ORDER_STATES = frozenset({OrderState.ACCEPTED, OrderState.AMENDED})
_ACCEPTABLE_TASK_STATES = frozenset({TaskState.SCHEDULED, TaskState.HELD})
_NONE = "<none>"


class RevalidationOutcome(StrEnum):
    PROCEED = "PROCEED"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOOP = "NOOP"


_OUTCOME_BY_CHECK: dict[int, RevalidationOutcome] = {
    1: RevalidationOutcome.NOOP,
    2: RevalidationOutcome.STALE,
    3: RevalidationOutcome.STALE,
    4: RevalidationOutcome.STALE,
    5: RevalidationOutcome.STALE,
    6: RevalidationOutcome.STALE,
    7: RevalidationOutcome.EXPIRED,
    8: RevalidationOutcome.UNAUTHORIZED,
    9: RevalidationOutcome.NOOP,
    10: RevalidationOutcome.NOOP,
}


@dataclass(frozen=True)
class CheckResult:
    index: int
    name: str
    passed: bool
    expected: str
    actual: str


@dataclass(frozen=True)
class RevalidationResult:
    checks: tuple[CheckResult, ...]
    outcome: RevalidationOutcome

    @property
    def failed(self) -> tuple[CheckResult, ...]:
        return tuple(check for check in self.checks if not check.passed)


def revalidate(
    snapshot: GraphSnapshot,
    request: ApprovalRequestRecord,
    decision: ApprovalDecisionRecord | None,
    now: datetime,
    *,
    track_is_waiting_for_customer: bool,
    case_is_waiting: bool,
    recovered_claims: Sequence[Claim] = (),
) -> RevalidationResult:
    """Run all ten checks against current state and derive the outcome."""
    order = snapshot.orders.get(request.order_id)
    order_line = snapshot.order_lines.get(request.order_line_id)
    task = None if order_line is None else snapshot.task_of_line(order_line.id)

    checks: list[CheckResult] = [
        _check(
            1,
            "track and case are waiting",
            track_is_waiting_for_customer and case_is_waiting,
            "track=WAITING_FOR_CUSTOMER case=WAITING",
            f"track={'WAITING_FOR_CUSTOMER' if track_is_waiting_for_customer else 'OTHER'} "
            f"case={'WAITING' if case_is_waiting else 'OTHER'}",
        ),
        _check(
            2,
            "order state and version unchanged",
            order is not None
            and order.state in _ACCEPTABLE_ORDER_STATES
            and order.external_version == request.captured_order_version,
            f"ACCEPTED|AMENDED @ v{request.captured_order_version}",
            _NONE if order is None else f"{order.state} @ v{order.external_version}",
        ),
        _check(
            3,
            "pinned recipe version unchanged",
            order_line is not None
            and order_line.recipe_version_id == request.captured_recipe_version_id,
            request.captured_recipe_version_id,
            _NONE if order_line is None else order_line.recipe_version_id,
        ),
        _check(
            4,
            "constraint snapshot unchanged",
            order is not None
            and constraint_hash(snapshot, request.order_id) == request.captured_constraint_hash,
            request.captured_constraint_hash,
            _NONE if order is None else constraint_hash(snapshot, request.order_id),
        ),
        _substitute_check(snapshot, request, now, recovered_claims),
        _check(
            6,
            "production task not started and still ahead",
            task is not None
            and task.state in _ACCEPTABLE_TASK_STATES
            and task.scheduled_start is not None
            and now < task.scheduled_start,
            f"SCHEDULED|HELD and start > {now.isoformat()}",
            _NONE
            if task is None
            else f"{task.state} and start "
            f"{_NONE if task.scheduled_start is None else task.scheduled_start.isoformat()}",
        ),
        _check(
            7,
            "approval deadline not passed",
            now <= request.deadline,
            f"now <= {request.deadline.isoformat()}",
            now.isoformat(),
        ),
        _check(
            8,
            "sender is the order's approval channel",
            decision is not None and decision.sender_identity == request.customer_channel,
            request.customer_channel,
            _NONE if decision is None else decision.sender_identity,
        ),
        _check(
            9,
            "decision came from the literal parser",
            decision is not None and decision.parser is ParserKind.LITERAL,
            str(ParserKind.LITERAL),
            _NONE if decision is None else str(decision.parser),
        ),
        _check(
            10,
            "request not already decided",
            not request.decided,
            "decided=False",
            f"decided={request.decided}",
        ),
    ]

    outcome = RevalidationOutcome.PROCEED
    for check in checks:
        if not check.passed:
            outcome = _OUTCOME_BY_CHECK[check.index]
            break
    return RevalidationResult(checks=tuple(checks), outcome=outcome)


def _substitute_check(
    snapshot: GraphSnapshot,
    request: ApprovalRequestRecord,
    now: datetime,
    recovered_claims: Sequence[Claim],
) -> CheckResult:
    """Check 5: is the substitute still available after tracks that already recovered?"""
    resource_id = request.substitute_resource_id
    required = request.required_substitute_quantity
    if resource_id is None or required is None:
        return _check(5, "substitute still available", True, "not applicable", "not applicable")

    task = snapshot.task_of_line(request.order_line_id)
    start = None if task is None else task.scheduled_start
    if start is None:
        return _check(5, "substitute still available", False, f">= {required}", _NONE)

    claim = Claim(
        id=f"revalidate:{request.id}",
        resource_id=resource_id,
        quantity=required,
        start=start,
        order_external_id=snapshot.order_of_line(request.order_line_id).external_id,
        order_line_id=request.order_line_id,
        is_candidate=True,
    )
    result = allocate(snapshot, resource_id, now, extra_claims=(*recovered_claims, claim))
    allocation = result.for_claim(claim.id)
    available: Decimal | None = None if allocation is None else allocation.available_before_start
    return _check(
        5,
        "substitute still available",
        not result.unknown and allocation is not None and allocation.satisfied,
        f">= {required}",
        _NONE if available is None else str(available),
    )


def _check(index: int, name: str, passed: bool, expected: str, actual: str) -> CheckResult:
    return CheckResult(index=index, name=name, passed=passed, expected=expected, actual=actual)
