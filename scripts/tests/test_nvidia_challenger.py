"""The NVIDIA challenger's composition root: everything it refuses, and what it never calls.

The experiment being wired up here is the one that was already frozen twice. Same dataset, same
stored Nova run, same six failures and six matched controls, same production prompt, same
scorer, same materiality floor. Only the challenger's model and endpoint change -- which is the
whole content of the claim, and the reason so much of this file is about proving that nothing
else did.

Every test ends with no NVIDIA client having existed. ``conftest.py`` refuses any connection
that leaves this machine, so "nothing was called" is enforced by the process rather than
asserted by the author, and :func:`test_the_off_machine_connection_count_is_still_zero` reads
that number back at the end.

Three properties this file is mostly about:

* a valid-looking key and a real base URL change nothing -- what refuses is the harness, not
  the provider, so a plausibly credentialed run still calls nothing;
* the credential is never printed, never persisted and never returned to anything that formats;
* the endpoint is part of the identity, so a run against another host is refused rather than
  recorded under this experiment's name.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pydantic
import pytest
import scripts.run_intent_challenger as challenger
from evals.authorisation import SpendScope, authorise, required_phrase
from evals.budget import BillingMode, BudgetExhaustedError, BudgetGuard, billing_for, price_for
from evals.cases import CustomerCase, EvalSplit
from evals.challenger import ProviderFailureCategory, provider_failure_category
from evals.challenger_report import column_from_results, render_comparison
from evals.dataset import GoldDataset, load_dataset
from evals.prompts import prompt_identity
from evals.results import CaseResult
from evals.runner import LIVE_MODE
from evals.store import ProviderFailureLog, RunHeader, StoreError, read_run
from scripts.tests.conftest import OFF_MACHINE_CONNECTIONS
from scripts.tests.test_openai_challenger import (
    EXPECTED_CONTROLS,
    EXPECTED_FAILURES,
    write_nova_like_source,
)
from scripts.tests.test_spend_interlock import BuilderSpy, GoldAnsweringProvider, reading

from promisepatch.config import LlmProvider, Settings
from promisepatch.semantic import (
    ApparentIntent,
    SemanticJob,
    SemanticProviderError,
    StructuredSemanticProvider,
)
from promisepatch.semantic.jobs import JobSpec
from promisepatch.semantic.provider import Attempt

NEMOTRON = challenger.NEMOTRON_3_SUPER
GPT = challenger.GPT_4O_MINI
NOVA = "us.amazon.nova-2-lite-v1:0"
HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
ENDPOINT = "https://integrate.api.nvidia.com/v1"

STAGE_A = required_phrase(SpendScope.STAGE_A)
STAGE_B = required_phrase(SpendScope.STAGE_B)

FAKE_KEY = "nvapi-test-secret-never-send"
"""A key shaped like a real one and belonging to nobody. It is never sent anywhere."""

FAKE_OPENAI_KEY = "sk-notarealkey-000000000000000000000000000000000000"


@pytest.fixture(scope="module")
def dataset() -> GoldDataset:
    return load_dataset()


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
    """A valid-looking NVIDIA credential and the real endpoint. Both change nothing, on purpose."""
    monkeypatch.setenv(challenger.NVIDIA_API_KEY_VARIABLE, FAKE_KEY)
    monkeypatch.setenv(challenger.NVIDIA_BASE_URL_VARIABLE, ENDPOINT)


@pytest.fixture
def keyless(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No key in the environment and no ``.env`` that could supply one."""
    monkeypatch.delenv(challenger.NVIDIA_API_KEY_VARIABLE, raising=False)
    monkeypatch.delenv(challenger.NVIDIA_BASE_URL_VARIABLE, raising=False)
    monkeypatch.chdir(tmp_path)


def argv(source: Path, *extra: str, stage: str = "a", model: str = NEMOTRON) -> list[str]:
    return [
        "--provider",
        "nvidia",
        "--model",
        model,
        "--stage",
        stage,
        *extra,
        "--source",
        str(source),
    ]


# =====================================================================================
# 1. provider and model identity
# =====================================================================================


def test_the_challenger_is_the_pinned_nemotron_and_the_provider_is_first_class() -> None:
    assert NEMOTRON == "nvidia/nemotron-3-super-120b-a12b"
    assert challenger.NVIDIA == "nvidia"
    assert billing_for("nvidia", NEMOTRON) is not None


@pytest.mark.parametrize(
    "other",
    [
        "nvidia/nemotron-3-nano-30b",
        "nvidia/nemotron-3.5-lightning",
        "nvidia/nemotron-ultra",
        "meta/llama-3.3-70b-instruct",
        "deepseek-ai/deepseek-r1",
        "openai/gpt-oss-120b",
    ],
)
def test_another_nvidia_hosted_model_has_no_billing_terms_and_is_refused(
    sandbox: Path, other: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The endpoint hosts many models. Only the one this experiment names may be run through it."""
    assert billing_for("nvidia", other) is None
    spy = BuilderSpy()
    assert challenger.main(argv(sandbox, model=other), provider_builder=spy) == 2
    assert "billing terms" in capsys.readouterr().err
    assert spy.calls == []


def test_no_two_challengers_share_a_result_file(dataset: GoldDataset) -> None:
    """Result identity, at the level a resumed run actually reads: the path on disk."""
    for path in (challenger.results_path, challenger.failures_path, challenger.selection_path):
        assert len({path(NEMOTRON), path(GPT), path(HAIKU), path(NOVA)}) == 4


def test_the_model_id_names_a_file_rather_than_a_directory() -> None:
    """A vendor-prefixed id carries a separator, and left alone it would put one run's results
    a directory below every other run's -- where the resume check, the attempt log and the
    report would each look somewhere different.
    """
    assert "/" not in challenger.slug(NEMOTRON)
    assert challenger.results_path(NEMOTRON).parent == challenger.RESULTS_DIR
    assert challenger.failures_path(NEMOTRON).parent == challenger.RESULTS_DIR
    assert challenger.selection_path(NEMOTRON).parent == challenger.RESULTS_DIR
    assert challenger.slug(NOVA) == "us.amazon.nova-2-lite-v1_0"


def test_a_run_of_one_provider_or_endpoint_cannot_be_continued_by_another(
    tmp_path: Path, dataset: GoldDataset
) -> None:
    """Provider, model and endpoint are all in the stored identity, so none drifts silently.

    The endpoint is the one this gate added, and it is the one a provider name cannot stand in
    for: the same model id behind a hosted service and behind a local container is two
    measurements, and the compatible protocol makes both reachable the same way.
    """

    def header(provider: str, model_id: str, endpoint: str | None = ENDPOINT) -> RunHeader:
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
            endpoint=endpoint,
        )

    from evals.store import ResultStore

    path = tmp_path / "challenger.jsonl"
    ResultStore(path, header("nvidia", NEMOTRON))

    for provider, model_id, endpoint, expected in (
        ("openai", NEMOTRON, ENDPOINT, "provider"),
        ("bedrock", HAIKU, ENDPOINT, "model_id"),
        ("nvidia", GPT, ENDPOINT, "model_id"),
        ("nvidia", NEMOTRON, "http://localhost:8000/v1", "endpoint"),
        ("nvidia", NEMOTRON, None, "endpoint"),
    ):
        with pytest.raises(StoreError) as error:
            ResultStore(path, header(provider, model_id, endpoint))
        assert expected in str(error.value)


def test_the_existing_providers_keep_recording_no_endpoint_and_stay_continuable(
    tmp_path: Path, dataset: GoldDataset
) -> None:
    """The field was added, and the runs that predate it are unaffected: absent matches absent."""
    assert challenger.endpoint_for("bedrock") is None
    assert challenger.endpoint_for("openai") is None
    assert challenger.endpoint_for("nvidia") == ENDPOINT

    from evals.store import ResultStore

    header = RunHeader(
        run_id="run000000002",
        started_at="2026-09-08T00:00:00+00:00",
        git_sha="0" * 40,
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        prompts=(),
        provider="openai",
        model_id=GPT,
        mode=LIVE_MODE,
        splits=(EvalSplit.DEVELOPMENT.value,),
    )
    path = tmp_path / "openai.jsonl"
    ResultStore(path, header)
    ResultStore(path, header)  # reopened, and not refused
    assert read_run(path)[0].endpoint is None


def test_the_result_header_binds_the_whole_experiment_identity(dataset: GoldDataset) -> None:
    """What a NVIDIA result must be able to say about itself, months later, on its own."""
    header = RunHeader(
        run_id="run000000003",
        started_at="2026-09-08T00:00:00+00:00",
        git_sha="a" * 40,
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        prompts=tuple(
            prompt_identity(job).as_payload()
            for job in (SemanticJob.INTERPRET_UTTERANCE, SemanticJob.CLASSIFY_REPLY_INTENT)
        ),
        provider="nvidia",
        model_id=NEMOTRON,
        mode=LIVE_MODE,
        splits=(EvalSplit.DEVELOPMENT.value,),
        endpoint=challenger.endpoint_for("nvidia"),
        decoding=challenger.decoding_for("nvidia"),
    )
    payload = header.as_payload()
    assert payload["provider"] == "nvidia"
    assert payload["model_id"] == NEMOTRON
    assert payload["endpoint"] == ENDPOINT
    assert payload["dataset_hash"] == dataset.content_hash
    assert payload["git_sha"] == "a" * 40
    assert payload["decoding"] == {
        "temperature": 1.0,
        "top_p": 0.95,
        "reasoning_effort": "none",
    }
    assert len(payload["prompts"]) == 2  # type: ignore[arg-type]
    assert FAKE_KEY not in json.dumps(payload)


# =====================================================================================
# 2. billing is represented honestly, and the paid providers are untouched
# =====================================================================================


def test_the_nvidia_endpoint_is_recorded_as_a_free_trial_and_never_as_a_zero_price() -> None:
    """A ``$0.00`` entry would assert a commercial rate nobody published -- and would make a
    dollar ceiling trivially satisfiable for every call this model ever answers.
    """
    billing = billing_for("nvidia", NEMOTRON)
    assert billing is not None
    assert billing.mode is BillingMode.FREE_HOSTED_TRIAL
    assert billing.price is None
    assert not billing.is_metered
    assert price_for("nvidia", NEMOTRON) is None
    assert "free hosted endpoint" in billing.source


def test_the_paid_providers_keep_their_prices_and_their_dollar_ceilings() -> None:
    """This gate adds a provider. It does not reprice, unmeter or loosen an existing one."""
    for provider, model in (("openai", GPT), ("bedrock", NOVA), ("bedrock", HAIKU)):
        billing = billing_for(provider, model)
        assert billing is not None
        assert billing.mode is BillingMode.METERED
        assert billing.price is not None
        assert billing.price == price_for(provider, model)

    assert challenger.OPENAI_CHALLENGER_CEILING.max_estimated_usd == Decimal("0.03")
    assert challenger.OPENAI_STAGE_A_CEILING.max_estimated_usd == Decimal("0.01")
    assert challenger.CHALLENGER_CEILING.max_estimated_usd == Decimal("0.15")
    assert challenger.STAGE_A_CEILING.max_estimated_usd == Decimal("0.03")


def test_a_free_endpoint_has_no_dollar_meter_and_says_so_rather_than_printing_zero() -> None:
    ceiling = challenger.NVIDIA_CHALLENGER_CEILING
    assert ceiling.max_estimated_usd is None
    assert not ceiling.has_dollar_cap
    assert challenger.NVIDIA_STAGE_A_CEILING.max_estimated_usd is None


def test_a_metered_model_still_refuses_to_start_without_a_price() -> None:
    """The guard the dollar cap provides for paid providers is unchanged by the free one."""
    from evals.budget import EvalBudget, PricingUnavailableError

    with pytest.raises(PricingUnavailableError):
        BudgetGuard(EvalBudget(max_estimated_usd=Decimal("1")), price=None, live=True)


# =====================================================================================
# 3. the ceilings are NVIDIA's own, and they bound calls and tokens
# =====================================================================================


def test_the_nvidia_ceilings_are_the_ones_written_down() -> None:
    ceiling = challenger.NVIDIA_CHALLENGER_CEILING
    assert ceiling.max_calls == 30
    assert ceiling.max_input_tokens == 100_000
    assert ceiling.max_output_tokens == 10_000
    assert challenger.NVIDIA_STAGE_A_CEILING.max_calls == 12


def test_nvidia_stage_a_composes_its_ceiling_with_the_nvidia_global_one() -> None:
    effective = challenger.stage_ceiling("a", "nvidia")
    assert effective.max_calls == 12
    assert effective.max_input_tokens == 100_000
    assert effective.max_output_tokens == 10_000
    assert effective.max_estimated_usd is None


def test_nvidia_stage_b_keeps_the_nvidia_global_ceiling_exactly() -> None:
    assert challenger.stage_ceiling("b", "nvidia") == challenger.NVIDIA_CHALLENGER_CEILING


def test_nvidia_stage_a_cannot_buy_a_thirteenth_call() -> None:
    """Twelve is the selection's own size, and the guard refuses the call that would cross it."""
    guard = BudgetGuard(challenger.stage_ceiling("a", "nvidia"), price=None, live=True)
    for _ in range(12):
        guard.authorise()
    with pytest.raises(BudgetExhaustedError) as error:
        guard.authorise()
    assert "call budget exhausted" in str(error.value)


def test_the_nvidia_global_call_ceiling_cannot_be_exceeded_either() -> None:
    guard = BudgetGuard(challenger.global_ceiling("nvidia"), price=None, live=True)
    for _ in range(30):
        guard.authorise()
    with pytest.raises(BudgetExhaustedError):
        guard.authorise()


def test_the_token_ceilings_bind_a_free_endpoint_because_the_dollar_one_cannot() -> None:
    """What is at risk on a free endpoint is quota, and quota is bounded in tokens."""
    from promisepatch.semantic.provider import SemanticTelemetry, SemanticUsage

    guard = BudgetGuard(challenger.stage_ceiling("a", "nvidia"), price=None, live=True)
    guard.authorise()
    guard.record(
        SemanticTelemetry(
            job=SemanticJob.CLASSIFY_REPLY_INTENT,
            provider="nvidia",
            model_id=NEMOTRON,
            attempts=1,
            usage=SemanticUsage(input_tokens=100_000, output_tokens=1),
        )
    )
    with pytest.raises(BudgetExhaustedError) as error:
        guard.authorise()
    assert "input-token budget exhausted" in str(error.value)


def test_the_nvidia_budget_is_not_an_operator_flag() -> None:
    """Raising a ceiling is an edit to a line in a commit, not something typed at a prompt."""
    flags = challenger.build_parser().format_help()
    for absent in ("--max-calls", "--max-estimated-usd", "--max-input-tokens", "--budget"):
        assert absent not in flags


def test_one_challengers_usage_never_debits_anothers_allowance(tmp_path: Path) -> None:
    """Provider *and* model, in both directions. A shared history would make one model's
    discontinued attempt keep paying for another's allowance for ever.
    """
    from evals.budget import CostLedgerEntry, append_to_ledger, ledger_totals

    ledger = tmp_path / "cost-ledger.jsonl"
    for provider, model, calls in (
        ("openai", GPT, 7),
        ("nvidia", NEMOTRON, 5),
        ("bedrock", NOVA, 3),
    ):
        append_to_ledger(
            ledger,
            CostLedgerEntry(
                run_id=f"run-{provider}",
                recorded_at="2026-09-08T00:00:00+00:00",
                git_sha="0" * 40,
                dataset_version="1.0.0",
                dataset_hash="hash",
                provider=provider,
                model_id=model,
                mode=LIVE_MODE,
                calls=calls,
                attempts=calls,
                input_tokens=10,
                output_tokens=1,
                estimated_usd="0.001",
                pricing_snapshot=None,
            ),
        )

    assert ledger_totals(ledger, mode=LIVE_MODE, provider="nvidia", model_id=NEMOTRON).calls == 5
    assert ledger_totals(ledger, mode=LIVE_MODE, provider="openai", model_id=GPT).calls == 7
    assert ledger_totals(ledger, mode=LIVE_MODE, provider="nvidia", model_id=GPT).calls == 0
    assert ledger_totals(ledger, mode=LIVE_MODE, provider="openai", model_id=NEMOTRON).calls == 0


# =====================================================================================
# 4. authorisation: --live is not permission, and no scope carries to another
# =====================================================================================


def test_live_without_an_authorisation_refuses_before_any_provider_exists(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    spy = BuilderSpy()
    assert challenger.main(argv(sandbox, "--live"), provider_builder=spy) == 2
    assert "does not authorise a charge" in capsys.readouterr().err
    assert spy.calls == []


def test_a_fully_authorised_nvidia_run_still_cannot_reach_the_default_builder(
    sandbox: Path, keyed: None
) -> None:
    """The interlock that does not depend on the operator: a pytest process builds no provider."""
    from evals.authorisation import SpendNotAuthorisedError

    target = challenger.ChallengerTarget(
        provider="nvidia",
        model_id=NEMOTRON,
        region=None,
        settings=Settings(),
        api_key=FAKE_KEY,
        base_url=ENDPOINT,
    )
    granted = authorise(STAGE_A, SpendScope.STAGE_A)
    for builder in (challenger.nvidia_provider, challenger.paid_provider):
        with pytest.raises(SpendNotAuthorisedError):
            builder(target, granted)


def test_a_stage_a_phrase_cannot_buy_nvidia_stage_b(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    spy = BuilderSpy()
    assert (
        challenger.main(
            argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A, stage="b"),
            provider_builder=spy,
        )
        == 2
    )
    assert "does not name STAGE-B" in capsys.readouterr().err
    assert spy.calls == []


def test_an_authorisation_names_a_scope_and_not_a_provider(sandbox: Path, keyed: None) -> None:
    """One authorisation opens one stage. It does not open the other stage for any provider,
    and every provider's Stage A is gated by the same typed phrase rather than by a default.
    """
    granted = authorise(STAGE_A, SpendScope.STAGE_A)
    granted.require(SpendScope.STAGE_A)
    from evals.authorisation import SpendNotAuthorisedError

    with pytest.raises(SpendNotAuthorisedError):
        granted.require(SpendScope.STAGE_B)


def test_neither_providers_authorisation_is_produced_without_the_phrase() -> None:
    """A run that could authorise itself from an OpenAI-shaped environment, or from nothing at
    all, is what this gate exists to prevent. The phrase is typed or there is no authorisation.
    """
    from evals.authorisation import SpendNotAuthorisedError

    for phrase in (None, "", "yes", STAGE_B, "AUTHORISE-PAID-INFERENCE"):
        with pytest.raises(SpendNotAuthorisedError):
            authorise(phrase, SpendScope.STAGE_A)


def test_an_authorisation_without_the_live_flag_is_an_incoherent_command(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    spy = BuilderSpy()
    assert (
        challenger.main(argv(sandbox, "--authorise-paid-inference", STAGE_A), provider_builder=spy)
        == 2
    )
    assert "without --live" in capsys.readouterr().err
    assert spy.calls == []


# =====================================================================================
# 5. the credential, and the endpoint
# =====================================================================================


def test_a_missing_key_refuses_before_the_provider_and_falls_back_to_nothing(
    sandbox: Path, keyless: None, capsys: pytest.CaptureFixture[str]
) -> None:
    spy = BuilderSpy()
    assert (
        challenger.main(
            argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A), provider_builder=spy
        )
        == 2
    )
    error = capsys.readouterr().err
    assert challenger.NVIDIA_API_KEY_VARIABLE in error
    assert "does not fall back" in error
    assert spy.calls == []


def test_the_key_is_read_from_the_environment_or_a_local_env_file_and_from_nowhere_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(challenger.NVIDIA_API_KEY_VARIABLE, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        f"# a comment\nUNRELATED=x\n{challenger.NVIDIA_API_KEY_VARIABLE}={FAKE_KEY}\n",
        encoding="utf-8",
    )
    assert challenger.read_env_value(challenger.NVIDIA_API_KEY_VARIABLE, env) == FAKE_KEY
    assert challenger.read_env_value("NOTHING_LIKE_THIS", env) is None

    monkeypatch.setenv(challenger.NVIDIA_API_KEY_VARIABLE, "from-the-environment")
    assert (
        challenger.read_env_value(challenger.NVIDIA_API_KEY_VARIABLE, env) == "from-the-environment"
    )


def test_an_empty_value_is_not_a_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(challenger.NVIDIA_API_KEY_VARIABLE, raising=False)
    env = tmp_path / ".env"
    env.write_text(f"{challenger.NVIDIA_API_KEY_VARIABLE}=\n", encoding="utf-8")
    assert challenger.read_env_value(challenger.NVIDIA_API_KEY_VARIABLE, env) is None
    assert challenger.api_key_present("nvidia", env) is False


def test_one_providers_key_is_never_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two variables, two providers. A run with only one credential cannot reach the other."""
    monkeypatch.delenv(challenger.NVIDIA_API_KEY_VARIABLE, raising=False)
    monkeypatch.delenv(challenger.API_KEY_VARIABLE, raising=False)
    env = tmp_path / ".env"
    env.write_text(f"{challenger.API_KEY_VARIABLE}={FAKE_OPENAI_KEY}\n", encoding="utf-8")
    assert challenger.api_key_present("openai", env) is True
    assert challenger.api_key_present("nvidia", env) is False
    assert challenger.api_key_for("bedrock", env) is None


def test_an_unset_base_url_defaults_to_the_documented_endpoint_and_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented policy: unset is not an error, because the default *is* the only endpoint
    this experiment would be allowed to use. A configured other one is the failure that matters.
    """
    monkeypatch.delenv(challenger.NVIDIA_BASE_URL_VARIABLE, raising=False)
    monkeypatch.chdir(tmp_path)
    assert challenger.nvidia_base_url() == ENDPOINT
    assert challenger.nvidia_base_url_present() is False
    challenger.refuse_a_foreign_nvidia_endpoint("nvidia")  # does not raise


@pytest.mark.parametrize(
    "foreign",
    [
        "http://localhost:8000/v1",
        "http://127.0.0.1:11434/v1",
        "https://api.openai.com/v1",
        "https://nim.partner.example.com/v1",
    ],
)
def test_a_configured_foreign_endpoint_is_refused_before_the_provider(
    sandbox: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    foreign: str,
) -> None:
    """A local NIM, Ollama, a proxy or a partner deployment could all answer to this model name.
    None of them may be recorded under this experiment's identity.
    """
    monkeypatch.setenv(challenger.NVIDIA_API_KEY_VARIABLE, FAKE_KEY)
    monkeypatch.setenv(challenger.NVIDIA_BASE_URL_VARIABLE, foreign)
    spy = BuilderSpy()
    assert (
        challenger.main(
            argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A), provider_builder=spy
        )
        == 2
    )
    error = capsys.readouterr().err
    assert "hosted NIM endpoint" in error
    assert spy.calls == []


def test_the_endpoint_check_does_not_apply_to_the_other_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(challenger.NVIDIA_BASE_URL_VARIABLE, "http://localhost:8000/v1")
    challenger.refuse_a_foreign_nvidia_endpoint("openai")
    challenger.refuse_a_foreign_nvidia_endpoint("bedrock")


def test_the_composition_root_and_the_adapter_share_one_endpoint_constant() -> None:
    """Two copies of a URL would drift, and the drift would be invisible until a wrong number."""
    from promisepatch.integrations.nvidia import HOSTED_BASE_URL

    assert challenger.nvidia_hosted_endpoint() == HOSTED_BASE_URL == ENDPOINT


def test_no_printed_output_or_stored_artifact_ever_carries_the_key(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Plan and refusal paths, with a plausible key present. Everything visible is a boolean."""
    challenger.main(argv(sandbox))
    plan = capsys.readouterr()
    challenger.main(argv(sandbox, model="nvidia/nemotron-3-nano-30b"))
    refusal = capsys.readouterr()

    written = "".join(
        path.read_text(encoding="utf-8")
        for path in challenger.RESULTS_DIR.rglob("*")
        if path.is_file()
    )
    for text in (plan.out, plan.err, refusal.out, refusal.err, written):
        assert FAKE_KEY not in text
        assert "nvapi-" not in text
        assert "Authorization" not in text

    assert "NVIDIA_API_KEY present           true" in plan.out
    assert OFF_MACHINE_CONNECTIONS == []


# =====================================================================================
# 6. the zero-call plan
# =====================================================================================


def test_the_plan_names_the_provider_the_model_the_endpoint_and_both_ceilings(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert challenger.main(argv(sandbox)) == 0
    printed = capsys.readouterr().out

    assert "provider                   nvidia" in printed
    assert f"model / inference profile  {NEMOTRON}" in printed
    assert "billing                    free_hosted_trial" in printed
    assert "free hosted trial" in printed
    assert "PLAN ONLY" in printed
    assert "  provider                     nvidia" in printed
    assert "global challenger ceiling    30 call(s) / no dollar cap" in printed
    assert "stage A ceiling              12 call(s) / no dollar cap" in printed
    assert "token ceilings               100000 in / 10000 out" in printed
    assert "$None" not in printed


def test_the_plan_counts_what_it_did_not_do(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every line is a number read off a value, or off a code path this run did not take."""
    assert challenger.main(argv(sandbox)) == 0
    printed = capsys.readouterr().out

    for line in (
        "challenger provider              nvidia",
        f"challenger model                 {NEMOTRON}",
        f"endpoint                         {ENDPOINT}",
        "endpoint is the intended one     true",
        "reasoning                        disabled (reasoning_effort=none)",
        "sampling                         temperature 1.0 / top_p 0.95",
        "stage A cases                    12",
        "worker cases                     0",
        "holdout cases                    0",
        "challenger model calls           0",
        "source (challenged) model calls  0",
        "provider clients constructed     0",
        "NVIDIA_API_KEY present           true",
    ):
        assert line in printed
    assert OFF_MACHINE_CONNECTIONS == []


def test_the_plan_needs_no_key_at_all(
    sandbox: Path, keyless: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """A plan reaches nothing, so it refuses nothing. The credential line simply says false."""
    assert challenger.main(argv(sandbox)) == 0
    printed = capsys.readouterr().out
    assert "NVIDIA_API_KEY present           false" in printed
    assert "PLAN ONLY" in printed


def test_a_plan_loads_no_vendor_sdk_in_a_fresh_interpreter(sandbox: Path) -> None:
    """The deferred imports, checked in a process that has not already loaded anything."""
    import subprocess
    import sys

    script = (
        "import sys;"
        "import scripts.run_intent_challenger as c;"
        "c.RESULTS_DIR=__import__('pathlib').Path(sys.argv[1]);"
        "c.LEDGER=c.RESULTS_DIR/'ledger.jsonl';"
        "code=c.main(['--provider','nvidia','--model',sys.argv[2],'--stage','a',"
        "'--source',sys.argv[3]]);"
        "print('SDK' if ('openai' in sys.modules or 'boto3' in sys.modules) else 'NO-SDK');"
        "sys.exit(code)"
    )
    finished = subprocess.run(
        [sys.executable, "-c", script, str(sandbox.parent), NEMOTRON, str(sandbox)],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        check=False,
    )
    assert finished.returncode == 0, finished.stderr
    assert "NO-SDK" in finished.stdout
    assert "provider clients constructed     0" in finished.stdout


def test_the_plan_records_no_region_for_a_provider_that_has_none(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """A Region is a Bedrock fact. Writing ``us-east-1`` here would be a fact that is not one."""
    assert challenger.main(argv(sandbox)) == 0
    assert "region                     not applicable" in capsys.readouterr().out


# =====================================================================================
# 7. the selection is the frozen one, and it comes from Nova
# =====================================================================================


def test_the_stage_a_selection_is_the_same_twelve_cases_as_before(
    sandbox: Path, dataset: GoldDataset, keyed: None
) -> None:
    """A paired experiment that re-matched its controls per challenger would not be paired."""
    assert challenger.main(argv(sandbox)) == 0
    payload = json.loads(challenger.selection_path(NEMOTRON).read_text(encoding="utf-8"))
    failures = tuple(sorted(pair["failure_case_id"] for pair in payload["pairs"]))
    controls = tuple(sorted(pair["control_case_id"] for pair in payload["pairs"]))

    assert failures == tuple(sorted(EXPECTED_FAILURES))
    assert controls == tuple(sorted(EXPECTED_CONTROLS))
    assert len(set(failures) | set(controls)) == 12
    assert payload["challenger_model_id"] == NEMOTRON


def test_the_selection_is_computed_from_nova_and_not_from_the_previous_challenger(
    sandbox: Path, dataset: GoldDataset, keyed: None
) -> None:
    """The primary pairing stays Nova's, so two challengers remain comparable with each other."""
    assert challenger.main(argv(sandbox)) == 0
    payload = json.loads(challenger.selection_path(NEMOTRON).read_text(encoding="utf-8"))
    assert payload["source_model_id"] == NOVA
    assert GPT not in json.dumps(payload)


def test_a_worker_case_cannot_reach_the_nvidia_provider(dataset: GoldDataset) -> None:
    from evals.dataset import GoldDataset as Gold

    with pytest.raises(challenger.ChallengerRefusedError) as error:
        challenger.refuse_ineligible_cases(
            Gold(
                version=dataset.version,
                worker=dataset.worker[:1],
                customer=tuple(c for c in dataset.customer if c.split is EvalSplit.DEVELOPMENT)[:1],
                provenance=dataset.provenance,
            )
        )
    assert "worker case" in str(error.value)


def test_a_holdout_case_cannot_reach_the_nvidia_provider(dataset: GoldDataset) -> None:
    from evals.dataset import GoldDataset as Gold

    holdout = tuple(c for c in dataset.customer if c.split is not EvalSplit.DEVELOPMENT)[:1]
    with pytest.raises(challenger.ChallengerRefusedError) as error:
        challenger.refuse_ineligible_cases(
            Gold(
                version=dataset.version,
                worker=(),
                customer=holdout,
                provenance=dataset.provenance,
            )
        )
    assert "holdout" in str(error.value)


def test_there_is_still_no_flag_that_opens_the_holdout_or_re_runs_the_source() -> None:
    flags = challenger.build_parser().format_help()
    for absent in ("--holdout", "--split", "--rerun-source", "--all-cases"):
        assert absent not in flags


# =====================================================================================
# 8. no evaluation field reaches the model
# =====================================================================================


def test_changing_a_gold_label_a_split_a_tag_or_a_role_does_not_change_the_request(
    dataset: GoldDataset,
) -> None:
    """The leakage guarantee stated positively: none of them is an input to the request."""
    from evals.cases import to_model_input

    from promisepatch.integrations.nvidia import NEMOTRON_DECODING
    from promisepatch.integrations.openai import build_chat_request
    from promisepatch.semantic.jobs import JOB_SPECS
    from promisepatch.semantic.prompts import build_user_content

    case = next(c for c in dataset.customer if c.id == "customer.approve.terse.001")
    spec = JOB_SPECS[SemanticJob.CLASSIFY_REPLY_INTENT]

    def request_for(subject: CustomerCase) -> dict[str, object]:
        return build_chat_request(
            spec,
            build_user_content(to_model_input(subject).request),
            model_id=NEMOTRON,
            correction=None,
            decoding=NEMOTRON_DECODING,
        )

    baseline = request_for(case)
    for altered in (
        case.model_copy(update={"expected": ApparentIntent.APPARENT_DECLINE}),
        case.model_copy(update={"split": EvalSplit.HOLDOUT}),
        case.model_copy(update={"tags": ("something_else",)}),
    ):
        assert request_for(altered) == baseline

    serialised = json.dumps(baseline)
    for forbidden in ("APPARENT_DECLINE_EXPECTED", "holdout", "terse_assent", "control"):
        assert forbidden not in serialised


def test_the_request_for_the_canonical_case_is_the_reply_and_nothing_more(
    dataset: GoldDataset,
) -> None:
    """ "Strawberries work" reaches the model as a customer reply and by no special path."""
    from evals.cases import to_model_input

    from promisepatch.integrations.nvidia import NEMOTRON_DECODING
    from promisepatch.integrations.openai import build_chat_request
    from promisepatch.semantic.jobs import JOB_SPECS
    from promisepatch.semantic.prompts import build_user_content

    case = next(c for c in dataset.customer if c.id == "customer.approve.terse.001")
    assert case.reply == "Strawberries work"

    request = build_chat_request(
        JOB_SPECS[SemanticJob.CLASSIFY_REPLY_INTENT],
        build_user_content(to_model_input(case).request),
        model_id=NEMOTRON,
        correction=None,
        decoding=NEMOTRON_DECODING,
    )
    assert "Strawberries work" in json.dumps(request["messages"][1])
    assert "Strawberries" not in json.dumps(request["messages"][0])
    assert "Strawberries" not in json.dumps(request["tools"])
    assert case.expected is ApparentIntent.APPARENT_APPROVE


# =====================================================================================
# 9. provider failures are execution facts, never readings
# =====================================================================================


class FailingNvidiaProvider(StructuredSemanticProvider):
    """Reached, and answers nothing -- the way a rejected key or a spent quota behaves."""

    name = "nvidia"
    model_id = NEMOTRON

    def __init__(self, error: SemanticProviderError) -> None:
        self._error = error
        self.attempts = 0

    async def invoke(self, spec: JobSpec, content: str, *, correction: str | None) -> Attempt:
        self.attempts += 1
        raise self._error


@pytest.mark.parametrize(
    ("class_name", "category"),
    [
        ("NvidiaAuthenticationError", ProviderFailureCategory.AUTHENTICATION),
        ("NvidiaPermissionError", ProviderFailureCategory.PERMISSION),
        ("NvidiaRateLimitError", ProviderFailureCategory.RATE_LIMITED),
        ("NvidiaInvalidRequestError", ProviderFailureCategory.INVALID_REQUEST),
        ("NvidiaUnavailableError", ProviderFailureCategory.PROVIDER_UNAVAILABLE),
        ("NvidiaEndpointError", ProviderFailureCategory.INVALID_REQUEST),
        ("SemanticTimeoutError", ProviderFailureCategory.TIMEOUT),
        ("SomethingNobodyHasSeen", ProviderFailureCategory.UNKNOWN_PROVIDER_FAILURE),
    ],
)
def test_each_transport_failure_normalises_to_a_category_and_never_to_a_label(
    dataset: GoldDataset, class_name: str, category: ProviderFailureCategory
) -> None:
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
        provider="nvidia",
        model_id=NEMOTRON,
        error_category=class_name,
        provider_error=True,
    )
    assert provider_failure_category(result) is category
    assert result.observed == {}
    assert not result.has_reading


def test_a_stage_stopped_by_nvidia_failures_reports_no_quality_verdict(
    sandbox: Path, dataset: GoldDataset, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """Three refusals stop the stage, and an outage is never a challenger's answer."""
    from promisepatch.integrations.nvidia import NvidiaRateLimitError

    provider = FailingNvidiaProvider(NvidiaRateLimitError("NVIDIA throttled: 429"))
    code = challenger.main(
        argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A),
        provider_builder=lambda target, granted: provider,
    )
    printed = capsys.readouterr().out

    assert code == 1
    assert "STAGE A INVALID FOR A QUALITY DECISION - EXECUTION FAILURE" in printed
    assert "NOT MEASURED" in printed
    assert "CHALLENGER NOT MATERIAL" not in printed
    assert "TARGETED CHALLENGER STOPPED" not in printed
    assert OFF_MACHINE_CONNECTIONS == []


def test_the_failed_nvidia_attempts_are_kept_out_of_the_readings_file(
    sandbox: Path, dataset: GoldDataset, keyed: None
) -> None:
    """An outage written into the readings file would be replayed for ever as an answer."""
    from promisepatch.integrations.nvidia import NvidiaUnavailableError

    challenger.main(
        argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A),
        provider_builder=lambda target, granted: FailingNvidiaProvider(
            NvidiaUnavailableError("NVIDIA is unreachable: APIConnectionError")
        ),
    )
    log = ProviderFailureLog(challenger.failures_path(NEMOTRON))
    assert log.records
    assert all(record.provider == "nvidia" for record in log.records)
    assert all(record.model_id == NEMOTRON for record in log.records)
    assert all(record.category == "NvidiaUnavailableError" for record in log.records)

    readings = challenger.results_path(NEMOTRON)
    if readings.exists():
        _, results = read_run(readings)
        assert results == ()

    written = log.path.read_text(encoding="utf-8")
    assert FAKE_KEY not in written
    assert "Authorization" not in written


# =====================================================================================
# 10. the orchestration, against a provider handed in
# =====================================================================================


class GoldAnsweringNvidia(GoldAnsweringProvider):
    """The gold-answering fake, wearing the NVIDIA identity so the store agrees with itself."""

    name = "nvidia"
    model_id = NEMOTRON


def test_an_authorised_nvidia_stage_a_runs_and_stops_there(
    sandbox: Path, dataset: GoldDataset, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole orchestration, offline, against a provider handed in. Stage B is not entered."""
    provider = GoldAnsweringNvidia(dataset)
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


def test_a_passed_nvidia_stage_a_does_not_open_stage_b_without_its_own_authorisation(
    sandbox: Path, dataset: GoldDataset, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        challenger.main(
            argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A),
            provider_builder=lambda target, granted: GoldAnsweringNvidia(dataset),
        )
        == 0
    )
    capsys.readouterr()

    spy = BuilderSpy()
    assert challenger.main(argv(sandbox, "--live", stage="b"), provider_builder=spy) == 2
    assert "does not authorise a charge" in capsys.readouterr().err
    assert spy.calls == []


def test_nvidia_stage_b_is_refused_before_any_provider_when_stage_a_bought_nothing(
    sandbox: Path, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
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


def test_a_report_rebuilds_from_stored_nvidia_evidence_with_no_call(
    sandbox: Path, dataset: GoldDataset, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The builder raises if touched, and it is never touched."""
    assert (
        challenger.main(
            argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A),
            provider_builder=lambda target, granted: GoldAnsweringNvidia(dataset),
        )
        == 0
    )
    capsys.readouterr()

    spy = BuilderSpy()
    code = challenger.main(
        [
            "--from-results",
            str(challenger.results_path(NEMOTRON)),
            "--source",
            str(sandbox),
        ],
        provider_builder=spy,
    )
    printed = capsys.readouterr().out
    assert code == 0
    assert "Rebuilt from" in printed
    assert "zero provider calls" in printed
    assert spy.calls == []
    assert OFF_MACHINE_CONNECTIONS == []


def test_a_rebuild_can_place_an_earlier_challenger_beside_this_one_and_still_call_nothing(
    sandbox: Path, dataset: GoldDataset, keyed: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--compare-with`` reads a second stored run and adds a column. It buys nothing."""
    assert (
        challenger.main(
            argv(sandbox, "--live", "--authorise-paid-inference", STAGE_A),
            provider_builder=lambda target, granted: GoldAnsweringNvidia(dataset),
        )
        == 0
    )
    capsys.readouterr()

    prior = write_prior_challenger(
        challenger.RESULTS_DIR / "challenger-prior.jsonl",
        dataset,
        model_id=GPT,
        correct=frozenset(EXPECTED_CONTROLS),
    )
    spy = BuilderSpy()
    code = challenger.main(
        [
            "--from-results",
            str(challenger.results_path(NEMOTRON)),
            "--source",
            str(sandbox),
            "--compare-with",
            str(prior),
        ],
        provider_builder=spy,
    )
    printed = capsys.readouterr().out

    assert code == 0
    assert "STAGE-A COMPARISON" in printed
    assert GPT[-15:] in printed
    assert spy.calls == []
    assert OFF_MACHINE_CONNECTIONS == []


def test_a_comparison_column_measured_against_other_labels_is_refused(
    sandbox: Path, dataset: GoldDataset, keyed: None
) -> None:
    """A column from another dataset would put a number in a table about a different experiment."""
    prior = write_prior_challenger(
        challenger.RESULTS_DIR / "challenger-foreign.jsonl",
        dataset,
        model_id=GPT,
        correct=frozenset(EXPECTED_CONTROLS),
        dataset_hash="0" * 64,
    )
    with pytest.raises(challenger.ChallengerRefusedError, match="same labels"):
        challenger.prior_columns([str(prior)], dataset)

    with pytest.raises(challenger.ChallengerRefusedError, match="does not exist"):
        challenger.prior_columns([str(sandbox.parent / "nothing.jsonl")], dataset)


def write_prior_challenger(
    path: Path,
    dataset: GoldDataset,
    *,
    model_id: str,
    correct: frozenset[str],
    dataset_hash: str | None = None,
) -> Path:
    """An earlier challenger's stored run, invented here. No model was asked anything for it."""
    from evals.store import ResultStore

    header = RunHeader(
        run_id="prior0000001",
        started_at="2026-09-08T00:00:00+00:00",
        git_sha="0" * 40,
        dataset_version=dataset.version,
        dataset_hash=dataset_hash or dataset.content_hash,
        prompts=(),
        provider="openai",
        model_id=model_id,
        mode=LIVE_MODE,
        splits=(EvalSplit.DEVELOPMENT.value,),
    )
    store = ResultStore(path, header)
    for result in scripted(dataset, correct):
        store.record(result)
    return path


# =====================================================================================
# 11. the comparative report, on scripted answers
# =====================================================================================


def scripted(dataset: GoldDataset, correct: frozenset[str]) -> tuple[CaseResult, ...]:
    """A challenger's twelve answers, invented here and never bought from anybody.

    No live data exists for this model and none is produced by this gate. These readings exercise
    the report's arithmetic; they are not evidence about any model and are never written to
    ``.eval-results``.
    """
    selected = set(EXPECTED_FAILURES) | set(EXPECTED_CONTROLS)
    results = []
    for case in dataset.customer:
        if case.id not in selected:
            continue
        if case.id in correct:
            predicted = case.expected
        else:
            predicted = next(label for label in ApparentIntent if label is not case.expected)
        results.append(reading(case, predicted))
    return tuple(results)


def test_the_comparison_shows_every_challenger_against_one_unchanged_pairing(
    sandbox: Path, dataset: GoldDataset
) -> None:
    """Three columns, one set of outcomes, and the outcomes are the challenger's against Nova."""
    from evals.challenger import build_stage_a, select_stage_a

    full = dataset
    source = challenger.load_source(sandbox, full)
    selection = select_stage_a(full, source)

    gpt_correct = frozenset(
        set(EXPECTED_CONTROLS) | {"customer.decline.indirect.005", "customer.decline.terse.003"}
    )
    nemotron_correct = frozenset(
        set(EXPECTED_CONTROLS)
        | {
            "customer.approve.terse.001",
            "customer.approve.terse.007",
            "customer.decline.indirect.005",
            "customer.unclear.injection.003",
        }
    )
    outcome = build_stage_a(full, selection, source, scripted(full, nemotron_correct))
    priors = (column_from_results(GPT, GPT, scripted(full, gpt_correct)),)

    rendered = render_comparison(outcome, challenger_label=NEMOTRON, priors=priors)

    assert "STAGE-A COMPARISON" in rendered
    for case_id in (*EXPECTED_FAILURES, *EXPECTED_CONTROLS):
        assert case_id in rendered
    assert "REPAIRED" in rendered
    assert "UNCHANGED_FAILURE" in rendered
    assert "repairs/6" in rendered
    # Four of Nova's six failures read correctly by the scripted challenger; two by the prior.
    assert "approve-side" in rendered
    assert "decline-side" in rendered


def test_a_prior_column_defines_no_outcome_and_no_threshold(dataset: GoldDataset) -> None:
    """Repairs stay defined against the model being challenged, whichever challenger ran first."""
    from evals.challenger import (
        STAGE_A_MATERIALITY,
        build_stage_a,
        evaluate_materiality,
        select_stage_a,
    )

    full = dataset
    source = challenger.load_source(_source_path(full), full)
    selection = select_stage_a(full, source)
    correct = frozenset(set(EXPECTED_CONTROLS) | set(EXPECTED_FAILURES))
    outcome = build_stage_a(full, selection, source, scripted(full, correct))

    without = render_comparison(outcome, challenger_label=NEMOTRON)
    with_prior = render_comparison(
        outcome,
        challenger_label=NEMOTRON,
        priors=(column_from_results(GPT, GPT, scripted(full, frozenset())),),
    )
    assert evaluate_materiality(outcome).passed
    assert STAGE_A_MATERIALITY.min_repair_rate == 0.5
    for line in without.splitlines():
        if "REPAIRED" in line:
            assert line.split()[0] in with_prior


_SOURCE_HOLDER: dict[str, Path] = {}


def _source_path(dataset: GoldDataset) -> Path:
    """A Nova-like source written once for the tests that need one outside the sandbox."""
    import tempfile

    if "path" not in _SOURCE_HOLDER:
        directory = Path(tempfile.mkdtemp())
        path = directory / "development-nova.jsonl"
        write_nova_like_source(path, dataset)
        _SOURCE_HOLDER["path"] = path
    return _SOURCE_HOLDER["path"]


# =====================================================================================
# 12. production is untouched
# =====================================================================================


def test_no_runtime_setting_can_route_a_deployment_to_nvidia() -> None:
    """The runtime's routing surface is the enum, and this gate did not widen it."""
    assert "nvidia" not in {member.value for member in LlmProvider}
    assert "openai" not in {member.value for member in LlmProvider}
    with pytest.raises(pydantic.ValidationError):
        Settings(llm_provider="nvidia")


def test_the_settings_handed_to_the_nvidia_builder_configure_nothing(
    sandbox: Path, keyed: None
) -> None:
    """Handing it a Bedrock-configured object would be a lie in the value that says what a
    deployment is. It is handed an unconfigured one it does not read.
    """
    namespace = challenger.build_parser().parse_args(argv(sandbox))
    settings = challenger._settings_for(namespace)
    assert settings.llm_provider is not None
    assert settings.bedrock_model_id != NEMOTRON


def test_the_off_machine_connection_count_is_still_zero() -> None:
    """The number this whole file rests on. Nothing here reached NVIDIA, OpenAI or AWS."""
    assert OFF_MACHINE_CONNECTIONS == []
