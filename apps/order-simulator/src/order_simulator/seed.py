"""The demo order book, as this order system holds it.

Hand-authored here rather than imported from PromisePatch, because an order system that read
its orders out of the application that mirrors it would not be an order system. The two
datasets are kept in step by a parity test on the PromisePatch side, which compares every field
that crosses the integration contract and fails if either side is edited alone.

**Due times are offsets.** The order system stores an anchor once, at seed time, and every due
date is measured from it, so a reset produces the same order book at any hour of any day.

**The catalogue is small and closed.** These are the product variants a human authored for the
demo; nothing at runtime adds one, here or on the other side. ``alternative_item_id`` is what
the operator screen offers first for a line, which is what makes the Proof A edit one click
rather than a hunt through a list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

SEED_ANCHOR: Final = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
"""The instant every seeded due date is measured from. Fixed, so a reset is reproducible."""

INITIAL_VERSION: Final = 1
"""Every seeded order starts at version 1. Every mutation moves it, and only forward."""


@dataclass(frozen=True, slots=True)
class CatalogueItem:
    """One product variant this order system can sell, and the demo swap offered for it."""

    external_item_id: str
    name: str
    alternative_item_id: str | None = None


@dataclass(frozen=True, slots=True)
class SeedLine:
    external_line_id: str
    external_item_id: str
    quantity: int


@dataclass(frozen=True, slots=True)
class SeedCustomer:
    external_id: str
    name: str
    channel_kind: str
    channel_address: str


@dataclass(frozen=True, slots=True)
class SeedOrder:
    external_id: str
    customer_external_id: str
    due_offset_minutes: int
    line: SeedLine


CATALOGUE: Final[tuple[CatalogueItem, ...]] = (
    CatalogueItem("rv-blueberry-danish-1", "Blueberry Danish v1"),
    CatalogueItem("rv-dark-chocolate-ganache-5", "Dark Chocolate Ganache Cake v5"),
    CatalogueItem("rv-lemon-curd-1", "Lemon Curd Layer v1", "rv-raspberry-lemon-2"),
    CatalogueItem("rv-raspberry-almond-3", "Raspberry Almond Cake v3", "rv-raspberry-almond-4"),
    CatalogueItem("rv-raspberry-almond-4", "Raspberry Almond Cake v4", "rv-raspberry-almond-3"),
    CatalogueItem("rv-raspberry-charlotte-1", "Raspberry Charlotte v1"),
    CatalogueItem("rv-raspberry-lemon-2", "Raspberry Lemon Layer v2", "rv-lemon-curd-1"),
    CatalogueItem("rv-raspberry-rose-2", "Raspberry Rose Cake v2", "rv-raspberry-rose-3"),
    CatalogueItem("rv-raspberry-rose-3", "Raspberry Rose Cake v3", "rv-raspberry-rose-2"),
)

CUSTOMERS: Final[tuple[SeedCustomer, ...]] = (
    SeedCustomer("cus-ahmed", "Ahmed Bouazizi", "telegram", "1005"),
    SeedCustomer("cus-cafe-marlow", "Cafe Marlow", "telegram", "1006"),
    SeedCustomer("cus-lena", "Lena Fischer", "telegram", "1004"),
    SeedCustomer("cus-okafor-reyes", "Okafor-Reyes wedding", "telegram", "1003"),
    SeedCustomer("cus-priya", "Priya Nair", "telegram", "1001"),
    SeedCustomer("cus-tomas", "Tomas Lindqvist", "telegram", "1002"),
)

ORDERS: Final[tuple[SeedOrder, ...]] = (
    SeedOrder("EXT-A", "cus-priya", 600, SeedLine("ol-a", "rv-raspberry-almond-3", 1)),
    SeedOrder("EXT-B", "cus-tomas", 690, SeedLine("ol-b", "rv-raspberry-rose-2", 1)),
    SeedOrder("EXT-C", "cus-okafor-reyes", 1620, SeedLine("ol-c", "rv-raspberry-charlotte-1", 1)),
    SeedOrder("EXT-D", "cus-lena", 1920, SeedLine("ol-d", "rv-raspberry-lemon-2", 1)),
    SeedOrder("EXT-E", "cus-ahmed", 540, SeedLine("ol-e", "rv-dark-chocolate-ganache-5", 1)),
    SeedOrder("EXT-F", "cus-cafe-marlow", 5760, SeedLine("ol-f", "rv-blueberry-danish-1", 24)),
)

ORDER_STATE_ACCEPTED: Final = "ACCEPTED"
ORDER_STATE_AMENDED: Final = "AMENDED"
ORDER_STATE_CANCELLED: Final = "CANCELLED"

OPEN_STATES: Final[frozenset[str]] = frozenset({ORDER_STATE_ACCEPTED, ORDER_STATE_AMENDED})
"""Only an open order may be amended. A settled one is history, and history does not move."""


def catalogue_by_id() -> dict[str, CatalogueItem]:
    return {item.external_item_id: item for item in CATALOGUE}
