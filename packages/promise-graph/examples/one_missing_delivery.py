"""One delivery did not arrive. Which customer promises are affected, and what may be done?

Run it::

    python examples/one_missing_delivery.py

Four orders at a bakery on the morning of 4 March 2026. Valley Produce owed 6 kg of raspberries
by 06:00. It is 07:00, the raspberries are not here, and the baker has said so.

* **Amara** ordered a berry tart and told the shop in advance that strawberries are a fine swap.
* **Ben** ordered the same tart and asked to be told before anything he can see changes.
* **Chandra** ordered the same tart and asked for no substitutions at all.
* **Dev** ordered a sourdough loaf, which has nothing to do with raspberries.

All three tart customers said something, which is deliberate: an order carrying *no* recorded
preference is not read as permission. Unknown state fails closed to ``BLOCKED`` --- never to
``UNAFFECTED``, never to ``AUTO_RECOVERABLE`` --- so silence would produce a blocked promise
rather than a quiet substitution.

The engine gets the missing delivery and the graph, and nothing else: no database, no network,
no environment, no clock. ``now`` is a parameter. Nothing is written and no recovery is carried
out --- this prints what the engine *decided*, which is the only thing the engine does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import promise_graph as pg
from promise_graph.availability import apply_exception_facts
from promise_graph.classification import analyze

NOW = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
DUE = NOW + timedelta(hours=8)
AUTHOR: dict[str, Any] = {"authored_by": "head-baker", "authored_at": NOW - timedelta(days=30)}
DECOR = pg.RecipeLineRole.VISIBLE_DECORATION

# ------------------------------------------------------------------------------- the world

RESOURCES = [
    pg.Resource(id=rid, kind=pg.ResourceKind.INGREDIENT, name=name, unit="kg")
    for rid, name in (
        ("raspberry", "raspberries"),
        ("strawberry", "strawberries"),
        ("flour", "flour"),
    )
]
STOCK = {"raspberry": "0.0", "strawberry": "6.0", "flour": "50.0"}  # on the shelf this morning

DELIVERY = pg.SupplierCommitment(
    id="com-valley",
    supplier_id="sup-valley",
    due_at=NOW - timedelta(hours=1),
    lines=(
        pg.CommitmentLine(
            id="line-raspberry",
            commitment_id="com-valley",
            resource_id="raspberry",
            quantity=Decimal("6.0"),
        ),
    ),
)


def tart(version_id: str, no: int, berry: str) -> pg.RecipeVersion:
    line = pg.RecipeVersionLine(resource_id=berry, role=DECOR, qty_per_unit=Decimal("2.0"))
    return pg.RecipeVersion(
        id=version_id, recipe_id="rec-tart", version_no=no, lines=(line,), **AUTHOR
    )


RASPBERRY_TART = tart("ver-raspberry-tart", 1, "raspberry")
STRAWBERRY_TART = tart("ver-strawberry-tart", 2, "strawberry")  # pre-authored; never invented
LOAF = pg.RecipeVersion(
    id="ver-loaf",
    recipe_id="rec-loaf",
    version_no=1,
    lines=(
        pg.RecipeVersionLine(
            resource_id="flour", role=pg.RecipeLineRole.STRUCTURAL, qty_per_unit=Decimal("1.0")
        ),
    ),
    **AUTHOR,
)

SWAP = pg.SubstitutionPolicyEntry(
    id="pol-berry-swap",
    affected_resource_id="raspberry",
    role=DECOR,
    source_version_id=RASPBERRY_TART.id,
    candidate_version_id=STRAWBERRY_TART.id,
    substitute_resource_id="strawberry",
    visible_change=True,  # a customer can see a strawberry where a raspberry was
)

PEOPLE = [
    ("amara", "Amara", RASPBERRY_TART, pg.ConstraintKind.PREAPPROVED_ALTERNATIVE),
    ("ben", "Ben", RASPBERRY_TART, pg.ConstraintKind.ASK_BEFORE_VISIBLE_CHANGE),
    ("chandra", "Chandra", RASPBERRY_TART, pg.ConstraintKind.NO_SUBSTITUTION),
    ("dev", "Dev", LOAF, None),
]

customers, orders, promises, tasks, reservations, constraints = [], [], [], [], [], []
for nth, (key, name, version, told_us) in enumerate(PEOPLE, start=1):
    order_id, line_id = f"ord-{key}", f"ol-{key}"
    needs, quantity = version.lines[0].resource_id, version.lines[0].qty_per_unit
    customers.append(pg.Customer(id=f"cus-{key}", name=name, approval_channel=f"tg:{key}"))
    orders.append(
        pg.Order(
            id=order_id,
            external_id=f"EXT-{nth}",
            external_version=1,
            customer_id=f"cus-{key}",
            due_at=DUE,
            state=pg.OrderState.ACCEPTED,
            lines=(
                pg.OrderLine(
                    id=line_id, order_id=order_id, recipe_version_id=version.id, quantity=1
                ),
            ),
        )
    )
    promises.append(pg.CustomerPromise(id=f"pro-{key}", order_id=order_id, due_at=DUE))
    tasks.append(
        pg.ProductionTask(
            id=f"tsk-{key}",
            order_line_id=line_id,
            state=pg.TaskState.SCHEDULED,
            scheduled_start=NOW + timedelta(hours=3, minutes=10 * nth),
        )
    )
    reservations.append(
        pg.InventoryReservation(
            id=f"rsv-{key}",
            order_line_id=line_id,
            resource_id=needs,
            quantity=quantity,
            source_recipe_version_id=version.id,
        )
    )
    if told_us is not None:
        # Only a pre-approval names resources; the other two kinds are blanket instructions.
        named = (
            {"resource_id": "raspberry", "substitute_resource_id": "strawberry"}
            if told_us is pg.ConstraintKind.PREAPPROVED_ALTERNATIVE
            else {}
        )
        constraints.append(
            pg.CustomerConstraint(
                id=f"con-{key}",
                order_id=order_id,
                kind=told_us,
                recorded_by="counter-staff",
                recorded_at=NOW - timedelta(days=2),
                **named,
            )
        )

SNAPSHOT = pg.GraphSnapshot.build(
    resources=RESOURCES,
    suppliers=[pg.Supplier(id="sup-valley", name="Valley Produce")],
    commitments=[DELIVERY],
    recipes=[pg.Recipe(id="rec-tart", name="berry tart"), pg.Recipe(id="rec-loaf", name="loaf")],
    versions=[RASPBERRY_TART, STRAWBERRY_TART, LOAF],
    customers=customers,
    orders=orders,
    constraints=constraints,
    promises=promises,
    tasks=tasks,
    reservations=reservations,
    ledger=[
        pg.InventoryLedgerEntry(
            seq=seq,
            resource_id=rid,
            delta=Decimal(amount),
            source_kind=pg.LedgerSourceKind.FIXTURE,
            source_id=f"opening:{rid}",
            recorded_at=NOW - timedelta(hours=2),
        )
        for seq, (rid, amount) in enumerate(sorted(STOCK.items()), start=1)
    ],
    policies=[SWAP],
)

# What the baker attested. A physical fact, authoritative on its own.
NOT_RECEIVED = pg.PhysicalException(
    id="exc-raspberry",
    category=pg.ExceptionCategory.SUPPLY_NOT_RECEIVED,
    commitment_id=DELIVERY.id,
    scope_line_ids=("line-raspberry",),
    reported_by="maya",
    reported_at=NOW,
    raw_utterance="today's raspberry delivery didn't arrive",
)

# ----------------------------------------------------------------------------- the reading

HEADING = {
    pg.Classification.AUTO_RECOVERABLE: "AUTO_RECOVERABLE   changed without asking anyone",
    pg.Classification.APPROVAL_REQUIRED: "APPROVAL_REQUIRED  needs the customer to say yes",
    pg.Classification.BLOCKED: "BLOCKED            no permitted recovery; a person decides",
    pg.Classification.UNAFFECTED: "UNAFFECTED         untouched by this exception",
}


def main() -> None:
    settled = apply_exception_facts(SNAPSHOT, NOT_RECEIVED, NOW)
    analysis = analyze(settled.snapshot, NOT_RECEIVED, NOW)
    graph, total = settled.snapshot, len(analysis.classifications)

    print(f'"{NOT_RECEIVED.raw_utterance}" -- {NOT_RECEIVED.reported_by}, {NOW:%H:%M on %d %B %Y}')
    print(f"{total} open promises read against the graph\n")

    for classification in pg.Classification:
        found = [r for r in analysis.classifications.values() if r.classification is classification]
        print(f"{HEADING[classification]}  ({len(found)} of {total})")
        for result in sorted(found, key=lambda item: item.promise_id):
            order = graph.orders[graph.promises[result.promise_id].order_id]
            who = graph.customers[order.customer_id].name
            print(f"    {order.external_id}  {who:<9} {result.rule_id}  {result.reason_detail}")
        print()

    untouched = sum(
        r.classification is pg.Classification.UNAFFECTED for r in analysis.classifications.values()
    )
    print(
        f"{untouched} of {total} untouched: no message, no write, no reservation change, no hold."
    )
    print("Nothing above was carried out. The engine decided; acting on it is somebody else's job.")


if __name__ == "__main__":
    main()
