"""The case row: locking it, and changing it through the audited boundary.

``cases`` is a governed table, so nothing here writes it outside a
:meth:`~promisepatch.db.uow.UnitOfWork.governed` block -- and the database refuses the write if
anything tries. What this module adds on top is the lock, which is what serialises a worker's
step against an owner's action on the same case, and the version bump, which is what an
optimistic reader elsewhere detects a concurrent change with.

**Where this sits in the lock order.** The case row is taken *after* the step row and *before*
any timer, inbox or outbox row, and before the event append. Every transaction in the system
takes these in the same order, which is what stops two of them from waiting on each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.db.models import Case
from promisepatch.db.uow import GovernedWrite
from promisepatch.domain.model import CaseChange


class CaseMissingError(RuntimeError):
    """A step names a case that does not exist.

    Not recoverable by retrying: the step is describing work on something that is not there.
    """


@dataclass(frozen=True, slots=True)
class LockedCase:
    """A case row this transaction holds exclusively until it ends."""

    id: UUID
    state: str
    version: int
    needs_owner_attention: bool


async def lock_case(connection: AsyncConnection, case_id: UUID) -> LockedCase:
    """Take the case row for update, and return what it says.

    A pessimistic lock rather than a version check, because the engine must not discover a
    conflict after doing the work: the point of holding it is that the handler reads a state
    nobody can change underneath it while the transaction decides what to do about it.
    """
    row = (
        await connection.execute(
            select(Case.id, Case.state, Case.version, Case.needs_owner_attention)
            .where(Case.id == case_id)
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise CaseMissingError(f"case {case_id} does not exist")
    return LockedCase(
        id=row.id,
        state=row.state,
        version=row.version,
        needs_owner_attention=row.needs_owner_attention,
    )


async def apply_case_change(
    write: GovernedWrite, *, case: LockedCase, change: CaseChange, now: datetime
) -> int:
    """Write the transition's effect on the case, and return its new version.

    The version is bumped on every consequential execution, whether or not the handler asked
    for a field to change. A step that ran and committed *is* a change to the case -- it is a
    different case afterwards, with different work outstanding -- and a reader that cached the
    old version has a stale view of it either way.
    """
    values: dict[str, object] = {"version": case.version + 1, "updated_at": now}
    if change.state is not None:
        values["state"] = change.state
    if change.needs_owner_attention is not None:
        values["needs_owner_attention"] = change.needs_owner_attention

    result = await write.execute(
        update(Case).where(Case.id == case.id, Case.version == case.version).values(**values)
    )
    if result.rowcount != 1:
        # Unreachable while the row lock is held, and asserted anyway: if it ever fires, the
        # lock discipline has been broken somewhere and the transition must not commit.
        raise CaseMissingError(
            f"case {case.id} changed under a held lock; expected version {case.version}"
        )
    return case.version + 1
