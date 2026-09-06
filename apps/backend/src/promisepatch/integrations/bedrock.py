"""The Amazon Bedrock boundary. The only module in PromisePatch that imports an AWS SDK.

Everything AWS-shaped stops here: boto3, botocore, Converse request dictionaries, the shape of
a `toolUse` block. Above this module the system knows about
:class:`~promisepatch.semantic.provider.SemanticProvider` and typed contracts, which is what
lets the whole test suite, the whole of CI and the whole local Docker stack run with no AWS
account in existence.

**Structured output, never prose parsing.** Every call defines exactly one tool -- the job's
output schema -- and forces it with ``toolChoice``. The model's answer therefore arrives as a
JSON object shaped by the schema, and a response that somehow contains no tool call is a
failure rather than something to run a regular expression over. The tool is an output shape
and nothing else: there is no tool here that changes an order, sends a message, records a
fact or approves anything, and the model is given none.

**The credential chain is the SDK's.** This module reads no AWS file, parses no profile and
holds no key. A local developer authenticates with `AWS_PROFILE` or an SSO session; a deployed
task authenticates with its IAM role. Credentials are resolved when a call is made, not when
settings are parsed, which is what keeps configuration testable and what makes a role-based
deployment the same code as a laptop.

**It cannot write anything.** This module holds no database handle and imports no SQLAlchemy
model -- an import contract forbids it, in the same way and for the same reason as the order
system adapter. It returns values. Whether those values matter is decided elsewhere.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Final, Protocol

from promisepatch.config import Settings
from promisepatch.semantic.errors import (
    SemanticProviderError,
    SemanticTimeoutError,
    SemanticValidationError,
    ValidationFailure,
)
from promisepatch.semantic.jobs import JobSpec
from promisepatch.semantic.provider import (
    Attempt,
    SemanticUsage,
    StructuredSemanticProvider,
    tool_definition,
)

TEMPERATURE: Final = 0.0
"""Sampled as little as the API allows. These are closed-label readings, not writing."""

RETRYABLE_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        "ThrottlingException",
        "TooManyRequestsException",
        "ServiceUnavailableException",
        "ServiceQuotaExceededException",
        "InternalServerException",
        "ModelTimeoutException",
        "ModelNotReadyException",
    }
)
"""Bedrock errors that say nothing about the request. Presenting it again may work.

Everything else -- a denied model, a bad request, an unknown model id -- is terminal here.
Retrying a request the service understood and refused is a way to be refused more expensively.
"""

TIMEOUT_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {"ModelTimeoutException", "RequestTimeout", "RequestTimeoutException"}
)


class ConverseTransport(Protocol):
    """The one call this module makes against AWS.

    Narrow on purpose. boto3's ``bedrock-runtime`` client satisfies it, and so does a stub in
    a test -- which is how the request this module builds is asserted in full without an AWS
    account, and without mocking away the part of the code that is worth testing.
    """

    def converse(self, **kwargs: Any) -> Mapping[str, Any]: ...


class BedrockSemanticProvider(StructuredSemanticProvider):
    """One configured model, reached through Converse with forced tool use.

    Holds a model id and a way to open a client. It does not know what a case is, what an
    order is, or what any of the answers it relays will be used for, and has no way to find
    out.

    **The client is opened on first use, never at construction.** boto3 resolves the whole
    credential chain when a client is created, so building one eagerly would mean a process
    could not start without AWS credentials -- and every process here starts, in CI and in a
    local stack, on machines that have none. Deferring it keeps "which model is configured" a
    settings question and "may this identity call it" a question asked when a call is made,
    which is also exactly how a task role behaves.
    """

    name = "bedrock"

    def __init__(self, *, open_transport: Callable[[], ConverseTransport], model_id: str) -> None:
        self._open_transport = open_transport
        self._opened: ConverseTransport | None = None
        # Twice on purpose. ``model_id`` is the port's telemetry field, which is optional
        # because a provider need not have a model; ``_model_id`` is this provider's own, and
        # a Bedrock client without one does not exist.
        self._model_id = model_id
        self.model_id = model_id

    @classmethod
    def from_settings(cls, settings: Settings) -> BedrockSemanticProvider:
        """The provider this deployment is configured for. Reads settings; opens nothing."""
        region = settings.require_aws_region()
        model_id = settings.require_bedrock_model_id()

        def open_transport() -> ConverseTransport:
            import boto3
            from botocore.config import Config

            config = Config(
                region_name=region,
                retries={"max_attempts": settings.bedrock_max_attempts, "mode": "standard"},
                connect_timeout=settings.bedrock_timeout_seconds,
                read_timeout=settings.bedrock_timeout_seconds,
            )
            client: ConverseTransport = boto3.client(
                "bedrock-runtime", region_name=region, config=config
            )
            return client

        return cls(open_transport=open_transport, model_id=model_id)

    def transport(self) -> ConverseTransport:
        """The client, opened once. Called from the event loop, so there is no race to lose.

        Opening it is where the AWS SDK resolves who we are, so this is where "there is no
        profile", "that profile needs a dependency you have not installed" and "no Region"
        surface. They are configuration, not weather: none of them is retryable, and all of
        them deserve the SDK's own sentence rather than a traceback through a call that never
        reached the network.
        """
        from botocore.exceptions import BotoCoreError, ClientError

        if self._opened is None:
            try:
                self._opened = self._open_transport()
            except (BotoCoreError, ClientError) as error:
                raise SemanticProviderError(
                    f"the AWS SDK could not be prepared for Bedrock: {error}",
                    retryable=False,
                ) from error
        return self._opened

    async def invoke(self, spec: JobSpec, content: str, *, correction: str | None) -> Attempt:
        request = build_converse_request(
            spec, content, model_id=self._model_id, correction=correction
        )
        transport = self.transport()
        # boto3 is synchronous, and this call is the slowest thing in a spoken turn. Off the
        # event loop it goes, so one worker waiting on a model does not stop every other task
        # in the process from making progress.
        response = await asyncio.to_thread(self._call, transport, request)
        return Attempt(payload=extract_tool_input(spec, response), usage=read_usage(response))

    def _call(self, transport: ConverseTransport, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """One Converse call, with every AWS failure translated into a semantic one.

        Nothing above this line should have to know what a ``ClientError`` is, and nothing
        below it decides what a failure means for a case.
        """
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

        try:
            return transport.converse(**request)
        except NoCredentialsError as error:
            # Not retryable and not a network problem: nobody has told the SDK who we are.
            # Named separately because the fix is a profile or a role, not another attempt.
            raise SemanticProviderError(
                "no AWS credentials were available to the SDK for this Bedrock call",
                retryable=False,
            ) from error
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", "")) or type(error).__name__
            if code in TIMEOUT_ERROR_CODES:
                raise SemanticTimeoutError(f"Bedrock timed out: {code}") from error
            raise SemanticProviderError(
                f"Bedrock refused the call: {code}",
                retryable=code in RETRYABLE_ERROR_CODES,
            ) from error
        except BotoCoreError as error:
            name = type(error).__name__
            if "Timeout" in name:
                raise SemanticTimeoutError(f"Bedrock timed out: {name}") from error
            raise SemanticProviderError(
                f"Bedrock is unreachable: {name}", retryable=True
            ) from error


def build_converse_request(
    spec: JobSpec, content: str, *, model_id: str, correction: str | None
) -> dict[str, Any]:
    """The exact Converse payload for one attempt. Pure, so a test can read it in full.

    The instruction is a system block; the person's words are inside a user block. That split
    is the request-level half of the injection posture: whatever a customer wrote arrives
    where user content arrives, never where the rules do.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": content}]}]
    if correction is not None:
        # The rejection is a second user turn rather than an edit of the first. The model can
        # see what it said and why it was refused, and the original question is still the
        # question -- which is what makes one corrective retry worth having at all.
        messages.append({"role": "assistant", "content": [{"text": "(previous answer)"}]})
        messages.append({"role": "user", "content": [{"text": correction}]})

    return {
        "modelId": model_id,
        "system": [{"text": spec.system_instruction}],
        "messages": messages,
        "toolConfig": {
            "tools": [tool_definition(spec)],
            "toolChoice": {"tool": {"name": spec.tool_name}},
        },
        "inferenceConfig": {"temperature": TEMPERATURE, "maxTokens": spec.max_tokens},
    }


def extract_tool_input(spec: JobSpec, response: Mapping[str, Any]) -> object:
    """The tool input the model produced, or a typed failure saying it did not produce one.

    A response with no call to the one tool that was forced is not an answer in a different
    format; it is the model declining the shape of the question. Reading its prose instead
    would be exactly the free-form parsing this boundary exists to avoid.
    """
    message = response.get("output", {}).get("message", {})
    for block in message.get("content", []):
        tool_use = block.get("toolUse") if isinstance(block, Mapping) else None
        if isinstance(tool_use, Mapping) and tool_use.get("name") == spec.tool_name:
            return tool_use.get("input")
    raise SemanticValidationError(
        f"{spec.job.value}: the model did not call {spec.tool_name}",
        category=ValidationFailure.MISSING_TOOL_USE,
    )


def read_usage(response: Mapping[str, Any]) -> SemanticUsage:
    """What the call cost, if Bedrock said. Never load-bearing, so absence is not a failure."""
    usage = response.get("usage") or {}
    metrics = response.get("metrics") or {}
    return SemanticUsage(
        input_tokens=_as_int(usage.get("inputTokens")),
        output_tokens=_as_int(usage.get("outputTokens")),
        latency_ms=_as_int(metrics.get("latencyMs")),
    )


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


__all__ = [
    "RETRYABLE_ERROR_CODES",
    "TEMPERATURE",
    "TIMEOUT_ERROR_CODES",
    "BedrockSemanticProvider",
    "ConverseTransport",
    "build_converse_request",
    "extract_tool_input",
    "read_usage",
]
