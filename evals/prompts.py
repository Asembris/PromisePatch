"""Which prompt was measured, said in a way two runs can be compared on.

"The current prompt" is not an answer. A benchmark result that does not name the words the
model was given cannot be compared with the next one, and a prompt revision that improves a
number is indistinguishable from a model that had a better day.

So every run records, per job, a hash of the system instruction and a hash of the tool schema
the answer had to satisfy. Both are derived from production -- :func:`build_system_instruction`
and :meth:`JobSpec.tool_schema` -- so an identity here cannot describe a prompt that is not the
one being sent.

Hashes rather than the text itself: the text is in the repository at the recorded commit, and a
result artifact carrying whole prompts would grow without telling anybody anything the hash does
not. Nothing here is secret; a prompt containing a secret would be a defect regardless.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from promisepatch.semantic import SemanticJob
from promisepatch.semantic.jobs import JOB_SPECS
from promisepatch.semantic.prompts import build_system_instruction

DIGEST_LENGTH = 16
"""How much of the SHA-256 is kept. Enough to distinguish revisions, short enough to read."""


@dataclass(frozen=True, slots=True)
class PromptIdentity:
    """One job's prompt, named by what it actually contains."""

    job: str
    tool_name: str
    system_hash: str
    schema_hash: str

    def as_payload(self) -> dict[str, str]:
        return {
            "job": self.job,
            "tool_name": self.tool_name,
            "system_hash": self.system_hash,
            "schema_hash": self.schema_hash,
        }


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]


def prompt_identity(job: SemanticJob) -> PromptIdentity:
    """The identity of the prompt and schema this job is currently sent with."""
    spec = JOB_SPECS[job]
    schema = json.dumps(spec.tool_schema(), sort_keys=True, separators=(",", ":"))
    return PromptIdentity(
        job=job.value,
        tool_name=spec.tool_name,
        system_hash=_digest(build_system_instruction(job)),
        schema_hash=_digest(schema),
    )


__all__ = ["DIGEST_LENGTH", "PromptIdentity", "prompt_identity"]
