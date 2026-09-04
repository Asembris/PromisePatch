"""The clock a durable transaction reads.

Every instant a worker writes -- a lease expiry, a retry time, a timer's due date, the moment a
step finished -- comes from ``now()`` on the connection the transaction is already using, never
from the process's own clock.

Two reasons, and the second is the one that bites. Workers on different machines disagree about
the time by whatever their NTP drift happens to be, and a lease expiry written by one and
compared by another has to be measured against a single authority or a step becomes stealable
early. And ``now()`` is the start of the *transaction*, so every instant derived from it inside
one transaction is consistent: a step marked done and the event announcing it cannot be stamped
a millisecond apart and imply an ordering that did not happen.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_NOW = text("SELECT now()")


async def database_now(connection: AsyncConnection) -> datetime:
    """The current transaction's start instant, as the database reckons it.

    Stable within a transaction by definition: ``now()`` is ``transaction_timestamp()``, so
    calling this twice in one transaction returns the same answer, which is what makes a
    transaction's derived deadlines internally consistent.
    """
    value: datetime = (await connection.execute(_NOW)).scalar_one()
    return value
