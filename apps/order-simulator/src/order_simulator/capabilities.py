"""What this build of the order system publishes, said out loud rather than left to be guessed.

A reader of ``GET /admin/events`` is reading a *projection*, and a projection can be widened.
When it is, an older process keeps answering the same endpoint with the same status code and a
narrower document -- which is exactly the shape of failure that is hardest to notice, because
every reachability probe still passes. ``docs/sur1-first-scored-run-defect.md`` records one: a
container four days behind the commit that added the committed event body answered ``/readyz``,
``/orders`` and ``/admin/events`` perfectly and published no ``event`` key, and twenty
benchmark attempts were spent before anybody could see it.

So this module states the projection once and this build says so out loud:

* :func:`event_entry` is the **only** place an admin event entry is built, and the route uses
  it, so what the endpoint publishes and what this module declares cannot drift apart;
* :data:`ADMIN_EVENT_ENTRY_FIELDS` and :data:`ADMIN_EVENT_BODY_FIELDS` name the keys of the two
  levels of that document, the second read from the contract's own model rather than retyped;
* :data:`CAPABILITIES` names the *facts a reader depends on* rather than a version string,
  because a reader needs to know whether the command that caused a change is published, not
  which release published it first.

``GET /admin/capabilities`` serves :func:`declaration`. A process that predates this module has
no such route and answers ``404``, which is the point: a reader can tell an old build from a
current one by asking, before it does anything that costs.

**It declares and never decides.** Nothing here reads an order, writes a row or changes what
any endpoint does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from order_contract.events import SCHEMA_VERSION, OrderEvent

if TYPE_CHECKING:  # pragma: no cover - a type-only import, never a runtime dependency
    from order_simulator.store import CommittedEvent

COMMITTED_BODY: Final = "admin-events.committed-body"
"""``/admin/events`` publishes each event's committed ``OrderEvent`` under an ``event`` key."""

COMMAND_IDEMPOTENCY_KEY: Final = "admin-events.command-idempotency-key"
"""That body carries the command that caused the change, so an amendment can be attributed.

The one an auditor cannot do without: an event log that says an order moved, and not who asked
for it, cannot tell an amendment this system made on somebody's instruction from an operator's
own edit.
"""

PREVIOUS_VERSION: Final = "admin-events.previous-version"
"""Each entry carries the version the order was at before the change."""

CAPABILITIES: Final = (COMMITTED_BODY, COMMAND_IDEMPOTENCY_KEY, PREVIOUS_VERSION)
"""Every fact about the admin projection a reader may depend on, by name."""

ADMIN_EVENT_ENTRY_FIELDS: Final = (
    "attempts",
    "delivery_state",
    "event",
    "event_id",
    "external_order_id",
    "occurred_at",
    "previous_version",
    "source",
    "type",
    "version",
)
"""The keys of one ``/admin/events`` entry, sorted. Asserted against :func:`event_entry`."""

ADMIN_EVENT_BODY_FIELDS: Final = tuple(sorted(OrderEvent.model_fields))
"""The keys of the committed body under ``event``, read from the contract's own model.

Derived rather than retyped, so a field added to the published message appears here without
anybody remembering to add it, and a field removed from it cannot go on being advertised.
"""


def event_entry(event: CommittedEvent, *, body: Any) -> dict[str, Any]:
    """One committed event as ``/admin/events`` publishes it.

    ``body`` is the already-parsed committed document, passed in rather than parsed here: this
    module declares a shape and the store owns the bytes, and a declaration that also decoded
    JSON would be doing the endpoint's work.
    """
    return {
        "event_id": str(event.event_id),
        "external_order_id": event.external_order_id,
        "type": event.type,
        "previous_version": event.previous_version,
        "version": event.version,
        "occurred_at": event.occurred_at.isoformat(),
        "source": event.source,
        "delivery_state": event.state,
        "attempts": event.attempts,
        "event": body,
    }


def declaration() -> dict[str, Any]:
    """What ``GET /admin/capabilities`` answers: this build's published projection, named."""
    return {
        "service": "order-simulator",
        "schema_version": SCHEMA_VERSION,
        "capabilities": list(CAPABILITIES),
        "projection": {
            "admin_events": {
                "entry_fields": list(ADMIN_EVENT_ENTRY_FIELDS),
                "body_fields": list(ADMIN_EVENT_BODY_FIELDS),
            }
        },
    }


__all__ = [
    "ADMIN_EVENT_BODY_FIELDS",
    "ADMIN_EVENT_ENTRY_FIELDS",
    "CAPABILITIES",
    "COMMAND_IDEMPOTENCY_KEY",
    "COMMITTED_BODY",
    "PREVIOUS_VERSION",
    "declaration",
    "event_entry",
]
