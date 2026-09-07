"""The challenger's composition root, proved without an AWS account and without spending.

Every case here ends with nothing having been called: the command refused, or it stopped at the
plan, or it rebuilt a report from readings somebody already paid for.

The properties a tired operator relies on, stated plainly:

* going live takes three explicit flags and reads no environment variable to decide;
* the plan is written and printable before any client exists, so the set can be reviewed first;
* a model with no verified price cannot be challenged at all;
* Stage B is opened by Stage A's result, never by the flag that asks for it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.budget import price_for
from evals.cases import EvalSplit
from evals.dataset import load_dataset
from scripts.run_intent_challenger import (
    CHALLENGER_CEILING,
    MAX_PROVIDER_FAILURES,
    ChallengerRefusedError,
    build_parser,
    main,
    narrow,
)

HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
NOVA = "us.amazon.nova-2-lite-v1:0"
UNPRICED = "example.unbenchmarked-model-v1:0"
SOURCE = Path(".eval-results/development-us.amazon.nova-2-lite-v1_0.jsonl")

needs_source = pytest.mark.skipif(
    not SOURCE.exists(),
    reason="the challenged model's stored run is a local artifact and is not committed",
)


# ------------------------------------------------------------------ the live opt-in


def test_going_live_needs_the_provider_and_the_model_named(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Three flags, none defaulted. A run that inherited its model measures one nobody chose."""
    assert main(["--live", "--stage", "a"]) == 2
    assert "requires --provider and --model" in capsys.readouterr().err


def test_a_run_without_a_stage_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    """One stage per invocation, so a Stage A gate cannot be skipped past into Stage B."""
    assert main(["--model", HAIKU]) == 2
    assert "--stage is required" in capsys.readouterr().err


def test_a_plan_needs_a_model_too(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--stage", "a"]) == 2
    assert "--model is required" in capsys.readouterr().err


@needs_source
def test_an_unpriced_model_cannot_be_challenged(capsys: pytest.CaptureFixture[str]) -> None:
    """Unknown pricing fails closed. It is never zero, and a ceiling on zero is not a ceiling."""
    assert price_for("bedrock", UNPRICED) is None
    assert main(["--stage", "a", "--model", UNPRICED]) == 2
    assert "no verified price" in capsys.readouterr().err


@needs_source
def test_an_aws_ready_environment_does_not_make_a_plan_live(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing here reads PP_LLM_PROVIDER to decide. The flag decides, and only the flag."""
    monkeypatch.setenv("PP_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("PP_BEDROCK_MODEL_ID", HAIKU)
    monkeypatch.setenv("AWS_PROFILE", "promisepatch")

    assert main(["--stage", "a", "--model", HAIKU]) == 0
    printed = capsys.readouterr().out
    assert "PLAN ONLY. No provider was constructed and nothing was spent." in printed


# ---------------------------------------------------------------------------- the plan


@needs_source
def test_the_plan_names_the_set_before_anything_is_bought(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A set reviewable before the money is spent is a set somebody can object to."""
    assert main(["--stage", "a", "--model", HAIKU]) == 0
    printed = capsys.readouterr().out
    for expected in (
        "CHALLENGER SET",
        "selection algorithm",
        "source results sha256",
        "FAILURE -> MATCHED CONTROL",
        "challenger readings on disk",
        load_dataset().content_hash,
    ):
        assert expected in printed


@needs_source
def test_the_plan_is_written_where_a_later_reader_can_reproduce_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The set's identity is an artifact, not a terminal buffer somebody has to still have."""
    from scripts.run_intent_challenger import selection_path

    main(["--stage", "a", "--model", HAIKU])
    capsys.readouterr()
    payload = json.loads(selection_path(HAIKU).read_text(encoding="utf-8"))
    for key in (
        "algorithm_version",
        "source_run_id",
        "source_results_sha",
        "dataset_hash",
        "failure_case_ids",
        "control_case_ids",
        "challenger_model_id",
        "prompts",
        "git_sha",
    ):
        assert key in payload
    assert payload["challenger_model_id"] == HAIKU
    assert len(payload["failure_case_ids"]) == len(payload["control_case_ids"])


@needs_source
def test_the_plan_carries_no_gold_label(capsys: pytest.CaptureFixture[str]) -> None:
    """The artifact records which cases were chosen, not what the right answers are.

    It records the *source model's* readings, which are a fact about a finished run and not a
    label. Nothing in it reaches a model: the challenger is sent
    :func:`~evals.cases.to_model_input`'s projection and this file is never part of a prompt.
    """
    from scripts.run_intent_challenger import selection_path

    main(["--stage", "a", "--model", HAIKU])
    capsys.readouterr()
    written = selection_path(HAIKU).read_text(encoding="utf-8")
    for case in load_dataset().customer:
        assert case.reply not in written


# ------------------------------------------------------------------ what cannot be bought


def test_a_narrowed_dataset_holds_no_worker_case_at_all() -> None:
    """Structural: "no worker call was made" is a property of the value handed to the runner."""
    full = load_dataset()
    assert full.worker
    selected = narrow(full, frozenset(case.id for case in full.customer))
    assert selected.worker == ()


def test_a_narrowed_dataset_holds_no_holdout_case_at_all() -> None:
    """The holdout is reserved for a selected strategy's final gate; nothing here opens it."""
    full = load_dataset()
    holdout = {case.id for case in full.customer if case.split is EvalSplit.HOLDOUT}
    assert holdout
    selected = narrow(full, frozenset(case.id for case in full.customer))
    assert not {case.id for case in selected.customer} & holdout
    assert all(case.split is EvalSplit.DEVELOPMENT for case in selected.customer)


def test_there_is_no_flag_that_opens_the_holdout() -> None:
    """Absence, not intention. The word does not appear in the command surface."""
    options = {action.dest for action in build_parser()._actions}
    assert "holdout" not in options
    assert build_parser().format_help().count("holdout") == 0


def test_there_is_no_flag_that_re_runs_the_challenged_model() -> None:
    """The source is read from a file. This command has no way to produce one."""
    source = next(action for action in build_parser()._actions if action.dest == "source")
    assert source.help is not None
    assert "never re-run" in source.help


# ------------------------------------------------------------- stage B is earned, not asked


@needs_source
def test_stage_b_is_refused_while_stage_a_has_bought_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Stage A that has decided nothing cannot authorise buying the rest of the split."""
    from scripts.run_intent_challenger import results_path

    if results_path(HAIKU).exists():
        pytest.skip("this machine has already run the challenger; the guard is state-dependent")
    assert main(["--stage", "b", "--model", HAIKU]) == 2
    assert "Stage A" in capsys.readouterr().err


# ------------------------------------------------------------------------- the ceilings


def test_the_ceilings_are_the_ones_written_down() -> None:
    """Fixed before the first call. Raising one is an edit somebody reviews, not a flag."""
    from decimal import Decimal

    assert CHALLENGER_CEILING.max_calls == 30
    assert CHALLENGER_CEILING.max_input_tokens == 100_000
    assert CHALLENGER_CEILING.max_output_tokens == 10_000
    assert CHALLENGER_CEILING.max_estimated_usd == Decimal("0.15")
    assert MAX_PROVIDER_FAILURES == 3


def test_the_challenged_model_is_not_the_challenger() -> None:
    """A comparison of a model with itself would be an expensive way to measure noise."""
    assert HAIKU != NOVA
    assert price_for("bedrock", HAIKU) is not None
    assert price_for("bedrock", NOVA) is not None


def test_a_refusal_is_an_exception_type_and_not_a_printed_warning() -> None:
    """A precondition that warned would already have spent the money by the time it printed."""
    assert issubclass(ChallengerRefusedError, RuntimeError)
