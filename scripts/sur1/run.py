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

**Nothing here has taken a run.** No arm has been driven against a ``SUR-1`` scenario, no model
reached, no AWS resource read, and ``AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE`` is unspent.
Running this module today refuses at the preflight, because the nine world programs are not
written and the scenarios cannot be prepared.
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
from scripts.sur1.bindings.bedrock import BedrockConverseClient
from scripts.sur1.bindings.config import BindingConfig
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
from scripts.sur1.preflight import SCORED, PreflightReport, preflight, require

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


def build(config: BindingConfig, contract: Contract) -> Bindings:
    """Assemble every binding from one configuration. Opens no client and reaches nothing.

    The model's transport, the MCP session and both database connections are opened on first
    use, so building this object on a machine with no stack and no AWS account succeeds and the
    preflight is what says whether a run could be taken.
    """
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
    world = LiveScenarioWorld(
        orders=OrderSystemReceiver(
            base_url=config.order_system_base_url, store_path=config.order_system_store
        ),
        channel=ChannelReceiver(database=database, ledger=ledger),
        kitchen=KitchenReceiver(database=database),
        database=database,
        ledger=ledger,
        fixture=contract.document["fixture"]["orders"],
        worker_surface=surface,
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
    """Preflight, then drive. A scored run that failed any check never reaches the driver."""
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
    directory = drive(
        arms=bindings.arms,
        world=bindings.world,
        clock=clock,
        run_id=run_id,
        kind=kind,
        command=command,
        classifier=_classifier(kind),
        scenarios=scenarios,
        root=root,
    )
    return report, directory


def main(argv: Sequence[str] | None = None) -> int:
    """The command line. ``--preflight`` is the only thing that is safe to run today.

    Driving anything refuses, because no scenario has a world program. That refusal is the
    harness working: an arm driven at a world nobody prepared would produce a number that looks
    exactly like a number about the scenario.
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
