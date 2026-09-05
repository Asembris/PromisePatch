"""What PromisePatch asks the order system to do, and what it is told in return.

An amendment is the only write PromisePatch ever performs against somebody's order, and every
field here exists to make it refusable rather than merely deliverable.

**``expected_version`` is optimistic concurrency, not decoration.** The plan was made against
one version of the order; if the order has moved since, the change PromisePatch computed may no
longer be the change the customer agreed to. The order system compares and refuses, so an old
amendment can never overwrite a newer truth -- and PromisePatch finds out rather than believing
it succeeded.

**``from_item_id`` is a precondition, not a hint.** It says what the line was pinned to when the
plan was made. A line already moved elsewhere is a different world, and the amendment is
refused in it.

**The idempotency key travels in a header, not in the body.** It identifies the *request*, so a
retry after an uncertain answer must present the identical key with the identical body; the
order system stores both and answers a repeat with the original result rather than acting
twice. Putting the key in the body would make it part of what is hashed for comparison, which
is circular.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from pydantic import Field

from order_contract.events import SCHEMA_VERSION, Message

IDEMPOTENCY_HEADER: Final = "Idempotency-Key"
"""The header a retry repeats. Never derived by the client from a clock or an attempt count."""

ERROR_VERSION_CONFLICT: Final = "VERSION_CONFLICT"
ERROR_IDEMPOTENCY_CONFLICT: Final = "IDEMPOTENCY_CONFLICT"
ERROR_ORDER_NOT_FOUND: Final = "ORDER_NOT_FOUND"
ERROR_LINE_NOT_FOUND: Final = "LINE_NOT_FOUND"
ERROR_UNKNOWN_ITEM: Final = "UNKNOWN_ITEM"
ERROR_LINE_MOVED: Final = "LINE_MOVED"
ERROR_ORDER_NOT_OPEN: Final = "ORDER_NOT_OPEN"
ERROR_SCHEMA_VERSION: Final = "UNSUPPORTED_SCHEMA_VERSION"

DETERMINISTIC_REFUSALS: Final[frozenset[str]] = frozenset(
    {
        ERROR_VERSION_CONFLICT,
        ERROR_IDEMPOTENCY_CONFLICT,
        ERROR_ORDER_NOT_FOUND,
        ERROR_LINE_NOT_FOUND,
        ERROR_UNKNOWN_ITEM,
        ERROR_LINE_MOVED,
        ERROR_ORDER_NOT_OPEN,
        ERROR_SCHEMA_VERSION,
    }
)
"""Refusals a retry cannot turn into an acceptance.

Each one is a statement about the world rather than about the network: the order moved, the
item is unknown, the line is already elsewhere. Sending the same request again would produce
the same answer, so the caller stops and says so instead of climbing a retry ladder that
cannot reach anything.
"""


class AmendmentCorrelation(Message):
    """Which recovery this amendment belongs to, for the order system's own record.

    Carried so a human reading the order system's history can find the case that caused a
    change. It confers no authority: the order system does not consult it, and PromisePatch
    does not ask it to.
    """

    case_id: UUID
    track_id: UUID
    option_id: UUID


class AmendmentRequest(Message):
    """Re-point one line of one order at another catalogue item."""

    schema_version: int = SCHEMA_VERSION
    external_order_id: str
    expected_version: int = Field(gt=0)
    external_line_id: str
    from_item_id: str
    to_item_id: str
    note: str = ""
    correlation: AmendmentCorrelation


class AmendmentResult(Message):
    """What the order system did, in terms the caller can verify against later events."""

    schema_version: int = SCHEMA_VERSION
    external_order_id: str
    external_line_id: str
    previous_version: int = Field(gt=0)
    external_version: int = Field(gt=0)
    item_id: str
    state: str
    provider_ref: str
    event_id: UUID
    replayed: bool = False
    """True when this answer was read back from the idempotency ledger rather than performed.

    The distinction matters to nobody's state and everything to a test: it is the evidence that
    a repeated key produced one mutation and two answers.
    """


class ContractError(Message):
    """A deterministic refusal, with a code a caller may branch on."""

    code: str
    message: str
    external_order_id: str | None = None
    current_version: int | None = None


class ErrorResponse(Message):
    error: ContractError


__all__ = [
    "DETERMINISTIC_REFUSALS",
    "ERROR_IDEMPOTENCY_CONFLICT",
    "ERROR_LINE_MOVED",
    "ERROR_LINE_NOT_FOUND",
    "ERROR_ORDER_NOT_FOUND",
    "ERROR_ORDER_NOT_OPEN",
    "ERROR_SCHEMA_VERSION",
    "ERROR_UNKNOWN_ITEM",
    "ERROR_VERSION_CONFLICT",
    "IDEMPOTENCY_HEADER",
    "AmendmentCorrelation",
    "AmendmentRequest",
    "AmendmentResult",
    "ContractError",
    "ErrorResponse",
]
