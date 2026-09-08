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
from decimal import Decimal
from pathlib import Path

import pytest
from evals.authorisation import SpendScope, required_phrase
from evals.budget import BudgetExhaustedError, BudgetGuard, price_for
from evals.cases import EvalSplit
from evals.dataset import load_dataset
from scripts.run_intent_challenger import (
    CHALLENGER_CEILING,
    MAX_PROVIDER_FAILURES,
    STAGE_A_CEILING,
    ChallengerRefusedError,
    build_parser,
    main,
    narrow,
    stage_ceiling,
)

from promisepatch.semantic import SemanticJob, SemanticTelemetry, SemanticUsage

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


# --------------------------------------- Stage A's own ceiling, on top of the global one


def _telemetry(*, input_tokens: int, output_tokens: int) -> SemanticTelemetry:
    """One answered call's usage. Synthetic: the thing under test is the arithmetic."""
    return SemanticTelemetry(
        job=SemanticJob.CLASSIFY_REPLY_INTENT,
        provider="counting",
        model_id=HAIKU,
        attempts=1,
        usage=SemanticUsage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def test_stage_a_is_bounded_by_twelve_calls_and_three_cents() -> None:
    """Twelve is the selection's size. The bound is written down, not typed at a keyboard."""
    assert STAGE_A_CEILING.max_calls == 12
    assert STAGE_A_CEILING.max_estimated_usd == Decimal("0.03")


def test_stage_a_composes_its_ceiling_with_the_global_one() -> None:
    """Both hold: the stage narrows calls and dollars, the global still bounds the tokens."""
    ceiling = stage_ceiling("a")
    assert ceiling.max_calls == 12
    assert ceiling.max_estimated_usd == Decimal("0.03")
    assert ceiling.max_input_tokens == CHALLENGER_CEILING.max_input_tokens
    assert ceiling.max_output_tokens == CHALLENGER_CEILING.max_output_tokens


def test_the_stage_ceiling_can_only_narrow_the_global_one() -> None:
    """A stage bound that widened any field would be a hole rather than a bound."""
    ceiling = stage_ceiling("a")
    assert ceiling.max_calls is not None
    assert CHALLENGER_CEILING.max_calls is not None
    assert ceiling.max_calls <= CHALLENGER_CEILING.max_calls
    assert ceiling.max_estimated_usd is not None
    assert CHALLENGER_CEILING.max_estimated_usd is not None
    assert ceiling.max_estimated_usd <= CHALLENGER_CEILING.max_estimated_usd


def test_stage_b_keeps_the_global_ceiling_exactly() -> None:
    """Stage B is separately authorised and separately approved. Nothing here changed it."""
    assert stage_ceiling("b") == CHALLENGER_CEILING
    assert stage_ceiling("b").max_calls == 30
    assert stage_ceiling("b").max_estimated_usd == Decimal("0.15")


def test_stage_a_cannot_buy_a_thirteenth_call() -> None:
    """The refusal is before the call, so the thirteenth question is never put to anything."""
    guard = BudgetGuard(stage_ceiling("a"), price=price_for("bedrock", HAIKU), live=True)

    for _ in range(12):
        guard.authorise()

    with pytest.raises(BudgetExhaustedError, match="call budget exhausted"):
        guard.authorise()
    assert guard.spend.calls == 12


def test_stage_a_refuses_the_call_that_would_cross_three_cents() -> None:
    """A dollar cap that reported afterwards would have spent the money before anybody read."""
    guard = BudgetGuard(stage_ceiling("a"), price=price_for("bedrock", HAIKU), live=True)
    guard.authorise()
    guard.record(_telemetry(input_tokens=30_000, output_tokens=0))

    assert guard.spend.estimated_usd is not None
    assert guard.spend.estimated_usd >= Decimal("0.03")
    with pytest.raises(BudgetExhaustedError, match="estimated spend budget exhausted"):
        guard.authorise()


def test_the_stage_a_budget_is_not_an_operator_flag() -> None:
    """Structural. There is no flag to widen it and none to forget to narrow."""
    options = {action.dest for action in build_parser()._actions}
    for forbidden in ("budget", "ceiling", "max_calls", "max_estimated_usd", "usd"):
        assert forbidden not in options
    help_text = build_parser().format_help()
    assert "--max-calls" not in help_text
    assert "--max-estimated-usd" not in help_text


# ----------------------------------------------- an approval that stops where it was given


def test_a_stage_a_phrase_cannot_buy_stage_b(capsys: pytest.CaptureFixture[str]) -> None:
    """Refused at the parse, before a dataset is read or a price is looked up."""
    code = main(
        [
            "--live",
            "--stage",
            "b",
            "--provider",
            "bedrock",
            "--model",
            HAIKU,
            "--authorise-paid-inference",
            required_phrase(SpendScope.STAGE_A),
        ]
    )
    assert code == 2
    assert "STAGE-B" in capsys.readouterr().err


@needs_source
def test_a_live_stage_a_names_its_ceiling_and_still_cannot_buy_from_a_test(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two properties at once, in the order they happen.

    The authorisation is granted against the *stage* ceiling, so what is printed for a reader
    to check is 12 / $0.03 rather than the global figures. Then the process interlock refuses
    to build the provider anyway, because this is pytest.
    """
    code = main(
        [
            "--live",
            "--stage",
            "a",
            "--provider",
            "bedrock",
            "--model",
            HAIKU,
            "--authorise-paid-inference",
            required_phrase(SpendScope.STAGE_A),
        ]
    )
    assert code == 2
    printed = capsys.readouterr()
    assert "caps 12 call(s) / $0.03" in printed.out
    assert "a test process may not construct a paid provider" in printed.err


@needs_source
def test_the_stage_a_selection_is_unchanged_by_the_budget(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The bound narrows money, not evidence: the same six failures and six controls."""
    from scripts.run_intent_challenger import selection_path

    assert main(["--stage", "a", "--model", HAIKU]) == 0
    capsys.readouterr()

    payload = json.loads(selection_path(HAIKU).read_text(encoding="utf-8"))
    assert payload["failure_case_ids"] == [
        "customer.approve.punctuation.001",
        "customer.approve.terse.001",
        "customer.approve.terse.007",
        "customer.decline.indirect.005",
        "customer.decline.terse.003",
        "customer.unclear.injection.003",
    ]
    assert payload["control_case_ids"] == [
        "customer.approve.terse.003",
        "customer.approve.terse.005",
        "customer.approve.explicit.001",
        "customer.decline.indirect.001",
        "customer.decline.punctuation.001",
        "customer.unclear.injection.001",
    ]
    assert payload["cases"] == 12
    selected = payload["failure_case_ids"] + payload["control_case_ids"]
    assert len(set(selected)) == 12
    # No worker case can reach a customer-intent challenger, and the ids say so.
    assert all(case_id.startswith("customer.") for case_id in selected)


def test_the_stage_a_budget_block_names_both_ceilings() -> None:
    """A stored preflight has to answer "which bound refused" without the operator present."""
    from scripts.run_intent_challenger import _stage_budget_block

    printed = _stage_budget_block("a", stage_ceiling("a"))
    assert "global challenger ceiling    30 call(s) / $0.15" in printed
    assert "stage A ceiling              12 call(s) / $0.03" in printed
    assert "effective ceiling            12 call(s) / $0.03" in printed
    assert "both remain in force" in printed
