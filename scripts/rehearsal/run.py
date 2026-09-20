"""The dress rehearsal, composed: install, read back, arm, drive three arms, capture, score, join.

This is the module that answers the question the ``SUR-1`` harness could not answer about itself:
whether its parts compose. Every part it uses is the real one --
:func:`~scripts.sur1.driver.drive`, :class:`~scripts.sur1.bindings.world.LiveScenarioWorld`, the
four receivers, the MCP transport, the workspace, the order simulator, the governed fixture load
and the customer-approval ingress. What is substituted is stated in one place, here, and is
exactly three things: the contract (``DR01`` instead of ``SUR-1``), the scorer (a rehearsal metric
instead of the frozen one) and arm A's model (a fixed plan instead of a provider).

**It cannot produce a scored artefact.** :data:`KIND` is ``development``, :func:`drive` refuses a
substituted contract or scorer for ``kind="scored"``, no authorisation is minted or held, and the
run root is ``docs/rehearsals/runs`` rather than the benchmark's. A rehearsal that wanted to
become a scored run would have to defeat all four.

**It leaves the demo world as it found it.** :func:`restore` runs the product's own
``reset-demo-state`` and the simulator's own ``/admin/reset``, and then reads both back. A
rehearsal that left ``DR01``'s world installed would be the next session's mystery.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from scripts.rehearsal import NOT_A_BENCHMARK, REHEARSAL_ID, RUNS_ROOT, SCENARIO
from scripts.rehearsal import ROOT as REPO
from scripts.rehearsal import contract as rehearsal_contract
from scripts.rehearsal.baseline import RehearsalModel
from scripts.rehearsal.program import bakery_anchor
from scripts.rehearsal.program import registry as rehearsal_registry
from scripts.rehearsal.scorer import REHEARSAL
from scripts.rehearsal.world import CustomerLinkSink
from scripts.sur1 import predeclaration
from scripts.sur1.adapters import AblationArm, BaselineArm, PromisePatchArm
from scripts.sur1.arms import ArmAdapter
from scripts.sur1.bindings.config import BindingConfig
from scripts.sur1.bindings.database import installer_target
from scripts.sur1.bindings.hostedworker import HostedWorkerControl
from scripts.sur1.bindings.lifecycle import ComposeWorkerControl
from scripts.sur1.bindings.promisepatch import LiveWorkerSurface, live_worker_surface
from scripts.sur1.bindings.receivers import (
    ChannelLedger,
    ChannelReceiver,
    DatabaseReader,
    KitchenReceiver,
    OrderSystemReceiver,
)
from scripts.sur1.bindings.world import LiveScenarioWorld
from scripts.sur1.bindings.worldsink import LedgerWriter
from scripts.sur1.capture import RunDirectory, write_once
from scripts.sur1.driver import Clock, drive, join
from scripts.sur1.frozen import Contract

KIND: Final = "development"
"""The only kind a rehearsal is driven as. Never ``scored``, and refused if asked for."""

HOST_ENV: Final = REPO / "docker" / "env" / "host.env"
MIGRATE_ENV: Final = REPO / "docker" / "env" / "migrate.env"
MCP_ENV: Final = REPO / "docker" / "env" / "mcp.env"
API_ENV: Final = REPO / "docker" / "env" / "api.env"


class RehearsalRefusedError(RuntimeError):
    """The rehearsal would not have been a rehearsal of anything, so it did not start."""


# ------------------------------------------------------------------------------- the stack


def _values(path: Path) -> dict[str, str]:
    """``KEY=value`` lines from one generated env file. The same reader ``with_local_env`` uses."""
    found: dict[str, str] = {}
    if not path.is_file():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        found[key.strip()] = value.strip()
    return found


def stack(environ: Mapping[str, str] | None = None) -> BindingConfig:
    """Where the local stack is, read from the files that configured it.

    ``SUR1_*`` is honoured first, so a machine that has them set uses them. Everything else comes
    out of the generated env files and the published ports, because a rehearsal that asked a
    person to retype six values would be a rehearsal nobody runs twice.
    """
    import os

    values = dict(os.environ if environ is None else environ)
    host = _values(HOST_ENV)
    migrate = _values(MIGRATE_ENV)
    mcp = _values(MCP_ENV)
    root = _values(REPO / ".env")

    def port(name: str, fallback: str) -> str:
        return values.get(name) or root.get(name) or fallback

    api = values.get("SUR1_API_BASE_URL") or (
        f"http://127.0.0.1:{port('PROMISEPATCH_API_PUBLISHED_PORT', '58000')}"
    )
    # The login endpoint matches ``Origin`` against ``PP_CORS_ORIGINS`` by exact string, and that
    # allowlist names the browser origins rather than the API's own. ``BindingConfig`` has no
    # default for it at all -- the one it used to have was a value the product answers 403 to --
    # so the rehearsal reads the allowlist the API was actually configured with and sends the
    # first origin on it, which is what ``SUR1_WORKSPACE_ORIGIN`` names for a scored run.
    allowed = [
        origin.strip()
        for origin in _values(API_ENV).get("PP_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    return BindingConfig(
        api_base_url=api.rstrip("/"),
        mcp_url=values.get("SUR1_MCP_URL")
        or f"http://127.0.0.1:{port('PROMISEPATCH_MCP_PUBLISHED_PORT', '58001')}/mcp",
        order_system_base_url=values.get("SUR1_ORDER_SYSTEM_BASE_URL")
        or f"http://127.0.0.1:{port('PROMISEPATCH_ORDER_SIMULATOR_PUBLISHED_PORT', '58100')}",
        workspace_origin=(
            values.get("SUR1_WORKSPACE_ORIGIN") or (allowed[0] if allowed else api.rstrip("/"))
        ),
        mcp_bearer_token=values.get("SUR1_MCP_BEARER_TOKEN") or mcp.get("PP_MCP_BEARER_TOKEN", ""),
        workspace_worker=values.get("SUR1_WORKSPACE_WORKER") or "maya",
        workspace_password=values.get("SUR1_WORKSPACE_PASSWORD")
        or migrate.get("PP_DEMO_WORKER_PASSWORD", ""),
        database_url=values.get("SUR1_DATABASE_URL") or host.get("PP_DATABASE_URL", ""),
        aws_region="",
    )


# -------------------------------------------------------------------------- the rehearsal world


@dataclass(slots=True)
class RehearsalWorld(LiveScenarioWorld):
    """:class:`LiveScenarioWorld`, with the customer's reply delivered through the real ingress.

    One overridden member. ``_sink`` is where a world decides how it performs what a scenario
    stipulated it would do, and the rehearsal's answer is
    :class:`~scripts.rehearsal.world.CustomerLinkSink` rather than the harness's own transport.
    Nothing else about the world changes: the same eleven actions, the same receivers, the same
    arm-blind settle.
    """

    api_base_url: str = ""
    sinks: list[CustomerLinkSink] = field(default_factory=list)

    def _sink(self) -> Any:
        made = CustomerLinkSink(
            api_base_url=self.api_base_url,
            database=self.database,
            channel=self.ledger,
            ledger=LedgerWriter(url=self.database.url),
        )
        self.sinks.append(made)
        return made

    def receipts(self) -> list[dict[str, Any]]:
        """Every door the world used to deliver a reply, in order, across the whole run."""
        return [receipt for sink in self.sinks for receipt in sink.receipts]


@dataclass(frozen=True, slots=True)
class Bench:
    """Everything the rehearsal was built out of, so a capture can say what ran."""

    config: BindingConfig
    contract: Contract
    anchor: datetime
    """The instant every attempt of this run installs its world from. Computed once."""

    world: RehearsalWorld
    surface: LiveWorkerSurface
    model: RehearsalModel
    arms: tuple[ArmAdapter, ...]

    def identity(self) -> dict[str, Any]:
        return {
            "not_a_benchmark": NOT_A_BENCHMARK,
            "rehearsal_id": REHEARSAL_ID,
            "scenario": SCENARIO,
            "contract": self.contract.identity.as_payload(),
            "scorer": {
                "version": REHEARSAL.version,
                "dimensions": list(REHEARSAL.safety_dimensions),
            },
            "model": dict(self.model.identity()),
            "world": dict(self.world.identity()),
            "surface": dict(self.surface.identity()),
            "arms": [arm.label for arm in self.arms],
            "world_anchor": self.anchor.isoformat(),
            "addresses": self.config.as_payload(),
        }


def build(config: BindingConfig, *, now: datetime | None = None) -> Bench:
    """Assemble the rehearsal. Opens no client and reaches nothing.

    The anchor is resolved here, once, and captured in the world-program registry's closure, so
    an attempt and its retry install the same world rather than two worlds an hour apart.
    """
    contract = rehearsal_contract.load()
    anchor = bakery_anchor(now or datetime.now(UTC))
    database = DatabaseReader(url=config.database_url)
    ledger = ChannelLedger()
    surface = live_worker_surface(
        mcp_url=config.mcp_url,
        bearer_token=config.mcp_bearer_token,
        api_base_url=config.api_base_url,
        origin=config.workspace_origin,
        username=config.workspace_worker,
        password=config.workspace_password,
    )
    world = RehearsalWorld(
        orders=OrderSystemReceiver(base_url=config.order_system_base_url),
        channel=ChannelReceiver(database=database, ledger=ledger),
        kitchen=KitchenReceiver(database=database),
        database=database,
        installer=installer_target(),
        ledger=ledger,
        fixture=contract.document["fixture"]["orders"],
        worker_surface=surface,
        program_lookup=rehearsal_registry(anchor=anchor),
        api_base_url=config.api_base_url,
        # The product's own durable worker, run in this process, which is what makes the two
        # PromisePatch arms of this rehearsal the two arms a scored run drives. Left at the
        # default, `LiveScenarioWorld` controls no worker: arm C's wrapper would rebind the
        # evaluator here while a container decided revalidation over there, the ablation would
        # reach nothing, no `REVALIDATION_CHECK` row could be read back to say which checks
        # ran, and a rehearsal of the corrected seam would have rehearsed the topology the
        # correction replaced. See ADR-0020 and docs/sur1-hosted-worker.md.
        worker=HostedWorkerControl(database=database, compose=ComposeWorkerControl()),
    )
    model = RehearsalModel(scenario_id=SCENARIO)
    promisepatch = PromisePatchArm(surface=surface)
    return Bench(
        config=config,
        contract=contract,
        anchor=anchor,
        world=world,
        surface=surface,
        model=model,
        arms=(
            BaselineArm(model=model),
            promisepatch,
            AblationArm(inner=promisepatch),
        ),
    )


# ------------------------------------------------------------------------------ the readiness


def readiness(bench: Bench) -> dict[str, Any]:
    """Ask every binding whether it is reachable. Mints nothing and authorises nothing.

    Deliberately **not** :func:`~scripts.sur1.preflight.preflight`. That function asks the
    questions a scored ``SUR-1`` run turns on -- the frozen identities, the world-program freeze,
    the declared classifier, the ground truth's reachability -- and mints a capability from the
    answers. A rehearsal has no business producing one, and answering those questions about a
    document that is not ``SUR-1`` would produce a report shaped like a scored preflight's.
    """
    checks = [
        {"name": probe.source, "passed": probe.reachable, "detail": probe.detail}
        for probe in (
            *bench.world.probes(),
            bench.surface.tools.probe(),
            bench.surface.workspace.probe(),
        )
    ]
    return {
        "checks": checks,
        "passed": all(check["passed"] for check in checks),
        "mints_no_authorisation": True,
    }


# --------------------------------------------------------------------------- install + readback


def simulator_reset(config: BindingConfig) -> dict[str, Any]:
    """Put the order book back to its seeded state, through the simulator's own endpoint."""
    import httpx2

    answer = httpx2.post(f"{config.order_system_base_url}/admin/reset", timeout=30.0)
    answer.raise_for_status()
    body: Mapping[str, Any] = answer.json()
    return dict(body)


def install(bench: Bench) -> dict[str, Any]:
    """Install ``DR01``'s world and arm what it owes, through the harness's own realisation."""
    bench.world.prepare(bench.contract.scenario(SCENARIO))
    arming = bench.world.arming
    return {
        "applied": list(bench.world.applied_steps),
        "world_digest": bench.world.world_digest,
        "armed": None if arming is None else arming.describes(),
    }


def readback(bench: Bench) -> dict[str, Any]:
    """Read the installed world back out of the live systems, not out of the objects that made it.

    Every value here comes from a query or an HTTP read against a running service. An install
    that reported success while writing nothing would pass a check made of the installer's own
    return value, and that is the check this one is deliberately not.
    """
    database = bench.world.database
    commitment = database.rows(
        "WORLD",
        "SELECT id, received_state, received_qty, attested_by FROM commitment_lines ORDER BY id",
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
    orders = bench.world.orders.snapshot()
    return {
        "database": {
            "commitment_lines": [
                {
                    "id": str(row[0]),
                    "received_state": str(row[1]),
                    "received_qty": None if row[2] is None else str(row[2]),
                    "attested_by": None if row[3] is None else str(row[3]),
                }
                for row in commitment
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
                {"id": str(row[0]), "order": str(row[1]), "kind": str(row[2])}
                for row in constraints
            ],
        },
        "order_system": {
            "orders": [
                {
                    "external_id": str(order.get("external_id")),
                    "version": order.get("version"),
                    "state": order.get("state"),
                    "items": [
                        str(line.get("external_item_id")) for line in order.get("lines") or ()
                    ],
                }
                for order in orders.get("orders") or ()
            ]
        },
    }


# ---------------------------------------------------------------------------------- the run


def execute(
    *,
    run_id: str,
    bench: Bench,
    command: Sequence[str],
    root: Path = RUNS_ROOT,
) -> RunDirectory:
    """Drive all three arms at ``DR01``, through the real driver, as a development run."""
    return drive(
        arms=bench.arms,
        world=bench.world,
        clock=Clock(monotonic=time.monotonic),
        run_id=run_id,
        kind=KIND,
        command=tuple(command),
        classifier=predeclaration.asserts_change,
        scenarios=(SCENARIO,),
        root=root,
        contract=bench.contract,
        scorer=REHEARSAL,
    )


def joined(directory: RunDirectory) -> dict[str, Any]:
    """The run's joined result: made once, and read rather than remade on a resume.

    :func:`~scripts.sur1.driver.join` writes ``result.json`` and refuses to write it twice, which
    is right -- a joined result is an artefact like every other one here, and the first
    invocation's account is not the second's to revise. So a resumed rehearsal reads the result
    that exists instead of failing at the last step.

    A resume that produced verdicts the first join did not cover is reported rather than merged:
    the keys are named, and whoever reads the report can join them deliberately. Rewriting the
    result to include them would be the one edit this layout exists to refuse.
    """
    if not directory.result_file.exists():
        return join(directory)

    existing: dict[str, Any] = json.loads(directory.result_file.read_text(encoding="utf-8"))
    covered = {
        f"{attempt['arm_token']}-{attempt['scenario_id']}-a{2 if attempt['retried'] else 1}"
        for attempt in existing["attempts"]
    }
    uncovered = sorted(directory.scored_attempts() - covered)
    return existing | {
        "joined": "read from the result an earlier invocation wrote; it was not rewritten",
        "verdicts_this_result_does_not_cover": uncovered,
    }


def restore(config: BindingConfig) -> dict[str, Any]:
    """Put the Hollow Oak demo world back, in both systems, and read both back.

    Two resets because there are two systems. ``reset-demo-state`` is the product's own governed
    fixture load and does not reach the order simulator; ``/admin/reset`` is the simulator's own
    and does not reach PostgreSQL. A rehearsal that ran only one of them would leave half of
    ``DR01``'s world behind.
    """
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
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    simulator = simulator_reset(config)
    return {
        "reset_demo_state": {
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip()[-400:],
            "stderr": completed.stderr.strip()[-400:],
        },
        "order_system_reset": simulator,
    }


def restored(bench: Bench) -> dict[str, Any]:
    """Read the restored world back and say whether it is the Hollow Oak demo again.

    Read from the live systems rather than from the reset's own return value, for the reason
    :func:`readback` gives: a reset that reported success while writing nothing would pass a
    check made of its own answer.

    ``cases`` is expected to be empty. ``reset_demo_state`` replaces every domain row the product
    owns, and the canonical demo case is provisioned by the worker at start-up, so it returns on
    the next ``docker compose restart worker`` or ``pp ensure-demo-case`` and not before. An empty
    case table is the honest post-reset state and is reported rather than corrected here.
    """
    database = bench.world.database
    settled = database.rows(
        "WORLD",
        "SELECT id FROM commitment_lines WHERE received_state <> 'EXPECTED' ORDER BY id",
    )
    strawberries = database.rows(
        "WORLD",
        "SELECT sum(delta) FROM inventory_ledger WHERE resource_id = 'res-strawberries'",
    )
    harness_rows = database.rows(
        "WORLD",
        "SELECT source_id FROM inventory_ledger WHERE source_id LIKE 'sur1:%' ORDER BY source_id",
    )
    cases = database.rows("WORLD", "SELECT count(*) FROM cases")
    replies = database.rows("WORLD", "SELECT count(*) FROM inbound_replies")
    orders = bench.world.orders.snapshot()
    versions = {
        str(order["external_id"]): int(order["version"]) for order in orders.get("orders") or ()
    }
    pinned = {
        str(entry["external_id"]): str(entry["pinned_version"])
        for entry in bench.contract.document["fixture"]["orders"].values()
    }
    items = {
        str(order["external_id"]): [
            str(line.get("external_item_id")) for line in order.get("lines") or ()
        ]
        for order in orders.get("orders") or ()
    }
    checks = {
        "no_settled_commitment_line": [str(row[0]) for row in settled] == [],
        "strawberries_back_to_fixture": str(strawberries[0][0]) == "2.000",
        "no_harness_ledger_postings": [str(row[0]) for row in harness_rows] == [],
        "no_cases": int(cases[0][0]) == 0,
        "no_inbound_replies": int(replies[0][0]) == 0,
        "every_order_at_version_one": set(versions.values()) == {1},
        "every_line_back_to_its_pinned_version": all(
            items.get(external) == [version] for external, version in pinned.items()
        ),
    }
    return {
        "checks": checks,
        "restored": all(checks.values()),
        "strawberries_on_hand": str(strawberries[0][0]),
        "order_versions": versions,
    }


def rehearse(
    *,
    run_id: str,
    config: BindingConfig,
    command: Sequence[str],
    root: Path = RUNS_ROOT,
    reset_at_exit: bool = True,
) -> dict[str, Any]:
    """The whole rehearsal, in the order the pipeline runs it."""
    bench = build(config)
    report: dict[str, Any] = {
        "not_a_benchmark": NOT_A_BENCHMARK,
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "bench": bench.identity(),
    }
    report["simulator_reset"] = simulator_reset(config)
    report["readiness"] = readiness(bench)
    if not report["readiness"]["passed"]:
        raise RehearsalRefusedError(
            "a binding this rehearsal drives is unreachable: "
            + "; ".join(
                f"{check['name']}: {check['detail']}"
                for check in report["readiness"]["checks"]
                if not check["passed"]
            )
        )
    report["install"] = install(bench)
    report["readback"] = readback(bench)

    directory = execute(run_id=run_id, bench=bench, command=command, root=root)
    report["result"] = joined(directory)
    report["customer_deliveries"] = bench.world.receipts()
    # The last install left a hosted worker running, and `reset-demo-state` is about to empty
    # forty-two tables and take an exclusive lock on each. That is the deadlock the installation
    # lifecycle exists to remove, and a restore is a fixture load like any other, so the worker
    # this rehearsal hosted goes down before the reset rather than racing it.
    report["worker_quiesced"] = _quiesce(bench)
    if reset_at_exit:
        report["restore"] = restore(config)
        report["restored"] = restored(bench)
    report["finished_at"] = datetime.now(UTC).isoformat()
    write_once(directory.path / _report_name(directory), report)
    return report


def _quiesce(bench: Bench) -> str:
    """Stop the worker this rehearsal hosted, and say what happened rather than raise.

    A rehearsal that failed to stop its own worker has still driven every arm and written every
    capture; ending the run here would lose the report those artefacts are summarised in. What
    the reset then finds is recorded by :func:`restored`, which reads the live systems back.
    """
    try:
        return str(bench.world.worker.quiesce())
    except Exception as failure:
        return f"{type(failure).__name__}: {failure}"


def _report_name(directory: RunDirectory) -> str:
    """One report per invocation, and never a second one over the first.

    A resume is a new invocation of the rehearsal against a run that already has artefacts. Its
    report is a new document beside the first rather than an edit of it, for the reason every
    capture in this layout is written once: the first invocation's account of what it found is
    not the second's to revise.
    """
    first = directory.path / "rehearsal.json"
    if not first.exists():
        return first.name
    return f"rehearsal.{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}.json"


def main(argv: Sequence[str] | None = None) -> int:
    """``uv run python -m scripts.rehearsal.run --run-id dr01-<something>``."""
    parser = argparse.ArgumentParser(
        prog="dress-rehearsal", description="Drive the SUR-1 execution pipeline at DR01."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--kind", default=KIND, choices=[KIND])
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument("--readiness-only", action="store_true")
    arguments = parser.parse_args(argv)

    config = stack()
    if arguments.readiness_only:
        bench = build(config)
        print(json.dumps(readiness(bench), indent=2, sort_keys=True))
        return 0
    report = rehearse(
        run_id=arguments.run_id,
        config=config,
        command=["dress-rehearsal", *(argv or sys.argv[1:])],
        reset_at_exit=not arguments.no_reset,
    )
    print(json.dumps({key: report[key] for key in ("run_id", "result")}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - a command line, exercised through main()
    raise SystemExit(main())


__all__ = ["KIND", "Bench", "RehearsalRefusedError", "RehearsalWorld", "build", "main", "rehearse"]
