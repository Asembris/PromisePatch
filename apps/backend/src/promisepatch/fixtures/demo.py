"""The binding between the shipped example dataset and this deployment's demo state.

Everything bakery-specific — ids, names, quantities, due times, policies, who authored what —
lives in ``promise_graph.examples.hollow_oak`` and is referenced from here by name. Nothing is
restated. If a value in this module looked like a bakery fact, it would be a second copy of one,
and the demo would eventually disagree with the engine tests that assert the same numbers.

What *is* decided here is deployment-shaped: which shipped fixture the demo loads, and which
people the demo needs a login for. The two staff members are the fixture's own attesting worker
and its own recipe author, so even their identities are read off the dataset rather than typed
in again.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from promise_graph.examples import hollow_oak
from promise_graph.snapshot import GraphSnapshot
from promisepatch.fixtures.projection import StaffSeed

FIXTURE_NAME: Final = "hollow-oak"
"""Recorded on ``fixture_state`` so an operator can see which dataset is loaded."""

BAKER_ROLE: Final = "baker"
OWNER_ROLE: Final = "owner"

STAFF: Final[tuple[StaffSeed, ...]] = (
    StaffSeed(
        worker_id=hollow_oak.BAKER,
        username=hollow_oak.BAKER,
        display_name=hollow_oak.BAKER.capitalize(),
        role=BAKER_ROLE,
    ),
    StaffSeed(
        worker_id=hollow_oak.AUTHOR,
        username=hollow_oak.AUTHOR,
        display_name=hollow_oak.AUTHOR.capitalize(),
        role=OWNER_ROLE,
    ),
)
"""The two seeded logins: the worker who attests physical facts, and the owner who escalates.

Their ids are the same strings the fixture already attributes attestations and authorship to,
which is what makes an audit row naming an actor resolve to a row in ``workers``.
"""


def build_snapshot(anchor: datetime) -> GraphSnapshot:
    """The demo graph, with every instant measured from ``anchor``."""
    return hollow_oak.hollow_oak(anchor)
