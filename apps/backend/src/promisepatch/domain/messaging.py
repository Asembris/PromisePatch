"""The customer-facing approval message, composed from persisted facts and nothing else.

Pure: a dataclass of values in, a string out. No database, no clock, no provider, no model. The
step that sends the message reads the rows; this module decides only how they read to a person.

Three properties are load-bearing, and all three are §13.6 and §16 rather than house style.

* **The reply instruction is a frozen literal.** :data:`CONSENT_INSTRUCTION` is appended
  verbatim, and :func:`carries_required_literals` checks it -- and the option code -- are
  present before anything is enqueued. Today the text is composed deterministically and the
  check cannot fail; it exists because the slice that lets a model draft the wording is the one
  where it can, and the guard has to predate the drafter rather than follow it.
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
    "Reply YES to approve this change or NO to decline it. "
    "If you decline, the bakery will follow up."
)
"""The frozen sentence, quoted from §13.6 and reproduced exactly.

It is the only instruction the customer is given, and it is what the literal parser enforces on
the other side: the two words it invites are the two words that mean anything.
"""

CONFIRMATION_INSTRUCTION: Final = "To confirm this change, reply YES. Reply NO to decline."
"""The frozen confirmation sentence, quoted from §13.6 and reproduced exactly.

Sent after a reply the literal parser could not read, and identical whatever a model made of
that reply. §13.6 gives all three apparent-intent labels -- and the deterministic fallback for
that job -- the same single prompt, so the words a customer sees do not vary with a model's
opinion of them. That is not a simplification of the protocol; it is the protocol, and it is
what stops the message from teaching the customer that something already read their mind.

It names the two words that count, because a prompt that asked for confirmation without saying
in what form would invite a second sentence nobody can act on.
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
    lines.append(CONSENT_INSTRUCTION)
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
            CONFIRMATION_INSTRUCTION,
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


def carries_required_literals(text: str, *, option_code: str) -> bool:
    """Whether an outbound message may be sent at all.

    The pre-send check from §13.6, kept as a separate function so the drafting side can change
    without the guard moving with it. A message missing either literal is not sent as written;
    the caller falls back to the composed template, which contains both by construction.
    """
    return CONSENT_INSTRUCTION in text and option_code in text


def carries_confirmation_literals(text: str, *, option_code: str) -> bool:
    """Whether a confirmation prompt may be sent at all.

    The same pre-send shape as :func:`carries_required_literals`, against the sentence §13.6
    fixes for this message. Separate rather than parameterised, because the two messages invite
    different words and a single guard that accepted either would accept the wrong one.
    """
    return CONFIRMATION_INSTRUCTION in text and option_code in text


__all__ = [
    "CONFIRMATION_INSTRUCTION",
    "CONSENT_INSTRUCTION",
    "ApprovalMessage",
    "build_approval_request",
    "build_confirmation_prompt",
    "carries_confirmation_literals",
    "carries_required_literals",
    "render_due",
]
