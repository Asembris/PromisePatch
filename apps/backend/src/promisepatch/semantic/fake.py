"""A semantic provider that answers from a script. The default everywhere but AWS.

This is what runs in unit tests, integration tests, CI, the crash suite and `docker compose
up`. It reaches no network, holds no credential and imports no SDK -- which is the property
that keeps the whole repository runnable, and the whole pipeline green, on a machine that has
never heard of AWS.

It is not a stub that returns a canned object past the rules. Its answers go through the same
:func:`~promisepatch.semantic.jobs.validate` gate as a real model's, because a fake that could
return something the real path would refuse would be a fake that makes tests agree with each
other instead of with production.

Its defaults are the cautious answer for each job: an interpretation that binds nothing, an
intent of ``UNCLEAR``, a one-word verbalisation. Nothing is configured into meaning something
unless a test says so, so a workflow accidentally wired to the fake stalls visibly rather than
proceeding on invented understanding.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from promisepatch.semantic.contracts import SemanticJob
from promisepatch.semantic.errors import SemanticError
from promisepatch.semantic.jobs import JobSpec
from promisepatch.semantic.provider import Attempt, SemanticUsage, StructuredSemanticProvider

type FakeReply = object
"""One scripted answer: the raw tool input a model would have returned, or a failure to raise.

Deliberately ``object`` rather than a validated model. A script that could only express valid
answers could not express the cases that matter -- the malformed one, the invented identifier,
the label outside the vocabulary.
"""

DEFAULT_REPLIES: Final[Mapping[SemanticJob, object]] = {
    SemanticJob.INTERPRET_UTTERANCE: {"clarification_needed": True},
    SemanticJob.CLASSIFY_REPLY_INTENT: {"apparent_intent": "UNCLEAR"},
    SemanticJob.VERBALISE: {"speech": "Recorded.", "fact_refs": []},
}
"""What the fake says when nothing was scripted: understood nothing, claimed nothing.

``UNCLEAR`` is also the architecture's deterministic fallback for that job, so a deployment
running the fake behaves the way a deployment whose model is unreachable behaves.

The verbalisation default accounts for no facts at all, which any real explanation request
refuses -- so an unconfigured deployment says the deterministic passage rather than the word
"Recorded." That is the same answer it would give if the provider were unreachable, which is
the property this file exists to preserve.
"""


@dataclass(frozen=True, slots=True)
class RecordedCall:
    """One question the fake was asked, kept so a test can assert what was sent."""

    job: SemanticJob
    content: str
    correction: str | None


class FakeSemanticProvider(StructuredSemanticProvider):
    """Answers each job from its script, then from the cautious default. No I/O, ever.

    The script is per job and consumed in order, which is what lets a test say "the model
    gets it wrong, then gets it right" and prove the single corrective retry without a network
    in the room.
    """

    name = "fake"
    model_id = None

    def __init__(self, script: Mapping[SemanticJob, Sequence[FakeReply]] | None = None) -> None:
        self._script: dict[SemanticJob, list[FakeReply]] = {
            job: list(replies) for job, replies in (script or {}).items()
        }
        self.calls: list[RecordedCall] = []

    async def invoke(self, spec: JobSpec, content: str, *, correction: str | None) -> Attempt:
        self.calls.append(RecordedCall(spec.job, content, correction))
        pending = self._script.get(spec.job)
        reply = pending.pop(0) if pending else DEFAULT_REPLIES[spec.job]
        if isinstance(reply, SemanticError):
            raise reply
        return Attempt(payload=reply, usage=SemanticUsage())


__all__ = ["DEFAULT_REPLIES", "FakeReply", "FakeSemanticProvider", "RecordedCall"]
