"""The ``pp`` operator CLI."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from promisepatch import cli
from promisepatch.cli import app, resolve_anchor
from promisepatch.config import Settings, get_settings
from promisepatch.domain import analysis, intake
from promisepatch.fixtures.reset import ResetOutcome

runner = CliRunner()

TUNIS = "Africa/Tunis"


@pytest.fixture
def reset_enabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A deployment that has opted into fixture resets and configured its demo logins."""
    monkeypatch.setenv("PP_ALLOW_FIXTURE_RESET", "true")
    monkeypatch.setenv("PP_DEMO_WORKER_PASSWORD", "cli-test-baker")
    monkeypatch.setenv("PP_DEMO_OWNER_PASSWORD", "cli-test-owner")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_api_is_a_subcommand_not_the_root_command() -> None:
    """``pp`` stays a command group, so later subcommands do not change its shape."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "api" in result.stdout


def test_bare_invocation_shows_help() -> None:
    assert runner.invoke(app, []).exit_code != 0


def test_api_serves_the_application_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_run(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr("uvicorn.run", fake_run)

    result = runner.invoke(app, ["api", "--host", "0.0.0.0", "--port", "9001", "--reload"])

    assert result.exit_code == 0, result.output
    assert calls == [
        (("promisepatch.main:app",), {"host": "0.0.0.0", "port": 9001, "reload": True})
    ]


# --------------------------------------------------------------------- reset-demo-state


def test_reset_demo_state_is_a_subcommand() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "reset-demo-state" in result.stdout


def test_a_reset_is_refused_unless_the_deployment_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off by default: a reset deletes every domain row PromisePatch owns."""
    monkeypatch.setenv("PP_ALLOW_FIXTURE_RESET", "false")
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["reset-demo-state"])
    finally:
        get_settings.cache_clear()

    assert result.exit_code == 1
    assert "PP_ALLOW_FIXTURE_RESET" in result.output


def test_a_reset_reports_what_it_loaded(
    reset_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    anchor = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
    outcome = ResetOutcome(
        fixture_name="hollow-oak",
        anchor=anchor,
        loaded_at=anchor,
        digest="d" * 64,
        audit_seq=7,
        domain_event_seq=9,
        row_counts={"resources": 18},
    )

    async def fake_reset(settings: Settings, resolved: datetime) -> ResetOutcome:
        assert resolved == anchor
        return outcome

    monkeypatch.setattr("promisepatch.cli._run_reset", fake_reset)
    result = runner.invoke(app, ["reset-demo-state", "--anchor", anchor.isoformat()])

    assert result.exit_code == 0, result.output
    assert "hollow-oak" in result.output
    assert outcome.digest in result.output
    assert "seq 9" in result.output


# --------------------------------------------------------------------- the anchor


def test_a_naive_anchor_is_read_in_the_bakery_s_timezone() -> None:
    """ "Seven in the morning" is a claim about the kitchen, not about the server."""
    settings = Settings(bakery_tz=TUNIS)
    resolved = resolve_anchor("2026-03-04T07:00", settings)
    assert resolved.tzinfo is UTC
    assert resolved == datetime(2026, 3, 4, 7, 0, tzinfo=ZoneInfo(TUNIS))


def test_an_aware_anchor_is_taken_as_given() -> None:
    settings = Settings(bakery_tz=TUNIS)
    assert resolve_anchor("2026-03-04T07:00+00:00", settings) == datetime(
        2026, 3, 4, 7, 0, tzinfo=UTC
    )


def test_an_omitted_anchor_is_now() -> None:
    before = datetime.now(UTC)
    resolved = resolve_anchor("", Settings(bakery_tz=TUNIS))
    assert before <= resolved <= datetime.now(UTC)


def test_an_unparseable_anchor_is_refused() -> None:
    with pytest.raises(ValueError, match="ISO-8601"):
        resolve_anchor("last tuesday", Settings(bakery_tz=TUNIS))


def test_an_unknown_bakery_timezone_is_refused() -> None:
    with pytest.raises(ValueError, match="PP_BAKERY_TZ"):
        resolve_anchor("2026-03-04T07:00", Settings(bakery_tz="Mars/Olympus_Mons"))


# ------------------------------------------------------------------------------ pp worker


def test_worker_is_a_subcommand() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "worker" in result.stdout


def test_worker_runs_the_loop_with_the_processes_own_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI resolves settings and hands them over; it decides nothing about the loop itself."""
    from promisepatch import worker as worker_module

    seen: list[Settings] = []

    async def record(settings: Settings, adapter: Any = None) -> None:
        seen.append(settings)

    monkeypatch.setattr(worker_module, "run", record)
    assert runner.invoke(app, ["worker"]).exit_code == 0
    assert len(seen) == 1


def test_worker_reports_a_misconfiguration_instead_of_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator gets the variable to fix, on stderr, with a non-zero exit code."""
    from promisepatch import worker as worker_module

    async def refuse(settings: Settings, adapter: Any = None) -> None:
        raise RuntimeError("PP_DATABASE_URL is not configured")

    monkeypatch.setattr(worker_module, "run", refuse)
    result = runner.invoke(app, ["worker"])
    assert result.exit_code == 1
    assert "PP_DATABASE_URL" in result.output


# ------------------------------------------------------------------------- intake commands


@pytest.mark.parametrize(
    "name", ["report-exception", "answer-clarification", "correct-physical-fact"]
)
def test_the_intake_commands_are_subcommands(name: str) -> None:
    assert name in runner.invoke(cli.app, ["--help"]).output


def test_reporting_an_exception_delegates_to_the_domain_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI parses arguments and prints a result. Everything else belongs to the domain."""
    seen: dict[str, object] = {}

    async def fake(database: object, **kwargs: object) -> intake.IntakeResult:
        seen.update(kwargs)
        return intake.IntakeResult(
            case_id=UUID(int=1), statement_id=UUID(int=2), state="RECEIVED", created=True
        )

    monkeypatch.setattr(intake, "open_physical_exception", fake)
    monkeypatch.setattr(cli, "_with_database", lambda settings, operation: operation(None))

    result = runner.invoke(
        cli.app, ["report-exception", "the deck oven is down", "--worker", "maya"]
    )

    assert result.exit_code == 0
    assert seen["worker_id"] == "maya"
    assert seen["raw_text"] == "the deck oven is down"
    assert str(UUID(int=1)) in result.output


def test_a_supplied_command_id_is_the_one_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport that can redeliver supplies its own identity, and it must survive intact."""
    given = UUID("11111111-2222-3333-4444-555555555555")
    seen: dict[str, object] = {}

    async def fake(database: object, **kwargs: object) -> intake.IntakeResult:
        seen.update(kwargs)
        return intake.IntakeResult(
            case_id=UUID(int=1), statement_id=given, state="CLARIFYING", created=False
        )

    monkeypatch.setattr(intake, "answer_clarification", fake)
    monkeypatch.setattr(cli, "_with_database", lambda settings, operation: operation(None))

    result = runner.invoke(
        cli.app,
        [
            "answer-clarification",
            "just the raspberries",
            "--case",
            str(UUID(int=1)),
            "--worker",
            "maya",
            "--command-id",
            str(given),
        ],
    )

    assert result.exit_code == 0
    assert seen["command_id"] == given
    assert "already (retry)" in result.output


def test_an_unparseable_identifier_is_reported_rather_than_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_with_database", lambda settings, operation: operation(None))
    result = runner.invoke(
        cli.app,
        [
            "correct-physical-fact",
            "the strawberries were missing",
            "--case",
            "nope",
            "--worker",
            "maya",
        ],
    )

    assert result.exit_code == 1
    assert "not a UUID" in result.output


# --------------------------------------------------------------------------- case status


def test_case_status_is_a_subcommand() -> None:
    assert "case-status" in runner.invoke(app, ["--help"]).stdout


def test_case_status_delegates_to_the_domain_read_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI parses a case id and prints. Reading a case belongs to the domain."""
    seen: dict[str, object] = {}
    track = analysis.TrackStatus(
        track_id=UUID(int=3),
        promise_id="pr-a",
        order_external_id="EXT-A",
        customer_name="Amara Diallo",
        state=analysis.TRACK_PENDING,
        classification="AUTO_RECOVERABLE",
        rule_id="R-PREAPPROVED",
        reason_detail="PREAPPROVAL_COVERS",
        priority=1,
        fingerprint="f" * 64,
        deadline_at=None,
        linked_track_id=None,
        paths=1,
        watched_entities=9,
        options=(
            analysis.OptionStatus(
                id=UUID(int=4),
                kind="SUBSTITUTE_RESOURCE",
                order_line_id="ol-a",
                from_version_id="rv-raspberry-almond-3",
                to_version_id="rv-raspberry-almond-4",
                substitute_resource_id="res-strawberries",
                required_quantity=None,
                requires_approval=False,
                approval_rule="R-PREAPPROVED",
                chosen=True,
            ),
        ),
    )

    async def fake(database: object, *, case_id: UUID) -> analysis.CaseStatus:
        seen["case_id"] = case_id
        return analysis.CaseStatus(
            case_id=case_id,
            state=analysis.CASE_PLANNED,
            needs_owner_attention=False,
            exception_id=UUID(int=2),
            category="SUPPLY_NOT_RECEIVED",
            tracks=(track,),
        )

    monkeypatch.setattr(analysis, "read_case_status", fake)
    monkeypatch.setattr(
        cli, "_read_case_status", lambda settings, case_id: fake(None, case_id=case_id)
    )

    result = runner.invoke(app, ["case-status", "--case", str(UUID(int=1))])

    assert result.exit_code == 0, result.output
    assert seen["case_id"] == UUID(int=1)
    assert analysis.CASE_PLANNED in result.output
    assert "AUTO_RECOVERABLE" in result.output
    assert "rv-raspberry-almond-4" in result.output


def test_case_status_refuses_an_unparseable_identifier() -> None:
    result = runner.invoke(app, ["case-status", "--case", "nope"])

    assert result.exit_code == 1
    assert "not a UUID" in result.output
