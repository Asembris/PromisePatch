"""The one place a ``SUR-1`` run is composed, so the preflight cannot be the optional step.

Everything else in this package is a part: a model client, a world, a worker surface, three
adapters, a driver, a gate. This module is where they are put together, and it exists because a
preflight a caller has to remember to run is a document rather than a control.

:func:`execute` builds the three bindings from configuration, asks
:func:`~scripts.sur1.preflight.preflight` every question, and **refuses a scored run that failed
any of them** before :func:`~scripts.sur1.driver.drive` is called -- before an arm is constructed,
before a world is prepared and before a model is reached. A development run is reported and
proceeds, because refusing one would make the harness unusable during the work that prepares a
scored run.

**One surface object, two arms.** Arm C composes arm B's own :class:`PromisePatchArm`, so there is
exactly one implementation of *drive PromisePatch* and the ablation cannot drift into being a
second one. :func:`~scripts.sur1.adapters.three_arms` is what builds them, and it is not given a
second surface to build a second one out of.

**This module has taken two runs.** ``20260919T2020Z-scored`` was driven on 2026-09-19,
``AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE`` was spent on it, and it is published
inconclusive and unaltered. ``20260920T1100Z-scored-corrected`` was driven on 2026-09-20, failed
in preparation on all 27 attempts, reached no model and spent nothing. Nothing here supersedes
either: a later run is a corrected execution beside both. What stands between this module and
one is a fresh authorisation and every one of
:data:`~scripts.sur1.preflight.REQUIRED_CHECKS` -- now eighteen -- passing in one report. See
``docs/sur1-first-scored-run-defect.md`` and ``docs/benchmarks/sur1-execution-revision.v3.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from scripts.sur1 import predeclaration
from scripts.sur1.adapters import three_arms
from scripts.sur1.arms import ArmAdapter
from scripts.sur1.authorisation import observe
from scripts.sur1.bindings.bedrock import BedrockConverseClient
from scripts.sur1.bindings.clock import RunClock, run_clock
from scripts.sur1.bindings.config import BindingConfig
from scripts.sur1.bindings.consentdoor import SignedLinkDoor
from scripts.sur1.bindings.database import installer_target
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
from scripts.sur1.capture import RUNS_ROOT, RunDirectory
from scripts.sur1.driver import Clock, drive
from scripts.sur1.evidence import UNDETERMINED, OutboundClassifier
from scripts.sur1.frozen import Contract
from scripts.sur1.preflight import SCORED, PreflightReport, authorise, preflight, require

DEVELOPMENT: Final = "development"


@dataclass(frozen=True, slots=True)
class Bindings:
    """The three real bindings and the three arms built out of exactly two of them."""

    model: BedrockConverseClient
    world: LiveScenarioWorld
    surface: LiveWorkerSurface
    arms: tuple[ArmAdapter, ...]

    def identity(self) -> dict[str, Any]:
        return {
            "model": dict(self.model.identity()),
            "world": dict(self.world.identity()),
            "surface": dict(self.surface.identity()),
            "arms": [arm.label for arm in self.arms],
        }


def build(config: BindingConfig, contract: Contract, *, clock: RunClock | None = None) -> Bindings:
    """Assemble every binding from one configuration. Opens no client and reaches nothing.

    The model's transport, the MCP session and both database connections are opened on first
    use, so building this object on a machine with no stack and no AWS account succeeds and the
    preflight is what says whether a run could be taken.

    **This is where the run is placed in time**, and it is the only place. The anchor is chosen
    once here -- before the preflight, before an arm is constructed and before a world is
    prepared -- and carried on the world, so every scenario and every attempt of this run
    installs from one instant and an attempt and its retry are attempts at one world. Nothing
    downstream may choose a second one: there is no parameter on an arm, an adapter or the
    driver by which it could. A caller passing ``clock`` is a test pinning the instant; a run
    takes :func:`~scripts.sur1.bindings.clock.run_clock`, which refuses an hour at which the
    scenarios would not be legible rather than moving them to fit. See ADR-0019.
    """
    clock = clock if clock is not None else run_clock()
    database = DatabaseReader(url=config.database_url)
    # Resolved here, once, and handed to the world rather than looked up inside the write. The
    # fixture load and the receivers are two connection strings that have to name one database,
    # and `database_identity` is what refuses a run where they do not. A resolution that failed
    # is carried on the target and reported by that check; nothing here raises.
    installer = installer_target()
    ledger = ChannelLedger()
    surface = live_worker_surface(
        mcp_url=config.mcp_url,
        bearer_token=config.mcp_bearer_token,
        api_base_url=config.api_base_url,
        origin=config.workspace_origin,
        username=config.workspace_worker,
        password=config.workspace_password,
    )
    world = LiveScenarioWorld(
        orders=OrderSystemReceiver(base_url=config.order_system_base_url),
        channel=ChannelReceiver(database=database, ledger=ledger),
        kitchen=KitchenReceiver(database=database),
        database=database,
        installer=installer,
        ledger=ledger,
        fixture=contract.document["fixture"]["orders"],
        worker_surface=surface,
        consent_door=SignedLinkDoor(api_base_url=config.api_base_url, database=database),
        clock=clock,
        worker=ComposeWorkerControl(),
    )
    model = BedrockConverseClient.from_contract(contract, region=config.aws_region)
    return Bindings(
        model=model,
        world=world,
        surface=surface,
        arms=three_arms(model=model, surface=surface),
    )


def check(
    *,
    kind: str,
    run_id: str,
    bindings: Bindings,
    config: BindingConfig,
    scenarios: Sequence[str] = (),
    root: Path = RUNS_ROOT,
) -> PreflightReport:
    """Ask every precondition. Reads only, and creates no run directory."""
    return preflight(
        kind=kind,
        run_id=run_id,
        model=bindings.model,
        world=bindings.world,
        surface=bindings.surface,
        config=config,
        classifier=_classifier(kind),
        scenarios=scenarios,
        root=root,
    )


def _classifier(kind: str) -> OutboundClassifier:
    """The declared rule for a scored run, and the undetermined default for a development one.

    A development run that borrowed the declared rule would be producing readings under it
    before it had been declared against a run, which is the ordering the contract cares about.
    The undetermined default voids those scenarios, which is the honest reading.
    """
    return predeclaration.asserts_change if kind == SCORED else UNDETERMINED


def execute(
    *,
    kind: str,
    run_id: str,
    config: BindingConfig,
    clock: Clock,
    command: Sequence[str],
    scenarios: Sequence[str] = (),
    root: Path = RUNS_ROOT,
    preflight_only: bool = False,
) -> tuple[PreflightReport, RunDirectory | None]:
    """Preflight, then drive. A scored run that failed any check never reaches the driver.

    The passing report is turned into the capability the driver asks for, here and nowhere else.
    That is what makes this function's first sentence structural rather than a description of
    the order the lines happen to be written in: a caller who skipped it has no capability, and
    a scored run without one is refused by the driver and by the capture layer.
    """
    contract = Contract.load()
    bindings = build(config, contract)
    report = require(
        check(
            kind=kind,
            run_id=run_id,
            bindings=bindings,
            config=config,
            scenarios=scenarios,
            root=root,
        )
    )
    if preflight_only:
        return report, None
    classifier = _classifier(kind)
    authorisation = (
        authorise(
            report,
            observe(
                kind=kind,
                run_id=run_id,
                root=root,
                scenarios=tuple(scenarios) or contract.scenario_ids,
                world=bindings.world,
                arms=bindings.arms,
                classifier=classifier,
            ),
        )
        if kind == SCORED
        else None
    )
    directory = drive(
        arms=bindings.arms,
        world=bindings.world,
        clock=clock,
        run_id=run_id,
        kind=kind,
        command=command,
        classifier=classifier,
        scenarios=scenarios,
        root=root,
        authorisation=authorisation,
    )
    return report, directory


def main(argv: Sequence[str] | None = None) -> int:
    """The command line. ``--preflight`` asks every question and drives nothing.

    A scored run refuses at the preflight until every required check passes against real
    bindings. That refusal is the harness working: a number produced around a failed check
    would look exactly like a number about the scenario.
    """
    import time

    parser = argparse.ArgumentParser(prog="sur1", description="Drive the SUR-1 comparative run.")
    parser.add_argument("--kind", choices=[DEVELOPMENT, SCORED], default=DEVELOPMENT)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="ask every precondition and drive nothing",
    )
    arguments = parser.parse_args(argv)

    config = BindingConfig.from_environment()
    report, _ = execute(
        kind=arguments.kind,
        run_id=arguments.run_id,
        config=config,
        clock=Clock(monotonic=time.monotonic),
        command=["sur1", *(argv or sys.argv[1:])],
        scenarios=arguments.scenario,
        preflight_only=arguments.preflight,
    )
    print(json.dumps(report.as_payload(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover - a command line, exercised through main()
    raise SystemExit(main())


__all__ = ["DEVELOPMENT", "Bindings", "build", "check", "execute", "main"]
