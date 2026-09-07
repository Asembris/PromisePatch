"""The acceptance story: dataset in, report out, and nothing reached.

This is the slice's own proof. The committed dataset is loaded, validated, projected into
model-safe inputs, answered from scripted payloads through the production acceptance path, and
scored -- and the run is shown to have called nothing, imported no AWS SDK, and invented no
latency, token count or cost.

The isolation assertions are deliberately blunt. It is not enough that a run happened to make
no network call; the module graph must contain no way for it to.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from evals.budget import EvalBudget
from evals.cases import EvalJob, EvalSplit
from evals.dataset import GoldDataset, load_dataset, validate_dataset
from evals.report import render
from evals.results import CaseResult, RunSummary
from evals.runner import ScriptedAnswers, run_offline
from evals.summary import build_summary, evaluate_gates, ledger_entry

from promisepatch.semantic import ApparentIntent


@pytest.fixture(scope="module")
def dataset() -> GoldDataset:
    return load_dataset()


@pytest.fixture(scope="module")
def answers() -> ScriptedAnswers:
    return ScriptedAnswers.from_file()


@pytest.fixture
async def summary(dataset: GoldDataset, answers: ScriptedAnswers) -> RunSummary:
    outcome = await run_offline(dataset, answers)
    return build_summary(dataset, outcome)


# ------------------------------------------------------------------------- the whole path


async def test_the_committed_baseline_passes_every_gate(summary: RunSummary) -> None:
    """Dataset, runner, metrics, thresholds and report agreeing end to end, with no model."""
    assert summary.mode == "replay"
    assert summary.provider == "fake"
    assert summary.cases == summary.dataset.cases
    assert summary.failed == 0
    assert summary.gate_status == "pass"
    assert all(gate.status != "fail" for gate in summary.gates)


async def test_the_run_identifies_what_it_measured(summary: RunSummary) -> None:
    """Dataset version and hash, prompt identity, commit, provider. The four a comparison needs."""
    assert summary.dataset.version
    assert len(summary.dataset.content_hash) == 64
    jobs = {entry["job"] for entry in summary.prompts}
    assert jobs == {"interpret_utterance", "classify_reply_intent"}
    for entry in summary.prompts:
        assert len(entry["system_hash"]) == 16
        assert len(entry["schema_hash"]) == 16


async def test_replay_invents_no_latency_no_tokens_and_no_cost(summary: RunSummary) -> None:
    """The absence rule. Nothing was measured, so nothing is reported as measured."""
    assert summary.model_id is None
    assert summary.operations["latency"] is None
    assert summary.cost["input_tokens"] is None
    assert summary.cost["output_tokens"] is None
    assert summary.cost["estimated_usd"] is None
    assert summary.cost["pricing"] == "unavailable"
    for result in summary.results:
        assert result.latency_ms is None
        assert result.input_tokens is None
        assert result.output_tokens is None
        assert result.estimated_usd is None


def test_no_threshold_is_still_awaiting_review() -> None:
    """Every gate this benchmark is judged by was agreed before a model was ever called.

    The evaluation slice shipped four of them marked ``PROPOSED``, because a number nobody has
    agreed to is a suggestion with a comparison operator rather than a gate. They were reviewed
    and approved on 2026-09-07, ahead of the first live call. The flag stays on the type for the
    next number that needs it; what this asserts is that no *current* gate is in that state.
    """
    from evals.thresholds import ALL_THRESHOLDS

    assert ALL_THRESHOLDS
    assert [threshold.name for threshold in ALL_THRESHOLDS if threshold.proposed] == []


async def test_the_report_says_not_available_rather_than_zero(summary: RunSummary) -> None:
    text = render(summary)
    assert "QUALITY" in text and "SAFETY" in text and "OPERATIONS" in text and "COST" in text
    assert "estimated spend                    unavailable" in text
    assert "no verified price is configured" in text
    assert "latency" in text and "n/a" in text


async def test_the_summary_is_plain_json(summary: RunSummary) -> None:
    """Machine-readable, no database, no framework types, nothing that needs this process."""
    payload = summary.as_payload()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["gate_status"] == "pass"
    assert len(round_tripped["results"]) == summary.cases
    assert round_tripped["results"][0]["case_id"]


async def test_a_case_result_carries_what_a_paired_comparison_would_need(
    summary: RunSummary,
) -> None:
    """Two runs over the same dataset join on ``case_id``; the columns to difference are here."""
    assert summary.results
    for field in ("case_id", "provider", "model_id", "attempts", "latency_ms", "estimated_usd"):
        assert field in CaseResult.model_fields


# ------------------------------------------------------------------------ the boundary


async def test_no_provider_is_called_for_a_sentence_the_lexicon_reads(
    dataset: GoldDataset, answers: ScriptedAnswers
) -> None:
    """Production never pays to understand a sentence it already understands. Nor does this."""
    unasked = tuple(case for case in dataset.worker if not case.asked)
    assert unasked
    narrowed = GoldDataset(
        version=dataset.version,
        worker=unasked,
        customer=(),
        provenance=dataset.provenance,
    )
    outcome = await run_offline(narrowed, answers)
    assert outcome.guard.spend.calls == 0
    assert all(score.case_passed for score in outcome.worker_scores)


async def test_the_call_count_is_the_asked_cases_and_the_attempts_exceed_it(
    dataset: GoldDataset, answers: ScriptedAnswers
) -> None:
    """One corrective retry in the baseline, so attempts and cases are visibly different."""
    outcome = await run_offline(dataset, answers)
    asked = sum(case.asked for case in dataset.worker) + len(dataset.customer)
    assert outcome.guard.spend.calls == asked
    assert outcome.guard.spend.attempts > outcome.guard.spend.calls


async def test_a_call_cap_stops_a_run_before_it_finishes(
    dataset: GoldDataset, answers: ScriptedAnswers
) -> None:
    """The guard is on the offline path too, so it cannot rot before the run it is for."""
    from evals.budget import BudgetExhaustedError

    with pytest.raises(BudgetExhaustedError):
        await run_offline(dataset, answers, budget=EvalBudget(max_calls=3))


async def test_a_split_can_be_scored_on_its_own(
    dataset: GoldDataset, answers: ScriptedAnswers
) -> None:
    """Holdout results are read once; running them apart from development is how."""
    holdout = dataset.split([EvalSplit.HOLDOUT])
    assert holdout.cases
    assert all(case.split is EvalSplit.HOLDOUT for case in holdout.cases)
    outcome = await run_offline(holdout, answers)
    assert len(outcome.results) == len(holdout.cases)


async def test_a_wrong_scripted_answer_fails_the_case_and_the_gate(
    dataset: GoldDataset,
) -> None:
    """The failing half of the proof, on the reading this slice exists because of.

    "Strawberries work" read as UNCLEAR is the miss reported from a Nova 2 Lite development run.
    Scored here it costs the terse-assent cluster its recall and fails that gate, which is the
    behaviour a benchmark needs for the finding to be visible rather than averaged away.
    """
    customer_only = GoldDataset(
        version=dataset.version,
        worker=(),
        customer=tuple(case for case in dataset.customer if "terse_assent" in case.tags),
        provenance=dataset.provenance,
    )
    wrong = ScriptedAnswers(
        {
            case.id: [{"apparent_intent": ApparentIntent.UNCLEAR.value}]
            for case in customer_only.customer
        }
    )
    outcome = await run_offline(customer_only, wrong)
    summary = build_summary(dataset, outcome)

    assert summary.failed > 0
    assert summary.gate_status == "fail"
    terse = next(gate for gate in summary.gates if "terse-assent" in gate.name)
    assert terse.status == "fail"
    assert all(result.passed or "UNCLEAR" in result.reason for result in summary.results)


async def test_a_provider_outage_is_reported_and_is_not_a_safety_finding(
    dataset: GoldDataset,
) -> None:
    """A model nobody could reach read nothing. That is an operational fact, not a breach."""
    from promisepatch.semantic import SemanticTimeoutError

    one = GoldDataset(
        version=dataset.version,
        worker=(),
        customer=dataset.customer[:1],
        provenance=dataset.provenance,
    )
    outcome = await run_offline(
        one, ScriptedAnswers({one.customer[0].id: [SemanticTimeoutError("no route")]})
    )
    summary = build_summary(dataset, outcome)
    assert summary.results[0].error_category == "SemanticTimeoutError"
    assert not summary.results[0].passed
    assert summary.safety["customer_authority_violations"] == 0


async def test_a_gate_over_a_metric_the_run_did_not_produce_reports_not_measured() -> None:
    """A silent pass would be the worst of the three outcomes, so it is not one of them."""
    gates = evaluate_gates({"worker": {}, "customer": {}})
    assert gates
    assert all(gate.status == "not-measured" for gate in gates)


# --------------------------------------------------------------------------- isolation


def test_the_evaluation_package_pulls_in_no_aws_sdk() -> None:
    """Not "it did not call AWS" but "it cannot": no SDK is loaded by importing any of it.

    Run in a fresh interpreter on purpose. Asserting against this process would be asserting
    about whatever else the session imported -- DeepEval itself pulls in botocore, which says
    nothing about whether an offline run could reach Bedrock.
    """
    probe = (
        "import sys;"
        "import evals.dataset, evals.report, evals.runner, evals.summary, evals.budget;"
        "loaded = [name for name in ('boto3', 'botocore',"
        " 'promisepatch.integrations.bedrock', 'promisepatch.integrations')"
        " if name in sys.modules];"
        "print(','.join(loaded))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert completed.stdout.strip() == ""


async def test_an_aws_configured_environment_changes_nothing(
    dataset: GoldDataset, answers: ScriptedAnswers, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A machine set up for Bedrock still spends nothing by running an evaluation.

    ``PP_LLM_PROVIDER=bedrock`` in a developer's ``.env`` is the realistic way an eval run would
    become an expensive surprise: application settings say "use the model", so a harness that
    consulted them would. This one does not consult them at all. The provider it answers from is
    the deterministic fake, chosen in code, and there is no branch reachable from here that
    reads ``Settings.llm_provider``.
    """
    monkeypatch.setenv("PP_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("PP_BEDROCK_MODEL_ID", "us.amazon.nova-lite-v1:0")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_PROFILE", "promisepatch")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLENOTREAL")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "not-a-real-secret")

    outcome = await run_offline(dataset, answers)

    assert outcome.provider == "fake"
    assert outcome.model_id is None
    assert build_summary(dataset, outcome).gate_status == "pass"
    assert "boto3" not in sys.modules


def test_the_core_of_the_package_works_without_deepeval() -> None:
    """The runner, the metrics and the dataset never import the framework."""
    for name in (
        "evals.dataset",
        "evals.metrics.worker",
        "evals.metrics.customer",
        "evals.runner",
        "evals.summary",
        "evals.report",
        "evals.budget",
    ):
        module = sys.modules.get(name)
        assert module is None or "deepeval" not in getattr(module, "__dict__", {})


async def test_the_ledger_line_for_a_replay_run_prices_nothing(summary: RunSummary) -> None:
    entry = ledger_entry(summary)
    assert entry.mode == "replay"
    assert entry.provider == "fake"
    assert entry.model_id is None
    assert entry.estimated_usd is None
    assert entry.pricing_snapshot is None
    assert entry.calls > 0
    assert entry.dataset_hash == summary.dataset.content_hash
    assert set(entry.jobs) == {job.value for job in EvalJob}


def test_the_dataset_used_by_the_run_is_the_validated_one(dataset: GoldDataset) -> None:
    assert validate_dataset(dataset) == ()
