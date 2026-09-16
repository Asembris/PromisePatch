"""The ``pp`` operator CLI.

Everything an operator does to a running PromisePatch — serve the API, reset the demo
fixture, replay an inbox row — is a subcommand here rather than a script, so each one is
typed, testable and discoverable.

Every command here is thin, and thin is a requirement rather than a style. A command parses
arguments, calls a reusable service in :mod:`promisepatch.domain`, and prints what came back.
None of them decides anything, and none of them is a shortcut around a rule: in particular
there is no command by which an operator could record a customer's approval, because approval
comes from the customer's own channel and from nowhere else.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer

from promise_graph.model import ApprovalRequestState
from promisepatch import provisioning
from promisepatch.config import LlmProvider, Settings, get_settings
from promisepatch.db import RuntimeDatabase, build_engine
from promisepatch.db.uow import Actor
from promisepatch.domain import analysis, handlers, inbox, intake, observation, recovery
from promisepatch.fixtures import demo
from promisepatch.fixtures.reset import ResetOutcome, ensure_reset_allowed, reset_demo_state
from promisepatch.integrations import build_semantic_provider
from promisepatch.semantic import ClassifyReplyIntentRequest, SemanticError, UntrustedText

app = typer.Typer(
    name="pp",
    help="PromisePatch operator commands.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    """Group callback.

    Without it Typer collapses a single-command application into the bare ``pp`` command,
    which would break the moment a second subcommand is added.
    """


@app.command()
def api(
    host: str = typer.Option("127.0.0.1", help="Interface to bind."),
    port: int = typer.Option(8000, help="Port to bind."),
    reload: bool = typer.Option(False, "--reload", help="Reload on source changes."),
) -> None:
    """Run the HTTP API."""
    import uvicorn

    uvicorn.run("promisepatch.main:app", host=host, port=port, reload=reload)


@app.command()
def mcp(
    host: str = typer.Option("127.0.0.1", help="Interface to bind."),
    port: int = typer.Option(8001, help="Port to bind."),
    reload: bool = typer.Option(False, "--reload", help="Reload on source changes."),
) -> None:
    """Run the Streamable HTTP MCP server.

    A separate process from the API on purpose: it is the endpoint a third-party MCP client is
    pointed at, and it is the one process in this application that cannot reach a database.
    Port 8001 locally so it does not clash with the API; a deployment on AgentCore Runtime
    binds the port that contract expects instead.
    """
    import uvicorn

    from promisepatch.mcp_server import APP_FACTORY

    uvicorn.run(APP_FACTORY, host=host, port=port, reload=reload, factory=True)


@app.command()
def worker() -> None:
    """Run the durable workflow worker.

    Connects as ``promisepatch_app`` like every other runtime process. Stop it with Ctrl+C or a
    ``SIGTERM``; killing it outright is also fine, because everything it was doing is a row and
    every claim it held expires.
    """
    from promisepatch import worker as worker_module

    settings = get_settings()
    try:
        asyncio.run(worker_module.run(settings))
    except RuntimeError as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error


@app.command()
def converse(
    turn: Annotated[
        list[str] | None,
        typer.Option(
            "--turn",
            help="One thing the worker says. Repeat for a scripted conversation; omit to type.",
        ),
    ] = None,
    show_tools: bool = typer.Option(
        False, "--show-tools", help="Print the tool calls each turn made, and what was chosen."
    ),
) -> None:
    """Hold one conversation with a case over the real MCP surface.

    A client, and only a client. It connects to the MCP endpoint with the bearer credential any
    third-party client would present, and every case it touches it touches through a tool call
    -- there is no database handle in this process and no way for it to write anything itself.

    The model chooses among the verbs the case's own state permits. It supplies no arguments:
    what a worker says is forwarded verbatim, and a plan is confirmed only by quoting back the
    identity ``status`` returned. Against the fake provider every turn chooses nothing, which
    is the honest behaviour of a deployment with no model configured.
    """
    settings = get_settings()
    url = settings.orchestrator_mcp_url
    if not url:
        typer.secho(
            "set PP_ORCHESTRATOR_MCP_URL to the MCP endpoint this should talk to "
            "(locally, http://127.0.0.1:8001/mcp).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    scripted = list(turn or ())
    try:
        asyncio.run(_converse(settings, url, scripted, show_tools=show_tools))
    except (RuntimeError, SemanticError) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error


async def _converse(settings: Settings, url: str, scripted: list[str], *, show_tools: bool) -> None:
    """Drive turns against one open session until the script or the operator runs out."""
    from promisepatch.orchestrator import Conversation, Orchestrator, connect

    provider = build_semantic_provider(settings)
    conversation = Conversation()
    async with connect(
        url,
        token=settings.require_mcp_bearer_token(),
        timeout_seconds=settings.orchestrator_timeout_seconds,
    ) as surface:
        orchestrator = Orchestrator(provider=provider, surface=surface)
        for said in scripted or _typed_turns():
            typer.secho(f"> {said}", fg=typer.colors.BLUE)
            started = time.perf_counter()
            result = await orchestrator.take_turn(conversation, said, correlation_id=str(uuid4()))
            conversation = result.conversation
            typer.echo(result.reply)
            if show_tools:
                typer.secho(
                    f"[{int((time.perf_counter() - started) * 1000)} ms | "
                    f"chose {result.selected.value if result.selected else '-'} | "
                    f"called {', '.join(result.calls) or 'nothing'} | "
                    f"phase {conversation.phase.value}]",
                    fg=typer.colors.BRIGHT_BLACK,
                )
            typer.echo("")


def _typed_turns() -> Iterator[str]:
    """Turns read from the terminal, until a blank line or end of input."""
    while True:
        try:
            said = typer.prompt("you", prompt_suffix="> ", default="", show_default=False)
        except (EOFError, typer.Abort):  # pragma: no cover - interactive only
            return
        if not said.strip():
            return
        yield said


@app.command(name="reset-demo-state")
def reset_demo_state_command(
    anchor: str = typer.Option(
        "",
        help=(
            "Reset instant as ISO-8601. Naive values are read in the bakery's timezone; "
            "omit it to anchor on now."
        ),
    ),
) -> None:
    """Reload the demo fixture, replacing every domain row PromisePatch owns.

    The audit ledger and the event spine are untouched: they record that this happened, and a
    reset that could erase its own trace would not be a reset worth trusting.
    """
    settings = get_settings()
    try:
        ensure_reset_allowed(settings)
        resolved_anchor = resolve_anchor(anchor, settings)
        outcome = asyncio.run(_run_reset(settings, resolved_anchor))
    except (RuntimeError, ValueError) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    local = outcome.anchor.astimezone(ZoneInfo(settings.bakery_tz))
    typer.echo(f"fixture:  {outcome.fixture_name}")
    typer.echo(f"anchor:   {outcome.anchor.isoformat()} ({local.isoformat()} {settings.bakery_tz})")
    typer.echo(f"digest:   {outcome.digest}")
    typer.echo(f"rows:     {outcome.rows_written}")
    typer.echo(f"audit:    seq {outcome.audit_seq}")
    typer.echo(f"event:    seq {outcome.domain_event_seq}")


def resolve_anchor(given: str, settings: Settings) -> datetime:
    """Turn the operator's ``--anchor`` into one unambiguous UTC instant.

    A naive value is read in the bakery's timezone rather than the server's, because "seven in
    the morning" is a claim about the kitchen, and the machine running this command may be
    nowhere near it. An aware value is taken as given.

    An omitted one is ``now``, corrected by :func:`promisepatch.fixtures.demo.resolve_demo_anchor`
    for the two hours a day where ``now`` would put the fixture's two deliveries on one bakery
    day and leave the demo undrivable. An operator who names an anchor gets exactly it — that
    is what naming one is for, including naming one this refuses to choose.
    """
    if not given:
        return demo.resolve_demo_anchor(datetime.now(UTC), settings.bakery_tz)
    try:
        parsed = datetime.fromisoformat(given)
    except ValueError as error:
        raise ValueError(f"--anchor {given!r} is not an ISO-8601 datetime") from error
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    try:
        zone = ZoneInfo(settings.bakery_tz)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(
            f"PP_BAKERY_TZ names an unknown timezone: {settings.bakery_tz!r}"
        ) from error
    return parsed.replace(tzinfo=zone).astimezone(UTC)


# --------------------------------------------------------------------------- intake commands
#
# Three thin wrappers, and thin is the requirement rather than the style. Each one parses a
# couple of arguments, calls the reusable service in `promisepatch.domain.intake`, and prints
# what came back. Not one line of what may be said, by whom, or what it means lives here --
# that all lives in the domain, where the MCP tools and the voice orchestrator will find it
# unchanged when they arrive.
#
# Nothing here interprets anything either. These commands only make a statement durable; the
# worker reads it, and until a worker runs, the case sits exactly where the command left it.


@app.command(name="ensure-demo-case")
def ensure_demo_case_command() -> None:
    """Make sure there is one case open to look at, without replacing one that already is.

    The same call the worker makes when it starts, exposed so an operator can run it against a
    database seeded before this existed. It is additive: a database already holding any case is
    left exactly as it is, and nothing here truncates, deletes or overwrites a row.
    """
    settings = get_settings()
    try:
        outcome = asyncio.run(_run_ensure_demo_case(settings))
    except (RuntimeError, ValueError) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"action:   {outcome.action.value}")
    typer.echo(f"case:     {outcome.case_id or '-'}")
    typer.echo(f"state:    {outcome.state or '-'}")
    if outcome.detail:
        typer.echo(f"detail:   {outcome.detail}")


@app.command(name="report-exception")
def report_exception_command(
    text: str = typer.Argument(..., help="What the worker said, verbatim."),
    worker: str = typer.Option(..., "--worker", help="The staff id attesting the observation."),
    command_id: str = typer.Option(
        "", "--command-id", help="Stable command identity; a retry must reuse it."
    ),
) -> None:
    """Open a case for a spoken physical exception."""
    _intake(
        lambda database: intake.open_physical_exception(
            database,
            command_id=_command_id(command_id),
            worker_id=worker,
            raw_text=text,
            observed_at=datetime.now(UTC),
        )
    )


@app.command(name="answer-clarification")
def answer_clarification_command(
    text: str = typer.Argument(..., help="The worker's answer, verbatim."),
    case: str = typer.Option(..., "--case", help="The case awaiting an answer."),
    worker: str = typer.Option(..., "--worker", help="The staff id answering."),
    command_id: str = typer.Option(
        "", "--command-id", help="Stable command identity; a retry must reuse it."
    ),
) -> None:
    """Answer the open clarification on a case."""
    _intake(
        lambda database: intake.answer_clarification(
            database,
            case_id=_uuid(case, "--case"),
            command_id=_command_id(command_id),
            worker_id=worker,
            raw_text=text,
        )
    )


@app.command(name="correct-physical-fact")
def correct_physical_fact_command(
    text: str = typer.Argument(..., help="The correction, verbatim."),
    case: str = typer.Option(..., "--case", help="The case whose facts are being corrected."),
    worker: str = typer.Option(..., "--worker", help="The staff id making the correction."),
    command_id: str = typer.Option(
        "", "--command-id", help="Stable command identity; a retry must reuse it."
    ),
) -> None:
    """Attest a correction to a physical fact this case already recorded.

    A correction is never an undo. The original attestation stays, and the ledger movement that
    cancels it is appended beside the one it cancels.
    """
    _intake(
        lambda database: intake.correct_physical_fact(
            database,
            case_id=_uuid(case, "--case"),
            command_id=_command_id(command_id),
            worker_id=worker,
            raw_text=text,
        )
    )


# --------------------------------------------------------------------------- case commands


@app.command(name="confirm-plan")
def confirm_plan_command(
    case: str = typer.Option(..., "--case", help="The planned case to confirm."),
    worker: str = typer.Option(..., "--worker", help="The staff id confirming the plan."),
    plan: str = typer.Option(
        ..., "--plan", help="The plan identity `case-status` printed for this case."
    ),
    command_id: str = typer.Option(
        "", "--command-id", help="Stable command identity; a retry must reuse it."
    ),
) -> None:
    """Confirm a plan, so the recoveries it already authorises may execute.

    Thin, like the intake commands. Who may confirm, what a confirmation permits, and which
    tracks it does *not* permit all live in :mod:`promisepatch.domain.recovery`, where the MCP
    tool and the voice orchestrator find them unchanged.

    ``--plan`` is required for the same reason the tool argument is: an operator who has not
    read the plan cannot quote its identity, and a confirmation that named only a case would
    authorise whatever the case held at the moment it arrived.

    Nothing is sent from here and nothing is applied here. This makes the confirmation durable;
    the worker process is what executes against it, and until one runs the case sits exactly
    where this command left it.
    """
    settings = get_settings()
    try:
        outcome = asyncio.run(
            _confirm(settings, _uuid(case, "--case"), worker, plan, _command_id(command_id))
        )
    except (RuntimeError, ValueError) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"case:      {outcome.case_id}")
    typer.echo(f"command:   {outcome.command_id}")
    typer.echo(f"state:     {outcome.state}")
    typer.echo(f"accepted:  {'now' if outcome.created else 'already (retry)'}")
    typer.echo(f"applying:  {len(outcome.applying)}")
    typer.echo(f"escalated: {len(outcome.escalated)}")
    typer.echo(f"awaiting approval: {len(outcome.awaiting_approval)}")


async def _confirm(
    settings: Settings, case_id: UUID, worker_id: str, plan_id: str, command_id: UUID
) -> recovery.ConfirmationResult:
    database = RuntimeDatabase.from_settings(settings)
    try:
        return await recovery.confirm_plan(
            database,
            case_id=case_id,
            command_id=command_id,
            worker_id=worker_id,
            plan_id=plan_id,
        )
    finally:
        await database.dispose()


# --------------------------------------------------------------------- customer channel


@app.command(name="receive-customer-reply")
def receive_customer_reply_command(
    text: str = typer.Argument(..., help="What the customer sent, verbatim."),
    request: str = typer.Option(..., "--request", help="The approval request being replied to."),
    sender: str = typer.Option(
        ..., "--from", help="The channel the reply arrived on, e.g. tg:1002."
    ),
    event_id: str = typer.Option(
        "", "--event-id", help="The provider's own id for this delivery; a retry must reuse it."
    ),
) -> None:
    """Deliver one customer reply through the fake customer channel.

    A transport, and only a transport. It writes the raw material to ``inbox_events`` and stops:
    it does not check the sender, does not read the words, and cannot create an approval
    decision. The worker reads the stored row and applies the consent protocol to it under the
    case lock, which is the only path by which a customer's words become authority.

    That separation is the point of the command's existence. There is deliberately no
    ``approve-for-customer``, and no flag here that would make one: an operator can deliver a
    message a customer sent, and cannot supply the message.

    A redelivery carrying the same ``--event-id`` is absorbed by the inbox's own uniqueness and
    does nothing a second time.
    """
    settings = get_settings()
    delivery = event_id or f"cli-{uuid4()}"
    try:
        stored = asyncio.run(
            _receive_reply(
                settings,
                request_id=_uuid(request, "--request"),
                sender=sender,
                text=text,
                provider_event_id=delivery,
            )
        )
    except (RuntimeError, ValueError) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"request:  {request}")
    typer.echo(f"from:     {sender}")
    typer.echo(f"event:    {delivery}")
    typer.echo(f"accepted: {'now' if stored else 'already (duplicate delivery)'}")


async def _receive_reply(
    settings: Settings,
    *,
    request_id: UUID,
    sender: str,
    text: str,
    provider_event_id: str,
) -> bool:
    database = RuntimeDatabase.from_settings(settings)
    try:
        async with database.begin() as connection:
            stored = await inbox.ingest(
                connection,
                source=handlers.CUSTOMER_REPLY_SOURCE,
                provider_event_id=provider_event_id,
                body=json.dumps(
                    {
                        "request_id": str(request_id),
                        "sender": sender,
                        "text": text,
                        "provider_message_id": provider_event_id,
                    }
                ),
            )
        return stored is not None
    finally:
        await database.dispose()


@app.command(name="case-status")
def case_status_command(
    case: str = typer.Option(..., "--case", help="The case to describe."),
) -> None:
    """Show what analysis and planning concluded for one case.

    Read-only. It runs no step, enqueues nothing and changes nothing: the worker is what moves
    a case, and an operator command that quietly did the work would make the durable engine
    optional. Everything printed comes from :func:`promisepatch.domain.analysis.read_case_status`.
    """
    settings = get_settings()
    try:
        status = asyncio.run(_read_case_status(settings, _uuid(case, "--case")))
    except (RuntimeError, ValueError) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"case:      {status.case_id}")
    typer.echo(f"state:     {status.state}")
    typer.echo(f"exception: {status.exception_id or '-'} ({status.category or '-'})")
    typer.echo(f"attention: {'yes' if status.needs_owner_attention else 'no'}")
    # The identity of the plan as it currently stands, so an operator confirming one quotes
    # back what they just read rather than naming a case and hoping.
    typer.echo(f"plan:      {status.plan_id}")
    if status.clarification is not None:
        typer.echo(f"question:  {status.clarification.question}")
        for answer in status.clarification.options:
            typer.echo(f"  [{answer.code}] {answer.label}")
    _echo_interpretation(status.interpretation)
    for track in status.tracks:
        typer.echo("")
        typer.echo(f"  {track.promise_id}  {track.customer_name} / {track.order_external_id}")
        typer.echo(
            f"    {track.classification or '-'} via {track.rule_id or '-'} "
            f"({track.reason_detail or '-'})"
        )
        typer.echo(
            f"    track {track.state}, priority {track.priority}, "
            f"{track.paths} path(s), {track.watched_entities} watched"
        )
        # The mirror, as it stands. An amendment the order system has accepted but not yet
        # echoed leaves the track waiting, and this is what it is waiting for: the external
        # version below has to reach the one the effect reports, with the line pinned to the
        # variant the plan chose. Read-only, like everything else this command prints.
        typer.echo(f"    mirror external version {track.order_external_version}")
        for line_id, version_id in sorted(track.mirrored_versions.items()):
            typer.echo(f"      {line_id} -> {version_id}")
        if track.fingerprint:
            typer.echo(f"    fingerprint {track.fingerprint}")
        if track.linked_track_id:
            typer.echo(f"    linked to track {track.linked_track_id}")
        if track.deadline_at:
            typer.echo(f"    approval window closes {track.deadline_at.isoformat()}")
        for option in track.options:
            marker = "*" if option.chosen else " "
            typer.echo(
                f"   {marker}option {option.kind} {option.from_version_id or '-'} -> "
                f"{option.to_version_id or '-'} "
                f"({'approval required' if option.requires_approval else 'no approval'})"
            )
        if not track.options:
            typer.echo("     no recovery option")
        if track.approval is not None:
            approval = track.approval
            typer.echo(
                f"    approval {approval.request_id} ({approval.option_code}) "
                f"{approval.state}, deadline {approval.deadline.isoformat()}"
            )
            typer.echo(
                f"      sent {approval.sent_at.isoformat()} "
                f"ref {approval.provider_ref or '-'}, replies {approval.replies}"
            )
            if approval.apparent_intents:
                # Printed above the decision and worded so the two cannot be confused: a
                # reading is what a model made of somebody's words, and an operator looking at
                # this line has to be able to see at a glance that nothing was authorised by it.
                typer.echo(
                    f"      apparent intent (a reading, not consent): "
                    f"{', '.join(approval.apparent_intents)}"
                )
            if approval.state == ApprovalRequestState.CONFIRMATION_PENDING.value:
                typer.echo("      a confirmation was requested; waiting for a literal YES or NO")
            typer.echo(f"      decision {approval.decision or '-'} via {approval.parser or '-'}")
        if track.revalidation is not None:
            checked = track.revalidation
            deciding = (
                "" if checked.deciding_check is None else f", failed at {checked.deciding_check}"
            )
            typer.echo(f"    revalidation {checked.outcome}{deciding}")
            if checked.detail:
                typer.echo(f"      {checked.detail}")
            for check in checked.checks:
                mark = "pass" if check.passed else "FAIL"
                typer.echo(f"      {check.index:>2}. {mark}  {check.name}")
                typer.echo(f"          expected {check.expected}")
                typer.echo(f"          actual   {check.actual}")
        for effect in track.effects:
            typer.echo(
                f"    effect {effect.kind} {effect.state} "
                f"(attempt {effect.attempts}, ref {effect.provider_ref or '-'})"
            )
            typer.echo(f"      key {effect.idempotency_key}")
            if effect.result:
                reported = ", ".join(
                    f"{name} {value}" for name, value in sorted(effect.result.items())
                )
                typer.echo(f"      provider reported: {reported}")
            if effect.last_error:
                typer.echo(f"      last error: {effect.last_error}")


def _echo_interpretation(reading: analysis.InterpretationStatus | None) -> None:
    """How this case's sentence was read, and who is on the record for what it said.

    Two lines for an ordinary case and four for one a model helped with. The second block
    exists to answer one question quickly -- *was a model involved, and did that change who
    attested the facts* -- and the answer to the second half never varies: the attestor is the
    person who spoke.

    No prompt and no model output is printed here, because neither is evidence of anything and
    the row does not hold them.
    """
    if reading is None:
        typer.echo("reading:   not yet interpreted")
        return

    typer.echo(f"reading:   {reading.source.lower().replace('_', '-')} ({reading.outcome or '-'})")
    typer.echo(f"  attestor {reading.attestor or '-'}, intake step {reading.step_state or '-'}")
    if reading.source == observation.SOURCE_SEMANTIC_ASSISTED:
        offered = ", ".join(f"{name} {count}" for name, count in sorted(reading.candidates.items()))
        typer.echo(
            f"  semantic {reading.provider or '-'} / {reading.model_id or '-'}, "
            f"asked because {reading.deterministic_reason or '-'}"
        )
        typer.echo(f"  candidates offered: {offered or 'none'}")
        typer.echo(
            f"  grounded {', '.join(reading.grounded) or 'nothing'}; "
            f"not supported by the report: {', '.join(reading.rejected) or 'nothing'}"
        )
        if reading.failure and reading.failure != "NONE":
            # Named apart from `asked because` above, which is the *deterministic* stop. This
            # one is what the reading itself failed on, and printing both under one word would
            # send somebody looking at the wrong thing.
            typer.echo(f"  the reading was refused: {reading.failure}")
    if reading.last_error:
        typer.echo(f"  last error: {reading.last_error}")


@app.command(name="semantic-smoke")
def semantic_smoke_command(
    text: str = typer.Option(
        "Strawberries work",
        "--text",
        help="The reply to read. Treated as data; it decides nothing.",
    ),
) -> None:
    """Put one small, safe question to the configured semantic provider and print the answer.

    A diagnostic, and only a diagnostic. It opens no database connection, touches no case and
    writes nothing anywhere: it exists to answer "can this machine reach the model, and does
    the model come back inside the schema" without staging a demo to find out.

    Against Bedrock it needs AWS credentials, which come from the SDK's own chain -- a profile,
    an SSO session, a task role. None of them is read by PromisePatch and none of them is
    printed here. If there are none, the SDK says so and this reports it.
    """
    settings = get_settings()
    request = ClassifyReplyIntentRequest(reply=UntrustedText(text=text))

    typer.echo(f"provider: {settings.llm_provider.value}")
    typer.echo(f"job:      {request.job.value}")
    try:
        # Construction is inside the guard as well as the call. Missing configuration and an
        # unreachable model are the same question for whoever ran this -- "why can I not talk
        # to the model" -- and both deserve a sentence rather than a stack trace.
        provider = build_semantic_provider(settings)
        result = asyncio.run(provider.run(request))
    except (RuntimeError, SemanticError) as error:
        # Credentials, model access and Region come from outside PromisePatch, so a failure
        # here is usually somebody's AWS setup rather than a bug. Name what to check, and
        # print no credential: the provider's message already carries the service's own code.
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        if settings.llm_provider is LlmProvider.BEDROCK:
            typer.secho(
                "check that credentials are available to the AWS SDK (AWS_PROFILE, an SSO "
                f"session or a task role) and that this account may invoke "
                f"{settings.bedrock_model_id} in {settings.aws_region}.",
                fg=typer.colors.RED,
                err=True,
            )
        raise typer.Exit(code=1) from error

    telemetry = result.telemetry
    typer.echo(f"model:    {telemetry.model_id or '-'}")
    typer.echo(f"attempts: {telemetry.attempts}")
    typer.echo(f"result:   {result.value.model_dump_json()}")
    typer.echo(
        f"usage:    in {telemetry.usage.input_tokens or '-'} "
        f"out {telemetry.usage.output_tokens or '-'} "
        f"latency {telemetry.usage.latency_ms or '-'} ms"
    )
    typer.echo("authority: none. This reading cannot approve, decline or record anything.")


async def _read_case_status(settings: Settings, case_id: UUID) -> analysis.CaseStatus:
    database = RuntimeDatabase.from_settings(settings)
    try:
        return await analysis.read_case_status(database, case_id=case_id)
    finally:
        await database.dispose()


def _uuid(value: str, flag: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{flag} {value!r} is not a UUID") from error


def _command_id(value: str) -> UUID:
    """The caller's identity for this statement, or a fresh one if they have none.

    Minting one is right for a person at a terminal: they are not retrying anything, and a new
    identity is exactly what they mean. A transport that can redeliver must supply its own.
    """
    return _uuid(value, "--command-id") if value else intake.new_command_id()


def _intake(operation: Callable[[RuntimeDatabase], Awaitable[intake.IntakeResult]]) -> None:
    """Run one intake command against the runtime connection and report what it did."""
    settings = get_settings()
    try:
        outcome = asyncio.run(_with_database(settings, operation))
    except (RuntimeError, ValueError) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"case:      {outcome.case_id}")
    typer.echo(f"statement: {outcome.statement_id}")
    typer.echo(f"state:     {outcome.state}")
    typer.echo(f"accepted:  {'now' if outcome.created else 'already (retry)'}")


async def _with_database(
    settings: Settings, operation: Callable[[RuntimeDatabase], Awaitable[intake.IntakeResult]]
) -> intake.IntakeResult:
    database = RuntimeDatabase.from_settings(settings)
    try:
        return await operation(database)
    finally:
        await database.dispose()


async def _run_ensure_demo_case(settings: Settings) -> provisioning.ProvisionOutcome:
    """The same call the worker makes at start, with a worker of its own to drive the case.

    ``built`` rather than a hand-rolled :class:`~promisepatch.worker.Worker`, so this reaches
    exactly the providers the deployed worker reaches and cannot drift into a second wiring.
    """
    from promisepatch import worker as worker_module

    async with worker_module.built(settings) as runner:
        return await provisioning.ensure_demo_case(
            runner.database, cycles=runner, settings=settings
        )


async def _run_reset(settings: Settings, anchor: datetime) -> ResetOutcome:
    """One connection, one transaction: the reset commits whole or not at all."""
    passwords = {
        demo.BAKER_ROLE: settings.require_demo_worker_password(),
        demo.OWNER_ROLE: settings.require_demo_owner_password(),
    }
    engine = build_engine(settings.require_migration_database_url(), pool_size=1)
    try:
        async with engine.begin() as connection:
            return await reset_demo_state(
                connection,
                anchor=anchor,
                now=datetime.now(UTC),
                passwords=passwords,
                actor=Actor(kind="SYSTEM", id="pp reset-demo-state"),
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    app()
