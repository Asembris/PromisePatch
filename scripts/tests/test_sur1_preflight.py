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
from scripts.sur1.doubles import ScriptedModel, ScriptedSurface, SyntheticWorld
from scripts.sur1.evidence import UNDETERMINED, ChannelMessage
from scripts.sur1.frozen import Contract
from scripts.sur1.preflight import (
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
    world_programs,
)

REGION = "eu-west-1"

CONFIGURED = {
    "SUR1_MCP_BEARER_TOKEN": "a-token",
    "SUR1_WORKSPACE_WORKER": "maya",
    "SUR1_WORKSPACE_PASSWORD": "a-password",
    "SUR1_DATABASE_URL": "postgresql://reader@127.0.0.1:55432/promisepatch",
    "SUR1_ORDER_SYSTEM_STORE": "/tmp/orders.sqlite3",
    "SUR1_AWS_REGION": REGION,
}


@dataclass(slots=True)
class ReachableBinding:
    """A real binding whose sources answer. It reaches nothing: the answers are values."""

    source: str
    reachable: bool = True
    binding_kind: str = REAL
    payload: Mapping[str, Any] = field(default_factory=dict)
    clock: RunClock | None = None
    """A world binding's run clock. ``None`` for every binding that is not a world.

    :func:`world` is what supplies one, because *every precondition true* now includes having
    been placed in time by a declared rule -- a world without one installs at the fixture's own
    March 2026 anchor and every scenario ends ``NEEDS_HUMAN_INTERPRETATION``. See ADR-0019.
    """

    def identity(self) -> Mapping[str, Any]:
        return dict(self.payload)

    def probe(self) -> Probe:
        return Probe(self.source, self.reachable, "" if self.reachable else "did not answer")

    def probes(self) -> tuple[Probe, ...]:
        return (self.probe(),)


def model() -> ReachableBinding:
    contract = Contract.load()
    return ReachableBinding(
        source="MODEL", payload=ModelIdentity.frozen(contract, region=REGION).as_payload()
    )


RUN_ANCHOR = datetime(2026, 9, 19, 13, 0, tzinfo=UTC)
"""A fixed instant, so this file does not become a test of the hour it is run at."""


def world(**overrides: Any) -> ReachableBinding:
    """A world binding that reaches nothing and has been placed in time by the declared rule."""
    return ReachableBinding(
        source="WORLD",
        clock=overrides.get("clock", RunClock(anchor=RUN_ANCHOR, timezone="Africa/Tunis")),
        **{name: value for name, value in overrides.items() if name != "clock"},
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
        surface=overrides.get("surface", ReachableBinding(source="PROMISEPATCH")),
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
        "receivers",
        "classifier_identity",
        "world_programs",
        "world_program_freeze",
        "world_clock",
        "output_directory",
        "blinding",
        "event_blinding",
    ]
    json.dumps(payload)


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
