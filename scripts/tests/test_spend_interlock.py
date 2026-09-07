"""The accident, reproduced offline, and the guards that now stop it.

What happened is worth stating exactly, because every test here is shaped by it. A case
asserted that a model with no verified price cannot be benchmarked, and it asserted it by
running the real command::

    main(["--live", "--split", "development", "--provider", "bedrock", "--model", HAIKU])

While Haiku had no price that line refused for the reason the test claimed. The day Haiku was
priced -- deliberately, for the challenger -- the same line stopped being an assertion and
became a live benchmark. It built the real Bedrock provider and put three worker sentences to
it. Nothing was billed, and the reason nothing was billed is that the account had no access to
that model. The thing that protected the repository was AWS.

That is the whole class of defect these tests close: a safety property that rests on unknown
pricing, absent credentials, or an IAM denial is not a safety property, because all three are
things somebody may fix on purpose one afternoon. So none of the tests below expects an
``AccessDeniedException``, none of them needs AWS to be missing, and several of them arrange
a complete, plausible set of AWS credentials precisely to show that it changes nothing.

Every case here ends with no provider having been constructed, or with one constructed by a
builder handed in as a parameter that reaches nothing. ``conftest.py`` refuses any connection
that leaves this machine, so "nothing was called" is enforced rather than asserted.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import scripts.run_intent_challenger as challenger
import scripts.run_semantic_benchmark as benchmark
from evals.authorisation import SpendNotAuthorisedError, SpendScope, required_phrase
from evals.cases import CustomerCase, EvalJob, EvalSplit
from evals.dataset import GoldDataset, load_dataset
from evals.prompts import prompt_identity
from evals.results import CaseResult
from evals.runner import LIVE_MODE
from evals.store import ResultStore, RunHeader
from scripts.tests.conftest import OFF_MACHINE_CONNECTIONS

from promisepatch.config import Settings
from promisepatch.semantic import (
    ApparentIntent,
    SemanticJob,
    SemanticProvider,
    StructuredSemanticProvider,
)
from promisepatch.semantic.jobs import JobSpec
from promisepatch.semantic.provider import Attempt

NOVA = "us.amazon.nova-2-lite-v1:0"
HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
UNPRICED = "example.unbenchmarked-model-v1:0"

STAGE_A = required_phrase(SpendScope.STAGE_A)
STAGE_B = required_phrase(SpendScope.STAGE_B)
SPLIT_DEV = required_phrase(SpendScope.SPLIT_DEVELOPMENT)

ROOT = Path(__file__).resolve().parents[2]

CREDENTIAL_LIKE_ENVIRONMENT = {
    "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
    "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "AWS_SESSION_TOKEN": "FwoGZXIvYXdzEEYaDEXAMPLESESSIONTOKEN",
    "AWS_PROFILE": "promisepatch",
    "AWS_REGION": "us-east-1",
    "AWS_DEFAULT_REGION": "us-east-1",
    "PP_LLM_PROVIDER": "bedrock",
    "PP_BEDROCK_MODEL_ID": HAIKU,
}
"""Everything a machine that could really spend would have, syntactically valid throughout.

Arranged on purpose. The claim under test is not "CI happens to have no credentials" -- that
is luck, and luck changes -- but "a credentialed, priced, configured process still cannot buy
inference from a test".
"""


@pytest.fixture(scope="module")
def dataset() -> GoldDataset:
    return load_dataset()


@pytest.fixture
def credentialed(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in CREDENTIAL_LIKE_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)


# --------------------------------------------------------------- the builders a test may pass


@dataclass
class BuilderSpy:
    """A provider builder that records being called, so "never reached" is a number."""

    provider: SemanticProvider | None = None
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    def __call__(self, settings: Settings, authorisation: object) -> SemanticProvider:
        self.calls.append((str(getattr(authorisation, "scope", "?")), settings.bedrock_model_id))
        if self.provider is None:
            raise AssertionError("this builder must not be reached")
        return self.provider


class GoldAnsweringProvider(StructuredSemanticProvider):
    """A fake that reads each customer reply correctly. No network, no credential, no SDK.

    It goes through production's own acceptance path like every other provider here, so an
    orchestration test that passes with it is a test of the real code around it. It answers
    from a table built out of the dataset, which makes it useful for proving that a stage
    which *did* clear materiality still cannot open the next one without its own authorisation.

    It reports the same ``name`` as :class:`RefusingProvider` because the two stand in for one
    provider in two states -- refusing, then answering once the infrastructure is fixed -- and
    the result store's identity check would rightly refuse to continue a file whose provider
    changed underneath it. Neither of them reaches anything.
    """

    name = "bedrock"
    model_id = HAIKU

    def __init__(self, dataset: GoldDataset) -> None:
        self._by_reply = {case.reply: case.expected for case in dataset.customer}
        self.asked: list[SemanticJob] = []

    async def invoke(self, spec: JobSpec, content: str, *, correction: str | None) -> Attempt:
        self.asked.append(spec.job)
        if spec.job is not SemanticJob.CLASSIFY_REPLY_INTENT:  # pragma: no cover - guarded above
            raise AssertionError(f"the challenger asked a {spec.job} question")
        label = next(
            (
                intent
                for reply, intent in sorted(self._by_reply.items(), key=lambda item: -len(item[0]))
                if reply in content
            ),
            ApparentIntent.UNCLEAR,
        )
        return Attempt(payload={"apparent_intent": label.value})


# ------------------------------------------------------------------ a sandboxed source run


def reading(case: CustomerCase, predicted: ApparentIntent) -> CaseResult:
    correct = predicted is case.expected
    return CaseResult(
        case_id=case.id,
        job=case.job,
        split=case.split,
        tags=case.tags,
        expected={"apparent_intent": case.expected.value},
        observed={"apparent_intent": predicted.value},
        metrics={
            "answered": True,
            "expected": case.expected.value,
            "predicted": predicted.value,
            "correct": correct,
            "authority_violation": False,
            "refusal_category": None,
        },
        passed=correct,
        reason="read",
        provider="bedrock",
        model_id=NOVA,
        attempts=1,
        latency_ms=300,
        e2e_latency_ms=380,
        input_tokens=400,
        output_tokens=12,
        estimated_usd="0.00015",
    )


def write_source(path: Path, dataset: GoldDataset) -> None:
    """A finished Nova run over the customer development split, wrong in exactly two places.

    Written here rather than read from ``.eval-results``: those files are local artifacts of
    somebody's machine and CI has none, so a suite that depended on them would silently skip
    the properties it exists to prove.
    """
    development = [case for case in dataset.customer if case.split is EvalSplit.DEVELOPMENT]
    approve = next(c for c in development if c.expected is ApparentIntent.APPARENT_APPROVE)
    decline = next(c for c in development if c.expected is ApparentIntent.APPARENT_DECLINE)
    wrong = {approve.id: ApparentIntent.UNCLEAR, decline.id: ApparentIntent.UNCLEAR}
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
    store = ResultStore(path, header)
    for case in development:
        store.record(reading(case, wrong.get(case.id, case.expected)))


@pytest.fixture
def sandbox(
    tmp_path: Path, dataset: GoldDataset, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """Point the challenger's whole artifact surface at a temporary directory."""
    results = tmp_path / "eval-results"
    results.mkdir()
    source = results / "development-nova.jsonl"
    write_source(source, dataset)
    monkeypatch.setattr(challenger, "RESULTS_DIR", results)
    monkeypatch.setattr(challenger, "LEDGER", results / "cost-ledger.jsonl")
    monkeypatch.setattr(challenger, "DEFAULT_SOURCE", source)
    yield source


def stage(argv: Sequence[str], source: Path) -> list[str]:
    return [*argv, "--source", str(source)]


# =====================================================================================
# 1. --live alone buys nothing
# =====================================================================================


def test_the_exact_historical_command_is_now_refused_before_any_provider_exists(
    credentialed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The line that spent three calls. Priced model, real flags, credentials present.

    Everything that was true on the day is arranged here except the outcome.
    """
    spy = BuilderSpy()
    code = benchmark.main(
        ["--live", "--split", "development", "--provider", "bedrock", "--model", HAIKU],
        provider_builder=spy,
    )
    assert code == 2
    assert "does not authorise a charge" in capsys.readouterr().err
    assert spy.calls == []
    assert OFF_MACHINE_CONNECTIONS == []


def test_the_same_refusal_holds_for_the_challenger(
    credentialed: None, sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spy = BuilderSpy()
    code = challenger.main(
        stage(["--live", "--stage", "a", "--provider", "bedrock", "--model", HAIKU], sandbox),
        provider_builder=spy,
    )
    assert code == 2
    assert "does not authorise a charge" in capsys.readouterr().err
    assert spy.calls == []


def test_a_credential_like_environment_changes_nothing(credentialed: None, sandbox: Path) -> None:
    """Not "CI has no credentials" but "credentials are not what was protecting it"."""
    spy = BuilderSpy()
    for argv in (
        ["--live", "--stage", "a", "--provider", "bedrock", "--model", HAIKU],
        ["--live", "--stage", "b", "--provider", "bedrock", "--model", HAIKU],
    ):
        assert challenger.main(stage(argv, sandbox), provider_builder=spy) == 2
    assert spy.calls == []


def test_importing_either_composition_root_loads_no_aws_sdk() -> None:
    """A fresh interpreter: the integration package is not even in the module graph."""
    probe = (
        "import sys, scripts.run_semantic_benchmark, scripts.run_intent_challenger;"
        "print(','.join(n for n in ('boto3', 'botocore',"
        " 'promisepatch.integrations.bedrock',"
        " 'promisepatch.integrations.semantic_provider') if n in sys.modules))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, cwd=ROOT
    )
    assert completed.stdout.strip() == ""


# =====================================================================================
# 2. the test-process interlock
# =====================================================================================


def test_the_real_builder_refuses_inside_pytest_however_it_is_called(
    credentialed: None,
) -> None:
    """Called directly, with a valid authorisation, in a fully credentialed process.

    This is the guard that does not depend on the operator at all. It refuses before the
    Bedrock import on the line below it, so a test that reaches here loads no SDK either.
    """
    from evals.authorisation import authorise

    granted = authorise(STAGE_A, SpendScope.STAGE_A)
    settings = Settings(bedrock_model_id=HAIKU)
    for builder in (challenger.bedrock_provider, benchmark.bedrock_provider):
        with pytest.raises(SpendNotAuthorisedError) as error:
            builder(settings, granted)
        assert "a test process may not construct a paid provider" in str(error.value)


def test_a_fully_authorised_command_still_cannot_reach_the_default_builder(
    credentialed: None, sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both guards, in the order a real invocation meets them.

    The phrase is correct, so the first guard passes. The default builder is the real one, so
    the second refuses. There is no arrangement of flags, credentials, pricing or model access
    that gets a pytest process past this, which is the property the previous design lacked.
    """
    code = challenger.main(
        stage(
            [
                "--live",
                "--stage",
                "a",
                "--provider",
                "bedrock",
                "--model",
                HAIKU,
                "--authorise-paid-inference",
                STAGE_A,
            ],
            sandbox,
        )
    )
    assert code == 2
    assert "a test process may not construct a paid provider" in capsys.readouterr().err
    assert OFF_MACHINE_CONNECTIONS == []


# =====================================================================================
# 3. the other guards keep their own jobs
# =====================================================================================


def test_unknown_pricing_still_fails_closed_with_a_valid_authorisation(
    sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Independent guards. Authorising a charge does not make an unmeasurable one enforceable."""
    spy = BuilderSpy()
    code = challenger.main(
        stage(
            [
                "--live",
                "--stage",
                "a",
                "--provider",
                "bedrock",
                "--model",
                UNPRICED,
                "--authorise-paid-inference",
                STAGE_A,
            ],
            sandbox,
        ),
        provider_builder=spy,
    )
    assert code == 2
    assert "no verified price" in capsys.readouterr().err
    assert spy.calls == []


def test_an_authorisation_without_the_live_flag_is_an_incoherent_command(
    sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        challenger.main(
            stage(
                ["--stage", "a", "--model", HAIKU, "--authorise-paid-inference", STAGE_A],
                sandbox,
            )
        )
        == 2
    )
    assert "does not call anything" in capsys.readouterr().err


def test_a_plan_still_needs_no_authorisation_and_names_the_one_it_would_need(
    sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The free half of the command stays free, and tells an operator what the other half costs."""
    spy = BuilderSpy()
    assert (
        challenger.main(stage(["--stage", "a", "--model", HAIKU], sandbox), provider_builder=spy)
        == 0
    )
    printed = capsys.readouterr().out
    assert "PLAN ONLY" in printed
    assert STAGE_A in printed
    assert spy.calls == []


# =====================================================================================
# 4. what cannot enter a challenger set, checked before the provider exists
# =====================================================================================


def test_a_worker_case_in_the_challenger_set_is_refused(dataset: GoldDataset) -> None:
    """The job the accidental run actually reached. Refused, not filtered."""
    with_worker = GoldDataset(
        version=dataset.version,
        worker=dataset.worker[:1],
        customer=tuple(c for c in dataset.customer if c.split is EvalSplit.DEVELOPMENT),
        provenance=dataset.provenance,
    )
    with pytest.raises(challenger.ChallengerRefusedError) as error:
        challenger.refuse_ineligible_cases(with_worker)
    assert "worker case(s) reached the challenger set" in str(error.value)


def test_a_holdout_case_in_the_challenger_set_is_refused(dataset: GoldDataset) -> None:
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


def test_a_customer_development_set_is_accepted(dataset: GoldDataset) -> None:
    development = tuple(c for c in dataset.customer if c.split is EvalSplit.DEVELOPMENT)
    eligible = GoldDataset(
        version=dataset.version, worker=(), customer=development, provenance=dataset.provenance
    )
    challenger.refuse_ineligible_cases(eligible)
    assert all(case.job is EvalJob.CUSTOMER_INTENT for case in eligible.customer)


def test_an_empty_set_is_refused(dataset: GoldDataset) -> None:
    with pytest.raises(challenger.ChallengerRefusedError):
        challenger.refuse_ineligible_cases(
            GoldDataset(
                version=dataset.version, worker=(), customer=(), provenance=dataset.provenance
            )
        )


def test_the_narrowed_set_the_runner_receives_is_always_eligible(dataset: GoldDataset) -> None:
    """The two guarantees agree: what ``narrow`` builds is what the check would accept."""
    narrowed = challenger.narrow(dataset, frozenset(case.id for case in dataset.customer))
    challenger.refuse_ineligible_cases(narrowed)
    assert narrowed.worker == ()


def test_the_challenged_model_cannot_be_the_challenger(
    sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nova is source evidence and is never a live participant, whatever the environment says."""
    spy = BuilderSpy()
    code = challenger.main(
        stage(
            [
                "--live",
                "--stage",
                "a",
                "--provider",
                "bedrock",
                "--model",
                NOVA,
                "--authorise-paid-inference",
                STAGE_A,
            ],
            sandbox,
        ),
        provider_builder=spy,
    )
    assert code == 2
    assert "is the model this comparison is challenging" in capsys.readouterr().err
    assert spy.calls == []


def test_nova_is_not_re_run_even_when_the_environment_names_it(
    monkeypatch: pytest.MonkeyPatch, sandbox: Path
) -> None:
    monkeypatch.setenv("PP_BEDROCK_MODEL_ID", NOVA)
    monkeypatch.setenv("PP_LLM_PROVIDER", "bedrock")
    spy = BuilderSpy()
    assert (
        challenger.main(
            stage(
                [
                    "--live",
                    "--stage",
                    "a",
                    "--provider",
                    "bedrock",
                    "--model",
                    NOVA,
                    "--authorise-paid-inference",
                    STAGE_A,
                ],
                sandbox,
            ),
            provider_builder=spy,
        )
        == 2
    )
    assert spy.calls == []


# =====================================================================================
# 5. stage authorisation does not carry
# =====================================================================================


def run_stage(
    sandbox: Path, dataset: GoldDataset, stage_name: str, phrase: str | None
) -> tuple[int, GoldAnsweringProvider]:
    provider = GoldAnsweringProvider(dataset)
    argv = ["--live", "--stage", stage_name, "--provider", "bedrock", "--model", HAIKU]
    if phrase is not None:
        argv += ["--authorise-paid-inference", phrase]
    code = challenger.main(
        stage(argv, sandbox), provider_builder=lambda settings, granted: provider
    )
    return code, provider


def test_an_authorised_stage_a_executes_against_a_provider_handed_in(
    sandbox: Path, dataset: GoldDataset, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance story B, first half. Real orchestration, no network, no real client."""
    code, provider = run_stage(sandbox, dataset, "a", STAGE_A)
    printed = capsys.readouterr().out
    assert "SPEND AUTHORISED  scope STAGE-A" in printed
    assert provider.asked
    assert all(job is SemanticJob.CLASSIFY_REPLY_INTENT for job in provider.asked)
    assert code == 0
    assert "STAGE A PASSED - STAGE B AUTHORISED" in printed
    assert OFF_MACHINE_CONNECTIONS == []


def test_a_passed_stage_a_does_not_open_stage_b_without_its_own_authorisation(
    sandbox: Path, dataset: GoldDataset, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance story B, second half. The approval that was given was for the probe."""
    assert run_stage(sandbox, dataset, "a", STAGE_A)[0] == 0
    capsys.readouterr()

    spy = BuilderSpy()
    argv = ["--live", "--stage", "b", "--provider", "bedrock", "--model", HAIKU]
    assert challenger.main(stage(argv, sandbox), provider_builder=spy) == 2
    assert "does not authorise a charge" in capsys.readouterr().err
    assert spy.calls == []


def test_a_stage_a_phrase_is_refused_for_stage_b(
    sandbox: Path, dataset: GoldDataset, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reusing the approval already given is the likeliest way to overspend by accident."""
    assert run_stage(sandbox, dataset, "a", STAGE_A)[0] == 0
    capsys.readouterr()

    spy = BuilderSpy()
    argv = [
        "--live",
        "--stage",
        "b",
        "--provider",
        "bedrock",
        "--model",
        HAIKU,
        "--authorise-paid-inference",
        STAGE_A,
    ]
    assert challenger.main(stage(argv, sandbox), provider_builder=spy) == 2
    error = capsys.readouterr().err
    assert "does not name STAGE-B" in error
    assert spy.calls == []


def test_stage_b_proceeds_once_it_is_separately_authorised(
    sandbox: Path, dataset: GoldDataset, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance story B, third half. A second, explicit decision, and only then."""
    assert run_stage(sandbox, dataset, "a", STAGE_A)[0] == 0
    capsys.readouterr()

    code, _ = run_stage(sandbox, dataset, "b", STAGE_B)
    printed = capsys.readouterr().out
    assert "SPEND AUTHORISED  scope STAGE-B" in printed
    assert code == 0
    assert "STAGE B" in printed
    assert OFF_MACHINE_CONNECTIONS == []


def test_stage_b_is_refused_before_any_provider_when_stage_a_bought_nothing(
    sandbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A correct Stage-B phrase does not substitute for a Stage A that decided something."""
    spy = BuilderSpy()
    argv = [
        "--live",
        "--stage",
        "b",
        "--provider",
        "bedrock",
        "--model",
        HAIKU,
        "--authorise-paid-inference",
        STAGE_B,
    ]
    assert challenger.main(stage(argv, sandbox), provider_builder=spy) == 2
    assert "Stage A" in capsys.readouterr().err
    assert spy.calls == []


# =====================================================================================
# 6. a stage stopped by provider failures decides nothing, and rebuilds without calling
# =====================================================================================


class RefusingProvider(StructuredSemanticProvider):
    """A provider that is reached and answers nothing, the way a denied account behaves."""

    name = "bedrock"
    model_id = None

    def __init__(self) -> None:
        self.attempts = 0

    async def invoke(self, spec: JobSpec, content: str, *, correction: str | None) -> Attempt:
        from promisepatch.semantic import SemanticProviderError

        self.attempts += 1
        raise SemanticProviderError("Bedrock rejected the request", retryable=False)


def test_a_stage_stopped_by_provider_failures_reports_no_quality_verdict(
    sandbox: Path, dataset: GoldDataset, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance story C, end to end, offline.

    Three refusals, the stop policy fires, and the run says what it actually knows: that it
    obtained no readings. It does not say the challenger was not material, because nothing
    about the challenger was measured.
    """
    provider = RefusingProvider()
    argv = [
        "--live",
        "--stage",
        "a",
        "--provider",
        "bedrock",
        "--model",
        HAIKU,
        "--authorise-paid-inference",
        STAGE_A,
    ]
    code = challenger.main(
        stage(argv, sandbox), provider_builder=lambda settings, granted: provider
    )
    printed = capsys.readouterr().out

    assert provider.attempts == challenger.MAX_PROVIDER_FAILURES
    assert "STAGE A INVALID FOR A QUALITY DECISION - EXECUTION FAILURE" in printed
    assert "Challenger quality: NOT MEASURED" in printed
    assert "readings obtained          0/4" in printed
    assert "provider failures          3" in printed
    # The two sentences this run must not produce: both claim something about the model.
    assert "CHALLENGER NOT MATERIAL" not in printed
    assert "STAGE A PASSED - STAGE B AUTHORISED" not in printed
    assert code != 0
    assert OFF_MACHINE_CONNECTIONS == []


def test_the_failed_attempts_are_kept_and_the_readings_file_stays_empty(
    sandbox: Path, dataset: GoldDataset
) -> None:
    """Evidence retained, and retained where a resumed run will not read it back as an answer."""
    provider = RefusingProvider()
    challenger.main(
        stage(
            [
                "--live",
                "--stage",
                "a",
                "--provider",
                "bedrock",
                "--model",
                HAIKU,
                "--authorise-paid-inference",
                STAGE_A,
            ],
            sandbox,
        ),
        provider_builder=lambda settings, granted: provider,
    )
    from evals.store import ProviderFailureLog, read_run

    attempts = ProviderFailureLog(challenger.failures_path(HAIKU))
    assert len(attempts.records) == challenger.MAX_PROVIDER_FAILURES
    assert all(record.category == "SemanticProviderError" for record in attempts.records)
    assert all(record.model_id == HAIKU for record in attempts.records)

    _, readings = read_run(challenger.results_path(HAIKU))
    assert readings == ()


def test_a_retried_case_is_asked_again_rather_than_read_back_as_an_outage(
    sandbox: Path, dataset: GoldDataset
) -> None:
    """The reason a failure is not written to the results file.

    The first run is refused on every case. The second, against a provider that answers, asks
    them again -- because nothing in the readings file said they were done -- and the attempt
    log still carries the first run's refusals beside the new answers.
    """
    challenger.main(
        stage(
            [
                "--live",
                "--stage",
                "a",
                "--provider",
                "bedrock",
                "--model",
                HAIKU,
                "--authorise-paid-inference",
                STAGE_A,
            ],
            sandbox,
        ),
        provider_builder=lambda settings, granted: RefusingProvider(),
    )
    code, provider = run_stage(sandbox, dataset, "a", STAGE_A)
    assert code == 0
    assert provider.asked

    from evals.store import ProviderFailureLog, read_run

    assert len(ProviderFailureLog(challenger.failures_path(HAIKU)).records) == 3
    _, readings = read_run(challenger.results_path(HAIKU))
    assert readings
    assert all(result.has_reading for result in readings)


def test_rebuilding_from_stored_evidence_makes_no_call_and_keeps_the_failures(
    sandbox: Path, dataset: GoldDataset, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance story D. The builder raises if touched, and it is never touched."""
    challenger.main(
        stage(
            [
                "--live",
                "--stage",
                "a",
                "--provider",
                "bedrock",
                "--model",
                HAIKU,
                "--authorise-paid-inference",
                STAGE_A,
            ],
            sandbox,
        ),
        provider_builder=lambda settings, granted: RefusingProvider(),
    )
    capsys.readouterr()

    spy = BuilderSpy()
    code = challenger.main(
        [
            "--from-results",
            str(challenger.results_path(HAIKU)),
            "--model",
            HAIKU,
            "--source",
            str(sandbox),
        ],
        provider_builder=spy,
    )
    printed = capsys.readouterr().out
    assert spy.calls == []
    assert "PROVIDER_FAILURE" in printed
    assert "provider failures          3" in printed
    assert "Rebuilt from" in printed
    assert code != 0
    assert OFF_MACHINE_CONNECTIONS == []


def test_a_rebuild_refuses_an_authorisation_because_it_buys_nothing(
    sandbox: Path, dataset: GoldDataset, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        challenger.main(
            [
                "--from-results",
                str(sandbox),
                "--authorise-paid-inference",
                STAGE_A,
            ]
        )
        == 2
    )
    assert "nothing here to authorise" in capsys.readouterr().err


def test_a_result_file_from_another_commit_is_refused_rather_than_continued(
    sandbox: Path, dataset: GoldDataset, capsys: pytest.CaptureFixture[str]
) -> None:
    """What must happen to the header-only file the invalid challenger run left behind.

    That run wrote a header naming its commit and then recorded nothing, because all three of
    its calls failed and a failure is not a reading. The harness has changed since. Continuing
    that file would append readings bought under one version of the code to a run identified
    as another, and the resulting comparison would describe neither.

    So it is refused, and the fix is a new run identity rather than an edit to old history.
    The file stays on disk, byte for byte, as evidence of what was attempted.

    The refusal lands after a client object exists and before any question is put to it, which
    is the distinction that matters: opening a client is not a charge, and no case is bought.
    """
    stale = challenger.results_path(HAIKU)
    header = json.loads(sandbox.read_text(encoding="utf-8").splitlines()[0])
    header["git_sha"] = "1" * 40
    header["model_id"] = HAIKU
    header["run_id"] = "8c78170b6bf4"
    stale.write_text(json.dumps(header) + "\n", encoding="utf-8")
    before = stale.read_bytes()

    provider = GoldAnsweringProvider(dataset)
    code = challenger.main(
        stage(
            [
                "--live",
                "--stage",
                "a",
                "--provider",
                "bedrock",
                "--model",
                HAIKU,
                "--authorise-paid-inference",
                STAGE_A,
            ],
            sandbox,
        ),
        provider_builder=lambda settings, granted: provider,
    )
    assert code == 2
    assert "cannot be continued" in capsys.readouterr().err
    assert provider.asked == []
    assert stale.read_bytes() == before
    assert OFF_MACHINE_CONNECTIONS == []


# =====================================================================================
# 7. nothing here is armed by default
# =====================================================================================


def test_no_fixture_here_authorises_spending() -> None:
    """Absence, asserted. An autouse grant would rebuild the accident one layer down."""
    import scripts.tests.conftest as conftest

    source = Path(conftest.__file__).read_text(encoding="utf-8")
    assert "AUTHORISE-PAID-INFERENCE" not in source
    assert "authorise(" not in source


def test_neither_parser_defaults_an_authorisation() -> None:
    for parser in (challenger.build_parser(), benchmark.build_parser()):
        namespace = parser.parse_args([])
        assert namespace.live is False
        assert namespace.authorise_paid_inference is None


def test_no_committed_file_carries_a_usable_authorisation() -> None:
    """The phrase may appear in documentation and in help text. It may not appear armed.

    Documented on purpose -- it is an intentionality gate, not a secret -- so what matters is
    that no workflow, script or environment file hands it to a command.
    """
    listed = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            ".github",
            "docker",
            "*.yml",
            "*.yaml",
            "*.sh",
            "*.env",
            ".env.example",
            "docker-compose.yml",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert listed, "the file listing is empty, so this test would pass by checking nothing"
    for name in listed:
        path = ROOT / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "AUTHORISE-PAID-INFERENCE" not in text, name
        assert "authorise-paid-inference" not in text, name


def test_the_off_machine_connection_count_is_zero() -> None:
    """The claim this whole file rests on, as a number rather than an intention."""
    assert OFF_MACHINE_CONNECTIONS == []
