"""Where a live run's results land as they happen, so nothing has to be bought twice.

A benchmark against a real model is the one workload here whose output cannot be regenerated
for free. If a summary fails to assemble, a report fails to render, or a terminal is closed,
the model calls that produced the answers are gone and the money with them. So a result is
written down the moment it exists, not at the end of the run.

The file is JSONL under the git-ignored results directory: a header line saying what this run
is, then one line per case. Append-only and flushed per case, because a buffered writer that
loses the last twenty results on a crash would defeat the whole point.

**Resuming is guarded by identity, not by filename.** A run may only continue a file whose
header names the same commit, dataset hash, prompt hashes, provider, model and split. Anything
else is a different experiment wearing the same path, and continuing it would silently blend
two runs into one summary -- which is exactly the sort of quiet error a benchmark exists to
avoid making.

Nothing here is a credential store. The header holds identifiers and counts, the case lines
hold gold labels, readings and usage. No AWS token, no session, no provider header.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from evals.results import CaseResult

HEADER_KIND = "run"
CASE_KIND = "case"

IDENTITY_FIELDS = (
    "git_sha",
    "dataset_version",
    "dataset_hash",
    "prompts",
    "provider",
    "model_id",
    "mode",
    "splits",
)
"""What must match for one file to be a continuation of the run that started it.

The prompt hashes are in the list deliberately. A resumed run whose prompts had changed in
between would be two experiments in one summary, and the identity check is the only thing
standing between that and a number nobody could interpret.
"""


class StoreError(RuntimeError):
    """The file on disk is not one this run may append to."""


@dataclass(frozen=True, slots=True)
class RunHeader:
    """What a result file says about the run that is writing it."""

    run_id: str
    started_at: str
    git_sha: str | None
    dataset_version: str
    dataset_hash: str
    prompts: tuple[Mapping[str, str], ...]
    provider: str
    model_id: str | None
    mode: str
    splits: tuple[str, ...]
    region: str | None = None
    pricing_snapshot: str | None = None

    def as_payload(self) -> dict[str, object]:
        return {
            "kind": HEADER_KIND,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "git_sha": self.git_sha,
            "dataset_version": self.dataset_version,
            "dataset_hash": self.dataset_hash,
            "prompts": [dict(entry) for entry in self.prompts],
            "provider": self.provider,
            "model_id": self.model_id,
            "mode": self.mode,
            "splits": list(self.splits),
            "region": self.region,
            "pricing_snapshot": self.pricing_snapshot,
        }

    def identity(self) -> dict[str, object]:
        payload = self.as_payload()
        return {field: payload[field] for field in IDENTITY_FIELDS}


class ResultStore:
    """One run's append-only result file, opened for writing or reopened to continue.

    ``existing`` is what was already there: the results a previous attempt at this run paid
    for. A caller skips those cases rather than asking the model about them again, which is
    what makes a failed report a formatting problem rather than a second bill.
    """

    def __init__(self, path: Path, header: RunHeader) -> None:
        self._path = path
        self._header = header
        self.existing: tuple[CaseResult, ...] = ()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_text(encoding="utf-8").strip():
            self._reopen()
        else:
            self._start()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def header(self) -> RunHeader:
        return self._header

    def _start(self) -> None:
        self._append(self._header.as_payload())

    def _reopen(self) -> None:
        stored_header, results = read_run(self._path)
        if stored_header.identity() != self._header.identity():
            differing = sorted(
                field
                for field in IDENTITY_FIELDS
                if stored_header.identity()[field] != self._header.identity()[field]
            )
            raise StoreError(
                f"{self._path.name} was written by a different run and cannot be continued; "
                f"these differ: {', '.join(differing)}. Start a new run file rather than "
                f"blending two experiments into one summary."
            )
        # The run id of the file wins. A resumed run is the same run, and a second identity
        # for it would make the cost ledger say the benchmark happened twice.
        self._header = stored_header
        self.existing = results

    def completed(self) -> frozenset[str]:
        """Case ids already answered and written down. Never asked again."""
        return frozenset(result.case_id for result in self.existing)

    def record(self, result: CaseResult) -> None:
        """Write one case result down before anything else is attempted."""
        payload = {"kind": CASE_KIND, **result.model_dump(mode="json")}
        self._append(payload)

    def _append(self, payload: Mapping[str, object]) -> None:
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()


def read_run(path: Path) -> tuple[RunHeader, tuple[CaseResult, ...]]:
    """Load a result file back: its header, and every case it recorded.

    This is the path that makes a lost terminal cheap. A summary and a report are rebuilt from
    here with no provider in the room.
    """
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise StoreError(f"{path.name} is empty")
    header_payload = json.loads(lines[0])
    if header_payload.get("kind") != HEADER_KIND:
        raise StoreError(f"{path.name} does not begin with a run header")
    header = RunHeader(
        run_id=header_payload["run_id"],
        started_at=header_payload["started_at"],
        git_sha=header_payload.get("git_sha"),
        dataset_version=header_payload["dataset_version"],
        dataset_hash=header_payload["dataset_hash"],
        prompts=tuple(header_payload.get("prompts", ())),
        provider=header_payload["provider"],
        model_id=header_payload.get("model_id"),
        mode=header_payload["mode"],
        splits=tuple(header_payload.get("splits", ())),
        region=header_payload.get("region"),
        pricing_snapshot=header_payload.get("pricing_snapshot"),
    )
    return header, tuple(_cases(lines[1:]))


def _cases(lines: Sequence[str]) -> Iterator[CaseResult]:
    for line in lines:
        payload = json.loads(line)
        if payload.get("kind") != CASE_KIND:
            continue
        yield CaseResult.model_validate({k: v for k, v in payload.items() if k != "kind"})


__all__ = [
    "CASE_KIND",
    "HEADER_KIND",
    "IDENTITY_FIELDS",
    "ResultStore",
    "RunHeader",
    "StoreError",
    "read_run",
]
