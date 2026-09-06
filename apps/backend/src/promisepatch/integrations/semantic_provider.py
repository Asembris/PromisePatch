"""Which semantic provider this deployment has, and the one place a semantic call is logged.

Two small things live here, and both exist so that nothing else has to know them.

**Provider selection happens once.** ``build_semantic_provider(settings)`` is the only place
that reads :attr:`~promisepatch.config.Settings.llm_provider`. No business logic anywhere asks
whether Bedrock is configured, because a rule whose behaviour depends on which provider is
switched on is a rule with two versions and one test.

**Observability wraps rather than threads through.** Every provider is returned wrapped, so a
semantic call is logged the same way whichever one answered, and a provider cannot forget to.

What is logged is deliberately thin: the job, the provider, the model, the outcome, how long
it took, how many attempts it needed, and -- when an answer was refused -- which category of
refusal. Never the worker's sentence, never the customer's reply, never a credential, never a
token. The interesting question about a semantic call is whether the boundary held, and none
of the answers to that require quoting somebody.
"""

from __future__ import annotations

import time

from promisepatch.config import LlmProvider, Settings
from promisepatch.observability import get_logger
from promisepatch.semantic.contracts import SemanticRequest
from promisepatch.semantic.errors import SemanticProviderError, SemanticValidationError
from promisepatch.semantic.fake import FakeSemanticProvider
from promisepatch.semantic.jobs import spec_for
from promisepatch.semantic.provider import SemanticProvider, SemanticResult

logger = get_logger(__name__)


class ObservedSemanticProvider:
    """One provider, with a structured log line per call and no other change in behaviour.

    It adds nothing to the answer and removes nothing from a failure: the same value comes
    back and the same exception propagates. Wall-clock latency is measured here because the
    contracts layer is not allowed to read a clock, and because what an operator wants to know
    is how long the call took from PromisePatch, not how long the model reported spending.
    """

    def __init__(self, inner: SemanticProvider) -> None:
        self._inner = inner
        self.name = inner.name

    async def run(self, request: SemanticRequest) -> SemanticResult:
        spec = spec_for(request)
        started = time.perf_counter()
        fields = {
            "job": spec.job.value,
            "provider": self._inner.name,
            "correlation_id": request.metadata.correlation_id,
            "case_id": request.metadata.case_id,
        }
        try:
            result = await self._inner.run(request)
        except SemanticValidationError as error:
            logger.warning(
                "semantic.rejected",
                **fields,
                outcome="rejected",
                validation_failure=error.category.value,
                latency_ms=_elapsed_ms(started),
            )
            raise
        except SemanticProviderError as error:
            logger.warning(
                "semantic.unavailable",
                **fields,
                outcome="unavailable",
                retryable=error.retryable,
                latency_ms=_elapsed_ms(started),
            )
            raise

        logger.info(
            "semantic.answered",
            **fields,
            outcome="answered",
            model_id=result.telemetry.model_id,
            attempts=result.telemetry.attempts,
            input_tokens=result.telemetry.usage.input_tokens,
            output_tokens=result.telemetry.usage.output_tokens,
            latency_ms=_elapsed_ms(started),
        )
        return result


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def build_semantic_provider(settings: Settings) -> SemanticProvider:
    """The provider this deployment is configured for, wrapped in its observability.

    An unrecognised mode cannot reach here: :class:`~promisepatch.config.LlmProvider` is a
    closed enum, so the failure happens when settings are parsed, with the offending value
    named. The exhaustive match below is what keeps that true when a provider is added.
    """
    match settings.llm_provider:
        case LlmProvider.FAKE:
            return ObservedSemanticProvider(FakeSemanticProvider())
        case LlmProvider.BEDROCK:
            # Imported here rather than at module scope so that a process configured for the
            # fake never loads an AWS SDK it will not use -- which is also what keeps the
            # local stack and CI honest about not needing one installed to run.
            from promisepatch.integrations.bedrock import BedrockSemanticProvider

            return ObservedSemanticProvider(BedrockSemanticProvider.from_settings(settings))


__all__ = ["ObservedSemanticProvider", "build_semantic_provider"]
