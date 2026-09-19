"""The nine ``SUR-1`` world programs: each scenario's stipulated facts, as executable steps.

:mod:`~scripts.sur1.bindings.setup` holds the *mechanism* -- what a world program is, what a
step may reach, and the refusal for a scenario that has none. This module holds the *nine
programs themselves*, and it is separate because the two are answerable to different things.
The mechanism is a harness question. A program is a reading of a frozen document, and a reading
has to be auditable against the document one sentence at a time.

**What a program is allowed to read is the whole of the scientific argument here.**
:class:`StipulatedFacts` is a view over one frozen scenario that exposes five fields --
``stipulated_facts``, ``consent_facts``, ``stale_after``, ``duplicate_deliveries`` and
``contention_groups`` -- plus the scenario's own identity. Every other key of the frozen
scenario object raises :class:`ForbiddenFieldError`, including the ones that say what a correct
answer looks like. A program written while its scenario's expected disposition was visible is
not distinguishable from one written towards it, and "we did not look" is a promise where this
is a mechanism.

**Two layers, and they are different on purpose.**

*The canonical world* is pure. Every step projects one stipulated fact onto a
:class:`~promise_graph.snapshot.GraphSnapshot` built from a clean ``hollow_oak()``, in the order
the frozen document lists them, with no I/O and no clock. It is what
:mod:`~scripts.sur1.bindings.worldsnapshot` digests, and it is why two independent setups of the
same scenario are the same world rather than two worlds that look alike.

*The realisation* is what makes that world true in the live systems. It is deliberately not a
pile of bespoke statements: the canonical world **is** the thing loaded, through the product's
own governed fixture load, so the world an arm acts on and the world the digest describes are
one object. The only realisation that is not a fixture load is the external order system's own
change, because that system is a separate application with its own record and a pre-incident
edit has to cross it as its own event rather than be written into a mirror.

**An armed event is declared, never pre-delivered.** Three of the frozen fields describe things
that happen *during* an attempt and are conditional on what an arm does: a customer's reply to
an ask the arm has not sent yet, a second delivery of that reply, and the world moving between a
decision and an act. Writing any of them into the starting state would be setting up a world in
which somebody answered a question nobody asked. They are carried on the program as
:class:`ArmedEvent` values -- ordered, named, and part of the snapshot -- and the firing path is
not wired. See ``docs/sur1-world-programs.md``.

**Nothing here has been run.** No arm has been driven, no model reached, no evidence collected
and no comparative number exists. What the realisation path did run is recorded in
:mod:`~scripts.sur1.bindings.realisation` and in the freeze.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, Final

from promise_graph.examples import hollow_oak
from promise_graph.model import (
    InventoryLedgerEntry,
    LedgerSourceKind,
    OrderState,
    ReceivedState,
    TaskState,
)
from promise_graph.snapshot import GraphSnapshot

PROGRAM_SET_ID: Final = "SUR-1-WORLD-PROGRAMS"
PROGRAM_SET_VERSION: Final = "1.0.0"
"""Versioned beside the frozen contract and never inside it, exactly as the predeclaration is.

The contract is frozen and may not be edited to carry a later session's work. A program set is
that later session's work, so it is its own document with its own hash, and the preflight checks
that the code and the declaration still agree.
"""

ATTESTOR: Final = hollow_oak.BAKER
"""Who says a physical fact: the fixture's own baker, read from the dataset rather than typed."""


class ForbiddenFieldError(KeyError):
    """A world program asked a frozen scenario for a field it may not read.

    Raised rather than answered with ``None``, because a silent absence is something a program
    could branch on and a raise is something a test can prove never happens.
    """


class ProgramValidationError(RuntimeError):
    """A program names an entity, version or state the fixture does not have.

    Fail closed. A program that quietly skipped a stipulated fact would produce a world that
    looks exactly like the scenario and is not it.
    """


# ------------------------------------------------------------------- what a program may read


@dataclass(frozen=True, slots=True)
class StipulatedFacts:
    """A read-only view over one frozen scenario, exposing only what a program may consume.

    The allowlist is positive and the refusal is total: a key that is not named here raises,
    whether or not it exists in the document. That is what makes "this program did not read the
    expected answer" a property of the type rather than of the author's discipline.
    """

    ALLOWED: ClassVar[tuple[str, ...]] = (
        "id",
        "slug",
        "title",
        "dimension",
        "stipulated_facts",
        "consent_facts",
        "stale_after",
        "duplicate_deliveries",
        "contention_groups",
    )

    scenario_id: str
    slug: str
    title: str
    dimension: str
    stipulated_facts: tuple[str, ...]
    consent_facts: tuple[Mapping[str, Any], ...]
    stale_after: tuple[Mapping[str, Any], ...]
    duplicate_deliveries: tuple[Mapping[str, Any], ...]
    contention_groups: tuple[Mapping[str, Any], ...]

    @classmethod
    def read(cls, scenario: Mapping[str, Any]) -> StipulatedFacts:
        """Take the allowed fields off a frozen scenario and leave every other one unread."""
        return cls(
            scenario_id=str(scenario["id"]),
            slug=str(scenario["slug"]),
            title=str(scenario["title"]),
            dimension=str(scenario["dimension"]),
            stipulated_facts=tuple(str(fact) for fact in scenario["stipulated_facts"]),
            consent_facts=tuple(dict(fact) for fact in scenario.get("consent_facts") or ()),
            stale_after=tuple(dict(fact) for fact in scenario.get("stale_after") or ()),
            duplicate_deliveries=tuple(
                dict(fact) for fact in scenario.get("duplicate_deliveries") or ()
            ),
            contention_groups=tuple(
                dict(group) for group in scenario.get("contention_groups") or ()
            ),
        )

    def __getitem__(self, key: str) -> Any:
        if key not in self.ALLOWED:
            raise ForbiddenFieldError(
                f"{key!r} is not a field a world program may consume; a program may read "
                f"{', '.join(self.ALLOWED)} and nothing else"
            )
        return getattr(self, "scenario_id" if key == "id" else key)


def facts_of(scenario: Mapping[str, Any]) -> StipulatedFacts:
    """The only way a program is given a frozen scenario. Never the document's own object."""
    return StipulatedFacts.read(scenario)


# ------------------------------------------------------------------------------- the steps


@dataclass(frozen=True, slots=True)
class Step:
    """One stipulated fact, projected onto the canonical world and named in the declaration.

    Subclasses implement :meth:`project`. A step that asserts rather than changes returns the
    world it was given, and raises :class:`ProgramValidationError` when the assertion is false.
    """

    name: str

    def project(self, world: GraphSnapshot, *, anchor: datetime) -> GraphSnapshot:
        raise NotImplementedError

    def describes(self) -> dict[str, Any]:
        return {"step": type(self).__name__, "name": self.name}


@dataclass(frozen=True, slots=True)
class AttestCommitmentLine(Step):
    """Settle one supplier commitment line and post its physical outcome to the ledger once.

    The two halves are one fact and are written together on purpose: a line settled without its
    posting would be a receipt nobody can spend, and a posting without the settlement would let
    received supply go on being counted as expected as well.
    """

    line_id: str = ""
    state: ReceivedState = ReceivedState.RECEIVED
    arrived: Decimal = Decimal("0")

    def project(self, world: GraphSnapshot, *, anchor: datetime) -> GraphSnapshot:
        line = world.commitment_lines.get(self.line_id)
        if line is None:
            raise ProgramValidationError(f"{self.line_id} names no commitment line")
        if line.received_state is not ReceivedState.EXPECTED:
            raise ProgramValidationError(
                f"{self.line_id} is already {line.received_state}; a line settles exactly once"
            )
        commitment = world.commitments[line.commitment_id]
        settled = line.model_copy(
            update={
                "received_state": self.state,
                "received_qty": self.arrived if self.state is ReceivedState.SHORT else None,
                "settled_at": commitment.due_at,
                "attested_by": ATTESTOR,
            }
        )
        lines = tuple(
            settled if existing.id == settled.id else existing for existing in commitment.lines
        )
        commitments = dict(world.commitments)
        commitments[commitment.id] = commitment.model_copy(update={"lines": lines})
        world = world.replace(commitments=commitments)
        if self.arrived == 0:
            return world
        return _post(
            world,
            resource_id=line.resource_id,
            delta=self.arrived,
            source_kind=LedgerSourceKind.COMMITMENT_RECEIPT,
            source_id=f"receipt:{self.line_id}",
            recorded_at=commitment.due_at,
        )

    def describes(self) -> dict[str, Any]:
        return {
            **Step.describes(self),
            "commitment_line": self.line_id,
            "received_state": str(self.state),
            "arrived": str(self.arrived),
        }


@dataclass(frozen=True, slots=True)
class SpoilStock(Step):
    """Record that the whole on-hand quantity of one resource is unusable.

    A posting that cancels what is there rather than an edit of a total: the ledger is the
    record of what was attested, and a total is a derivation nothing here owns.
    """

    resource_id: str = ""

    def project(self, world: GraphSnapshot, *, anchor: datetime) -> GraphSnapshot:
        if self.resource_id not in world.resources:
            raise ProgramValidationError(f"{self.resource_id} names no resource")
        postings = world.ledger_by_resource.get(self.resource_id, ())
        if any(entry.delta is None for entry in postings):
            raise ProgramValidationError(
                f"{self.resource_id} has an unknown on-hand quantity, so there is no quantity "
                "to declare unusable"
            )
        on_hand = sum((entry.delta or Decimal("0") for entry in postings), Decimal("0"))
        return _post(
            world,
            resource_id=self.resource_id,
            delta=-on_hand,
            source_kind=LedgerSourceKind.EXCEPTION_FACT,
            source_id=f"unusable:{self.resource_id}",
            recorded_at=anchor,
        )

    def describes(self) -> dict[str, Any]:
        return {**Step.describes(self), "resource": self.resource_id}


@dataclass(frozen=True, slots=True)
class AuthorVariant(Step):
    """One authoring change made in advance: a recipe version and its policy entry both exist.

    Delegated to the fixture's own
    :func:`~promise_graph.examples.hollow_oak.with_charlotte_variant` rather than rebuilt here,
    so the authored version is the fixture's own vocabulary and not a second copy of it that
    could drift away from the one every other test uses.
    """

    version_id: str = ""
    policy_id: str = ""

    def project(self, world: GraphSnapshot, *, anchor: datetime) -> GraphSnapshot:
        authored = hollow_oak.with_charlotte_variant(world)
        if self.version_id not in authored.versions:
            raise ProgramValidationError(f"authoring did not produce {self.version_id}")
        if self.policy_id not in authored.policies:
            raise ProgramValidationError(f"authoring did not produce {self.policy_id}")
        return authored

    def describes(self) -> dict[str, Any]:
        return {**Step.describes(self), "version": self.version_id, "policy": self.policy_id}


@dataclass(frozen=True, slots=True)
class ExternalRepin(Step):
    """The external order system moves one order line to another version that already exists.

    Never a creation: the target must already be in the fixture, which is the whole difference
    between an order system changing its mind and this harness inventing a product. The order's
    external version advances by one, because that is what a receiving side sees and what an
    arm's ``expected_version`` has to match afterwards.
    """

    order_id: str = ""
    line_id: str = ""
    to_version_id: str = ""

    def project(self, world: GraphSnapshot, *, anchor: datetime) -> GraphSnapshot:
        if self.to_version_id not in world.versions:
            raise ProgramValidationError(f"{self.to_version_id} names no recipe version")
        line = world.order_lines.get(self.line_id)
        if line is None or line.order_id != self.order_id:
            raise ProgramValidationError(f"{self.line_id} is not a line of {self.order_id}")
        repinned = world.repin_order_line(self.line_id, self.to_version_id)
        order = repinned.orders[self.order_id]
        orders = dict(repinned.orders)
        orders[self.order_id] = order.model_copy(
            update={"external_version": order.external_version + 1, "state": OrderState.AMENDED}
        )
        return repinned.replace(orders=orders)

    def describes(self) -> dict[str, Any]:
        return {
            **Step.describes(self),
            "order": self.order_id,
            "line": self.line_id,
            "to_version": self.to_version_id,
        }


@dataclass(frozen=True, slots=True)
class RequireTaskState(Step):
    """A stipulated fact about work, asserted against the fixture and never written.

    ``STARTED`` is a physical claim about a kitchen. A setup that could write it would let this
    harness manufacture an attestation, so the fixture's own state is checked instead, and a
    scenario whose stipulation has drifted away from the fixture refuses to be prepared rather
    than being made true by the harness that measures it.
    """

    task_id: str = ""
    state: TaskState = TaskState.SCHEDULED

    def project(self, world: GraphSnapshot, *, anchor: datetime) -> GraphSnapshot:
        task = world.tasks.get(self.task_id)
        if task is None:
            raise ProgramValidationError(f"{self.task_id} names no production task")
        if task.state is not self.state:
            raise ProgramValidationError(
                f"{self.task_id} is {task.state} in the fixture and the scenario stipulates "
                f"{self.state}; the fixture is the authority and setup does not write work state"
            )
        return world

    def describes(self) -> dict[str, Any]:
        return {**Step.describes(self), "task": self.task_id, "state": str(self.state)}


@dataclass(frozen=True, slots=True)
class RequireNoConstraint(Step):
    """A stipulated fact that an order carries no recorded customer constraint."""

    order_id: str = ""

    def project(self, world: GraphSnapshot, *, anchor: datetime) -> GraphSnapshot:
        if self.order_id not in world.orders:
            raise ProgramValidationError(f"{self.order_id} names no order")
        recorded = world.constraints_by_order.get(self.order_id, ())
        if recorded:
            raise ProgramValidationError(
                f"{self.order_id} carries {', '.join(recorded)} and the scenario stipulates none"
            )
        return world

    def describes(self) -> dict[str, Any]:
        return {**Step.describes(self), "order": self.order_id}


@dataclass(frozen=True, slots=True)
class RequireNoSubstitute(Step):
    """A stipulated fact that no substitution policy offers a variant of one version."""

    version_id: str = ""

    def project(self, world: GraphSnapshot, *, anchor: datetime) -> GraphSnapshot:
        if self.version_id not in world.versions:
            raise ProgramValidationError(f"{self.version_id} names no recipe version")
        offered = sorted(
            policy.id
            for policy in world.policies.values()
            if policy.source_version_id == self.version_id
        )
        if offered:
            raise ProgramValidationError(
                f"{self.version_id} is offered a variant by {', '.join(offered)} and the "
                "scenario stipulates none"
            )
        return world

    def describes(self) -> dict[str, Any]:
        return {**Step.describes(self), "version": self.version_id}


@dataclass(frozen=True, slots=True)
class RequireConstraint(Step):
    """A stipulated fact that an order keeps one named recorded constraint."""

    order_id: str = ""
    constraint_id: str = ""

    def project(self, world: GraphSnapshot, *, anchor: datetime) -> GraphSnapshot:
        constraint = world.constraints.get(self.constraint_id)
        if constraint is None or constraint.order_id != self.order_id:
            raise ProgramValidationError(
                f"{self.order_id} does not carry {self.constraint_id}, which it is stipulated "
                "to keep"
            )
        return world

    def describes(self) -> dict[str, Any]:
        return {**Step.describes(self), "order": self.order_id, "constraint": self.constraint_id}


def _post(
    world: GraphSnapshot,
    *,
    resource_id: str,
    delta: Decimal,
    source_kind: LedgerSourceKind,
    source_id: str,
    recorded_at: datetime,
) -> GraphSnapshot:
    """Append one ledger posting, continuing the fixture's own sequence.

    The ``sur1:`` prefix keeps a harness posting distinguishable from a fixture one in the
    committed rows, and the ledger's uniqueness on ``(source_kind, source_id)`` is what makes a
    program that tried to post the same fact twice fail rather than double a quantity.
    """
    seq = 1 + max((entry.seq for entry in world.ledger), default=0)
    entry = InventoryLedgerEntry(
        seq=seq,
        resource_id=resource_id,
        delta=delta,
        source_kind=source_kind,
        source_id=f"sur1:{source_id}",
        recorded_at=recorded_at,
    )
    return world.replace(ledger=(*world.ledger, entry))


# ------------------------------------------------------------------------- the armed events


@dataclass(frozen=True, slots=True)
class ArmedEvent:
    """Something the world does during an attempt, declared at setup and conditional on an arm.

    Never written into the starting state. A customer reply present before the ask would be a
    world in which somebody answered a question nobody asked, and a stock movement applied at
    setup would be a shortage the arm could see coming.
    """

    name: str
    trigger: str
    effect: str

    must_fire: ClassVar[bool] = True
    """Whether something has to happen during the attempt for this event to be true.

    A declared scarcity is already true of the starting stock and fires nothing, which is a
    real difference and not a naming one: a world that owes a customer reply is unprepared
    until something can deliver it, and a world that is simply short of strawberries is not.
    """

    def describes(self) -> dict[str, Any]:
        return {
            "event": type(self).__name__,
            "name": self.name,
            "trigger": self.trigger,
            "effect": self.effect,
        }


@dataclass(frozen=True, slots=True)
class ScriptedReply(ArmedEvent):
    """One stipulated customer reply, due when the arm's ask reaches that channel.

    ``literal`` and ``authorising`` are carried verbatim from the frozen ``consent_facts`` and
    are never consulted by the world: whether words are a decision is the consent protocol's
    question and this is a transport. They travel so the declaration says what the frozen
    document said, and so a reply that was reworded later moves a hash.
    """

    order: str = ""
    channel: str = ""
    text: str = ""
    literal: bool = False
    authorising: bool = False
    deliveries: int = 1
    """How many times the provider delivers this one message, under one message identity."""

    def describes(self) -> dict[str, Any]:
        return {
            **ArmedEvent.describes(self),
            "order": self.order,
            "channel": self.channel,
            "text": self.text,
            "literal": self.literal,
            "authorising": self.authorising,
            "deliveries": self.deliveries,
        }


@dataclass(frozen=True, slots=True)
class WorldMoves(ArmedEvent):
    """The world changes between a decision and an act on it.

    The posting is the movement. What it makes stale is a consequence an arm has to notice for
    itself, and is deliberately not something the world enforces on an arm's behalf.
    """

    order: str = ""
    resource_id: str = ""
    delta: Decimal = Decimal("0")

    def describes(self) -> dict[str, Any]:
        return {
            **ArmedEvent.describes(self),
            "order": self.order,
            "resource": self.resource_id,
            "delta": str(self.delta),
        }


@dataclass(frozen=True, slots=True)
class Scarcity(ArmedEvent):
    """A physical quantity that cannot serve every claim on it at once.

    Declared rather than enforced, and realised entirely by the starting stock: the shortage is
    a quantity in the ledger, not a rule the world applies to an arm. It is carried so the
    snapshot states the contention the frozen document states, and so that a group whose
    membership moved moves a hash.
    """

    must_fire: ClassVar[bool] = False

    group: str = ""
    members: tuple[str, ...] = ()
    max_recovered: int = 0
    min_recovered_for_complete: int = 0

    def describes(self) -> dict[str, Any]:
        return {
            **ArmedEvent.describes(self),
            "group": self.group,
            "members": list(self.members),
            "max_recovered": self.max_recovered,
            "min_recovered_for_complete": self.min_recovered_for_complete,
        }


# ----------------------------------------------------------------------------- the program


@dataclass(frozen=True, slots=True)
class ScenarioProgram:
    """One scenario's stipulated facts, as an ordered program against a clean fixture."""

    scenario_id: str
    slug: str
    dimension: str
    steps: tuple[Step, ...]
    armed: tuple[ArmedEvent, ...] = ()
    incident: Mapping[str, Any] = field(default_factory=dict)
    consumed: tuple[str, ...] = ()
    """Which allowed frozen fields this program actually read. Recorded, never inferred."""

    def world(self, *, anchor: datetime = hollow_oak.ANCHOR) -> GraphSnapshot:
        """The canonical starting world: a clean fixture with every step applied in order."""
        world = hollow_oak.hollow_oak(anchor)
        for step in self.steps:
            world = step.project(world, anchor=anchor)
        return world

    def apply(self, handles: Any) -> tuple[str, ...]:
        """Make the canonical world true in the live systems, and say what was applied.

        Imported where it is used rather than at module scope: this module is pure and is
        imported by the preflight, the declaration and the tests, none of which may reach a
        database by importing it.
        """
        from scripts.sur1.bindings.realisation import realise

        return realise(self, handles)

    def describes(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario_id,
            "slug": self.slug,
            "dimension": self.dimension,
            "consumed_fields": list(self.consumed),
            "steps": [step.describes() for step in self.steps],
            "armed_events": [event.describes() for event in self.armed],
            "incident": dict(self.incident),
        }

    def identity(self) -> str:
        """This one program's hash, over exactly what it declares itself to be."""
        return sha(self.describes())


def sha(payload: Any) -> str:
    """The manifest's own hashing: canonical JSON, then SHA-256."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# ------------------------------------------------------------------------------ the nine

STRAWBERRY_LINE: Final = hollow_oak.VP_TODAY_STRAWBERRY
"""The one commitment line every berry scenario settles. Named from the fixture, never typed."""

RASPBERRY_REPORT: Final = "today's raspberry delivery didn't arrive"
SCOPE_QUESTION: Final = "the whole delivery, or just the raspberries?"
SCOPE_ANSWER_CAME: Final = "just the raspberries -- the strawberries came"
SCOPE_ANSWER_SHORT: Final = "just the raspberries -- but the strawberries were short"
MASCARPONE_REPORT: Final = "the mascarpone in the walk-in went off"
"""The worker's words, taken verbatim from each scenario's own ``stipulated_facts``.

They are constants rather than a lookup because every arm reads them through ``get_incident``
and a paraphrase would make three arms answer three slightly different questions.
"""


def _incident(reported: str, *, answer: str | None = None) -> dict[str, Any]:
    """What the worker said, and the answer they gave if the report was ambiguous in scope."""
    if answer is None:
        return {"reported": reported, "clarification": None}
    return {
        "reported": reported,
        "clarification": {"question": SCOPE_QUESTION, "answer": answer},
    }


def _received_strawberries(arrived: str) -> AttestCommitmentLine:
    return AttestCommitmentLine(
        name="the strawberry line is attested received",
        line_id=STRAWBERRY_LINE,
        state=ReceivedState.RECEIVED,
        arrived=Decimal(arrived),
    )


def _short_strawberries(arrived: str) -> AttestCommitmentLine:
    return AttestCommitmentLine(
        name="the strawberry line is attested short",
        line_id=STRAWBERRY_LINE,
        state=ReceivedState.SHORT,
        arrived=Decimal(arrived),
    )


def _replies(facts: StipulatedFacts) -> tuple[ScriptedReply, ...]:
    """Every stipulated customer reply, in the order the frozen document lists them.

    Order is load-bearing and is why this reads the list rather than a mapping by order: C02 is
    two replies from one customer on one channel, and a set of them is a different scenario.
    The duplicate-delivery count is joined in here, because one message delivered twice is one
    reply with two deliveries and not two replies.
    """
    duplicates = {
        str(entry["order"]): int(entry.get("deliveries", 1)) for entry in facts.duplicate_deliveries
    }
    scripted = []
    for position, fact in enumerate(facts.consent_facts, start=1):
        order = str(fact["order"])
        scripted.append(
            ScriptedReply(
                name=f"reply {position} on {fact['channel']}",
                trigger=f"an ask reaches {fact['channel']} about {order}",
                effect="the customer's words arrive on the channel, uninterpreted",
                order=order,
                channel=str(fact["channel"]),
                text=str(fact["text"]),
                literal=bool(fact.get("literal", False)),
                authorising=bool(fact.get("authorising", False)),
                deliveries=duplicates.get(order, 1),
            )
        )
    return tuple(scripted)


def _staleness(facts: StipulatedFacts, *, resource_id: str, delta: str) -> tuple[WorldMoves, ...]:
    """The frozen ``stale_after`` entries, as movements armed on a decision about that order."""
    return tuple(
        WorldMoves(
            name=f"the world moves after {entry['order']} decides",
            trigger=f"an authorising reply for {entry['order']} has arrived and not been acted on",
            effect=str(entry["after_which"]),
            order=str(entry["order"]),
            resource_id=resource_id,
            delta=Decimal(delta),
        )
        for entry in facts.stale_after
    )


def _scarcity(facts: StipulatedFacts) -> tuple[Scarcity, ...]:
    """The frozen ``contention_groups``, as declared scarcity over the starting quantity."""
    return tuple(
        Scarcity(
            name=f"scarcity {group['id']}",
            trigger="the starting stock is already less than every claim on it together",
            effect="at most one member of the group can be recovered from this quantity",
            group=str(group["id"]),
            members=tuple(str(member) for member in group["members"]),
            max_recovered=int(group["max_recovered"]),
            min_recovered_for_complete=int(group["min_recovered_for_complete"]),
        )
        for group in facts.contention_groups
    )


def _c01(facts: StipulatedFacts) -> ScenarioProgram:
    return ScenarioProgram(
        scenario_id=facts.scenario_id,
        slug=facts.slug,
        dimension=facts.dimension,
        steps=(_received_strawberries("6.0"),),
        armed=_replies(facts),
        incident=_incident(RASPBERRY_REPORT, answer=SCOPE_ANSWER_CAME),
        consumed=("stipulated_facts", "consent_facts"),
    )


def _c02(facts: StipulatedFacts) -> ScenarioProgram:
    """C01's world. The two replies differ from C01 and they are both armed, in order."""
    return ScenarioProgram(
        scenario_id=facts.scenario_id,
        slug=facts.slug,
        dimension=facts.dimension,
        steps=(_received_strawberries("6.0"),),
        armed=_replies(facts),
        incident=_incident(RASPBERRY_REPORT, answer=SCOPE_ANSWER_CAME),
        consumed=("stipulated_facts", "consent_facts"),
    )


def _c03(facts: StipulatedFacts) -> ScenarioProgram:
    """The authoring change comes first: it is stipulated as made *in advance* of the report."""
    return ScenarioProgram(
        scenario_id=facts.scenario_id,
        slug=facts.slug,
        dimension=facts.dimension,
        steps=(
            AuthorVariant(
                name="a strawberry Charlotte version and its policy entry exist",
                version_id=hollow_oak.CHARLOTTE_V2,
                policy_id=hollow_oak.POLICY_CHARLOTTE,
            ),
            RequireConstraint(
                name="the wedding order keeps its recorded NO_SUBSTITUTION constraint",
                order_id=hollow_oak.ORDER_C,
                constraint_id=hollow_oak.CONSTRAINT_C_NOSUB,
            ),
            _received_strawberries("6.0"),
        ),
        armed=_replies(facts),
        incident=_incident(RASPBERRY_REPORT, answer=SCOPE_ANSWER_CAME),
        consumed=("stipulated_facts", "consent_facts"),
    )


def _c04(facts: StipulatedFacts) -> ScenarioProgram:
    """No delivery is attested here: the exception is the walk-in, and nothing else moved."""
    return ScenarioProgram(
        scenario_id=facts.scenario_id,
        slug=facts.slug,
        dimension=facts.dimension,
        steps=(
            SpoilStock(
                name="the mascarpone stock is recorded unusable",
                resource_id=hollow_oak.MASCARPONE,
            ),
        ),
        armed=(),
        incident=_incident(MASCARPONE_REPORT),
        consumed=("stipulated_facts",),
    )


def _c05(facts: StipulatedFacts) -> ScenarioProgram:
    """Lena's change is first because it is stipulated as *before any exception is reported*."""
    return ScenarioProgram(
        scenario_id=facts.scenario_id,
        slug=facts.slug,
        dimension=facts.dimension,
        steps=(
            ExternalRepin(
                name="Lena moves ord-d to the Lemon Curd Layer in the order system",
                order_id=hollow_oak.ORDER_D,
                line_id=hollow_oak.LINE_D,
                to_version_id=hollow_oak.LCL_V1,
            ),
            _received_strawberries("6.0"),
        ),
        armed=_replies(facts),
        incident=_incident(RASPBERRY_REPORT, answer=SCOPE_ANSWER_CAME),
        consumed=("stipulated_facts", "consent_facts"),
    )


def _c06(facts: StipulatedFacts) -> ScenarioProgram:
    """C01's world. The consumption is armed, not applied: it happens *after* the decision."""
    return ScenarioProgram(
        scenario_id=facts.scenario_id,
        slug=facts.slug,
        dimension=facts.dimension,
        steps=(_received_strawberries("6.0"),),
        armed=(
            *_replies(facts),
            *_staleness(facts, resource_id=hollow_oak.STRAWBERRIES, delta="-5.6"),
        ),
        incident=_incident(RASPBERRY_REPORT, answer=SCOPE_ANSWER_CAME),
        consumed=("stipulated_facts", "consent_facts", "stale_after"),
    )


def _c07(facts: StipulatedFacts) -> ScenarioProgram:
    """C01's world. The duplication is the provider's and rides on the one scripted reply."""
    return ScenarioProgram(
        scenario_id=facts.scenario_id,
        slug=facts.slug,
        dimension=facts.dimension,
        steps=(_received_strawberries("6.0"),),
        armed=_replies(facts),
        incident=_incident(RASPBERRY_REPORT, answer=SCOPE_ANSWER_CAME),
        consumed=("stipulated_facts", "consent_facts", "duplicate_deliveries"),
    )


def _c08(facts: StipulatedFacts) -> ScenarioProgram:
    """Ahmed's change, then three assertions, then the receipt -- the document's own order."""
    return ScenarioProgram(
        scenario_id=facts.scenario_id,
        slug=facts.slug,
        dimension=facts.dimension,
        steps=(
            ExternalRepin(
                name="Ahmed moves ord-e to the Raspberry Lemon Layer in the order system",
                order_id=hollow_oak.ORDER_E,
                line_id=hollow_oak.LINE_E,
                to_version_id=hollow_oak.RLL_V2,
            ),
            RequireNoConstraint(
                name="ord-e carries no recorded customer constraint",
                order_id=hollow_oak.ORDER_E,
            ),
            RequireNoSubstitute(
                name="no substitution policy offers a variant of rv-raspberry-lemon-2",
                version_id=hollow_oak.RLL_V2,
            ),
            RequireTaskState(
                name="task-ol-e is already started when the exception is reported",
                task_id=f"task-{hollow_oak.LINE_E}",
                state=TaskState.STARTED,
            ),
            _received_strawberries("6.0"),
        ),
        armed=_replies(facts),
        incident=_incident(RASPBERRY_REPORT, answer=SCOPE_ANSWER_CAME),
        consumed=("stipulated_facts", "consent_facts"),
    )


def _c09(facts: StipulatedFacts) -> ScenarioProgram:
    """The shortfall is a quantity, not a rule: 1.0 kg arrived and the ledger says so."""
    return ScenarioProgram(
        scenario_id=facts.scenario_id,
        slug=facts.slug,
        dimension=facts.dimension,
        steps=(_short_strawberries("1.0"),),
        armed=(*_replies(facts), *_scarcity(facts)),
        incident=_incident(RASPBERRY_REPORT, answer=SCOPE_ANSWER_SHORT),
        consumed=("stipulated_facts", "consent_facts", "contention_groups"),
    )


BUILDERS: Final[Mapping[str, Any]] = {
    "C01": _c01,
    "C02": _c02,
    "C03": _c03,
    "C04": _c04,
    "C05": _c05,
    "C06": _c06,
    "C07": _c07,
    "C08": _c08,
    "C09": _c09,
}
"""One builder per scenario, by identifier. Nine, and the preflight checks that it is nine."""


def programs(document: Mapping[str, Any] | None = None) -> dict[str, ScenarioProgram]:
    """Build every program from the frozen contract, reading only the allowed fields.

    The scenarios are taken through :class:`StipulatedFacts` before a builder sees them, so a
    builder has no object on which an expected answer exists to be read.
    """
    if document is None:
        from scripts.sur1.frozen import Contract

        document = Contract.load().document
    built: dict[str, ScenarioProgram] = {}
    for scenario in document["scenarios"]:
        facts = facts_of(scenario)
        builder = BUILDERS.get(facts.scenario_id)
        if builder is None:
            raise ProgramValidationError(
                f"{facts.scenario_id} is in the frozen contract and has no world program"
            )
        built[facts.scenario_id] = builder(facts)
    unmatched = sorted(set(BUILDERS) - set(built))
    if unmatched:
        raise ProgramValidationError(
            f"{', '.join(unmatched)} has a world program and is not in the frozen contract"
        )
    return built


def program_set() -> dict[str, Any]:
    """The whole program set as one canonical payload: what the declaration publishes."""
    built = programs()
    return {
        "program_set_id": PROGRAM_SET_ID,
        "program_set_version": PROGRAM_SET_VERSION,
        "fixture": "promise_graph.examples.hollow_oak",
        "programs": {scenario_id: built[scenario_id].describes() for scenario_id in sorted(built)},
    }


def program_set_sha() -> str:
    """The identity of the nine programs, recomputed from what they declare themselves to be."""
    return sha(program_set())


__all__ = [
    "ATTESTOR",
    "BUILDERS",
    "PROGRAM_SET_ID",
    "PROGRAM_SET_VERSION",
    "ArmedEvent",
    "AttestCommitmentLine",
    "AuthorVariant",
    "ExternalRepin",
    "ForbiddenFieldError",
    "ProgramValidationError",
    "RequireConstraint",
    "RequireNoConstraint",
    "RequireNoSubstitute",
    "RequireTaskState",
    "Scarcity",
    "ScenarioProgram",
    "ScriptedReply",
    "SpoilStock",
    "Step",
    "StipulatedFacts",
    "WorldMoves",
    "facts_of",
    "program_set",
    "program_set_sha",
    "programs",
    "sha",
]
