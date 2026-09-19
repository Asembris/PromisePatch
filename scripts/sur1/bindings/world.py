"""The one world all three arms act on, and the four receivers read back out of it.

The contract's tool surface opens with a sentence this module exists to make true::

    Every arm acts on the same world through the same set of allowed external actions. No arm
    has an action another arm lacks.

One :class:`LiveScenarioWorld` object serves every arm in a run. It is prepared once per attempt
from a clean fixture, it performs the eleven frozen actions, and it reads the four receivers back
through :mod:`~scripts.sur1.bindings.receivers`. Nothing about which arm is driving reaches it:
:meth:`LiveScenarioWorld.invoke` takes a name and arguments, and an arm token never travels this
far.

**The reads are the world's data and not one arm's opinion of it.** ``get_orders`` is the order
system's own snapshot. ``get_promise_graph``, ``get_stock`` and ``get_tasks`` are read from the
rows the fixture loaded, over a read-only connection. The contract is explicit that the baseline
is denied PromisePatch's deterministic machinery and **not** the domain -- *an agent that did not
know the wedding customer had refused substitution would be measuring ignorance rather than
architecture* -- so the substitution policy, the recorded constraints and the attested stock are
read for whoever asks.

**E4 has two honest sources and the contract names both.** An arm with a ``report_outcome`` call
is reported by that call. Arms B and C have no such call: their report is *projected from
``status_view``*, which this world does by reading the product's own status surface once at
collection time, under the rule declared in :mod:`scripts.sur1.predeclaration`.

**Preparation is refused rather than approximated.** A scenario with no world program raises,
the driver records ``HARNESS_FAILURE``, and the preflight refuses the run before an attempt is
bought. A world missing a stipulated fact would produce a number that looks exactly like a number
about the scenario.

**This world has been prepared for one scored run**, ``20260919T2020Z-scored``, which is published
inconclusive and unaltered. See ``docs/sur1-first-scored-run-defect.md``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4

from scripts.sur1 import predeclaration
from scripts.sur1.bindings import REAL, Probe
from scripts.sur1.bindings.clock import RunClock, strategy_of
from scripts.sur1.bindings.consentdoor import ConsentDoor
from scripts.sur1.bindings.events import Arming, FiredEvent, observe
from scripts.sur1.bindings.lifecycle import (
    InstallationLifecycle,
    UncontrolledWorker,
    WorkerControl,
)
from scripts.sur1.bindings.promisepatch import LiveWorkerSurface
from scripts.sur1.bindings.receivers import (
    ChannelLedger,
    ChannelReceiver,
    DatabaseReader,
    KitchenReceiver,
    OrderSystemReceiver,
    ReceiverUnreadableError,
)
from scripts.sur1.bindings.setup import KitchenWriter, WorldHandles, program_for
from scripts.sur1.bindings.worldsink import LedgerWriter, LiveWorldSink
from scripts.sur1.evidence import (
    OUTBOUND,
    ChannelMessage,
    OrderEvent,
    ReceiverEvidence,
    ReportedPromiseRow,
    TaskSample,
)
from scripts.sur1.evidence import WorkerReport as ReportRow

READS: Final = (
    "get_incident",
    "get_orders",
    "get_promise_graph",
    "get_stock",
    "get_tasks",
    "read_customer_replies",
)
WRITES: Final = (
    "amend_order",
    "send_customer_message",
    "hold_task",
    "release_task",
    "report_outcome",
)
ACTIONS: Final = (*READS, *WRITES)
"""The eleven frozen actions. A world that offered a twelfth would be a different benchmark."""


class WorldActionError(RuntimeError):
    """A frozen action could not be performed at all. Never softened into a plausible answer."""


@dataclass(slots=True)
class LiveScenarioWorld:
    """The order system, the customer channel and the kitchen, as one prepared world.

    Built once per run and prepared once per attempt. It holds the receivers, the two systems
    and -- for arms B and C only -- the worker surface whose status projection is their E4.
    """

    orders: OrderSystemReceiver
    channel: ChannelReceiver
    kitchen: KitchenReceiver
    database: DatabaseReader
    ledger: ChannelLedger
    fixture: Mapping[str, Mapping[str, Any]]
    worker_surface: LiveWorkerSurface | None = None
    consent_door: ConsentDoor | None = None
    """The production consent ingress a declared reply is additionally offered to.

    One door for the whole run, held by the one world every attempt shares, and never chosen per
    attempt: an object that bound a different door depending on who was driving would make the
    later numbers a comparison between two worlds. It is blind by construction rather than by
    care -- it presses the link the *driven system's own outbox* holds, so where nothing asked
    the customer anything there is no link, the door stays shut, and the reply is on the channel
    record alone. See :mod:`scripts.sur1.bindings.consentdoor`.
    """

    environment: Mapping[str, str] = field(default_factory=dict)

    run_id: UUID = field(default_factory=uuid4)
    scenario_id: str = ""
    incident: Mapping[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    at_incident: Mapping[str, tuple[str, str | None]] = field(default_factory=dict)
    report: ReportRow | None = None
    applied_steps: tuple[str, ...] = ()
    arming: Arming | None = None
    world_digest: str = ""
    binding_kind: str = REAL
    clock: RunClock | None = None
    """Where in time this run installs its worlds, decided once before any arm exists.

    ``None`` is the fixture's own byte-stable anchor, which is right for a unit test and is
    refused for a scored run by :func:`scripts.sur1.preflight.world_clock`. It is a field on the
    world rather than on a program because it is a property of the *run*: one anchor serves every
    scenario and every attempt, so an attempt and its retry are attempts at one world. See
    ADR-0019.
    """

    worker: WorkerControl = field(default_factory=UncontrolledWorker)
    """What puts the durable worker down while a world is installed, and brings it back.

    The default controls nothing and declares itself a stand-in, which is right for a unit test
    and is refused for a scored run by :func:`~scripts.sur1.preflight.worker_lifecycle`. A run
    binds the real one. See :mod:`scripts.sur1.bindings.lifecycle` for why an install beside a
    live worker is a deadlock rather than a slow moment.
    """

    program_lookup: Callable[[str], Any] = program_for
    """How this world finds the program for a scenario. The frozen registry, by default.

    A parameter so the execution pipeline can be driven end to end at a scenario the frozen
    contract never held -- a dress rehearsal -- without a ``SUR-1`` attempt being bought. It is
    named in :meth:`identity`, so a world carrying any other lookup fingerprints differently
    from the real one and cannot be driven under a capability minted against it.
    """

    # ------------------------------------------------------------------------------ identity

    def identity(self) -> Mapping[str, Any]:
        return {
            "world": "live",
            "E1": self.orders.identity(),
            "E2": self.channel.identity(),
            "E3": self.kitchen.identity(),
            "actions": list(ACTIONS),
            "programs": f"{self.program_lookup.__module__}.{self.program_lookup.__qualname__}",
            "clock": strategy_of(self.clock),
            "worker_control": type(self.worker).__name__,
            "consent_ingress": (
                None if self.consent_door is None else dict(self.consent_door.identity())
            ),
        }

    def probe(self) -> Probe:
        for probe in (self.orders.probe(), self.channel.probe(), self.kitchen.probe()):
            if not probe.reachable:
                return Probe("WORLD", False, f"{probe.source}: {probe.detail}")
        return Probe("WORLD", True, "E1, E2 and E3 read")

    def probes(self) -> tuple[Probe, ...]:
        """Every receiver's own answer, so a preflight can report which one is unreachable."""
        return (self.orders.probe(), self.channel.probe(), self.kitchen.probe())

    # --------------------------------------------------------------------------- preparation

    def prepare(self, scenario: Mapping[str, Any]) -> None:
        """Bring the world to this scenario's stipulated facts, from a clean fixture.

        Everything that makes an attempt an attempt is reset here: the run identity that
        attributes a hold, the channel the harness's own transport carries, the instant every
        receiver read is taken from, and the sample E3 compares against. A world that kept any
        of them would be reporting a previous attempt's effects as this one's.
        """
        self.scenario_id = str(scenario["id"])
        self.run_id = uuid4()
        self.report = None
        self.arming = None
        self.world_digest = ""
        self.ledger.clear()
        if self.consent_door is not None:
            self.consent_door.begin()
        if self.worker_surface is not None:
            self.worker_surface.forget()
            # The world catches up while that surface waits. Arm A's world catches up when it
            # acts, through ``invoke``; these arms invoke once and then work through the surface,
            # so without this the declared reply is never delivered to an ask that did reach a
            # channel. The settle itself is unchanged and stays arm-blind.
            self.worker_surface.on_poll = self.settle

        program = self.program_lookup(self.scenario_id)
        handles = WorldHandles(
            order_system_base_url=self.orders.base_url,
            database=self.database,
            environment=self.environment,
        )
        sink = self._sink()
        anchor = None if self.clock is None else self.clock.anchor
        realisation = InstallationLifecycle(worker=self.worker, database=self.database).around(
            self.scenario_id,
            lambda: program.apply(handles, sink=sink, anchor=anchor),
        )
        self.applied_steps = realisation.applied
        self.arming = realisation.arming
        self.world_digest = realisation.digest
        self.incident = dict(program.incident)
        self.started_at = datetime.now(UTC)
        self.at_incident = self.kitchen.sample()

    def _sink(self) -> LiveWorldSink:
        """The two powers the world needs to perform what this scenario stipulated it would do.

        Built per attempt beside the arming that drives it, and reachable from nothing an arm
        holds: an :class:`~scripts.sur1.arms.AttemptRequest` carries a world and a budget, and
        there is no path from either to this object.
        """
        return LiveWorldSink(
            channel=self.ledger,
            ledger=LedgerWriter(url=self.database.url),
            door=self.consent_door,
        )

    # ------------------------------------------------------------------------- the actions

    def tools(self) -> Mapping[str, Any]:
        """The eleven actions by name. Identical for every arm, which is the point of them."""
        return {name: {"name": name} for name in ACTIONS}

    def invoke(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Perform one frozen action and return what the receiver said about it.

        The world catches up with itself on either side of the action. Before, because an ask
        that reached a channel during PromisePatch's own work is due its reply before the next
        read; after, because an ask this very call put on the channel is due one too. Neither is
        a twelfth action and neither is an arm firing an event: the arm did the ordinary thing,
        and what the world owes for it is decided by the world's own records.
        """
        if name not in ACTIONS:
            raise WorldActionError(f"{name} is not one of the eleven actions this world offers")
        self.settle()
        handler = getattr(self, f"_{name}")
        result: Mapping[str, Any] = handler(dict(arguments))
        self.settle()
        return result

    def settle(self) -> tuple[FiredEvent, ...]:
        """Fire every declared event the world's own records now make due.

        Arm-blind by construction: the observation is a count of outbound messages per channel
        address taken from the channel receiver, which holds the product's own outbox and the
        harness's own transport alike. An arm that is PromisePatch and an arm that is not both
        reach a customer by putting a message on a channel, and this answers the message rather
        than the sender.

        An unreadable channel leaves every event pending rather than being treated as *no ask
        yet*: the two look alike here and are told apart where it matters, because
        :meth:`collect` reads ``E2`` again and an unreadable source voids the attempt. Events
        still pending at the end are not a failure -- an arm that never asked is owed no reply,
        which is the whole of what one of these scenarios measures.
        """
        arming = self.arming
        if arming is None or not arming.pending:
            return ()
        try:
            messages = self.channel.read(since=self.started_at)
        except ReceiverUnreadableError:
            return ()
        return arming.pump(observe(messages, completed=arming.completed), self._sink())

    # -- reads ---------------------------------------------------------------------------------

    def _get_incident(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """What the worker said, verbatim, and the answer they gave to a clarification.

        The same read for every arm, so 'the same facts' is a fact about the harness rather than
        a claim about three setups.
        """
        return dict(self.incident)

    def _get_orders(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return self.orders.snapshot()

    def _get_promise_graph(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        versions = self.database.rows(
            "WORLD",
            "SELECT version_id, resource_id, role, qty_per_unit FROM recipe_version_lines"
            " ORDER BY version_id, resource_id, role",
        )
        policies = self.database.rows(
            "WORLD",
            "SELECT id, affected_resource_id, role, source_version_id, candidate_version_id,"
            " substitute_resource_id, visible_change FROM substitution_policies ORDER BY id",
        )
        constraints = self.database.rows(
            "WORLD",
            "SELECT id, order_id, kind, resource_id, substitute_resource_id"
            " FROM order_constraints ORDER BY id",
        )
        return {
            "recipe_version_lines": [
                {
                    "version_id": str(version),
                    "resource_id": str(resource),
                    "role": str(role),
                    "qty_per_unit": None if quantity is None else str(quantity),
                }
                for version, resource, role, quantity in versions
            ],
            "substitution_policies": [
                {
                    "id": str(identifier),
                    "affected_resource_id": str(affected),
                    "role": str(role),
                    "source_version_id": str(source),
                    "candidate_version_id": str(candidate),
                    "substitute_resource_id": str(substitute),
                    "visible_change": bool(visible),
                }
                for identifier, affected, role, source, candidate, substitute, visible in policies
            ],
            "order_constraints": [
                {
                    "id": str(identifier),
                    "order_id": str(order),
                    "kind": str(kind),
                    "resource_id": None if resource is None else str(resource),
                    "substitute_resource_id": None if substitute is None else str(substitute),
                }
                for identifier, order, kind, resource, substitute in constraints
            ],
        }

    def _get_stock(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Attested on-hand quantity per resource, as of the incident.

        Summed from the ledger rather than from a cached total, because the ledger is what the
        attestations wrote and a total is a derivation this harness has no business owning.
        """
        rows = self.database.rows(
            "WORLD",
            "SELECT resource_id, sum(delta) FROM inventory_ledger"
            " WHERE delta IS NOT NULL GROUP BY resource_id ORDER BY resource_id",
        )
        return {"on_hand": {str(resource): str(total) for resource, total in rows}}

    def _get_tasks(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        sample = self.kitchen.sample()
        orders = self.kitchen.orders()
        return {
            "tasks": [
                {
                    "task_id": task,
                    "order": orders.get(task, ""),
                    "state": state,
                    "held": held is not None,
                }
                for task, (state, held) in sorted(sample.items())
            ]
        }

    def _read_customer_replies(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        messages = [
            message
            for message in self.channel.read(since=self.started_at)
            if message.direction != OUTBOUND
        ]
        return {"replies": [message.as_payload() for message in messages]}

    # -- writes --------------------------------------------------------------------------------

    def _amend_order(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """The order system's own governed amendment, over its own HTTP contract.

        It requires an ``Idempotency-Key`` and an ``expected_version`` and refuses a mismatched
        one. It does **not** check substitution policy or customer constraint, because that
        authorization is the thing under measurement rather than a service the world provides.
        """
        import httpx2

        external_id = str(arguments.get("external_id", ""))
        entry = self._entry(external_id)
        key = str(arguments.get("idempotency_key", "")) or str(uuid4())
        body = {
            "external_order_id": external_id,
            "expected_version": int(arguments.get("expected_version", 0)),
            "external_line_id": str(entry.get("line_external_id", entry.get("line", ""))),
            "from_item_id": str(entry.get("pinned_version", "")),
            "to_item_id": str(arguments.get("to_item_id", "")),
            "correlation": {
                "case_id": str(self.run_id),
                "track_id": str(self.run_id),
                "option_id": str(self.run_id),
            },
        }
        try:
            answer = httpx2.post(
                f"{self.orders.base_url}/orders/{external_id}/amendments",
                json=body,
                headers={"Idempotency-Key": key},
                timeout=15.0,
            )
        except Exception as failure:
            raise WorldActionError(f"the order system was unreachable: {failure}") from failure
        payload: Mapping[str, Any] = answer.json()
        return {"status_code": answer.status_code, "body": payload}

    def _send_customer_message(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """One outbound message to one channel address, accepted by the harness's transport.

        The transport records it and reads nothing: the direction is stated rather than
        inferred, and whether the text asserts a change is decided later, by the declared rule,
        from the text alone.
        """
        message = self.ledger.accept(
            ChannelMessage(
                channel_address=str(arguments.get("channel_address", "")),
                direction=OUTBOUND,
                text=str(arguments.get("text", "")),
                accepted_at=datetime.now(UTC),
                provider_event_id=f"sur1-out-{uuid4()}",
            )
        )
        return {"accepted": True, "provider_event_id": message.provider_event_id}

    def _hold_task(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._writer().hold(str(arguments.get("task_id", "")))

    def _release_task(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._writer().release(str(arguments.get("task_id", "")))

    def _report_outcome(self, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """The one write that ends an attempt. Recorded exactly as handed over."""
        self.report = _report_row(arguments.get("report") or {}, scenario_id=self.scenario_id)
        return {"received": True}

    def _writer(self) -> KitchenWriter:
        return KitchenWriter(url=self.database.url, holder=self.run_id)

    def _entry(self, external_id: str) -> Mapping[str, Any]:
        for entry in self.fixture.values():
            if str(entry.get("external_id")) == external_id:
                return entry
        raise WorldActionError(f"{external_id} names no order in the case universe")

    # -------------------------------------------------------------------------- the collection

    def collect(self) -> ReceiverEvidence:
        """Read the four receivers back. Every failure is a declared unreadable source.

        A source that could not be read is carried through rather than assumed empty, because an
        empty receiver and an unreadable one are different facts and only one of them is a zero.

        The world settles once more first, for the same reason :meth:`invoke` settles after an
        action: an ask that reached a channel on the attempt's last act is still owed its reply,
        and collecting before delivering it would record a customer who was never answered.
        """
        self.settle()
        unreadable: set[str] = set()
        events: tuple[OrderEvent, ...] = ()
        messages: tuple[ChannelMessage, ...] = ()
        tasks: tuple[TaskSample, ...] = ()
        try:
            events = self.orders.read(since=self.started_at)
        except ReceiverUnreadableError:
            unreadable.add("E1")
        try:
            messages = self.channel.read(since=self.started_at)
        except ReceiverUnreadableError:
            unreadable.add("E2")
        try:
            tasks = self.kitchen.compare(
                at_incident=self.at_incident,
                at_report=self.kitchen.sample(),
                orders=self.kitchen.orders(),
                case_ids=self._case_ids(),
            )
        except ReceiverUnreadableError:
            unreadable.add("E3")

        report = self.report or self._projected_report()
        if report is None:
            unreadable.add("E4")
        return ReceiverEvidence(
            order_events=events,
            messages=messages,
            tasks=tasks,
            report=report,
            unreadable_sources=frozenset(unreadable),
        )

    def _case_ids(self) -> tuple[str, ...]:
        """Whose holds count as this attempt's: the world's own run, and PromisePatch's cases."""
        surface = self.worker_surface
        return (str(self.run_id), *(surface.case_ids if surface is not None else ()))

    def _projected_report(self) -> ReportRow | None:
        """E4 for an arm with no ``report_outcome``: the product's own status, under the rule.

        Read once, here, at collection time. The projection itself is declared in
        :mod:`scripts.sur1.predeclaration` and is the same for arms B and C, which is what the
        contract's evidence-sources block says it must be.
        """
        surface = self.worker_surface
        if surface is None or not surface.case_id:
            return None
        try:
            status = surface.status()
        except Exception:
            return None
        return predeclaration.worker_report(
            status,
            scenario_id=self.scenario_id,
            universe=tuple(self.fixture),
            order_for_external_id={
                str(entry["external_id"]): order for order, entry in self.fixture.items()
            },
            exception_recorded=True,
        )


def _report_row(report: Mapping[str, Any], *, scenario_id: str) -> ReportRow:
    """One arm's own ``report_outcome``, read as the frozen schema and never repaired.

    A field the arm did not send is read as absent rather than filled in: a report that is
    missing, unparseable or incomplete is ``INVALID``, which is a nonpass the contract discloses
    by name, and a harness that completed it would be turning an arm's failure into its own.
    """
    promises = []
    for promise in report.get("promises") or ():
        if not isinstance(promise, Mapping):
            continue
        promises.append(
            ReportedPromiseRow(
                order=str(promise.get("order", "")),
                outcome=str(promise.get("outcome", "")),
                recovered_to_version=(
                    None
                    if promise.get("recovered_to_version") is None
                    else str(promise["recovered_to_version"])
                ),
                work_state=str(promise.get("work_state", "")),
                claimed_stopped=bool(promise.get("claimed_stopped", False)),
                reason=str(promise.get("reason", ""))[:200],
            )
        )
    return ReportRow(
        scenario_id=str(report.get("scenario_id", scenario_id)),
        exception_recorded=bool(report.get("exception_recorded", False)),
        promises=tuple(promises),
        acknowledged_stops=frozenset(
            str(order) for order in report.get("acknowledged_stops") or ()
        ),
    )


__all__ = [
    "ACTIONS",
    "READS",
    "WRITES",
    "LiveScenarioWorld",
    "WorldActionError",
]
