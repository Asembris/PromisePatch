"""The composition root's refusals, proved without an AWS account and without spending.

This file tests the one module in the repository that can spend money, and it tests the part
that decides *whether* to. Every case here ends with nothing having been called: either the
command refused, or it stopped at the preflight, or it rebuilt a report from answers somebody
already paid for.

The two properties worth stating plainly, because they are the ones a tired operator relies on:

* going live takes three explicit flags and reads no environment variable to decide;
* a model with no verified price cannot be benchmarked at all -- which is what stands between
  ``PP_BEDROCK_MODEL_ID``'s Claude default and an unintended bill.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from evals.budget import BudgetGuard, EvalBudget, price_for
from evals.cases import EvalSplit
from evals.dataset import GoldDataset, load_dataset
from evals.runner import LIVE_MODE, ScriptedAnswers, new_run_id, run_cases, scripted_provider
from evals.store import ResultStore, RunHeader
from scripts.run_semantic_benchmark import (
    GLOBAL_CEILING,
    MAX_PROVIDER_FAILURES,
    BenchmarkRefusedError,
    build_parser,
    main,
)

NOVA = "us.amazon.nova-2-lite-v1:0"
HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
UNPRICED = "example.unbenchmarked-model-v1:0"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def dataset() -> GoldDataset:
    return load_dataset()


# ------------------------------------------------------------------ the live opt-in


def test_going_live_needs_the_provider_and_the_model_named(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Three flags, none defaulted. A run that inherited its model measures one nobody chose."""
    assert main(["--live", "--split", "development"]) == 2
    assert "requires --provider and --model" in capsys.readouterr().err


def test_a_run_without_a_split_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    """One split per run, so development and holdout are never blended into one number."""
    assert main(["--model", NOVA]) == 2
    assert "--split is required" in capsys.readouterr().err


def test_a_dry_run_prints_the_preflight_and_constructs_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without --live the command is a description of what would happen, and costs nothing."""
    assert main(["--split", "development", "--model", NOVA]) == 0
    printed = capsys.readouterr().out
    assert "PREFLIGHT" in printed
    assert "DRY RUN. No provider was constructed and nothing was spent." in printed
    assert NOVA in printed
    assert "THRESHOLD POLICY" in printed


def test_the_preflight_names_everything_a_later_reader_would_need(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Identity is fixed before the first call, not reconstructed from a terminal buffer."""
    main(["--split", "development", "--model", NOVA])
    printed = capsys.readouterr().out
    dataset = load_dataset()
    for expected in (
        dataset.content_hash,
        dataset.version,
        "us-east-1",
        "pricing snapshot",
        "model-eligible calls",
        "never asked (0 calls)",
        "max estimated spend",
        "PROJECTION",
    ):
        assert expected in printed


def test_an_aws_ready_environment_does_not_make_a_dry_run_live(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing here reads PP_LLM_PROVIDER to decide. The flag decides, and only the flag.

    This is the realistic way a benchmark becomes an accident: a developer's ``.env`` already
    says ``bedrock`` because the worker was being tried against a model that afternoon.
    """
    monkeypatch.setenv("PP_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("PP_BEDROCK_MODEL_ID", HAIKU)
    monkeypatch.setenv("AWS_PROFILE", "promisepatch")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    assert main(["--split", "development", "--model", NOVA]) == 0
    printed = capsys.readouterr().out
    assert "DRY RUN" in printed
    assert HAIKU not in printed


def test_importing_the_composition_root_loads_no_aws_sdk() -> None:
    """Not "it did not call AWS" but "importing it does not even load the SDK".

    A fresh interpreter, because asserting against this one would be asserting about whatever
    else the session imported. ``build_semantic_provider`` defers the Bedrock import into the
    branch that needs it, so the module graph stays clean until somebody asks for a client.
    """
    probe = (
        "import sys; import scripts.run_semantic_benchmark;"
        "print(','.join(n for n in ('boto3', 'botocore',"
        " 'promisepatch.integrations.bedrock') if n in sys.modules))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, cwd=ROOT
    )
    assert completed.stdout.strip() == ""


# --------------------------------------------------------------------- pricing refusals


def test_a_model_with_no_verified_price_cannot_be_benchmarked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The structural guard against an unintended model: no price, no enforceable ceiling.

    It used to be demonstrated with Haiku 4.5, which was then unpriced. Haiku is priced now
    -- the customer-intent challenger measures it, deliberately and under its own ceiling --
    so the demonstration moves to a model nobody has benchmarked. The rule is unchanged: an
    id that is not a key in the catalog refuses before a client is opened.
    """
    assert (
        main(["--live", "--split", "development", "--provider", "bedrock", "--model", UNPRICED])
        == 2
    )
    error = capsys.readouterr().err
    assert "has no verified price" in error
    assert UNPRICED in error


def test_only_benchmarked_models_carry_a_price() -> None:
    """Nova for this benchmark, Haiku for the customer-intent challenger, and nothing else."""
    assert price_for("bedrock", NOVA) is not None
    assert price_for("bedrock", HAIKU) is not None
    assert price_for("bedrock", UNPRICED) is None


# ------------------------------------------------------------------ the holdout protocol


def test_the_holdout_is_not_opened_without_saying_development_passed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Read once, to decide. A holdout opened casually is a second development set."""
    code = main(["--live", "--split", "holdout", "--provider", "bedrock", "--model", NOVA])
    assert code == 2
    assert "the holdout is opened once" in capsys.readouterr().err


# ------------------------------------------------------------------------- the ceilings


def test_the_ceilings_are_the_ones_this_benchmark_was_authorised_for() -> None:
    """Written down as constants so raising one is a diff somebody reviews."""
    assert GLOBAL_CEILING.max_calls == 110
    assert GLOBAL_CEILING.max_input_tokens == 300_000
    assert GLOBAL_CEILING.max_output_tokens == 30_000
    assert GLOBAL_CEILING.max_estimated_usd == Decimal("0.20")
    assert MAX_PROVIDER_FAILURES == 3


def test_the_whole_dataset_fits_inside_the_call_ceiling(dataset: GoldDataset) -> None:
    """Both splits together, so the ceiling is a bound on the benchmark and not on one run."""
    logical = sum(case.asked for case in dataset.worker) + len(dataset.customer)
    assert logical == 92
    assert GLOBAL_CEILING.max_calls is not None and logical <= GLOBAL_CEILING.max_calls


# ------------------------------------------------------ rebuilding without calling anything


def store_a_finished_run(path: Path, dataset: GoldDataset) -> RunHeader:
    """Write a result file the way a live run would, but from scripted answers.

    Synchronous on purpose: ``rebuild`` drives its own event loop, the way the command does,
    and a test that was already inside one would be testing a different entry point.
    """
    return asyncio.run(_write_a_finished_run(path, dataset))


async def _write_a_finished_run(path: Path, dataset: GoldDataset) -> RunHeader:
    from evals.prompts import prompt_identity

    from promisepatch.semantic import SemanticJob

    selected = dataset.split([EvalSplit.DEVELOPMENT])
    header = RunHeader(
        run_id=new_run_id(),
        started_at="2026-09-07T00:00:00+00:00",
        git_sha="abc123",
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        prompts=tuple(
            prompt_identity(job).as_payload()
            for job in (SemanticJob.INTERPRET_UTTERANCE, SemanticJob.CLASSIFY_REPLY_INTENT)
        ),
        provider="fake",
        model_id=NOVA,
        mode=LIVE_MODE,
        splits=(EvalSplit.DEVELOPMENT.value,),
    )
    store = ResultStore(path, header)
    await run_cases(
        selected,
        scripted_provider(ScriptedAnswers.from_file()),
        guard=BudgetGuard(EvalBudget(), price=price_for("bedrock", NOVA), live=False),
        provider_name="fake",
        mode=LIVE_MODE,
        on_result=store.record,
    )
    return header


def test_a_report_is_rebuilt_from_stored_answers_with_no_provider_call(
    dataset: GoldDataset, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A formatting failure must never be a reason to buy a split's answers a second time."""
    path = tmp_path / "development.jsonl"
    store_a_finished_run(path, dataset)
    capsys.readouterr()

    assert main(["--from-results", str(path)]) == 0
    printed = capsys.readouterr().out
    assert "Rebuilt from" in printed
    assert "with zero provider calls" in printed
    assert "QUALITY" in printed and "SAFETY" in printed and "COST" in printed


def test_a_rebuild_refuses_a_run_recorded_against_a_different_dataset(
    dataset: GoldDataset, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Re-scoring one run's answers against another dataset's labels measures neither."""
    path = tmp_path / "development.jsonl"
    store_a_finished_run(path, dataset)
    contents = path.read_text(encoding="utf-8").splitlines()
    contents[0] = contents[0].replace(dataset.content_hash, "0" * 64)
    path.write_text("\n".join(contents) + "\n", encoding="utf-8")
    capsys.readouterr()

    assert main(["--from-results", str(path)]) == 2
    assert "was run against dataset hash" in capsys.readouterr().err


# --------------------------------------------------------------------------- the parser


def test_the_parser_defaults_nothing_that_could_start_a_call() -> None:
    namespace = build_parser().parse_args([])
    assert namespace.live is False
    assert namespace.provider is None
    assert namespace.model is None
    assert namespace.split is None
    assert namespace.development_passed is False


def test_bedrock_is_the_only_provider_this_command_knows() -> None:
    """A choices list rather than a free string: a typo is a refusal, not a different vendor."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--provider", "openai"])


def test_the_refusal_type_says_nothing_was_spent() -> None:
    assert issubclass(BenchmarkRefusedError, RuntimeError)
    assert "nothing was spent" in (BenchmarkRefusedError.__doc__ or "")
