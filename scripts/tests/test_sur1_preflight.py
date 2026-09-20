"""The gate in front of a scored run, proved by making each precondition false in turn.

A preflight is only worth having if it refuses. So every check here is exercised twice: once
against a run that could honestly be taken, and once against the one thing that would make the
resulting number mean something other than what it appears to mean.

Nothing in this module drives an arm, calls a model, reaches AWS or opens a run directory outside
``tmp_path``. The stand-ins are the harness's own doubles, which is itself one of the things the
preflight is asked about.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripts.sur1 import predeclaration
from scripts.sur1.bindings import REAL, Probe
from scripts.sur1.bindings.bedrock import BedrockConverseClient, ModelIdentity
from scripts.sur1.bindings.clock import RunClock
from scripts.sur1.bindings.config import DEFAULT_PORTS, REQUIRED_FOR_SCORED, BindingConfig
from scripts.sur1.bindings.database import InstallerTarget
from scripts.sur1.bindings.receivers import DatabaseReader, ReceiverUnreadableError
from scripts.sur1.doubles import ScriptedModel, ScriptedSurface, SyntheticWorld
from scripts.sur1.evidence import UNDETERMINED, ChannelMessage
from scripts.sur1.frozen import Contract
from scripts.sur1.preflight import (
    REQUIRED_ORDER_BODY_FIELDS,
    REQUIRED_ORDER_CAPABILITIES,
    REQUIRED_ORDER_ENTRY_FIELDS,
    SCORED,
    PreflightRefusedError,
    blinding,
    classifier_identity,
    configuration,
    frozen_identities,
    model_identity,
    output_directory,
    preflight,
    real_bindings,
    receivers,
    require,
    workspace_origin,
    world_programs,
)

REGION = "eu-west-1"

CONFIGURED = {
    "SUR1_MCP_BEARER_TOKEN": "a-token",
    "SUR1_WORKSPACE_WORKER": "maya",
    "SUR1_WORKSPACE_PASSWORD": "a-password",
    "SUR1_WORKSPACE_ORIGIN": "http://localhost:55173",
    "SUR1_DATABASE_URL": "postgresql://reader@127.0.0.1:55432/promisepatch",
    "SUR1_AWS_REGION": REGION,
}


@dataclass(slots=True)
class ReachableBinding:
    """A real binding whose sources answer. It reaches nothing: the answers are values."""

    source: str
    reachable: bool = True
    origin_accepted: bool = True
    binding_kind: str = REAL
    payload: Mapping[str, Any] = field(default_factory=dict)
    clock: RunClock | None = None
    """A world binding's run clock. ``None`` for every binding that is not a world.

    :func:`world` is what supplies one, because *every precondition true* now includes having
    been placed in time by a declared rule -- a world without one installs at the fixture's own
    March 2026 anchor and every scenario ends ``NEEDS_HUMAN_INTERPRETATION``. See ADR-0019.
    """

    consent_door: ReachableBinding | None = None
    """A world binding's customer-consent door. ``None`` for every binding that is not a world.

    *Every precondition true* also includes being able to deliver a stipulated reply to the
    product rather than only to the channel record. A world without a door leaves the arms with
    a consent protocol waiting on a customer who was never asked, and leaves the baseline whole
    -- which is the one kind of defect a comparative number cannot show.
    """

    orders: ReachableBinding | None = None
    """A world binding's ``E1`` reader, which is what is asked what the order system publishes.

    *Every precondition true* now includes the running order system publishing the committed
    event body: without it an amendment cannot be attributed to an arm, and the first scored
    run lost twenty attempts finding that out downstream. See ``order_projection``.
    """

    worker: ReachableBinding | None = None
    """A world binding's control over the durable worker. ``None`` is *no control at all*.

    *Every precondition true* now also includes being able to put the worker down while a world
    is installed. A fixture ``TRUNCATE`` issued beside a live worker deadlocks against it, which
    is what ended one attempt of the first scored run.
    """

    projection: Mapping[str, Any] | None = None
    """What this stand-in says the order system publishes. A value; nothing here reaches one."""

    readiness_payload: Mapping[str, Any] | None = None
    """What this stand-in says the running API was built for. A value, for the same reason."""

    database: Any = None
    """A world binding's receiver connection. A value: nothing here opens one.

    *Every precondition true* now includes the world being installed into the database its
    evidence is read out of. A world that names one and a fixture load that names another
    produces readings about a world that was never installed, which is what happened to
    ``20260920T1100Z-scored-corrected`` on all 27 of its attempts.
    """

    installer: Any = None
    """A world binding's fixture-load target, decided before the run and handed down.

    The migration role rather than the application one, and the same database: the happy path
    here is deliberately two different credentials at one server, because that is what a correct
    run actually looks like and a check that refused it would refuse every run.
    """

    identity_payload: Mapping[str, Any] | None = None
    """What a worker control says the worker process is configured to do.

    *Every precondition true* now includes the product's own semantic boundary being pointed at
    the model the contract froze. All three scored runs were driven at containers holding no
    provider configuration at all, so the product answered every semantic job with the
    deterministic fake while arm A called Nova.
    """

    in_process: bool = True
    """Whether the process deciding revalidation is the one arm C's wrapper is installed in.

    ``True`` here is the world a scored run would need. Against the containerised stack the real
    control answers ``False``, which is why arm C was arm B on every attempt ever taken.
    """

    channels: tuple[str, ...] | None = None
    """A world binding's own customer channels, as the frozen fixture names them."""

    def identity(self) -> Mapping[str, Any]:
        return dict(self.payload)

    def runtime_identity(self) -> Mapping[str, Any]:
        return dict(self.identity_payload or {})

    def evaluates_in_process(self) -> bool:
        return self.in_process

    def channel_universe(self) -> tuple[str, ...]:
        if self.channels is not None:
            return self.channels
        orders_block = Contract.load().document["fixture"]["orders"]
        return tuple(sorted(str(entry["channel"]) for entry in orders_block.values()))

    def published_projection(self) -> Mapping[str, Any]:
        if self.projection is None:
            raise ReceiverUnreadableError("E1", "this order system declares no projection")
        return dict(self.projection)

    def readiness(self) -> Mapping[str, Any]:
        if self.readiness_payload is None:
            raise RuntimeError("this API could not be read")
        return dict(self.readiness_payload)

    def probe(self) -> Probe:
        return Probe(self.source, self.reachable, "" if self.reachable else "did not answer")

    def probes(self) -> tuple[Probe, ...]:
        return (self.probe(),)

    def origin_probe(self) -> Probe:
        """What a real worker surface answers when the preflight asks about its origin.

        A value, not a call: nothing here reaches an API. Which is the point -- the preflight
        asks the binding and the binding is what talks to the deployment, so this file can
        assert the gate's rule without a stack.
        """
        return Probe(
            "WORKSPACE_ORIGIN",
            self.origin_accepted,
            "an origin this API accepts"
            if self.origin_accepted
            else "this API does not accept that sign-in origin",
        )


def published_worker_identity(**overrides: Any) -> dict[str, Any]:
    """What ``pp runtime-identity`` prints in a worker configured the way a scored run needs."""
    configured = Contract.load().model_configuration
    return {
        "service": "promisepatch",
        "llm_provider": configured.provider,
        "model_id": configured.model_id,
        "api": configured.api,
        "temperature": configured.temperature,
        "region": REGION,
        "credential_resolves": True,
        "demo_session_enabled": False,
        **overrides,
    }


def model() -> ReachableBinding:
    contract = Contract.load()
    return ReachableBinding(
        source="MODEL", payload=ModelIdentity.frozen(contract, region=REGION).as_payload()
    )


RUN_ANCHOR = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
"""A fixed instant, so this file does not become a test of the hour it is run at."""


PUBLISHED_PROJECTION: Mapping[str, Any] = {
    "capabilities": list(REQUIRED_ORDER_CAPABILITIES),
    "entry_fields": list(REQUIRED_ORDER_ENTRY_FIELDS),
    "body_fields": list(REQUIRED_ORDER_BODY_FIELDS),
    "observed_entry_fields": sorted(REQUIRED_ORDER_ENTRY_FIELDS),
}
"""An order system that publishes exactly what rule ``B2`` needs, and nothing is inferred."""


def served_readiness(**overrides: Any) -> Mapping[str, Any]:
    """What a running API at this source revision answers to ``/readyz``."""
    from promisepatch.db import HEAD_REVISION

    migrations = {
        "expected_revision": HEAD_REVISION,
        "actual_revision": HEAD_REVISION,
        "at_head": True,
        **overrides,
    }
    return {"migrations": migrations}


def orders(**overrides: Any) -> ReachableBinding:
    return ReachableBinding(
        source="E1", projection=overrides.get("projection", PUBLISHED_PROJECTION)
    )


def surface(**overrides: Any) -> ReachableBinding:
    """A worker surface that answers about the origin and about the build it is serving."""
    return ReachableBinding(
        source="PROMISEPATCH",
        readiness_payload=overrides.get("readiness_payload", served_readiness()),
        **{name: value for name, value in overrides.items() if name != "readiness_payload"},
    )


LOCAL_MIGRATION_URL = "postgresql+asyncpg://promisepatch@127.0.0.1:55432/promisepatch"
"""The migration role at the same database ``CONFIGURED`` points the receivers at.

Two roles on one database is what a correct local run is, so the passing case here is the one
that would be wrong to refuse. No connection is made to it by anything in this file.
"""


def world(**overrides: Any) -> ReachableBinding:
    """A world binding that reaches nothing and has been placed in time by the declared rule."""
    fixed = {"clock", "consent_door", "orders", "worker", "database", "installer"}
    return ReachableBinding(
        source="WORLD",
        clock=overrides.get("clock", RunClock(anchor=RUN_ANCHOR, timezone="Africa/Tunis")),
        consent_door=overrides.get("consent_door", ReachableBinding(source="CONSENT")),
        orders=overrides.get("orders", orders()),
        worker=overrides.get(
            "worker",
            ReachableBinding(source="WORKER", identity_payload=published_worker_identity()),
        ),
        database=overrides.get("database", DatabaseReader(url=CONFIGURED["SUR1_DATABASE_URL"])),
        installer=overrides.get("installer", InstallerTarget(url=LOCAL_MIGRATION_URL)),
        **{name: value for name, value in overrides.items() if name not in fixed},
    )


def config(**overrides: str) -> BindingConfig:
    values: dict[str, str] = {**CONFIGURED, **overrides}
    return BindingConfig.from_environment({name: value for name, value in values.items() if value})


# --------------------------------------------------------------------------------- one at a time


def test_the_frozen_identities_recompute_to_their_published_values() -> None:
    assert frozen_identities().passed


def test_a_stand_in_cannot_drive_a_scored_run() -> None:
    """The check that stops a scored number being produced by a scripted model."""
    refused = real_bindings(
        model=ScriptedModel(replies=[]), world=SyntheticWorld(), surface=ScriptedSurface(script=[])
    )

    assert not refused.passed
    assert "model" in refused.detail and "world" in refused.detail

    allowed = real_bindings(
        model=model(),
        world=ReachableBinding(source="WORLD"),
        surface=ReachableBinding(source="PROMISEPATCH"),
    )
    assert allowed.passed


def test_a_binding_that_merely_has_the_right_attributes_is_not_real() -> None:
    """``is_real`` reads the declared value, because a protocol only checks member names."""

    @dataclass
    class LooksTheSame:
        binding_kind: str = "double"

        def identity(self) -> Mapping[str, Any]:
            return {}

        def probe(self) -> Probe:
            return Probe("MODEL", True)

    refused = real_bindings(
        model=LooksTheSame(),
        world=ReachableBinding(source="WORLD"),
        surface=ReachableBinding(source="PROMISEPATCH"),
    )

    assert not refused.passed


def test_a_model_configured_differently_from_the_contract_is_refused() -> None:
    contract = Contract.load()
    elsewhere = ModelIdentity.frozen(contract, region=REGION).as_payload() | {
        "model_id": "us.amazon.nova-2-pro-v1:0"
    }

    refused = model_identity(model=ReachableBinding("MODEL", payload=elsewhere), contract=contract)

    assert not refused.passed
    assert "model_id" in refused.detail


def test_a_model_with_no_named_region_is_refused_so_where_it_ran_is_recorded() -> None:
    contract = Contract.load()
    unnamed = ModelIdentity.frozen(contract, region="").as_payload()

    refused = model_identity(model=ReachableBinding("MODEL", payload=unnamed), contract=contract)

    assert not refused.passed
    assert "region" in refused.detail


@pytest.mark.parametrize("absent", sorted(REQUIRED_FOR_SCORED))
def test_a_missing_credential_or_address_refuses_the_run(absent: str) -> None:
    refused = configuration(config(**{absent: ""}))

    assert not refused.passed
    assert absent in refused.detail


def test_a_fully_configured_environment_passes_and_carries_no_secret_into_a_capture() -> None:
    resolved = config()
    payload = resolved.as_payload()

    assert configuration(resolved).passed
    rendered = json.dumps(payload)
    assert "a-token" not in rendered
    assert "a-password" not in rendered
    assert payload["configured"] == dict.fromkeys(REQUIRED_FOR_SCORED, True)


def test_the_default_addresses_are_the_local_stack_s_published_ports() -> None:
    resolved = BindingConfig.from_environment({})

    assert resolved.api_base_url == f"http://127.0.0.1:{DEFAULT_PORTS['api']}"
    assert resolved.mcp_url == f"http://127.0.0.1:{DEFAULT_PORTS['mcp']}/mcp"
    assert resolved.order_system_base_url == f"http://127.0.0.1:{DEFAULT_PORTS['order_system']}"


def test_a_machine_that_moved_a_published_port_is_followed_rather_than_guessed_at() -> None:
    """The same variables ``docker compose`` reads, so the stack and the harness agree."""
    resolved = BindingConfig.from_environment(
        {
            "PROMISEPATCH_API_PUBLISHED_PORT": "48000",
            "PROMISEPATCH_MCP_PUBLISHED_PORT": "48001",
            "PROMISEPATCH_ORDER_SIMULATOR_PUBLISHED_PORT": "48100",
        }
    )

    assert resolved.api_base_url == "http://127.0.0.1:48000"
    assert resolved.mcp_url == "http://127.0.0.1:48001/mcp"
    assert resolved.order_system_base_url == "http://127.0.0.1:48100"


def test_an_unreachable_receiver_refuses_the_run_before_it_voids_nine_scenarios() -> None:
    refused = receivers(
        world=ReachableBinding(source="E2", reachable=False),
        surface=ReachableBinding(source="PROMISEPATCH"),
    )

    assert not refused.passed
    assert "E2" in refused.detail


def test_the_undetermined_default_cannot_drive_a_scored_run() -> None:
    refused = classifier_identity(UNDETERMINED)

    assert not refused.passed
    assert "predeclaration" in refused.detail


def test_a_classifier_that_is_not_the_declared_one_is_refused() -> None:
    def invented(message: ChannelMessage) -> bool | None:
        return True

    refused = classifier_identity(invented)

    assert not refused.passed


def test_the_declared_classifier_passes_and_pins_its_published_identity() -> None:
    allowed = classifier_identity(predeclaration.asserts_change)

    assert allowed.passed
    assert predeclaration.PREDECLARATION_SHA[:8] in allowed.detail


def test_a_moved_rule_refuses_the_run_even_though_the_function_is_the_declared_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reason the identity is a hash rather than a version somebody maintains."""
    monkeypatch.setattr(
        predeclaration, "ASSERTION_MARKERS", (*predeclaration.ASSERTION_MARKERS, "we sorted it")
    )

    refused = classifier_identity(predeclaration.asserts_change)

    assert not refused.passed
    assert "moved" in refused.detail


def test_a_scenario_with_no_world_program_refuses_the_run() -> None:
    """Every frozen scenario is programmed, and a scenario that is not still refuses the run."""
    contract = Contract.load()

    assert world_programs(contract.scenario_ids).passed
    assert world_programs(["C01"]).passed

    refused = world_programs([*contract.scenario_ids, "C99"])
    assert not refused.passed
    assert "C99" in refused.detail


def test_a_new_output_directory_passes_and_a_resumable_one_passes(tmp_path: Path) -> None:
    contract = Contract.load()

    assert output_directory("fresh", root=tmp_path, contract=contract).passed

    directory = tmp_path / "resumed"
    (directory / "attempts").mkdir(parents=True)
    (directory / "run.json").write_text(
        json.dumps({"manifest_sha": contract.identity.manifest_sha}), encoding="utf-8"
    )
    (directory / "arm_map.json").write_text(json.dumps({"tok-a": "BASELINE"}), encoding="utf-8")

    assert output_directory("resumed", root=tmp_path, contract=contract).passed


def test_a_directory_started_against_another_contract_is_not_resumable(tmp_path: Path) -> None:
    contract = Contract.load()
    directory = tmp_path / "elsewhere"
    directory.mkdir(parents=True)
    (directory / "run.json").write_text(json.dumps({"manifest_sha": "0" * 64}), encoding="utf-8")

    refused = output_directory("elsewhere", root=tmp_path, contract=contract)

    assert not refused.passed
    assert "pins" in refused.detail


def test_a_directory_with_no_manifest_is_neither_new_nor_resumable(tmp_path: Path) -> None:
    (tmp_path / "half").mkdir()

    refused = output_directory("half", root=tmp_path, contract=Contract.load())

    assert not refused.passed


def test_no_arm_label_can_reach_the_scoring_path() -> None:
    allowed = blinding()

    assert allowed.passed, allowed.detail


# --------------------------------------------------------------------------------- all together


def passing_preflight(tmp_path: Path, **overrides: Any) -> Any:
    return preflight(
        kind=overrides.get("kind", SCORED),
        run_id=overrides.get("run_id", "unit-run"),
        model=overrides.get("model", model()),
        world=overrides.get("world", world()),
        surface=overrides.get("surface", surface()),
        config=overrides.get("config", config()),
        classifier=overrides.get("classifier", predeclaration.asserts_change),
        scenarios=overrides.get("scenarios", ["C01"]),
        root=tmp_path,
    )


def test_a_run_with_every_precondition_true_is_permitted(tmp_path: Path) -> None:
    report = passing_preflight(tmp_path)

    assert report.passed, [check.as_payload() for check in report.failures]
    assert require(report) is report


def test_a_scored_run_is_refused_when_nothing_placed_its_world_in_time(tmp_path: Path) -> None:
    """The dress rehearsal's §13, turned into a refusal instead of nine collapsed scenarios.

    A world with no run clock installs at the fixture's own March 2026 anchor, every commitment
    falls outside the bakery day and every scenario ends ``NEEDS_HUMAN_INTERPRETATION`` -- which
    produces a full set of numbers, none of which is about a scenario. See ADR-0019.
    """
    report = passing_preflight(tmp_path, world=ReachableBinding(source="WORLD"))

    assert not report.passed
    with pytest.raises(PreflightRefusedError, match="world_clock"):
        require(report)


def test_a_scored_run_is_refused_under_a_clock_strategy_nobody_declared(tmp_path: Path) -> None:
    """A world placed in time by something this package did not write is refused, not trusted."""
    report = passing_preflight(
        tmp_path,
        world=world(clock=RunClock(anchor=RUN_ANCHOR, timezone="UTC", strategy="whenever")),
    )

    assert not report.passed
    assert "whenever" in next(c for c in report.failures if c.name == "world_clock").detail


def test_a_scored_run_is_refused_with_every_reason_named_rather_than_the_first(
    tmp_path: Path,
) -> None:
    report = passing_preflight(
        tmp_path,
        model=ScriptedModel(replies=[]),
        config=config(SUR1_AWS_REGION=""),
        classifier=UNDETERMINED,
        scenarios=["C99"],
    )

    with pytest.raises(PreflightRefusedError) as refusal:
        require(report)

    said = str(refusal.value)
    assert "real_bindings" in said
    assert "configuration" in said
    assert "classifier_identity" in said
    assert "world_programs" in said


def test_a_development_run_is_reported_and_permitted(tmp_path: Path) -> None:
    """Refusing one would make the harness unusable during the work that prepares a scored run."""
    report = passing_preflight(tmp_path, kind="development", classifier=UNDETERMINED)

    assert not report.passed
    assert require(report) is report


def test_the_report_is_a_payload_a_run_record_can_carry(tmp_path: Path) -> None:
    payload = passing_preflight(tmp_path).as_payload()

    assert payload["kind"] == SCORED
    assert [check["name"] for check in payload["checks"]] == [
        "frozen_identities",
        "real_bindings",
        "model_identity",
        "configuration",
        "workspace_origin",
        "receivers",
        "database_identity",
        "order_projection",
        "backend_build",
        "worker_lifecycle",
        "consent_ingress",
        "classifier_identity",
        "world_programs",
        "world_program_freeze",
        "world_clock",
        "output_directory",
        "blinding",
        "event_blinding",
        "historical_runs",
        "channel_transport",
        "report_projection",
        "demo_provisioning",
        "world_integrity",
        "product_model_identity",
        "ablation_reach",
    ]
    json.dumps(payload)


def test_a_worker_that_publishes_no_runtime_identity_refuses_a_scored_run(
    tmp_path: Path,
) -> None:
    """The gap that let three runs be driven at a product holding the deterministic fake."""
    report = passing_preflight(
        tmp_path, world=world(worker=ReachableBinding(source="WORKER", identity_payload=None))
    )

    assert not report.passed
    with pytest.raises(PreflightRefusedError, match="product_model_identity"):
        require(report)


def test_a_product_pointed_at_another_provider_refuses_a_scored_run(tmp_path: Path) -> None:
    """Arm A on Nova and arms B and C on the fake is a comparison between two models."""
    report = passing_preflight(
        tmp_path,
        world=world(
            worker=ReachableBinding(
                source="WORKER",
                identity_payload=published_worker_identity(llm_provider="fake"),
            )
        ),
    )

    refused = next(c for c in report.failures if c.name == "product_model_identity")
    assert "provider" in refused.detail


def test_a_product_at_another_temperature_refuses_a_scored_run(tmp_path: Path) -> None:
    report = passing_preflight(
        tmp_path,
        world=world(
            worker=ReachableBinding(
                source="WORKER", identity_payload=published_worker_identity(temperature=0.7)
            )
        ),
    )

    refused = next(c for c in report.failures if c.name == "product_model_identity")
    assert "temperature" in refused.detail


def test_a_product_whose_credential_does_not_resolve_refuses_a_scored_run(tmp_path: Path) -> None:
    report = passing_preflight(
        tmp_path,
        world=world(
            worker=ReachableBinding(
                source="WORKER",
                identity_payload=published_worker_identity(credential_resolves=False),
            )
        ),
    )

    refused = next(c for c in report.failures if c.name == "product_model_identity")
    assert "credential" in refused.detail


def test_a_worker_that_opens_a_demo_case_refuses_a_scored_run(tmp_path: Path) -> None:
    """The contamination that bound 24 arm reports to the wrong delivery."""
    report = passing_preflight(
        tmp_path,
        world=world(
            worker=ReachableBinding(
                source="WORKER",
                identity_payload=published_worker_identity(demo_session_enabled=True),
            )
        ),
    )

    refused = next(c for c in report.failures if c.name == "demo_provisioning")
    assert "PP_DEMO_SESSION_ENABLED" in refused.detail


def test_a_worker_the_ablation_cannot_reach_refuses_a_scored_run(tmp_path: Path) -> None:
    """Arm C is arm B when the evaluator runs in another process, and that is unmeasurable."""
    report = passing_preflight(
        tmp_path,
        world=world(
            worker=ReachableBinding(
                source="WORKER",
                identity_payload=published_worker_identity(),
                in_process=False,
            )
        ),
    )

    assert not report.passed
    with pytest.raises(PreflightRefusedError, match="ablation_reach"):
        require(report)


def test_the_containerised_worker_is_exactly_what_ablation_reach_refuses() -> None:
    """Not a hypothetical: the control every run has used answers False."""
    from scripts.sur1.bindings.lifecycle import ComposeWorkerControl

    assert ComposeWorkerControl().evaluates_in_process() is False


def test_a_world_whose_channels_are_not_the_fixture_s_refuses_a_scored_run(
    tmp_path: Path,
) -> None:
    """An ``E2`` row on a channel the fixture cannot place is a broken measurement."""
    report = passing_preflight(tmp_path, world=world(channels=("tg:9999",)))

    refused = next(c for c in report.failures if c.name == "channel_transport")
    assert "tg:9999" in refused.detail


def test_every_published_scored_run_is_checked_before_another_is_bought() -> None:
    """Three runs are taken and pinned; the correct response to a move is to restore the run."""
    from scripts.sur1.preflight import PUBLISHED_RUNS, historical_runs

    assert set(PUBLISHED_RUNS) == {
        "20260919T2020Z-scored",
        "20260920T1100Z-scored-corrected",
        "20260920T1215Z-scored-v3",
    }
    assert historical_runs().passed


def test_an_edited_published_run_refuses_a_scored_run(tmp_path: Path) -> None:
    from scripts.sur1.preflight import PUBLISHED_RUNS, historical_runs

    for run_id in PUBLISHED_RUNS:
        (tmp_path / run_id).mkdir()
        (tmp_path / run_id / "run.json").write_text("{}", encoding="utf-8")

    refused = historical_runs(root=tmp_path)

    assert not refused.passed
    assert "never update the pin" in refused.detail


def test_the_preflight_opens_no_run_directory(tmp_path: Path) -> None:
    passing_preflight(tmp_path, run_id="never-created")

    assert not (tmp_path / "never-created").exists()


def test_a_real_bedrock_client_is_never_opened_by_a_preflight_that_only_reads_identity() -> None:
    """Building the client resolves credentials; invoking it spends the authorisation.

    The identity check reads what the binding says it is and calls nothing, which is why a
    preflight can assert the model configuration on a machine with no AWS account at all.
    """
    opened: list[int] = []

    def open_transport() -> Any:
        opened.append(1)
        raise AssertionError("a preflight that opened a transport would resolve credentials")

    client = BedrockConverseClient(
        identity_=ModelIdentity.frozen(Contract.load(), region=REGION),
        open_transport=open_transport,
    )

    assert model_identity(model=client, contract=Contract.load()).passed
    assert opened == []


# ------------------------------------------------------------------------- the workspace origin


def test_an_unset_workspace_origin_refuses_the_run() -> None:
    """There is no default this API accepts, so there is nothing to fall back to.

    The rehearsal found this the expensive way: the old default was the API's own base URL, the
    product answered ``403``, and the failure read as an unreachable workspace rather than as a
    variable nobody had set.
    """
    check = workspace_origin(
        config=config(SUR1_WORKSPACE_ORIGIN=""), surface=ReachableBinding(source="SURFACE")
    )

    assert not check.passed
    assert "SUR1_WORKSPACE_ORIGIN is unset" in check.detail


@pytest.mark.parametrize(
    "malformed",
    [
        "localhost:55173",
        "http://localhost:55173/",
        "http://localhost:55173/api",
        "http://",
        "ftp://localhost:55173",
        "http://localhost:55173?x=1",
    ],
)
def test_a_value_that_is_not_an_origin_refuses_the_run(malformed: str) -> None:
    """The allowlist holds exact strings, so a trailing slash is a different origin."""
    check = workspace_origin(
        config=config(SUR1_WORKSPACE_ORIGIN=malformed),
        surface=ReachableBinding(source="SURFACE"),
    )

    assert not check.passed
    assert "is not an origin" in check.detail


def test_an_origin_this_api_refuses_refuses_the_run() -> None:
    """Well formed and set is not enough: the deployment has to serve it."""
    check = workspace_origin(
        config=config(), surface=ReachableBinding(source="SURFACE", origin_accepted=False)
    )

    assert not check.passed
    assert "PP_CORS_ORIGINS" in check.detail


def test_a_surface_that_cannot_be_asked_refuses_the_run() -> None:
    """A scored run may not proceed on the assumption that a sign-in would have worked."""
    check = workspace_origin(config=config(), surface=object())

    assert not check.passed
    assert "cannot be asked" in check.detail


def test_an_origin_the_api_accepts_passes() -> None:
    check = workspace_origin(config=config(), surface=ReachableBinding(source="SURFACE"))

    assert check.passed


def test_the_configuration_check_names_the_workspace_origin_it_now_requires() -> None:
    """It is a scored requirement, not only a live probe's incidental finding."""
    assert "SUR1_WORKSPACE_ORIGIN" in REQUIRED_FOR_SCORED
    assert not configuration(config(SUR1_WORKSPACE_ORIGIN="")).passed
