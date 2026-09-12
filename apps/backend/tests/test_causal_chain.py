"""The path from the exception to one promise, projected out of the rows that stored it.

Pure tests over a pure function: no database, no engine, no transport. What they guard is not a
crash but a fabrication -- a chain assembled out of two traversals, a path shown for a promise
nothing reached, a node named with an identifier the bands forbid, or a count taken from the
steps that happen to be on screen instead of from the rows that exist.

The negative cases carry the weight here. A stored path with no readable node, a track whose
rule no path carries, a node with no durable name and an untouched promise that *was* reached
and simply put in no danger are all states this projection has to say something honest about,
and none of them may say it by inventing a route.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from promisepatch.domain.analysis import (
    NodeFact,
    PathNodeStatus,
    TrackPathStatus,
    TrackStatus,
)
from promisepatch.domain.causal import (
    NO_DECIDING_PATH,
    NO_PATH_STORED,
    UNREADABLE,
    CausalSlot,
    chain_for,
)

RASPBERRY_DELIVERY = "cl-valley-raspberry"
RASPBERRY = "res-raspberry"
CHARLOTTE_V2 = "rv-charlotte-2"
LINE_A = "ol-a1"
PROMISE_A = "pr-a"

FACTS = {
    RASPBERRY_DELIVERY: NodeFact(
        kind="COMMITMENT_LINE",
        name="Raspberries",
        unit="kg",
        supplier="Valley Produce",
        quantity=Decimal("4.000"),
        received_state="NOT_RECEIVED",
    ),
    RASPBERRY: NodeFact(kind="RESOURCE", name="Raspberries", unit="kg"),
    CHARLOTTE_V2: NodeFact(kind="RECIPE_VERSION", name="Raspberry Charlotte", version_no=2),
    LINE_A: NodeFact(kind="ORDER_LINE", name="EXT-A"),
}

QUANTIFIED = {
    "order_line_id": LINE_A,
    "resource_id": RASPBERRY,
    "roles": ["FILLING"],
    "need": "4.000",
    "available_before_start": "1.200",
    "shortfall": "2.800",
    "satisfied": False,
    "unknown": False,
}


def nodes(*refs: str) -> tuple[PathNodeStatus, ...]:
    """The canonical supply traversal: delivery line, resource, version, order line, promise."""
    edges = (
        None,
        "COMMITMENT_LINE_TO_RESOURCE",
        "RESOURCE_TO_RECIPE_VERSION",
        "RECIPE_VERSION_TO_ORDER_LINE",
        "ORDER_LINE_TO_PROMISE",
    )
    roles = (None, None, "FILLING", "FILLING", "FILLING")
    return tuple(
        PathNodeStatus(node_ref=ref, edge_kind=edges[index], role=roles[index])
        for index, ref in enumerate(refs)
    )


def path(
    *,
    ordinal: int = 0,
    rule_id: str | None = "R-SUB-OK",
    steps: tuple[PathNodeStatus, ...] | None = None,
    quantification: dict[str, object] | None = None,
) -> TrackPathStatus:
    return TrackPathStatus(
        ordinal=ordinal,
        nodes=nodes(RASPBERRY_DELIVERY, RASPBERRY, CHARLOTTE_V2, LINE_A, PROMISE_A)
        if steps is None
        else steps,
        role="FILLING",
        quantification=QUANTIFIED if quantification is None else quantification,
        rule_id=rule_id,
    )


def track(
    *,
    state: str = "PENDING",
    rule_id: str | None = "R-SUB-OK",
    reason: str | None = "VISIBLE_CHANGE_ASK",
    promise_id: str = PROMISE_A,
    customer: str = "Priya Nair",
    order: str = "EXT-A",
    paths: tuple[TrackPathStatus, ...] = (),
    track_id: UUID | None = None,
) -> TrackStatus:
    return TrackStatus(
        track_id=track_id or uuid4(),
        promise_id=promise_id,
        order_external_id=order,
        order_external_version=1,
        mirrored_versions={},
        customer_name=customer,
        state=state,
        classification="APPROVAL_REQUIRED" if state != "UNAFFECTED" else "UNAFFECTED",
        rule_id=rule_id,
        reason_detail=reason,
        priority=1,
        fingerprint=None,
        deadline_at=None,
        linked_track_id=None,
        paths=len(paths),
        watched_entities=0,
        revalidation=None,
        options=(),
        path_rows=paths,
    )


# ------------------------------------------------------------------ the traversal, as it happened


def test_the_chain_is_the_stored_path_in_the_stored_order() -> None:
    """Five nodes in, five steps out, in the order the engine walked them."""
    chain = chain_for(track(paths=(path(),)), facts=FACTS)

    assert chain.present is True
    assert [step.node_ref for step in chain.steps] == [
        RASPBERRY_DELIVERY,
        RASPBERRY,
        CHARLOTTE_V2,
        LINE_A,
        PROMISE_A,
    ]
    assert [step.slot for step in chain.steps] == [
        CausalSlot.SHORTFALL,
        CausalSlot.RESOURCE,
        CausalSlot.VERSION,
        CausalSlot.VERSION,
        CausalSlot.PROMISE,
    ]
    assert chain.deciding_rule == "R-SUB-OK"
    assert chain.absence_reason is None


def test_every_step_is_named_by_a_durable_row_and_never_by_its_reference() -> None:
    """Bands 1-4 carry no identifier, so no label may be one."""
    chain = chain_for(track(paths=(path(),)), facts=FACTS)

    labels = [step.label for step in chain.steps]
    assert labels == [
        "Valley Produce: Raspberries",
        "Raspberries",
        "Raspberry Charlotte v2",
        "the line on EXT-A",
        "Priya Nair - EXT-A",
    ]
    assert all(step.node_ref not in step.label for step in chain.steps)


def test_the_engines_own_arithmetic_is_read_back_on_the_node_it_was_measured_against() -> None:
    """The shortfall is quoted, not recomputed, and it lands on the resource it is about."""
    chain = chain_for(track(paths=(path(),)), facts=FACTS)

    shortfall = next(step for step in chain.steps if step.node_ref == RASPBERRY)
    assert shortfall.detail == "needed 4 kg, 1.2 kg available, 2.8 kg short"
    assert chain.steps[0].detail == "4 kg expected, none received"
    assert next(step for step in chain.steps if step.node_ref == CHARLOTTE_V2).detail == (
        "used as the filling"
    )


def test_a_covered_shortfall_is_said_as_covered_rather_than_as_a_shortage() -> None:
    covered = dict(QUANTIFIED, satisfied=True, shortfall=None)
    chain = chain_for(track(paths=(path(quantification=covered),)), facts=FACTS)

    assert next(step for step in chain.steps if step.node_ref == RASPBERRY).detail == (
        "needed 4 kg, 1.2 kg available - covered"
    )


def test_an_unknown_quantity_says_so_and_never_reads_as_zero() -> None:
    unknown = dict(QUANTIFIED, unknown=True, need=None, shortfall=None)
    chain = chain_for(track(paths=(path(quantification=unknown),)), facts=FACTS)

    assert next(step for step in chain.steps if step.node_ref == RASPBERRY).detail == (
        "the quantity on this line is unknown, which fails closed"
    )


# ------------------------------------------------------------------------------- several paths


def test_several_paths_return_the_one_that_decided_and_count_the_rest() -> None:
    """Three traversals, one decision. The chain is the deciding traversal, whole and alone."""
    other = path(ordinal=0, rule_id="R-UNREACH")
    deciding = path(ordinal=1, rule_id="R-SUB-OK")
    later = path(ordinal=2, rule_id="R-SUB-OK")

    chain = chain_for(track(paths=(other, deciding, later)), facts=FACTS)

    assert chain.path_count == 3, "the count is the rows, never the steps on screen"
    assert chain.deciding_rule == "R-SUB-OK"
    assert len(chain.steps) == 5, "one traversal, not three merged into one"


def test_the_lowest_ordinal_breaks_a_tie_between_two_deciding_paths() -> None:
    first = path(ordinal=3)
    second = path(
        ordinal=7, steps=nodes("cl-other", "res-other", "rv-other", "ol-other", PROMISE_A)
    )

    chain = chain_for(track(paths=(second, first)), facts=FACTS)

    assert chain.steps[0].node_ref == RASPBERRY_DELIVERY
    assert chain.path_count == 2


def test_three_promises_in_one_authority_lane_each_return_their_own_chain() -> None:
    """The chain hangs off the promise. A lane is a grouping of rows, not a shared trunk."""
    lane = [
        track(
            promise_id=f"pr-{name.lower()}",
            customer=name,
            order=f"EXT-{name[0]}",
            paths=(
                path(
                    steps=nodes(
                        RASPBERRY_DELIVERY,
                        RASPBERRY,
                        CHARLOTTE_V2,
                        f"ol-{name.lower()}",
                        f"pr-{name.lower()}",
                    )
                ),
            ),
        )
        for name in ("Priya", "Tomas", "Okafor")
    ]

    chains = [chain_for(item, facts=FACTS) for item in lane]

    assert all(chain.present for chain in chains)
    assert [chain.steps[-1].label for chain in chains] == [
        "Priya - EXT-P",
        "Tomas - EXT-T",
        "Okafor - EXT-O",
    ]
    assert len({id(chain) for chain in chains}) == 3
    assert all(chain.path_count == 1 for chain in chains)


# --------------------------------------------------------------------------- absence, stated


def test_an_untouched_promise_nothing_reached_has_no_chain_and_says_why() -> None:
    """Band 4's row. The empty causal column is the selectivity claim, so it carries a sentence."""
    chain = chain_for(track(state="UNAFFECTED", reason="NOT_REACHABLE"), facts=FACTS)

    assert chain.present is False
    assert chain.steps == ()
    assert chain.path_count == 0
    assert chain.deciding_rule is None
    assert chain.absence_reason == (
        "Nothing in this case reaches this promise - the exception reaches nothing it depends on."
    )


def test_an_untouched_promise_that_was_reached_is_not_described_as_unreachable() -> None:
    """Reachable-but-covered and no-path-at-all are different facts, and are said differently."""
    reached = track(
        state="UNAFFECTED",
        reason="SHORTFALL_COVERED",
        rule_id="R-COVERED",
        paths=(path(rule_id="R-COVERED"),),
    )

    chain = chain_for(reached, facts=FACTS)

    assert chain.present is False
    assert chain.path_count == 1
    assert chain.absence_reason is not None
    assert chain.absence_reason.startswith("A path reaches this promise and nothing about it")
    assert "still covers the need" in chain.absence_reason


def test_an_untouched_promise_with_an_unrecognised_reason_still_says_the_part_it_knows() -> None:
    chain = chain_for(track(state="UNAFFECTED", reason="SOMETHING_NEW"), facts=FACTS)

    assert chain.absence_reason == "Nothing in this case reaches this promise."


def test_a_threatened_promise_with_no_stored_path_says_so_rather_than_showing_one() -> None:
    chain = chain_for(track(), facts=FACTS)

    assert chain.present is False
    assert chain.absence_reason == NO_PATH_STORED
    assert chain.path_count == 0


def test_a_path_that_carries_no_deciding_rule_is_refused_rather_than_shown() -> None:
    """Showing a traversal that did not decide would answer the question with the wrong route."""
    chain = chain_for(track(rule_id="R-SUB-OK", paths=(path(rule_id="R-NOSUB"),)), facts=FACTS)

    assert chain.present is False
    assert chain.absence_reason == NO_DECIDING_PATH
    assert chain.path_count == 1


def test_a_track_with_no_rule_at_all_shows_no_chain() -> None:
    chain = chain_for(track(rule_id=None, paths=(path(rule_id=None),)), facts=FACTS)

    assert chain.present is False
    assert chain.absence_reason == NO_DECIDING_PATH


def test_a_stored_path_with_nothing_readable_in_it_fails_closed() -> None:
    """A row written by a build that is gone. No chain, and a sentence that admits it."""
    blank = path(steps=(PathNodeStatus(node_ref="", edge_kind=None, role=None),))

    chain = chain_for(track(paths=(blank,)), facts=FACTS)

    assert chain.present is False
    assert chain.steps == ()
    assert chain.absence_reason == UNREADABLE
    assert chain.path_count == 1


def test_a_node_with_no_durable_name_is_called_what_it_is_and_the_chain_survives() -> None:
    """A missing name costs the label, never the shape, and never leaks the reference."""
    chain = chain_for(track(paths=(path(),)), facts={RASPBERRY: FACTS[RASPBERRY]})

    assert chain.present is True
    assert [step.label for step in chain.steps] == [
        "a step on the path",
        "Raspberries",
        "a recipe version",
        "an order line",
        "Priya Nair - EXT-A",
    ]
    assert [step.slot for step in chain.steps] == [
        CausalSlot.SHORTFALL,
        CausalSlot.RESOURCE,
        CausalSlot.VERSION,
        CausalSlot.VERSION,
        CausalSlot.PROMISE,
    ]
    assert all(step.node_ref not in step.label for step in chain.steps)


def test_a_final_node_that_is_not_this_promise_is_not_labelled_as_this_customer() -> None:
    """The promise column names the track's own promise, and only where the path arrives at it."""
    elsewhere = path(
        steps=nodes(RASPBERRY_DELIVERY, RASPBERRY, CHARLOTTE_V2, LINE_A, "pr-somebody-else")
    )

    chain = chain_for(track(paths=(elsewhere,)), facts=FACTS)

    assert chain.steps[-1].label == "a promise"
    assert "Priya Nair" not in chain.steps[-1].label


# ------------------------------------------------------------------------ the equipment branch


def test_an_equipment_outage_reads_in_the_same_four_columns() -> None:
    """A shorter traversal occupies the same geometry: what went out, then where it landed."""
    equipment = TrackPathStatus(
        ordinal=0,
        nodes=(
            PathNodeStatus(node_ref="res-deck-oven", edge_kind=None, role=None),
            PathNodeStatus(node_ref="task-a1", edge_kind="EQUIPMENT_TO_PRODUCTION_TASK", role=None),
            PathNodeStatus(node_ref=LINE_A, edge_kind="PRODUCTION_TASK_TO_ORDER_LINE", role=None),
            PathNodeStatus(node_ref=PROMISE_A, edge_kind="ORDER_LINE_TO_PROMISE", role=None),
        ),
        role=None,
        quantification=None,
        rule_id="R-EQUIP",
    )
    facts = dict(FACTS, **{"res-deck-oven": NodeFact(kind="EQUIPMENT", name="Deck oven")})

    chain = chain_for(track(rule_id="R-EQUIP", paths=(equipment,)), facts=facts)

    assert [step.slot for step in chain.steps] == [
        CausalSlot.SHORTFALL,
        CausalSlot.RESOURCE,
        CausalSlot.VERSION,
        CausalSlot.PROMISE,
    ]
    assert [step.label for step in chain.steps] == [
        "Deck oven",
        "a production task",
        "the line on EXT-A",
        "Priya Nair - EXT-A",
    ]
