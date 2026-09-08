"""How a provider behaves: deterministic answers, one correction, and clean failures.

Every test here runs against the fake, which is the point. The fake and the Bedrock client
share the prompt, the schema, the validator and the retry, so what is proved about the
acceptance path here is proved about the path a real model's answer takes.

No network, no credential, no AWS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest

from promise_graph.model import ExceptionCategory
from promisepatch.config import Environment, LlmProvider, Settings
from promisepatch.domain import customer_intent, semantic_intake, steps
from promisepatch.domain.adapters import FakeEffectAdapter
from promisepatch.domain.approvals import STEP_INTERPRET_CUSTOMER_REPLY
from promisepatch.domain.model import StepResult
from promisepatch.domain.observation import STEP_INTERPRET_SEMANTICALLY
from promisepatch.domain.steps import StepClaim
from promisepatch.integrations import build_semantic_provider, semantic_provider
from promisepatch.integrations.semantic_provider import ObservedSemanticProvider
from promisepatch.semantic import (
    ApparentIntent,
    CandidateResource,
    ClassifyReplyIntentRequest,
    FakeSemanticProvider,
    InterpretUtteranceRequest,
    ObservationInterpretation,
    ReplyIntentReading,
    SemanticJob,
    SemanticMetadata,
    SemanticProvider,
    SemanticProviderError,
    SemanticTimeoutError,
    SemanticValidationError,
    UntrustedText,
)
from promisepatch.semantic.errors import ValidationFailure
from promisepatch.semantic.provider import CORRECTIVE_RETRIES
from promisepatch.worker import Worker

RASPBERRY = CandidateResource(id="res-raspberry", name="raspberries")

GOOD_BINDING = {
    "category": "SUPPLY_NOT_RECEIVED",
    "bindings": [
        {
            "node_type": "RESOURCE",
            "node_id": "res-raspberry",
            "confidence": 0.9,
            "evidence_span": "raspberry",
        }
    ],
}
INVENTED_BINDING = {
    "bindings": [
        {
            "node_type": "RESOURCE",
            "node_id": "res-blueberry",
            "confidence": 1.0,
            "evidence_span": "blueberries",
        }
    ]
}


def observation() -> InterpretUtteranceRequest:
    return InterpretUtteranceRequest(
        utterance=UntrustedText(text="today's raspberry delivery didn't arrive"),
        categories=(ExceptionCategory.SUPPLY_NOT_RECEIVED,),
        resources=(RASPBERRY,),
    )


def reply(text: str = "Strawberries work") -> ClassifyReplyIntentRequest:
    return ClassifyReplyIntentRequest(reply=UntrustedText(text=text))


# ----------------------------------------------------------------------------- the fake


async def test_the_fake_answers_the_same_thing_every_time() -> None:
    """Determinism is the reason it is the default: a suite that varies proves nothing."""
    first = await FakeSemanticProvider().run(reply())
    second = await FakeSemanticProvider().run(reply())
    again = await FakeSemanticProvider().run(reply())
    assert first.value == second.value == again.value
    assert first.telemetry.attempts == 1


async def test_the_fake_claims_nothing_when_nothing_is_scripted() -> None:
    """Its defaults are the cautious answer, so a mis-wired workflow stalls rather than acts."""
    intent = (await FakeSemanticProvider().run(reply())).value
    assert isinstance(intent, ReplyIntentReading)
    assert intent.apparent_intent is ApparentIntent.UNCLEAR
    assert (await FakeSemanticProvider().run(observation())).value == ObservationInterpretation(
        clarification_needed=True
    )


async def test_a_scripted_answer_is_validated_like_any_other() -> None:
    provider = FakeSemanticProvider({SemanticJob.INTERPRET_UTTERANCE: [GOOD_BINDING]})
    result = await provider.run(observation())
    assert isinstance(result.value, ObservationInterpretation)
    assert result.value.bindings[0].node_id == "res-raspberry"
    assert result.telemetry.provider == "fake"
    assert result.telemetry.model_id is None


async def test_the_fake_reports_no_usage_rather_than_inventing_some() -> None:
    result = await FakeSemanticProvider().run(reply())
    assert result.telemetry.usage.input_tokens is None
    assert result.telemetry.usage.latency_ms is None


# ------------------------------------------------------------------------ the one correction


async def test_a_rejected_answer_is_put_back_once_with_the_reason() -> None:
    """The retry is corrective: the second attempt is answering a different question."""
    provider = FakeSemanticProvider(
        {SemanticJob.INTERPRET_UTTERANCE: [{"category": "NOT_A_CATEGORY"}, GOOD_BINDING]}
    )
    result = await provider.run(observation())

    assert result.telemetry.attempts == 2
    assert len(provider.calls) == 2
    assert provider.calls[0].correction is None
    assert provider.calls[1].correction is not None
    assert "rejected" in provider.calls[1].correction
    assert provider.calls[0].content == provider.calls[1].content


async def test_two_bad_answers_are_refused_rather_than_asked_a_third_time() -> None:
    """Bounded, and bounded at one. Repeating until a schema is satisfied is how invention
    becomes accepted data."""
    provider = FakeSemanticProvider(
        {SemanticJob.INTERPRET_UTTERANCE: [INVENTED_BINDING, INVENTED_BINDING, GOOD_BINDING]}
    )
    with pytest.raises(SemanticValidationError) as raised:
        await provider.run(observation())

    assert raised.value.category is ValidationFailure.UNKNOWN_CANDIDATE
    assert len(provider.calls) == CORRECTIVE_RETRIES + 1 == 2


async def test_a_retry_never_turns_an_invented_identifier_into_a_guess() -> None:
    """No branch anywhere drops the offending binding and keeps the rest of the answer."""
    provider = FakeSemanticProvider(
        {SemanticJob.INTERPRET_UTTERANCE: [INVENTED_BINDING, INVENTED_BINDING]}
    )
    with pytest.raises(SemanticValidationError):
        await provider.run(observation())


async def test_an_unsafe_label_survives_neither_attempt() -> None:
    provider = FakeSemanticProvider(
        {SemanticJob.CLASSIFY_REPLY_INTENT: [{"apparent_intent": "APPROVE"}] * 2}
    )
    with pytest.raises(SemanticValidationError) as raised:
        await provider.run(reply())
    assert raised.value.category is ValidationFailure.UNSUPPORTED_VOCABULARY


# -------------------------------------------------------------------------- provider failures


@pytest.mark.parametrize(
    ("failure", "retryable"),
    [
        (SemanticTimeoutError("the model did not answer in time"), True),
        (SemanticProviderError("throttled", retryable=True), True),
        (SemanticProviderError("service unavailable", retryable=True), True),
        (SemanticProviderError("access denied", retryable=False), False),
    ],
)
async def test_a_provider_failure_produces_no_value_at_all(
    failure: SemanticProviderError, retryable: bool
) -> None:
    """A timeout is not an approval, an unclear, or an empty reading. It is a failure."""
    provider = FakeSemanticProvider({SemanticJob.CLASSIFY_REPLY_INTENT: [failure]})
    with pytest.raises(SemanticProviderError) as raised:
        await provider.run(reply())
    assert raised.value.retryable is retryable


async def test_a_transport_failure_is_not_retried_by_the_corrective_bound() -> None:
    """The one retry is for a bad answer. Not having an answer is somebody else's problem."""
    provider = FakeSemanticProvider(
        {SemanticJob.CLASSIFY_REPLY_INTENT: [SemanticTimeoutError("timed out")]}
    )
    with pytest.raises(SemanticTimeoutError):
        await provider.run(reply())
    assert len(provider.calls) == 1


def test_a_rejected_answer_is_not_a_provider_failure() -> None:
    """Different types on purpose: one may be worth retrying later, the other never is."""
    assert not issubclass(SemanticValidationError, SemanticProviderError)
    assert not issubclass(SemanticProviderError, SemanticValidationError)


# ------------------------------------------------------------------------ provider selection


def local_settings(**overrides: object) -> Settings:
    return Settings(env=Environment.LOCAL, log_level="info", **overrides)  # type: ignore[arg-type]


def test_the_fake_is_what_a_deployment_gets_unless_it_says_otherwise() -> None:
    assert Settings.model_fields["llm_provider"].default is LlmProvider.FAKE
    provider = build_semantic_provider(local_settings())
    assert isinstance(provider, SemanticProvider)
    assert provider.name == "fake"


def test_bedrock_is_selected_by_configuration_and_needs_no_credential_to_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Construction resolves no identity. Whether this machine may call the model is a
    question the SDK asks at call time, which is what keeps configuration testable."""
    for variable in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_ACCESS_KEY_ID"):
        monkeypatch.delenv(variable, raising=False)

    provider = build_semantic_provider(local_settings(llm_provider=LlmProvider.BEDROCK))
    assert provider.name == "bedrock"


def test_an_unknown_provider_is_a_configuration_error_before_anything_runs() -> None:
    with pytest.raises(ValueError, match="llm_provider"):
        local_settings(llm_provider="anthropic-direct")


def test_the_fake_needs_no_bedrock_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """No region, no model, no credential: the whole point of the default."""
    monkeypatch.setenv("PP_BEDROCK_MODEL_ID", "")
    monkeypatch.setenv("PP_AWS_REGION", "")
    settings = Settings()
    assert settings.llm_provider is LlmProvider.FAKE
    assert build_semantic_provider(settings).name == "fake"


def test_bedrock_configuration_is_validated_and_names_what_is_missing() -> None:
    blank = local_settings(llm_provider=LlmProvider.BEDROCK, bedrock_model_id="  ", aws_region="")
    with pytest.raises(RuntimeError, match="PP_BEDROCK_MODEL_ID"):
        blank.require_bedrock_model_id()
    with pytest.raises(RuntimeError, match="PP_AWS_REGION"):
        blank.require_aws_region()
    with pytest.raises(RuntimeError, match="PP_AWS_REGION"):
        build_semantic_provider(blank)


def test_settings_parse_without_any_aws_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """Credential resolution belongs to the SDK, at call time. Nothing here reads a key."""
    for variable in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
    ):
        monkeypatch.delenv(variable, raising=False)
    settings = Settings()
    assert settings.bedrock_model_id.startswith("us.amazon.nova-2-lite")
    assert not any("aws_access" in name for name in Settings.model_fields)
    assert not any("credential" in name for name in Settings.model_fields)


def test_the_configured_model_is_the_one_the_architecture_names() -> None:
    """One model, no router, no automatic escalation to a stronger one.

    ADR-0007 names it, amending ADR-0004 on the model identity and on nothing else.
    """
    assert Settings().bedrock_model_id == "us.amazon.nova-2-lite-v1:0"
    assert not any("escalation" in name for name in Settings.model_fields)


def test_the_default_model_is_not_the_one_this_account_cannot_call() -> None:
    """Haiku 4.5 is a supported value of the variable and is not the shipping default.

    Nothing here is a claim about how Haiku reads: its quality was never measured. What was
    measured is access, and the P4.6 record has the Marketplace subscription this account needs
    failing with `INVALID_PAYMENT_INSTRUMENT`. A default naming a model the deployment cannot
    invoke is a configuration error that waits until the first spoken turn to appear.
    """
    assert "haiku" not in Settings().bedrock_model_id.lower()
    # Still buildable when a deployment asks for it by name, because the transport is unchanged.
    configured = local_settings(
        llm_provider=LlmProvider.BEDROCK,
        bedrock_model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    )
    assert configured.require_bedrock_model_id() == "us.anthropic.claude-haiku-4-5-20251001-v1:0"


async def test_both_semantic_jobs_are_answered_by_the_one_configured_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker's sentence and the customer's reply are read by the same provider object.

    This is why selecting a model selects it for both jobs: `Worker` has one provider field and
    no per-job route to point somewhere else. Adding one would be the multi-model routing
    ADR-0004 rejected, and no measured evidence asks for it -- no challenger cleared the frozen
    materiality floor, so there is no better customer model to route to.

    Both `prepare` functions are stood in for here, and so are the claim and the execution, so
    what is asserted is the routing and nothing about a database.
    """
    handed: dict[str, object] = {}

    async def record_worker(_db: object, provider: object, *, claim: StepClaim) -> None:
        handed["worker"] = provider

    async def record_customer(_db: object, provider: object, *, claim: StepClaim) -> None:
        handed["customer"] = provider

    monkeypatch.setattr(semantic_intake, "prepare", record_worker)
    monkeypatch.setattr(customer_intent, "prepare", record_customer)

    kinds = iter((STEP_INTERPRET_SEMANTICALLY, STEP_INTERPRET_CUSTOMER_REPLY))

    async def claim_next(_db: object, *, worker: str, **_: object) -> StepClaim:
        return StepClaim(
            step_id=uuid4(),
            case_id=uuid4(),
            step_key="k",
            kind=next(kinds),
            attempts=1,
            lease_owner=worker,
            lease_expires_at=datetime(2026, 9, 8, tzinfo=UTC),
        )

    async def executed(_db: object, *, claim: StepClaim, actor: object) -> StepResult:
        return StepResult.COMPLETED

    monkeypatch.setattr(steps, "claim_step", claim_next)
    monkeypatch.setattr(steps, "execute_step", executed)

    configured = FakeSemanticProvider()
    worker = Worker(database=cast(Any, None), adapter=FakeEffectAdapter(), semantic=configured)
    await worker._execute_one_step()
    await worker._execute_one_step()

    assert handed["worker"] is configured
    assert handed["customer"] is configured


# ------------------------------------------------------------------------------ observability
#
# Asserted on the fields the provider hands the logger, not on rendered output. The application
# configures structlog with `cache_logger_on_first_use`, so a bound logger keeps whatever
# processors and output stream it was built with -- an in-memory or stdout capture therefore
# observes nothing once anything else in the suite has configured logging, and a test that
# passes alone while proving nothing in the suite is worse than no test. What is worth
# asserting is the payload anyway: a renderer cannot add a customer's words that were never
# passed to it.


@dataclass
class RecordingLogger:
    """Stands where the module's logger stands, and remembers what it was told."""

    entries: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def info(self, event: str, **fields: Any) -> None:
        self.entries.append((event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        self.entries.append((event, fields))


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> RecordingLogger:
    logger = RecordingLogger()
    monkeypatch.setattr(semantic_provider, "logger", logger)
    return logger


async def test_a_successful_call_is_logged_without_quoting_anybody(
    recorded: RecordingLogger,
) -> None:
    provider = ObservedSemanticProvider(FakeSemanticProvider())
    await provider.run(reply("Strawberries work, and my address is 12 Rue Neuve"))

    (event, fields) = recorded.entries[0]
    assert event == "semantic.answered"
    assert fields["job"] == SemanticJob.CLASSIFY_REPLY_INTENT.value
    assert fields["provider"] == "fake"
    assert fields["outcome"] == "answered"
    assert fields["attempts"] == 1
    assert isinstance(fields["latency_ms"], int)
    assert "Rue Neuve" not in json.dumps(fields)


async def test_a_rejected_answer_is_logged_with_the_reason_it_was_rejected(
    recorded: RecordingLogger,
) -> None:
    provider = ObservedSemanticProvider(
        FakeSemanticProvider(
            {SemanticJob.INTERPRET_UTTERANCE: [INVENTED_BINDING, INVENTED_BINDING]}
        )
    )
    with pytest.raises(SemanticValidationError):
        await provider.run(observation())

    (event, fields) = recorded.entries[0]
    assert event == "semantic.rejected"
    assert fields["outcome"] == "rejected"
    assert fields["validation_failure"] == ValidationFailure.UNKNOWN_CANDIDATE.value


async def test_an_unreachable_provider_is_logged_as_unavailable(
    recorded: RecordingLogger,
) -> None:
    provider = ObservedSemanticProvider(
        FakeSemanticProvider({SemanticJob.CLASSIFY_REPLY_INTENT: [SemanticTimeoutError("slow")]})
    )
    with pytest.raises(SemanticTimeoutError):
        await provider.run(reply())

    (event, fields) = recorded.entries[0]
    assert event == "semantic.unavailable"
    assert fields["outcome"] == "unavailable"
    assert fields["retryable"] is True


async def test_correlation_travels_with_the_call_and_not_to_the_model(
    recorded: RecordingLogger,
) -> None:
    provider = ObservedSemanticProvider(FakeSemanticProvider())
    request = ClassifyReplyIntentRequest(
        reply=UntrustedText(text="sounds good to me"),
        metadata=SemanticMetadata(correlation_id="corr-9", case_id="case-9"),
    )
    await provider.run(request)

    (_, fields) = recorded.entries[0]
    assert fields["correlation_id"] == "corr-9"
    assert fields["case_id"] == "case-9"
    assert "sounds good" not in json.dumps(fields)
