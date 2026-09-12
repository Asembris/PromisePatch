"""The path from the exception to one promise, in the words the product is allowed to use.

``track_paths`` has held the traversal since impact analysis ran: the nodes in order, the edge
that led into each one, the engine's own arithmetic for the line it arrives at, and the rule
that cited it. Until now the read service counted those rows and discarded the traversal, so
the evidence drawer could say "3 paths" and nothing could say what any of them was.

This module projects them. It composes no path, joins none, and never returns a chain assembled
out of two -- **a chain a person reads as one traversal has to be one traversal that actually
happened**. Where several paths exist it returns the one whose stored rule is the rule the
track was decided under, and reports the count beside it so a reader knows there were others.

Three rules shape it.

**Pure, like its siblings.** No database, no clock, no environment. It is handed the durable
path rows and a lookup of durable names, and everything it returns is a function of those two.
The import-linter contract of the same name enforces it.

**Absence is stated, never implied.** A promise nothing reached gets ``present`` false, an empty
step tuple and a sentence saying why -- and so does a promise whose stored path could not be
read. An empty causal column with no sentence would read as a screen that had failed to load,
and on band 4 it is the opposite: the emptiness is the selectivity claim, so it has to be said.

**A missing name understates; it never leaks an identifier.** A node with no durable row renders
under the generic noun for the edge that led into it. Bands 1-4 may carry no identifier, so a
label falling back to a node reference would be worse than a label that says less.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Final

from promisepatch.domain.analysis import NodeFact, TrackPathStatus, TrackStatus
from promisepatch.domain.explanations import CLOSED_VOCABULARIES, FactId

TRACK_UNAFFECTED: Final = "UNAFFECTED"
"""The one durable track state that means the exception never reached this promise."""


class CausalSlot(StrEnum):
    """The four fixed columns of the dependency view, in the order a judge reads them.

    *What did not arrive* -> *what it fell short of* -> *the version the order pins* -> *the
    promise*. Every chain occupies the same four positions whether it is three nodes long or
    five, so rows are compared rather than relearned. A slot may carry more than one step -- a
    supply path runs through a recipe version and then the order line pinning it, and both are
    the version column -- and no step is ever dropped to make a path fit the geometry.
    """

    SHORTFALL = "SHORTFALL"
    RESOURCE = "RESOURCE"
    VERSION = "VERSION"
    PROMISE = "PROMISE"


@dataclass(frozen=True, slots=True)
class CausalStep:
    """One node of the traversal, named."""

    slot: CausalSlot
    label: str
    detail: str | None
    node_ref: str
    """Drawer vocabulary. Present so band 5 can quote the traversal; never drawn in bands 1-4."""


@dataclass(frozen=True, slots=True)
class CausalChain:
    """How the exception reached one promise, or the reason nothing did."""

    present: bool
    steps: tuple[CausalStep, ...]
    absence_reason: str | None
    path_count: int
    """Every path stored for this track, including the ones not shown. Never the step count."""

    deciding_rule: str | None


_KIND_SLOT: Final[Mapping[str, CausalSlot]] = {
    "COMMITMENT_LINE": CausalSlot.SHORTFALL,
    "RESOURCE": CausalSlot.RESOURCE,
    "EQUIPMENT": CausalSlot.RESOURCE,
    "RECIPE_VERSION": CausalSlot.VERSION,
    "ORDER_LINE": CausalSlot.VERSION,
}

_EDGE_NOUN: Final[Mapping[str, str]] = {
    "COMMITMENT_LINE_TO_RESOURCE": "an ingredient",
    "RESOURCE_TO_RECIPE_VERSION": "a recipe version",
    "RECIPE_VERSION_TO_ORDER_LINE": "an order line",
    "EQUIPMENT_TO_PRODUCTION_TASK": "a production task",
    "PRODUCTION_TASK_TO_ORDER_LINE": "an order line",
    "ORDER_LINE_TO_PROMISE": "a promise",
}
"""What to call a node with no durable name, by the edge that led into it.

Closed, and deliberately vague. Every one of these is a noun a person can read; none of them is
an identifier. A path is still worth showing when one of its nodes has lost its name, and what
is lost is the name rather than the shape.
"""

_EDGE_SLOT: Final[Mapping[str, CausalSlot]] = {
    "COMMITMENT_LINE_TO_RESOURCE": CausalSlot.RESOURCE,
    "RESOURCE_TO_RECIPE_VERSION": CausalSlot.VERSION,
    "RECIPE_VERSION_TO_ORDER_LINE": CausalSlot.VERSION,
    "EQUIPMENT_TO_PRODUCTION_TASK": CausalSlot.RESOURCE,
    "PRODUCTION_TASK_TO_ORDER_LINE": CausalSlot.VERSION,
    "ORDER_LINE_TO_PROMISE": CausalSlot.PROMISE,
}

_ROLE_PHRASE: Final[Mapping[str, str]] = {
    "STRUCTURAL": "structural",
    "FILLING": "the filling",
    "VISIBLE_DECORATION": "visible decoration",
}

_RECEIVED_PHRASE: Final[Mapping[str, str]] = {
    "EXPECTED": "still expected",
    "RECEIVED": "received",
    "NOT_RECEIVED": "none received",
    "SHORT": "short",
}

UNREADABLE: Final = "This promise's stored path could not be read."
NO_PATH_STORED: Final = "No traversed path is stored for this promise."
NO_DECIDING_PATH: Final = "No stored path carries the rule that decided this promise."
NOTHING_REACHES: Final = "Nothing in this case reaches this promise"
NOTHING_AT_RISK: Final = "A path reaches this promise and nothing about it was put at risk"


def chain_for(track: TrackStatus, *, facts: Mapping[str, NodeFact]) -> CausalChain:
    """The path that decided one promise, or the stated reason there is none to show.

    ``facts`` is the case's durable name lookup. A node missing from it is named generically
    rather than skipped, so the shape of a traversal never depends on how complete the naming is.
    """
    count = len(track.path_rows)
    if track.state == TRACK_UNAFFECTED:
        return CausalChain(
            present=False,
            steps=(),
            absence_reason=_untouched_reason(track, count),
            path_count=count,
            deciding_rule=None,
        )
    deciding = _deciding(track)
    if deciding is None:
        return CausalChain(
            present=False,
            steps=(),
            absence_reason=NO_PATH_STORED if count == 0 else NO_DECIDING_PATH,
            path_count=count,
            deciding_rule=None,
        )
    steps = _steps(deciding, track=track, facts=facts)
    if not steps:
        return CausalChain(
            present=False,
            steps=(),
            absence_reason=UNREADABLE,
            path_count=count,
            deciding_rule=None,
        )
    return CausalChain(
        present=True,
        steps=steps,
        absence_reason=None,
        path_count=count,
        deciding_rule=deciding.rule_id,
    )


def _deciding(track: TrackStatus) -> TrackPathStatus | None:
    """The path whose stored rule is the one this track was decided under, lowest ordinal first.

    Not the first path, and not a merge of them. A track with three traversals was decided by
    one of them, and showing a different one would answer "how did this promise get here" with a
    route that did not carry the decision.
    """
    if track.rule_id is None:
        return None
    candidates = [path for path in track.path_rows if path.rule_id == track.rule_id]
    if not candidates:
        return None
    return min(candidates, key=lambda path: path.ordinal)


def _steps(
    path: TrackPathStatus, *, track: TrackStatus, facts: Mapping[str, NodeFact]
) -> tuple[CausalStep, ...]:
    """The stored nodes, in stored order, one step each. Nothing is sorted, filtered or merged."""
    nodes = [node for node in path.nodes if node.node_ref]
    if not nodes:
        return ()
    last = len(nodes) - 1
    steps = []
    for index, node in enumerate(nodes):
        fact = facts.get(node.node_ref)
        if index == last:
            slot = CausalSlot.PROMISE
        elif index == 0:
            # The entry node is what the exception itself names -- a delivery line that did not
            # arrive, stock that cannot be used, equipment that is out. Whichever kind of node
            # it is, it is the first column: what did not arrive.
            slot = CausalSlot.SHORTFALL
        else:
            slot = _slot_of(fact, node.edge_kind)
        steps.append(
            CausalStep(
                slot=slot,
                label=_label(node.node_ref, fact, node.edge_kind, track=track, last=index == last),
                detail=_detail(fact, node.role, path=path, node_ref=node.node_ref),
                node_ref=node.node_ref,
            )
        )
    return tuple(steps)


def _slot_of(fact: NodeFact | None, edge_kind: str | None) -> CausalSlot:
    """Which column a middle node belongs in: by what it is, or by the edge that reached it."""
    if fact is not None and fact.kind in _KIND_SLOT:
        return _KIND_SLOT[fact.kind]
    if edge_kind is not None and edge_kind in _EDGE_SLOT:
        return _EDGE_SLOT[edge_kind]
    return CausalSlot.RESOURCE


def _label(
    node_ref: str,
    fact: NodeFact | None,
    edge_kind: str | None,
    *,
    track: TrackStatus,
    last: bool,
) -> str:
    """What to call one node. The promise is named by its own track; the rest by their rows."""
    if last and node_ref == track.promise_id:
        return f"{track.customer_name} - {track.order_external_id}"
    if fact is None:
        return _EDGE_NOUN.get(edge_kind or "", "a step on the path")
    match fact.kind:
        case "COMMITMENT_LINE":
            supplier = fact.supplier or "the supplier"
            return f"{supplier}: {fact.name}"
        case "RECIPE_VERSION":
            return fact.name if fact.version_no is None else f"{fact.name} v{fact.version_no}"
        case "ORDER_LINE":
            return f"the line on {fact.name}"
    return fact.name


def _detail(
    fact: NodeFact | None, role: str | None, *, path: TrackPathStatus, node_ref: str
) -> str | None:
    """The one extra clause a node earns, and only where a durable value supports it."""
    if fact is not None and fact.kind == "COMMITMENT_LINE":
        return _delivery_detail(fact)
    quantified = _quantification_detail(
        path, node_ref=node_ref, unit=None if fact is None else fact.unit
    )
    if quantified is not None:
        return quantified
    if role is not None and role in _ROLE_PHRASE:
        return f"used as {_ROLE_PHRASE[role]}"
    return None


def _delivery_detail(fact: NodeFact) -> str | None:
    """What the delivery line promised and what it turned out to be. Both are columns."""
    if fact.quantity is None and fact.received_state is None:
        return None
    expected = None if fact.quantity is None else f"{_number(fact.quantity)}{_unit(fact.unit)}"
    settled = _RECEIVED_PHRASE.get(fact.received_state or "")
    if settled == "short" and fact.received_quantity is not None:
        settled = f"{_number(fact.received_quantity)}{_unit(fact.unit)} received"
    if expected is None:
        return None if settled is None else settled
    return expected + " expected" if settled is None else f"{expected} expected, {settled}"


def _quantification_detail(path: TrackPathStatus, *, node_ref: str, unit: str | None) -> str | None:
    """The engine's own arithmetic, read back on the node it was about and nowhere else.

    Attached to the resource the shortfall was measured against, because that is the node the
    stored quantification names. Putting it anywhere else would be this module deciding which
    step a number belongs to, and the number already says.
    """
    values = path.quantification
    if not isinstance(values, dict) or values.get("resource_id") != node_ref:
        return None
    if values.get("unknown") is True:
        return "the quantity on this line is unknown, which fails closed"
    need = _text(values.get("need"))
    available = _text(values.get("available_before_start"))
    shortfall = _text(values.get("shortfall"))
    if need is None or available is None:
        return None
    measured = f"needed {need}{_unit(unit)}, {available}{_unit(unit)} available"
    if values.get("satisfied") is True:
        return f"{measured} - covered"
    if shortfall is None:
        return measured
    return f"{measured}, {shortfall}{_unit(unit)} short"


def _untouched_reason(track: TrackStatus, count: int) -> str:
    """Why nothing was done to a promise, said from what the engine concluded and counted.

    Two different facts, and saying the wrong one would be a lie of exactly the kind this
    product exists to avoid: a promise with no path was never reached, while a promise with a
    path was reached and found to be in no danger. The reason detail is the engine's own, read
    through the phrase table the explanation surface already publishes for it.
    """
    opening = NOTHING_REACHES if count == 0 else NOTHING_AT_RISK
    phrase = _reason_phrase(track.reason_detail)
    return f"{opening}." if phrase is None else f"{opening} - {phrase}."


def _reason_phrase(reason_detail: str | None) -> str | None:
    if reason_detail is None:
        return None
    return CLOSED_VOCABULARIES[FactId.IMPACT_REASON].get(reason_detail)


def _text(value: Any) -> str | None:
    """One stored quantity, said the way a person says it, or nothing at all.

    ``None`` survives as ``None``: the engine fails closed on an unknown quantity, and a zero
    here would present a promise as satisfiable that the engine refuses to call satisfiable. A
    value that will not parse as a number is passed through as it was stored rather than
    dropped, because a reader is better served by a strange number than by a silent one.
    """
    if value is None:
        return None
    try:
        return _number(Decimal(str(value)))
    except InvalidOperation:
        return str(value)


def _number(value: Decimal) -> str:
    """A stored quantity, said without its trailing zeros. ``4.000`` is read out as ``4``."""
    normalised = value.normalize()
    return f"{normalised:f}"


def _unit(unit: str | None) -> str:
    return "" if not unit else f" {unit}"
