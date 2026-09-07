"""Loading the gold dataset, and refusing to load a corrupt one.

The dataset is the instrument. A benchmark run against a dataset with a duplicated case, a
resource identifier that does not exist, or a gold outcome that production could never produce
is a benchmark that measures nothing, and it will not say so on its own.

So validation is not a linting pass over JSON. It runs production code:

* every worker case's **deterministic** claim is checked by calling
  :func:`promisepatch.domain.interpretation.interpret`, so a case that says "the lexicon cannot
  read this" about a sentence the lexicon reads perfectly well fails here rather than quietly
  measuring the semantic layer on work it never does;
* every worker case's **expected outcome** is checked by building the reading the gold case
  describes and putting it through
  :func:`promisepatch.domain.grounding.resolve_semantic_observation`, so a hand-written label
  that PromisePatch would never reach fails here rather than making every model look wrong;
* every expected identifier is checked against the frozen evaluation kitchen.

That ordering is the hierarchy this evaluation is built on: where a deterministic verifier can
decide, it outranks the human label, and the human label outranks anybody's opinion. There is
no model judging anything.

The manifest is a committed statement of what the dataset contains, including a content hash
over the cases. It is regenerated deliberately (``python -m evals manifest --write``), so a
dataset change that nobody meant to make fails validation instead of arriving unannounced.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from evals import context
from evals.cases import (
    SCHEMA_VERSION,
    CustomerCase,
    EvalJob,
    EvalSplit,
    Frozen,
    GoldCase,
    Outcome,
    WorkerCase,
    to_model_input,
)
from evals.metrics.worker import offered_ids
from promise_graph.model import ResourceKind
from promisepatch.domain import consent, interpretation
from promisepatch.domain import grounding as grounding_rules
from promisepatch.domain.grounding import GroundingFailure
from promisepatch.domain.observation import (
    ClarificationRequired,
    EscalationReason,
    HumanInterpretationRequired,
    InterpretationOutcome,
    ResolvedObservation,
    ResourceView,
)
from promisepatch.semantic import (
    CandidateBinding,
    CandidateNodeType,
    InterpretUtteranceRequest,
    ObservationInterpretation,
)

DATASET_NAME = "promisepatch-semantic-gold"
DATASET_DIR = Path(__file__).parent / "datasets"
WORKER_FILE = DATASET_DIR / "worker_semantics.json"
CUSTOMER_FILE = DATASET_DIR / "customer_intent.json"
MANIFEST_FILE = DATASET_DIR / "manifest.json"


@dataclass(frozen=True, slots=True)
class DatasetFile:
    """One dataset file: a declared schema version, a job, its provenance, and its cases.

    A dataclass rather than a model: the cases have already been validated individually, and
    re-validating them through a union would let a worker case be re-read as a customer one.
    """

    schema_version: str
    job: EvalJob
    provenance: str
    cases: tuple[GoldCase, ...]


class Manifest(Frozen):
    """What the dataset contains, committed so a change to it is a change somebody made."""

    name: str
    schema_version: str
    version: str
    content_hash: str
    cases: int
    by_job: dict[str, int]
    by_split: dict[str, int]
    by_tag: dict[str, int]


class DatasetError(RuntimeError):
    """The dataset on disk is not one this code can measure anything with."""


@dataclass(frozen=True, slots=True)
class GoldDataset:
    """Every case, in load order, with the identity a run records itself against."""

    version: str
    worker: tuple[WorkerCase, ...]
    customer: tuple[CustomerCase, ...]
    provenance: tuple[str, ...]

    @property
    def cases(self) -> tuple[GoldCase, ...]:
        return (*self.worker, *self.customer)

    @property
    def content_hash(self) -> str:
        """SHA-256 over every case in canonical form. Changes when the data changes."""
        payload = [json.loads(case.model_dump_json()) for case in (*self.worker, *self.customer)]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def split(self, splits: Sequence[EvalSplit] | None) -> GoldDataset:
        """The same dataset narrowed to the given splits, keeping its version."""
        if splits is None:
            return self
        wanted = frozenset(splits)
        return GoldDataset(
            version=self.version,
            worker=tuple(case for case in self.worker if case.split in wanted),
            customer=tuple(case for case in self.customer if case.split in wanted),
            provenance=self.provenance,
        )

    def manifest(self) -> Manifest:
        by_tag: dict[str, int] = {}
        for case in self.cases:
            for tag in case.tags:
                by_tag[tag] = by_tag.get(tag, 0) + 1
        return Manifest(
            name=DATASET_NAME,
            schema_version=SCHEMA_VERSION,
            version=self.version,
            content_hash=self.content_hash,
            cases=len(self.cases),
            by_job={
                EvalJob.WORKER_SEMANTICS.value: len(self.worker),
                EvalJob.CUSTOMER_INTENT.value: len(self.customer),
            },
            by_split={
                split.value: sum(case.split is split for case in self.cases) for split in EvalSplit
            },
            by_tag=dict(sorted(by_tag.items())),
        )


def _read(path: Path, model: type[WorkerCase] | type[CustomerCase]) -> DatasetFile:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DatasetError(f"{path.name}: {error}") from error
    if not isinstance(raw, dict):
        raise DatasetError(f"{path.name}: the file is not an object")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise DatasetError(
            f"{path.name}: schema version {raw.get('schema_version')!r} is not {SCHEMA_VERSION!r}"
        )
    try:
        cases = tuple(model.model_validate(entry) for entry in raw.get("cases", ()))
        return DatasetFile(
            schema_version=raw["schema_version"],
            job=EvalJob(raw["job"]),
            provenance=raw["provenance"],
            cases=cases,
        )
    except (ValidationError, KeyError, ValueError) as error:
        raise DatasetError(f"{path.name}: {error}") from error


def load_dataset(directory: Path = DATASET_DIR) -> GoldDataset:
    """Read both files and the manifest, and return the dataset they describe.

    Structural failures raise here. Semantic failures -- a label production could not produce,
    an identifier that does not exist -- are found by :func:`validate_dataset`, which is run by
    the dataset suite and by the ``validate`` command.
    """
    worker_file = _read(directory / WORKER_FILE.name, WorkerCase)
    customer_file = _read(directory / CUSTOMER_FILE.name, CustomerCase)
    manifest = _load_manifest(directory / MANIFEST_FILE.name)
    return GoldDataset(
        version=manifest.version,
        worker=tuple(case for case in worker_file.cases if isinstance(case, WorkerCase)),
        customer=tuple(case for case in customer_file.cases if isinstance(case, CustomerCase)),
        provenance=(worker_file.provenance, customer_file.provenance),
    )


def _load_manifest(path: Path) -> Manifest:
    try:
        return Manifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise DatasetError(f"{path.name}: {error}") from error


def write_manifest(dataset: GoldDataset, path: Path = MANIFEST_FILE) -> Manifest:
    """Regenerate the committed manifest. A deliberate act, never a side effect of a run."""
    manifest = dataset.manifest()
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest


# ------------------------------------------------------------------------------ validation


def ideal_reading(case: WorkerCase) -> ObservationInterpretation:
    """The reading a perfect model would return for this case, built from the gold fields.

    Used to check the gold *outcome* against production, and by nothing that scores a model. It
    binds exactly the identity the case expects, with no scope hint, no quantity hint and no
    ambiguity flag -- because none of those are read by the resolver, and a gold case that
    depended on one would be asserting something the application ignores.
    """
    if case.expected is None:
        raise DatasetError(f"{case.id}: no model is asked about this sentence")
    observation = context.observation_context(case.id, case.utterance)
    bindings = tuple(
        CandidateBinding(
            node_type=_node_type(observation.resource(resource_id)),
            node_id=resource_id,
            confidence=1.0,
            evidence_span="gold",
        )
        for resource_id in case.expected.proposals
    )
    return ObservationInterpretation(
        category=case.expected.category,
        bindings=bindings,
        out_of_scope=case.expected.out_of_scope,
    )


def _node_type(resource: ResourceView | None) -> CandidateNodeType:
    """Equipment binds as equipment; everything else binds as a resource."""
    if resource is not None and resource.kind is ResourceKind.EQUIPMENT:
        return CandidateNodeType.EQUIPMENT
    return CandidateNodeType.RESOURCE


def _outcome_kind(outcome: InterpretationOutcome) -> Outcome:
    if isinstance(outcome, ResolvedObservation):
        return Outcome.RESOLVED
    if isinstance(outcome, ClarificationRequired):
        return Outcome.CLARIFICATION
    return Outcome.ESCALATED


def _deterministic_problems(case: WorkerCase) -> list[str]:
    """Check the case's claim about the lexicon against the lexicon."""
    observation = context.observation_context(case.id, case.utterance)
    outcome = interpretation.interpret(observation)
    kind = _outcome_kind(outcome)
    problems: list[str] = []
    if kind is not case.deterministic:
        problems.append(
            f"{case.id}: claims the deterministic reading is {case.deterministic.value}, "
            f"production reaches {kind.value}"
        )
    reason = outcome.reason if isinstance(outcome, HumanInterpretationRequired) else None
    if reason != case.deterministic_reason:
        problems.append(
            f"{case.id}: claims deterministic reason {case.deterministic_reason}, "
            f"production reaches {reason}"
        )
    return problems


def _expected_problems(case: WorkerCase) -> list[str]:
    """Check the case's expected outcome by running the reading through production grounding."""
    if case.expected is None:
        if case.semantic_eligible:
            return [
                f"{case.id}: the boundary asks a model about this sentence, so it needs an "
                f"expected reading"
            ]
        return []
    if not case.semantic_eligible:
        return [
            f"{case.id}: carries an expected reading, but the boundary never asks a model "
            f"about a sentence whose deterministic stop is {case.deterministic_reason}"
        ]
    observation = context.observation_context(case.id, case.utterance)
    resolution = grounding_rules.resolve_semantic_observation(
        observation,
        ideal_reading(case),
        deterministic_reason=case.deterministic_reason or EscalationReason.NO_CATEGORY,
    )
    problems: list[str] = []
    if resolution.grounding.failure is not case.expected.grounding:
        problems.append(
            f"{case.id}: expects grounding {case.expected.grounding.value}, production "
            f"reaches {resolution.grounding.failure.value}"
        )
    kind = _outcome_kind(resolution.outcome)
    if kind is not case.expected.outcome:
        problems.append(
            f"{case.id}: expects outcome {case.expected.outcome.value}, production reaches "
            f"{kind.value}"
        )
    if isinstance(resolution.outcome, ClarificationRequired):
        if resolution.outcome.slot is not case.expected.clarification_slot:
            problems.append(
                f"{case.id}: expects clarification slot {case.expected.clarification_slot}, "
                f"production reaches {resolution.outcome.slot.value}"
            )
    elif case.expected.clarification_slot is not None:
        problems.append(f"{case.id}: names a clarification slot but does not expect a question")
    if isinstance(resolution.outcome, HumanInterpretationRequired):
        if resolution.outcome.reason is not case.expected.escalation_reason:
            problems.append(
                f"{case.id}: expects escalation {case.expected.escalation_reason}, production "
                f"reaches {resolution.outcome.reason.value}"
            )
    elif case.expected.escalation_reason is not None:
        problems.append(f"{case.id}: names an escalation reason but does not expect one")
    return problems


def _identifier_problems(case: WorkerCase) -> list[str]:
    """Every expected identifier must exist in the frozen kitchen and have been offered."""
    if case.expected is None:
        return []
    problems: list[str] = []
    request = to_model_input(case).request
    offered: frozenset[str] = frozenset()
    if isinstance(request, InterpretUtteranceRequest):
        offered = offered_ids(request)
    for expected_id in {*case.expected.proposals, *filter(None, [case.expected.resource_id])}:
        if expected_id not in context.resource_ids():
            problems.append(f"{case.id}: names {expected_id!r}, which the fixture does not contain")
        elif expected_id not in offered:
            problems.append(
                f"{case.id}: names {expected_id!r}, which the candidate set does not offer"
            )
    return problems


def _consistency_problems(case: WorkerCase) -> list[str]:
    """Internal coherence a reader would expect and a typo would break."""
    problems: list[str] = []
    expected = case.expected
    if expected is None:
        return problems
    if expected.resource_id is not None and expected.resource_id not in expected.proposals:
        problems.append(f"{case.id}: accepts an identity a correct reading does not propose")
    if expected.out_of_scope and expected.resource_id is not None:
        problems.append(f"{case.id}: is out of scope and still expects an identity")
    if expected.grounding is GroundingFailure.NONE and expected.resource_id is None:
        problems.append(f"{case.id}: expects a grounded reading with no identity")
    ungrounded = expected.grounding is not GroundingFailure.NONE
    if ungrounded and expected.outcome is not Outcome.ESCALATED:
        problems.append(f"{case.id}: expects an ungrounded reading that does not escalate")
    return problems


def _duplicate_problems(cases: Iterable[GoldCase]) -> list[str]:
    """Duplicate ids, and duplicate content wearing two ids."""
    seen_ids: set[str] = set()
    seen_text: dict[str, str] = {}
    problems: list[str] = []
    for case in cases:
        if case.id in seen_ids:
            problems.append(f"{case.id}: duplicate case id")
        seen_ids.add(case.id)
        text = case.utterance if isinstance(case, WorkerCase) else case.reply
        key = " ".join(text.lower().split())
        if key in seen_text:
            problems.append(f"{case.id}: the same text already appears as {seen_text[key]}")
        seen_text[key] = case.id
    return problems


def _customer_problems(case: CustomerCase) -> list[str]:
    """A reply the literal parser reads is a reply no model is ever shown.

    Every inbound reply goes to :func:`promisepatch.domain.consent.read_literal` first, and an
    exact ``YES`` or ``NO`` becomes a decision without a provider being called. A dataset
    carrying one would be measuring a classifier on text it never sees -- and the punctuation
    trimming means ``"yes!!!"`` is one of those, which is exactly the sort of case somebody
    would add without noticing.
    """
    decision = consent.read_literal(case.reply)
    if decision is None:
        return []
    return [
        f"{case.id}: the literal parser reads this reply as {decision.value}, so no model is "
        f"ever asked about it"
    ]


def validate_dataset(dataset: GoldDataset) -> tuple[str, ...]:
    """Everything wrong with this dataset, or an empty tuple.

    Returns problems rather than raising on the first, so a broken dataset is fixed in one pass
    instead of one line at a time.
    """
    problems: list[str] = list(_duplicate_problems(dataset.cases))
    for reply_case in dataset.customer:
        problems.extend(_customer_problems(reply_case))
    for case in dataset.worker:
        problems.extend(_identifier_problems(case))
        problems.extend(_consistency_problems(case))
        problems.extend(_deterministic_problems(case))
        problems.extend(_expected_problems(case))
    if not dataset.worker:
        problems.append("the dataset contains no worker cases")
    if not dataset.customer:
        problems.append("the dataset contains no customer cases")
    for split in EvalSplit:
        if not any(case.split is split for case in dataset.cases):
            problems.append(f"the dataset contains no {split.value} cases")
    return tuple(problems)


def manifest_problems(dataset: GoldDataset, manifest: Manifest) -> tuple[str, ...]:
    """Whether the committed manifest still describes the dataset beside it."""
    computed = dataset.manifest()
    if computed == manifest:
        return ()
    return (
        "the committed manifest does not describe this dataset; regenerate it with "
        f"`python -m evals manifest --write` (hash on disk {manifest.content_hash[:12]}, "
        f"computed {computed.content_hash[:12]})",
    )


__all__ = [
    "CUSTOMER_FILE",
    "DATASET_DIR",
    "DATASET_NAME",
    "MANIFEST_FILE",
    "WORKER_FILE",
    "DatasetError",
    "DatasetFile",
    "GoldDataset",
    "Manifest",
    "ideal_reading",
    "load_dataset",
    "manifest_problems",
    "validate_dataset",
    "write_manifest",
]
