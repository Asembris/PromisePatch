"""How a quantity crosses the HTTP boundary.

The engine's whole arithmetic story rests on quantities being :class:`~decimal.Decimal` and
never ``float`` -- allocation order, shortfall subtraction and fingerprints all have to be
reproducible, and binary floating point is not. Serialising through a JSON number would undo
that at the last possible moment: ``0.1 + 0.2`` is a different value in a JavaScript client
than it is in the ledger it came from, and a shortfall of ``-0.30000000000000004`` on a
screen is worse than no number at all.

So a quantity is serialised as a **string**, using the same rendering the engine's own
canonical form uses (``promise_graph.fingerprint``): ``format(value.normalize(), "f")`` --
fixed point, no exponent, trailing zeros trimmed. A test pins the two together, so the
representation a client reads is the representation a fingerprint was taken over.

``None`` stays ``null``. An unknown quantity is not zero, and the engine fails closed on it;
turning it into ``0`` here would present a promise as satisfiable that the engine refuses to
call satisfiable.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer


def render(value: Decimal) -> str:
    """A quantity as the engine's canonical fixed-point string."""
    return format(value.normalize(), "f")


def render_optional(value: Decimal | None) -> str | None:
    """The same, with unknown preserved as unknown."""
    return None if value is None else render(value)


QuantityOut = Annotated[Decimal, PlainSerializer(render, return_type=str)]
"""A known quantity, rendered as a string."""

OptionalQuantityOut = Annotated[
    Decimal | None, PlainSerializer(render_optional, return_type=str | None)
]
"""A quantity that may be unknown. ``null`` means unknown, never zero."""
