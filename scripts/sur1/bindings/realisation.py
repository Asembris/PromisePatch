"""Making one scenario's canonical world true in the live systems.

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

**Every failure is a refusal.** A realisation that could not complete raises
:class:`~scripts.sur1.bindings.setup.PreparationError`, the driver records ``HARNESS_FAILURE``
and no arm is driven. A world that quietly missed a stipulated fact would produce a number that
looks exactly like a number about the scenario, so a half-installed world is never reported as
a prepared one.

**The armed events are not wired here.** They fire during an attempt, conditional on what an arm
does, and the path that fires them does not exist. :func:`realise` refuses a program that carries
one, which is why the preflight still refuses a scored run. See ``docs/sur1-world-programs.md``.

**What has been executed, exactly once.** ``C04``'s canonical world was installed into the local
development PostgreSQL while a refusal message was being checked, and the local demo fixture was
restored immediately afterwards. No arm was driven at that world, no order system was posted to,
nothing was read back and no capture exists. Recorded here and in
:data:`~scripts.sur1.bindings.declaration.REALISATION_EXERCISED` rather than left out.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Final

from promise_graph.examples import hollow_oak
from scripts.sur1.bindings.setup import PreparationError

if TYPE_CHECKING:
    from scripts.sur1.bindings.programs import ScenarioProgram
    from scripts.sur1.bindings.setup import WorldHandles

WORLD_SOURCE: Final = "operator"
"""What the order system records as the source of a change that is its own, not an amendment."""


def realise(program: ScenarioProgram, handles: WorldHandles) -> tuple[str, ...]:
    """Install one scenario's canonical world, and name every step that was applied.

    The order is the program's own: the graph is loaded first, because an external change posted
    to the order system before the load would be a committed event about a world that was about
    to be replaced.
    """
    from scripts.sur1.bindings.programs import ExternalRepin

    pending = [event.name for event in program.armed if type(event).must_fire]
    if pending:
        raise PreparationError(
            f"{program.scenario_id} carries {len(pending)} armed world events the path that "
            f"fires them does not exist for ({', '.join(pending)}); an attempt driven at this "
            "world would be an attempt at a scenario whose stipulated events never happen"
        )

    applied = [_load(program, handles)]
    for step in program.steps:
        if isinstance(step, ExternalRepin):
            applied.append(_cross(step, handles))
    return tuple(applied)


def _load(program: ScenarioProgram, handles: WorldHandles) -> str:
    """Write the canonical graph through the product's own governed fixture load.

    ``anchor`` is the fixture's own byte-stable anchor rather than the wall clock. A benchmark
    attempt is not a demo: the two Valley Produce deliveries have to land where the frozen
    contract's quantities assume they land, and an anchor that moved with the clock would make
    two attempts at one scenario two different worlds.
    """
    import asyncio

    anchor = hollow_oak.ANCHOR
    graph = program.world(anchor=anchor)
    fixture_name = f"hollow-oak+sur1-{program.scenario_id}"
    try:
        asyncio.run(_write(graph, fixture_name=fixture_name, anchor=anchor))
    except PreparationError:
        raise
    except Exception as failure:
        raise PreparationError(
            f"{program.scenario_id}'s world could not be installed: "
            f"{type(failure).__name__}: {failure}"
        ) from failure
    return f"load:{fixture_name}"


async def _write(graph: Any, *, fixture_name: str, anchor: Any) -> None:
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
    passwords = {
        demo.BAKER_ROLE: settings.require_demo_worker_password(),
        demo.OWNER_ROLE: settings.require_demo_owner_password(),
    }
    engine = build_engine(settings.require_migration_database_url(), pool_size=1)
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


__all__ = ["WORLD_SOURCE", "realise"]
