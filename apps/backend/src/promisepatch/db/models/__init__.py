"""Every mapped table, imported so the metadata is complete.

Alembic and the schema tests both work from ``Base.metadata``. A model module that nothing
imports is a table that autogenerate would propose dropping, so the import list here is the
registry rather than a convenience.
"""

from promisepatch.db.models.actors import FixtureState, Session, Worker
from promisepatch.db.models.audit import AuditEvent
from promisepatch.db.models.cases import (
    ApprovalDecision,
    ApprovalRequest,
    Case,
    CaseReport,
    ExceptionClarification,
    ExceptionFact,
    InboundReply,
    PhysicalException,
    RecoveryOption,
    Track,
    TrackPath,
    TrackWatch,
)
from promisepatch.db.models.graph import (
    CommitmentLine,
    EquipmentAlternative,
    Recipe,
    RecipeVersion,
    RecipeVersionEquipment,
    RecipeVersionLine,
    Resource,
    ResourceAlias,
    SubstitutionPolicy,
    Supplier,
    SupplierCommitment,
)
from promisepatch.db.models.inventory import InventoryLedgerEntry
from promisepatch.db.models.orders import (
    Customer,
    Order,
    OrderConstraint,
    OrderLine,
    OrderLineMapping,
    Promise,
)
from promisepatch.db.models.production import EquipmentOutage, ProductionTask, Reservation
from promisepatch.db.models.workflow import (
    CaseStep,
    Conversation,
    DomainEvent,
    InboxEvent,
    OutboxMessage,
    Timer,
)

__all__ = [
    "ApprovalDecision",
    "ApprovalRequest",
    "AuditEvent",
    "Case",
    "CaseReport",
    "CaseStep",
    "CommitmentLine",
    "Conversation",
    "Customer",
    "DomainEvent",
    "EquipmentAlternative",
    "EquipmentOutage",
    "ExceptionClarification",
    "ExceptionFact",
    "FixtureState",
    "InboundReply",
    "InboxEvent",
    "InventoryLedgerEntry",
    "Order",
    "OrderConstraint",
    "OrderLine",
    "OrderLineMapping",
    "OutboxMessage",
    "PhysicalException",
    "ProductionTask",
    "Promise",
    "Recipe",
    "RecipeVersion",
    "RecipeVersionEquipment",
    "RecipeVersionLine",
    "RecoveryOption",
    "Reservation",
    "Resource",
    "ResourceAlias",
    "Session",
    "SubstitutionPolicy",
    "Supplier",
    "SupplierCommitment",
    "Timer",
    "Track",
    "TrackPath",
    "TrackWatch",
    "Worker",
]
