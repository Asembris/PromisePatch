"""Making one scenario's canonical world true in the live systems, and arming what it owes.

:mod:`~scripts.sur1.bindings.programs` says what a scenario's world *is*. This module is the
only place that says how it is *installed*, and it is separate because the first is a reading of
a frozen document and the second is a set of writes against two running services.

**The canonical world is the thing installed, not a recipe for building something like it.**
The program's projected :class:`~promise_graph.snapshot.GraphSnapshot` is handed to the
product's own governed fixture load, which projects it to rows and writes them inside one
audited transaction. There is no second construction path and therefore no way for the world an
arm acts on to drift from the world the digest describes: they are the same object, hashed once
and loaded once.

**The order system is crossed, never mirrored into.** A pre-incident external change is that
system's own event -- rule ``B6`` turns on who committed it -- so it is made by posting the
operator change to the order simulator's own surface and letting it commit its own record. The
graph already carries the re-pin, because the change happened before the world was prepared;
what the post adds is the *event*, in the system of record, with its own version bump.

**A realisation is ``READY`` or it is a refusal, and there is nothing in between.** The order is
deliberate and every stage of it can only fail closed:

1. the firing plan is derived from what the program declares, which refuses a scenario whose
   stipulated event no observable trigger can honestly fire;
2. the world about to be installed is checked against the frozen declaration's own digest for
   that scenario, so a program that drifted from the freeze refuses before it is written;
3. the external order system is put back to its seeded order book;
4. the canonical graph is installed through the governed fixture load;
5. each pre-incident external change crosses into the order system's own record;
6. the declared events are armed, and only then is ``READY`` returned.

**The world is three systems and all three are prepared.** Step 3 exists because the world an arm
acts on is the order system, the customer channel and the kitchen, and resetting two of them is
not a clean fixture. The graph load gives PromisePatch an order book at version 1; the order
simulator keeps whatever versions the previous attempt left it at; and an amendment carrying
``expected_version: 1`` against an order the last attempt moved to 2 is answered ``409 Conflict``,
the recovery is abandoned and the promise escalates. Only the very first attempt of a run would
have seen a clean order book. It is reset **after** the two refusals above, so a scenario that
cannot be realised does not cost the order book.

A realisation that could not complete raises
:class:`~scripts.sur1.bindings.setup.PreparationError`, the driver records ``HARNESS_FAILURE``
and no arm is driven. A world that quietly missed a stipulated fact would produce a number that
looks exactly like a number about the scenario, so a half-installed world is never reported as a
prepared one -- and neither is an installed world whose events nothing could fire.

**The arming is not the firing.** Nothing here delivers a reply or moves stock. It hands back an
:class:`~scripts.sur1.bindings.events.Arming`, which fires only when the world's own records
show the trigger has happened. The arm that reaches a channel is not firing a benchmark event;
it is doing the ordinary thing the event was declared to be armed on.

**What has been executed, exactly once.** ``C04``'s canonical world was installed into the local
development PostgreSQL while a refusal message was being checked, and the local demo fixture was
restored immediately afterwards. No arm was driven at that world, no order system was posted to,
nothing was read back and no capture exists. Recorded here and in
:data:`~scripts.sur1.bindings.declaration.REALISATION_EXERCISED` rather than left out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from promise_graph.examples import hollow_oak
from scripts.sur1.bindings.events import Arming, EventPlanError
from scripts.sur1.bindings.setup import PreparationError

if TYPE_CHECKING:
    from scripts.sur1.bindings.events import WorldSink
    from scripts.sur1.bindings.programs import ScenarioProgram
    from scripts.sur1.bindings.setup import WorldHandles

WORLD_SOURCE: Final = "operator"
"""What the order system records as the source of a change that is its own, not an amendment."""

READY: Final = "READY"
"""The only state a realisation reports. Everything else is raised rather than returned."""


@dataclass(frozen=True, slots=True)
class Realisation:
    """One prepared scenario: what was installed, which world it is, and what it still owes.

    Returned whole or not at all. ``arming`` is the live half -- the declared events that have
    not happened yet and the triggers that will make them happen -- and it is carried on the
    receipt rather than left to a caller to remember, because an installed world whose events
    nobody armed is a world an attempt was not set up in.
    """

    scenario_id: str
    state: str
    digest: str
    applied: tuple[str, ...]
    arming: Arming

    @property
    def ready(self) -> bool:
        return self.state == READY

    def describes(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario_id,
            "state": self.state,
            "world_digest": self.digest,
            "applied": list(self.applied),
            "armed": self.arming.describes(),
        }


class Installer(Protocol):
    """The three writes a realisation makes, kept behind a name so their order can be proved.

    A test can hand :func:`realise` an installer that refuses and assert that nothing reports
    ``READY``, without a database, an order system, or a single row written. The default is the
    live one and there is no configuration by which a run could choose another.
    """

    def reset(self, handles: WorldHandles) -> str: ...

    def load(self, program: ScenarioProgram) -> str: ...

    def cross(self, step: Any, handles: WorldHandles) -> str: ...


@dataclass(frozen=True, slots=True)
class LiveInstaller:
    """The real writes: the product's own fixture load, and the order system's own surface."""

    expected_database: str = ""
    """The database the receivers read, so the load can refuse to write to a different one.

    :func:`_write` resolves its connection from ``promisepatch.config.get_settings()``, which
    falls back to the repository's own ``.env`` when nothing is exported. The receivers resolve
    theirs from ``SUR1_DATABASE_URL``. Nothing joined the two, so a run started without the local
    environment loaded would install its canonical world into whichever database ``.env`` names
    and then read its evidence out of another -- and every reading would be about a world that was
    never installed. :func:`_same_database` is what makes that a refusal instead.
    """

    anchor: Any = None
    """The instant the fixture's own offsets are measured from, or the fixture's own.

    A parameter with no configuration behind it: nothing in a ``SUR-1`` run passes one, so a
    scored install is at ``hollow_oak.ANCHOR`` exactly as before. It exists because the world
    snapshot renders every instant as an *offset* from the anchor, so the published world digest
    is the same whichever anchor a world is installed at -- which is what lets a rehearsal
    install the declared world at an instant the engine's own bakery-day arithmetic can still
    read, without describing a different world.
    """

    def reset(self, handles: WorldHandles) -> str:
        return _reset(handles)

    def load(self, program: ScenarioProgram) -> str:
        return _load(program, expected_database=self.expected_database, anchor=self.anchor)

    def cross(self, step: Any, handles: WorldHandles) -> str:
        return _cross(step, handles)


def realise(
    program: ScenarioProgram,
    handles: WorldHandles,
    *,
    sink: WorldSink | None = None,
    installer: Installer | None = None,
    published_programs: Mapping[str, Any] | None = None,
    anchor: Any = None,
) -> Realisation:
    """Install one scenario's canonical world, arm what it owes, and report it ``READY``.

    The order is the program's own: the graph is loaded first, because an external change posted
    to the order system before the load would be a committed event about a world that was about
    to be replaced.
    """
    from scripts.sur1.bindings.programs import ExternalRepin

    arming = _arm(program)
    if arming.planned and sink is None:
        raise PreparationError(
            f"{program.scenario_id} declares {len(arming.planned)} world events and no sink was "
            "given to perform them; an attempt driven at this world would be an attempt at a "
            "scenario whose stipulated events never happen"
        )
    digest = _verify(program, published_programs)

    writer = installer or LiveInstaller(expected_database=handles.database.url, anchor=anchor)
    applied = [writer.reset(handles), writer.load(program)]
    for step in program.steps:
        if isinstance(step, ExternalRepin):
            applied.append(writer.cross(step, handles))
    return Realisation(
        scenario_id=program.scenario_id,
        state=READY,
        digest=digest,
        applied=tuple(applied),
        arming=arming,
    )


def _arm(program: ScenarioProgram) -> Arming:
    """Derive the firing plan first, so an unfireable scenario refuses before anything is written.

    A plan that cannot be built is the honest refusal this whole path exists to make: the world
    would install perfectly and then owe a reply nothing could deliver.
    """
    try:
        return Arming.arm(program)
    except EventPlanError as failure:
        raise PreparationError(str(failure)) from failure


def _verify(program: ScenarioProgram, published: Mapping[str, Any] | None = None) -> str:
    """Check the world about to be installed against the frozen declaration's own digest.

    This is the starting-world check, made before the write rather than after it: the object
    handed to the fixture load is the object this digest was taken of, so a program that has
    drifted away from the freeze refuses rather than installing a world nobody declared. It is
    deliberately not a read-back of the committed rows -- that is a separate surface with its own
    schema, and the freeze is about the canonical form.
    """
    from scripts.sur1.bindings.declaration import DeclarationMismatchError
    from scripts.sur1.bindings.declaration import published as frozen_declaration
    from scripts.sur1.bindings.worldsnapshot import digest_of

    digest = digest_of(program)
    try:
        declared = dict(published) if published is not None else frozen_declaration()["programs"]
    except (DeclarationMismatchError, KeyError) as failure:
        raise PreparationError(
            f"{program.scenario_id}'s starting world could not be checked against the frozen "
            f"world-program declaration: {failure}"
        ) from failure
    entry = declared.get(program.scenario_id)
    if entry is None:
        raise PreparationError(
            f"{program.scenario_id} is not in the frozen world-program declaration, so there is "
            "no published world for the installed one to be checked against"
        )
    if entry.get("world_digest") != digest:
        raise PreparationError(
            f"{program.scenario_id}'s starting world is {digest} and the frozen declaration says "
            f"{entry.get('world_digest')}; the world about to be installed is not the declared one"
        )
    return digest


def _endpoint(url: str) -> tuple[str, str]:
    """A connection string's host, port and database name. Never its credential.

    Compared rather than the whole URL because the fixture load connects as the migration role
    and the receivers connect as the application role: two roles on one database are the same
    database, and two databases behind one role are not.
    """
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    return (f"{parsed.hostname or ''}:{parsed.port or ''}", parsed.path.lstrip("/"))


def _same_database(migration_url: str, expected: str) -> bool:
    return _endpoint(migration_url) == _endpoint(expected)


def _reset(handles: WorldHandles) -> str:
    """Put the external order system back to its seeded order book, through its own endpoint.

    Its own surface and not a write into its store: the order system is a separate application
    and its state is its to restore. ``POST /admin/reset`` is the endpoint it publishes for
    exactly this.
    """
    import httpx2

    try:
        answer = httpx2.post(f"{handles.order_system_base_url}/admin/reset", timeout=30.0)
    except Exception as failure:
        raise PreparationError(
            f"the order system could not be reset: {type(failure).__name__}: {failure}"
        ) from failure
    if answer.status_code != 200:
        raise PreparationError(
            f"the order system answered {answer.status_code} to a reset; an attempt driven at "
            "an order book the last attempt moved would be answered 409 on every amendment"
        )
    return "order-system:reset"


def _load(program: ScenarioProgram, *, expected_database: str = "", anchor: Any = None) -> str:
    """Write the canonical graph through the product's own governed fixture load.

    ``anchor`` is the fixture's own byte-stable anchor rather than the wall clock. A benchmark
    attempt is not a demo: the two Valley Produce deliveries have to land where the frozen
    contract's quantities assume they land, and an anchor that moved with the clock would make
    two attempts at one scenario two different worlds.
    """
    import asyncio

    anchor = anchor if anchor is not None else hollow_oak.ANCHOR
    graph = program.world(anchor=anchor)
    fixture_name = f"hollow-oak+sur1-{program.scenario_id}"
    try:
        asyncio.run(
            _write(
                graph,
                fixture_name=fixture_name,
                anchor=anchor,
                expected_database=expected_database,
            )
        )
    except PreparationError:
        raise
    except Exception as failure:
        raise PreparationError(
            f"{program.scenario_id}'s world could not be installed: "
            f"{type(failure).__name__}: {failure}"
        ) from failure
    return f"load:{fixture_name}"


async def _write(
    graph: Any, *, fixture_name: str, anchor: Any, expected_database: str = ""
) -> None:
    """One governed fixture load, in one transaction the harness owns and commits.

    Deliberately the same wiring the product's own ``pp reset-demo-state`` uses: the migration
    role, a single-connection engine and one ``begin`` block, so the load commits whole or not
    at all. The staff passwords come from the application's settings rather than from anything
    typed here; a harness that invented a credential would seed a deployment with one that is
    in a committed file.

    Imported inside the function on purpose. This module is imported by the program set, by the
    declaration and by the tests; importing the application's database layer at module scope
    would make reading a hash open a connection pool.
    """
    from datetime import UTC, datetime

    from promisepatch.config import get_settings
    from promisepatch.db.session import build_engine
    from promisepatch.db.uow import Actor
    from promisepatch.fixtures import demo
    from promisepatch.fixtures.reset import ensure_reset_allowed, reset_demo_state

    settings = get_settings()
    ensure_reset_allowed(settings)
    migration_url = settings.require_migration_database_url()
    if expected_database and not _same_database(migration_url, expected_database):
        raise PreparationError(
            "the fixture load resolved "
            f"{_endpoint(migration_url)[0]}/{_endpoint(migration_url)[1]} and the receivers read "
            f"{_endpoint(expected_database)[0]}/{_endpoint(expected_database)[1]}; installing a "
            "world into one database and reading evidence out of another would produce readings "
            "about a world that was never installed. Load the local environment "
            "(scripts/with_local_env.py) so both name the same database."
        )
    passwords = {
        demo.BAKER_ROLE: settings.require_demo_worker_password(),
        demo.OWNER_ROLE: settings.require_demo_owner_password(),
    }
    engine = build_engine(migration_url, pool_size=1)
    try:
        async with engine.begin() as connection:
            await reset_demo_state(
                connection,
                anchor=anchor,
                now=datetime.now(UTC),
                passwords=passwords,
                actor=Actor(kind="SYSTEM", id="sur1 world program"),
                snapshot=graph,
                fixture_name=fixture_name,
            )
    finally:
        await engine.dispose()


def _cross(step: Any, handles: WorldHandles) -> str:
    """Post one external change to the order system, so its own record holds its own event.

    The item the line moves to is the recipe version the step names: the simulator's catalogue
    is keyed on exactly those identifiers, which is what makes an external change expressible
    without a second vocabulary.
    """
    import httpx2

    external_id = _external_id(step.order_id, handles)
    url = f"{handles.order_system_base_url}/ui/orders/{external_id}/lines/{step.line_id}"
    try:
        answer = httpx2.post(
            url, data={"to_item_id": step.to_version_id}, follow_redirects=False, timeout=15.0
        )
    except Exception as failure:
        raise PreparationError(
            f"the order system did not accept {step.order_id}'s external change: "
            f"{type(failure).__name__}: {failure}"
        ) from failure
    if answer.status_code not in (200, 303):
        raise PreparationError(
            f"the order system answered {answer.status_code} to {step.order_id}'s external "
            f"change; the stipulated event did not cross"
        )
    return f"external-change:{step.order_id}->{step.to_version_id}"


def _external_id(order_id: str, handles: WorldHandles) -> str:
    """The order system's own identifier for one case-universe order.

    Read from the frozen contract's fixture table rather than derived from the order id, because
    the mapping is the contract's to state and a rule that guessed ``EXT-`` from ``ord-`` would
    be a second, unpublished copy of it.
    """
    from scripts.sur1.frozen import Contract

    orders: Sequence[tuple[str, Any]] = tuple(Contract.load().document["fixture"]["orders"].items())
    for known, entry in orders:
        if known == order_id:
            return str(entry["external_id"])
    raise PreparationError(f"{order_id} names no order in the frozen case universe")


__all__ = [
    "READY",
    "WORLD_SOURCE",
    "Installer",
    "LiveInstaller",
    "Realisation",
    "realise",
]
