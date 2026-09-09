"""The explanation gate's live composition root, proved to spend nothing from a test.

This directory's other suite exists because a test once bought inference by accident. The
command under test here is newer and can spend against two providers rather than one, so every
property that stopped that accident is restated for it: ``--live`` alone buys nothing, an
authorisation for one scope cannot buy another, a development phrase cannot open the holdout,
and the real builders refuse inside pytest whatever they were handed.

Every answer in this file comes from the offline scripted factory the gate is already exercised
with, or from a scripted judge, both passed in as parameters. ``conftest.py`` refuses any
connection that leaves this machine, so "nothing was called" is enforced rather than asserted.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
import scripts.run_explanation_eval as command
from evals.authorisation import (
    SpendNotAuthorisedError,
    SpendScope,
    authorise,
    required_phrase,
)
from evals.budget import NEMOTRON_3_SUPER, BillingMode, ledger_totals
from evals.cases import EvalSplit
from evals.explanation_dataset import load_explanation_dataset
from evals.explanation_judge import (
    RUBRIC,
    JudgeProviderError,
    ScriptedJudge,
    StructuredJudge,
    build_judge_request,
)
from evals.explanation_results import JudgeOutcome
from evals.explanation_runner import (
    LIVE_MODE,
    ScriptedExplanations,
    scripted_provider,
    scripted_verdicts,
)
from evals.explanation_store import ExplanationResultStore, read_run

from promisepatch.config import Settings

from .conftest import OFF_MACHINE_CONNECTIONS

ROOT = Path(__file__).resolve().parents[2]

GENERATION = required_phrase(SpendScope.P4_8_NOVA_DEVELOPMENT_GENERATION)
JUDGING = required_phrase(SpendScope.P4_8_NEMOTRON_DEVELOPMENT_JUDGING)
HOLDOUT = required_phrase(SpendScope.P4_8_EXPLANATION_HOLDOUT)

CREDENTIAL_LIKE_ENVIRONMENT = {
    "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
    "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "AWS_PROFILE": "promisepatch",
    "AWS_REGION": "us-east-1",
    "PP_LLM_PROVIDER": "bedrock",
    "NVIDIA_API_KEY": "nvapi-never-sent",
}
"""Everything a machine that could really spend would have. The claim under test is not that
CI happens to lack credentials -- that is luck -- but that a credentialed process still cannot
buy inference from a test."""


@pytest.fixture
def credentialed(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in CREDENTIAL_LIKE_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the command's whole artifact surface at a temporary directory."""
    results = tmp_path / "eval-results"
    results.mkdir()
    monkeypatch.setattr(command, "RESULTS_DIR", results)
    monkeypatch.setattr(command, "LEDGER", results / "explanation-cost-ledger.jsonl")
    return results


def namespace_for(argv: Sequence[str]) -> argparse.Namespace:
    return command.build_parser().parse_args(list(argv))


def generation_argv(
    results: Path, *, phrase: str = GENERATION, split: str = "development"
) -> list[str]:
    return [
        "generate",
        "--live",
        "--split",
        split,
        "--authorise-paid-inference",
        phrase,
        "--results",
        str(results),
    ]


def offline_generation(results: Path, **kwargs: str) -> argparse.Namespace:
    """A generation invocation whose provider is the scripted one, handed in as a parameter."""
    namespace = namespace_for(generation_argv(results, **kwargs))
    namespace.factory = scripted_provider(ScriptedExplanations.from_file())
    return namespace


# =====================================================================================
# 1. --live alone buys nothing
# =====================================================================================


def test_neither_pass_defaults_an_authorisation() -> None:
    for argv in (
        ["generate", "--split", "development"],
        ["judge", "--split", "development"],
    ):
        namespace = namespace_for(argv)
        assert namespace.live is False
        assert namespace.authorise_paid_inference is None


def test_live_alone_is_refused_before_any_provider_exists(
    credentialed: None, sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = command.main(["generate", "--live", "--split", "development"])
    assert code == 2
    assert "does not authorise a charge" in capsys.readouterr().err
    assert OFF_MACHINE_CONNECTIONS == []


def test_an_authorisation_without_live_is_an_incoherent_command(
    credentialed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    code = command.main(
        ["generate", "--split", "development", "--authorise-paid-inference", GENERATION]
    )
    assert code == 2
    assert "without --live" in capsys.readouterr().err


def test_a_pass_that_reaches_a_provider_refuses_without_live(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert command.main(["generate", "--split", "development"]) == 2
    assert "needs --live" in capsys.readouterr().err


def test_importing_the_composition_root_loads_no_vendor_sdk() -> None:
    """A fresh interpreter: no SDK and no integration package is even in the module graph."""
    probe = (
        "import sys, scripts.run_explanation_eval;"
        "print(','.join(n for n in ('boto3', 'botocore', 'openai',"
        " 'promisepatch.integrations.bedrock', 'promisepatch.integrations.nvidia',"
        " 'promisepatch.integrations.semantic_provider') if n in sys.modules))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, cwd=ROOT
    )
    assert completed.stdout.strip() == ""


# =====================================================================================
# 2. one scope never pays for another
# =====================================================================================


@pytest.mark.parametrize("phrase", [JUDGING, HOLDOUT])
def test_a_phrase_for_one_scope_cannot_buy_generation(
    credentialed: None,
    sandbox: Path,
    capsys: pytest.CaptureFixture[str],
    phrase: str,
) -> None:
    results = sandbox / "run.jsonl"
    code = command.main(generation_argv(results, phrase=phrase))
    assert code == 2
    assert "does not name" in capsys.readouterr().err
    assert not results.exists()


async def test_a_generation_phrase_cannot_buy_judging(credentialed: None, sandbox: Path) -> None:
    """Authorising the model under test to speak is not authorising a judge to grade it."""
    results = sandbox / "run.jsonl"
    await command.run_generation(offline_generation(results))

    namespace = namespace_for(
        [
            "judge",
            "--live",
            "--split",
            "development",
            "--authorise-paid-inference",
            GENERATION,
            "--results",
            str(results),
        ]
    )
    namespace.judge = ScriptedJudge(scripted_verdicts())
    with pytest.raises(SpendNotAuthorisedError) as refused:
        await command.run_judging(namespace)
    assert "does not name" in str(refused.value)

    _header, _generations, judgements = read_run(results)
    assert judgements == ()


def test_a_development_phrase_cannot_open_the_holdout(
    credentialed: None, sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one failure in this gate that cannot be undone by re-running."""
    results = sandbox / "run.jsonl"
    code = command.main(generation_argv(results, split="holdout"))
    assert code == 2
    assert "does not name" in capsys.readouterr().err
    assert not results.exists()
    assert OFF_MACHINE_CONNECTIONS == []


def test_the_holdout_maps_to_its_own_scope_in_both_passes() -> None:
    assert command.GENERATION_SCOPES[EvalSplit.HOLDOUT] is SpendScope.P4_8_EXPLANATION_HOLDOUT
    assert command.JUDGING_SCOPES[EvalSplit.HOLDOUT] is SpendScope.P4_8_EXPLANATION_HOLDOUT


# =====================================================================================
# 3. the test-process interlock
# =====================================================================================


def test_the_real_generation_factory_refuses_inside_pytest(credentialed: None) -> None:
    """Called directly, with a valid authorisation, in a fully credentialed process."""
    granted = authorise(GENERATION, SpendScope.P4_8_NOVA_DEVELOPMENT_GENERATION)
    with pytest.raises(SpendNotAuthorisedError) as refused:
        command.bedrock_factory(Settings(), granted)
    assert "a test process may not construct a paid provider" in str(refused.value)


async def test_a_fully_authorised_judge_run_still_cannot_build_the_real_judge(
    credentialed: None, sandbox: Path
) -> None:
    """Both guards, in the order a real invocation meets them, with a key in the environment."""
    results = sandbox / "run.jsonl"
    await command.run_generation(offline_generation(results))

    namespace = namespace_for(
        [
            "judge",
            "--live",
            "--split",
            "development",
            "--authorise-paid-inference",
            JUDGING,
            "--results",
            str(results),
        ]
    )
    namespace.judge = None
    with pytest.raises(SpendNotAuthorisedError):
        await command.run_judging(namespace)
    assert OFF_MACHINE_CONNECTIONS == []


# =====================================================================================
# 4. an authorised pass, against providers handed in
# =====================================================================================


async def test_an_authorised_generation_writes_every_passage_down_as_it_arrives(
    sandbox: Path,
) -> None:
    results = sandbox / "run.jsonl"
    assert await command.run_generation(offline_generation(results)) == 0

    header, generations, judgements = read_run(results)
    development = load_explanation_dataset().split([EvalSplit.DEVELOPMENT])
    assert len(generations) == len(development.cases)
    assert judgements == ()
    assert header.splits == (EvalSplit.DEVELOPMENT.value,)
    assert all(result.split is EvalSplit.DEVELOPMENT for result in generations)
    assert all(result.usage.latency_ms is not None for result in generations)


async def test_a_second_run_over_the_same_file_asks_for_nothing_again(sandbox: Path) -> None:
    """The resume property, as a count. A passage already paid for is never bought twice."""
    results = sandbox / "run.jsonl"
    await command.run_generation(offline_generation(results))
    _header, first, _ = read_run(results)

    refusing = namespace_for(generation_argv(results))

    def must_not_be_reached(model_input: object) -> object:
        raise AssertionError("a completed case was asked again")

    refusing.factory = must_not_be_reached
    assert await command.run_generation(refusing) == 0
    _header, second, _ = read_run(results)
    assert [item.case_id for item in second] == [item.case_id for item in first]


async def test_judging_reads_passages_from_the_file_and_never_reaches_nova(
    sandbox: Path,
) -> None:
    results = sandbox / "run.jsonl"
    await command.run_generation(offline_generation(results))

    namespace = namespace_for(
        [
            "judge",
            "--live",
            "--split",
            "development",
            "--authorise-paid-inference",
            JUDGING,
            "--results",
            str(results),
        ]
    )
    judge = ScriptedJudge(scripted_verdicts())
    namespace.judge = judge
    assert await command.run_judging(namespace) == 0

    _header, generations, judgements = read_run(results)
    accepted = [result for result in generations if result.accepted]
    assert len(judgements) == len(accepted)
    assert len(judge.seen) == len(accepted)
    assert {item.case_id for item in judgements} == {item.case_id for item in accepted}


async def test_one_logical_judge_call_per_accepted_passage_and_no_more(sandbox: Path) -> None:
    """The fan-out prohibition, as a number the framework cannot change."""
    results = sandbox / "run.jsonl"
    await command.run_generation(offline_generation(results))
    _header, generations, _ = read_run(results)
    accepted = [result for result in generations if result.accepted]

    namespace = namespace_for(
        [
            "judge",
            "--live",
            "--split",
            "development",
            "--authorise-paid-inference",
            JUDGING,
            "--results",
            str(results),
        ]
    )
    judge = ScriptedJudge(scripted_verdicts())
    namespace.judge = judge
    await command.run_judging(namespace)

    _header, _generations, judgements = read_run(results)
    assert sum(item.usage.logical_calls for item in judgements) == len(accepted)
    assert len(judge.seen) == len(set(judge.seen))


async def test_a_second_judge_run_rejudges_nothing(sandbox: Path) -> None:
    results = sandbox / "run.jsonl"
    await command.run_generation(offline_generation(results))
    for _ in range(2):
        namespace = namespace_for(
            [
                "judge",
                "--live",
                "--split",
                "development",
                "--authorise-paid-inference",
                JUDGING,
                "--results",
                str(results),
            ]
        )
        namespace.judge = ScriptedJudge(scripted_verdicts())
        assert await command.run_judging(namespace) == 0

    _header, generations, judgements = read_run(results)
    accepted = [result for result in generations if result.accepted]
    assert len(judgements) == len(accepted)


# =====================================================================================
# 5. what the judge is shown, and what it may answer
# =====================================================================================


def test_the_judge_request_carries_the_rubric_the_facts_and_one_passage() -> None:
    """Leakage, checked in the bytes rather than in the intention."""
    from evals.explanation_cases import to_model_input

    case = next(
        item for item in load_explanation_dataset().cases if item.split is EvalSplit.DEVELOPMENT
    )
    request = build_judge_request(
        case.id, case.family, to_model_input(case).request, "a passage about the outcome"
    )
    payload = command.build_judge_chat_request(request, model_id="m", correction=None)

    assert payload["messages"][0] == {"role": "system", "content": RUBRIC}
    assert payload["tool_choice"]["function"]["name"] == command.VERDICT_TOOL_NAME
    serialised = str(payload)
    assert case.split.value not in serialised
    assert "holdout" not in serialised
    for tag in case.tags:
        assert tag.value not in serialised


def test_a_correction_is_a_second_turn_rather_than_an_edited_question() -> None:
    from evals.explanation_cases import to_model_input

    case = load_explanation_dataset().cases[0]
    request = build_judge_request(case.id, case.family, to_model_input(case).request, "a passage")
    first = command.build_judge_chat_request(request, model_id="m", correction=None)
    corrected = command.build_judge_chat_request(request, model_id="m", correction="try again")

    assert corrected["messages"][:2] == first["messages"]
    assert corrected["messages"][-1] == {"role": "user", "content": "try again"}


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"tool_calls": []}}]},
        {"choices": [{"message": {"content": "I think it is fine."}}]},
        {"choices": [{"message": {"tool_calls": [{"function": {"name": "other"}}]}}]},
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"function": {"name": command.VERDICT_TOOL_NAME, "arguments": "{"}}
                        ]
                    }
                }
            ]
        },
    ],
)
def test_an_answer_that_is_not_a_verdict_yields_nothing_to_believe(response: object) -> None:
    """A model that declined the shape of the question produced no verdict, not a partial one."""
    assert command.extract_verdict_arguments(response) is None  # type: ignore[arg-type]


async def test_a_refused_shape_is_a_contract_failure_rather_than_an_outage() -> None:
    """The distinction the judge stop-rule depends on: a bad answer is not an outage.

    Three outages stop judging. If a model writing prose were counted as one, a model that
    simply answered badly could end the subjective pass and be reported as an unreachable
    provider instead of as what it was.
    """

    class ProseOnly:
        name = "prose-only"
        model_id: str | None = None

        def __init__(self) -> None:
            self.attempts = 0

        async def invoke(self, request: object, *, correction: str | None) -> object:
            self.attempts += 1
            from evals.explanation_judge import JudgeAttempt

            return JudgeAttempt(payload=None)

    from evals.explanation_cases import to_model_input

    case = load_explanation_dataset().cases[0]
    request = build_judge_request(case.id, case.family, to_model_input(case).request, "a passage")
    provider = ProseOnly()
    judgement = await StructuredJudge(provider).judge(request)  # type: ignore[arg-type]

    assert judgement.outcome is JudgeOutcome.JUDGE_RESULT_INVALID
    assert judgement.verdict is None
    assert provider.attempts == 2
    assert judgement.usage.logical_calls == 1


def test_a_transport_failure_is_the_only_thing_reported_as_an_outage() -> None:
    class Broken:
        def create(self, **kwargs: object) -> object:
            raise TimeoutError("the socket gave up")

    judge = command.NvidiaJudge(open_transport=lambda: Broken(), model_id="m")
    with pytest.raises(JudgeProviderError) as failure:
        judge._call(Broken(), {})
    assert "TimeoutError" in str(failure.value)
    assert "socket gave up" not in str(failure.value)


# =====================================================================================
# 6. the zero-call operations
# =====================================================================================


async def test_a_report_and_a_review_are_rebuilt_from_the_file_alone(
    sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The property that makes a lost terminal cheap and a manual review free."""
    results = sandbox / "run.jsonl"
    await command.run_generation(offline_generation(results))
    namespace = namespace_for(
        [
            "judge",
            "--live",
            "--split",
            "development",
            "--authorise-paid-inference",
            JUDGING,
            "--results",
            str(results),
        ]
    )
    namespace.judge = ScriptedJudge(scripted_verdicts())
    await command.run_judging(namespace)
    capsys.readouterr()
    _header, generations, _judgements = read_run(results)

    command.run_report(namespace_for(["report", "--results", str(results)]))
    report = capsys.readouterr().out
    assert "STRUCTURAL GATES" in report
    assert "LATENCY" in report

    command.run_review(namespace_for(["review", "--results", str(results), "--json"]))
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == len(generations)
    assert all(row["manual_disposition"] is None for row in rows)
    assert OFF_MACHINE_CONNECTIONS == []


def test_the_plan_needs_no_authorisation_and_names_the_ones_it_would(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert command.main(["plan", "--split", "development"]) == 0
    printed = capsys.readouterr().out
    assert GENERATION in printed
    assert JUDGING in printed
    assert "model calls                  0" in printed
    assert "SEALED" in printed


def test_percentiles_over_nothing_are_absent_rather_than_zero() -> None:
    assert command.percentile([], 0.5) is None
    assert command.percentile([5], 0.95) == 5
    assert command.percentile([1, 2, 3, 4], 0.5) == 3


# =====================================================================================
# 7. the file this run may not continue
# =====================================================================================


async def test_a_run_whose_dataset_moved_is_not_judged(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = sandbox / "run.jsonl"
    await command.run_generation(offline_generation(results))

    header, generations, judgements = read_run(results)
    moved = replace(header, dataset_hash="0" * 64)
    monkeypatch.setattr(command, "read_run", lambda path: (moved, generations, judgements))

    namespace = namespace_for(
        [
            "judge",
            "--live",
            "--split",
            "development",
            "--authorise-paid-inference",
            JUDGING,
            "--results",
            str(results),
        ]
    )
    namespace.judge = ScriptedJudge(scripted_verdicts())
    with pytest.raises(command.ExplanationRunRefusedError) as refused:
        await command.run_judging(namespace)
    assert "has moved" in str(refused.value)


async def test_a_passage_written_under_another_prompt_is_not_rejudged(sandbox: Path) -> None:
    results = sandbox / "run.jsonl"
    await command.run_generation(offline_generation(results))
    _header, generations, _ = read_run(results)

    stale = [
        result.model_copy(
            update={"identity": result.identity.model_copy(update={"prompt_system_hash": "moved"})}
        )
        for result in generations
    ]
    with pytest.raises(command.ExplanationRunRefusedError) as refused:
        command.refuse_a_moved_request(stale)
    assert "has moved" in str(refused.value)


def test_no_fixture_here_authorises_spending() -> None:
    """Absence, asserted structurally. An autouse grant would rebuild the accident one layer down.

    Read off the fixtures themselves rather than out of the file's text: a source-grep for the
    word would be satisfied or defeated by this very sentence, which is not a property of
    anything.
    """
    declared = [
        (name, marker)
        for name, value in globals().items()
        if (marker := getattr(value, "_fixture_function_marker", None)) is not None
    ]
    assert declared, "this test would pass by checking nothing if the fixtures moved"
    for name, marker in declared:
        assert marker.autouse is False, name


def test_the_off_machine_connection_count_is_zero() -> None:
    """The claim this whole file rests on, as a number rather than an intention."""
    assert OFF_MACHINE_CONNECTIONS == []


# =====================================================================================
# 8. every call that happened is in the ledger, exactly once
# =====================================================================================


class CountingProvider:
    """The scripted provider with every call it actually makes counted at the seam."""

    def __init__(self, inner: object, calls: list[str]) -> None:
        self._inner = inner
        self._calls = calls
        self.name = getattr(inner, "name", "fake")

    async def run(self, request: object) -> object:
        self._calls.append(type(request).__name__)
        return await self._inner.run(request)  # type: ignore[attr-defined]


def counting_factory(calls: list[str]) -> object:
    inner = scripted_provider(ScriptedExplanations.from_file())

    def build(model_input: object) -> object:
        return CountingProvider(inner(model_input), calls)  # type: ignore[arg-type]

    return build


def canary_generation(results: Path, calls: list[str], *extra: str) -> argparse.Namespace:
    namespace = namespace_for(generation_argv(results) + list(extra))
    namespace.factory = counting_factory(calls)
    return namespace


async def test_a_canary_call_the_ceiling_stopped_after_is_still_in_the_ledger(
    sandbox: Path,
) -> None:
    """One call was bought, the next was refused, and the ledger must say one -- not nothing.

    The pass ends on ``BudgetExhaustedError`` after the first call, which is after the passage
    was written to the run file. A ledger line written only on the happy path would leave a
    paid call unrecorded and hand the resumed run one call more than the ceiling allows.
    """
    results = sandbox / "run.jsonl"
    calls: list[str] = []
    assert await command.run_generation(canary_generation(results, calls, "--max-calls", "1")) == 1

    _header, generations, _ = read_run(results)
    assert len(generations) == 1
    assert calls == ["VerbaliseRequest"]

    lines = command.LEDGER.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["calls"] == 1
    assert entry["attempts"] == 1
    assert entry["run_id"] == _header.run_id


async def test_a_resumed_run_charges_its_own_calls_and_never_the_canary_again(
    sandbox: Path,
) -> None:
    """Two passes, two ledger lines, and the total is exactly the calls that happened."""
    results = sandbox / "run.jsonl"
    calls: list[str] = []
    await command.run_generation(canary_generation(results, calls, "--max-calls", "1"))
    assert await command.run_generation(canary_generation(results, calls)) == 0

    header, generations, _ = read_run(results)
    development = load_explanation_dataset().split([EvalSplit.DEVELOPMENT])
    assert len(generations) == len(development.cases)
    assert len({item.case_id for item in generations}) == len(generations)
    assert len(calls) == len(development.cases)

    totals = ledger_totals(
        command.LEDGER, mode=LIVE_MODE, provider=header.provider, model_id=header.model_id
    )
    assert totals.runs == 2
    assert totals.calls == len(development.cases)
    assert totals.attempts == sum(result.usage.provider_attempts for result in generations)
    assert totals.attempts >= totals.calls


async def test_a_ceiling_that_refuses_the_first_call_writes_no_ledger_line(
    sandbox: Path,
) -> None:
    """Nothing was bought, so nothing is recorded. A measured nought is not a spend."""
    results = sandbox / "run.jsonl"
    calls: list[str] = []
    assert await command.run_generation(canary_generation(results, calls, "--max-calls", "0")) == 1
    _header, generations, _ = read_run(results)
    assert generations == ()
    assert calls == []
    assert not command.LEDGER.exists()


async def test_a_provider_fault_mid_run_still_leaves_the_calls_made_in_the_ledger(
    sandbox: Path,
) -> None:
    """The invariant holds for any exit, not only the ceiling's: calls made are calls recorded."""
    results = sandbox / "run.jsonl"
    calls: list[str] = []
    inner = counting_factory(calls)

    def faulting(model_input: object) -> object:
        if len(calls) >= 2:
            raise RuntimeError("the transport fell over")
        return inner(model_input)  # type: ignore[operator]

    namespace = namespace_for(generation_argv(results))
    namespace.factory = faulting
    with pytest.raises(RuntimeError):
        await command.run_generation(namespace)

    entry = json.loads(command.LEDGER.read_text(encoding="utf-8").splitlines()[0])
    assert entry["calls"] == len(calls) == 2


# =====================================================================================
# 9. the judge's billing mode is the repository's own value
# =====================================================================================


async def test_the_judge_billing_mode_is_rendered_from_the_evaluation_foundation(
    sandbox: Path,
) -> None:
    results = sandbox / "run.jsonl"
    await command.run_generation(offline_generation(results))
    header, _generations, _ = read_run(results)
    store = ExplanationResultStore(results, header)

    printed = command.render_judging(store, None, 21)
    assert f"billing mode       {NEMOTRON_3_SUPER.mode.value}" in printed
    assert NEMOTRON_3_SUPER.mode is BillingMode.FREE_HOSTED_TRIAL
    assert "prototype" not in printed
    assert "$0" not in printed


# =====================================================================================
# 10. every record names the frozen dataset, never the selection it was generated from
# =====================================================================================


async def test_every_record_carries_the_frozen_dataset_hash_across_a_resumed_run(
    sandbox: Path,
) -> None:
    """A canary of one case and a resume of twenty are one dataset, and every row says so."""
    results = sandbox / "run.jsonl"
    calls: list[str] = []
    await command.run_generation(canary_generation(results, calls, "--max-calls", "1"))
    await command.run_generation(canary_generation(results, calls))

    namespace = namespace_for(
        [
            "judge",
            "--live",
            "--split",
            "development",
            "--authorise-paid-inference",
            JUDGING,
            "--results",
            str(results),
        ]
    )
    namespace.judge = ScriptedJudge(scripted_verdicts())
    await command.run_judging(namespace)

    frozen = load_explanation_dataset().content_hash
    header, generations, judgements = read_run(results)
    assert header.dataset_hash == frozen
    assert {result.identity.dataset_hash for result in generations} == {frozen}
    assert {result.identity.dataset_hash for result in judgements} == {frozen}
