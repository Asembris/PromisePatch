"""Who the domain admits to a case, characterised against real rows before anything widens it.

``intake.require_permitted`` is the one function every write in this system passes through: the
operator CLI, the intent API behind the MCP tools, and the recovery confirmation all call it, and
none of them re-implements it. That makes it the thing a later change is most likely to widen by
accident, and the reason this file exists is to make such a widening fail here first.

The table below is therefore not "some cases that should work". It is **the whole answer**: one
row per kind of principal this deployment can have, each asserted positively or negatively, so a
new admission has to change a literal in this file rather than slip through a gap between tests.

Nothing here arranges a case by inserting one. The case is opened by a worker reporting, exactly
as it is in production, because a permission check reads ``cases.opened_by`` and a hand-written
row would prove only that the query runs.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from _intake_support import BAKER, OWNER, Intake
from _intake_support import physical as physical

from promisepatch.domain import intake

pytestmark = pytest.mark.integration

STRANGER = "sam"
"""A second baker. Present in the bakery, absent from this case."""

OBSERVER = "onlooker"
"""A principal with the observer role. It is never the opener and it is never an owner."""


async def permitted(physical: Intake, case_id: UUID, worker_id: str) -> bool:
    """Whether the domain would let this worker speak on this case. The function itself, called."""
    async with physical.database.connect() as connection:
        try:
            await intake.require_permitted(connection, case_id=case_id, worker_id=worker_id)
        except intake.NotPermittedError:
            return False
    return True


async def test_the_worker_who_opened_the_case_may_speak_on_it(physical: Intake) -> None:
    opened = await physical.report()

    assert await permitted(physical, opened.case_id, BAKER)


async def test_an_owner_may_speak_on_a_case_they_did_not_open(physical: Intake) -> None:
    """Escalation is the owner's to resolve, so the owner is admitted to every case."""
    opened = await physical.report()

    assert await permitted(physical, opened.case_id, OWNER)


async def test_another_baker_may_not_speak_on_somebody_elses_case(physical: Intake) -> None:
    """A physical attestation is worth something only if the person was there to see it."""
    opened = await physical.report()

    async with physical.another_worker(STRANGER, role="baker") as stranger:
        assert not await permitted(physical, opened.case_id, stranger)


async def test_an_observer_may_not_speak_on_any_case(physical: Intake) -> None:
    """The role the database now admits is admitted to nothing by this function.

    This is the property the read widening below rests on: because every write gates here, and
    here has no branch for an observer, a write route added later with no observer check of its
    own still refuses one. The refusal is the domain's rather than the transport's.
    """
    opened = await physical.report()

    async with physical.another_worker(OBSERVER, role="observer") as observer:
        assert not await permitted(physical, opened.case_id, observer)


async def test_a_worker_who_does_not_exist_may_not_speak(physical: Intake) -> None:
    """An id nobody holds is refused by the same answer as an id somebody else holds."""
    opened = await physical.report()

    assert not await permitted(physical, opened.case_id, "nobody-by-that-name")
