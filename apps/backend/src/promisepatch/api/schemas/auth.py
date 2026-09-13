"""Authentication contracts.

The response type is the interesting one: it is a deliberately narrow projection of the
``workers`` row. ``password_hash`` is not on it, the session id is not on it, and the CSRF
token is not on it -- ``extra="forbid"`` plus an explicit field list means a column added to
the table later cannot start being served by accident.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """Credentials. Bounded lengths so an oversized body is rejected before it is hashed."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class WorkerIdentity(BaseModel):
    """Everything a client may know about the logged-in worker, and nothing more."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    username: str
    display_name: str
    role: str
    may_report: bool = Field(
        description=(
            "whether the domain would accept a physical claim from this principal at all, "
            "asked of promisepatch.domain.intake.may_attest rather than worked out from role"
        )
    )
    """Whether this principal may open a case by saying what happened.

    Here rather than left to a screen, for the same reason ``may_speak`` is on the case
    response: a surface that read ``role`` and decided for itself would be a second copy of the
    domain's rule, in a language this suite does not test, and the two would eventually disagree
    about somebody. The domain refuses a write regardless of what was drawn; what this field
    buys is that the screen never *offers* what would be refused.
    """


class WorkerResponse(BaseModel):
    """The body of ``login`` and of ``me``: one shape for "who am I"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    worker: WorkerIdentity


class SignInOptions(BaseModel):
    """What ways in this deployment offers, so a screen draws the ones that exist.

    Unauthenticated, and deliberately so: it is read by the sign-in screen, which by definition
    has no session. It says nothing about anybody -- no username, no principal, no count -- only
    what this deployment serves, which is the same thing a judge is meant to discover by looking
    at the page.

    It exists so the screen does not have to *probe*. A control drawn on the hope that an endpoint
    is there is a control that can be dead on arrival, and the P7.1 contract forbids drawing a
    capability that does not exist. One field now; a second way in would be a second field rather
    than a second guess.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    demo_session: bool = Field(
        description="whether POST /api/auth/demo-session is served by this deployment"
    )
