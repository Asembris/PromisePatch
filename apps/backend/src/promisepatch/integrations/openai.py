"""The OpenAI boundary. The only module in PromisePatch that imports the OpenAI SDK.

A transport adapter and nothing else. It holds a model id, a key it was handed, and the
knowledge of how one Chat Completions call is shaped -- and it holds no prompt, no schema, no
vocabulary and no idea what any of the answers it relays are for.

**It reuses production's semantic contract rather than restating it.** The system instruction
comes from :meth:`~promisepatch.semantic.jobs.JobSpec.system_instruction`, the user content
from :func:`~promisepatch.semantic.prompts.build_user_content`, the function schema from
:meth:`~promisepatch.semantic.jobs.JobSpec.tool_schema`, and the acceptance path -- validation,
grounding, the single corrective retry -- from
:class:`~promisepatch.semantic.provider.StructuredSemanticProvider`. There is no OpenAI prompt,
no OpenAI schema and no OpenAI parser, because a benchmark that measured a second prompt would
be measuring the prompt.

**Structured output, never prose parsing.** Every call defines exactly one function -- the
job's output schema -- and forces it with ``tool_choice``. That is the same mechanism, and the
same forcing, as the Bedrock adapter's ``toolConfig``; the envelope differs because the two
HTTP APIs differ, and the meaning does not. A response with no call to that one function is a
failure rather than something to run a regular expression over. The function is an output shape
and nothing else: there is no function here that changes an order, sends a message, records a
fact or approves anything, and the model is given none.

**No agent loop, no external tool, no retrieval.** One request, one answer, whatever it says.
The model is never given a second turn it did not have to be given, and the one corrective
retry it does get belongs to the shared acceptance path rather than to this module.

**The key is an argument, never an environment read.** The SDK will happily discover
``OPENAI_API_KEY`` for itself; it is not allowed to here. A provider that could find a
credential on its own is a provider that can be constructed by accident, and the composition
root's job of refusing before a client exists would become advisory.

**The SDK is imported where a client is built, and where one of its exceptions is classified,
and nowhere else.** Both are unreachable without a real client. So every other path through
this module -- building a request, reading a response, mapping a label, refusing a malformed
answer, propagating a failure raised by a stub -- runs with the package absent, which is what
lets the boundary be tested in the jobs that install no evaluation dependency at all.

**It cannot write anything.** This module holds no database handle and imports no SQLAlchemy
model -- an import contract forbids it, in the same way and for the same reason as the Bedrock
adapter. It returns values. Whether those values matter is decided elsewhere.

**"OpenAI" here names a wire protocol as well as a vendor.** Chat Completions with forced
function calling is what several hosted endpoints speak, and everything in this module except
the two places a vendor is actually named -- the base URL a client is opened against, and the
words in a failure message -- is a property of that protocol rather than of OpenAI. So the two
things that legitimately differ between one compatible endpoint and another are values:
:class:`Decoding`, which is the provider-native sampling configuration, and
:class:`TransportErrors`, which is the set of exception types a fault is classified into. A
second compatible provider is those two values, a base URL and a name. It is emphatically not a
second request builder, a second schema, a second extractor or a second prompt -- a benchmark
whose adapters each carried their own would be measuring the adapters.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Final, Protocol, Self, cast

from promisepatch.semantic.errors import (
    SemanticError,
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
)

PROVIDER_NAME: Final = "openai"
"""What a result file records as the provider. Half of a challenger's stored identity."""

TEMPERATURE: Final = 0.0
"""Sampled as little as the API allows, exactly as the other adapter is. Closed-label reads."""

DEFAULT_TIMEOUT_SECONDS: Final = 30.0
DEFAULT_MAX_RETRIES: Final = 2
"""The SDK's own transport retries. Bounded, and not the corrective retry -- that is the
boundary's, it is about content, and there is exactly one of it."""


# --------------------------------------------------------------------- provider-native decoding


@dataclass(frozen=True, slots=True)
class Decoding:
    """How one endpoint is asked to sample, and nothing about what it is asked.

    Separated from the request builder because it is the one part of a compatible call that is
    legitimately per provider: model families publish their own sampling guidance, and following
    a vendor's is not a change to the question. Everything semantic -- the instruction, the
    person's words, the function, the schema, the forced choice, the output ceiling -- is built
    from the job spec and is identical whoever answers.

    A field left ``None`` is a key the request does not carry at all, rather than a default
    somebody has to know. That matters for :attr:`reasoning_effort` in particular: absent is not
    the same as ``"none"``, and an endpoint that has no such control must not be sent one.
    """

    temperature: float
    top_p: float | None = None
    reasoning_effort: str | None = None
    """The single reasoning control this module will send. One mechanism, never two.

    A request that carried both a reasoning-effort field and a chat-template thinking switch
    would be two instructions about one thing, and which of them the endpoint honoured would be
    a fact about that endpoint on that day rather than about this experiment. So there is one
    field, it is the parameter the installed client types natively, and there is no escape
    hatch here through which a second control could be added without editing this class.
    """

    def as_payload(self) -> dict[str, object]:
        """The decoding configuration, for a preflight and a result identity to record.

        Recorded because it is part of what was measured: the same model asked with reasoning
        on and reasoning off is two experiments, and a result that did not say which is a
        number nobody can reproduce.
        """
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "reasoning_effort": self.reasoning_effort,
        }


OPENAI_DECODING: Final = Decoding(temperature=TEMPERATURE)
"""OpenAI's own configuration: sampled as little as the API allows, and nothing else set.

Exactly the request this module sent before a second compatible provider existed. ``top_p`` and
``reasoning_effort`` are absent rather than defaulted, so the bytes an OpenAI call carries are
unchanged by the generalisation around them.
"""


# ------------------------------------------------------------------- transport failures
#
# Subclasses rather than one error with a string, because the evaluator classifies a failed
# attempt by the exception's class name -- the only thing about a fault that is safe to store.
# A provider message can carry an account id, an organisation, a request context or a fragment
# of what was sent; none of that is written down anywhere, so the category has to be in the
# type. None of these is a semantic label and none can become one: they carry no value, and
# a caller that sees one has no reading to grade.


class OpenAiAuthenticationError(SemanticProviderError):
    """The key was rejected. Not retryable: presenting it again is presenting the same key."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class OpenAiPermissionError(SemanticProviderError):
    """The key is valid and this account may not call this model. A billing or access fact."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class OpenAiRateLimitError(SemanticProviderError):
    """Throttled or out of quota. Retryable in the transport sense; still no reading here."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class OpenAiUnavailableError(SemanticProviderError):
    """The service could not be reached or answered with a server fault."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class OpenAiInvalidRequestError(SemanticProviderError):
    """The request was understood and refused. Sending it again is being refused twice."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


@dataclass(frozen=True, slots=True)
class TransportErrors:
    """The five types one compatible endpoint's faults are classified into, plus its name.

    A record rather than five hard-coded classes, because the classification *logic* is a
    property of the protocol and the class *names* are a property of the provider. A stored
    result keeps the exception class name and nothing else about a fault, so a NVIDIA outage
    recorded as ``OpenAiUnavailableError`` would be a result file saying the wrong vendor was
    unreachable -- and the evaluator's taxonomy, which maps those names to categories, would be
    reading one provider's history under another's label.

    So a second compatible provider gets its own five subclasses and hands them here. It does
    not get its own copy of :func:`translate_transport_error`, which is the part that could
    drift.
    """

    label: str
    """What a failure message calls this endpoint. Never a URL, never an account, never a key."""

    authentication: Callable[[str], SemanticProviderError]
    permission: Callable[[str], SemanticProviderError]
    rate_limited: Callable[[str], SemanticProviderError]
    unavailable: Callable[[str], SemanticProviderError]
    invalid_request: Callable[[str], SemanticProviderError]
    """Each is a class in practice, and typed as "something that turns a message into one of
    ours" because that is the whole of what this record needs: the retryability is decided by
    the subclass, once, rather than by every call site being trusted to pass the right flag."""


OPENAI_ERRORS: Final = TransportErrors(
    label="OpenAI",
    authentication=OpenAiAuthenticationError,
    permission=OpenAiPermissionError,
    rate_limited=OpenAiRateLimitError,
    unavailable=OpenAiUnavailableError,
    invalid_request=OpenAiInvalidRequestError,
)


class ChatTransport(Protocol):
    """The one call this module makes against OpenAI.

    Narrow on purpose, exactly as the Bedrock adapter's is. The SDK's
    ``client.chat.completions`` satisfies it, and so does a stub in a test -- which is how the
    request this module builds is asserted in full without an API key, and without mocking away
    the part of the code that is worth testing.
    """

    def create(self, **kwargs: Any) -> Any: ...


class OpenAiSemanticProvider(StructuredSemanticProvider):
    """One pinned model, reached through Chat Completions with forced function calling.

    Holds a model id and a way to open a client. It does not know what a case is, what an order
    is, or what any of the answers it relays will be used for, and has no way to find out.

    **The client is opened on first use, never at construction.** For the same reason the other
    adapter defers: building one eagerly would make "is a credential present" a question asked
    when a process starts rather than when a call is made, and the composition root above this
    is the thing that is supposed to answer it, before anything here exists.

    **The model id is the snapshot, not an alias.** Nothing in this module enforces that -- it
    is a transport and takes what it is given -- but the id it is given is written into the
    telemetry, and from there into the run header a resumed run is checked against. An alias
    and the snapshot it points at therefore cannot be blended into one result file.
    """

    name = PROVIDER_NAME

    decoding: ClassVar[Decoding] = OPENAI_DECODING
    """This endpoint's sampling configuration. A class attribute so a compatible subclass states
    its own vendor guidance in one line and inherits every other byte of the request."""

    errors: ClassVar[TransportErrors] = OPENAI_ERRORS
    """Which exception types this endpoint's faults become. See :class:`TransportErrors`."""

    def __init__(self, *, open_transport: Callable[[], ChatTransport], model_id: str) -> None:
        self._open_transport = open_transport
        self._opened: ChatTransport | None = None
        # Twice, for the same reason the Bedrock adapter does it: ``model_id`` is the port's
        # optional telemetry field, and ``_model_id`` is this provider's own, which always
        # exists.
        self._model_id = model_id
        self.model_id = model_id

    @classmethod
    def with_api_key(
        cls,
        *,
        api_key: str,
        model_id: str,
        base_url: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> Self:
        """A provider for one pinned model, against a key the caller already resolved.

        The key is taken as an argument and never looked up. It is held in the closure below
        and reaches exactly one place -- the SDK constructor -- and it is never logged, never
        put in an exception message and never written to any artifact this repository produces.

        ``base_url`` is the one other thing a compatible endpoint changes, and it is taken the
        same way for the same reason: ``None`` is the SDK's own default and is what OpenAI is
        reached on, and a value is resolved and *validated* by the composition root above --
        never discovered here. An adapter that could pick its own endpoint would be an adapter
        that could quietly benchmark a different one.
        """
        if not api_key:
            raise cls.errors.authentication(
                f"no {cls.errors.label} API key was supplied to this provider, and it does not "
                f"look for one"
            )

        def open_transport() -> ChatTransport:
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout_seconds,
                max_retries=max_retries,
            )
            return cast(ChatTransport, client.chat.completions)

        return cls(open_transport=open_transport, model_id=model_id)

    def transport(self) -> ChatTransport:
        """The client, opened once. Called from the event loop, so there is no race to lose."""
        if self._opened is None:
            try:
                self._opened = self._open_transport()
            except Exception as error:
                raise self.errors.unavailable(
                    f"the {self.errors.label} client could not be prepared: {type(error).__name__}"
                ) from error
        return self._opened

    async def invoke(self, spec: JobSpec, content: str, *, correction: str | None) -> Attempt:
        request = build_chat_request(
            spec,
            content,
            model_id=self._model_id,
            correction=correction,
            decoding=self.decoding,
        )
        transport = self.transport()
        # The SDK's client is synchronous, and this call is the slowest thing in a turn. Off
        # the event loop it goes, exactly as the Bedrock call does.
        response = await asyncio.to_thread(self._call, transport, request)
        payload = as_mapping(response)
        return Attempt(payload=extract_tool_arguments(spec, payload), usage=read_usage(payload))

    def _call(self, transport: ChatTransport, request: Mapping[str, Any]) -> object:
        """One Chat Completions call, with every SDK failure translated into a semantic one.

        Nothing above this line should have to know what an ``APIStatusError`` is, and nothing
        below it decides what a failure means for a case.

        A failure that is already one of ours is re-raised untouched. That is the case whenever
        the transport is a stub, and it is why this whole path needs no SDK installed to be
        exercised: the module is reached only to classify an exception the SDK itself raised.
        """
        try:
            return transport.create(**request)
        except SemanticError:
            raise
        except Exception as error:
            raise translate_transport_error(error, errors=self.errors) from error


def translate_transport_error(
    error: Exception, *, errors: TransportErrors = OPENAI_ERRORS
) -> SemanticProviderError:
    """One third-party exception, as the category the evaluator is allowed to store.

    The SDK's exception types are resolved here rather than at the call site, and only if the
    package can be imported at all. That is not a fallback for a broken installation: the only
    way a real OpenAI exception can reach this function is through a client, and the only place
    a client is built is :meth:`OpenAiSemanticProvider.with_api_key`, which imports the SDK to
    do it. So "the module is missing" and "this exception came from the module" cannot both be
    true, and the honest answer when the first holds is the unclassified one.

    The messages carry a class name and, where the SDK publishes one, an HTTP status -- never a
    response body, never a header, never a key, and never the text that was sent.
    """
    try:
        import openai
    except ImportError:  # pragma: no cover - see the note above
        return errors.unavailable(f"the {errors.label} transport failed: {type(error).__name__}")

    if isinstance(error, openai.APITimeoutError):
        return SemanticTimeoutError(f"{errors.label} timed out: APITimeoutError")
    if isinstance(error, openai.AuthenticationError):
        return errors.authentication(f"{errors.label} rejected the credential: 401")
    if isinstance(error, openai.PermissionDeniedError):
        return errors.permission(f"{errors.label} refused this account access to the model: 403")
    if isinstance(error, openai.RateLimitError):
        return errors.rate_limited(f"{errors.label} throttled or refused for quota: 429")
    if isinstance(error, openai.APIConnectionError | openai.InternalServerError):
        return errors.unavailable(f"{errors.label} is unreachable: {type(error).__name__}")
    if isinstance(error, openai.APIStatusError):
        status = getattr(error, "status_code", None)
        return errors.invalid_request(
            f"{errors.label} refused the call: {type(error).__name__} {status}"
        )
    return errors.unavailable(
        f"the {errors.label} client failed before an answer: {type(error).__name__}"
    )


def function_definition(spec: JobSpec) -> dict[str, Any]:
    """The Chat Completions function entry for one job.

    Derived entirely from the job spec, so it is worth being able to assert without a client in
    the room -- and so that it cannot describe a shape the validator does not check. It is the
    same name, the same description and the same JSON Schema the Bedrock adapter sends; only
    the envelope around them belongs to this provider.
    """
    return {
        "type": "function",
        "function": {
            "name": spec.tool_name,
            "description": spec.tool_description,
            "parameters": spec.tool_schema(),
        },
    }


def build_chat_request(
    spec: JobSpec,
    content: str,
    *,
    model_id: str,
    correction: str | None,
    decoding: Decoding = OPENAI_DECODING,
) -> dict[str, Any]:
    """The exact Chat Completions payload for one attempt. Pure, so a test can read it in full.

    The instruction is a system message; the person's words are inside a user message. That
    split is the request-level half of the injection posture and it is the same split the
    Bedrock request makes: whatever a customer wrote arrives where user content arrives, never
    where the rules do.

    ``decoding`` is the only parameter that varies by endpoint, and it can only reach the four
    sampling keys below. There is no path from it to the messages, the tools or the forced
    choice, which is what makes "different provider, same question" a property of this function
    rather than a claim about it.
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": spec.system_instruction},
        {"role": "user", "content": content},
    ]
    if correction is not None:
        # A second user turn rather than an edit of the first, matching the other adapter: the
        # model can see what it said and why it was refused, and the original question is still
        # the question.
        messages.append({"role": "assistant", "content": "(previous answer)"})
        messages.append({"role": "user", "content": correction})

    request: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "tools": [function_definition(spec)],
        "tool_choice": {"type": "function", "function": {"name": spec.tool_name}},
        "temperature": decoding.temperature,
        "max_completion_tokens": spec.max_tokens,
    }
    # Absent rather than defaulted. A key this endpoint has no control for would be a request
    # the provider may reject outright, and a `None` sent for a reasoning control reads as a
    # request for the vendor default -- which for a reasoning model is a long hidden trace this
    # three-label classification has no use for and would be billed a ceiling of tokens for.
    if decoding.top_p is not None:
        request["top_p"] = decoding.top_p
    if decoding.reasoning_effort is not None:
        request["reasoning_effort"] = decoding.reasoning_effort
    return request


def as_mapping(response: object) -> Mapping[str, Any]:
    """One answer as plain data, whatever object the SDK handed back.

    The SDK returns Pydantic models; a stub in a test returns a dict. Both are read the same
    way from here down, which keeps the extraction below assertable without the SDK installed
    and stops this module depending on the shape of a vendor type.
    """
    dump = getattr(response, "model_dump", None)
    if callable(dump):
        return cast(Mapping[str, Any], dump(mode="python"))
    if isinstance(response, Mapping):
        return cast(Mapping[str, Any], response)
    raise OpenAiUnavailableError(
        f"OpenAI returned something that is not a response: {type(response).__name__}"
    )


def extract_tool_arguments(spec: JobSpec, response: Mapping[str, Any]) -> object:
    """The function arguments the model produced, or a typed failure saying it produced none.

    A response with no call to the one function that was forced is not an answer in a different
    format; it is the model declining the shape of the question. Reading its prose instead
    would be exactly the free-form parsing this boundary exists to avoid.
    """
    for choice in _sequence(response.get("choices")):
        message = choice.get("message") if isinstance(choice, Mapping) else None
        if not isinstance(message, Mapping):
            continue
        for call in _sequence(message.get("tool_calls")):
            function = call.get("function") if isinstance(call, Mapping) else None
            if not isinstance(function, Mapping) or function.get("name") != spec.tool_name:
                continue
            return _decode(spec, function.get("arguments"))
    raise SemanticValidationError(
        f"{spec.job.value}: the model did not call {spec.tool_name}",
        category=ValidationFailure.MISSING_TOOL_USE,
    )


def _decode(spec: JobSpec, arguments: object) -> object:
    """Function arguments arrive as a JSON string, so a string that is not JSON is malformed.

    Never repaired and never partially read. The shared acceptance path decides what a decoded
    object is worth; this only decides whether there is an object at all.
    """
    if isinstance(arguments, Mapping):
        return arguments
    if not isinstance(arguments, str):
        raise SemanticValidationError(
            f"{spec.job.value}: the model's function arguments are not an object",
            category=ValidationFailure.MALFORMED_OUTPUT,
        )
    try:
        return cast(object, json.loads(arguments))
    except json.JSONDecodeError as error:
        raise SemanticValidationError(
            f"{spec.job.value}: the model's function arguments are not valid JSON",
            category=ValidationFailure.MALFORMED_OUTPUT,
        ) from error


def _sequence(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def read_usage(response: Mapping[str, Any]) -> SemanticUsage:
    """What the call cost, if OpenAI said. Never load-bearing, so absence is not a failure.

    ``prompt_tokens`` includes any cached portion, which is what the account is billed the
    standard rate against unless a discount applies -- so counting it whole is the direction
    that cannot understate a budget. Latency is not reported by this API and stays ``None``
    rather than becoming a zero somebody could read as a measurement.
    """
    usage = response.get("usage") or {}
    if not isinstance(usage, Mapping):  # pragma: no cover - the SDK types this field
        return SemanticUsage()
    return SemanticUsage(
        input_tokens=_as_int(usage.get("prompt_tokens")),
        output_tokens=_as_int(usage.get("completion_tokens")),
    )


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = [
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TIMEOUT_SECONDS",
    "OPENAI_DECODING",
    "OPENAI_ERRORS",
    "PROVIDER_NAME",
    "TEMPERATURE",
    "ChatTransport",
    "Decoding",
    "OpenAiAuthenticationError",
    "OpenAiInvalidRequestError",
    "OpenAiPermissionError",
    "OpenAiRateLimitError",
    "OpenAiSemanticProvider",
    "OpenAiUnavailableError",
    "TransportErrors",
    "as_mapping",
    "build_chat_request",
    "extract_tool_arguments",
    "function_definition",
    "read_usage",
    "translate_transport_error",
]
