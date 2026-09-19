"""Fixture construction and the kitchen, kept in their own module so an arm cannot reach them.

Everything here is a privilege the harness holds and no arm has. Bringing the world to a
scenario's stipulated facts, and moving a production task on behalf of an arm that is not
PromisePatch, are the world's own powers; an arm receives an
:class:`~scripts.sur1.arms.AttemptRequest` carrying a world and a budget, and there is no path
from either to this module.

**Two different things live here and they are different on purpose.**

:class:`WorldProgram` is *preparation*: what a scenario's stipulated facts do to a clean fixture,
before any arm is constructed. It runs once per attempt, from the driver, and every arm sees the
same world afterwards.

:class:`KitchenWriter` is a *world facility*: the frozen tool surface gives every arm
``hold_task`` and ``release_task``, and something has to perform them for an arm that is not the
system which owns the production tasks. It performs exactly those two actions and nothing else.

**The nine scenario programs are not written here and this is the gap that remains.** The frozen
contract states each scenario's stipulated facts as English sentences -- *the strawberry line is
therefore attested received: 6.0 kg* -- and there is no machine-readable form of them in the
document. Turning nine of those into world programs is scenario preparation, it is the execution
session's own authoring, and it is deliberately not done in the session that also built the
scoring path: a program written while its scenario's ground truth is visible is not
distinguishable from one written towards it. :data:`PROGRAMS` is therefore empty,
:func:`program_for` refuses a scenario it has no program for, and the preflight refuses a scored
run for any scenario in that state. The mechanism is closed; the authoring is named.

**Nothing here has been run against a ``SUR-1`` scenario.**
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol
from uuid import UUID

from scripts.sur1.bindings.receivers import DatabaseReader

ROOT: Final = Path(__file__).resolve().parents[3]

HELD: Final = "HELD"
SCHEDULED: Final = "SCHEDULED"
"""The two task states this module is permitted to write.

Never ``STARTED`` and never ``STOPPED_BY_A_PERSON``: starting work is a physical fact and
stopping it is a person, and a benchmark facility that could write either would let an arm's
tool call produce an attestation. See ADR-0017 and ``docs/started-work-contract.md``.
"""


class PreparationError(RuntimeError):
    """The world could not be brought to a scenario's stipulated facts."""


class UnprogrammedScenarioError(PreparationError):
    """This scenario has no world program, so no arm may be driven at it.

    A refusal rather than a best effort. Driving an arm at a world that is missing a stipulated
    fact would produce a number about a scenario nobody set up, and the number would look exactly
    like a number about the scenario.
    """


# --------------------------------------------------------------------------- the world program


class WorldStep(Protocol):
    """One thing a scenario's stipulated facts do to a clean fixture."""

    name: str

    def apply(self, world: WorldHandles) -> None: ...


@dataclass(frozen=True, slots=True)
class WorldHandles:
    """What a world step is allowed to reach. Deliberately small and deliberately named.

    A step has the two systems and a way to run the product's own command line, which is the
    surface a physical correction is made on. It has no model, no arm, no budget and no scorer.
    """

    order_system_base_url: str
    database: DatabaseReader
    environment: Mapping[str, str] = field(default_factory=dict)

    def cli(self, *arguments: str) -> str:
        """Run one ``pp`` command, which is how a physical fact is corrected in this product.

        ``check=True``: a preparation step that failed must fail the preparation. A world that
        quietly missed a stipulated fact is the one thing worse than a world that refused to be
        prepared, because only the second is visible in the capture.
        """
        completed = subprocess.run(
            ["uv", "run", "pp", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={**self.environment},
            check=False,
        )
        if completed.returncode != 0:
            raise PreparationError(
                f"pp {' '.join(arguments)} exited {completed.returncode}: "
                f"{completed.stderr.strip()[:400]}"
            )
        return completed.stdout


@dataclass(frozen=True, slots=True)
class WorldProgram:
    """One scenario's stipulated facts, as an ordered list of steps against a clean fixture.

    Ordered because the contract says so -- *applies its stipulated facts in the order listed* --
    and because several of them are not commutative: a ledger consumption after a receipt is a
    different world from a ledger consumption before one.
    """

    scenario_id: str
    steps: tuple[WorldStep, ...]
    incident: Mapping[str, Any] = field(default_factory=dict)
    """What the worker said, and any answer they gave to a clarification.

    Part of the program rather than derived from the contract, because the frozen document states
    it as prose inside ``stipulated_facts`` and there is no machine-readable form of it. Every arm
    reads it through ``get_incident``, so it is one fact seen identically by three arms.
    """

    def apply(self, handles: WorldHandles) -> tuple[str, ...]:
        applied = []
        for step in self.steps:
            step.apply(handles)
            applied.append(step.name)
        return tuple(applied)


PROGRAMS: Final[dict[str, WorldProgram]] = {}
"""The nine scenario programs, by identifier. Empty, and see this module's docstring for why."""


def program_for(scenario_id: str) -> WorldProgram:
    """The program for one scenario, or a refusal naming what is missing."""
    try:
        return PROGRAMS[scenario_id]
    except KeyError:
        raise UnprogrammedScenarioError(
            f"{scenario_id} has no world program: its stipulated facts are prose in the frozen "
            "contract and nobody has authored them into world steps. No arm may be driven at a "
            "world that was not prepared."
        ) from None


def unprogrammed(scenario_ids: Sequence[str]) -> tuple[str, ...]:
    """Which of these scenarios could not be set up. The preflight refuses on a non-empty list."""
    return tuple(scenario_id for scenario_id in scenario_ids if scenario_id not in PROGRAMS)


# -------------------------------------------------------------------------- the kitchen facility


@dataclass(slots=True)
class KitchenWriter:
    """``hold_task`` and ``release_task``, for an arm that does not own the production tasks.

    Two statements and no others. A hold sets the task to ``HELD`` and records the holder;
    a release puts a task **this attempt holds** back to ``SCHEDULED`` and clears the holder.
    Releasing a hold somebody else took is refused, because a release that restored the literal
    ``SCHEDULED`` on work another party had held would be this harness asserting something about
    that party's decision.
    """

    url: str
    holder: UUID

    def _execute(self, statement: str, parameters: Sequence[Any]) -> int:
        import psycopg

        with (
            psycopg.connect(_dsn(self.url), autocommit=True, connect_timeout=5) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(statement, parameters)
            return int(cursor.rowcount)

    def hold(self, task_id: str) -> Mapping[str, Any]:
        """Hold one task so work cannot begin. Refused on work that has already started.

        The refusal is the product's own rule and is enforced here rather than left to an arm:
        releasing begun work would assert that it never began, so it may not be held in the
        first place. An arm that asks is told no, which is a reading about that arm.
        """
        changed = self._execute(
            "UPDATE production_tasks SET state = %s, held_by_case_id = %s"
            " WHERE id = %s AND state = %s",
            (HELD, str(self.holder), task_id, SCHEDULED),
        )
        if changed == 0:
            return {"held": False, "task_id": task_id, "reason": "not scheduled work"}
        return {"held": True, "task_id": task_id}

    def release(self, task_id: str) -> Mapping[str, Any]:
        changed = self._execute(
            "UPDATE production_tasks SET state = %s, held_by_case_id = NULL"
            " WHERE id = %s AND held_by_case_id = %s",
            (SCHEDULED, task_id, str(self.holder)),
        )
        if changed == 0:
            return {"released": False, "task_id": task_id, "reason": "not held by this attempt"}
        return {"released": True, "task_id": task_id}


def _dsn(url: str) -> str:
    scheme, separator, rest = url.partition("://")
    return f"{scheme.split('+')[0]}{separator}{rest}"


__all__ = [
    "HELD",
    "PROGRAMS",
    "SCHEDULED",
    "KitchenWriter",
    "PreparationError",
    "UnprogrammedScenarioError",
    "WorldHandles",
    "WorldProgram",
    "WorldStep",
    "program_for",
    "unprogrammed",
]
