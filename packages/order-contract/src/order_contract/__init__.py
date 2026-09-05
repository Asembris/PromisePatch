"""The integration contract between PromisePatch and the external order system.

One distribution, imported by both sides, because two implementations of one message drift the
day somebody edits one of them. Pydantic and the standard library only: no I/O, no database
models, and no import of either application.
"""

from order_contract.amendments import (
    IDEMPOTENCY_HEADER,
    AmendmentCorrelation,
    AmendmentRequest,
    AmendmentResult,
    ContractError,
    ErrorResponse,
)
from order_contract.events import (
    EVENT_ORDER_CANCELLED,
    EVENT_ORDER_UPDATED,
    SCHEMA_VERSION,
    ChannelRef,
    CommandRef,
    CustomerRef,
    OrderEvent,
    OrderLineRef,
    OrderSnapshot,
)
from order_contract.signing import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    SignatureError,
    headers_for,
    signature_for,
    verify,
)

__all__ = [
    "EVENT_ORDER_CANCELLED",
    "EVENT_ORDER_UPDATED",
    "IDEMPOTENCY_HEADER",
    "SCHEMA_VERSION",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "AmendmentCorrelation",
    "AmendmentRequest",
    "AmendmentResult",
    "ChannelRef",
    "CommandRef",
    "ContractError",
    "CustomerRef",
    "ErrorResponse",
    "OrderEvent",
    "OrderLineRef",
    "OrderSnapshot",
    "SignatureError",
    "headers_for",
    "signature_for",
    "verify",
]
