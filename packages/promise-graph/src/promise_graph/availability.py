"""Temporal availability, deterministic allocation, and commitment settlement.

This module owns the invariant that a physical quantity has exactly one home (ADR-0014):

* A commitment line is **open** (``EXPECTED``) or **settled** (``RECEIVED`` / ``SHORT`` /
  ``NOT_RECEIVED``).
* Settling a line posts its physical outcome to the ledger **once** and removes the line from
  expected supply **forever**, in every settled state.
* ``RECEIVED`` posts ``+qty``; ``SHORT(q)`` posts ``+q``; ``NOT_RECEIVED`` posts nothing. The
  shortfall of a SHORT line is lost supply, not still-expected supply.

The engine never persists anything. :func:`apply_exception_facts` returns the *intended*
ledger postings and line settlements as data, alongside the transformed snapshot, so the same
pure function serves both the hypothetical clarification pass (discard the result) and the
attested pass (persist the postings).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from promise_graph.model import (
    CommitmentLine,
    EquipmentOutage,
    ExceptionCategory,
    InventoryLedgerEntry,
    LedgerSourceKind,
    OrderLineId,
    PhysicalException,
    ReceivedState,
    ResourceId,
    TaskState,
)
from promise_graph.snapshot import GraphSnapshot, LineSettlement

ZERO = Decimal("0.000")

_CONSUMING_TASK_STATES = frozenset({TaskState.SCHEDULED, TaskState.STARTED, TaskState.HELD})
"""A ``DONE`` task has already consumed its resources through the ledger."""


# --------------------------------------------------------------------------- views


@dataclass(frozen=True)
class AvailabilityView:
    """The four quantities the Evidence screen shows next to every affected line."""

    resource_id: ResourceId
    at: datetime
    on_hand: Decimal | None
    expected: Decimal | None
    reserved: Decimal | None
    available_by: Decimal | None
    overdue_line_ids: tuple[str, ...]
    as_of: int

    @property
    def unknown(self) -> bool:
        return self.available_by is None


@dataclass(frozen=True)
class Claim:
    """A demand on a resource: an existing reservation, or a candidate being validated."""

    id: str
    resource_id: ResourceId
    quantity: Decimal | None
    start: datetime | None
    order_external_id: str
    order_line_id: OrderLineId | None = None
    is_candidate: bool = False


@dataclass(frozen=True)
class Allocation:
    claim_id: str
    order_line_id: OrderLineId | None
    need: Decimal
    start: datetime
    available_before_start: Decimal
    take: Decimal
    satisfied: bool

    @property
    def shortfall(self) -> Decimal:
        return self.need - self.take


@dataclass(frozen=True)
class AllocationResult:
    resource_id: ResourceId
    unknown: bool
    allocations: tuple[Allocation, ...]

    def for_claim(self, claim_id: str) -> Allocation | None:
        for allocation in self.allocations:
            if allocation.claim_id == claim_id:
                return allocation
        return None


@dataclass(frozen=True)
class LedgerPosting:
    """An intended, exactly-once physical posting. Persistence is the caller's job."""

    resource_id: ResourceId
    delta: Decimal | None
    source_kind: LedgerSourceKind
    source_id: str


@dataclass(frozen=True)
class SettlementResult:
    snapshot: GraphSnapshot
    postings: tuple[LedgerPosting, ...]
    settlements: tuple[LineSettlement, ...]
    outage: EquipmentOutage | None = None


# --------------------------------------------------------------------------- quantities


def on_hand(snapshot: GraphSnapshot, resource_id: ResourceId) -> Decimal | None:
    """Physical quantity now: the sum of the append-only ledger. ``None`` if any delta is."""
    total = ZERO
    for entry in snapshot.ledger_by_resource.get(resource_id, ()):
        if entry.delta is None:
            return None
        total += entry.delta
    return total


def open_commitment_lines(
    snapshot: GraphSnapshot, resource_id: ResourceId
) -> tuple[CommitmentLine, ...]:
    """Lines still ``EXPECTED`` for this resource, ordered by their commitment's due time."""
    lines = [
        snapshot.commitment_lines[line_id]
        for line_id in snapshot.commitment_lines_by_resource.get(resource_id, ())
        if snapshot.commitment_lines[line_id].received_state is ReceivedState.EXPECTED
    ]
    return tuple(sorted(lines, key=lambda line: (_due_at(snapshot, line), line.id)))


def overdue_commitment_line_ids(
    snapshot: GraphSnapshot, resource_id: ResourceId, now: datetime
) -> tuple[str, ...]:
    """Open lines whose due time has passed. They contribute zero and are flagged."""
    return tuple(
        line.id
        for line in open_commitment_lines(snapshot, resource_id)
        if _due_at(snapshot, line) < now
    )


def expected(
    snapshot: GraphSnapshot, resource_id: ResourceId, at: datetime, now: datetime
) -> Decimal | None:
    """Supply still to arrive by ``at``.

    Settled lines contribute exactly zero in every settled state, because their physical
    outcome is already in ``on_hand``. Overdue open lines contribute zero as well.
    """
    total = ZERO
    for line in open_commitment_lines(snapshot, resource_id):
        due_at = _due_at(snapshot, line)
        if due_at < now or due_at > at:
            continue
        if line.quantity is None:
            return None
        total += line.quantity
    return total


def reserved(snapshot: GraphSnapshot, resource_id: ResourceId, upto: datetime) -> Decimal | None:
    """Claims on this resource whose production task starts at or before ``upto``."""
    total = ZERO
    for claim in _reservation_claims(snapshot, resource_id):
        if claim.start is None or claim.quantity is None:
            return None
        if claim.start <= upto:
            total += claim.quantity
    return total


def supply(
    snapshot: GraphSnapshot, resource_id: ResourceId, at: datetime, now: datetime
) -> Decimal | None:
    current = on_hand(snapshot, resource_id)
    incoming = expected(snapshot, resource_id, at, now)
    if current is None or incoming is None:
        return None
    return current + incoming


def available_by(
    snapshot: GraphSnapshot, resource_id: ResourceId, at: datetime, now: datetime
) -> AvailabilityView:
    current = on_hand(snapshot, resource_id)
    incoming = expected(snapshot, resource_id, at, now)
    committed = reserved(snapshot, resource_id, at)
    available = (
        None
        if current is None or incoming is None or committed is None
        else current + incoming - committed
    )
    return AvailabilityView(
        resource_id=resource_id,
        at=at,
        on_hand=current,
        expected=incoming,
        reserved=committed,
        available_by=available,
        overdue_line_ids=overdue_commitment_line_ids(snapshot, resource_id, now),
        as_of=snapshot.as_of,
    )


# --------------------------------------------------------------------------- allocation


def allocate(
    snapshot: GraphSnapshot,
    resource_id: ResourceId,
    now: datetime,
    extra_claims: Sequence[Claim] = (),
) -> AllocationResult:
    """Greedy, deterministic allocation (spec invariant 11.4.5).

    Claims are ordered strictly by ``(task start, order external id, claim id)``. Expected
    supply is released as each claim's start time is passed, so a delivery due tomorrow can
    never satisfy a task starting today. A partially served claim still consumes what it took.
    """
    claims = list(_reservation_claims(snapshot, resource_id)) + [
        claim for claim in extra_claims if claim.resource_id == resource_id
    ]
    current = on_hand(snapshot, resource_id)
    if current is None or any(c.quantity is None or c.start is None for c in claims):
        return AllocationResult(resource_id=resource_id, unknown=True, allocations=())

    incoming = [
        line
        for line in open_commitment_lines(snapshot, resource_id)
        if _due_at(snapshot, line) >= now
    ]
    if any(line.quantity is None for line in incoming):
        return AllocationResult(resource_id=resource_id, unknown=True, allocations=())

    ordered = sorted(claims, key=_claim_sort_key)
    remaining = current
    cursor = 0
    allocations: list[Allocation] = []
    for claim in ordered:
        start = claim.start
        need = claim.quantity
        assert start is not None and need is not None
        while cursor < len(incoming) and _due_at(snapshot, incoming[cursor]) <= start:
            line_quantity = incoming[cursor].quantity
            assert line_quantity is not None
            remaining += line_quantity
            cursor += 1
        available = remaining
        take = min(need, remaining) if remaining > ZERO else ZERO
        remaining -= take
        allocations.append(
            Allocation(
                claim_id=claim.id,
                order_line_id=claim.order_line_id,
                need=need,
                start=start,
                available_before_start=available,
                take=take,
                satisfied=take == need,
            )
        )
    return AllocationResult(resource_id=resource_id, unknown=False, allocations=tuple(allocations))


# --------------------------------------------------------------------------- settlement


def apply_exception_facts(
    snapshot: GraphSnapshot, exception: PhysicalException, now: datetime
) -> SettlementResult:
    """Apply a worker-attested physical exception to the snapshot.

    Returns the transformed snapshot plus the ledger postings and line settlements it
    implies. Applying the same exception twice yields no further postings, because settled
    lines are never re-settled — the value-level mirror of the database's exactly-once index.
    """
    if exception.category is ExceptionCategory.SUPPLY_NOT_RECEIVED:
        return _apply_supply_exception(snapshot, exception, now)
    if exception.category is ExceptionCategory.STOCK_UNUSABLE:
        return _apply_stock_exception(snapshot, exception, now)
    return _apply_equipment_exception(snapshot, exception, now)


def _apply_supply_exception(
    snapshot: GraphSnapshot, exception: PhysicalException, now: datetime
) -> SettlementResult:
    commitment = snapshot.commitments[str(exception.commitment_id)]
    scope = set(exception.scope_line_ids) or {line.id for line in commitment.lines}
    settlements: list[LineSettlement] = []
    postings: list[LedgerPosting] = []

    for line in sorted(commitment.lines, key=lambda item: item.id):
        if line.received_state is not ReceivedState.EXPECTED:
            continue
        if line.id in scope:
            if exception.quantity is not None and len(scope) == 1:
                settlements.append(
                    LineSettlement(
                        commitment_line_id=line.id,
                        to_state=ReceivedState.SHORT,
                        received_qty=exception.quantity,
                        settled_at=now,
                        attested_by=exception.reported_by,
                    )
                )
                postings.append(
                    LedgerPosting(
                        resource_id=line.resource_id,
                        delta=exception.quantity,
                        source_kind=LedgerSourceKind.COMMITMENT_RECEIPT,
                        source_id=line.id,
                    )
                )
            else:
                settlements.append(
                    LineSettlement(
                        commitment_line_id=line.id,
                        to_state=ReceivedState.NOT_RECEIVED,
                        received_qty=None,
                        settled_at=now,
                        attested_by=exception.reported_by,
                    )
                )
        else:
            # The worker just attested that these goods physically arrived.
            settlements.append(
                LineSettlement(
                    commitment_line_id=line.id,
                    to_state=ReceivedState.RECEIVED,
                    received_qty=None,
                    settled_at=now,
                    attested_by=exception.reported_by,
                )
            )
            postings.append(
                LedgerPosting(
                    resource_id=line.resource_id,
                    delta=line.quantity,
                    source_kind=LedgerSourceKind.COMMITMENT_RECEIPT,
                    source_id=line.id,
                )
            )

    updated = snapshot.settle_commitment_lines(settlements)
    updated = _post(updated, postings, now)
    return SettlementResult(
        snapshot=updated, postings=tuple(postings), settlements=tuple(settlements)
    )


def _apply_stock_exception(
    snapshot: GraphSnapshot, exception: PhysicalException, now: datetime
) -> SettlementResult:
    resource_id = str(exception.resource_id)
    lost = exception.quantity
    if lost is None:
        current = on_hand(snapshot, resource_id)
        delta = None if current is None else -current
    else:
        delta = -lost
    postings = [
        LedgerPosting(
            resource_id=resource_id,
            delta=delta,
            source_kind=LedgerSourceKind.EXCEPTION_FACT,
            source_id=f"{exception.id}:{resource_id}",
        )
    ]
    if _already_posted(snapshot, postings[0]):
        return SettlementResult(snapshot=snapshot, postings=(), settlements=())
    return SettlementResult(
        snapshot=_post(snapshot, postings, now), postings=tuple(postings), settlements=()
    )


def _apply_equipment_exception(
    snapshot: GraphSnapshot, exception: PhysicalException, now: datetime
) -> SettlementResult:
    outage = EquipmentOutage(
        id=f"outage:{exception.id}",
        equipment_id=str(exception.resource_id),
        starts_at=now,
        ends_at=exception.outage_until,
    )
    if any(existing.id == outage.id for existing in snapshot.outages):
        return SettlementResult(snapshot=snapshot, postings=(), settlements=())
    return SettlementResult(
        snapshot=snapshot.add_outage(outage), postings=(), settlements=(), outage=outage
    )


# --------------------------------------------------------------------------- helpers


def _post(
    snapshot: GraphSnapshot, postings: Sequence[LedgerPosting], now: datetime
) -> GraphSnapshot:
    if not postings:
        return snapshot
    seq = snapshot.next_ledger_seq()
    entries = []
    for offset, posting in enumerate(postings):
        entries.append(
            InventoryLedgerEntry(
                seq=seq + offset,
                resource_id=posting.resource_id,
                delta=posting.delta,
                source_kind=posting.source_kind,
                source_id=posting.source_id,
                recorded_at=now,
            )
        )
    return snapshot.append_ledger(entries)


def _already_posted(snapshot: GraphSnapshot, posting: LedgerPosting) -> bool:
    return any(
        entry.source_kind is posting.source_kind and entry.source_id == posting.source_id
        for entry in snapshot.ledger
    )


def _due_at(snapshot: GraphSnapshot, line: CommitmentLine) -> datetime:
    return snapshot.commitments[line.commitment_id].due_at


def _reservation_claims(snapshot: GraphSnapshot, resource_id: ResourceId) -> list[Claim]:
    claims: list[Claim] = []
    for reservation_id in snapshot.reservations_by_resource.get(resource_id, ()):
        reservation = snapshot.reservations[reservation_id]
        task = snapshot.task_of_line(reservation.order_line_id)
        if task is not None and task.state not in _CONSUMING_TASK_STATES:
            continue
        order = snapshot.order_of_line(reservation.order_line_id)
        claims.append(
            Claim(
                id=reservation.id,
                resource_id=resource_id,
                quantity=reservation.quantity,
                start=None if task is None else task.scheduled_start,
                order_external_id=order.external_id,
                order_line_id=reservation.order_line_id,
            )
        )
    return claims


def _claim_sort_key(claim: Claim) -> tuple[datetime, str, str]:
    assert claim.start is not None
    return (claim.start, claim.order_external_id, claim.id)
