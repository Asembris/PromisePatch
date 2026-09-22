"""The customer-facing approval message, composed from persisted facts and nothing else.

Pure: a dataclass of values in, a string out. No database, no clock, no provider, no model. The
step that sends the message reads the rows; this module decides only how they read to a person.

Four properties are load-bearing, and all four are §13.6, §16 and ADR-0021 rather than
house style.

* **The answering instruction is a frozen literal.** :data:`CONSENT_INSTRUCTION` is appended
  verbatim, and :func:`carries_required_literals` checks it -- and the option code -- are
  present before anything is enqueued. Today the text is composed deterministically and the
  check cannot fail; it exists because the slice that lets a model draft the wording is the one
  where it can, and the guard has to predate the drafter rather than follow it.
* **It names the only door that opens.** Per ADR-0021 the instruction sends the customer to the
  signed link the message carries, because that link is the one and only way an answer reaches
  the consent protocol. There is no inbound message path, deliberately -- a second door for the
  word ``YES`` would be a second consent parser -- so an instruction inviting a reply on the
  channel would be inviting one into nothing. A deployment that mints no link therefore gets
  :data:`CONSENT_WITHOUT_LINK_INSTRUCTION`, which invites no answer at all rather than one that
  could not arrive.
* **Nothing here promises the original.** Declining does not restore an ingredient that did not
  arrive, so the message says the bakery will follow up and never says the order will be made
  as first agreed. Saying otherwise would be a promise the kitchen has no way to keep.
* **Nothing here asserts safety.** The message names the exact change and stops. PromisePatch
  has no allergen knowledge (§16.1), so there is no sentence in this module that could imply
  it does -- no "should be fine", no reassurance, no dietary claim.

The wording is generic by construction: every noun a customer reads is a column value, so the
same builder serves any bakery, and no fixture's customers or recipes appear in this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CONSENT_INSTRUCTION: Final = (
    "Open the secure link below to approve or decline this change. "
    "If you decline, the bakery will follow up."
)
"""The frozen sentence a customer is given when this deployment mints a link.

ADR-0021 replaces §13.6's "Reply YES to approve this change or NO to decline it." with this.
The second clause is §13.6's own and is reproduced exactly; the first named a way to answer
that does not exist, and a real customer typed a literal ``YES`` into the bot's chat on
2026-09-22 and reached nothing -- ``inbound_replies`` 0, ``approval_decisions`` 0, ``getUpdates``
calls 0. See [`deployed-customer-channel.md`](../../../../../docs/deployed-customer-channel.md)
section 10.7.

What the customer does on the other side of that link is unchanged: two buttons, each writing
one of the two literal words, into the one parser that has ever been able to read a yes. The
protocol did not move -- only the sentence that says where to find it.
"""

CONSENT_WITHOUT_LINK_INSTRUCTION: Final = (
    "This message cannot take your answer, so nothing about your order changes because of it. "
    "The bakery will follow up."
)
"""What is said instead where the deployment signs no links, and therefore opens no door.

Not a question, and deliberately not one. With no link there is no surface on which this
customer could answer, so a sentence inviting an answer would be the same lie in a new spelling.
Both of its claims hold by construction: no consent means no amendment, and an unanswered
request reaches its deadline and escalates the promise to its owner, which is the bakery
following up.

It is never sent by the deployed product, which has minted a link since its first delivery. It
is what a deployment configured without
:attr:`~promisepatch.config.Settings.customer_link_secret` sends, and it exists so that the
degraded configuration is honest rather than merely untested.
"""

CONFIRMATION_INSTRUCTION: Final = (
    "To approve or decline this change, use the secure link in our earlier message."
)
"""The frozen confirmation sentence, sent where a link exists.

It points **backwards**, and that is not a stylistic choice. The confirmation prompt's effect
payload carries no ``approval_url`` -- only the approval request's does -- so a prompt that said
"the link below" would name a line the transport was never given anything to write. The link the
customer already holds is the right one anyway: it is derived from the request and the channel,
so it is the same string a second mint would produce, and it opens the same single question.

Sent after a reply the literal parser could not read, and identical whatever a model made of
that reply. §13.6 gives all three apparent-intent labels -- and the deterministic fallback for
that job -- the same single prompt, so the words a customer sees do not vary with a model's
opinion of them. That is not a simplification of the protocol; it is the protocol, and it is
what stops the message from teaching the customer that something already read their mind.

ADR-0021 moves it from naming two words to naming the link, for the reason
:data:`CONSENT_INSTRUCTION` moved: the words were not readable from anywhere the customer could
type them.
"""

CONFIRMATION_WITHOUT_LINK_INSTRUCTION: Final = (
    "This message cannot take your answer. The bakery will follow up."
)
"""The confirmation prompt's no-link form, for the reason :data:`CONSENT_WITHOUT_LINK_INSTRUCTION`
has one: a prompt asking again on a channel that cannot hear is worse than one that says so."""


CONSENT_INSTRUCTIONS: Final = (CONSENT_INSTRUCTION, CONSENT_WITHOUT_LINK_INSTRUCTION)
CONFIRMATION_INSTRUCTIONS: Final = (
    CONFIRMATION_INSTRUCTION,
    CONFIRMATION_WITHOUT_LINK_INSTRUCTION,
)
"""Both forms of each instruction, so a guard can refuse a text carrying *any* of them.

:func:`carries_supersede_literals` is the reader: a notice that invited an answer in either
spelling would be a second question the customer's answer could not be applied to, and a guard
that knew only the link form would have stopped catching that the moment the second form
existed.
"""


SUPERSEDE_NOTICE: Final = (
    "Your order changed after we asked you about it, so that request no longer applies, "
    "and nothing was done to your order because of it."
)
"""§14.4's one message, and the only place a customer may receive a second one in the MVP.

A notice, not a question. It carries neither :data:`CONSENT_INSTRUCTION` nor
:data:`CONFIRMATION_INSTRUCTION`, and there is no word a customer could send back that would
mean anything -- which is why the builder below invites none.

**It says that their order changed, so it is sent only where that is true.** §14.4 words the
message as "explaining that their order changed", and §23 puts it in the row headed "order
changes while approval pending". A re-plan whose cause was something else -- stock consumed
elsewhere, a constraint rewritten, a task started -- has not changed this customer's order, and
telling them it did would be the one thing this module may never do.

"nothing was done to your order because of it" is a claim about the world, and it holds by
construction on every path that reaches here: a plan goes stale *before* its amendment, so the
request being voided never became a write.
"""

SUPERSEDE_FOLLOW_UP: Final = "If we still need your permission, we will send a new request."
"""§14.4's "and a new request (if any) follows", worded so that either outcome keeps it true.

Whether the fresh plan needs asking at all is decided after this message is composed, so
promising a new request outright would be a promise this module cannot keep. Saying nothing
would leave a customer whose last word was a yes with no idea whether anybody is coming back.
"""


@dataclass(frozen=True, slots=True)
class ApprovalMessage:
    """Everything the message says, read from rows before this module is called.

    Every field is optional except the ones a message cannot be written without, because the
    builder must degrade into a plainer sentence rather than into a placeholder a customer
    would read. A missing recipe name costs detail; it never costs the instruction.
    """

    customer_name: str
    order_reference: str
    option_code: str
    due_at: datetime | None = None
    timezone: str = "UTC"
    from_product: str | None = None
    to_product: str | None = None
    affected_resource: str | None = None
    substitute_resource: str | None = None
    link_available: bool = False
    """Whether this deployment will attach a signed link to the message being composed.

    Not the link itself, and deliberately not. This module composes words and must stay pure in
    its arguments; the URL is minted inside the transaction that creates the request, appended
    beside the text by the transport, and never rendered here. What the builder needs is only
    whether there will *be* one, because that decides which instruction is true.

    It defaults to ``False`` -- the degraded, invites-nothing form -- so a caller that has not
    been taught about links cannot accidentally promise one. The cost of forgetting is then a
    message that asks for no answer, which a deadline and an escalation already handle; the
    opposite default would send a customer looking for a link nobody attached.
    """


def render_due(moment: datetime, timezone: str) -> str:
    """The due time as the kitchen's clock shows it, in a format that does not vary by locale.

    ``%Y-%m-%d %H:%M`` rather than a written-out weekday: ``strftime``'s names follow whatever
    locale the process happens to be in, and a message whose wording depends on a container's
    environment is a message no test can pin down.
    """
    try:
        local = moment.astimezone(ZoneInfo(timezone))
    except (ZoneInfoNotFoundError, ValueError):
        local, timezone = moment, "UTC"
    return f"{local:%Y-%m-%d %H:%M} ({timezone})"


def consent_instruction(*, link_available: bool) -> str:
    """Which of the two frozen consent sentences is true for this deployment.

    One function rather than a conditional at each call site, so the builder and the guard that
    checks the builder's output cannot disagree about which sentence was owed. That pairing is
    the whole value of the pre-send check: a guard reading a different constant from the one the
    drafter wrote would pass every message and catch nothing.
    """
    return CONSENT_INSTRUCTION if link_available else CONSENT_WITHOUT_LINK_INSTRUCTION


def confirmation_instruction(*, link_available: bool) -> str:
    """Which of the two frozen confirmation sentences is true for this deployment."""
    return CONFIRMATION_INSTRUCTION if link_available else CONFIRMATION_WITHOUT_LINK_INSTRUCTION


def build_approval_request(message: ApprovalMessage) -> str:
    """Compose the outbound approval request.

    The change is described in the customer's terms -- the product they ordered, the product
    they would get -- and the ingredient substitution is named beneath it when the option
    records one, because §16.7 requires the exact substitute to be named rather than alluded to.
    """
    lines = [f"Hello {message.customer_name},", ""]

    due = "" if message.due_at is None else f", due {render_due(message.due_at, message.timezone)}"
    lines.append(
        f"An ingredient for your order {message.order_reference}{due} did not arrive, "
        "so we cannot make it exactly as ordered."
    )
    lines.append("")
    lines.append(_change(message))
    if message.affected_resource and message.substitute_resource:
        lines.append(
            f"That change uses {message.substitute_resource} in place of "
            f"{message.affected_resource}."
        )
    lines.append("")
    lines.append(f"Change reference: {message.option_code}")
    lines.append("")
    lines.append(consent_instruction(link_available=message.link_available))
    return "\n".join(lines)


def build_confirmation_prompt(message: ApprovalMessage) -> str:
    """Compose the one confirmation prompt §13.6 allows per request.

    Deliberately short, deliberately incurious, and deliberately the same for every reply that
    reached it. It says that the reply was not recorded as an answer, names the change reference
    so the customer knows which conversation this is, and asks for one of the two words.

    Three things it never does, each of them a rule rather than a preference:

    * **It does not quote the customer back at themselves.** Repeating "you said strawberries
      work" would put a reading of their words in a message they might answer NO to.
    * **It does not say what PromisePatch thinks they meant.** "It sounds like you approve" is
      an anchor, and an anchor placed by a model's label is a model influencing consent.
    * **It does not restate the change.** The original request named the exact substitution and
      is the message this one is about; a second description is a second chance to get it wrong.
    """
    return "\n".join(
        [
            f"Hello {message.customer_name},",
            "",
            f"We could not record your last message about order {message.order_reference} "
            "as an answer.",
            "",
            f"Change reference: {message.option_code}",
            "",
            confirmation_instruction(link_available=message.link_available),
        ]
    )


def build_supersede_notice(message: ApprovalMessage) -> str:
    """Compose §14.4's supersede notice: the customer's order moved, so the ask is void.

    Short, and deliberately incurious about what changed. PromisePatch did not make the edit and
    has no business narrating somebody's own order back at them; what it owes them is that the
    question they were asked no longer stands and that nothing was done on the strength of it.

    It names the change reference so the customer knows which conversation this ends, and it
    does not restate the change itself -- the original request named the exact substitution and
    is the message this one is about.
    """
    return "\n".join(
        [
            f"Hello {message.customer_name},",
            "",
            f"About your order {message.order_reference}:",
            "",
            SUPERSEDE_NOTICE,
            "",
            f"Change reference: {message.option_code}",
            "",
            SUPERSEDE_FOLLOW_UP,
        ]
    )


def _change(message: ApprovalMessage) -> str:
    """One sentence naming what the customer would receive instead, however much we know.

    The fallback is deliberately vague about the product and exact about the reference, because
    a customer who cannot tell what changed can still quote the code to the bakery -- whereas a
    message that invented a product name to fill the gap would be worse than a vague one.
    """
    if message.from_product and message.to_product:
        return f"We propose to make {message.to_product} instead of {message.from_product}."
    if message.to_product:
        return f"We propose to make {message.to_product} instead."
    return "We propose one change to that item, recorded under the reference below."


def carries_required_literals(text: str, *, option_code: str, link_available: bool) -> bool:
    """Whether an outbound message may be sent at all.

    The pre-send check from §13.6, kept as a separate function so the drafting side can change
    without the guard moving with it. A message missing either literal is not sent as written;
    the caller falls back to the composed template, which contains both by construction.

    ``link_available`` is required rather than defaulted, and that is the point of the argument:
    the guard must be told which sentence was owed, so a message composed for a deployment that
    mints links cannot be waved through by a guard checking the sentence for one that does not.
    A default would decide that question silently on behalf of a caller that forgot to, which is
    exactly the mistake a pre-send check exists to catch.
    """
    return consent_instruction(link_available=link_available) in text and option_code in text


def carries_confirmation_literals(text: str, *, option_code: str, link_available: bool) -> bool:
    """Whether a confirmation prompt may be sent at all.

    The same pre-send shape as :func:`carries_required_literals`, against the sentence §13.6
    fixes for this message. Separate rather than parameterised, because the two messages say
    different things and a single guard that accepted either would accept the wrong one.
    """
    return confirmation_instruction(link_available=link_available) in text and option_code in text


def carries_supersede_literals(text: str, *, option_code: str) -> bool:
    """Whether a supersede notice may be sent at all.

    The same pre-send shape as the other two guards, against the two sentences §14.4 fixes for
    this message. Separate rather than parameterised, because this one must *not* accept a text
    carrying an answering instruction: a notice that told the customer how to approve would be a
    second question their answer could not be applied to.

    It refuses **every** form of both instructions rather than the link form alone, which is why
    :data:`CONSENT_INSTRUCTIONS` and :data:`CONFIRMATION_INSTRUCTIONS` exist. A guard that knew
    only the sentence its own deployment sends would stop catching the other one, and a notice
    is a notice on every deployment.
    """
    return (
        SUPERSEDE_NOTICE in text
        and SUPERSEDE_FOLLOW_UP in text
        and option_code in text
        and not any(instruction in text for instruction in CONSENT_INSTRUCTIONS)
        and not any(instruction in text for instruction in CONFIRMATION_INSTRUCTIONS)
    )


__all__ = [
    "CONFIRMATION_INSTRUCTION",
    "CONFIRMATION_INSTRUCTIONS",
    "CONFIRMATION_WITHOUT_LINK_INSTRUCTION",
    "CONSENT_INSTRUCTION",
    "CONSENT_INSTRUCTIONS",
    "CONSENT_WITHOUT_LINK_INSTRUCTION",
    "SUPERSEDE_FOLLOW_UP",
    "SUPERSEDE_NOTICE",
    "ApprovalMessage",
    "build_approval_request",
    "build_confirmation_prompt",
    "build_supersede_notice",
    "carries_confirmation_literals",
    "carries_required_literals",
    "carries_supersede_literals",
    "confirmation_instruction",
    "consent_instruction",
    "render_due",
]
