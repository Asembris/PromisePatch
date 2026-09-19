"""Composition: the preflight is in front of the driver, not beside it.

The point of these tests is the ordering. A scored run that failed a precondition must never
reach :func:`~scripts.sur1.driver.drive`, because by the time the driver has been called an arm
has been constructed, a world has been prepared and the next thing that happens costs money.

Nothing here opens a client, reaches a service or drives a scenario. ``build`` is asserted to
open nothing precisely so that this is checkable on a machine with no stack and no AWS account,
which is every machine this harness has been proved on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.sur1 import predeclaration
from scripts.sur1.bindings import is_real
from scripts.sur1.bindings.config import BindingConfig
from scripts.sur1.capture import CaptureError, write_once
from scripts.sur1.doubles import FakeClock
from scripts.sur1.driver import Clock
from scripts.sur1.evidence import UNDETERMINED
from scripts.sur1.frozen import ARMS, Contract
from scripts.sur1.preflight import SCORED, PreflightRefusedError
from scripts.sur1.run import DEVELOPMENT, build, check, execute, main

ENVIRONMENT = {
    # Loopback ports nothing listens on, so the receiver probes answer the same way whether or
    # not this machine happens to have the local stack up. A test whose result depended on that
    # would be a test about a developer's docker, and the composition is what is under test.
    "SUR1_API_BASE_URL": "http://127.0.0.1:1",
    "SUR1_MCP_URL": "http://127.0.0.1:1/mcp",
    "SUR1_ORDER_SYSTEM_BASE_URL": "http://127.0.0.1:1",
    "SUR1_DATABASE_URL": "postgresql://reader@127.0.0.1:1/promisepatch",
    "SUR1_MCP_BEARER_TOKEN": "a-token",
    "SUR1_WORKSPACE_WORKER": "maya",
    "SUR1_WORKSPACE_PASSWORD": "a-password",
    "SUR1_WORKSPACE_ORIGIN": "http://localhost:55173",
    "SUR1_AWS_REGION": "eu-west-1",
}


def config(**overrides: str) -> BindingConfig:
    values = {**ENVIRONMENT, **overrides}
    return BindingConfig.from_environment({k: v for k, v in values.items() if v})


def test_building_the_bindings_opens_nothing_and_reaches_nobody() -> None:
    """The reason a preflight can be honest on a machine with no stack and no account."""
    bindings = build(config(), Contract.load())

    assert is_real(bindings.model)
    assert is_real(bindings.world)
    assert is_real(bindings.surface)


def test_the_three_arms_are_built_from_two_bindings_and_share_one_surface() -> None:
    bindings = build(config(), Contract.load())
    baseline, promisepatch, ablation = bindings.arms

    assert [arm.label for arm in bindings.arms] == list(ARMS)
    assert ablation.inner is promisepatch  # type: ignore[attr-defined]
    assert promisepatch.surface is bindings.surface
    assert baseline.model is bindings.model  # type: ignore[attr-defined]


def test_the_identity_a_run_records_names_addresses_and_no_credential() -> None:
    rendered = json.dumps(build(config(), Contract.load()).identity())

    assert "a-token" not in rendered
    assert "a-password" not in rendered
    assert "127.0.0.1" in rendered


def test_a_scored_run_uses_the_declared_rule_and_a_development_run_does_not() -> None:
    """A development run that borrowed the declared rule would read under it before it applied."""
    from scripts.sur1.run import _classifier

    assert _classifier(SCORED) is predeclaration.asserts_change
    assert _classifier(DEVELOPMENT) is UNDETERMINED


def test_a_scored_run_never_reaches_the_driver_when_a_precondition_is_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering this module exists for, asserted by making the driver an alarm."""
    import scripts.sur1.run as run_module

    def never(**_kwargs: object) -> None:
        raise AssertionError("a refused scored run reached the driver")

    monkeypatch.setattr(run_module, "drive", never)

    with pytest.raises(PreflightRefusedError):
        execute(
            kind=SCORED,
            run_id="refused",
            config=config(),
            clock=Clock(monotonic=FakeClock()),
            command=["sur1"],
            scenarios=["C01"],
            root=tmp_path,
        )


def test_a_scored_run_with_no_configured_credential_is_refused(tmp_path: Path) -> None:
    with pytest.raises(PreflightRefusedError) as refusal:
        execute(
            kind=SCORED,
            run_id="unconfigured",
            config=config(SUR1_MCP_BEARER_TOKEN="", SUR1_DATABASE_URL=""),
            clock=Clock(monotonic=FakeClock()),
            command=["sur1"],
            scenarios=["C01"],
            root=tmp_path,
        )

    said = str(refusal.value)
    assert "SUR1_MCP_BEARER_TOKEN" in said
    assert "SUR1_DATABASE_URL" in said


def test_a_refused_scored_run_writes_nothing_at_all(tmp_path: Path) -> None:
    with pytest.raises(PreflightRefusedError):
        execute(
            kind=SCORED,
            run_id="nothing-written",
            config=config(),
            clock=Clock(monotonic=FakeClock()),
            command=["sur1"],
            scenarios=["C01"],
            root=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []


def test_a_preflight_only_invocation_drives_nothing_and_opens_no_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.sur1.run as run_module

    monkeypatch.setattr(
        run_module, "drive", lambda **_kwargs: pytest.fail("preflight-only drove an arm")
    )

    report, directory = execute(
        kind=DEVELOPMENT,
        run_id="just-asking",
        config=config(),
        clock=Clock(monotonic=FakeClock()),
        command=["sur1"],
        scenarios=["C01"],
        root=tmp_path,
        preflight_only=True,
    )

    assert directory is None
    assert not (tmp_path / "just-asking").exists()
    assert [check.name for check in report.failures] == [
        "workspace_origin",
        "receivers",
        "classifier_identity",
    ], "a development run reports the undetermined rule rather than being refused for it"


def test_the_command_line_reports_the_preflight_and_refuses_a_scored_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("scripts.sur1.run.RUNS_ROOT", tmp_path)
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)

    code = main(["--run-id", "cli", "--preflight", "--scenario", "C01"])

    printed = json.loads(capsys.readouterr().out)
    assert code == 1, "a development preflight that cannot prepare a world reports so"
    assert printed["kind"] == DEVELOPMENT
    assert not printed["passed"]


def test_the_world_programs_are_the_remaining_blocker_and_the_preflight_names_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindings = build(config(), Contract.load())

    before = check(
        kind=SCORED,
        run_id="named",
        bindings=bindings,
        config=config(),
        scenarios=["C99"],
        root=tmp_path,
    )
    assert "world_programs" in [failed.name for failed in before.failures]

    after = check(
        kind=SCORED,
        run_id="named",
        bindings=bindings,
        config=config(),
        scenarios=["C01"],
        root=tmp_path,
    )
    assert "world_programs" not in [failed.name for failed in after.failures]


def test_write_once_still_refuses_to_edit_a_capture(tmp_path: Path) -> None:
    """The protection the whole capture layout rests on, asserted beside the new composition."""
    path = tmp_path / "attempts" / "tok-a-C01-a1.json"
    write_once(path, {"evidence": {}})

    with pytest.raises(CaptureError):
        write_once(path, {"evidence": {"repaired": True}})
