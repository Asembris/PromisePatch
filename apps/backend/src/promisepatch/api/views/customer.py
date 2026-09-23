"""What a customer is shown about one approval request, read from rows and nothing else.

The narrowest read surface in the application, and narrow is the requirement rather than a
simplification. Whoever is looking at this page proved possession of a link and nothing more --
no account, no password, no session -- so the page may show only what the message on their own
channel already said, phrased so that a stranger holding a forwarded link learns nothing about
somebody's life that the message did not already tell them.

**It shows differences that exist and no others.** The product they ordered and the product
proposed, the ingredient replaced and the one replacing it, the date their order is due and the
date this question closes. Each one is omitted when the row does not hold it, rather than
rendered as a placeholder: a line saying "no change" where nothing was read is a claim, and a
line saying "--" is a claim a customer has to decode.

**There is no price line, because PromisePatch holds no price.** Not omitted as an
simplification and not deferred: no order, no order line, no recipe version and no recovery
option in this schema carries an amount, so there is no price difference to state and any
sentence about money here would be invented. A deployment that models prices adds a column
first and a line here second.

**It asserts nothing about safety.** §16.1 gives PromisePatch no allergen knowledge, so nothing
here reassures, qualifies or implies a dietary claim. The change is named, exactly, and the page
stops.

**Nothing here decides anything.** The state this reports is read from the request row, the
decision row and the track row; it never computes a decision, never compares a deadline in
order to close a window, and never writes. A page that said "expired" is describing a row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.model import ApprovalRequestState
from promisepatch.db.clock import database_now
from promisepatch.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    Customer,
    InboxEvent,
    Order,
    Recipe,
    RecipeVersion,
    RecoveryOption,
    Resource,
    Track,
)
from promisepatch.domain import approvals, handlers


class Phase:
    """What this request is, to the person holding the link. A closed vocabulary.

    Deliberately not the worker's vocabulary. A customer is not shown ``WAITING_FOR_CUSTOMER``
    or ``AUTO_RECOVERABLE``; they are shown whether the question is open, whether we have their
    answer, and what it was. The two vocabularies stay separate because they answer different
    questions for different people, and one table serving both would eventually say "escalated"
    to a customer.
    """

    OPEN: Final = "OPEN"
    """Still a question. The only phase in which an answer can be given."""

    RECEIVED: Final = "RECEIVED"
    """Their answer is stored and has not been read yet.

    A real state rather than a loading spinner. The answer is durable the moment the page
    returns, and what has not happened yet is the protocol reading it -- so this says exactly
    that, and never implies a decision that no row holds.
    """

    APPROVED: Final = "APPROVED"
    DECLINED: Final = "DECLINED"
    """A decision row exists and says this. Nothing after this changes it."""

    EXPIRED: Final = "EXPIRED"
    """The window closed with no decision. Nothing was done on the strength of the question."""

    SUPERSEDED: Final = "SUPERSEDED"
    """Their order moved after they were asked, so the question no longer stands."""

    CLOSED: Final = "CLOSED"
    """The fail-closed answer: the request is not open and no decision is readable.

    It should be unreachable, and it is here because the honest thing to show a person whose
    state we cannot name is that the question is closed -- never a button that might do
    something.
    """


ANSWERABLE: Final[frozenset[str]] = frozenset({Phase.OPEN})
"""The one phase in which the page offers a choice. Read by the router, not by the browser."""


@dataclass(frozen=True, slots=True)
class CustomerApprovalView:
    """One request as the person holding its link may see it."""

    phase: str
    customer_name: str | None
    order_reference: str | None
    option_code: str | None
    due_at: datetime | None
    answer_by: datetime | None
    from_product: str | None
    to_product: str | None
    affected_resource: str | None
    substitute_resource: str | None
    outcome: str | None
    answered_at: datetime | None
    awaiting_outcome: bool
    """Whether something is still going to happen on account of this answer.

    True while the answer is stored and unread, and while a yes is being checked against the
    order as it now stands or carried to the order system. False everywhere else -- including
    every fail-closed view -- because a page that keeps re-reading while this is true must stop
    once there is nothing left for it to learn. Decided here, from the rows, for the reason
    ``answerable`` is: a browser that worked out for itself whether the work was finished would
    be guessing from a sentence.
    """


CLOSED_LINK: Final = CustomerApprovalView(
    phase=Phase.CLOSED,
    customer_name=None,
    order_reference=None,
    option_code=None,
    due_at=None,
    answer_by=None,
    from_product=None,
    to_product=None,
    affected_resource=None,
    substitute_resource=None,
    outcome=None,
    answered_at=None,
    awaiting_outcome=False,
)
"""What a link that does not open this request is shown: the closed phase and no detail at all.

One answer for a request that never existed, a link whose channel is not the channel the
request was sent to, and a request whose row has gone. A page that distinguished them would
tell whoever is holding the link which of those they had found.
"""


_OUTCOME: Final[dict[str, str]] = {
    "RECOVERED": "Your order now shows this change.",
    "APPLYING": "We are updating your order now.",
    "ESCALATED": "The bakery will follow up with you about this order.",
    "STALE": "Your order changed after you were asked, so this question no longer applies.",
    "WITHDRAWN": "This request was stood down. Nothing was done to your order because of it.",
}
"""What each durable track state means to the customer, once there is something to say.

Every sentence is about a state the workflow has actually reached. ``RECOVERED`` is the only one
that says the order shows the change, because the workflow reaches that state only after the
order system's own version was observed to carry it -- which is why "now shows" can be said
there and nowhere earlier. A track state absent from this table produces no sentence, so an
unforeseen posture says nothing rather than something untrue.
"""

_CHECKED_FIRST: Final = (
    "Before anything changes, the bakery checks that your order can still be made this way."
)
"""What an approval is followed by, said while it is being followed by it.

The track is still ``WAITING_FOR_CUSTOMER`` between the decision being written and the change
going out, because a yes is not yet a change: the worker compares the order, the recipe it pins,
its constraints, the substitute's stock and the production task against how they stand *now*,
and only then amends anything. Said only once a yes is on the record, so a stored answer the
protocol has not read yet is never described as being acted on.
"""

_SETTLING_AFTER_YES: Final[frozenset[str]] = frozenset({"WAITING_FOR_CUSTOMER", "APPLYING"})
"""Track states in which an approved change has neither been made nor been refused yet."""


async def read(connection: AsyncConnection, *, request_id: UUID, channel: str) -> Any:
    """Read one request for the holder of a link, or the closed view.

    ``channel`` is the channel the link was minted for. It is compared against the channel the
    request was actually sent to, and a mismatch shows nothing: an order's approval channel can
    legitimately change after a request goes out, and a link minted for the old one must not
    keep reading a customer's order back to whoever now holds that address.

    A mismatch is *not* refused here as a policy matter -- answering is a different question,
    decided by the consent protocol against the same comparison, where it becomes an audited
    unauthorised reply rather than a quiet 404. This function only declines to reveal.
    """
    request = (
        await connection.execute(select(ApprovalRequest).where(ApprovalRequest.id == request_id))
    ).one_or_none()
    if request is None or request.customer_channel != channel:
        return CLOSED_LINK

    now = await database_now(connection)
    decision = (
        await connection.execute(
            select(ApprovalDecision).where(ApprovalDecision.request_id == request_id)
        )
    ).one_or_none()
    order = (
        await connection.execute(select(Order).where(Order.id == request.order_id))
    ).one_or_none()
    customer = (
        None
        if order is None
        else (
            await connection.execute(select(Customer).where(Customer.id == order.customer_id))
        ).one_or_none()
    )
    option = (
        await connection.execute(
            select(RecoveryOption).where(RecoveryOption.id == request.option_id)
        )
    ).one_or_none()
    track = (
        await connection.execute(select(Track).where(Track.id == request.track_id))
    ).one_or_none()
    phase = await _phase(connection, request=request, decision=decision, now=now)
    track_state = None if track is None else track.state

    return CustomerApprovalView(
        phase=phase,
        customer_name=None if customer is None else customer.name,
        order_reference=None if order is None else order.external_id,
        option_code=request.option_code,
        due_at=None if order is None else order.due_at,
        answer_by=request.deadline,
        from_product=await _product(connection, None if option is None else option.from_version_id),
        to_product=await _product(connection, None if option is None else option.to_version_id),
        affected_resource=await _resource(
            connection, None if option is None else option.affected_resource_id
        ),
        substitute_resource=await _resource(
            connection, None if option is None else option.substitute_resource_id
        ),
        outcome=_outcome(phase, track_state),
        answered_at=None if decision is None else decision.received_at,
        awaiting_outcome=_awaiting_outcome(phase, track_state),
    )


def _outcome(phase: str, track_state: str | None) -> str | None:
    """What has happened to the order since, or what happens next once a yes is recorded."""
    if phase == Phase.APPROVED and track_state == "WAITING_FOR_CUSTOMER":
        return _CHECKED_FIRST
    return None if track_state is None else _OUTCOME.get(track_state)


def _awaiting_outcome(phase: str, track_state: str | None) -> bool:
    """Whether the page should keep reading: an unread answer, or a yes not yet settled."""
    if phase == Phase.RECEIVED:
        return True
    return phase == Phase.APPROVED and track_state in _SETTLING_AFTER_YES


async def _phase(connection: AsyncConnection, *, request: Any, decision: Any, now: datetime) -> str:
    """Which of the closed vocabulary this request is in, in the order the protocol settles them.

    A decision is read first and a deadline last, because a decision that committed before its
    window closed is the answer for ever -- a page that checked the clock first would tell a
    customer who answered in time that they had missed it.
    """
    if decision is not None:
        return Phase.APPROVED if decision.decision == "APPROVE" else Phase.DECLINED
    if request.state == ApprovalRequestState.SUPERSEDED.value:
        return Phase.SUPERSEDED
    if request.state == ApprovalRequestState.EXPIRED.value:
        return Phase.EXPIRED
    if request.decided or request.state not in _OPEN_STATES:
        return Phase.CLOSED
    if request.deadline <= now:
        # The row has not been expired yet -- the timer runs on the worker's schedule, not the
        # browser's -- but no answer sent from this page could be accepted, and a button that
        # could not work is worse than the truth.
        return Phase.EXPIRED
    if await _answer_is_stored(connection, request_id=request.id, channel=request.customer_channel):
        return Phase.RECEIVED
    return Phase.OPEN


_OPEN_STATES: Final[frozenset[str]] = frozenset(
    {ApprovalRequestState.SENT.value, ApprovalRequestState.CONFIRMATION_PENDING.value}
)
"""The request states in which an answer can still be given, as the protocol defines them."""


async def _answer_is_stored(connection: AsyncConnection, *, request_id: UUID, channel: str) -> bool:
    """Whether this page's own answer for this request is already in the inbox.

    Asked by the record's derived id rather than by scanning replies, which is the same identity
    the answer was written under -- so this cannot disagree with what the unique index will do
    to a second press.
    """
    stored = await connection.scalar(
        select(InboxEvent.id).where(
            InboxEvent.source == handlers.CUSTOMER_REPLY_SOURCE,
            InboxEvent.provider_event_id == approvals.link_message_id(request_id, channel),
        )
    )
    return stored is not None


async def _product(connection: AsyncConnection, version_id: str | None) -> str | None:
    """A recipe version as a customer would recognise it, or nothing.

    The same phrasing the outbound message uses, for the same reason it uses it: the page and
    the message are about one change, and two spellings of one product is two changes to read.
    """
    if version_id is None:
        return None
    row = (
        await connection.execute(
            select(Recipe.name, RecipeVersion.version_no)
            .join(RecipeVersion, RecipeVersion.recipe_id == Recipe.id)
            .where(RecipeVersion.id == version_id)
        )
    ).one_or_none()
    return None if row is None else f"{row.name} (v{row.version_no})"


async def _resource(connection: AsyncConnection, resource_id: str | None) -> str | None:
    if resource_id is None:
        return None
    name: str | None = await connection.scalar(
        select(Resource.name).where(Resource.id == resource_id)
    )
    return name


__all__ = ["ANSWERABLE", "CLOSED_LINK", "CustomerApprovalView", "Phase", "read"]
