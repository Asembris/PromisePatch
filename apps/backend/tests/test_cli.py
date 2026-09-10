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
from promisepatch.domain import analysis, cases, intake, observation, recovery
from promisepatch.fixtures.reset import ResetOutcome
from promisepatch.semantic import SemanticProviderError

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


# --------------------------------------------------------------------------------- pp mcp


def test_mcp_is_a_subcommand() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "mcp" in result.stdout


def test_mcp_serves_the_application_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """A factory, not a module-level app.

    Building the MCP server asserts things about the environment -- an inbound credential, an
    engine to reach -- so a module-level instance would make *importing* it an assertion, and
    the import has to succeed on a machine that has neither. ``--factory`` is how uvicorn is
    told to call it at startup instead.
    """
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_run(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr("uvicorn.run", fake_run)

    result = runner.invoke(app, ["mcp", "--host", "0.0.0.0", "--port", "9002"])

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            ("promisepatch.mcp_server:create_app",),
            {"host": "0.0.0.0", "port": 9002, "reload": False, "factory": True},
        )
    ]


def test_the_mcp_server_refuses_to_start_without_an_inbound_credential() -> None:
    """A startup failure, not a runtime one. A server with no credential accepts everyone."""
    from promisepatch.mcp_server import create_app

    settings = Settings(mcp_intent_api_base_url="http://api:8000")
    with pytest.raises(RuntimeError, match="PP_MCP_BEARER_TOKEN"):
        create_app(settings)


def test_the_mcp_server_refuses_to_start_with_no_engine_to_reach() -> None:
    """One that came up anyway would answer every call ``ENGINE_UNAVAILABLE`` while looking well."""
    from promisepatch.mcp_server import create_app

    settings = Settings(mcp_bearer_token="a-token")
    with pytest.raises(RuntimeError, match="PP_MCP_INTENT_API_BASE_URL"):
        create_app(settings)


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
        order_external_version=1,
        mirrored_versions={"ol-a": "rv-raspberry-almond-3"},
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
        revalidation=None,
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


def _status_with(
    monkeypatch: pytest.MonkeyPatch, reading: analysis.InterpretationStatus | None
) -> str:
    """Run ``case-status`` against a case whose interpretation is exactly this."""

    async def fake(database: object, *, case_id: UUID) -> analysis.CaseStatus:
        return analysis.CaseStatus(
            case_id=case_id,
            state=analysis.CASE_PLANNED,
            needs_owner_attention=False,
            exception_id=UUID(int=2),
            category="SUPPLY_NOT_RECEIVED",
            tracks=(),
            interpretation=reading,
        )

    monkeypatch.setattr(
        cli, "_read_case_status", lambda settings, case_id: fake(None, case_id=case_id)
    )
    result = runner.invoke(app, ["case-status", "--case", str(UUID(int=1))])
    assert result.exit_code == 0, result.output
    return result.output


def test_case_status_says_who_attested_a_semantic_assisted_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator's version of the trust line: a model read it, a person attested it."""
    output = _status_with(
        monkeypatch,
        analysis.InterpretationStatus(
            source=observation.SOURCE_SEMANTIC_ASSISTED,
            outcome="RESOLVED",
            attestor="maya",
            step_state="DONE",
            provider="bedrock",
            model_id="us.amazon.nova-2-lite-v1:0",
            deterministic_reason="NO_CATEGORY",
            grounded=("res-deck-oven",),
            rejected=("res-raspberries",),
            failure="NONE",
            candidates={"resources": 16, "equipment": 2},
        ),
    )

    assert "semantic-assisted" in output
    assert "attestor maya" in output
    assert "us.amazon.nova-2-lite-v1:0" in output
    assert "asked because NO_CATEGORY" in output
    assert "grounded res-deck-oven" in output
    assert "not supported by the report: res-raspberries" in output
    assert "resources 16" in output


def test_case_status_prints_no_prompt_and_no_model_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence, not a transcript. There is nothing here for a prompt to be printed from."""
    output = _status_with(
        monkeypatch,
        analysis.InterpretationStatus(
            source=observation.SOURCE_SEMANTIC_ASSISTED,
            outcome="CLARIFICATION_REQUIRED",
            attestor=None,
            provider="fake",
        ),
    )

    assert "CANDIDATES" not in output
    assert "WORKER STATEMENT" not in output
    assert "delivery didn" not in output


def test_case_status_says_when_a_reading_was_purely_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _status_with(
        monkeypatch,
        analysis.InterpretationStatus(
            source=observation.SOURCE_DETERMINISTIC, outcome="RESOLVED", attestor="maya"
        ),
    )

    assert "deterministic (RESOLVED)" in output
    assert "semantic" not in output


def test_case_status_says_when_nothing_has_read_the_sentence_yet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert "not yet interpreted" in _status_with(monkeypatch, None)


def test_case_status_shows_the_effect_a_recovery_produced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator asking "did that reach the order system" gets the key and the receipt."""
    track = analysis.TrackStatus(
        track_id=UUID(int=3),
        promise_id="pr-a",
        order_external_id="EXT-A",
        order_external_version=1,
        mirrored_versions={"ol-a": "rv-raspberry-almond-3"},
        customer_name="Amara Diallo",
        state=recovery.TRACK_RECOVERED,
        classification="AUTO_RECOVERABLE",
        rule_id="R-PREAPPROVED",
        reason_detail="PREAPPROVAL_COVERS",
        priority=1,
        fingerprint="f" * 64,
        deadline_at=None,
        linked_track_id=None,
        paths=1,
        watched_entities=9,
        revalidation=None,
        options=(),
        effects=(
            analysis.EffectStatus(
                kind=recovery.EFFECT_ORDER_AMEND,
                state="DELIVERED",
                idempotency_key="pp:amend:track:option:1",
                provider_ref="fake-abc123",
                attempts=2,
                result={"external_version": 2, "item_id": "rv-raspberry-almond-4"},
                delivered_at=None,
                last_error=None,
            ),
        ),
    )

    async def fake(database: object, *, case_id: UUID) -> analysis.CaseStatus:
        return analysis.CaseStatus(
            case_id=case_id,
            state=cases.CASE_EXECUTING,
            needs_owner_attention=True,
            exception_id=UUID(int=2),
            category="SUPPLY_NOT_RECEIVED",
            tracks=(track,),
        )

    monkeypatch.setattr(
        cli, "_read_case_status", lambda settings, case_id: fake(None, case_id=case_id)
    )

    result = runner.invoke(app, ["case-status", "--case", str(UUID(int=1))])

    assert result.exit_code == 0, result.output
    assert recovery.EFFECT_ORDER_AMEND in result.output
    assert "DELIVERED" in result.output
    assert "pp:amend:track:option:1" in result.output
    assert "fake-abc123" in result.output


def test_case_status_shows_the_ten_checks_with_the_values_they_compared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§22's checklist, on a terminal: each check named, each with its two values.

    The one screen a judge is shown for Proof F, and the one place an operator can see *why* a
    customer's approval was or was not acted on -- so it prints the comparison, not a verdict.
    """
    track = analysis.TrackStatus(
        track_id=UUID(int=3),
        promise_id="pr-b",
        order_external_id="EXT-B",
        order_external_version=1,
        mirrored_versions={"ol-b": "rv-raspberry-rose-2"},
        customer_name="Tomas Nowak",
        state=recovery.TRACK_STALE,
        classification="APPROVAL_REQUIRED",
        rule_id="R-VISIBLE-ASK",
        reason_detail="VISIBLE_CHANGE",
        priority=2,
        fingerprint="f" * 64,
        deadline_at=None,
        linked_track_id=None,
        paths=1,
        watched_entities=9,
        revalidation=analysis.RevalidationStatus(
            outcome="STALE",
            deciding_check=2,
            detail="check 2: ACCEPTED @ v1 != AMENDED @ v2",
            fingerprint=None,
            checks=(
                analysis.RevalidationCheck(
                    index=1,
                    name="track and case are waiting",
                    passed=True,
                    expected="track=WAITING_FOR_CUSTOMER case=WAITING",
                    actual="track=WAITING_FOR_CUSTOMER case=WAITING",
                ),
                analysis.RevalidationCheck(
                    index=2,
                    name="order state and version unchanged",
                    passed=False,
                    expected="ACCEPTED|AMENDED @ v1",
                    actual="AMENDED @ v2",
                ),
            ),
        ),
        options=(),
        effects=(),
    )

    async def fake(database: object, *, case_id: UUID) -> analysis.CaseStatus:
        return analysis.CaseStatus(
            case_id=case_id,
            state=cases.CASE_REVALIDATING,
            needs_owner_attention=False,
            exception_id=UUID(int=2),
            category="SUPPLY_NOT_RECEIVED",
            tracks=(track,),
        )

    monkeypatch.setattr(
        cli, "_read_case_status", lambda settings, case_id: fake(None, case_id=case_id)
    )

    result = runner.invoke(app, ["case-status", "--case", str(UUID(int=1))])

    assert result.exit_code == 0, result.output
    assert "revalidation STALE" in result.output
    assert "failed at 2" in result.output
    assert "order state and version unchanged" in result.output
    assert "ACCEPTED|AMENDED @ v1" in result.output
    assert "AMENDED @ v2" in result.output
    assert "FAIL" in result.output
    assert "pass" in result.output


def test_case_status_refuses_an_unparseable_identifier() -> None:
    result = runner.invoke(app, ["case-status", "--case", "nope"])

    assert result.exit_code == 1
    assert "not a UUID" in result.output


# --------------------------------------------------------------------------- confirm plan


def test_confirm_plan_is_a_subcommand() -> None:
    assert "confirm-plan" in runner.invoke(app, ["--help"]).stdout


def test_confirming_a_plan_delegates_to_the_domain_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI parses three arguments and prints. What a yes authorises is the domain's."""
    seen: dict[str, object] = {}
    given = UUID("11111111-2222-3333-4444-555555555555")

    async def fake(database: object, **kwargs: object) -> recovery.ConfirmationResult:
        seen.update(kwargs)
        return recovery.ConfirmationResult(
            case_id=UUID(int=1),
            command_id=given,
            state=cases.CASE_EXECUTING,
            created=True,
            applying=(UUID(int=3),),
            escalated=(UUID(int=4), UUID(int=5)),
            awaiting_approval=(UUID(int=6),),
        )

    monkeypatch.setattr(recovery, "confirm_plan", fake)
    monkeypatch.setattr(
        cli,
        "_confirm",
        lambda settings, case_id, worker_id, command_id: fake(
            None, case_id=case_id, worker_id=worker_id, command_id=command_id
        ),
    )

    result = runner.invoke(
        app,
        [
            "confirm-plan",
            "--case",
            str(UUID(int=1)),
            "--worker",
            "maya",
            "--command-id",
            str(given),
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen["case_id"] == UUID(int=1)
    assert seen["worker_id"] == "maya"
    assert seen["command_id"] == given
    assert cases.CASE_EXECUTING in result.output
    assert "applying:  1" in result.output


def test_confirm_plan_reports_a_refusal_instead_of_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A case that is not waiting for a yes is an operator error, not a crash."""

    async def refuse(settings: object, case_id: UUID, worker_id: str, command_id: UUID) -> None:
        raise recovery.PlanNotConfirmableError("case is ANALYZED, not PLANNED")

    monkeypatch.setattr(cli, "_confirm", refuse)

    result = runner.invoke(app, ["confirm-plan", "--case", str(UUID(int=1)), "--worker", "maya"])

    assert result.exit_code == 1
    assert "not PLANNED" in result.output


def test_confirm_plan_refuses_an_unparseable_identifier() -> None:
    result = runner.invoke(app, ["confirm-plan", "--case", "nope", "--worker", "maya"])

    assert result.exit_code == 1
    assert "not a UUID" in result.output


# ---------------------------------------------------------------- semantic diagnostics


def test_semantic_smoke_is_a_subcommand() -> None:
    assert "semantic-smoke" in runner.invoke(app, ["--help"]).stdout


def test_semantic_smoke_reports_the_reading_and_says_it_authorises_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A diagnostic: the configured provider answers, and the answer decides nothing.

    Runs against the fake, because that is what an unconfigured machine has. It opens no
    database connection, which is why there is nothing to stub here but the environment.
    """
    monkeypatch.setenv("PP_LLM_PROVIDER", "fake")
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["semantic-smoke", "--text", "Strawberries work"])
    finally:
        get_settings.cache_clear()

    assert result.exit_code == 0, result.output
    assert "provider: fake" in result.output
    assert "job:      classify_reply_intent" in result.output
    assert "APPARENT" in result.output or "UNCLEAR" in result.output
    assert "authority: none" in result.output


def test_semantic_smoke_reports_a_failure_instead_of_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A machine with no AWS access should be told what to configure, not shown a stack."""

    def unavailable(settings: object) -> object:
        raise SemanticProviderError(
            "Bedrock refused the call: AccessDeniedException", retryable=False
        )

    monkeypatch.setenv("PP_LLM_PROVIDER", "bedrock")
    monkeypatch.setattr(cli, "build_semantic_provider", unavailable)
    get_settings.cache_clear()
    try:
        result = runner.invoke(app, ["semantic-smoke"])
    finally:
        get_settings.cache_clear()

    assert result.exit_code == 1
    assert "AccessDeniedException" in result.output
    assert "AWS_PROFILE" in result.output


def test_there_is_no_diagnostic_that_changes_anything() -> None:
    """A semantic command may look; none of them may act."""
    names = {command.name or "" for command in app.registered_commands}
    semantic = {name for name in names if name.startswith("semantic")}

    assert semantic == {"semantic-smoke"}
    assert not [name for name in semantic if "apply" in name or "interpret-and" in name]


# ------------------------------------------------------------------ customer channel


def test_receive_customer_reply_is_a_subcommand() -> None:
    assert "receive-customer-reply" in runner.invoke(app, ["--help"]).stdout


def test_there_is_no_command_that_approves_for_a_customer() -> None:
    """The absence is the assertion.

    A worker or an owner cannot record a customer's consent, so no operator command may exist
    that would let them. The delivery command is the only path in, and all it can do is carry
    what somebody actually sent.
    """
    names = {command.name or "" for command in app.registered_commands}

    assert "approve-for-customer" not in names
    assert not [name for name in names if "approve" in name]
    assert not [name for name in names if "decision" in name]


def test_a_delivered_reply_is_only_ingested(monkeypatch: pytest.MonkeyPatch) -> None:
    """The command writes transport material and decides nothing at all."""
    seen: dict[str, object] = {}

    async def fake(settings: object, **kwargs: object) -> bool:
        seen.update(kwargs)
        return True

    monkeypatch.setattr(
        cli,
        "_receive_reply",
        lambda settings, *, request_id, sender, text, provider_event_id: fake(
            None,
            request_id=request_id,
            sender=sender,
            text=text,
            provider_event_id=provider_event_id,
        ),
    )

    result = runner.invoke(
        app,
        [
            "receive-customer-reply",
            "Strawberries work",
            "--request",
            str(UUID(int=7)),
            "--from",
            "tg:1002",
            "--event-id",
            "update-42",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen["request_id"] == UUID(int=7)
    assert seen["sender"] == "tg:1002"
    assert seen["text"] == "Strawberries work"
    assert seen["provider_event_id"] == "update-42"
    assert "accepted: now" in result.output


def test_a_redelivered_reply_is_reported_as_a_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The inbox deduplicated it, and the operator is told so rather than told it worked."""
    monkeypatch.setattr(
        cli,
        "_receive_reply",
        lambda settings, **kwargs: _false(),
    )

    result = runner.invoke(
        app,
        [
            "receive-customer-reply",
            "YES",
            "--request",
            str(UUID(int=7)),
            "--from",
            "tg:1002",
            "--event-id",
            "update-42",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "duplicate delivery" in result.output


async def _false() -> bool:
    return False


def test_receive_customer_reply_refuses_an_unparseable_request() -> None:
    result = runner.invoke(
        app, ["receive-customer-reply", "YES", "--request", "nope", "--from", "tg:1002"]
    )

    assert result.exit_code == 1
    assert "not a UUID" in result.output


def test_case_status_shows_the_approval_without_the_customers_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator sees which request, until when, and what came back. Not the address."""
    approval = analysis.ApprovalStatus(
        request_id=UUID(int=9),
        option_code="OPT-ABC123",
        state="ANSWERED",
        decided=True,
        sent_at=datetime(2026, 3, 4, 8, 0, tzinfo=UTC),
        deadline=datetime(2026, 3, 4, 12, 0, tzinfo=UTC),
        provider_ref="fake-msg-1",
        decision="APPROVE",
        parser="LITERAL",
        replies=2,
    )
    track = analysis.TrackStatus(
        track_id=UUID(int=3),
        promise_id="pr-b",
        order_external_id="EXT-B",
        order_external_version=1,
        mirrored_versions={"ol-b": "rv-raspberry-rose-2"},
        customer_name="Tomas Lindqvist",
        state="WAITING_FOR_CUSTOMER",
        classification="APPROVAL_REQUIRED",
        rule_id="R-VISIBLE-ASK",
        reason_detail="VISIBLE_CHANGE_ASK",
        priority=1,
        fingerprint="f" * 64,
        deadline_at=approval.deadline,
        linked_track_id=None,
        paths=1,
        watched_entities=4,
        revalidation=None,
        options=(),
        approval=approval,
    )

    async def fake(database: object, *, case_id: UUID) -> analysis.CaseStatus:
        return analysis.CaseStatus(
            case_id=case_id,
            state="WAITING",
            needs_owner_attention=False,
            exception_id=UUID(int=2),
            category="SUPPLY_NOT_RECEIVED",
            tracks=(track,),
        )

    monkeypatch.setattr(
        cli, "_read_case_status", lambda settings, case_id: fake(None, case_id=case_id)
    )

    result = runner.invoke(app, ["case-status", "--case", str(UUID(int=1))])

    assert result.exit_code == 0, result.output
    assert str(UUID(int=9)) in result.output
    assert "OPT-ABC123" in result.output
    assert "ANSWERED" in result.output
    assert "APPROVE" in result.output
    assert "LITERAL" in result.output
    assert "fake-msg-1" in result.output
    assert "tg:" not in result.output
