"""``GET /api/cases`` and ``GET /api/cases/{case_id}`` -- the first case workspace.

Two reads and no writes, and there will not be a write here. A worker changes a case by saying
something, through the conversational surface and the intent API behind it, where the
attestation, the confirmation and the audit row are governed together. A browser button that
posted a state change would be a second authority with none of that machinery around it.

**The same permission the tools enforce, widened once and only for reading.**
``require_readable`` is the domain's answer to "may this worker be *shown* that case": whoever
may speak on it, plus an observer. It is a different function from the ``require_permitted``
every write gates on, which is unchanged -- so nothing here can widen a write, and the answer to
"may I read somebody else's case" is still the domain's rather than the transport's convenience.

**Existence before permission**, so the two refusals stay different answers. Case ids are
UUIDs and the caller holds a live session, so this is not an enumeration surface, and a screen
that could not tell "no such case" from "not yours" would have to guess which it was.

**Nothing here composes a sentence.** The response is built by
:mod:`promisepatch.api.views.cases` from one projection of one durable read. This module
authenticates, resolves and hands back.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.api.dependencies import DatabaseDep, PrincipalDep
from promisepatch.api.errors import ApiError
from promisepatch.api.schemas.cases import CaseListResponse, CaseWorkspaceResponse
from promisepatch.api.views import cases as view
from promisepatch.db.models import Case
from promisepatch.domain import analysis, intake

router = APIRouter(prefix="/api", tags=["cases"])

DEFAULT_LIMIT: Final = 20
MAX_LIMIT: Final = 100

NO_SUCH_CASE = ApiError(status_code=404, code="CASE_NOT_FOUND", message="no case by that id")

NOT_PERMITTED = ApiError(
    status_code=403,
    code="CASE_NOT_PERMITTED",
    message="this worker may not read that case",
)


@router.get("/cases", response_model=CaseListResponse, summary="The cases a worker can open")
async def list_cases(
    principal: PrincipalDep,
    database: DatabaseDep,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> CaseListResponse:
    """Every case, newest first.

    Newest first because a bakery's question is "what is happening now", and a bounded page
    because a list that grew without limit would eventually be a read a worker waits for.
    """
    async with database.connect() as connection:
        return await view.summaries(connection, limit=limit)


@router.get(
    "/cases/{case_id}",
    response_model=CaseWorkspaceResponse,
    summary="One case, as the workspace shows it",
)
async def read_case(
    case_id: UUID,
    principal: PrincipalDep,
    database: DatabaseDep,
) -> CaseWorkspaceResponse:
    """The five bands of one case, projected from the durable case and from nothing else.

    A reload of this URL after a restarted worker, a dropped stream or a closed browser lands
    on the same case in the same state, because every value in the answer is a row somebody
    committed rather than anything this process was holding.
    """
    async with database.connect() as connection:
        if not await connection.scalar(select(Case.id).where(Case.id == case_id)):
            raise NO_SUCH_CASE
        try:
            await intake.require_readable(
                connection, case_id=case_id, worker_id=principal.worker_id
            )
        except intake.NotPermittedError as error:
            raise NOT_PERMITTED from error
        # Asked here, where the caller is known, and answered by the same function every write
        # gates on. The screen is then told what it may offer instead of reading a role and
        # deciding for itself -- and the domain refuses the call again either way.
        may_speak = await _may_speak(connection, case_id=case_id, worker_id=principal.worker_id)
        opening = await view.first_report(connection, case_id=case_id)

    try:
        status = await analysis.read_case_status(database, case_id=case_id)
    except analysis.CaseNotFoundError as error:
        raise NO_SUCH_CASE from error
    return view.build(status, opening=opening, may_speak=may_speak)


async def _may_speak(connection: AsyncConnection, *, case_id: UUID, worker_id: str) -> bool:
    """Whether the domain would let this caller say anything to this case.

    ``require_permitted`` itself, called and caught, rather than a rule restated here. A copy of
    "the opener or an owner" in this module would be a second answer to the question, and the two
    would eventually disagree about somebody on a screen that claims to be the truthful one.
    """
    try:
        await intake.require_permitted(connection, case_id=case_id, worker_id=worker_id)
    except intake.NotPermittedError:
        return False
    return True
