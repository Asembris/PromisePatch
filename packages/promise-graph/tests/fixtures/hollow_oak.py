"""The Hollow Oak Bakery fixture: hand-authored, deterministic, relative-time.

Every timestamp is an offset from an ``anchor`` supplied by the caller, so the fixture is
correct at any recording hour and no test depends on the wall clock.

**Quantity arithmetic is derived, not decorative.** Three frozen statements constrain the
berry quantities simultaneously:

* strawberries "2.0 kg + 6.0 kg arriving today (sufficient for A and B after allocation)"
  => ``need_A + need_B <= 8.0``
* whole-delivery scope must make **both** A and B ``BLOCKED`` on substitute stock. A rejected
  candidate commits nothing, so B sees the full 2.0 kg when A is rejected => ``need_A > 2.0``
  **and** ``need_B > 2.0``
* raspberries 0.3 kg is "below any single reservation" => every raspberry need > 0.3

The chosen values (A 2.4 kg, B 2.2 kg) are the smallest tidy numbers that satisfy all three.
They are large for one cake; that is forced by the frozen expectations, not a modelling error,
and ``test_hollow_oak_matrix`` asserts the constraints so a future retune cannot silently
break the demo behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from promise_graph.model import (
    CommitmentLine,
    ConstraintKind,
    Customer,
    CustomerConstraint,
    CustomerPromise,
    EquipmentAlternative,
    EquipmentOutage,
    ExceptionCategory,
    InventoryLedgerEntry,
    LedgerSourceKind,
    Order,
    OrderLine,
    OrderState,
    PhysicalException,
    ProductionTask,
    Recipe,
    RecipeLineRole,
    RecipeVersion,
    RecipeVersionLine,
    Resource,
    ResourceKind,
    SubstitutionPolicyEntry,
    Supplier,
    SupplierCommitment,
    TaskState,
)
from promise_graph.snapshot import GraphSnapshot, reservations_for_line

ANCHOR = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
"""Only used where a byte-stable hash is asserted; behavioural tests vary the anchor."""

AUTHOR = "jo"
BAKER = "maya"

# --- identifiers -----------------------------------------------------------------------

RASPBERRIES = "res-raspberries"
STRAWBERRIES = "res-strawberries"
BLUEBERRIES = "res-blueberries"
LEMONS = "res-lemons"
LEMON_CURD = "res-lemon-curd"
ALMOND_FLOUR = "res-almond-flour"
PLAIN_FLOUR = "res-plain-flour"
CASTER_SUGAR = "res-caster-sugar"
BUTTER = "res-butter"
EGGS = "res-eggs"
HEAVY_CREAM = "res-heavy-cream"
DARK_CHOCOLATE = "res-dark-chocolate"
VANILLA = "res-vanilla"
ROSE_WATER = "res-rose-water"
MASCARPONE = "res-mascarpone"
LADYFINGERS = "res-ladyfingers"
DECK_OVEN = "res-deck-oven"
CONVECTION_OVEN = "res-convection-oven"

VP_TODAY = "com-vp-today"
VP_TODAY_RASPBERRY = "cl-vp-today-raspberries"
VP_TODAY_STRAWBERRY = "cl-vp-today-strawberries"
VP_TOMORROW = "com-vp-tomorrow"
DL_TOMORROW = "com-dl-tomorrow"

RAC_V3 = "rv-raspberry-almond-3"
RAC_V4 = "rv-raspberry-almond-4"
RRC_V2 = "rv-raspberry-rose-2"
RRC_V3 = "rv-raspberry-rose-3"
CHARLOTTE_V1 = "rv-raspberry-charlotte-1"
CHARLOTTE_V2 = "rv-raspberry-charlotte-2"
RLL_V2 = "rv-raspberry-lemon-2"
LCL_V1 = "rv-lemon-curd-1"
GANACHE_V5 = "rv-dark-chocolate-ganache-5"
DANISH_V1 = "rv-blueberry-danish-1"

ORDER_A = "ord-a"
ORDER_B = "ord-b"
ORDER_C = "ord-c"
ORDER_D = "ord-d"
ORDER_E = "ord-e"
ORDER_F = "ord-f"
LINE_A = "ol-a"
LINE_B = "ol-b"
LINE_C = "ol-c"
LINE_D = "ol-d"
LINE_E = "ol-e"
LINE_F = "ol-f"
PROMISE_A = "pr-a"
PROMISE_B = "pr-b"
PROMISE_C = "pr-c"
PROMISE_D = "pr-d"
PROMISE_E = "pr-e"
PROMISE_F = "pr-f"

CONSTRAINT_A_PREAPPROVED = "cn-a-preapproved"
CONSTRAINT_B_ASK = "cn-b-ask"
CONSTRAINT_C_NOSUB = "cn-c-nosub"
CONSTRAINT_C_ASK = "cn-c-ask"
CONSTRAINT_D_ASK = "cn-d-ask"

POLICY_ALMOND_FILLING = "pol-almond-filling"
POLICY_ROSE_CROWN = "pol-rose-crown"
POLICY_CHARLOTTE = "pol-charlotte"
ALTERNATIVE_DECK = "alt-deck-to-convection"

EXCEPTION_RASPBERRY_ONLY = "exc-raspberry-only"
EXCEPTION_WHOLE_DELIVERY = "exc-whole-delivery"
EXCEPTION_DECK_OVEN = "exc-deck-oven"
EXCEPTION_CREAM = "exc-cream"

AMPLE = Decimal("100.0")


def q(value: str) -> Decimal:
    return Decimal(value)


@dataclass(frozen=True)
class Times:
    """Every fixture instant, as an offset from the reset anchor."""

    anchor: datetime

    def at(self, **offset: float) -> datetime:
        return self.anchor + timedelta(**offset)


def hollow_oak(anchor: datetime = ANCHOR) -> GraphSnapshot:
    """The base fixture: six accepted orders, D still pinned to Raspberry Lemon Layer v2."""
    t = Times(anchor)
    resources = _resources()
    recipes, versions = _recipes(anchor)
    orders, promises, tasks = _orders(t)
    reservations = [
        reservation
        for order in orders
        for line in order.lines
        for reservation in reservations_for_line(
            line,
            next(v for v in versions if v.id == line.recipe_version_id),
            {r.id: r for r in resources},
        )
    ]
    return GraphSnapshot.build(
        resources=resources,
        suppliers=_suppliers(),
        commitments=_commitments(t),
        recipes=recipes,
        versions=versions,
        customers=_customers(),
        orders=orders,
        constraints=_constraints(anchor),
        promises=promises,
        tasks=tasks,
        reservations=reservations,
        ledger=_ledger(resources, anchor),
        policies=_policies(),
        equipment_alternatives=[
            EquipmentAlternative(
                id=ALTERNATIVE_DECK,
                equipment_id=DECK_OVEN,
                alternative_equipment_id=CONVECTION_OVEN,
            )
        ],
        as_of=1,
    )


# --------------------------------------------------------------------------- variants


def with_lena_mutation(snapshot: GraphSnapshot) -> GraphSnapshot:
    """The Proof A mutation, made in the external order system: D moves to Lemon Curd v1."""
    updated = snapshot.repin_order_line(LINE_D, LCL_V1)
    order = updated.orders[ORDER_D]
    orders = dict(updated.orders)
    orders[ORDER_D] = order.model_copy(
        update={"external_version": order.external_version + 1, "state": OrderState.AMENDED}
    )
    return updated.replace(orders=orders)


def with_charlotte_variant(snapshot: GraphSnapshot) -> GraphSnapshot:
    """Author a Charlotte strawberry variant and its policy entry, keeping C's constraint."""
    version = RecipeVersion(
        id=CHARLOTTE_V2,
        recipe_id="rec-raspberry-charlotte",
        version_no=2,
        lines=(
            RecipeVersionLine(
                resource_id=STRAWBERRIES, role=RecipeLineRole.FILLING, qty_per_unit=q("3.0")
            ),
            RecipeVersionLine(
                resource_id=LADYFINGERS, role=RecipeLineRole.STRUCTURAL, qty_per_unit=q("1.0")
            ),
        ),
        equipment_ids=(DECK_OVEN,),
        authored_by=AUTHOR,
        authored_at=snapshot.versions[CHARLOTTE_V1].authored_at,
    )
    versions = dict(snapshot.versions)
    versions[CHARLOTTE_V2] = version
    policies = dict(snapshot.policies)
    policies[POLICY_CHARLOTTE] = SubstitutionPolicyEntry(
        id=POLICY_CHARLOTTE,
        affected_resource_id=RASPBERRIES,
        role=RecipeLineRole.FILLING,
        source_version_id=CHARLOTTE_V1,
        candidate_version_id=CHARLOTTE_V2,
        substitute_resource_id=STRAWBERRIES,
        visible_change=True,
    )
    return snapshot.replace(versions=versions, policies=policies)


def with_c_ask(snapshot: GraphSnapshot) -> GraphSnapshot:
    """Proof C: swap C's NO_SUBSTITUTION for ASK and author the variant it would need.

    Two data points change, because the frozen fixture deliberately has no Charlotte variant
    (spec 19) while Proof C requires the constraint flip to yield APPROVAL_REQUIRED. The
    intermediate case -- variant authored, NO_SUBSTITUTION retained -- is tested separately
    and stays BLOCKED, which is what proves the constraint is doing the work in the canonical
    fixture.
    """
    with_variant = with_charlotte_variant(snapshot)
    constraints = {
        constraint_id: constraint
        for constraint_id, constraint in with_variant.constraints.items()
        if constraint_id != CONSTRAINT_C_NOSUB
    }
    constraints[CONSTRAINT_C_ASK] = CustomerConstraint(
        id=CONSTRAINT_C_ASK,
        order_id=ORDER_C,
        kind=ConstraintKind.ASK_BEFORE_VISIBLE_CHANGE,
        recorded_by=AUTHOR,
        recorded_at=with_variant.promises[PROMISE_C].due_at,
    )
    return with_variant.replace(constraints=constraints)


# --------------------------------------------------------------------------- exceptions


def raspberry_only(anchor: datetime = ANCHOR) -> PhysicalException:
    """ "Just the raspberries -- the strawberries came." """
    return PhysicalException(
        id=EXCEPTION_RASPBERRY_ONLY,
        category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
        commitment_id=VP_TODAY,
        scope_line_ids=(VP_TODAY_RASPBERRY,),
        reported_by=BAKER,
        reported_at=anchor,
        raw_utterance="today's raspberry delivery didn't arrive",
    )


def whole_delivery(anchor: datetime = ANCHOR) -> PhysicalException:
    """ "The whole Valley Produce delivery." """
    return PhysicalException(
        id=EXCEPTION_WHOLE_DELIVERY,
        category=ExceptionCategory.SUPPLY_NOT_RECEIVED,
        commitment_id=VP_TODAY,
        reported_by=BAKER,
        reported_at=anchor,
        raw_utterance="the Valley Produce delivery didn't arrive",
    )


def deck_oven_down(anchor: datetime = ANCHOR) -> PhysicalException:
    return PhysicalException(
        id=EXCEPTION_DECK_OVEN,
        category=ExceptionCategory.EQUIPMENT_UNAVAILABLE,
        resource_id=DECK_OVEN,
        outage_until=anchor + timedelta(hours=16),
        reported_by=BAKER,
        reported_at=anchor,
        raw_utterance="the deck oven is down",
    )


def cream_unusable(anchor: datetime = ANCHOR) -> PhysicalException:
    return PhysicalException(
        id=EXCEPTION_CREAM,
        category=ExceptionCategory.STOCK_UNUSABLE,
        resource_id=HEAVY_CREAM,
        reported_by=BAKER,
        reported_at=anchor,
        raw_utterance="the cream in the walk-in went off",
    )


def outage(anchor: datetime = ANCHOR) -> EquipmentOutage:
    return EquipmentOutage(
        id=f"outage:{EXCEPTION_DECK_OVEN}",
        equipment_id=DECK_OVEN,
        starts_at=anchor,
        ends_at=anchor + timedelta(hours=16),
    )


# --------------------------------------------------------------------------- data


def _resources() -> list[Resource]:
    ingredients = [
        (RASPBERRIES, "raspberries", ("raspberry",)),
        (STRAWBERRIES, "strawberries", ("strawberry",)),
        (BLUEBERRIES, "blueberries", ("blueberry",)),
        (LEMONS, "lemons", ()),
        (LEMON_CURD, "lemon curd", ()),
        (ALMOND_FLOUR, "almond flour", ()),
        (PLAIN_FLOUR, "plain flour", ()),
        (CASTER_SUGAR, "caster sugar", ()),
        (BUTTER, "butter", ()),
        (EGGS, "eggs", ()),
        (HEAVY_CREAM, "heavy cream", ("cream",)),
        (DARK_CHOCOLATE, "dark chocolate", ()),
        (VANILLA, "vanilla", ()),
        (ROSE_WATER, "rose water", ()),
        (MASCARPONE, "mascarpone", ()),
        (LADYFINGERS, "ladyfingers", ()),
    ]
    resources = [
        Resource(id=rid, kind=ResourceKind.INGREDIENT, name=name, unit="kg", aliases=aliases)
        for rid, name, aliases in ingredients
    ]
    resources += [
        Resource(id=DECK_OVEN, kind=ResourceKind.EQUIPMENT, name="deck oven"),
        Resource(id=CONVECTION_OVEN, kind=ResourceKind.EQUIPMENT, name="convection oven"),
    ]
    return resources


def _suppliers() -> list[Supplier]:
    return [
        Supplier(id="sup-valley-produce", name="Valley Produce"),
        Supplier(id="sup-millstone-mill", name="Millstone Mill"),
        Supplier(id="sup-dairy-lane", name="Dairy Lane"),
    ]


def _commitments(t: Times) -> list[SupplierCommitment]:
    return [
        SupplierCommitment(
            id=VP_TODAY,
            supplier_id="sup-valley-produce",
            due_at=t.at(hours=1),
            lines=(
                CommitmentLine(
                    id=VP_TODAY_RASPBERRY,
                    commitment_id=VP_TODAY,
                    resource_id=RASPBERRIES,
                    quantity=q("4.0"),
                ),
                CommitmentLine(
                    id=VP_TODAY_STRAWBERRY,
                    commitment_id=VP_TODAY,
                    resource_id=STRAWBERRIES,
                    quantity=q("6.0"),
                ),
            ),
        ),
        SupplierCommitment(
            id=VP_TOMORROW,
            supplier_id="sup-valley-produce",
            due_at=t.at(hours=23),
            lines=(
                CommitmentLine(
                    id="cl-vp-tomorrow-raspberries",
                    commitment_id=VP_TOMORROW,
                    resource_id=RASPBERRIES,
                    quantity=q("3.0"),
                ),
                CommitmentLine(
                    id="cl-vp-tomorrow-blueberries",
                    commitment_id=VP_TOMORROW,
                    resource_id=BLUEBERRIES,
                    quantity=q("2.0"),
                ),
            ),
        ),
        SupplierCommitment(
            id=DL_TOMORROW,
            supplier_id="sup-dairy-lane",
            due_at=t.at(hours=25),
            lines=(
                CommitmentLine(
                    id="cl-dl-tomorrow-cream",
                    commitment_id=DL_TOMORROW,
                    resource_id=HEAVY_CREAM,
                    quantity=q("8.0"),
                ),
                CommitmentLine(
                    id="cl-dl-tomorrow-butter",
                    commitment_id=DL_TOMORROW,
                    resource_id=BUTTER,
                    quantity=q("5.0"),
                ),
            ),
        ),
    ]


def _recipes(anchor: datetime) -> tuple[list[Recipe], list[RecipeVersion]]:
    recipes = [
        Recipe(id="rec-raspberry-almond", name="Raspberry Almond Cake"),
        Recipe(id="rec-raspberry-rose", name="Raspberry Rose Cake"),
        Recipe(id="rec-raspberry-charlotte", name="Raspberry Charlotte"),
        Recipe(id="rec-raspberry-lemon", name="Raspberry Lemon Layer"),
        Recipe(id="rec-lemon-curd", name="Lemon Curd Layer"),
        Recipe(id="rec-dark-chocolate-ganache", name="Dark Chocolate Ganache Cake"),
        Recipe(id="rec-blueberry-danish", name="Blueberry Danish"),
    ]

    def version(
        version_id: str,
        recipe_id: str,
        version_no: int,
        lines: tuple[RecipeVersionLine, ...],
        equipment: tuple[str, ...],
    ) -> RecipeVersion:
        return RecipeVersion(
            id=version_id,
            recipe_id=recipe_id,
            version_no=version_no,
            lines=lines,
            equipment_ids=equipment,
            authored_by=AUTHOR,
            authored_at=anchor - timedelta(days=30),
        )

    base = (
        RecipeVersionLine(
            resource_id=ALMOND_FLOUR, role=RecipeLineRole.STRUCTURAL, qty_per_unit=q("0.8")
        ),
        RecipeVersionLine(resource_id=EGGS, role=RecipeLineRole.STRUCTURAL, qty_per_unit=q("0.6")),
    )
    versions = [
        version(
            RAC_V3,
            "rec-raspberry-almond",
            3,
            (
                *base,
                RecipeVersionLine(
                    resource_id=RASPBERRIES, role=RecipeLineRole.FILLING, qty_per_unit=q("2.4")
                ),
            ),
            (DECK_OVEN,),
        ),
        version(
            RAC_V4,
            "rec-raspberry-almond",
            4,
            (
                *base,
                RecipeVersionLine(
                    resource_id=STRAWBERRIES, role=RecipeLineRole.FILLING, qty_per_unit=q("2.4")
                ),
            ),
            (DECK_OVEN,),
        ),
        version(
            RRC_V2,
            "rec-raspberry-rose",
            2,
            (
                RecipeVersionLine(
                    resource_id=PLAIN_FLOUR, role=RecipeLineRole.STRUCTURAL, qty_per_unit=q("0.9")
                ),
                RecipeVersionLine(
                    resource_id=ROSE_WATER, role=RecipeLineRole.FILLING, qty_per_unit=q("0.05")
                ),
                RecipeVersionLine(
                    resource_id=RASPBERRIES,
                    role=RecipeLineRole.VISIBLE_DECORATION,
                    qty_per_unit=q("2.2"),
                ),
            ),
            (DECK_OVEN,),
        ),
        version(
            RRC_V3,
            "rec-raspberry-rose",
            3,
            (
                RecipeVersionLine(
                    resource_id=PLAIN_FLOUR, role=RecipeLineRole.STRUCTURAL, qty_per_unit=q("0.9")
                ),
                RecipeVersionLine(
                    resource_id=ROSE_WATER, role=RecipeLineRole.FILLING, qty_per_unit=q("0.05")
                ),
                RecipeVersionLine(
                    resource_id=STRAWBERRIES,
                    role=RecipeLineRole.VISIBLE_DECORATION,
                    qty_per_unit=q("2.2"),
                ),
            ),
            (DECK_OVEN,),
        ),
        version(
            CHARLOTTE_V1,
            "rec-raspberry-charlotte",
            1,
            (
                RecipeVersionLine(
                    resource_id=RASPBERRIES, role=RecipeLineRole.FILLING, qty_per_unit=q("3.0")
                ),
                RecipeVersionLine(
                    resource_id=LADYFINGERS, role=RecipeLineRole.STRUCTURAL, qty_per_unit=q("1.0")
                ),
            ),
            (DECK_OVEN,),
        ),
        version(
            RLL_V2,
            "rec-raspberry-lemon",
            2,
            (
                RecipeVersionLine(
                    resource_id=RASPBERRIES, role=RecipeLineRole.FILLING, qty_per_unit=q("1.5")
                ),
                RecipeVersionLine(
                    resource_id=LEMONS, role=RecipeLineRole.FILLING, qty_per_unit=q("0.4")
                ),
            ),
            (CONVECTION_OVEN,),
        ),
        version(
            LCL_V1,
            "rec-lemon-curd",
            1,
            (
                RecipeVersionLine(
                    resource_id=LEMON_CURD, role=RecipeLineRole.FILLING, qty_per_unit=q("1.2")
                ),
                RecipeVersionLine(
                    resource_id=LEMONS, role=RecipeLineRole.FILLING, qty_per_unit=q("0.4")
                ),
            ),
            (CONVECTION_OVEN,),
        ),
        version(
            GANACHE_V5,
            "rec-dark-chocolate-ganache",
            5,
            (
                RecipeVersionLine(
                    resource_id=DARK_CHOCOLATE, role=RecipeLineRole.FILLING, qty_per_unit=q("1.1")
                ),
                RecipeVersionLine(
                    resource_id=HEAVY_CREAM, role=RecipeLineRole.FILLING, qty_per_unit=q("0.9")
                ),
            ),
            (CONVECTION_OVEN,),
        ),
        version(
            DANISH_V1,
            "rec-blueberry-danish",
            1,
            (
                RecipeVersionLine(
                    resource_id=BLUEBERRIES, role=RecipeLineRole.FILLING, qty_per_unit=q("0.05")
                ),
                RecipeVersionLine(
                    resource_id=BUTTER, role=RecipeLineRole.STRUCTURAL, qty_per_unit=q("0.04")
                ),
            ),
            (CONVECTION_OVEN,),
        ),
    ]
    return recipes, versions


def _customers() -> list[Customer]:
    return [
        Customer(id="cus-priya", name="Priya Nair", approval_channel="tg:1001"),
        Customer(id="cus-tomas", name="Tomas Lindqvist", approval_channel="tg:1002"),
        Customer(id="cus-okafor-reyes", name="Okafor-Reyes wedding", approval_channel="tg:1003"),
        Customer(id="cus-lena", name="Lena Fischer", approval_channel="tg:1004"),
        Customer(id="cus-ahmed", name="Ahmed Bouazizi", approval_channel="tg:1005"),
        Customer(id="cus-cafe-marlow", name="Cafe Marlow", approval_channel="tg:1006"),
    ]


def _orders(
    t: Times,
) -> tuple[list[Order], list[CustomerPromise], list[ProductionTask]]:
    # (order, external id, customer, line, version, qty, due min, promise,
    #  task start min, task end min, equipment, task state)
    specs: list[tuple[str, str, str, str, str, int, int, str, int, int, str, TaskState]] = [
        (
            ORDER_A,
            "EXT-A",
            "cus-priya",
            LINE_A,
            RAC_V3,
            1,
            600,
            PROMISE_A,
            300,
            420,
            DECK_OVEN,
            TaskState.SCHEDULED,
        ),
        (
            ORDER_B,
            "EXT-B",
            "cus-tomas",
            LINE_B,
            RRC_V2,
            1,
            690,
            PROMISE_B,
            360,
            480,
            DECK_OVEN,
            TaskState.SCHEDULED,
        ),
        (
            ORDER_C,
            "EXT-C",
            "cus-okafor-reyes",
            LINE_C,
            CHARLOTTE_V1,
            1,
            1620,
            PROMISE_C,
            720,
            840,
            DECK_OVEN,
            TaskState.SCHEDULED,
        ),
        (
            ORDER_D,
            "EXT-D",
            "cus-lena",
            LINE_D,
            RLL_V2,
            1,
            1920,
            PROMISE_D,
            1260,
            1380,
            CONVECTION_OVEN,
            TaskState.SCHEDULED,
        ),
        (
            ORDER_E,
            "EXT-E",
            "cus-ahmed",
            LINE_E,
            GANACHE_V5,
            1,
            540,
            PROMISE_E,
            80,
            180,
            CONVECTION_OVEN,
            TaskState.STARTED,
        ),
        (
            ORDER_F,
            "EXT-F",
            "cus-cafe-marlow",
            LINE_F,
            DANISH_V1,
            24,
            5760,
            PROMISE_F,
            5400,
            5520,
            CONVECTION_OVEN,
            TaskState.SCHEDULED,
        ),
    ]
    orders: list[Order] = []
    promises: list[CustomerPromise] = []
    tasks: list[ProductionTask] = []
    for (
        order_id,
        external_id,
        customer_id,
        line_id,
        version_id,
        quantity,
        due_minutes,
        promise_id,
        start_minutes,
        end_minutes,
        equipment_id,
        state,
    ) in specs:
        due_at = t.at(minutes=due_minutes)
        orders.append(
            Order(
                id=order_id,
                external_id=external_id,
                external_version=1,
                customer_id=customer_id,
                due_at=due_at,
                state=OrderState.ACCEPTED,
                lines=(
                    OrderLine(
                        id=line_id,
                        order_id=order_id,
                        recipe_version_id=version_id,
                        quantity=quantity,
                    ),
                ),
            )
        )
        promises.append(CustomerPromise(id=promise_id, order_id=order_id, due_at=due_at))
        tasks.append(
            ProductionTask(
                id=f"task-{line_id}",
                order_line_id=line_id,
                state=state,
                scheduled_start=t.at(minutes=start_minutes),
                scheduled_end=t.at(minutes=end_minutes),
                equipment_id=equipment_id,
            )
        )
    return orders, promises, tasks


def _constraints(anchor: datetime) -> list[CustomerConstraint]:
    recorded_at = anchor - timedelta(days=3)
    return [
        CustomerConstraint(
            id=CONSTRAINT_A_PREAPPROVED,
            order_id=ORDER_A,
            kind=ConstraintKind.PREAPPROVED_ALTERNATIVE,
            resource_id=RASPBERRIES,
            substitute_resource_id=STRAWBERRIES,
            recorded_by=AUTHOR,
            recorded_at=recorded_at,
        ),
        CustomerConstraint(
            id=CONSTRAINT_B_ASK,
            order_id=ORDER_B,
            kind=ConstraintKind.ASK_BEFORE_VISIBLE_CHANGE,
            recorded_by=AUTHOR,
            recorded_at=recorded_at,
        ),
        CustomerConstraint(
            id=CONSTRAINT_C_NOSUB,
            order_id=ORDER_C,
            kind=ConstraintKind.NO_SUBSTITUTION,
            recorded_by=AUTHOR,
            recorded_at=recorded_at,
        ),
        CustomerConstraint(
            id=CONSTRAINT_D_ASK,
            order_id=ORDER_D,
            kind=ConstraintKind.ASK_BEFORE_VISIBLE_CHANGE,
            recorded_by=AUTHOR,
            recorded_at=recorded_at,
        ),
    ]


def _policies() -> list[SubstitutionPolicyEntry]:
    return [
        SubstitutionPolicyEntry(
            id=POLICY_ALMOND_FILLING,
            affected_resource_id=RASPBERRIES,
            role=RecipeLineRole.FILLING,
            source_version_id=RAC_V3,
            candidate_version_id=RAC_V4,
            substitute_resource_id=STRAWBERRIES,
            visible_change=False,
        ),
        SubstitutionPolicyEntry(
            id=POLICY_ROSE_CROWN,
            affected_resource_id=RASPBERRIES,
            role=RecipeLineRole.VISIBLE_DECORATION,
            source_version_id=RRC_V2,
            candidate_version_id=RRC_V3,
            substitute_resource_id=STRAWBERRIES,
            visible_change=True,
        ),
    ]


def _ledger(resources: list[Resource], anchor: datetime) -> list[InventoryLedgerEntry]:
    on_hand = {RASPBERRIES: q("0.3"), STRAWBERRIES: q("2.0")}
    entries: list[InventoryLedgerEntry] = []
    seq = 1
    for resource in resources:
        if resource.kind is not ResourceKind.INGREDIENT:
            continue
        entries.append(
            InventoryLedgerEntry(
                seq=seq,
                resource_id=resource.id,
                delta=on_hand.get(resource.id, AMPLE),
                source_kind=LedgerSourceKind.FIXTURE,
                source_id=f"fixture:{resource.id}",
                recorded_at=anchor - timedelta(hours=2),
            )
        )
        seq += 1
    return entries
