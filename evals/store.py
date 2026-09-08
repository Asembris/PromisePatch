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
ATTEMPT_KIND = "provider_failure"

IDENTITY_FIELDS = (
    "git_sha",
    "dataset_version",
    "dataset_hash",
    "prompts",
    "provider",
    "model_id",
    "endpoint",
    "mode",
    "splits",
)
"""What must match for one file to be a continuation of the run that started it.

The prompt hashes are in the list deliberately. A resumed run whose prompts had changed in
between would be two experiments in one summary, and the identity check is the only thing
standing between that and a number nobody could interpret.

So is the endpoint, and for the same reason one step further out. A provider name and a model
id do not always locate a model: an OpenAI-compatible protocol is spoken by hosted services,
self-hosted containers and proxies alike, and the same model name behind two of them is two
measurements. Runs that predate this field, and every run against a provider with one canonical
endpoint, record ``None`` -- which matches ``None`` and leaves them continuable exactly as they
were.
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
    endpoint: str | None = None
    """Which host answered, where that is not implied by the provider name. See
    :data:`IDENTITY_FIELDS`."""

    decoding: Mapping[str, object] | None = None
    """How the model was asked to sample, and whether it was asked to reason.

    Recorded because it is part of what was measured -- the same model with a hidden reasoning
    trace on and off is two experiments -- and deliberately *not* in :data:`IDENTITY_FIELDS`:
    it is descriptive telemetry, and the fields that gate a resume are the ones whose drift
    would silently blend two datasets or two models into one summary."""

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
            "endpoint": self.endpoint,
            "decoding": None if self.decoding is None else dict(self.decoding),
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


# ------------------------------------------------- attempts that produced no reading


@dataclass(frozen=True, slots=True)
class ProviderFailureRecord:
    """One provider invocation that produced no reading. Execution evidence, never a result.

    Kept apart from the result file on purpose, and the separation carries a rule each way.

    *Out of the results file*, because a resumed run reads that file to decide what it has
    already bought, and a failure written there would be read back as an answer: the case
    would never be asked again, and an outage would be frozen into the record as a reading.

    *Into a file of its own rather than discarded*, because "we tried, three times, and were
    refused" is worth keeping. It is the difference between a model that answered badly and an
    endpoint nobody could reach, and a project that throws the second away can only report the
    first.

    The fields are identifiers, a coarse category and timings. There is no credential, no
    session token, no request header, no prompt, no reply and no provider message here -- a
    provider's own text can carry an account id or a request context, so the exception class
    name is as far as this goes. Token counts and cost are absent rather than zero: AWS
    reported no usage for these calls, and a zero would be a measurement nobody made.
    """

    run_id: str
    recorded_at: str
    git_sha: str | None
    case_id: str
    job: str
    split: str
    provider: str
    model_id: str | None
    attempt: int
    """Which attempt at this case this was, counting every earlier one in this log."""

    category: str | None
    """The boundary's exception class, the only thing about the fault that is safe to keep."""

    e2e_latency_ms: int | None

    def as_payload(self) -> dict[str, object]:
        return {
            "kind": ATTEMPT_KIND,
            "run_id": self.run_id,
            "recorded_at": self.recorded_at,
            "git_sha": self.git_sha,
            "case_id": self.case_id,
            "job": self.job,
            "split": self.split,
            "provider": self.provider,
            "model_id": self.model_id,
            "attempt": self.attempt,
            "category": self.category,
            "e2e_latency_ms": self.e2e_latency_ms,
            "input_tokens": None,
            "output_tokens": None,
            "estimated_usd": None,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> ProviderFailureRecord:
        return cls(
            run_id=str(payload["run_id"]),
            recorded_at=str(payload["recorded_at"]),
            git_sha=_optional_str(payload.get("git_sha")),
            case_id=str(payload["case_id"]),
            job=str(payload["job"]),
            split=str(payload["split"]),
            provider=str(payload["provider"]),
            model_id=_optional_str(payload.get("model_id")),
            attempt=int(payload["attempt"]) if isinstance(payload["attempt"], int) else 1,
            category=_optional_str(payload.get("category")),
            e2e_latency_ms=_optional_int(payload.get("e2e_latency_ms")),
        )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class ProviderFailureLog:
    """An append-only history of attempts nobody answered, across runs and across commits.

    Deliberately *not* identity-gated the way :class:`ResultStore` is. A result file may only
    be continued by the same commit, because blending two versions of the harness into one
    measurement would corrupt it. This file is the opposite kind of thing: it is the record of
    what infrastructure did, every line says which run and which commit produced it, and the
    whole value of it is that a later attempt under a fixed configuration can sit beside an
    earlier refusal rather than erasing it.

    Nothing here makes a call, and reading it makes none either.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self.records: tuple[ProviderFailureRecord, ...] = _read_attempts(path)

    @property
    def path(self) -> Path:
        return self._path

    def attempts_for(self, case_id: str) -> int:
        return sum(record.case_id == case_id for record in self.records)

    def case_ids(self) -> frozenset[str]:
        return frozenset(record.case_id for record in self.records)

    def record(self, record: ProviderFailureRecord) -> ProviderFailureRecord:
        """Append one failed attempt, flushed before anything else is tried."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.as_payload(), sort_keys=True, separators=(",", ":"))
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
        self.records = (*self.records, record)
        return record


def _read_attempts(path: Path) -> tuple[ProviderFailureRecord, ...]:
    if not path.exists():
        return ()
    records: list[ProviderFailureRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if payload.get("kind") != ATTEMPT_KIND:
            continue
        records.append(ProviderFailureRecord.from_payload(payload))
    return tuple(records)


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
        endpoint=header_payload.get("endpoint"),
        decoding=header_payload.get("decoding"),
    )
    return header, tuple(_cases(lines[1:]))


def _cases(lines: Sequence[str]) -> Iterator[CaseResult]:
    for line in lines:
        payload = json.loads(line)
        if payload.get("kind") != CASE_KIND:
            continue
        yield CaseResult.model_validate({k: v for k, v in payload.items() if k != "kind"})


__all__ = [
    "ATTEMPT_KIND",
    "CASE_KIND",
    "HEADER_KIND",
    "IDENTITY_FIELDS",
    "ProviderFailureLog",
    "ProviderFailureRecord",
    "ResultStore",
    "RunHeader",
    "StoreError",
    "read_run",
]
