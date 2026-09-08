"""The OpenAI challenger's composition root: everything it refuses, and what it never calls.

The experiment being wired up here is the one that was already frozen. Same dataset, same
stored Nova run, same six failures and six matched controls, same production prompt, same
scorer, same materiality floor. Only the challenger's model changes -- which is the whole
content of the claim, and the reason so much of this file is about proving that nothing else
did.

Every test ends with no OpenAI client having existed. ``conftest.py`` refuses any connection
that leaves this machine, so "nothing was called" is enforced by the process rather than
asserted by the author, and :func:`test_the_off_machine_connection_count_is_still_zero` reads
that number back at the end.

Two properties are worth naming because they are what the previous challenger lacked:

* a valid-looking key changes nothing -- the interlocks that refuse are the harness's, not the
  provider's, so a test with a plausible credential still buys nothing;
* the credential is never printed, never persisted and never returned to anything that
  formats. Everything visible anywhere is a boolean.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
import scripts.run_intent_challenger as challenger
from evals.authorisation import SpendScope, required_phrase
from evals.budget import BudgetExhaustedError, BudgetGuard, price_for
from evals.cases import CustomerCase, EvalSplit
from evals.challenger import ProviderFailureCategory, provider_failure_category
from evals.dataset import GoldDataset, load_dataset
from evals.prompts import prompt_identity
from evals.results import CaseResult
from evals.runner import LIVE_MODE
from evals.store import ProviderFailureLog, RunHeader, StoreError, read_run
from scripts.tests.conftest import OFF_MACHINE_CONNECTIONS
from scripts.tests.test_spend_interlock import BuilderSpy, GoldAnsweringProvider, reading

from promisepatch.config import Settings
from promisepatch.semantic import (
    ApparentIntent,
    SemanticJob,
    SemanticProviderError,
    StructuredSemanticProvider,
)
from promisepatch.semantic.jobs import JobSpec
from promisepatch.semantic.provider import Attempt

GPT = challenger.GPT_4O_MINI
ALIAS = "gpt-4o-mini"
NOVA = "us.amazon.nova-2-lite-v1:0"
HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

STAGE_A = required_phrase(SpendScope.STAGE_A)
STAGE_B = required_phrase(SpendScope.STAGE_B)

FAKE_KEY = "sk-test-never-send"
"""A key shaped like a real one and belonging to nobody. It is never sent anywhere."""

EXPECTED_FAILURES = (
    "customer.approve.punctuation.001",
    "customer.approve.terse.001",
    "customer.approve.terse.007",
    "customer.decline.indirect.005",
    "customer.decline.terse.003",
    "customer.unclear.injection.003",
)
EXPECTED_CONTROLS = (
    "customer.approve.explicit.001",
    "customer.approve.terse.003",
    "customer.approve.terse.005",
    "customer.decline.indirect.001",
    "customer.decline.punctuation.001",
    "customer.unclear.injection.001",
)
"""The frozen Stage-A set. Written out because a paired experiment that re-matched its controls
when the challenger changed would no longer be paired, and the difference would be invisible."""


@pytest.fixture(scope="module")
def dataset() -> GoldDataset:
    return load_dataset()


def wrong_label(case: CustomerCase) -> ApparentIntent:
    """Any label but the right one. Which one it is does not affect how a control is matched."""
    return next(label for label in ApparentIntent if label is not case.expected)


def write_nova_like_source(path: Path, dataset: GoldDataset) -> None:
    """A stored source run that fails on exactly the six cases the real Nova run failed on.

    Reconstructed here rather than read from ``.eval-results``: those files are local artifacts
    of one machine and CI has none, so a suite that depended on them would silently skip the
    properties it exists to prove. The six ids are the frozen ones, and every other development
    case is recorded correct -- which is what the real run did, and therefore what makes the
    control pool, and the matched controls, the same twelve cases.
    """
    development = [case for case in dataset.customer if case.split is EvalSplit.DEVELOPMENT]
    assert set(EXPECTED_FAILURES) <= {case.id for case in development}
    header = RunHeader(
        run_id="source000001",
        started_at="2026-09-07T00:00:00+00:00",
        git_sha="0" * 40,
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        prompts=tuple(
            prompt_identity(job).as_payload()
            for job in (SemanticJob.INTERPRET_UTTERANCE, SemanticJob.CLASSIFY_REPLY_INTENT)
        ),
        provider="bedrock",
        model_id=NOVA,
        mode=LIVE_MODE,
        splits=(EvalSplit.DEVELOPMENT.value,),
    )
    from evals.store import ResultStore

    store = ResultStore(path, header)
    for case in development:
        predicted = wrong_label(case) if case.id in EXPECTED_FAILURES else case.expected
        store.record(reading(case, predicted))


@pytest.fixture
def sandbox(
    tmp_path: Path, dataset: GoldDataset, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """The challenger's whole artifact surface, pointed at a temporary directory."""
    results = tmp_path / "eval-results"
    results.mkdir()
    source = results / "development-nova.jsonl"
    write_nova_like_source(source, dataset)
    monkeypatch.setattr(challenger, "RESULTS_DIR", results)
    monkeypatch.setattr(challenger, "LEDGER", results / "cost-ledger.jsonl")
    monkeypatch.setattr(challenger, "DEFAULT_SOURCE", source)
    yield source


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid-looking OpenAI credential in the environment. It changes nothing, on purpose."""
    monkeypatch.setenv(challenger.API_KEY_VARIABLE, FAKE_KEY)


@pytest.fixture
def keyless(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No key in the environment and no ``.env`` that could supply one."""
    monkeypatch.delenv(challenger.API_KEY_VARIABLE, raising=False)
    monkeypatch.chdir(tmp_path)


def argv(source: Path, *extra: str, stage: str = "a", model: str = GPT) -> list[str]:
    return [
        "--provider",
        "openai",
        "--model",
        model,
        "--stage",
        stage,
        *extra,
        "--source",
        str(source),
    ]


# =====================================================================================
# 1. the model identity is the pinned snapshot
# =====================================================================================


def test_the_challenger_model_is_the_dated_snapshot() -> None:
    """The benchmark's model identity. A date, so a moved alias cannot change it underneath."""
    assert GPT == "gpt-4o-mini-2024-07-18"
    assert price_for("openai", GPT) is not None


def test_the_floating_alias_is_refused_by_name_before_anything_is_read(
    sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not merely unpriced. An operator who typed the alias is told to type the date."""
    spy = BuilderSpy()
    assert challenger.main(argv(sandbox, model=ALIAS), provider_builder=spy) == 2
    error = capsys.readouterr().err
    assert "floating alias" in error
    assert GPT in error
    assert spy.calls == []


def test_the_alias_is_refused_even_with_a_full_authorisation_and_a_key(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    spy = BuilderSpy()
    assert (
        challenger.main(
            argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A, model=ALIAS),
            provider_builder=spy,
        )
        == 2
    )
    assert "floating alias" in capsys.readouterr().err
    assert spy.calls == []


def test_the_alias_and_the_snapshot_never_share_a_result_file(dataset: GoldDataset) -> None:
    """Result identity, at the level a resumed run actually reads: the path on disk."""
    for path in (challenger.results_path, challenger.failures_path, challenger.selection_path):
        assert path(GPT) != path(ALIAS)
        assert path(GPT) != path(HAIKU)


def test_a_run_of_one_provider_cannot_be_continued_by_another(
    tmp_path: Path, dataset: GoldDataset
) -> None:
    """Provider and model are both in the stored identity, so neither drifts silently.

    Three ways one file could become two experiments -- a different provider, a different model
    snapshot, the alias standing in for the snapshot -- and all three are refused rather than
    appended to.
    """

    def header(provider: str, model_id: str) -> RunHeader:
        return RunHeader(
            run_id="run000000001",
            started_at="2026-09-08T00:00:00+00:00",
            git_sha="0" * 40,
            dataset_version=dataset.version,
            dataset_hash=dataset.content_hash,
            prompts=tuple(
                prompt_identity(job).as_payload()
                for job in (SemanticJob.INTERPRET_UTTERANCE, SemanticJob.CLASSIFY_REPLY_INTENT)
            ),
            provider=provider,
            model_id=model_id,
            mode=LIVE_MODE,
            splits=(EvalSplit.DEVELOPMENT.value,),
        )

    from evals.store import ResultStore

    path = tmp_path / "challenger.jsonl"
    ResultStore(path, header("openai", GPT))

    for provider, model_id, expected in (
        ("bedrock", GPT, "provider"),
        ("openai", ALIAS, "model_id"),
        ("bedrock", HAIKU, "model_id"),
    ):
        with pytest.raises(StoreError) as error:
            ResultStore(path, header(provider, model_id))
        assert expected in str(error.value)


# =====================================================================================
# 2. the ceilings are OpenAI's own
# =====================================================================================


def test_the_openai_ceilings_are_the_ones_written_down() -> None:
    """Fixed before the first call, and separate from the ceilings of a dearer model."""
    ceiling = challenger.OPENAI_CHALLENGER_CEILING
    assert ceiling.max_calls == 30
    assert ceiling.max_input_tokens == 100_000
    assert ceiling.max_output_tokens == 10_000
    assert ceiling.max_estimated_usd == Decimal("0.03")

    assert challenger.OPENAI_STAGE_A_CEILING.max_calls == 12
    assert challenger.OPENAI_STAGE_A_CEILING.max_estimated_usd == Decimal("0.01")


def test_the_bedrock_ceilings_are_untouched_by_the_new_provider() -> None:
    """History keeps its meaning. Adding a provider is not repricing the one already there."""
    assert challenger.CHALLENGER_CEILING.max_estimated_usd == Decimal("0.15")
    assert challenger.STAGE_A_CEILING.max_estimated_usd == Decimal("0.03")
    assert challenger.stage_ceiling("a", "bedrock").max_estimated_usd == Decimal("0.03")
    assert challenger.stage_ceiling("b", "bedrock") == challenger.CHALLENGER_CEILING


def test_openai_stage_a_composes_its_ceiling_with_the_openai_global_one() -> None:
    """Both hold: the stage narrows calls and dollars, the global still bounds the tokens."""
    ceiling = challenger.stage_ceiling("a", "openai")
    assert ceiling.max_calls == 12
    assert ceiling.max_estimated_usd == Decimal("0.01")
    assert ceiling.max_input_tokens == 100_000
    assert ceiling.max_output_tokens == 10_000


def test_the_openai_stage_ceiling_can_only_narrow_the_openai_global_one() -> None:
    stage = challenger.stage_ceiling("a", "openai")
    whole = challenger.global_ceiling("openai")
    assert stage.max_calls is not None and whole.max_calls is not None
    assert stage.max_calls <= whole.max_calls
    assert stage.max_estimated_usd is not None and whole.max_estimated_usd is not None
    assert stage.max_estimated_usd <= whole.max_estimated_usd


def test_openai_stage_b_keeps_the_openai_global_ceiling_exactly() -> None:
    """Stage B is separately authorised and separately bounded. Nothing here changed it."""
    assert challenger.stage_ceiling("b", "openai") == challenger.OPENAI_CHALLENGER_CEILING


def test_openai_stage_a_cannot_buy_a_thirteenth_call() -> None:
    """The refusal is before the call, so the thirteenth question is never put to anything."""
    guard = BudgetGuard(
        challenger.stage_ceiling("a", "openai"), price=price_for("openai", GPT), live=True
    )
    for _ in range(12):
        guard.authorise()
    with pytest.raises(BudgetExhaustedError, match="call budget exhausted"):
        guard.authorise()
    assert guard.spend.calls == 12


def test_openai_stage_a_refuses_the_call_that_would_cross_one_cent() -> None:
    """A dollar cap that reported afterwards would have spent the money before anybody read."""
    from promisepatch.semantic import SemanticTelemetry, SemanticUsage

    guard = BudgetGuard(
        challenger.stage_ceiling("a", "openai"), price=price_for("openai", GPT), live=True
    )
    guard.authorise()
    guard.record(
        SemanticTelemetry(
            job=SemanticJob.CLASSIFY_REPLY_INTENT,
            provider="openai",
            model_id=GPT,
            attempts=1,
            usage=SemanticUsage(input_tokens=70_000, output_tokens=0),
        )
    )
    assert guard.spend.estimated_usd is not None
    assert guard.spend.estimated_usd >= Decimal("0.01")
    with pytest.raises(BudgetExhaustedError, match="estimated spend budget exhausted"):
        guard.authorise()


def test_the_openai_global_ceiling_cannot_be_exceeded_either() -> None:
    """The stage bound is the stricter one, so the global is defence in depth rather than moot."""
    guard = BudgetGuard(
        challenger.global_ceiling("openai"), price=price_for("openai", GPT), live=True
    )
    for _ in range(30):
        guard.authorise()
    with pytest.raises(BudgetExhaustedError):
        guard.authorise()


def test_the_openai_budget_is_not_an_operator_flag() -> None:
    """A ceiling typed at the keyboard is a ceiling that depends on somebody being awake."""
    parser = challenger.build_parser()
    flags = {action.option_strings[0] for action in parser._actions if action.option_strings}
    assert "--max-estimated-usd" not in flags
    assert "--max-calls" not in flags


def test_the_budget_block_names_the_provider_whose_ceilings_are_in_force() -> None:
    """A stored preflight has to answer "which bound refused", and now also "whose bound"."""
    printed = challenger._stage_budget_block("a", challenger.stage_ceiling("a", "openai"), "openai")
    assert "provider                     openai" in printed
    assert "global challenger ceiling    30 call(s) / $0.03" in printed
    assert "stage A ceiling              12 call(s) / $0.01" in printed
    assert "effective ceiling            12 call(s) / $0.01" in printed


# =====================================================================================
# 3. --live alone buys nothing, and a key does not change that
# =====================================================================================


def test_live_without_an_authorisation_refuses_before_any_provider_exists(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """A plausible key present throughout. What refuses is the harness, not the credential."""
    spy = BuilderSpy()
    assert challenger.main(argv(sandbox, "--live"), provider_builder=spy) == 2
    assert "does not authorise a charge" in capsys.readouterr().err
    assert spy.calls == []
    assert OFF_MACHINE_CONNECTIONS == []


def test_a_fully_authorised_openai_run_still_cannot_reach_the_default_builder(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both guards, in the order a real invocation meets them.

    The phrase is correct and the key is present, so everything an operator controls has been
    satisfied. The default builder is the real one, and a pytest process does not pass it.
    """
    code = challenger.main(argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A))
    assert code == 2
    assert "a test process may not construct a paid provider" in capsys.readouterr().err
    assert OFF_MACHINE_CONNECTIONS == []


def test_a_stage_a_phrase_cannot_buy_openai_stage_b(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """An authorisation names one scope, and adding a provider did not make it name two."""
    spy = BuilderSpy()
    assert (
        challenger.main(
            argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A, stage="b"),
            provider_builder=spy,
        )
        == 2
    )
    assert spy.calls == []


def test_an_authorisation_from_the_other_provider_is_not_a_different_authorisation(
    sandbox: Path, keyed: None
) -> None:
    """The phrase names a stage, not a provider, and the stage ceilings it carries are OpenAI's.

    Worth asserting rather than assuming: the authorisation records the caps it was granted
    against, and a report that quoted Bedrock's caps for an OpenAI run would describe a decision
    nobody took.
    """
    namespace = challenger.build_parser().parse_args(
        argv(Path("source.jsonl"), "--live", "--authorise-paid-inference", STAGE_A)
    )
    challenger._validate(namespace)
    assert namespace.authorisation.scope is SpendScope.STAGE_A
    assert namespace.authorisation.max_calls == 12
    assert namespace.authorisation.max_estimated_usd == Decimal("0.01")


# =====================================================================================
# 4. the credential: refused when absent, never printed when present
# =====================================================================================


def test_a_missing_key_refuses_before_the_provider_and_falls_back_to_nothing(
    sandbox: Path, keyless: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """No key, no client, no request -- and no quiet substitution of some other model."""
    spy = BuilderSpy()
    code = challenger.main(
        argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A), provider_builder=spy
    )
    error = capsys.readouterr().err
    assert code == 2
    assert challenger.API_KEY_VARIABLE in error
    assert spy.calls == []
    assert "bedrock" not in error.lower()
    assert OFF_MACHINE_CONNECTIONS == []


def test_the_refusal_is_reachable_on_its_own_and_says_nothing_about_a_value(
    keyless: None,
) -> None:
    with pytest.raises(challenger.ChallengerRefusedError) as error:
        challenger.refuse_a_missing_openai_key("openai")
    assert "nothing was spent" in str(error.value)
    # Bedrock has no such credential to be missing, and this check does not invent one for it.
    challenger.refuse_a_missing_openai_key("bedrock")


def test_the_key_is_read_from_the_environment_or_a_local_env_file_and_from_nowhere_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two places, both of them this repository's existing convention. No third."""
    monkeypatch.delenv(challenger.API_KEY_VARIABLE, raising=False)
    monkeypatch.chdir(tmp_path)
    assert challenger.openai_api_key_present() is False

    (tmp_path / ".env").write_text(
        f"# a comment\nPP_ENV=local\n{challenger.API_KEY_VARIABLE}={FAKE_KEY}\n", encoding="utf-8"
    )
    assert challenger.openai_api_key_present() is True

    monkeypatch.setenv(challenger.API_KEY_VARIABLE, "sk-environment-wins")
    assert challenger.read_openai_api_key() == "sk-environment-wins"


def test_an_empty_value_is_not_a_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(challenger.API_KEY_VARIABLE, "   ")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"{challenger.API_KEY_VARIABLE}=\n", encoding="utf-8")
    assert challenger.openai_api_key_present() is False


def test_no_printed_output_or_stored_artifact_ever_carries_the_key(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The plan prints a boolean. The selection file, the preflight and stderr carry nothing.

    Run with a key present so that everything which *could* print one has the chance to.
    """
    assert challenger.main(argv(sandbox), provider_builder=BuilderSpy()) == 0
    captured = capsys.readouterr()
    assert FAKE_KEY not in captured.out
    assert FAKE_KEY not in captured.err
    assert f"  {(challenger.API_KEY_VARIABLE + ' present').ljust(32)} true" in captured.out

    for path in sandbox.parent.rglob("*"):
        if path.is_file():
            assert FAKE_KEY not in path.read_text(encoding="utf-8", errors="ignore"), path


# =====================================================================================
# 5. the zero-call plan
# =====================================================================================


def test_the_plan_names_the_provider_the_model_and_both_ceilings(
    sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Everything a reviewer needs before deciding whether to spend, printed before spending."""
    spy = BuilderSpy()
    assert challenger.main(argv(sandbox), provider_builder=spy) == 0
    printed = capsys.readouterr().out

    assert "provider                   openai" in printed
    assert f"model / inference profile  {GPT}" in printed
    assert "$0.15 in / $0.60 out per 1M tokens" in printed
    assert "stage A ceiling              12 call(s) / $0.01" in printed
    assert "global challenger ceiling    30 call(s) / $0.03" in printed
    assert "PLAN ONLY" in printed
    assert spy.calls == []


def test_the_plan_counts_what_it_did_not_do(
    sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A plan that only claimed "nothing was called" would be an assertion about intent."""
    assert challenger.main(argv(sandbox), provider_builder=BuilderSpy()) == 0
    printed = capsys.readouterr().out

    for label, value in (
        ("challenger provider", "openai"),
        ("challenger model", GPT),
        ("stage A cases", "12"),
        ("worker cases", "0"),
        ("holdout cases", "0"),
        ("challenger model calls", "0"),
        ("source (challenged) model calls", "0"),
        ("provider clients constructed", "0"),
    ):
        assert f"  {label.ljust(32)} {value}" in printed
    assert OFF_MACHINE_CONNECTIONS == []


def test_the_plan_records_no_region_for_a_provider_that_has_none(
    sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``us-east-1`` against an OpenAI run would be a fact in a result file that is not one."""
    assert challenger.main(argv(sandbox), provider_builder=BuilderSpy()) == 0
    assert "region                     not applicable" in capsys.readouterr().out

    written = json.loads(challenger.selection_path(GPT).read_text(encoding="utf-8"))
    assert written["region"] == "not applicable"
    assert written["challenger_model_id"] == GPT


def test_a_plan_loads_no_openai_sdk_in_a_fresh_interpreter(sandbox: Path) -> None:
    """The strongest form of "no client was constructed": the SDK is not in the module graph.

    A separate interpreter, because this one has imported the adapter for other tests. The plan
    is run end to end and the module list is read afterwards -- so this is not an assertion that
    the code looks right, it is the process saying what it loaded.
    """
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    probe = (
        "import sys, io, contextlib;"
        "import scripts.run_intent_challenger as c;"
        "buffer = io.StringIO();"
        "code = None;"
        "\nwith contextlib.redirect_stdout(buffer):\n"
        "    code = c.main(['--stage', 'a', '--provider', 'openai', '--model',"
        f" {GPT!r}, '--source', {str(sandbox)!r}])\n"
        "print(code, 'openai' in sys.modules,"
        " 'promisepatch.integrations.openai' in sys.modules,"
        " 'boto3' in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, cwd=root
    )
    assert completed.stdout.strip() == "0 False False False"


def test_the_plan_needs_no_key_at_all(
    sandbox: Path, keyless: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The free half of the command stays free, and says what the other half would need."""
    assert challenger.main(argv(sandbox), provider_builder=BuilderSpy()) == 0
    printed = capsys.readouterr().out
    assert f"  {(challenger.API_KEY_VARIABLE + ' present').ljust(32)} false" in printed
    assert STAGE_A in printed


# =====================================================================================
# 6. the selection is the frozen one, and nothing else can enter it
# =====================================================================================


def test_the_stage_a_selection_is_the_same_twelve_cases_as_before(
    sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A paired experiment that re-matched its controls per challenger would not be paired.

    Built from the stored source run, which the challenger's identity does not touch: the
    failures are whatever Nova got wrong and the controls are chosen by a rule that cannot see
    who is being challenged.
    """
    assert challenger.main(argv(sandbox), provider_builder=BuilderSpy()) == 0
    capsys.readouterr()
    written = json.loads(challenger.selection_path(GPT).read_text(encoding="utf-8"))

    assert len(written["failure_case_ids"]) == 6
    assert len(written["control_case_ids"]) == 6
    assert written["cases"] == 12
    assert set(written["failure_case_ids"]) | set(written["control_case_ids"]) == set(
        written["failure_case_ids"]
    ) ^ set(written["control_case_ids"])
    assert all(case_id.startswith("customer.") for case_id in written["failure_case_ids"])


@pytest.mark.skipif(
    not Path(".eval-results/development-us.amazon.nova-2-lite-v1_0.jsonl").exists(),
    reason="the challenged model's stored run is a local artifact and is not committed",
)
def test_the_selection_against_the_real_nova_run_is_the_frozen_set() -> None:
    """The exact twelve, against the run that produced them. Skipped where that file is absent."""
    from evals.challenger import SourceRun, customer_development, select_stage_a

    full = load_dataset()
    header, results = read_run(Path(".eval-results/development-us.amazon.nova-2-lite-v1_0.jsonl"))
    selection = select_stage_a(
        full,
        SourceRun(
            run_id=header.run_id,
            model_id=header.model_id,
            provider=header.provider,
            git_sha=header.git_sha,
            dataset_version=header.dataset_version,
            dataset_hash=header.dataset_hash,
            results=customer_development(results),
        ),
    )
    assert header.run_id == "36c1f008de80"
    assert tuple(sorted(selection.failure_ids)) == EXPECTED_FAILURES
    assert tuple(sorted(selection.control_ids)) == EXPECTED_CONTROLS
    assert len(selection.case_ids) == 12


def test_a_worker_case_cannot_reach_the_openai_provider(dataset: GoldDataset) -> None:
    """Refused, not filtered. The job the earlier accidental run actually reached."""
    with pytest.raises(challenger.ChallengerRefusedError) as error:
        challenger.refuse_ineligible_cases(
            GoldDataset(
                version=dataset.version,
                worker=dataset.worker[:1],
                customer=tuple(c for c in dataset.customer if c.split is EvalSplit.DEVELOPMENT)[:2],
                provenance=dataset.provenance,
            )
        )
    assert "worker case(s) reached the challenger set" in str(error.value)


def test_a_holdout_case_cannot_reach_the_openai_provider(dataset: GoldDataset) -> None:
    """Identified by split metadata alone. No holdout input is read to prove this."""
    holdout = tuple(c for c in dataset.customer if c.split is EvalSplit.HOLDOUT)
    assert holdout
    with pytest.raises(challenger.ChallengerRefusedError) as error:
        challenger.refuse_ineligible_cases(
            GoldDataset(
                version=dataset.version,
                worker=(),
                customer=holdout[:2],
                provenance=dataset.provenance,
            )
        )
    assert "outside the development split" in str(error.value)


def test_there_is_still_no_flag_that_opens_the_holdout_or_re_runs_the_source() -> None:
    text = Path(challenger.__file__).read_text(encoding="utf-8")
    flags = {
        action.option_strings[0]
        for action in challenger.build_parser()._actions
        if action.option_strings
    }
    assert "--split" not in flags
    assert "--holdout" not in flags
    assert "--rerun-source" not in flags
    assert "EvalSplit.HOLDOUT" not in text


# =====================================================================================
# 7. gold never reaches the model
# =====================================================================================


def _request_bytes(case: CustomerCase) -> str:
    """Exactly what would go on the wire for one case, through the OpenAI adapter."""
    from evals.cases import to_model_input

    from promisepatch.integrations.openai import build_chat_request
    from promisepatch.semantic.jobs import spec_for
    from promisepatch.semantic.prompts import build_user_content

    model_input = to_model_input(case)
    spec = spec_for(model_input.request)
    return json.dumps(
        build_chat_request(
            spec,
            build_user_content(model_input.request),
            model_id=GPT,
            correction=None,
        ),
        sort_keys=True,
    )


def test_changing_a_gold_label_a_split_a_tag_or_a_role_does_not_change_the_request(
    dataset: GoldDataset,
) -> None:
    """The P4.4 invariant, asserted on the OpenAI composition path specifically.

    Each mutation is one a tuner might make, and each leaves the bytes identical. The request is
    built from the customer's reply and the job spec; nothing about how the case is *scored*
    is an input to it, so there is no route by which the model could learn the answer.
    """
    case = next(c for c in dataset.customer if c.split is EvalSplit.DEVELOPMENT)
    baseline = _request_bytes(case)

    other_label = next(label for label in ApparentIntent if label is not case.expected)
    for mutated in (
        case.model_copy(update={"expected": other_label}),
        case.model_copy(update={"split": EvalSplit.HOLDOUT}),
        case.model_copy(update={"tags": ("invented_tag",)}),
        case.model_copy(update={"id": "customer.renamed.999"}),
    ):
        assert _request_bytes(mutated) == baseline

    changed_reply = case.model_copy(update={"reply": "something else entirely"})
    assert _request_bytes(changed_reply) != baseline


def test_the_request_for_the_canonical_case_is_the_reply_and_nothing_more(
    dataset: GoldDataset,
) -> None:
    """The case the challenge exists for gets one ordinary request, with no help of any kind.

    No example, no hint, no note that a previous model read it as ``UNCLEAR``, and no mention
    of the case at all. It is asked exactly what every other case is asked.
    """
    case = next(c for c in dataset.customer if c.id == "customer.approve.terse.001")
    serialised = _request_bytes(case)
    plain = _request_bytes(
        next(c for c in dataset.customer if c.id != case.id and c.split is case.split)
    )

    assert case.reply in serialised
    for forbidden in (case.id, "Nova", "nova", "previously", "hint", "for example"):
        assert forbidden not in serialised

    # The only difference between this case's request and any other case's is the reply. The
    # system message, the function and the forced choice are byte-identical, so nothing about
    # this case has been special-cased anywhere on the path.
    for key in ("tools", "tool_choice", "temperature", "max_completion_tokens"):
        assert json.loads(serialised)[key] == json.loads(plain)[key]
    assert json.loads(serialised)["messages"][0] == json.loads(plain)["messages"][0]


# =====================================================================================
# 8. provider failures are execution facts, never quality
# =====================================================================================


class FailingOpenAiProvider(StructuredSemanticProvider):
    """Reached, and answers nothing -- the way a rejected key or a denied account behaves."""

    name = "openai"
    model_id = GPT

    def __init__(self, error: SemanticProviderError) -> None:
        self._error = error
        self.attempts = 0

    async def invoke(self, spec: JobSpec, content: str, *, correction: str | None) -> Attempt:
        self.attempts += 1
        raise self._error


@pytest.mark.parametrize(
    ("class_name", "category"),
    [
        ("OpenAiAuthenticationError", ProviderFailureCategory.AUTHENTICATION),
        ("OpenAiPermissionError", ProviderFailureCategory.PERMISSION),
        ("OpenAiRateLimitError", ProviderFailureCategory.RATE_LIMITED),
        ("OpenAiInvalidRequestError", ProviderFailureCategory.INVALID_REQUEST),
        ("OpenAiUnavailableError", ProviderFailureCategory.PROVIDER_UNAVAILABLE),
        ("SemanticTimeoutError", ProviderFailureCategory.TIMEOUT),
        ("SemanticProviderError", ProviderFailureCategory.PROVIDER_UNREACHABLE),
        ("SomethingNobodyHasSeen", ProviderFailureCategory.UNKNOWN_PROVIDER_FAILURE),
    ],
)
def test_each_transport_failure_normalises_to_a_category_and_never_to_a_label(
    dataset: GoldDataset, class_name: str, category: ProviderFailureCategory
) -> None:
    """A failure names why nobody was reached.

    None of these is a reading, and none of them can become one.
    """
    case = next(c for c in dataset.customer if c.split is EvalSplit.DEVELOPMENT)
    result = CaseResult(
        case_id=case.id,
        job=case.job,
        split=case.split,
        tags=case.tags,
        expected={"apparent_intent": case.expected.value},
        observed={},
        metrics={},
        passed=False,
        reason="no reading",
        provider="openai",
        model_id=GPT,
        error_category=class_name,
        provider_error=True,
    )
    assert provider_failure_category(result) is category
    assert result.observed == {}
    assert not result.has_reading


def test_a_stage_stopped_by_openai_failures_reports_no_quality_verdict(
    sandbox: Path, dataset: GoldDataset, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The lesson the Haiku attempt taught, kept for the replacement.

    Three refusals, the stop policy fires, and the run says what it knows: that it obtained no
    readings. It does not say the challenger was not material, because nothing about the
    challenger was measured.
    """
    from promisepatch.integrations.openai import OpenAiAuthenticationError

    provider = FailingOpenAiProvider(OpenAiAuthenticationError("OpenAI rejected the key: 401"))
    code = challenger.main(
        argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A),
        provider_builder=lambda target, granted: provider,
    )
    printed = capsys.readouterr().out

    assert provider.attempts == challenger.MAX_PROVIDER_FAILURES
    assert "STAGE A INVALID FOR A QUALITY DECISION - EXECUTION FAILURE" in printed
    assert "Challenger quality: NOT MEASURED" in printed
    assert "CHALLENGER NOT MATERIAL" not in printed
    assert "STAGE A PASSED - STAGE B AUTHORISED" not in printed
    assert code != 0
    assert OFF_MACHINE_CONNECTIONS == []


def test_the_failed_openai_attempts_are_kept_out_of_the_readings_file(
    sandbox: Path, dataset: GoldDataset, keyed: None
) -> None:
    """Evidence retained, and retained where a resumed run will not read it back as an answer."""
    from promisepatch.integrations.openai import OpenAiPermissionError

    challenger.main(
        argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A),
        provider_builder=lambda target, granted: FailingOpenAiProvider(
            OpenAiPermissionError("403")
        ),
    )
    attempts = ProviderFailureLog(challenger.failures_path(GPT))
    assert len(attempts.records) == challenger.MAX_PROVIDER_FAILURES
    assert all(record.model_id == GPT for record in attempts.records)
    assert all(record.provider == "openai" for record in attempts.records)
    assert all(record.category == "OpenAiPermissionError" for record in attempts.records)
    # The category is a class name and carries no message, no header and no key.
    assert all(FAKE_KEY not in str(record.as_payload()) for record in attempts.records)

    _, readings = read_run(challenger.results_path(GPT))
    assert readings == ()


# =====================================================================================
# 9. Stage A does not continue into Stage B by itself
# =====================================================================================


class GoldAnsweringOpenAi(GoldAnsweringProvider):
    """The gold-answering fake, wearing the OpenAI identity so the store agrees with itself."""

    name = "openai"
    model_id = GPT


def test_an_authorised_openai_stage_a_runs_and_stops_there(
    sandbox: Path, dataset: GoldDataset, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole orchestration, offline, against a provider handed in. Stage B is not entered."""
    provider = GoldAnsweringOpenAi(dataset)
    code = challenger.main(
        argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A),
        provider_builder=lambda target, granted: provider,
    )
    printed = capsys.readouterr().out

    assert "SPEND AUTHORISED  scope STAGE-A" in printed
    assert provider.asked
    assert all(job is SemanticJob.CLASSIFY_REPLY_INTENT for job in provider.asked)
    assert len(provider.asked) <= 12
    assert code == 0
    assert "STAGE A PASSED - STAGE B AUTHORISED" in printed
    assert OFF_MACHINE_CONNECTIONS == []


def test_a_passed_openai_stage_a_does_not_open_stage_b_without_its_own_authorisation(
    sandbox: Path, dataset: GoldDataset, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The approval that was given was for the probe, and it does not carry."""
    assert (
        challenger.main(
            argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A),
            provider_builder=lambda target, granted: GoldAnsweringOpenAi(dataset),
        )
        == 0
    )
    capsys.readouterr()

    spy = BuilderSpy()
    assert challenger.main(argv(sandbox, "--live", stage="b"), provider_builder=spy) == 2
    assert "does not authorise a charge" in capsys.readouterr().err
    assert spy.calls == []


def test_openai_stage_b_is_refused_before_any_provider_when_stage_a_bought_nothing(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """A correct Stage-B phrase does not substitute for a Stage A that decided something."""
    spy = BuilderSpy()
    assert (
        challenger.main(
            argv(sandbox, "--live", "--authorise-paid-inference", STAGE_B, stage="b"),
            provider_builder=spy,
        )
        == 2
    )
    assert "Stage A" in capsys.readouterr().err
    assert spy.calls == []


# =====================================================================================
# 10. rebuilding, and the number this file rests on
# =====================================================================================


def test_a_report_rebuilds_from_stored_openai_evidence_with_no_call(
    sandbox: Path, dataset: GoldDataset, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The builder raises if touched, and it is never touched."""
    challenger.main(
        argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A),
        provider_builder=lambda target, granted: GoldAnsweringOpenAi(dataset),
    )
    capsys.readouterr()

    spy = BuilderSpy()
    code = challenger.main(
        [
            "--from-results",
            str(challenger.results_path(GPT)),
            "--model",
            GPT,
            "--source",
            str(sandbox),
        ],
        provider_builder=spy,
    )
    printed = capsys.readouterr().out
    assert spy.calls == []
    assert "Rebuilt from" in printed
    assert code in (0, 1)
    assert OFF_MACHINE_CONNECTIONS == []


def test_the_openai_provider_holds_no_settings_that_route_production(
    sandbox: Path,
) -> None:
    """OpenAI is not in the runtime's provider enum, and this gate did not put it there."""
    from promisepatch.config import LlmProvider

    assert {member.value for member in LlmProvider} == {"fake", "bedrock"}
    assert Settings().llm_provider is LlmProvider.FAKE


def test_the_off_machine_connection_count_is_still_zero() -> None:
    """The claim this whole file rests on, as a number rather than an intention."""
    assert OFF_MACHINE_CONNECTIONS == []
