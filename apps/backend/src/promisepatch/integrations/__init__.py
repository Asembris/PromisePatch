"""Adapters that talk to systems PromisePatch does not own.

Everything here is on the far side of a boundary: it holds a URL, a credential and an HTTP
client, and it holds no database handle at all. That is enforced rather than intended -- an
import contract forbids this package from reaching :mod:`promisepatch.db` or SQLAlchemy, so an
adapter cannot quietly change PromisePatch's own copy of the state it is integrating with.
"""

from promisepatch.integrations.order_system import (
    OrderSystemAdapter,
    OrderSystemClient,
    OrderSystemUnavailableError,
)

__all__ = ["OrderSystemAdapter", "OrderSystemClient", "OrderSystemUnavailableError"]
