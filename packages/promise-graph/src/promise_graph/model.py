"""Frozen typed domain records and the closed vocabularies the engine reasons over.

This module is the bottom of the engine's import layering: it imports nothing from
``promise_graph`` and performs no computation beyond validation.

Two deliberate constraints live here:

* **Quantities are :class:`~decimal.Decimal`, never ``float``.** Floats would make allocation
  order, shortfall arithmetic and snapshot fingerprints non-reproducible. Every quantity is
  normalised to a fixed scale on construction so ``2.0`` and ``2.00`` are one value.
* **Timestamps are timezone-aware and normalised to UTC.** The engine never calls the wall
  clock; ``now`` is always an explicit parameter supplied by the caller.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Final

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, model_validator

# --------------------------------------------------------------------------- identifiers

ResourceId = str
SupplierId = str
CommitmentId = str
CommitmentLineId = str
RecipeId = str
RecipeVersionId = str
CustomerId = str
OrderId = str
OrderLineId = str
ConstraintId = str
PromiseId = str
TaskId = str
ReservationId = str
PolicyId = str
ExceptionId = str
OutageId = str

# --------------------------------------------------------------------------- scalars

QUANTITY_EXPONENT: Final = Decimal("0.001")
"""Fixed scale every quantity is normalised to, so equal amounts hash equally."""


def _to_quantity(value: Any) -> Any:
    """Reject floats and normalise every accepted quantity to :data:`QUANTITY_EXPONENT`."""
    if isinstance(value, bool):
        raise ValueError("booleans are not quantities")
    if isinstance(value, float):
        raise ValueError("float quantities are forbidden; pass Decimal, int or str")
    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int | str):
        try:
            decimal_value = Decimal(value)
        except InvalidOperation as exc:  # pragma: no cover - defensive
            raise ValueError(f"not a decimal quantity: {value!r}") from exc
    else:
        return value
    if not decimal_value.is_finite():
        raise ValueError("quantities must be finite")
    return decimal_value.quantize(QUANTITY_EXPONENT)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _reject_negative(value: Decimal) -> Decimal:
    if value < 0:
        raise ValueError("quantity must not be negative")
    return value


Quantity = Annotated[Decimal, BeforeValidator(_to_quantity)]
"""A signed decimal amount (ledger deltas may be negative)."""

NonNegativeQuantity = Annotated[
    Decimal, BeforeValidator(_to_quantity), AfterValidator(_reject_negative)
]

Timestamp = Annotated[datetime, AfterValidator(_to_utc)]

# --------------------------------------------------------------------------- vocabularies


class ResourceKind(StrEnum):
    INGREDIENT = "INGREDIENT"
    EQUIPMENT = "EQUIPMENT"


class RecipeLineRole(StrEnum):
    STRUCTURAL = "STRUCTURAL"
    FILLING = "FILLING"
    VISIBLE_DECORATION = "VISIBLE_DECORATION"


class ReceivedState(StrEnum):
    """A commitment line is open (``EXPECTED``) or settled (everything else)."""

    EXPECTED = "EXPECTED"
    RECEIVED = "RECEIVED"
    NOT_RECEIVED = "NOT_RECEIVED"
    SHORT = "SHORT"


SETTLED_STATES: Final = frozenset(
    {ReceivedState.RECEIVED, ReceivedState.NOT_RECEIVED, ReceivedState.SHORT}
)


class OrderState(StrEnum):
    ACCEPTED = "ACCEPTED"
    AMENDED = "AMENDED"
    CANCELLED = "CANCELLED"
    FULFILLED = "FULFILLED"


class TaskState(StrEnum):
    SCHEDULED = "SCHEDULED"
    STARTED = "STARTED"
    DONE = "DONE"
    HELD = "HELD"


class ConstraintKind(StrEnum):
    NO_SUBSTITUTION = "NO_SUBSTITUTION"
    PREAPPROVED_ALTERNATIVE = "PREAPPROVED_ALTERNATIVE"
    ASK_BEFORE_VISIBLE_CHANGE = "ASK_BEFORE_VISIBLE_CHANGE"
    EXCLUDE_RESOURCE = "EXCLUDE_RESOURCE"


class ExceptionCategory(StrEnum):
    SUPPLY_NOT_RECEIVED = "SUPPLY_NOT_RECEIVED"
    STOCK_UNUSABLE = "STOCK_UNUSABLE"
    EQUIPMENT_UNAVAILABLE = "EQUIPMENT_UNAVAILABLE"


class OptionKind(StrEnum):
    SUBSTITUTE_RESOURCE = "SUBSTITUTE_RESOURCE"
    REASSIGN_EQUIPMENT = "REASSIGN_EQUIPMENT"
    ESCALATE_TO_OWNER = "ESCALATE_TO_OWNER"


class Classification(StrEnum):
    UNAFFECTED = "UNAFFECTED"
    AUTO_RECOVERABLE = "AUTO_RECOVERABLE"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    BLOCKED = "BLOCKED"


SEVERITY_ORDER: Final = {
    Classification.UNAFFECTED: 0,
    Classification.AUTO_RECOVERABLE: 1,
    Classification.APPROVAL_REQUIRED: 2,
    Classification.BLOCKED: 3,
}
"""Total order used by the monotonicity invariant: more supply never raises severity."""


class RuleId(StrEnum):
    """The twelve frozen classification rule ids. No thirteenth id is invented."""

    R_UNREACH = "R-UNREACH"
    R_COVERED = "R-COVERED"
    R_PREAPPROVED = "R-PREAPPROVED"
    R_INVISIBLE_NOASK = "R-INVISIBLE-NOASK"
    R_VISIBLE_ASK = "R-VISIBLE-ASK"
    R_NOT_PREAPPROVED = "R-NOT-PREAPPROVED"
    R_NOSUB = "R-NOSUB"
    R_EXCLUDED = "R-EXCLUDED"
    R_SUBSTOCK = "R-SUBSTOCK"
    R_NOEQUIP = "R-NOEQUIP"
    R_UNKNOWN = "R-UNKNOWN"
    R_CONFLICT = "R-CONFLICT"


class ReasonDetail(StrEnum):
    """Sub-cause carried alongside a :class:`RuleId`.

    ``R_NOSUB`` means "substitution is not available for this promise" and covers two
    distinct causes: an explicit ``NO_SUBSTITUTION`` constraint on the order, and the absence
    of any pre-authored variant version. The cause is recorded here rather than by adding a
    rule id outside the frozen set.
    """

    NONE = "NONE"
    NOSUB_CONSTRAINT = "NOSUB_CONSTRAINT"
    NO_PREAUTHORED_VARIANT = "NO_PREAUTHORED_VARIANT"
    EXCLUDED_SUBSTITUTE = "EXCLUDED_SUBSTITUTE"
    INSUFFICIENT_SUBSTITUTE_STOCK = "INSUFFICIENT_SUBSTITUTE_STOCK"
    NO_ALTERNATIVE_EQUIPMENT = "NO_ALTERNATIVE_EQUIPMENT"
    NO_CONSTRAINT_SNAPSHOT = "NO_CONSTRAINT_SNAPSHOT"
    UNKNOWN_QUANTITY = "UNKNOWN_QUANTITY"
    CONFLICTING_CONSTRAINTS = "CONFLICTING_CONSTRAINTS"
    NOT_REACHABLE = "NOT_REACHABLE"
    SHORTFALL_COVERED = "SHORTFALL_COVERED"
    PREAPPROVAL_COVERS = "PREAPPROVAL_COVERS"
    NOT_VISIBLE_NO_ASK = "NOT_VISIBLE_NO_ASK"
    VISIBLE_CHANGE_ASK = "VISIBLE_CHANGE_ASK"
    NOT_PREAPPROVED = "NOT_PREAPPROVED"
    EQUIPMENT_REASSIGNED = "EQUIPMENT_REASSIGNED"


class RejectionReason(StrEnum):
    """Why a recovery candidate did not validate."""

    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"
    NOSUB_CONSTRAINT = "NOSUB_CONSTRAINT"
    NO_PREAUTHORED_VARIANT = "NO_PREAUTHORED_VARIANT"
    EXCLUDED = "EXCLUDED"
    SUBSTOCK = "SUBSTOCK"
    NOEQUIP = "NOEQUIP"


REJECTION_PRECEDENCE: Final = (
    RejectionReason.CONFLICT,
    RejectionReason.UNKNOWN,
    RejectionReason.NOSUB_CONSTRAINT,
    RejectionReason.NO_PREAUTHORED_VARIANT,
    RejectionReason.EXCLUDED,
    RejectionReason.SUBSTOCK,
    RejectionReason.NOEQUIP,
)
"""Fixed ladder: when several block reasons hold at once, the earliest one is cited."""


class LedgerSourceKind(StrEnum):
    FIXTURE = "FIXTURE"
    COMMITMENT_RECEIPT = "COMMITMENT_RECEIPT"
    EXCEPTION_FACT = "EXCEPTION_FACT"
    CORRECTION = "CORRECTION"
    RESERVATION_RELEASE = "RESERVATION_RELEASE"


class EdgeKind(StrEnum):
    COMMITMENT_LINE_TO_RESOURCE = "COMMITMENT_LINE_TO_RESOURCE"
    RESOURCE_TO_RECIPE_VERSION = "RESOURCE_TO_RECIPE_VERSION"
    RECIPE_VERSION_TO_ORDER_LINE = "RECIPE_VERSION_TO_ORDER_LINE"
    EQUIPMENT_TO_PRODUCTION_TASK = "EQUIPMENT_TO_PRODUCTION_TASK"
    PRODUCTION_TASK_TO_ORDER_LINE = "PRODUCTION_TASK_TO_ORDER_LINE"
    ORDER_LINE_TO_PROMISE = "ORDER_LINE_TO_PROMISE"


class ParserKind(StrEnum):
    """Only ``LITERAL`` can produce an authoritative approval decision."""

    LITERAL = "LITERAL"
    LLM = "LLM"


class ApprovalDecisionKind(StrEnum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"


class ApprovalRequestState(StrEnum):
    SENT = "SENT"
    CONFIRMATION_PENDING = "CONFIRMATION_PENDING"
    ANSWERED = "ANSWERED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------- records


class Record(BaseModel):
    """Immutable base for every domain record."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Resource(Record):
    id: ResourceId
    kind: ResourceKind
    name: str
    unit: str = "unit"
    aliases: tuple[str, ...] = ()


class Supplier(Record):
    id: SupplierId
    name: str


class CommitmentLine(Record):
    """One expected resource line of a supplier commitment.

    ``quantity is None`` models an unknown expected amount, which fails closed downstream.
    """

    id: CommitmentLineId
    commitment_id: CommitmentId
    resource_id: ResourceId
    quantity: NonNegativeQuantity | None
    received_state: ReceivedState = ReceivedState.EXPECTED
    received_qty: NonNegativeQuantity | None = None
    settled_at: Timestamp | None = None
    attested_by: str | None = None

    @model_validator(mode="after")
    def _check_settlement(self) -> CommitmentLine:
        if self.received_state is ReceivedState.SHORT:
            if self.received_qty is None:
                raise ValueError("SHORT commitment lines must carry received_qty")
        elif self.received_qty is not None:
            raise ValueError("received_qty is only meaningful for SHORT lines")
        if self.received_state is ReceivedState.EXPECTED and self.settled_at is not None:
            raise ValueError("an EXPECTED line is not settled")
        return self

    @property
    def is_settled(self) -> bool:
        return self.received_state in SETTLED_STATES


class SupplierCommitment(Record):
    id: CommitmentId
    supplier_id: SupplierId
    due_at: Timestamp
    lines: tuple[CommitmentLine, ...]

    @model_validator(mode="after")
    def _check_lines(self) -> SupplierCommitment:
        for line in self.lines:
            if line.commitment_id != self.id:
                raise ValueError("commitment line does not belong to this commitment")
        if len({line.id for line in self.lines}) != len(self.lines):
            raise ValueError("duplicate commitment line id")
        return self


class Recipe(Record):
    id: RecipeId
    name: str


class RecipeVersionLine(Record):
    resource_id: ResourceId
    role: RecipeLineRole
    qty_per_unit: NonNegativeQuantity | None


class RecipeVersion(Record):
    """Immutable, human-authored bill of resources. Never created at runtime."""

    id: RecipeVersionId
    recipe_id: RecipeId
    version_no: int
    lines: tuple[RecipeVersionLine, ...]
    equipment_ids: tuple[ResourceId, ...] = ()
    authored_by: str
    authored_at: Timestamp


class Customer(Record):
    """Identity plus the channel an approval must arrive on. Nothing else."""

    id: CustomerId
    name: str
    approval_channel: str


class OrderLine(Record):
    id: OrderLineId
    order_id: OrderId
    recipe_version_id: RecipeVersionId
    quantity: int
    customization_note: str = ""

    @model_validator(mode="after")
    def _check_quantity(self) -> OrderLine:
        if self.quantity <= 0:
            raise ValueError("order line quantity must be positive")
        return self


class Order(Record):
    """Mirror of the external system of record."""

    id: OrderId
    external_id: str
    external_version: int
    customer_id: CustomerId
    due_at: Timestamp
    state: OrderState
    lines: tuple[OrderLine, ...]

    @model_validator(mode="after")
    def _check_lines(self) -> Order:
        for line in self.lines:
            if line.order_id != self.id:
                raise ValueError("order line does not belong to this order")
        if len({line.id for line in self.lines}) != len(self.lines):
            raise ValueError("duplicate order line id")
        return self


class CustomerConstraint(Record):
    """An order-scoped consent/safety rule. Provenance is mandatory by construction."""

    id: ConstraintId
    order_id: OrderId
    kind: ConstraintKind
    resource_id: ResourceId | None = None
    substitute_resource_id: ResourceId | None = None
    recorded_by: str
    recorded_at: Timestamp

    @model_validator(mode="after")
    def _check_shape(self) -> CustomerConstraint:
        if not self.recorded_by.strip():
            raise ValueError("constraint provenance (recorded_by) is mandatory")
        if self.kind is ConstraintKind.PREAPPROVED_ALTERNATIVE:
            if self.resource_id is None or self.substitute_resource_id is None:
                raise ValueError("PREAPPROVED_ALTERNATIVE needs both resources")
        elif self.kind is ConstraintKind.EXCLUDE_RESOURCE:
            if self.resource_id is None:
                raise ValueError("EXCLUDE_RESOURCE needs a resource")
            if self.substitute_resource_id is not None:
                raise ValueError("EXCLUDE_RESOURCE has no substitute")
        elif self.resource_id is not None or self.substitute_resource_id is not None:
            raise ValueError(f"{self.kind} carries no resources")
        return self


class CustomerPromise(Record):
    """The unit of impact: one per accepted order."""

    id: PromiseId
    order_id: OrderId
    due_at: Timestamp


class ProductionTask(Record):
    id: TaskId
    order_line_id: OrderLineId
    state: TaskState
    scheduled_start: Timestamp | None
    scheduled_end: Timestamp | None = None
    equipment_id: ResourceId | None = None
    held_by_case_id: str | None = None


class InventoryReservation(Record):
    id: ReservationId
    order_line_id: OrderLineId
    resource_id: ResourceId
    quantity: NonNegativeQuantity | None
    source_recipe_version_id: RecipeVersionId


class InventoryLedgerEntry(Record):
    """Append-only physical posting. ``delta is None`` makes on-hand unknown."""

    seq: int
    resource_id: ResourceId
    delta: Quantity | None
    source_kind: LedgerSourceKind
    source_id: str
    recorded_at: Timestamp


class EquipmentOutage(Record):
    id: OutageId
    equipment_id: ResourceId
    starts_at: Timestamp
    ends_at: Timestamp | None = None


class SubstitutionPolicyEntry(Record):
    """Bakery-authored map to a *pre-authored* variant version. Proposes candidates only."""

    id: PolicyId
    affected_resource_id: ResourceId
    role: RecipeLineRole
    source_version_id: RecipeVersionId
    candidate_version_id: RecipeVersionId
    substitute_resource_id: ResourceId
    visible_change: bool


class EquipmentAlternative(Record):
    id: PolicyId
    equipment_id: ResourceId
    alternative_equipment_id: ResourceId

    @model_validator(mode="after")
    def _check_distinct(self) -> EquipmentAlternative:
        if self.equipment_id == self.alternative_equipment_id:
            raise ValueError("equipment cannot be its own alternative")
        return self


class PhysicalException(Record):
    """The interpreted, worker-attested fact.

    ``raw_utterance`` is provenance only. No engine function reads it, which is what makes
    the "no branch on utterance text" guarantee structural rather than aspirational.
    """

    id: ExceptionId
    category: ExceptionCategory
    commitment_id: CommitmentId | None = None
    scope_line_ids: tuple[CommitmentLineId, ...] = ()
    resource_id: ResourceId | None = None
    quantity: NonNegativeQuantity | None = None
    outage_until: Timestamp | None = None
    reported_by: str
    reported_at: Timestamp
    raw_utterance: str = ""

    @model_validator(mode="after")
    def _check_binding(self) -> PhysicalException:
        if self.category is ExceptionCategory.SUPPLY_NOT_RECEIVED:
            if self.commitment_id is None:
                raise ValueError("SUPPLY_NOT_RECEIVED must bind a commitment")
            if self.resource_id is not None:
                raise ValueError("SUPPLY_NOT_RECEIVED binds lines, not a bare resource")
        elif self.category is ExceptionCategory.STOCK_UNUSABLE:
            if self.resource_id is None:
                raise ValueError("STOCK_UNUSABLE must bind a resource")
            if self.commitment_id is not None:
                raise ValueError("STOCK_UNUSABLE does not bind a commitment")
        else:
            if self.resource_id is None:
                raise ValueError("EQUIPMENT_UNAVAILABLE must bind an equipment resource")
            if self.commitment_id is not None:
                raise ValueError("EQUIPMENT_UNAVAILABLE does not bind a commitment")
        return self


class ApprovalRequestRecord(Record):
    """What was asked of the customer, and the state it was asked against."""

    id: str
    track_id: str
    promise_id: PromiseId
    order_id: OrderId
    order_line_id: OrderLineId
    option_id: str
    candidate_version_id: RecipeVersionId | None = None
    substitute_resource_id: ResourceId | None = None
    required_substitute_quantity: NonNegativeQuantity | None = None
    customer_channel: str
    sent_at: Timestamp
    deadline: Timestamp
    captured_fingerprint: str
    captured_order_version: int
    captured_recipe_version_id: RecipeVersionId
    captured_constraint_hash: str
    state: ApprovalRequestState = ApprovalRequestState.SENT
    decided: bool = False


class ApprovalDecisionRecord(Record):
    """The authoritative answer. Only the literal parser may produce one."""

    request_id: str
    decision: ApprovalDecisionKind
    parser: ParserKind
    sender_identity: str
    provider_message_id: str
    raw_text: str = ""
    received_at: Timestamp
