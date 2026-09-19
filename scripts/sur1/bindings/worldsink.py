"""The world's own two powers, performed against the live systems.

:mod:`~scripts.sur1.bindings.events` decides *when* a declared event happens and *what* it is.
This module is the only thing that actually does it, and it is separate for the same reason
:mod:`~scripts.sur1.bindings.realisation` is separate from
:mod:`~scripts.sur1.bindings.programs`: the first is a reading of a frozen document and the
second is a write against a running system, and the two are answerable to different things.

**Two statements and no others.** A stipulated customer message is put on the channel, and one
signed physical movement is posted to the append-only ledger. There is no third power here: this
object cannot amend an order, cannot move a production task, cannot settle a commitment line and
cannot write a case. A world facility that could do an arm's work would make an arm's reading a
reading about the harness.

**It does not interpret.** The reply is recorded with the direction stated and the text carried
verbatim; nothing here reads the words, and whether they are a decision stays the consent
protocol's question. That is the same rule the harness's transport already obeys, applied to the
side that delivers rather than the side that records.

**Exactly once, twice over.** The event model refuses to fire an event it has already fired, and
the ledger's own ``uq_inventory_ledger_source`` refuses a second posting under one source
identity. The two guards are independent on purpose: the first is this process's memory, which a
crash could lose, and the second is a constraint in PostgreSQL, which it cannot.

**Nothing here has been pointed at a driven arm.** No attempt has used this sink, no reply has
been delivered to a live channel and no movement has been posted to a live ledger.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from promise_graph.model import LedgerSourceKind
from scripts.sur1.bindings.receivers import ChannelLedger
from scripts.sur1.evidence import INBOUND, ChannelMessage

HARNESS_PREFIX: Final = "sur1"
"""What marks a posting this harness made, exactly as a world program's own postings are marked.

The same prefix ``programs._post`` writes, so a prepared world's rows say which of them came
from the benchmark and which came from the fixture, without a second convention to keep in step.
"""

MOVEMENT_KIND: Final = LedgerSourceKind.EXCEPTION_FACT
"""A physical fact about the world, recorded as one.

Counter sales consuming stock is a thing that happened in a kitchen, not a correction of an
earlier posting and not a reservation being released. It is the kind
:class:`~scripts.sur1.bindings.programs.SpoilStock` already uses for the same reason.
"""


class SinkUnavailableError(RuntimeError):
    """The world could not perform a declared event against the live systems.

    Always raised, never returned. :class:`~scripts.sur1.bindings.events.Arming` turns any
    failure here into a failed arming, so a world whose stipulated event could not happen is
    never carried on as a world an attempt was set up in.
    """


@dataclass(slots=True)
class LedgerWriter:
    """One append-only physical posting, and nothing else in the database.

    Deliberately shaped like :class:`~scripts.sur1.bindings.setup.KitchenWriter`: one statement,
    its own short-lived connection, and a count of the rows it actually moved. A writer that held
    a connection would be a connection sitting beside a suite that truncates.
    """

    url: str

    def post(
        self, *, resource_id: str, delta: Decimal, source_id: str, recorded_at: datetime
    ) -> str:
        """Append one signed movement. A repeat of one source identity is refused by PostgreSQL."""
        marked = f"{HARNESS_PREFIX}:{source_id}"
        try:
            asyncio.run(self._insert(resource_id, delta, marked, recorded_at))
        except Exception as failure:
            raise SinkUnavailableError(
                f"the movement {marked} could not be posted: {type(failure).__name__}: {failure}"
            ) from failure
        return f"ledger:{marked}"

    async def _insert(
        self, resource_id: str, delta: Decimal, source_id: str, recorded_at: datetime
    ) -> None:
        import asyncpg

        connection = await asyncpg.connect(dsn=_dsn(self.url), timeout=5)
        try:
            await connection.execute(
                "INSERT INTO inventory_ledger (resource_id, delta, source_kind, source_id,"
                " recorded_at) VALUES ($1, $2, $3, $4, $5)",
                resource_id,
                delta,
                str(MOVEMENT_KIND),
                source_id,
                recorded_at,
            )
        finally:
            await connection.close()


@dataclass(slots=True)
class LiveWorldSink:
    """The world, doing what one scenario stipulated it would do during an attempt.

    Built once per attempt beside the arming that drives it. It holds the harness's own channel
    and a ledger writer, which is the whole of what a declared event needs and the whole of what
    this object may reach.
    """

    channel: ChannelLedger
    ledger: LedgerWriter

    def deliver_reply(
        self,
        *,
        message_id: str,
        channel: str,
        order: str,
        text: str,
        delivery: int,
        deliveries: int,
    ) -> str:
        """Put one stipulated message on the channel, under the provider's own identity.

        ``message_id`` is the same string for every delivery of one message, which is what makes
        ``C07`` one decision seen twice rather than two decisions. The delivery ordinal is
        carried in the receipt and never in the identity, because a provider that redelivers does
        not mint a new message.
        """
        if delivery < 1 or delivery > deliveries:
            raise SinkUnavailableError(
                f"delivery {delivery} of {message_id} is outside the {deliveries} the frozen "
                "document stipulates"
            )
        self.channel.accept(
            ChannelMessage(
                channel_address=channel,
                direction=INBOUND,
                text=text,
                accepted_at=datetime.now(UTC),
                provider_event_id=message_id,
            )
        )
        return f"reply:{message_id}:{delivery}/{deliveries}:{order}"

    def move_stock(self, *, resource: str, delta: Decimal, source_id: str, order: str) -> str:
        """Post one physical movement, attributed to the world and to nobody's attempt."""
        return self.ledger.post(
            resource_id=resource,
            delta=delta,
            source_id=source_id,
            recorded_at=datetime.now(UTC),
        )


def _dsn(url: str) -> str:
    scheme, separator, rest = url.partition("://")
    return f"{scheme.split('+')[0]}{separator}{rest}"


__all__ = [
    "HARNESS_PREFIX",
    "MOVEMENT_KIND",
    "LedgerWriter",
    "LiveWorldSink",
    "SinkUnavailableError",
]
