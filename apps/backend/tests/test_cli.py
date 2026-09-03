"""The ``pp`` operator CLI."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from promisepatch.cli import app, resolve_anchor
from promisepatch.config import Settings, get_settings
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
