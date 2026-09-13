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


class TurnAccepted(BaseModel):
    """What the case engine did with one turn. A permission, never an outcome.

    ``attested_by`` is the worker the **server** attributed the statement to, echoed so a person
    can see whose name is on the record rather than assuming it is theirs. It is an answer, not an
    argument: nothing in the request could have changed it.

    ``speech`` is rendered by :mod:`promisepatch.domain.status_view` and is delivered to a person
    unchanged. A panel that re-worded it would be one word away from saying a plan was carried
    out, which is the failure this whole product exists not to have.
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
