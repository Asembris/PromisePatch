"""What travels over the live feed, and what deliberately does not.

An SSE frame is a notification envelope. It says that something happened, when, and to what --
enough for a client to decide which read to repeat -- and it is not a copy of the state, because
a copy delivered over a transport with no acknowledgement, no ordering guarantee beyond our own
and no audit would be a second, unaccountable source of truth for a system whose whole argument
is that there is one.

So the envelope carries identifiers and nothing that reads as content. No payload blob, no
correlation id, no customer, no message text, no session or database detail. A subscriber that
wants to know what an order now says asks ``/api/promises``, where the answer is assembled under
the rules that govern every other read.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from promisepatch.db.events import DomainEventRecord


class DomainEventEnvelope(BaseModel):
    """One committed domain event, as much of it as a browser is told.

    ``entity_refs`` names the entities the event touched, which is what lets a client invalidate
    one promise rather than the whole order book. By the contract of the spine those references
    are entity kinds and stored identifiers -- never attributes of a customer or an order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int
    id: UUID
    type: str
    occurred_at: datetime
    case_id: UUID | None
    entity_refs: tuple[Any, ...]

    @classmethod
    def of(cls, record: DomainEventRecord) -> DomainEventEnvelope:
        return cls(
            seq=record.seq,
            id=record.event_id,
            type=record.type,
            occurred_at=record.occurred_at,
            case_id=record.case_id,
            entity_refs=record.entity_refs,
        )


class ResyncEnvelope(BaseModel):
    """History was skipped, and the client is being told so rather than left to assume.

    A subscriber that has been away longer than the feed replays is not sent a silent partial
    catch-up: it is sent this, with the sequence the ledger has actually reached, and is expected
    to refetch the read APIs. Saying "you missed some" is the honest answer; quietly resuming
    from the present while implying continuity is not.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    latest_seq: int
    skipped_from_seq: int
    reason: str
    detail: str
