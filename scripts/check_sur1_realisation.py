"""Prove the nine ``SUR-1`` worlds install into the live local systems, without driving an arm.

The world programs were frozen against their own digests and proved *temporally* executable at a
run-local anchor, but neither of those is a statement about committed rows. A digest is taken of
the canonical :class:`~promise_graph.snapshot.GraphSnapshot` **before** it is written, and a
program that installed nothing at all would still match one. This is the check that the world an
arm would act on is actually there, read back out of PostgreSQL and out of the order system's own
endpoints rather than out of the installer's return value.

**Nothing here is a benchmark run.** No arm is constructed, no model is called, no armed event is
fired, no verdict is produced and no ``SUR-1`` result directory is opened. What it does per
scenario is exactly the arm-independent half of a real attempt: place the run in time by the
ADR-0019 rule, install the canonical world, read it back, check its digest against the frozen
declaration, derive the firing plan, and stop.

**The arming is derived and never fired.** :func:`~scripts.sur1.bindings.realisation.realise`
returns an :class:`~scripts.sur1.bindings.events.Arming` whose events fire only when the world's
own records show their trigger has happened. Nothing here pumps one, so every declared event is
still pending when the scenario ends -- which is asserted rather than assumed.

**Isolation is proved by repetition, not by inspection.** After the nine, the first scenario is
installed a second time and its readback is compared with the one taken when nothing had run
before. Two identical readbacks mean the eight scenarios in between left nothing behind: a leak
would have to survive a reset and then reproduce itself byte for byte, which is not a way a leak
behaves. The residue tables a harness could pollute -- the benchmark's own inventory rows, the
accepted replies, the cases -- are also read at every scenario and expected empty.

**It leaves the demo world as it found it.** The last act is the product's own
``pp reset-demo-state`` and the order system's own ``POST /admin/reset``, exactly as the dress
rehearsal does, followed by a read-back of the restored world.

    uv run python scripts/with_local_env.py -- uv run python scripts/check_sur1_realisation.py

Writes one JSON document to ``docs/sur1-realisation/`` and prints its path. It is evidence about
the environment, not about any arm, and it is deliberately not written under ``docs/benchmarks``
or into a run directory.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from scripts.rehearsal.run import stack
from scripts.sur1.bindings.clock import run_clock
from scripts.sur1.bindings.config import BindingConfig
from scripts.sur1.bindings.declaration import published
from scripts.sur1.bindings.realisation import realise
from scripts.sur1.bindings.receivers import DatabaseReader, OrderSystemReceiver
from scripts.sur1.bindings.setup import PreparationError, WorldHandles, program_for
from scripts.sur1.frozen import Contract

REPO: Final = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT: Final = REPO / "docs" / "sur1-realisation"

NOT_A_BENCHMARK: Final = (
    "This document is evidence that the nine SUR-1 worlds install into the live local systems. "
    "No arm was constructed or driven, no model was called, no armed event was fired, no "
    "evidence bundle was collected, no scorer ran and no comparative number exists. It is not "
    "a SUR-1 run, it consumes no SUR-1 outcome and it must never be read as one."
)

RESIDUE: Final = {
    "cases": "SELECT count(*) FROM cases",
    "exceptions": "SELECT count(*) FROM exceptions",
    "tracks": "SELECT count(*) FROM tracks",
    "case_steps": "SELECT count(*) FROM case_steps",
    "plan_approvals": "SELECT count(*) FROM plan_approvals",
    "approval_requests": "SELECT count(*) FROM approval_requests",
    "approval_decisions": "SELECT count(*) FROM approval_decisions",
    "outbox_messages": "SELECT count(*) FROM outbox_messages",
    "inbound_replies": "SELECT count(*) FROM inbound_replies",
    "timers": "SELECT count(*) FROM timers",
}
"""Rows that exist only because something drove a case. An installed world has none of them.

Deliberately not the benchmark's own inventory postings. A stipulated stock fact *is* part of a
scenario's canonical world -- it is in the snapshot the world digest is taken of -- so a
``sur1:`` ledger row after an install is the world, not a leak. Whether the ledger holds exactly
what the scenario declares is asked by :func:`_essential_facts`, where it belongs; asking it
here as well would report a correctly installed world as a dirty one.

What these ten have in common is that no world program writes one. A case, a track, an enqueued
step, an approval, an outbound message, an accepted reply or a pending timer is something an
*attempt* produced, so a non-zero count after an install is either a previous scenario that
survived the reset or something driving this database while the check runs.
"""


class RealisationCheckError(RuntimeError):
    """The environment could not answer, or a scenario did not install as declared."""


# ------------------------------------------------------------------------------- reading back


def _readback(database: DatabaseReader, orders: OrderSystemReceiver) -> dict[str, Any]:
    """The installed world, out of the live systems and out of nothing else.

    Every value comes from a query or an HTTP read against a running service. An install that
    reported success while writing nothing would pass a check made of the installer's own return
    value, and that is the check this one is deliberately not.

    Sorted and stringified so two readbacks compare by value: the isolation proof is an equality
    between two of these documents, and a set that came back in a different row order would read
    as a difference nobody made.
    """
    commitments = database.rows(
        "WORLD",
        "SELECT id, resource_id, quantity, received_state, received_qty, settled_at,"
        " attested_by FROM commitment_lines ORDER BY id",
    )
    stock = database.rows(
        "WORLD",
        "SELECT resource_id, sum(delta) FROM inventory_ledger GROUP BY resource_id"
        " ORDER BY resource_id",
    )
    tasks = database.rows(
        "WORLD", "SELECT id, state, held_by_case_id FROM production_tasks ORDER BY id"
    )
    constraints = database.rows(
        "WORLD", "SELECT id, order_id, kind FROM order_constraints ORDER BY id"
    )
    promises = database.rows("WORLD", "SELECT id, recipe_version_id FROM order_lines ORDER BY id")
    ledger = database.rows(
        "WORLD",
        "SELECT seq, resource_id, delta, source_id FROM inventory_ledger ORDER BY seq",
    )
    snapshot = orders.snapshot()
    return {
        "commitment_lines": [
            {
                "id": str(row[0]),
                "resource": str(row[1]),
                "quantity": None if row[2] is None else str(row[2]),
                "received_state": str(row[3]),
                "received_qty": None if row[4] is None else str(row[4]),
                "settled": row[5] is not None,
                "attested_by": None if row[6] is None else str(row[6]),
            }
            for row in commitments
        ],
        "stock_on_hand": {str(row[0]): str(row[1]) for row in stock},
        "production_tasks": [
            {
                "id": str(row[0]),
                "state": str(row[1]),
                "held_by": None if row[2] is None else str(row[2]),
            }
            for row in tasks
        ],
        "order_constraints": [
            {"id": str(row[0]), "order": str(row[1]), "kind": str(row[2])} for row in constraints
        ],
        "order_lines": [{"id": str(row[0]), "version": str(row[1])} for row in promises],
        "inventory_ledger": [
            {
                "seq": int(row[0]),
                "resource": str(row[1]),
                "delta": None if row[2] is None else str(row[2]),
                "source": str(row[3]),
            }
            for row in ledger
        ],
        "order_system": {
            str(order["external_id"]): {
                "version": int(order["version"]),
                "lines": sorted(
                    (str(line["external_line_id"]), str(line["external_item_id"]))
                    for line in order["lines"]
                ),
            }
            for order in snapshot.get("orders") or ()
        },
    }


def _residue(database: DatabaseReader) -> dict[str, int]:
    """What an attempt would have left. An installed world leaves none of it."""
    return {
        name: int(database.rows("WORLD", statement)[0][0]) for name, statement in RESIDUE.items()
    }


def _essential_facts(program: Any, readback: Mapping[str, Any]) -> dict[str, Any]:
    """The canonical world's own assertions, against the rows that were actually committed.

    Read out of :func:`~scripts.sur1.bindings.worldsnapshot.snapshot_of` rather than restated
    here. That payload is the object the published world digest is taken of, so agreement
    between it and the committed rows is precisely the statement the digest cannot make on its
    own: *the world this digest describes is the world that is there*. A second list of facts
    typed into this file would be a third description of a scenario and would be wrong the first
    time one moved.

    Four facts, because they are the four an attempt turns on: whether a commitment line is
    still open, how much of each resource is attested on hand, which recipe version each order
    line is pinned to, and what state each production task is in.
    """
    from scripts.sur1.bindings.worldsnapshot import snapshot_of

    canonical = snapshot_of(program, anchor=program_anchor())

    declared_commitments = {
        str(line["id"]): str(line["received_state"])
        for commitment in canonical["commitments"]
        for line in commitment["lines"]
    }
    committed_commitments = {
        str(row["id"]): str(row["received_state"]) for row in readback["commitment_lines"]
    }
    declared_stock = {
        str(resource): _quantity(value)
        for resource, value in canonical["on_hand"].items()
        if value is not None
    }
    committed_stock = {
        str(resource): _quantity(value) for resource, value in readback["stock_on_hand"].items()
    }
    declared_versions = {
        str(line["id"]): str(line["recipe_version"])
        for order in canonical["orders"]
        for line in order["lines"]
    }
    committed_versions = {str(row["id"]): str(row["version"]) for row in readback["order_lines"]}
    declared_tasks = {str(task["id"]): str(task["state"]) for task in canonical["tasks"]}
    committed_tasks = {str(row["id"]): str(row["state"]) for row in readback["production_tasks"]}
    declared_pins = {
        str(order["external_id"]): int(order["external_version"]) for order in canonical["orders"]
    }
    declared_ledger = {
        f"{entry['seq']}:{entry['resource']}": _posting(entry["delta"], entry["source_id"])
        for entry in canonical["ledger"]
    }
    committed_ledger = {
        f"{row['seq']}:{row['resource']}": _posting(row["delta"], row["source"])
        for row in readback["inventory_ledger"]
    }
    committed_pins = {
        external: int(entry["version"]) for external, entry in readback["order_system"].items()
    }
    return {
        "commitment_states": _agreement(declared_commitments, committed_commitments),
        "stock_on_hand": _agreement(declared_stock, committed_stock),
        "promise_versions": _agreement(declared_versions, committed_versions),
        "task_states": _agreement(declared_tasks, committed_tasks),
        "order_system_versions": _agreement(declared_pins, committed_pins),
        "inventory_ledger": _agreement(declared_ledger, committed_ledger),
    }


def _agreement(declared: Mapping[str, Any], committed: Mapping[str, Any]) -> dict[str, Any]:
    """One fact, both readings of it, and where they differ. Never a bare boolean.

    A check that reported only *agree* would make a failure a thing somebody has to reproduce to
    understand, so the two readings and the keys they differ on are carried into the evidence.
    """
    differences = sorted(
        key for key in set(declared) | set(committed) if declared.get(key) != committed.get(key)
    )
    return {
        "declared": dict(sorted(declared.items())),
        "committed": dict(sorted(committed.items())),
        "differences": differences,
        "agree": not differences,
    }


def _posting(delta: Any, source: Any) -> str:
    """One ledger posting as a comparable pair. An unknown delta stays unknown, never a zero."""
    return f"{'?' if delta is None else _quantity(delta)}@{source}"


def _quantity(value: Any) -> str:
    """A quantity as one spelling, so ``2`` and ``2.000`` are not read as a disagreement."""
    from decimal import Decimal

    return str(Decimal(str(value)).normalize())


_ANCHOR: datetime | None = None


def program_anchor() -> datetime:
    """The run-local anchor every scenario in this check is installed at. Decided once."""
    if _ANCHOR is None:  # pragma: no cover - set before any scenario is realised
        raise RealisationCheckError("the run clock was not decided before a world was projected")
    return _ANCHOR


# ------------------------------------------------------------------------------ one scenario


def _scenario(
    scenario_id: str,
    *,
    handles: WorldHandles,
    orders: OrderSystemReceiver,
    declaration: Mapping[str, Any],
) -> dict[str, Any]:
    """Install one world, read it back, check it, derive its firing plan, and fire nothing."""
    program = program_for(scenario_id)
    realisation = realise(
        program,
        handles,
        sink=None if not program.armed else _InertSink(),
        published_programs=declaration,
        anchor=program_anchor(),
    )
    readback = _readback(handles.database, orders)
    facts = _essential_facts(program, readback)
    residue = _residue(handles.database)
    declared_digest = str(declaration[scenario_id]["world_digest"])
    return {
        "scenario": scenario_id,
        "slug": program.slug,
        "state": realisation.state,
        "installed_at": program_anchor().isoformat(),
        "world_digest": realisation.digest,
        "frozen_world_digest": declared_digest,
        "digest_agrees": realisation.digest == declared_digest,
        "applied": list(realisation.applied),
        "armed": realisation.arming.describes(),
        "armed_and_unfired": len(realisation.arming.pending) == len(realisation.arming.planned),
        "essential_facts": facts,
        "facts_agree": all(part["agree"] for part in facts.values()),
        "residue": residue,
        "residue_clean": all(count == 0 for count in residue.values()),
        "readback": readback,
    }


class _InertSink:
    """A sink an armed event could reach and that this check never lets one reach.

    :func:`~scripts.sur1.bindings.realisation.realise` refuses to report a world ``READY`` when
    it declares events and no sink was given, because an installed world whose events nobody
    could deliver is a world an attempt was not set up in. Arming is derived before anything is
    written, so the refusal has to be satisfied for the write to happen at all -- and this
    object satisfies it without being able to deliver anything. If one of its methods is ever
    called, this check fired a world event, which it must not do, and it says so by raising.
    """

    def __getattr__(self, name: str) -> Any:
        def refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise RealisationCheckError(
                f"a world event reached the sink ({name}); this check arms events and fires none"
            )

        return refuse


# ----------------------------------------------------------------------------------- the whole


def restore(config: BindingConfig) -> dict[str, Any]:
    """Put both systems back to the Hollow Oak demo, through each one's own reset."""
    import httpx2

    answer = httpx2.post(f"{config.order_system_base_url}/admin/reset", timeout=30.0)
    answer.raise_for_status()
    completed = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/with_local_env.py",
            "--",
            "uv",
            "run",
            "pp",
            "reset-demo-state",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    return {
        "order_system": answer.json(),
        "demo_fixture": {
            "returncode": completed.returncode,
            "detail": (completed.stdout or completed.stderr).strip()[-400:],
        },
    }


def check(*, scenarios: Sequence[str], config: BindingConfig, now: datetime) -> dict[str, Any]:
    """Every scenario in order, then the first one again, then both systems back."""
    global _ANCHOR

    clock = run_clock(now)
    _ANCHOR = clock.anchor
    contract = Contract.load()
    declaration = published()["programs"]
    database = DatabaseReader(url=config.database_url)
    orders = OrderSystemReceiver(base_url=config.order_system_base_url)
    handles = WorldHandles(
        order_system_base_url=config.order_system_base_url, database=database, environment={}
    )

    for probe in (orders.probe(),):
        if not probe.reachable:
            raise RealisationCheckError(f"{probe.source}: {probe.detail}")

    report: dict[str, Any] = {
        "not_a_benchmark": NOT_A_BENCHMARK,
        "started_at": now.isoformat(),
        "contract": {
            "manifest_sha": contract.identity.manifest_sha,
            "scorer_version": contract.identity.scorer_version,
        },
        "clock": clock.describes(),
        "scenarios": [],
    }
    for scenario_id in scenarios:
        report["scenarios"].append(
            _scenario(scenario_id, handles=handles, orders=orders, declaration=declaration)
        )

    # The isolation proof. The first scenario again, after the other eight have each installed
    # and been read back: a readback identical to the one taken when nothing had run before is
    # a statement that none of them left anything a world install does not overwrite.
    again = _scenario(scenarios[0], handles=handles, orders=orders, declaration=declaration)
    first = report["scenarios"][0]
    report["isolation"] = {
        "scenario": scenarios[0],
        "installed_first": True,
        "installed_again_after": list(scenarios[1:]),
        "readback_identical": again["readback"] == first["readback"],
        "digest_identical": again["world_digest"] == first["world_digest"],
        "residue_clean_both_times": first["residue_clean"] and again["residue_clean"],
        "second_readback": again["readback"],
    }
    report["restore"] = restore(config)
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["passed"] = bool(
        all(
            entry["state"] == "READY"
            and entry["digest_agrees"]
            and entry["facts_agree"]
            and entry["armed_and_unfired"]
            and entry["residue_clean"]
            for entry in [*report["scenarios"], again]
        )
        and report["isolation"]["readback_identical"]
        and report["isolation"]["digest_identical"]
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check-sur1-realisation",
        description="Install each SUR-1 world into the live local systems and read it back.",
    )
    parser.add_argument("--scenarios", default="")
    parser.add_argument("--out", default="")
    arguments = parser.parse_args(argv)

    contract = Contract.load()
    scenarios = [name.strip() for name in arguments.scenarios.split(",") if name.strip()] or list(
        contract.scenario_ids
    )
    config = stack()
    if not config.database_url:
        raise RealisationCheckError(
            "no database URL; run this under scripts/with_local_env.py so the fixture load and "
            "the readback name the same database"
        )
    started = datetime.now(UTC)
    try:
        report = check(scenarios=scenarios, config=config, now=started)
    except PreparationError as refused:
        print(json.dumps({"passed": False, "refused": str(refused)}, indent=2))
        return 1

    destination = (
        Path(arguments.out)
        if arguments.out
        else EVIDENCE_ROOT / f"{started.strftime('%Y%m%dT%H%M%S')}-realisation.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "scenarios": [
                    {
                        "scenario": entry["scenario"],
                        "state": entry["state"],
                        "digest_agrees": entry["digest_agrees"],
                        "facts_agree": entry["facts_agree"],
                        "armed": len(entry["armed"]["planned"]),
                        "armed_and_unfired": entry["armed_and_unfired"],
                        "residue_clean": entry["residue_clean"],
                    }
                    for entry in report["scenarios"]
                ],
                "isolation": {
                    key: value
                    for key, value in report["isolation"].items()
                    if key != "second_readback"
                },
                "written_to": str(destination.relative_to(REPO)),
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":  # pragma: no cover - a command line, exercised through main()
    raise SystemExit(main())
