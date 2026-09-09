"""Where a live explanation run's results land as they happen, so nothing is bought twice.

The generation pass is the one workload in this gate whose output cannot be regenerated for
free: a passage Nova wrote is a passage somebody paid for, and a lost terminal would lose it.
So a result is written down the moment it exists rather than at the end of the run, and the
judge pass and every report afterwards read it back from here instead of asking again.

The file is JSONL under the git-ignored results directory: a header line saying what this run
is, then one line per generation, then one line per verdict. Append-only and flushed per
record, because a buffered writer that loses the last twenty passages on a crash would defeat
the whole point of writing them down at all.

**One file holds both passes.** A verdict is about a generation, and keeping the two in one
place is what lets a judge run be resumed, a report rebuilt and a rejudge refused without
three paths having to agree about which files belong together. The kinds are separate lines,
the judge never rewrites the header, and neither pass can overwrite the other's records.

**Resuming is guarded by identity, not by filename.** A run may only continue a file whose
header names the same commit, dataset name, version and hash, provider, model, mode, splits,
prompt hash and schema hash. Anything else is a different experiment wearing the same path,
and continuing it would blend two runs into one summary -- the quiet error this gate exists
to avoid making. Per-case identity is checked a second time, by the fingerprint each result
already carries; this header check is what stops a file being opened for the wrong run at all.

Nothing here is a credential store. The header holds identifiers, the records hold passages,
verdicts and usage. No AWS token, no API key, no session, no provider header.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from evals.budget import utc_now_iso
from evals.explanation_results import ExplanationJudgeResult, NovaExplanationResult

HEADER_KIND: Final = "explanation_run"
GENERATION_KIND: Final = "generation"
JUDGE_KIND: Final = "judge"

IDENTITY_FIELDS: Final = (
    "git_sha",
    "dataset_name",
    "dataset_version",
    "dataset_hash",
    "provider",
    "model_id",
    "mode",
    "splits",
    "prompt_system_hash",
    "schema_hash",
)
"""What must match for one file to be a continuation of the run that started it.

The prompt and schema hashes are in the list for the reason the per-result fingerprint carries
them too: a resumed run whose production prompt or verdict schema had moved in between would
be two experiments in one summary. ``run_id`` is deliberately absent -- the file's own run id
wins on reopen, because a resumed run is the same run and a second identity for it would make
the cost ledger say the evaluation happened twice.
"""


class ExplanationStoreError(RuntimeError):
    """The file on disk is not one this run may append to, or is not one at all."""


@dataclass(frozen=True, slots=True)
class ExplanationRunHeader:
    """What an explanation result file says about the run that is writing it."""

    run_id: str
    started_at: str
    git_sha: str | None
    dataset_name: str
    dataset_version: str
    dataset_hash: str
    provider: str
    model_id: str | None
    mode: str
    splits: tuple[str, ...]
    prompt_system_hash: str
    schema_hash: str
    region: str | None = None
    """Where a Bedrock model was called. Descriptive telemetry, deliberately not an identity
    field: a Region-scoped inference profile is already named by the model id."""

    def as_payload(self) -> dict[str, object]:
        return {
            "kind": HEADER_KIND,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "git_sha": self.git_sha,
            "dataset_name": self.dataset_name,
            "dataset_version": self.dataset_version,
            "dataset_hash": self.dataset_hash,
            "provider": self.provider,
            "model_id": self.model_id,
            "mode": self.mode,
            "splits": list(self.splits),
            "prompt_system_hash": self.prompt_system_hash,
            "schema_hash": self.schema_hash,
            "region": self.region,
        }

    def identity(self) -> dict[str, object]:
        payload = self.as_payload()
        return {field: payload[field] for field in IDENTITY_FIELDS}

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> ExplanationRunHeader:
        return cls(
            run_id=_text(payload, "run_id"),
            started_at=_text(payload, "started_at"),
            git_sha=_optional_text(payload.get("git_sha")),
            dataset_name=_text(payload, "dataset_name"),
            dataset_version=_text(payload, "dataset_version"),
            dataset_hash=_text(payload, "dataset_hash"),
            provider=_text(payload, "provider"),
            model_id=_optional_text(payload.get("model_id")),
            mode=_text(payload, "mode"),
            splits=tuple(_strings(payload.get("splits"))),
            prompt_system_hash=_text(payload, "prompt_system_hash"),
            schema_hash=_text(payload, "schema_hash"),
            region=_optional_text(payload.get("region")),
        )


class ExplanationResultStore:
    """One run's append-only record, opened for writing or reopened to continue.

    ``generations`` and ``judgements`` are what was already there: the work a previous attempt
    at this run paid for. A generation pass skips the cases in :meth:`completed`, and a judge
    pass skips the ones in :meth:`judged`, which is what makes a failed report a formatting
    problem rather than a second bill.
    """

    def __init__(self, path: Path, header: ExplanationRunHeader) -> None:
        self._path = path
        self._header = header
        self.generations: tuple[NovaExplanationResult, ...] = ()
        self.judgements: tuple[ExplanationJudgeResult, ...] = ()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_text(encoding="utf-8").strip():
            self._reopen()
        else:
            self._append(self._header.as_payload())

    @property
    def path(self) -> Path:
        return self._path

    @property
    def header(self) -> ExplanationRunHeader:
        return self._header

    def _reopen(self) -> None:
        stored, generations, judgements = read_run(self._path)
        if stored.identity() != self._header.identity():
            differing = sorted(
                field
                for field in IDENTITY_FIELDS
                if stored.identity()[field] != self._header.identity()[field]
            )
            raise ExplanationStoreError(
                f"{self._path.name} was written by a different run and cannot be continued; "
                f"these differ: {', '.join(differing)}. Start a new run file rather than "
                f"blending two evaluations into one summary."
            )
        self._header = stored
        self.generations = generations
        self.judgements = judgements

    def completed(self) -> frozenset[str]:
        """Case ids Nova has already answered and that are written down. Never asked again."""
        return frozenset(result.case_id for result in self.generations)

    def judged(self) -> frozenset[str]:
        """Case ids the judge has already answered about. Never asked again."""
        return frozenset(result.case_id for result in self.judgements)

    def record_generation(self, result: NovaExplanationResult) -> NovaExplanationResult:
        """Write one passage down before anything else is attempted, and stamp when.

        Returns the stamped record rather than the one passed in, so a caller reporting on
        what it wrote reports the same object the file holds.
        """
        stamped = (
            result
            if result.recorded_at is not None
            else result.model_copy(update={"recorded_at": utc_now_iso()})
        )
        self._append({"kind": GENERATION_KIND, **stamped.model_dump(mode="json")})
        self.generations = (*self.generations, stamped)
        return stamped

    def record_judgement(self, result: ExplanationJudgeResult) -> ExplanationJudgeResult:
        """Write one verdict down beside the generation it is about, and stamp when."""
        stamped = (
            result
            if result.recorded_at is not None
            else result.model_copy(update={"recorded_at": utc_now_iso()})
        )
        self._append({"kind": JUDGE_KIND, **stamped.model_dump(mode="json")})
        self.judgements = (*self.judgements, stamped)
        return stamped

    def _append(self, payload: Mapping[str, object]) -> None:
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()


type StoredRun = tuple[
    ExplanationRunHeader,
    tuple[NovaExplanationResult, ...],
    tuple[ExplanationJudgeResult, ...],
]
"""One run as it comes back off disk: what it was, what Nova wrote, what the judge said."""


def read_run(path: Path) -> StoredRun:
    """Load one explanation run back: its header, its passages and its verdicts.

    The path that makes a lost terminal cheap and every metric change free. A rescore, a
    rejudge and a report are all rebuilt from here, with no provider in the room.
    """
    if not path.exists():
        raise ExplanationStoreError(f"{path} does not exist")
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise ExplanationStoreError(f"{path.name} is empty")
    header_payload = json.loads(lines[0])
    if not isinstance(header_payload, Mapping) or header_payload.get("kind") != HEADER_KIND:
        raise ExplanationStoreError(f"{path.name} does not begin with an explanation run header")
    header = ExplanationRunHeader.from_payload(header_payload)
    return header, tuple(_generations(lines[1:])), tuple(_judgements(lines[1:]))


def _generations(lines: Sequence[str]) -> Iterator[NovaExplanationResult]:
    for payload in _records(lines, GENERATION_KIND):
        yield NovaExplanationResult.model_validate(payload)


def _judgements(lines: Sequence[str]) -> Iterator[ExplanationJudgeResult]:
    for payload in _records(lines, JUDGE_KIND):
        yield ExplanationJudgeResult.model_validate(payload)


def _records(lines: Sequence[str], kind: str) -> Iterator[dict[str, object]]:
    for line in lines:
        payload = json.loads(line)
        if not isinstance(payload, Mapping) or payload.get("kind") != kind:
            continue
        yield {key: value for key, value in payload.items() if key != "kind"}


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ExplanationStoreError(f"the run header has no {key}")
    return value


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


__all__ = [
    "GENERATION_KIND",
    "HEADER_KIND",
    "IDENTITY_FIELDS",
    "JUDGE_KIND",
    "ExplanationResultStore",
    "ExplanationRunHeader",
    "ExplanationStoreError",
    "StoredRun",
    "read_run",
]
