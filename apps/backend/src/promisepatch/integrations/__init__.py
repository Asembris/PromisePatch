"""Adapters that talk to systems PromisePatch does not own.

Everything here is on the far side of a boundary: it holds a URL, a credential and an HTTP
client, and it holds no database handle at all. That is enforced rather than intended -- an
import contract forbids this package from reaching :mod:`promisepatch.db` or SQLAlchemy, so an
adapter cannot quietly change PromisePatch's own copy of the state it is integrating with.

The same rule is what makes the semantic boundary safe by construction: the module that calls
Amazon Bedrock lives here, so it cannot write a row, record a decision or attest a fact even
if a model asked it to in perfect JSON.
"""

from promisepatch.integrations.order_system import (
    OrderSystemAdapter,
    OrderSystemClient,
    OrderSystemUnavailableError,
)
from promisepatch.integrations.semantic_provider import (
    ObservedSemanticProvider,
    build_semantic_provider,
)
from promisepatch.integrations.telegram import TelegramAdapter, build_customer_channel

__all__ = [
    "ObservedSemanticProvider",
    "OrderSystemAdapter",
    "OrderSystemClient",
    "OrderSystemUnavailableError",
    "TelegramAdapter",
    "build_customer_channel",
    "build_semantic_provider",
]
