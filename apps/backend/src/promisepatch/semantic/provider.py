"""The one semantic boundary: a typed request in, a validated value out, or a typed failure.

There is exactly one port. Not a client per job, not a client per model -- one
:class:`SemanticProvider`, whose method takes a job-discriminated request and returns a
validated value. A second entry point would be a second place for the rules to be almost
enforced.

**The port has no generic call.** There is no "send these messages and give me the text". A
caller can ask one of the questions in :class:`~promisepatch.semantic.contracts.SemanticJob`
and cannot ask anything else, which is what makes the model's reach reviewable rather than
merely bounded by good intentions.

**Every provider shares the acceptance path.** :class:`StructuredSemanticProvider` owns the
prompt, the validation and the single corrective retry the architecture fixes; a provider
implements only how one attempt reaches a model. The fake and the Bedrock client are therefore
the same code everywhere it matters and differ only where they must.

**The retry is corrective, not hopeful.** A malformed answer is retried exactly once, and the
retry carries the validation error so the model is answering a different question the second
time. Asking the identical question again and taking whatever comes back would be a policy of
waiting for a model to guess correctly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from promisepatch.semantic.contracts import SemanticJob, SemanticRequest, SemanticValue
from promisepatch.semantic.errors import SemanticValidationError
from promisepatch.semantic.jobs import JobSpec, spec_for, validate
from promisepatch.semantic.prompts import build_user_content

CORRECTIVE_RETRIES = 1
"""How many times a schema-invalid answer is put back to the model. The architecture's number.

One, and fixed rather than configured. A second corrective attempt would be arguing with a
model about a schema, and a bound that a deployment could raise would be a bound somebody
raises the night a demo is failing.
"""


@dataclass(frozen=True, slots=True)
class SemanticUsage:
    """What one call cost, as the provider reported it. Never load-bearing.

    Telemetry only. No decision anywhere in PromisePatch reads these numbers, and a provider
    that reports none is not degraded -- it is a provider that does not publish them.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SemanticTelemetry:
    """Who answered, with what, and how hard it was to get a usable answer."""

    job: SemanticJob
    provider: str
    model_id: str | None
    attempts: int
    usage: SemanticUsage = SemanticUsage()


@dataclass(frozen=True, slots=True)
class SemanticResult:
    """A validated reading and the story of how it arrived.

    ``value`` has passed the schema and the candidate check. It is still a proposal: nothing
    about surviving validation makes a model's answer authoritative, and every caller of this
    boundary is deterministic code that decides for itself what the reading is worth.
    """

    value: SemanticValue
    telemetry: SemanticTelemetry


@runtime_checkable
class SemanticProvider(Protocol):
    """Somewhere a bounded semantic question can be asked. The whole interface.

    Domain code depends on this, never on a vendor SDK. That is what keeps "which model runs
    this" a configuration question rather than an architectural one -- and what makes a suite
    that never touches AWS a real test of the code that will.
    """

    name: str

    async def run(self, request: SemanticRequest) -> SemanticResult:
        """Answer one semantic job, or raise a typed semantic failure. Never guesses."""
        ...


@dataclass(frozen=True, slots=True)
class Attempt:
    """One answer from a model, before anybody has decided whether it is acceptable."""

    payload: object
    usage: SemanticUsage = SemanticUsage()


class StructuredSemanticProvider:
    """The shared half of every provider: prompt, validate, correct once, give up cleanly.

    Subclasses implement :meth:`invoke` and nothing else. The consequence is that the fake
    provider exercises the identical acceptance path as the real one, so a test proving that
    an invented resource id is refused is proving it about production code.
    """

    name = "structured"
    model_id: str | None = None

    async def run(self, request: SemanticRequest) -> SemanticResult:
        spec = spec_for(request)
        content = build_user_content(request)
        correction: str | None = None

        for attempt_number in range(1, CORRECTIVE_RETRIES + 2):
            attempt = await self.invoke(spec, content, correction=correction)
            try:
                value = validate(request, attempt.payload)
            except SemanticValidationError as error:
                if attempt_number > CORRECTIVE_RETRIES:
                    raise
                correction = (
                    f"Your previous answer was rejected: {error}. "
                    f"Call {spec.tool_name} again with an answer that satisfies the schema, "
                    f"using only the identifiers and labels you were given."
                )
                continue
            return SemanticResult(
                value=value,
                telemetry=SemanticTelemetry(
                    job=spec.job,
                    provider=self.name,
                    model_id=self.model_id,
                    attempts=attempt_number,
                    usage=attempt.usage,
                ),
            )

        raise AssertionError("unreachable: the loop returns or raises")  # pragma: no cover

    async def invoke(self, spec: JobSpec, content: str, *, correction: str | None) -> Attempt:
        """Put one question to a model and return whatever it said. No validation here.

        ``correction`` is the rejection text from the previous attempt, or ``None`` on the
        first. A provider that ignores it will simply be asked the same thing twice, which is
        the behaviour the bound exists to stop being useful.
        """
        raise NotImplementedError


def tool_definition(spec: JobSpec) -> dict[str, Any]:
    """The Bedrock Converse tool entry for one job.

    Lives here rather than in the adapter because it is derived entirely from the job spec and
    is worth being able to assert without an AWS client in the room. It describes an output
    shape and nothing else: there is no tool in PromisePatch that a model can call to change
    anything, and this is not the beginning of one.
    """
    return {
        "toolSpec": {
            "name": spec.tool_name,
            "description": spec.tool_description,
            "inputSchema": {"json": spec.tool_schema()},
        }
    }


__all__ = [
    "CORRECTIVE_RETRIES",
    "Attempt",
    "SemanticProvider",
    "SemanticResult",
    "SemanticTelemetry",
    "SemanticUsage",
    "StructuredSemanticProvider",
    "tool_definition",
]
