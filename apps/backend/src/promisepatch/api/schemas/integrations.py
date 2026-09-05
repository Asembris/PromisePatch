"""What the order system is told about a delivery it just made.

Deliberately thin. The answer confirms receipt and nothing else: it does not say what the event
will do to a mirrored order, because at the moment it is written nobody has decided that yet and
a sender is not entitled to know it.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrderEventAccepted(BaseModel):
    """A receipt. ``duplicate`` is a success, not a warning."""

    model_config = ConfigDict(frozen=True)

    accepted: bool = True
    event_id: UUID = Field(description="the sender's own identifier for this change")
    duplicate: bool = Field(
        default=False, description="whether this exact delivery was already stored"
    )
    inbox_event_id: UUID | None = Field(
        default=None, description="the stored record, absent for a redelivery"
    )
