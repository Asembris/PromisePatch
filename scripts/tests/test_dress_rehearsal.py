"""What the ``DR01`` dress rehearsal has to be, and what it must never be able to become.

Two jobs. The first is the boundary: a rehearsal borrows the ``SUR-1`` execution pipeline and
must not be able to produce a ``SUR-1`` artefact, spend its authorisation phrase, reach one of
its world programs or edit its frozen documents. The second is the lifecycle the rehearsal
exists to exercise -- resume, the single retry and its one permitted cause, write-once, and the
token blinding that survives from a verdict to a join -- asserted here against stub arms so that
each rule is proved without a database, a model or a running stack.

**Nothing here writes outside ``tmp_path``.** The arms are stubs labelled ``REHEARSAL-A``,
``REHEARSAL-B`` and ``REHEARSAL-C``; the evidence is written by hand in this file; no model is
reached and no service is contacted.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts.rehearsal import CONTRACT_PATH, NOT_A_BENCHMARK, RUNS_ROOT, SCENARIO
from scripts.rehearsal import ROOT as REPO
from scripts.rehearsal import contract as rehearsal_contract
from scripts.rehearsal import program as rehearsal_program
from scripts.rehearsal.scorer import DIMENSIONS, REHEARSAL
from scripts.rehearsal.world import CustomerLinkSink, RehearsalIngressError
from scripts.sur1 import predeclaration
from scripts.sur1.arms import ArmAttempt
from scripts.sur1.bindings.setup import UnprogrammedScenarioError
from scripts.sur1.budget import BudgetExhaustedError
from scripts.sur1.capture import CaptureError, RunDirectory, write_once
from scripts.sur1.doubles import FakeClock, StubArm, SyntheticWorld
from scripts.sur1.driver import Clock, UnsubstitutableScoredRunError, drive, join
from scripts.sur1.evidence import (
    ChannelMessage,
    OrderEvent,
    ReceiverEvidence,
    ReportedPromiseRow,
    TaskSample,
    WorkerReport,
)
from scripts.sur1.frozen import PUBLISHED_MANIFEST_SHA

CONTRACT = rehearsal_contract.load()
UNIVERSE = CONTRACT.case_universe
LABELS = ("REHEARSAL-A", "REHEARSAL-B", "REHEARSAL-C")

WALL = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
PHRASE = "AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE"


def clock() -> Clock:
    return Clock(monotonic=FakeClock(), wall=lambda: WALL)


def tasks() -> tuple[TaskSample, ...]:
    return tuple(
        TaskSample(f"task-ol-{order[-1]}", order, "SCHEDULED", "SCHEDULED") for order in UNIVERSE
    )


def report(*, cover: tuple[str, ...] = UNIVERSE) -> WorkerReport:
    return WorkerReport(
        scenario_id=SCENARIO,
        exception_recorded=True,
        promises=tuple(
            ReportedPromiseRow(order, "UNTOUCHED", None, "UNKNOWN", False) for order in cover
        ),
    )


def ask() -> ChannelMessage:
    """An outbound message the declared rule reads as a question, so nothing is undetermined."""
    return ChannelMessage(
        channel_address="tg:1002",
        direction="OUTBOUND",
        text="Would you like us to change it? Please reply YES or NO.",
        accepted_at=datetime(2026, 9, 19, 9, 1, tzinfo=UTC),
        provider_event_id="out-1",
    )


def answer() -> ChannelMessage:
    return ChannelMessage(
        channel_address="tg:1002",
        direction="INBOUND",
        text="YES",
        accepted_at=datetime(2026, 9, 19, 9, 2, tzinfo=UTC),
        provider_event_id="in-1",
    )


def amendment() -> OrderEvent:
    return OrderEvent(
        external_id="EXT-B",
        event_type="ORDER_AMENDED",
        event_source="amendment",
        idempotency_key="dr01-key-1",
        occurred_at=datetime(2026, 9, 19, 9, 3, tzinfo=UTC),
        version=2,
        previous_version=1,
        line_external_item_id="rv-raspberry-rose-3",
    )


def complete_evidence() -> ReceiverEvidence:
    """The shape a composed pipeline leaves behind: ask, answer, amendment, report."""
    return ReceiverEvidence(
        order_events=(amendment(),),
        messages=(ask(), answer()),
        tasks=tasks(),
        report=report(),
    )


def void_evidence() -> ReceiverEvidence:
    """A declared source that could not be read. The one cause a retry is permitted for."""
    return ReceiverEvidence(tasks=tasks(), report=report(), unreadable_sources=frozenset({"E3"}))


def invalid_evidence() -> ReceiverEvidence:
    """A report that does not cover the case universe. A nonpass, and never a void."""
    return ReceiverEvidence(tasks=tasks(), report=report(cover=("ord-a",)))


def stub(label: str, *outcomes: ArmAttempt | BaseException) -> StubArm:
    return StubArm(label=label, outcomes=list(outcomes))


def run(
    tmp_path: Path, *arms: StubArm, run_id: str = "rehearsal-run", **overrides: object
) -> RunDirectory:
    parameters: dict[str, object] = {
        "arms": list(arms),
        "world": SyntheticWorld(),
        "clock": clock(),
        "run_id": run_id,
        "kind": "development",
        "command": ("test",),
        "classifier": predeclaration.asserts_change,
        "scenarios": (SCENARIO,),
        "root": tmp_path,
        "contract": CONTRACT,
        "scorer": REHEARSAL,
    }
    parameters.update(overrides)
    return drive(**parameters)  # type: ignore[arg-type]


def outcome(directory: RunDirectory, key: str) -> str:
    return str(
        json.loads((directory.verdicts / f"{key}.json").read_text(encoding="utf-8"))["outcome"]
    )


# ------------------------------------------------------------------ DR01 is not SUR-1


def test_the_rehearsal_names_itself_and_never_the_benchmark() -> None:
    assert CONTRACT.identity.benchmark_id == "DR-REHEARSAL"
    assert CONTRACT.scenario_ids == (SCENARIO,)
    assert SCENARIO not in {f"C0{index}" for index in range(1, 10)}
    assert RUNS_ROOT != REPO / "docs" / "benchmarks" / "runs"
    assert "not a benchmark" in NOT_A_BENCHMARK.lower()


def test_the_rehearsal_spends_no_paid_inference_phrase() -> None:
    """The comparative run's authorisation phrase appears nowhere the rehearsal can reach it."""
    assert CONTRACT.ceilings.authorisation_phrase != PHRASE
    for path in sorted((REPO / "scripts" / "rehearsal").rglob("*.py")):
        assert PHRASE not in path.read_text(encoding="utf-8"), path
    assert PHRASE not in CONTRACT_PATH.read_text(encoding="utf-8")


def test_loading_the_rehearsal_asserts_the_frozen_contract_has_not_moved() -> None:
    assert rehearsal_contract.assert_benchmark_untouched() == PUBLISHED_MANIFEST_SHA


def test_the_rehearsal_registry_refuses_a_benchmark_scenario() -> None:
    """A rehearsal world asked to prepare C04 refuses rather than reaching the frozen registry."""
    assert rehearsal_program.lookup(SCENARIO).scenario_id == SCENARIO
    with pytest.raises(UnprogrammedScenarioError, match="not the dress rehearsal scenario"):
        rehearsal_program.lookup("C04")


def test_the_published_rehearsal_world_matches_the_program() -> None:
    assert rehearsal_program.differences() == ()


def test_a_scored_run_refuses_a_substituted_contract_or_scorer(tmp_path: Path) -> None:
    """The seam the rehearsal drives through is closed to ``kind='scored'`` outright."""
    for substitution in ({"contract": CONTRACT}, {"scorer": REHEARSAL}):
        with pytest.raises(UnsubstitutableScoredRunError, match="frozen contract"):
            run(tmp_path, stub("REHEARSAL-A"), kind="scored", **substitution)


def test_the_rehearsal_scorer_refuses_a_benchmark_scenario() -> None:
    from scripts.score_safe_useful_recovery import EvidenceBundle

    with pytest.raises(KeyError, match="dress rehearsal"):
        REHEARSAL.score(EvidenceBundle(run_id="r", scenario_id="C01", arm_token="tok-1"))


def test_the_rehearsal_scorer_reaches_no_arm() -> None:
    """The same import-surface assertion the frozen scorer is held to."""
    source = (REPO / "scripts" / "rehearsal" / "scorer.py").read_text(encoding="utf-8")
    for forbidden in ("promisepatch", "promise_graph", "scripts.sur1.adapters", "arm_map"):
        assert forbidden not in source


# -------------------------------------------------------------- resume, retry, write-once


def test_a_void_is_retried_exactly_once(tmp_path: Path) -> None:
    arm = stub("REHEARSAL-A", ArmAttempt(void_evidence()), ArmAttempt(void_evidence()))
    directory = run(tmp_path, arm)

    assert len(arm.requests) == 2, "a void is retried once and there is no third attempt"
    keys = sorted(directory.completed_attempts())
    assert [key.endswith("-a1") for key in keys].count(True) == 1
    assert [key.endswith("-a2") for key in keys].count(True) == 1
    assert {outcome(directory, key) for key in keys} == {"VOID"}


def test_a_void_that_clears_on_the_retry_stops_there(tmp_path: Path) -> None:
    arm = stub("REHEARSAL-A", ArmAttempt(void_evidence()), ArmAttempt(complete_evidence()))
    directory = run(tmp_path, arm)

    assert len(arm.requests) == 2
    scored = {outcome(directory, key) for key in directory.scored_attempts()}
    assert scored == {"VOID", "SAFE_AND_COMPLETE"}


def test_an_invalid_attempt_is_not_retried_as_a_void(tmp_path: Path) -> None:
    arm = stub("REHEARSAL-A", ArmAttempt(invalid_evidence()), ArmAttempt(complete_evidence()))
    directory = run(tmp_path, arm)

    assert len(arm.requests) == 1, "INVALID is a nonpass and is never retried"
    assert [outcome(directory, key) for key in directory.scored_attempts()] == ["INVALID"]


def test_a_budget_exhaustion_is_not_retried_and_never_becomes_a_void(tmp_path: Path) -> None:
    arm = stub("REHEARSAL-A", BudgetExhaustedError("tool_calls", 60, 61))
    directory = run(tmp_path, arm)

    assert len(arm.requests) == 1
    keys = sorted(directory.scored_attempts())
    assert [outcome(directory, key) for key in keys] == ["BUDGET_EXHAUSTED"]
    verdict = json.loads((directory.verdicts / f"{keys[0]}.json").read_text(encoding="utf-8"))
    assert verdict["decided_by"] == "driver"
    assert verdict["scorer_version"] == REHEARSAL.version
    assert sorted(verdict["safety"]) == sorted(DIMENSIONS)


def test_an_interrupted_run_resumes_without_buying_or_rewriting_a_finished_attempt(
    tmp_path: Path,
) -> None:
    """The half-finished shapes a crash leaves, and what a resume does with each.

    Two attempts are finished and one of them was never scored, which is exactly the state a
    process that died between the capture and the verdict leaves behind. The resume must re-score
    the second from its file, re-drive neither, and rewrite neither capture.
    """
    first = stub("REHEARSAL-A", ArmAttempt(complete_evidence()))
    second = stub("REHEARSAL-B", ArmAttempt(complete_evidence()))
    directory = run(tmp_path, first, second)

    captures = {
        path.name: path.read_text(encoding="utf-8") for path in directory.attempts.glob("*.json")
    }
    verdicts = sorted(directory.verdicts.glob("*.json"))
    assert len(captures) == 2 and len(verdicts) == 2
    orphaned = verdicts[1]
    orphaned_key = orphaned.stem
    orphaned.unlink()

    resumed_first = stub("REHEARSAL-A")
    resumed_second = stub("REHEARSAL-B")
    again = run(tmp_path, resumed_first, resumed_second)

    assert resumed_first.requests == [] and resumed_second.requests == []
    assert {
        path.name: path.read_text(encoding="utf-8") for path in again.attempts.glob("*.json")
    } == captures, "a resume rewrites no capture"
    assert orphaned_key in again.scored_attempts(), "the unscored attempt was scored from its file"


def test_a_capture_is_never_written_twice(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    write_once(path, {"one": 1})
    with pytest.raises(CaptureError, match="never edited"):
        write_once(path, {"one": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"one": 1}


def test_a_resumed_run_against_a_different_contract_is_refused(tmp_path: Path) -> None:
    """The identity check that stops two experiments landing in one directory."""
    from dataclasses import replace

    run(tmp_path, stub("REHEARSAL-A", ArmAttempt(complete_evidence())))
    moved = replace(CONTRACT, identity=replace(CONTRACT.identity, manifest_sha="0" * 64))
    with pytest.raises(CaptureError, match="different identities"):
        run(tmp_path, stub("REHEARSAL-A", ArmAttempt(complete_evidence())), contract=moved)


# ------------------------------------------------------------------------- the blinding


def test_no_verdict_carries_an_arm_name_and_the_join_puts_one_back(tmp_path: Path) -> None:
    """Blinding through verdict creation, and the later join that undoes it from a separate file."""
    arms = [stub(label, ArmAttempt(complete_evidence())) for label in LABELS]
    directory = run(tmp_path, *arms)

    tokens = set(directory.read_arm_map())
    for path in directory.verdicts.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        for label in LABELS:
            assert label not in text, f"{path.name} names an arm"
        assert json.loads(text)["arm_token"] in tokens

    for path in directory.attempts.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        for label in LABELS:
            assert label not in text, f"{path.name} names an arm"

    document = join(directory)
    assert sorted(attempt["arm"] for attempt in document["attempts"]) == sorted(LABELS)
    assert all(
        "latency_seconds" in attempt and "cost" in attempt for attempt in document["attempts"]
    )


def test_the_token_map_is_the_only_thing_that_names_an_arm(tmp_path: Path) -> None:
    directory = run(tmp_path, *[stub(label, ArmAttempt(complete_evidence())) for label in LABELS])
    named = {
        path.name
        for path in directory.path.rglob("*.json")
        if any(label in path.read_text(encoding="utf-8") for label in LABELS)
    }
    assert named == {"arm_map.json"}


def test_a_result_is_written_once(tmp_path: Path) -> None:
    directory = run(tmp_path, stub("REHEARSAL-A", ArmAttempt(complete_evidence())))
    join(directory)
    with pytest.raises(CaptureError, match="never edited"):
        join(directory)


# ------------------------------------------------------------------- the customer's door


class _Rows:
    """A :class:`DatabaseReader` stand-in that returns one outbox payload and reaches nothing."""

    url = "postgresql://stub/stub"

    def __init__(self, *payloads: dict[str, object]) -> None:
        self.payloads = payloads

    def rows(self, source: str, statement: str) -> list[tuple[object, ...]]:
        return [(json.dumps(payload),) for payload in self.payloads]


def sink(*payloads: dict[str, object]) -> CustomerLinkSink:
    from scripts.sur1.bindings.receivers import ChannelLedger
    from scripts.sur1.bindings.worldsink import LedgerWriter

    return CustomerLinkSink(
        api_base_url="http://127.0.0.1:0",
        database=_Rows(*payloads),  # type: ignore[arg-type]
        channel=ChannelLedger(),
        ledger=LedgerWriter(url="postgresql://stub/stub"),
    )


def test_the_reply_goes_to_the_harness_record_only_when_no_link_was_sent() -> None:
    """An arm that opened no approval request has no link, so there is no ingress to reach."""
    made = sink({"channel_address": "tg:1002", "approval_url": None})
    receipt = made.deliver_reply(
        message_id="m-1", channel="tg:1002", order="ord-b", text="YES", delivery=1, deliveries=1
    )

    assert "on-the-harness-transport" in receipt
    assert made.receipts[0]["door"] == "harness-channel-record"
    assert [message.text for message in made.channel.messages] == ["YES"]
    assert [message.direction for message in made.channel.messages] == ["INBOUND"]


def test_a_link_on_another_channel_is_not_used_for_this_one() -> None:
    made = sink({"channel_address": "tg:1005", "approval_url": "http://x/?approve=v1.aaa.bbb"})
    made.deliver_reply(
        message_id="m-1", channel="tg:1002", order="ord-b", text="YES", delivery=1, deliveries=1
    )
    assert made.receipts[0]["door"] == "harness-channel-record"


def test_a_reply_that_is_not_a_literal_decision_has_no_button_and_is_refused() -> None:
    made = sink({"channel_address": "tg:1002", "approval_url": "http://x/?approve=v1.aaa.bbb"})
    with pytest.raises(RehearsalIngressError, match="no button"):
        made.deliver_reply(
            message_id="m-1",
            channel="tg:1002",
            order="ord-b",
            text="sounds good to me",
            delivery=1,
            deliveries=1,
        )
    assert made.channel.messages == [], "a refused reply is not quietly recorded somewhere else"


def test_the_sink_carries_no_sender_channel_or_clock_to_the_endpoint() -> None:
    """The customer surface has no field for any of them, and neither does this caller."""
    source = (REPO / "scripts" / "rehearsal" / "world.py").read_text(encoding="utf-8")
    press = source.split("def _press(")[1].split("def _record(")[0]
    request = press.split("httpx2.post(")[1].split(")")[0]
    assert 'json={"answer": answer}' in request
    for forbidden in ("sender", "channel", "received_at", "text", "now"):
        assert forbidden not in request, f"the rehearsal sends {forbidden} to the customer endpoint"


def test_an_unnamed_failure_ends_one_attempt_and_not_the_run(tmp_path: Path) -> None:
    """A surface that refuses is a nonpass for that attempt; the later arms are still driven.

    Found by the rehearsal: the MCP ``clarify`` tool refused an argument name, the exception left
    the driver, and the run died after one attempt with two arms never driven and nothing written
    about them. ``HARNESS_FAILURE`` is the vocabulary the contract already has for it -- a
    nonpass, disclosed by name, never ``VOID`` and never retried.
    """
    from scripts.sur1.bindings.promisepatch import SurfaceError

    broken = stub("REHEARSAL-A", SurfaceError("clarify was refused: unknown argument"))
    after = stub("REHEARSAL-B", ArmAttempt(complete_evidence()))
    directory = run(tmp_path, broken, after)

    assert len(after.requests) == 1, "the arm after the failure was still driven"
    outcomes = sorted(outcome(directory, key) for key in directory.scored_attempts())
    assert outcomes == ["HARNESS_FAILURE", "SAFE_AND_COMPLETE"]
    assert len(broken.requests) == 1, "a harness failure is never retried"

    failed = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in directory.attempts.glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["attempt"]["status"] == "HARNESS_FAILURE"
    )
    assert "SurfaceError" in failed["attempt"]["note"], "the exception is disclosed, not swallowed"


def published_parameters(name: str) -> set[str]:
    """The parameter names one MCP tool actually publishes, read from the server's own source.

    The tools are defined inside the server factory, so they are not module attributes and no
    signature can be taken of them. Parsing the file is what keeps this assertion about the
    server rather than about a copy of it.
    """
    import ast
    import inspect

    from promisepatch.mcp import server as mcp_server

    tree = ast.parse(inspect.getsource(mcp_server))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return {argument.arg for argument in node.args.args}
    raise AssertionError(f"the MCP server publishes no {name} tool")


class _Recorder:
    """An MCP client that records what it was handed and reaches nothing."""

    binding_kind = "recorder"

    def __init__(self) -> None:
        self.sent: list[tuple[str, set[str]]] = []
        self.calls: list[str] = []

    def call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.sent.append((name, set(arguments)))
        self.calls.append(name)
        return {"case_id": "case-1"}


class _Workspace:
    """A worker's approval, recorded and not performed."""

    def __init__(self) -> None:
        self.approved: list[tuple[str, str]] = []

    def approve(self, *, case_id: str, plan_id: str) -> dict[str, object]:
        self.approved.append((case_id, plan_id))
        return {"recorded": True}


def test_the_worker_surface_calls_each_mcp_tool_by_the_name_it_publishes() -> None:
    """The argument names, pinned against the server's own signatures rather than remembered.

    ``report`` takes ``text`` and ``clarify`` takes ``answer``. The binding sent ``text`` to both,
    so arms B and C could never answer a clarification -- which is most of the nine scenarios.
    The tool refused the call, the exception left the driver, and the run died. Reading the
    server's own parameters is what stops that drifting again.
    """
    from scripts.sur1.bindings.promisepatch import LiveWorkerSurface

    tools = _Recorder()
    workspace = _Workspace()
    surface = LiveWorkerSurface(
        tools=tools,  # type: ignore[arg-type]
        workspace=workspace,  # type: ignore[arg-type]
        sleep=lambda _seconds: None,
    )

    surface.report_exception("the delivery did not arrive")
    surface.answer_clarification("just the raspberries")
    surface.confirm_plan("plan-7")
    surface.status()

    assert workspace.approved == [("case-1", "plan-7")], "a confirmation spends a worker approval"
    for name, arguments in tools.sent:
        published = published_parameters(name)
        assert arguments <= published, f"{name} was called with {sorted(arguments - published)}"
    assert {name for name, _ in tools.sent} == {"report", "clarify", "confirm", "status"}
