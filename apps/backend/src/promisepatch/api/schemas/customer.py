"""The customer approval surface's wire shapes.

Two of them, and the asymmetry between them is the authority model on the wire.

The **response** is wide: it carries everything the page renders, because a page a stranger
reaches must not need a second request to say something true.

The **request** is one field, and that field is a choice between two values. There is no sender
field, no channel field, no customer field, no timestamp and no free text -- nothing a caller
could put in a body that would name who is answering, when they answered or what they meant.
The channel comes from the signature on the link and the clock comes from the database, so the
only thing this body carries is which of the two words the person pressed.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class CustomerAnswer(StrEnum):
    """The two answers a button can carry, which are the two the literal parser reads.

    An enum rather than a string, so the transport cannot deliver a sentence into the consent
    path: a body that is not one of these two values is refused by the schema before any
    handler runs, and the words that reach the parser are composed on the server from these
    members. A page cannot ask the protocol a question it was not given two buttons for.
    """

    APPROVE = "APPROVE"
    DECLINE = "DECLINE"


class CustomerAnswerRequest(BaseModel):
    """What the customer's page sends. One field, closed to anything else."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: CustomerAnswer


class CustomerApprovalResponse(BaseModel):
    """One approval request, as the holder of its link may see it.

    Every field is optional except the phase, because the closed view carries none of them: a
    link that opens nothing answers with a phase and no detail, in the same shape, so the
    browser has one response to render rather than two.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase: str
    """``OPEN``, ``RECEIVED``, ``APPROVED``, ``DECLINED``, ``EXPIRED``, ``SUPERSEDED``,
    ``CLOSED``. The customer's vocabulary, which is not the worker's."""

    answerable: bool
    """Whether this page may still offer the choice. Decided on the server, never in the
    browser: a page that worked out for itself whether a window was open would be a second,
    weaker deadline."""

    customer_name: str | None = None
    order_reference: str | None = None
    option_code: str | None = None
    due_at: datetime | None = None
    """When the order itself is due, if the mirror holds it."""

    answer_by: datetime | None = None
    """When this question closes. The request's own deadline, which is what the protocol
    compares an answer against."""

    from_product: str | None = None
    to_product: str | None = None
    affected_resource: str | None = None
    substitute_resource: str | None = None
    """The differences that exist. Absent where the rows hold none, never a placeholder."""

    outcome: str | None = None
    """What has actually happened to the order since, if anything has -- or, once a yes is on
    the record and before the change is made, that the order is checked again first."""

    answered_at: datetime | None = None

    awaiting_outcome: bool
    """Whether something is still going to happen on account of this answer, so the page keeps
    reading. Decided on the server for the reason ``answerable`` is; a browser that inferred it
    from ``outcome``'s wording would be deciding from a sentence."""


__all__ = ["CustomerAnswer", "CustomerAnswerRequest", "CustomerApprovalResponse"]
