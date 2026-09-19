"""Arm A's model: the frozen configuration, built into an exact Converse request.

The contract freezes four things about the model and this module restates none of them. The
provider, the model id, the API and the temperature are read out of
``docs/benchmarks/safe-useful-recovery.v1.json`` after its hash has been asserted, and the output
ceiling is read out of the same document's budget block. A harness carrying its own copy of a
model id would eventually be the copy that ran.

**The request is built by a pure function.** :func:`build_converse_request` takes an identity, a
system prompt, a conversation and a tool surface, and returns the dictionary that would be sent.
It opens nothing, so the exact payload -- including the temperature and the ceiling the contract
froze -- is asserted in a test with no AWS account, no credential and no socket, which is the
only way "the binding sends what the contract says" can be evidence rather than intent.

**The client is opened on first use, never at construction.** boto3 resolves the whole credential
chain when a client is made, so building one eagerly would mean this module could not be imported
on a machine with no AWS configuration -- which is every machine this harness has been proved on.
Deferring it keeps *which model* a configuration question and *may this identity call it* a
question asked when a call is made.

**Translation is this module's job and not the arm's.**
:class:`~scripts.sur1.adapters.BaselineArm` keeps a conversation in the harness's own shape,
because two of the three arms have no conversation at all and the driver must not learn one
provider's envelope. Turning that shape into Converse blocks -- assistant ``toolUse``, user
``toolResult``, one user turn per group of results -- happens here, where it can be read in full
beside the request it produces.

**Nothing in this module has been called.** No Bedrock endpoint has been reached from it, the
spend authorisation is unspent, and the tests that exercise it run under a socket guard that
raises on anything that is not loopback.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from scripts.sur1.arms import ModelReply
from scripts.sur1.bindings import REAL, Probe
from scripts.sur1.frozen import Contract

CONVERSE_API: Final = "bedrock-runtime Converse"
"""The one API the contract names. A configuration that says anything else is a different run."""

BEDROCK: Final = "bedrock"

JSON_TYPES: Final[dict[str, str]] = {
    "string": "string",
    "integer": "integer",
    "object": "object",
    "boolean": "boolean",
    "number": "number",
}
"""How an argument shape in :data:`~scripts.sur1.adapters.ARGUMENTS` becomes a JSON-schema type.

The shapes are written as prose there -- ``"object, the frozen RunReport schema"`` -- because
they are documentation for the one arm that reads them. The first word is the type, and a word
this table does not hold is a programming error rather than a default.
"""


class ModelConfigurationError(RuntimeError):
    """The configuration a client was built with is not the one the contract froze."""


class ConverseTransport(Protocol):
    """The one call this module makes against AWS.

    Narrow on purpose, and the same shape the product's own Bedrock provider declares: boto3's
    ``bedrock-runtime`` client satisfies it, and so does a stub -- which is how the request is
    asserted in full without an account and without mocking away the code worth testing.
    """

    def converse(self, **kwargs: Any) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """Which model, on what terms, with what ceiling. Read from the contract, never restated."""

    provider: str
    model_id: str
    api: str
    temperature: float
    max_output_tokens: int
    region: str

    @classmethod
    def frozen(cls, contract: Contract, *, region: str) -> ModelIdentity:
        """The configuration the contract holds, plus the region the account is reached in.

        The region is not frozen and could not be: it is a fact about an account rather than
        about the benchmark. It is recorded in the manifest so a published number says where
        the model was invoked.
        """
        configured = contract.model_configuration
        if configured.provider != BEDROCK or configured.api != CONVERSE_API:
            raise ModelConfigurationError(
                f"this binding is the {CONVERSE_API} one and the contract configures "
                f"{configured.provider} / {configured.api}"
            )
        return cls(
            provider=configured.provider,
            model_id=configured.model_id,
            api=configured.api,
            temperature=configured.temperature,
            max_output_tokens=contract.ceilings.output_tokens,
            region=region,
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "api": self.api,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "region": self.region,
        }


# ------------------------------------------------------------------------ the request, purely


def tool_configuration(tools: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The frozen actions as Converse tool specifications.

    Every argument is required, because a frozen action with an omitted argument is not that
    action. ``toolChoice`` is deliberately absent: the baseline is an agent deciding what to do,
    and forcing a tool would be the harness deciding for it.
    """
    specifications = []
    for tool in tools:
        arguments: Mapping[str, Any] = tool.get("arguments", {})
        properties = {}
        for name, shape in arguments.items():
            word = str(shape).split(",")[0].strip()
            if word not in JSON_TYPES:
                raise ModelConfigurationError(
                    f"{tool['name']}.{name} is declared {shape!r}, which names no JSON type"
                )
            properties[name] = {"type": JSON_TYPES[word]}
        specifications.append(
            {
                "toolSpec": {
                    "name": str(tool["name"]),
                    "description": str(tool.get("description", "")),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": properties,
                            "required": sorted(properties),
                        }
                    },
                }
            }
        )
    return {"tools": specifications}


def converse_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The harness's conversation, as Converse turns.

    Three translations and no judgements. A user turn is one text block. An assistant turn is
    its text followed by one ``toolUse`` block per call it made. A run of tool results becomes
    **one** user turn carrying every ``toolResult``, because Converse alternates roles and the
    arm appends one message per call.

    A ``toolResult`` is paired to its ``toolUse`` by identity when the reply carried one, and by
    position among the same-named calls of the preceding assistant turn otherwise -- which is
    exact, because the arm performs the calls in the order the reply listed them.
    """
    turns: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    outstanding: list[tuple[str, str]] = []

    def flush() -> None:
        if pending:
            turns.append({"role": "user", "content": list(pending)})
            pending.clear()

    for index, message in enumerate(messages):
        role = str(message["role"])
        if role == "tool":
            name = str(message["name"])
            identifier = _claim(outstanding, name)
            pending.append(
                {
                    "toolResult": {
                        "toolUseId": identifier,
                        "content": [{"json": dict(message.get("content") or {})}],
                    }
                }
            )
            continue

        flush()
        if role == "user":
            turns.append({"role": "user", "content": [{"text": str(message["content"])}]})
            continue

        blocks: list[dict[str, Any]] = []
        text = str(message.get("content") or "")
        if text:
            blocks.append({"text": text})
        outstanding = []
        for position, call in enumerate(message.get("tools") or ()):
            name = str(call["name"])
            identifier = str(call.get("id") or f"call-{index}-{position}")
            outstanding.append((name, identifier))
            blocks.append(
                {
                    "toolUse": {
                        "toolUseId": identifier,
                        "name": name,
                        "input": dict(call.get("arguments") or {}),
                    }
                }
            )
        turns.append({"role": "assistant", "content": blocks})

    flush()
    return turns


def _claim(outstanding: list[tuple[str, str]], name: str) -> str:
    """The identity of the earliest unanswered call of this name, or a declared absence.

    A tool result the conversation cannot attribute is not guessed at: it is given an identity
    that says so, and a provider that rejects it is telling the truth about the conversation.
    """
    for position, (called, identifier) in enumerate(outstanding):
        if called == name:
            outstanding.pop(position)
            return identifier
    return f"unmatched-{name}"


def build_converse_request(
    *,
    identity: ModelIdentity,
    system: str,
    messages: Sequence[Mapping[str, Any]],
    tools: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The exact payload one attempt would send. Pure, so a test can read it in full.

    The temperature and the output ceiling come from :class:`ModelIdentity`, which read them out
    of the frozen document. There is no literal in this function that a contract change would
    fail to move.
    """
    return {
        "modelId": identity.model_id,
        "system": [{"text": system}],
        "messages": converse_messages(messages),
        "toolConfig": tool_configuration(tools),
        "inferenceConfig": {
            "temperature": identity.temperature,
            "maxTokens": identity.max_output_tokens,
        },
    }


def read_reply(response: Mapping[str, Any]) -> ModelReply:
    """One Converse answer, as the harness's own reply. Defensive at every level.

    An envelope from outside is untrusted input like any other, so a missing or differently
    shaped ``output``, ``message`` or ``content`` reads as an answer with no text and no calls
    rather than raising an attribute error out of a binding whose caller catches neither.

    Usage is read the same way and is never load-bearing: an absent token count is recorded as
    zero spend for *this* reply, and the ledger's own ceilings still bound the attempt.
    """
    message = _mapping(_mapping(response.get("output")).get("message"))
    texts: list[str] = []
    calls: list[dict[str, Any]] = []
    for block in _sequence(message.get("content")):
        if "text" in block:
            texts.append(str(block["text"]))
        use = block.get("toolUse")
        if isinstance(use, Mapping):
            calls.append(
                {
                    "id": str(use.get("toolUseId", "")),
                    "name": str(use.get("name", "")),
                    "arguments": dict(_mapping(use.get("input"))),
                }
            )
    usage = _mapping(response.get("usage"))
    return ModelReply(
        text="\n".join(texts),
        tool_calls=tuple(calls),
        input_tokens=_as_int(usage.get("inputTokens")),
        output_tokens=_as_int(usage.get("outputTokens")),
        stop_reason=str(response.get("stopReason", "end_turn")),
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [block for block in value if isinstance(block, Mapping)]


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


# ------------------------------------------------------------------------------- the binding


@dataclass(slots=True)
class BedrockConverseClient:
    """Arm A's :class:`~scripts.sur1.arms.ModelClient`, bound to ``bedrock-runtime``.

    Holds an identity and a way to open a transport, and opens the transport on the first call
    rather than in ``__init__``. Every request it sends is the one
    :func:`build_converse_request` returns, so there is nothing this object does to a payload
    that a test cannot see.
    """

    identity_: ModelIdentity
    open_transport: Callable[[], ConverseTransport]
    binding_kind: str = REAL
    _opened: ConverseTransport | None = None

    @classmethod
    def from_contract(cls, contract: Contract, *, region: str) -> BedrockConverseClient:
        """The client this benchmark's own configuration describes. Opens nothing."""
        identity = ModelIdentity.frozen(contract, region=region)

        def open_transport() -> ConverseTransport:
            import boto3
            from botocore.config import Config

            client: ConverseTransport = boto3.client(
                "bedrock-runtime",
                region_name=identity.region,
                config=Config(region_name=identity.region, retries={"max_attempts": 1}),
            )
            return client

        return cls(identity_=identity, open_transport=open_transport)

    def converse(
        self,
        *,
        system: str,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> ModelReply:
        request = build_converse_request(
            identity=self.identity_, system=system, messages=messages, tools=tools
        )
        if self._opened is None:
            self._opened = self.open_transport()
        return read_reply(self._opened.converse(**request))

    def identity(self) -> Mapping[str, Any]:
        return self.identity_.as_payload()

    def probe(self) -> Probe:
        """Whether this client *could* be opened, without invoking the model.

        Opening a boto3 client resolves the credential chain and reaches nothing, so a probe
        that opens one costs no inference and spends no authorisation. Invoking the model to
        find out whether the model can be invoked would spend exactly the thing the preflight
        exists to protect.
        """
        if not self.identity_.region:
            return Probe("MODEL", False, "no region is configured for bedrock-runtime")
        try:
            self._opened = self._opened or self.open_transport()
        except Exception as failure:  # a client that cannot be built is a configuration fact
            return Probe("MODEL", False, f"{type(failure).__name__}: {failure}")
        return Probe("MODEL", True, f"{self.identity_.model_id} in {self.identity_.region}")


__all__ = [
    "BEDROCK",
    "CONVERSE_API",
    "BedrockConverseClient",
    "ConverseTransport",
    "ModelConfigurationError",
    "ModelIdentity",
    "build_converse_request",
    "converse_messages",
    "read_reply",
    "tool_configuration",
]
