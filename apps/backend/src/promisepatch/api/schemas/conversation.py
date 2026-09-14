"""The wire shapes of the browser conversation, and the two fields deliberately absent from them.

**No actor field and no timestamp field**, exactly as on the internal intent API and for exactly
the same reason. Who is speaking comes from the session row behind an ``HttpOnly`` cookie this
process issued; when they spoke is read from this server's clock. Neither is a value a request
can carry, so there is nothing for a page, a script or a compromised extension to fill in with a
name it preferred -- a field that could carry an actor is an authority somebody eventually gets to
choose.

``extra="forbid"`` everywhere for the same reason. A request arriving with a ``worker_id`` it
invented is rejected outright rather than quietly ignored, so a caller labouring under that
misunderstanding finds out immediately rather than believing it worked.

``command_id`` is the one identity the caller does choose, and it is not an authority: it names
*this* statement so that a redelivery is one statement arriving twice. A different request under
an id already used is a conflict, loudly, because two different things were said and only one of
them can be what happened. It cannot name a worker, a case that was not derived from it, or a
moment.

Every response says what the command was permitted to do and never what it completed. Nothing has
been sent, no order has been amended and no customer has been asked when one of these returns.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from promisepatch.semantic.contracts import MAX_UNTRUSTED_CHARACTERS


class ReportTurn(BaseModel):
    """One spoken physical exception, typed into the conversation panel."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: UUID = Field(
        description="stable command identity; a redelivery must reuse it, and it derives the case"
    )
    text: str = Field(
        min_length=1,
        max_length=MAX_UNTRUSTED_CHARACTERS,
        description=(
            "what the worker said, verbatim. Stored exactly as sent, before anything is "
            "concluded from it. The bound is the semantic boundary's own, so an input this "
            "application could not carry is refused here rather than deeper in."
        ),
    )


class ClarifyTurn(BaseModel):
    """A worker's answer to the one question this case is waiting on.

    An answer, and nothing else. There is no field for which question is being answered, because
    a case has at most one open and choosing among several would be an authority; and no field
    for a physical outcome, because the words are resolved by the worker process against the
    options captured from the delivery's own rows when the question was asked.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: UUID = Field(description="stable command identity; a redelivery must reuse it")
    case_id: UUID
    text: str = Field(
        min_length=1,
        max_length=MAX_UNTRUSTED_CHARACTERS,
        description="what the worker answered, verbatim. Stored exactly as sent.",
    )


class ConfirmTurn(BaseModel):
    """A worker's yes to one specific plan.

    ``plan_id`` is the whole difference between this and a blanket authorisation. It is the
    identity of the plan the case response presented, and the domain checks it against the plan
    the case is currently offering, under the lock the confirmation is written with -- so a yes
    cannot land on a plan that was re-made after the worker read it.

    There is no ``confirmed: bool``. A false one would be a withdrawal wearing a confirmation's
    name, and withdrawal is its own capability with its own rules; calling this endpoint *is* the
    yes. It is also not a customer's consent, which is a literal reply on that customer's own
    channel and cannot be produced by anybody pressing a button in this building.

    ``text`` is the one field a spoken confirmation adds, and its **absence** is as meaningful as
    its presence (ADR-0015). Omitted, the explicit confirmation control was pressed and the press
    itself is the yes: there is no sentence to read and none is invented, because a screen that
    filled this in on a worker's behalf would be composing an attestation nobody made. Present, it
    is what the worker actually said, and the route reads it with the closed literal rule the
    conversational orchestrator already uses -- so a sentence that is not a plain yes confirms
    nothing. Either way ``plan_id`` decides *which* plan a yes is about, and nothing here can
    widen that.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: UUID = Field(description="stable command identity; a redelivery must reuse it")
    case_id: UUID
    plan_id: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "the identity of the plan being confirmed, exactly as the case response returned it. "
            "Opaque: it names a plan the server rendered and cannot describe one it did not."
        ),
    )
    text: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_UNTRUSTED_CHARACTERS,
        description=(
            "what the worker said, verbatim, when they said it rather than pressed it. Read by "
            "the server with the existing literal rule and never by the caller; omit it for the "
            "explicit control, whose press is itself the yes."
        ),
    )


class WithdrawTurn(BaseModel):
    """A worker withdrawing an exception they no longer stand behind.

    A case and a command identity, and nothing else. No reason field, because a reason is not an
    authority; no field naming what to reverse, because what is reversible is decided from rows
    under the case lock; and no field that could name a physical fact, because withdrawing a plan
    is not a claim about the kitchen and correcting one is a separate attestation this panel
    cannot reach.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: UUID = Field(description="stable command identity; a redelivery must reuse it")
    case_id: UUID


class WithdrawalAccepted(BaseModel):
    """What a withdrawal stopped, and -- never omitted -- what it could not stop.

    Both lists are sentences the **domain** composed, delivered to a person unchanged. ``applied``
    is the half that keeps this honest: every entry is something a customer or the order system
    already has. A screen that rendered only ``reversed_writes`` would be drawing a rollback that
    did not happen, which is why the field is on the response rather than left to a caller to
    work out from counts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: UUID
    command_id: UUID
    state: str
    created: bool = Field(
        description="false for a redelivery of a withdrawal already accepted, which is a success"
    )
    withdrawn_by: str = Field(
        description="the worker this server attributed the withdrawal to, from the session row"
    )
    withdrawn: int = Field(description="promises taken out of the case with nothing carried out")
    escalated: int = Field(
        description="promises handed to the owner because something had already gone out"
    )
    reversed_writes: tuple[str, ...] = Field(
        default=(), description="what was stood down, each already true when this returns"
    )
    applied: tuple[str, ...] = Field(
        default=(),
        description=(
            "what had already happened and is **not** undone. Empty only when nothing had."
        ),
    )
    speech: str = Field(description="what to say back, rendered deterministically by the domain")
    spoken: str = Field(
        description="the same answer composed short enough to hear, inside the G7 word budget"
    )


class TurnAccepted(BaseModel):
    """What the case engine did with one turn. A permission, never an outcome.

    ``attested_by`` is the worker the **server** attributed the statement to, echoed so a person
    can see whose name is on the record rather than assuming it is theirs. It is an answer, not an
    argument: nothing in the request could have changed it.

    ``speech`` is rendered by :mod:`promisepatch.domain.status_view` and is delivered to a person
    unchanged. A panel that re-worded it would be one word away from saying a plan was carried
    out, which is the failure this whole product exists not to have.

    ``spoken`` is the same answer, composed shorter by the same module for a worker who is
    listening rather than reading (ADR-0014). Both are the backend's: a browser chooses which
    one to read aloud and which to show, and composes neither.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: UUID
    statement_id: UUID
    state: str
    created: bool = Field(
        description="false for a redelivery of a request already accepted, which is a success"
    )
    attested_by: str = Field(
        description="the worker this server attributed the statement to, from the session row"
    )
    speech: str = Field(description="what to say back, rendered deterministically by the domain")
    spoken: str = Field(
        description="the same answer composed short enough to hear, inside the G7 word budget"
    )
