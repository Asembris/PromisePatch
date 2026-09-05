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
10    ``NOOP``          this request was already decided, or its decision is not this one
===== ================= ==========================================================

Three of the checks ask something the graph alone cannot answer -- whose answer this was, whose
hold that is, and whether this answer has already been spent. Each takes an input from the
caller, and each defaults to the value that leaves its check exactly as the frozen list words it:

``sender_chain``
    The sender identity the persisted chain resolves to -- decision -> stored inbound reply ->
    the channel it arrived on. Check 8 already compares the decision's own claim about who sent
    it; this compares the record behind that claim, so a chain that was corrupted after the fact
    fails closed instead of passing on a denormalised field.

``holding_case_id``
    The case whose recovery is being revalidated. §14.3's check 6 requires the production task
    to be ``SCHEDULED`` **or held by this case** -- a task another case put on hold is a task
    somebody else's blocked promise is waiting on, and starting work on it would take a
    decision that belongs to that case's owner. A caller that supplies none keeps the plain
    reading, in which any hold passes.

``binding``
    Which decision settled this request, and whether it has already been spent. §14.3's check 10
    ("this request id has not already been decided") is enforced at the *decision-commit*
    boundary by the one-decision-per-request constraint; by the time a durable revalidation runs,
    the request is legitimately decided -- by the very decision being consumed. A caller that can
    prove which decision that was supplies a :class:`DecisionBinding`, and the check then asks the
    question that is still open: is this the one decision recorded against this request, does it
    belong to this track and this chosen option, has it been superseded, and has it already
    authorised an execution. A caller that supplies none keeps the plain reading.
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
    ProductionTask,
    TaskState,
)
from promise_graph.snapshot import GraphSnapshot

_ACCEPTABLE_ORDER_STATES = frozenset({OrderState.ACCEPTED, OrderState.AMENDED})
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
class DecisionBinding:
    """Which decision settled a request, and whether it is still spendable.

    Assembled by the caller from persisted rows, because every field of it is a fact about what
    the database holds rather than about the graph. Supplying one turns check 10 from "has this
    request been answered at all" into the question a durable workflow actually has to answer:
    *is the answer being consumed here the one and only answer this request received, does it
    still describe this track's chosen option, and has it already been spent.*
    """

    request_id: str
    """The request the persisted decision was recorded against."""

    track_id: str
    """The track that request belongs to, read back from the request rather than assumed."""

    option_id: str
    """The option the track has chosen *now*. A plan that moved makes this differ."""

    decision_count: int
    """Decisions recorded against the request. Anything but one is a broken consent record."""

    superseded: bool
    """The request was withdrawn by a re-plan (§14.4), so its answer authorises nothing."""

    consumed: bool
    """This decision has already authorised an execution. One consent, one recovery."""


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
    holding_case_id: str | None = None,
    sender_chain: str | None = None,
    binding: DecisionBinding | None = None,
) -> RevalidationResult:
    """Run all ten checks against current state and derive the outcome.

    ``holding_case_id``, ``sender_chain`` and ``binding`` are the persisted-state inputs
    described in the module docstring. All three are optional and all three default to leaving
    their check exactly as the frozen checklist words it.
    """
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
            and _task_is_ours(task, holding_case_id)
            and task.scheduled_start is not None
            and now < task.scheduled_start,
            f"SCHEDULED|HELD by {holding_case_id or 'anyone'} and start > {now.isoformat()}",
            _NONE
            if task is None
            else f"{task.state}"
            + (f" held by {task.held_by_case_id or _NONE}" if task.state is TaskState.HELD else "")
            + " and start "
            + (_NONE if task.scheduled_start is None else task.scheduled_start.isoformat()),
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
            decision is not None
            and decision.sender_identity == request.customer_channel
            and (sender_chain is None or sender_chain == request.customer_channel),
            request.customer_channel,
            _NONE
            if decision is None
            else decision.sender_identity
            + ("" if sender_chain is None else f" via {sender_chain}"),
        ),
        _check(
            9,
            "decision came from the literal parser",
            decision is not None and decision.parser is ParserKind.LITERAL,
            str(ParserKind.LITERAL),
            _NONE if decision is None else str(decision.parser),
        ),
        _binding_check(request, decision, binding),
    ]

    outcome = RevalidationOutcome.PROCEED
    for check in checks:
        if not check.passed:
            outcome = _OUTCOME_BY_CHECK[check.index]
            break
    return RevalidationResult(checks=tuple(checks), outcome=outcome)


def _task_is_ours(task: ProductionTask, holding_case_id: str | None) -> bool:
    """Check 6's state half: scheduled, or held by the case whose recovery this is.

    A hold is how §13.5 stops the kitchen starting a cake that cannot be finished, and it is
    always taken out by a particular case. One case's recovery may proceed against its own hold;
    it may not proceed against somebody else's, because releasing that would be deciding a
    blocked promise on behalf of an owner who has not looked at it yet.
    """
    if task.state is TaskState.SCHEDULED:
        return True
    if task.state is not TaskState.HELD:
        return False
    return holding_case_id is None or task.held_by_case_id == holding_case_id


def _binding_check(
    request: ApprovalRequestRecord,
    decision: ApprovalDecisionRecord | None,
    binding: DecisionBinding | None,
) -> CheckResult:
    """Check 10, in whichever of its two readings the caller has the evidence for."""
    if binding is None:
        return _check(
            10,
            "request not already decided",
            not request.decided,
            "decided=False",
            f"decided={request.decided}",
        )
    expected = (
        f"one decision for {request.id} on track {request.track_id} option {request.option_id}"
    )
    actual = (
        f"{binding.decision_count} decision(s) for {binding.request_id} "
        f"on track {binding.track_id} option {binding.option_id}"
        f"{', superseded' if binding.superseded else ''}"
        f"{', already consumed' if binding.consumed else ''}"
        f"{'' if decision is not None else ', no decision'}"
    )
    passed = (
        decision is not None
        and binding.decision_count == 1
        and binding.request_id == request.id
        and binding.track_id == request.track_id
        and binding.option_id == request.option_id
        and not binding.superseded
        and not binding.consumed
    )
    return _check(10, "one unspent decision, bound to this plan", passed, expected, actual)


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
