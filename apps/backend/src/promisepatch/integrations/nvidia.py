"""The NVIDIA hosted NIM boundary: the OpenAI-compatible transport, pointed somewhere else.

NVIDIA's build endpoint speaks Chat Completions, including ``tools`` and named ``tool_choice``,
which is the whole reason this module is configuration rather than a second adapter. Everything
that decides what a model is asked -- the system instruction, the person's words, the one
function, its JSON Schema, the forced choice, the output ceiling, the acceptance path and the
single corrective retry -- comes from :mod:`promisepatch.integrations.openai` and through it
from production's own job spec. Nothing semantic is restated here, because a challenger whose
adapter carried its own prompt would be measuring the adapter.

**What this module contains is exactly what honestly differs between two compatible endpoints:**

* the base URL a client is opened against, and the refusal of any other one;
* the provider name a result file records;
* the sampling configuration NVIDIA publishes for this model family;
* five exception subclasses, so a fault recorded against NVIDIA does not name OpenAI.

**The endpoint is part of the experiment's identity, so a different one is refused rather than
used.** ``https://integrate.api.nvidia.com/v1`` is a specific hosted service with a specific
model behind a specific name. A self-hosted NIM, a partner deployment, a local container or an
OpenAI-compatible proxy could all answer to ``nvidia/nemotron-3-super-120b-a12b`` and would be
a different measurement wearing the same label. :func:`refuse_a_foreign_endpoint` is what stops
those becoming one number, and it fails closed: an endpoint that is not the intended one is a
refusal, never a fallback.

**Reasoning is off, deliberately and by one mechanism.** This job is a three-label
classification of one short customer sentence against a closed vocabulary, with a 64-token
output ceiling the job spec already declares. The model family's default configuration budgets
thousands of tokens for a hidden trace, which this question has no use for and which would not
fit inside the ceiling the semantic contract sets. So :data:`NEMOTRON_DECODING` sends
``reasoning_effort="none"`` -- the parameter the installed client types natively -- and sends
no second, contradicting control. That is a provider-native decoding choice, not a change to
the question, and it is recorded as part of what was measured.

**Authority is unchanged and is none.** This module returns a reading from the closed set the
semantic contract defines and can do nothing else: it holds no database handle, imports no
SQLAlchemy model, and the one "tool" in its requests is an output shape rather than anything
that could act. No NVIDIA tool call is ever executed against anything.
"""

from __future__ import annotations

from typing import ClassVar, Final, Self

from promisepatch.integrations.openai import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    Decoding,
    OpenAiSemanticProvider,
    TransportErrors,
)
from promisepatch.semantic.errors import SemanticProviderError

PROVIDER_NAME: Final = "nvidia"
"""What a result file records as the provider. Half of a challenger's stored identity."""

HOSTED_BASE_URL: Final = "https://integrate.api.nvidia.com/v1"
"""The one endpoint this benchmark's identity is defined against. See the module note."""

NEMOTRON_3_SUPER: Final = "nvidia/nemotron-3-super-120b-a12b"
"""The pinned challenger model. Written out because a result names what produced it."""

TEMPERATURE: Final = 1.0
TOP_P: Final = 0.95
"""NVIDIA's published sampling guidance for this model family, followed rather than overridden.

Higher than the near-zero temperature the other two adapters use, and that difference is the
vendor's own recommendation for this family rather than a knob this repository turned. Decoding
is per provider; the question is not.
"""

REASONING_EFFORT: Final = "none"
"""The one reasoning control sent, and the only one. See the module note."""

NEMOTRON_DECODING: Final = Decoding(
    temperature=TEMPERATURE, top_p=TOP_P, reasoning_effort=REASONING_EFFORT
)


# ------------------------------------------------------------------- transport failures
#
# Five subclasses that add no behaviour, for one reason: a stored result keeps the exception's
# class name and nothing else about a fault. Reusing the OpenAI types would write "OpenAi..."
# into an NVIDIA run's failure log, and the evaluator's taxonomy -- which reads those names --
# would be classifying one provider's outages under another provider's vocabulary. None of
# them is a semantic label and none can become one: they carry no reading.


class NvidiaAuthenticationError(SemanticProviderError):
    """The key was rejected. Not retryable: presenting it again is presenting the same key."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class NvidiaPermissionError(SemanticProviderError):
    """The key is valid and this account may not call this model. An access or quota fact."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class NvidiaRateLimitError(SemanticProviderError):
    """Throttled, or the free endpoint's quota is spent. Retryable; still no reading here."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class NvidiaUnavailableError(SemanticProviderError):
    """The service could not be reached or answered with a server fault."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class NvidiaInvalidRequestError(SemanticProviderError):
    """The request was understood and refused. Sending it again is being refused twice."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


NVIDIA_ERRORS: Final = TransportErrors(
    label="NVIDIA",
    authentication=NvidiaAuthenticationError,
    permission=NvidiaPermissionError,
    rate_limited=NvidiaRateLimitError,
    unavailable=NvidiaUnavailableError,
    invalid_request=NvidiaInvalidRequestError,
)


# ----------------------------------------------------------------------- endpoint identity


class NvidiaEndpointError(SemanticProviderError):
    """The configured endpoint is not the one this experiment is defined against.

    A refusal rather than a redirection, and raised before any client exists. Not retryable:
    the same configuration would be refused again.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


def normalise_base_url(base_url: str) -> str:
    """One endpoint written two ways, as one string. Whitespace and a trailing slash only.

    Deliberately not a URL parser. Case-folding a host, dropping a default port or reordering a
    query would each be a small decision about which endpoints count as the same one, and every
    one of them widens what this benchmark's identity accepts. Two spellings are forgiven
    because they are typing, not addressing; everything else is a different endpoint.
    """
    return base_url.strip().rstrip("/")


def refuse_a_foreign_endpoint(base_url: str) -> str:
    """The configured endpoint, or a refusal. Never a fallback and never a correction.

    Fails closed by construction: the only value that returns is the intended one, so a
    misconfiguration cannot become a run against a local container, a proxy or a partner
    deployment recorded under this experiment's name.
    """
    normalised = normalise_base_url(base_url)
    if normalised == HOSTED_BASE_URL:
        return normalised
    raise NvidiaEndpointError(
        f"this benchmark is defined against the NVIDIA hosted NIM endpoint "
        f"{HOSTED_BASE_URL} and the configured base URL is {normalised!r}. A different "
        f"endpoint is a different measurement, so it is refused rather than used: nothing was "
        f"constructed and nothing was called."
    )


class NvidiaSemanticProvider(OpenAiSemanticProvider):
    """One pinned model on NVIDIA's hosted NIM, reached through the compatible transport.

    A subclass rather than a copy, and it overrides nothing that shapes a question. What it
    states is the four things above: its name, its decoding, its error types and the endpoint
    it will accept. Everything else -- opening the client lazily, building the request, forcing
    the one function, extracting the arguments, reading usage, classifying a fault -- is the
    parent's, which is what makes "same question, different model" checkable rather than
    claimed.
    """

    name = PROVIDER_NAME
    decoding: ClassVar[Decoding] = NEMOTRON_DECODING
    errors: ClassVar[TransportErrors] = NVIDIA_ERRORS

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
        """A provider for one pinned model on the hosted endpoint, or a refusal.

        The endpoint is checked here as well as by the composition root above, and the ordering
        is the point: this is the last line before a client could exist, so whatever route
        reached it, an endpoint that is not the intended one stops here.

        ``None`` means "the endpoint this experiment is defined against" rather than the SDK's
        own default. There is no configuration under which this class reaches OpenAI.
        """
        return super().with_api_key(
            api_key=api_key,
            model_id=model_id,
            base_url=refuse_a_foreign_endpoint(base_url or HOSTED_BASE_URL),
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )


__all__ = [
    "HOSTED_BASE_URL",
    "NEMOTRON_3_SUPER",
    "NEMOTRON_DECODING",
    "NVIDIA_ERRORS",
    "PROVIDER_NAME",
    "REASONING_EFFORT",
    "TEMPERATURE",
    "TOP_P",
    "NvidiaAuthenticationError",
    "NvidiaEndpointError",
    "NvidiaInvalidRequestError",
    "NvidiaPermissionError",
    "NvidiaRateLimitError",
    "NvidiaSemanticProvider",
    "NvidiaUnavailableError",
    "normalise_base_url",
    "refuse_a_foreign_endpoint",
]
