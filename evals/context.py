"""The one kitchen every worker gold case is read against.

A gold case is a sentence plus a claim about what PromisePatch would do with it, and that
second half is meaningless without saying *which* bakery. So the vocabulary is pinned: the
shipped Hollow Oak dataset, at one fixed instant, projected into the same
:class:`~promisepatch.domain.observation.ObservationContext` the intake workflow hydrates from
persisted rows.

Pinning it is what makes a dataset reviewable. "``res-deck-oven`` is the expected identity" is
a checkable statement because the deck oven is in this context; a case naming an identifier
this context does not contain fails dataset validation rather than being scored against
nothing.

Nothing here reads a clock, a database or the environment. ``anchor`` is a constant, and the
day window around it is stated rather than computed, because the interpreter is never allowed
to work out what "today" means for itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Final
from uuid import UUID, uuid5

from promise_graph import availability
from promise_graph.examples import hollow_oak
from promise_graph.model import ReceivedState, ResourceKind
from promise_graph.snapshot import GraphSnapshot
from promisepatch.domain.observation import (
    CommitmentLineView,
    CommitmentView,
    ObservationContext,
    ReportKind,
    ResourceView,
    Statement,
)

ANCHOR: Final = hollow_oak.ANCHOR
"""The fixture's own instant. Deliveries and outages are measured from it."""

NOW: Final = ANCHOR + timedelta(hours=2)
"""Two hours in: today's Valley Produce delivery is due and overdue, which is the scenario."""

DAY_START: Final = datetime(ANCHOR.year, ANCHOR.month, ANCHOR.day, tzinfo=UTC)
DAY_END: Final = DAY_START + timedelta(days=1)
"""The bakery's calendar day around the anchor. Today's delivery is inside it; tomorrow's is not."""

REPORTER: Final = hollow_oak.BAKER
"""Whoever attests a physical fact in the fixture also speaks the sentences in the dataset."""

_STATEMENT_NAMESPACE: Final = UUID("0f8b6f9e-2c1a-4f6d-9a71-9d5f3c2b7e40")
"""Namespace for deriving a stable statement id from a case id. Fixed so runs are comparable."""


@lru_cache(maxsize=1)
def snapshot() -> GraphSnapshot:
    """The shipped example graph at the fixed anchor."""
    return hollow_oak.hollow_oak(ANCHOR)


@lru_cache(maxsize=1)
def resources() -> tuple[ResourceView, ...]:
    """Every resource the interpreter may name, in the shape it reads them in."""
    return tuple(
        ResourceView(
            id=resource.id,
            kind=resource.kind,
            name=resource.name,
            aliases=tuple(resource.aliases),
        )
        for resource in snapshot().resources.values()
    )


@lru_cache(maxsize=1)
def commitments() -> tuple[CommitmentView, ...]:
    """Every supplier delivery, with every line still expected.

    Expected rather than settled on purpose: a settled line is a fact somebody attested, and a
    dataset that shipped one would be asserting a physical outcome nobody in it observed.
    """
    graph = snapshot()
    return tuple(
        CommitmentView(
            id=commitment.id,
            supplier_id=commitment.supplier_id,
            supplier_name=graph.suppliers[commitment.supplier_id].name,
            due_at=commitment.due_at,
            lines=tuple(
                CommitmentLineView(
                    id=line.id,
                    resource_id=line.resource_id,
                    quantity=line.quantity,
                    received_state=ReceivedState.EXPECTED,
                )
                for line in commitment.lines
            ),
        )
        for commitment in graph.commitments.values()
    )


@lru_cache(maxsize=1)
def on_hand() -> dict[str, Decimal | None]:
    """What the ledger says is counted, for every ingredient the fixture stocks."""
    graph = snapshot()
    return {
        resource.id: availability.on_hand(graph, resource.id)
        for resource in graph.resources.values()
        if resource.kind is ResourceKind.INGREDIENT
    }


def observation_context(case_id: str, utterance: str) -> ObservationContext:
    """The context one worker case is read against: this kitchen, and that sentence.

    The statement id is derived from the case id rather than generated, so the request
    fingerprint of a case is the same on every machine and in every run.
    """
    statement = Statement(
        id=uuid5(_STATEMENT_NAMESPACE, case_id),
        kind=ReportKind.REPORT,
        raw_text=utterance,
        reported_by=REPORTER,
        observed_at=NOW,
    )
    return ObservationContext(
        now=NOW,
        day_start=DAY_START,
        day_end=DAY_END,
        resources=resources(),
        commitments=commitments(),
        on_hand=on_hand(),
        report=statement,
        current=statement,
    )


@lru_cache(maxsize=1)
def resource_ids() -> frozenset[str]:
    """Every resource and equipment identifier this context contains."""
    return frozenset(item.id for item in resources())


__all__ = [
    "ANCHOR",
    "DAY_END",
    "DAY_START",
    "NOW",
    "REPORTER",
    "commitments",
    "observation_context",
    "on_hand",
    "resource_ids",
    "resources",
    "snapshot",
]
