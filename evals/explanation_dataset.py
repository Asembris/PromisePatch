"""Loading the explanation dataset, and refusing to load one production could not have produced.

The dataset is the instrument, and a fixture describing a state the engine cannot reach measures
nothing while looking exactly like a measurement. So validation is not a lint pass over JSON. It
checks each case against the application's own code and its own vocabularies:

* every value on a fact drawn from a closed set must be one of the phrases
  :data:`~promisepatch.domain.explanations.CLOSED_VOCABULARIES` says the engine emits, so a
  hand-written reason cannot be one no rule produces;
* every fixture's facts, in order, must be a subsequence of what the production projection emits
  for that surface, and must contain the facts it always emits;
* the ``required`` set must be exactly the one production's own projection would compute from
  those facts, so a case cannot demand more or less of a passage than the workflow would;
* the whole fixture must build a real :class:`~promisepatch.semantic.contracts.VerbaliseRequest`,
  which is where the fact-count ceiling, the id pattern and the word cap are enforced by the
  application rather than restated here;
* the deterministic renderer must be able to phrase it, inside the surface's own cap, because a
  fallback that fails is a case where explaining an outcome could block recovering it.

And the split balance is checked without printing a holdout case: counts, families and ids are
assertable, prose is not. A test failure message that dumps holdout passages has unsealed the
holdout in the CI log of the run that was protecting it.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import Field, ValidationError

from evals.cases import EvalSplit, Frozen
from evals.explanation_cases import (
    SCHEMA_VERSION,
    ExplanationEvalCase,
    ExplanationFamily,
    ExplanationTag,
    FactsFixture,
    supported_digits,
)
from promise_graph.evidence import Reachability
from promise_graph.model import Classification, ConstraintKind, ReasonDetail
from promise_graph.revalidation import RevalidationOutcome
from promisepatch.domain.explanations import (
    CLOSED_VOCABULARIES,
    CONSTRAINT_PREFIXES,
    WORD_LIMITS,
    ExplanationSurface,
    FactId,
    render,
)

DATASET_NAME = "promisepatch-explanation-gold"
DATASET_DIR = Path(__file__).parent / "datasets"
CASES_FILE = DATASET_DIR / "explanation_gold.json"
MANIFEST_FILE = DATASET_DIR / "explanation_manifest.json"
CALIBRATION_FILE = DATASET_DIR / "explanation_calibration.json"

TOTAL_CASES: Final = 35
CASES_PER_FAMILY: Final = 5
DEVELOPMENT_PER_FAMILY: Final = 3
HOLDOUT_PER_FAMILY: Final = 2
"""The frozen shape. Seven families of five, three development and two holdout in each."""


# --------------------------------------------------------------- what production emits


FACT_ORDER: Final[dict[ExplanationSurface, tuple[FactId, ...]]] = {
    ExplanationSurface.PLAN_SUMMARY: (
        FactId.CASE_EXCEPTION,
        FactId.RESOURCE_AFFECTED,
        FactId.CASE_AFFECTED,
        FactId.CASE_UNAFFECTED,
        FactId.CASE_AUTOMATIC,
        FactId.CASE_APPROVAL,
        FactId.CASE_BLOCKED,
    ),
    ExplanationSurface.TRACK_OUTCOME: (
        FactId.PROMISE_CUSTOMER,
        FactId.PROMISE_ORDER,
        FactId.PROMISE_ITEM,
        FactId.IMPACT_OUTCOME,
        FactId.IMPACT_REACHABILITY,
        FactId.IMPACT_REASON,
        FactId.RESOURCE_AFFECTED,
        FactId.RESOURCE_REQUIRED,
        FactId.RESOURCE_AVAILABLE,
        FactId.RESOURCE_SHORTFALL,
        FactId.RECOVERY_OPTION,
        FactId.RECOVERY_VARIANT,
        FactId.RECOVERY_SUBSTITUTE,
        FactId.CONSTRAINT_CITED,
    ),
    ExplanationSurface.CUSTOMER_WAIT: (
        FactId.PROMISE_CUSTOMER,
        FactId.PROMISE_ORDER,
        FactId.PROMISE_ITEM,
        FactId.RECOVERY_VARIANT,
        FactId.APPROVAL_STATE,
        FactId.APPROVAL_DEADLINE,
        FactId.CONSENT_AUTHORITY,
        FactId.CONSENT_READING,
    ),
    ExplanationSurface.REVALIDATION: (
        FactId.PROMISE_CUSTOMER,
        FactId.PROMISE_ORDER,
        FactId.REVALIDATION_OUTCOME,
        FactId.REVALIDATION_CHECK,
        FactId.REVALIDATION_COMPARISON,
        FactId.REVALIDATION_NEXT,
    ),
}
"""The order each projection in :mod:`promisepatch.domain.explanations` appends its facts in.

A fixture's facts must be a subsequence of its surface's tuple. Order is checked rather than
only membership because the facts fingerprint is computed over the sequence: a fixture in some
other order is a fixture whose identity no production call could ever produce.
"""

FACT_LABELS: Final[dict[tuple[ExplanationSurface, FactId], str]] = {
    (ExplanationSurface.PLAN_SUMMARY, FactId.CASE_EXCEPTION): "what happened",
    (ExplanationSurface.PLAN_SUMMARY, FactId.RESOURCE_AFFECTED): "what is short",
    (ExplanationSurface.PLAN_SUMMARY, FactId.CASE_AFFECTED): "promises affected",
    (ExplanationSurface.PLAN_SUMMARY, FactId.CASE_UNAFFECTED): "promises untouched",
    (ExplanationSurface.PLAN_SUMMARY, FactId.CASE_AUTOMATIC): "recovered without asking anyone",
    (ExplanationSurface.PLAN_SUMMARY, FactId.CASE_APPROVAL): "waiting on a customer's approval",
    (ExplanationSurface.PLAN_SUMMARY, FactId.CASE_BLOCKED): "blocked, going to the owner",
    (ExplanationSurface.TRACK_OUTCOME, FactId.PROMISE_CUSTOMER): "customer",
    (ExplanationSurface.TRACK_OUTCOME, FactId.PROMISE_ORDER): "order",
    (ExplanationSurface.TRACK_OUTCOME, FactId.PROMISE_ITEM): "item ordered",
    (ExplanationSurface.TRACK_OUTCOME, FactId.IMPACT_OUTCOME): "outcome",
    (ExplanationSurface.TRACK_OUTCOME, FactId.IMPACT_REACHABILITY): (
        "how the exception reaches it"
    ),
    (ExplanationSurface.TRACK_OUTCOME, FactId.IMPACT_REASON): "reason",
    (ExplanationSurface.TRACK_OUTCOME, FactId.RESOURCE_AFFECTED): "ingredient short",
    (ExplanationSurface.TRACK_OUTCOME, FactId.RESOURCE_REQUIRED): "needed",
    (ExplanationSurface.TRACK_OUTCOME, FactId.RESOURCE_AVAILABLE): (
        "available before the task starts"
    ),
    (ExplanationSurface.TRACK_OUTCOME, FactId.RESOURCE_SHORTFALL): "short by",
    (ExplanationSurface.TRACK_OUTCOME, FactId.RECOVERY_OPTION): "recovery",
    (ExplanationSurface.TRACK_OUTCOME, FactId.RECOVERY_VARIANT): ("pre-authored variant selected"),
    (ExplanationSurface.TRACK_OUTCOME, FactId.RECOVERY_SUBSTITUTE): "substitute ingredient",
    (ExplanationSurface.TRACK_OUTCOME, FactId.CONSTRAINT_CITED): "constraint on the order",
    (ExplanationSurface.CUSTOMER_WAIT, FactId.PROMISE_CUSTOMER): "customer",
    (ExplanationSurface.CUSTOMER_WAIT, FactId.PROMISE_ORDER): "order",
    (ExplanationSurface.CUSTOMER_WAIT, FactId.PROMISE_ITEM): "item ordered",
    (ExplanationSurface.CUSTOMER_WAIT, FactId.RECOVERY_VARIANT): (
        "change the customer was asked about"
    ),
    (ExplanationSurface.CUSTOMER_WAIT, FactId.APPROVAL_STATE): "where the request stands",
    (ExplanationSurface.CUSTOMER_WAIT, FactId.APPROVAL_DEADLINE): "answer needed by",
    (ExplanationSurface.CUSTOMER_WAIT, FactId.CONSENT_AUTHORITY): "what counts as an answer",
    (ExplanationSurface.CUSTOMER_WAIT, FactId.CONSENT_READING): (
        "non-authoritative reading of their message"
    ),
    (ExplanationSurface.REVALIDATION, FactId.PROMISE_CUSTOMER): "customer",
    (ExplanationSurface.REVALIDATION, FactId.PROMISE_ORDER): "order",
    (ExplanationSurface.REVALIDATION, FactId.REVALIDATION_OUTCOME): "revalidation outcome",
    (ExplanationSurface.REVALIDATION, FactId.REVALIDATION_CHECK): "the check that decided it",
    (ExplanationSurface.REVALIDATION, FactId.REVALIDATION_COMPARISON): "expected against found",
    (ExplanationSurface.REVALIDATION, FactId.REVALIDATION_NEXT): "what happens next",
}
"""The label each projection attaches to each fact, by surface.

Labels are part of the request the model is shown and part of the facts fingerprint, so a
fixture that got one wrong would be measuring a prompt production never sends. Two facts carry a
different label on different surfaces -- what is short on a plan summary is the ingredient short
on a track, and a variant is the selection on a track and the thing the customer was asked about
on a wait -- and that is why this is keyed by the pair.
"""

ALWAYS_EMITTED: Final[dict[ExplanationSurface, frozenset[FactId]]] = {
    ExplanationSurface.PLAN_SUMMARY: frozenset(FACT_ORDER[ExplanationSurface.PLAN_SUMMARY]),
    ExplanationSurface.TRACK_OUTCOME: frozenset(
        {
            FactId.PROMISE_CUSTOMER,
            FactId.PROMISE_ORDER,
            FactId.PROMISE_ITEM,
            FactId.IMPACT_OUTCOME,
            FactId.IMPACT_REACHABILITY,
            FactId.IMPACT_REASON,
        }
    ),
    ExplanationSurface.CUSTOMER_WAIT: frozenset(
        {
            FactId.PROMISE_CUSTOMER,
            FactId.PROMISE_ORDER,
            FactId.PROMISE_ITEM,
            FactId.APPROVAL_STATE,
            FactId.APPROVAL_DEADLINE,
            FactId.CONSENT_AUTHORITY,
        }
    ),
    ExplanationSurface.REVALIDATION: frozenset(
        {
            FactId.PROMISE_CUSTOMER,
            FactId.PROMISE_ORDER,
            FactId.REVALIDATION_OUTCOME,
            FactId.REVALIDATION_NEXT,
        }
    ),
}
"""The facts every call to a projection produces, whatever the case. A fixture missing one
describes a call that cannot happen."""


CLASSIFICATION_OF: Final[dict[ExplanationFamily, Classification]] = {
    ExplanationFamily.TRACK_AUTO_RECOVERABLE: Classification.AUTO_RECOVERABLE,
    ExplanationFamily.TRACK_APPROVAL_REQUIRED: Classification.APPROVAL_REQUIRED,
    ExplanationFamily.TRACK_BLOCKED: Classification.BLOCKED,
    ExplanationFamily.TRACK_UNAFFECTED: Classification.UNAFFECTED,
}

REASONS_FOR: Final[dict[Classification, frozenset[ReasonDetail]]] = {
    Classification.UNAFFECTED: frozenset(
        {ReasonDetail.NOT_REACHABLE, ReasonDetail.SHORTFALL_COVERED}
    ),
    Classification.AUTO_RECOVERABLE: frozenset(
        {
            ReasonDetail.PREAPPROVAL_COVERS,
            ReasonDetail.NOT_VISIBLE_NO_ASK,
            ReasonDetail.EQUIPMENT_REASSIGNED,
        }
    ),
    Classification.APPROVAL_REQUIRED: frozenset(
        {ReasonDetail.VISIBLE_CHANGE_ASK, ReasonDetail.NOT_PREAPPROVED}
    ),
    Classification.BLOCKED: frozenset(
        {
            ReasonDetail.UNKNOWN_QUANTITY,
            ReasonDetail.NOSUB_CONSTRAINT,
            ReasonDetail.NO_PREAUTHORED_VARIANT,
            ReasonDetail.EXCLUDED_SUBSTITUTE,
            ReasonDetail.INSUFFICIENT_SUBSTITUTE_STOCK,
            ReasonDetail.NO_ALTERNATIVE_EQUIPMENT,
            ReasonDetail.NO_CONSTRAINT_SNAPSHOT,
            ReasonDetail.CONFLICTING_CONSTRAINTS,
        }
    ),
}
"""Which sub-causes each classification can carry, read off ``promise_graph.classification``.

Restated as a mapping rather than derived, because the engine expresses it as control flow over
three modules. The pairs are asserted against the engine's own enums, so a reason that stops
existing breaks this table rather than passing quietly.
"""

OUTCOME_PHRASE_OF: Final[dict[Classification, str]] = {
    classification: CLOSED_VOCABULARIES[FactId.IMPACT_OUTCOME][classification.value]
    for classification in Classification
}
REASON_PHRASE_OF: Final[dict[ReasonDetail, str]] = {
    detail: CLOSED_VOCABULARIES[FactId.IMPACT_REASON][detail.value] for detail in ReasonDetail
}
DETAIL_OF_REASON: Final[dict[str, ReasonDetail]] = {
    phrase: detail for detail, phrase in REASON_PHRASE_OF.items()
}
CONSTRAINT_FOR: Final[dict[ReasonDetail, ConstraintKind]] = {
    ReasonDetail.PREAPPROVAL_COVERS: ConstraintKind.PREAPPROVED_ALTERNATIVE,
    ReasonDetail.VISIBLE_CHANGE_ASK: ConstraintKind.ASK_BEFORE_VISIBLE_CHANGE,
    ReasonDetail.NOSUB_CONSTRAINT: ConstraintKind.NO_SUBSTITUTION,
    ReasonDetail.EXCLUDED_SUBSTITUTE: ConstraintKind.EXCLUDE_RESOURCE,
}
"""The four sub-causes that come from a recorded constraint, and which constraint each names.

``promise_graph.options`` cites a constraint on exactly these and on nothing else, and
``build_promise_evidence`` carries the citation through. So a fixture whose reason is one of
these and which cites no constraint -- or which cites one on a reason that never cites -- is
describing an evidence record the engine does not build, and its passage would then be measured
against a rule the case does not actually have.
"""

REACHABILITY_FOR: Final[dict[ReasonDetail, str]] = {
    ReasonDetail.NOT_REACHABLE: CLOSED_VOCABULARIES[FactId.IMPACT_REACHABILITY][
        Reachability.NO_PATH.value
    ],
    ReasonDetail.SHORTFALL_COVERED: CLOSED_VOCABULARIES[FactId.IMPACT_REACHABILITY][
        Reachability.REACHABLE_COVERED.value
    ],
}
"""The two unaffected readings, kept apart. Spec 13.1's distinction is the whole family.

Both halves come from production's own vocabulary rather than from a phrase written here, so a
wording change in the projection breaks this table instead of silently making every unaffected
case pass a check that no longer means anything.
"""

UNAFFECTED_PHRASE: Final = OUTCOME_PHRASE_OF[Classification.UNAFFECTED]

REVALIDATION_CHECKS: Final[dict[str, RevalidationOutcome]] = {
    "track and case are waiting": RevalidationOutcome.NOOP,
    "order state and version unchanged": RevalidationOutcome.STALE,
    "pinned recipe version unchanged": RevalidationOutcome.STALE,
    "constraint snapshot unchanged": RevalidationOutcome.STALE,
    "substitute still available": RevalidationOutcome.STALE,
    "production task not started and still ahead": RevalidationOutcome.STALE,
    "approval deadline not passed": RevalidationOutcome.EXPIRED,
    "sender is the order's approval channel": RevalidationOutcome.UNAUTHORIZED,
    "decision came from the literal parser": RevalidationOutcome.NOOP,
    "request not already decided": RevalidationOutcome.NOOP,
}
"""The ten checks by the name the engine gives them, and the outcome each one's failure produces.

Restated, because ``promise_graph.revalidation`` expresses both as literals inside one function
and neither is exported. The restatement is pinned rather than trusted: the dataset suite runs
the engine's own :func:`~promise_graph.revalidation.revalidate` and asserts every name it emits
is a key here with the outcome this table gives it, so a renamed check fails a test instead of
letting a fixture name a check nobody runs.
"""

OUTCOME_OF_REVALIDATION_PHRASE: Final[dict[str, RevalidationOutcome]] = {
    CLOSED_VOCABULARIES[FactId.REVALIDATION_OUTCOME][outcome.value]: outcome
    for outcome in RevalidationOutcome
}
NEXT_PHRASE_OF: Final[dict[RevalidationOutcome, str]] = {
    outcome: CLOSED_VOCABULARIES[FactId.REVALIDATION_NEXT][outcome.value]
    for outcome in RevalidationOutcome
}

_COUNT = re.compile(r"^\d+$")
_QUANTITY = re.compile(r"^(an unknown amount|\d+(?:\.\d+)? \S+)$")
_DEADLINE = re.compile(r"^\d{1,2} [A-Z][a-z]+ at \d{2}:\d{2}$")


# ------------------------------------------------------------------------ the dataset


class ExplanationManifest(Frozen):
    """What the dataset contains, committed so a change to it is a change somebody made."""

    name: str
    schema_version: str
    version: str
    content_hash: str
    cases: int
    by_family: dict[str, int]
    by_split: dict[str, int]
    by_family_split: dict[str, dict[str, int]]
    by_tag: dict[str, int]


class CalibrationExample(Frozen):
    """One hand-authored candidate passage and what a correct judgement of it looks like.

    Development-only, and never a prompt example: the judge is shown facts and a passage, and
    these say what the answer should have been. They exist so that the first live judging run can
    be checked against something before its numbers are believed -- and the expected values are
    ranges, because a rubric that demanded an exact 4 would be calibrating the judge against a
    coin toss.
    """

    id: str = Field(pattern=r"^calibrate\.[a-z_]+$")
    case_id: str
    label: str = Field(min_length=1, max_length=80)
    candidate: str = Field(min_length=1, max_length=800)
    expect_outcome_contradiction: bool = False
    expect_authority_contradiction: bool = False
    expect_unsupported_entity_or_option: bool = False
    expect_unsupported_guarantee: bool = False
    expect_unsupported_quantity_in_words: bool = False
    faithfulness_range: tuple[int, int]
    causal_completeness_range: tuple[int, int]
    clarity_range: tuple[int, int]
    brevity_range: tuple[int, int]
    speech_naturalness_range: tuple[int, int]
    note: str = Field(default="", max_length=400)

    def ranges(self) -> dict[str, tuple[int, int]]:
        return {
            "faithfulness": self.faithfulness_range,
            "causal_completeness": self.causal_completeness_range,
            "clarity": self.clarity_range,
            "brevity": self.brevity_range,
            "speech_naturalness": self.speech_naturalness_range,
        }

    def expected_flags(self) -> dict[str, bool]:
        return {
            "outcome_contradiction": self.expect_outcome_contradiction,
            "authority_contradiction": self.expect_authority_contradiction,
            "unsupported_entity_or_option": self.expect_unsupported_entity_or_option,
            "unsupported_guarantee": self.expect_unsupported_guarantee,
            "unsupported_quantity_in_words": self.expect_unsupported_quantity_in_words,
        }


class ExplanationDatasetError(RuntimeError):
    """The dataset on disk is not one this code can measure anything with."""


@dataclass(frozen=True, slots=True)
class ExplanationDataset:
    """Every case, in load order, with the identity a run records itself against."""

    version: str
    provenance: str
    cases: tuple[ExplanationEvalCase, ...]
    identity_hash: str | None = None
    """The frozen dataset a selection was cut from, or ``None`` for the dataset as loaded.

    A split or a narrowed selection is a view of the committed dataset, not a dataset of its
    own. The records a run writes name the dataset they measured, and the hash they carry has
    to be the one the manifest, the run header and the authorisation all name -- so a view
    keeps its source's identity rather than hashing the handful of cases it happens to hold.
    """

    @property
    def content_hash(self) -> str:
        """The identity of the frozen dataset. Changes when the committed data changes.

        For the dataset as loaded this is a SHA-256 over every case in canonical form. For a
        view produced by :meth:`split` or :meth:`select` it is the identity of the dataset the
        view was cut from: the same cases, selected differently, are the same dataset.
        """
        if self.identity_hash is not None:
            return self.identity_hash
        payload = [json.loads(case.model_dump_json()) for case in self.cases]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def split(self, splits: Sequence[EvalSplit] | None) -> ExplanationDataset:
        if splits is None:
            return self
        wanted = frozenset(splits)
        return self.select(case.id for case in self.cases if case.split in wanted)

    def select(self, case_ids: Iterable[str]) -> ExplanationDataset:
        """The same dataset with only the named cases in it. Identity is unchanged."""
        chosen = frozenset(case_ids)
        return ExplanationDataset(
            version=self.version,
            provenance=self.provenance,
            cases=tuple(case for case in self.cases if case.id in chosen),
            identity_hash=self.content_hash,
        )

    def family(self, family: ExplanationFamily) -> tuple[ExplanationEvalCase, ...]:
        return tuple(case for case in self.cases if case.family is family)

    def manifest(self) -> ExplanationManifest:
        by_tag: dict[str, int] = {}
        for case in self.cases:
            for tag in case.tags:
                by_tag[tag.value] = by_tag.get(tag.value, 0) + 1
        return ExplanationManifest(
            name=DATASET_NAME,
            schema_version=SCHEMA_VERSION,
            version=self.version,
            content_hash=self.content_hash,
            cases=len(self.cases),
            by_family={
                family.value: sum(case.family is family for case in self.cases)
                for family in ExplanationFamily
            },
            by_split={
                split.value: sum(case.split is split for case in self.cases) for split in EvalSplit
            },
            by_family_split={
                family.value: {
                    split.value: sum(
                        case.family is family and case.split is split for case in self.cases
                    )
                    for split in EvalSplit
                }
                for family in ExplanationFamily
            },
            by_tag=dict(sorted(by_tag.items())),
        )


def load_explanation_dataset(directory: Path = DATASET_DIR) -> ExplanationDataset:
    """Read the case file and the committed manifest, and return the dataset they describe."""
    path = directory / CASES_FILE.name
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExplanationDatasetError(f"{path.name}: {error}") from error
    if not isinstance(raw, dict):
        raise ExplanationDatasetError(f"{path.name}: the file is not an object")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ExplanationDatasetError(
            f"{path.name}: schema version {raw.get('schema_version')!r} is not {SCHEMA_VERSION!r}"
        )
    try:
        cases = tuple(ExplanationEvalCase.model_validate(entry) for entry in raw.get("cases", ()))
        provenance = str(raw["provenance"])
    except (ValidationError, KeyError, ValueError) as error:
        raise ExplanationDatasetError(f"{path.name}: {error}") from error
    manifest = load_manifest(directory / MANIFEST_FILE.name)
    return ExplanationDataset(version=manifest.version, provenance=provenance, cases=cases)


def load_manifest(path: Path = MANIFEST_FILE) -> ExplanationManifest:
    try:
        return ExplanationManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise ExplanationDatasetError(f"{path.name}: {error}") from error


def write_manifest(dataset: ExplanationDataset, path: Path = MANIFEST_FILE) -> ExplanationManifest:
    """Regenerate the committed manifest. A deliberate act, never a side effect of a run."""
    manifest = dataset.manifest()
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest


def load_calibration(path: Path = CALIBRATION_FILE) -> tuple[CalibrationExample, ...]:
    """The five development-only judge calibration examples. Nothing here calls a judge."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return tuple(CalibrationExample.model_validate(entry) for entry in raw["examples"])
    except (OSError, json.JSONDecodeError, ValidationError, KeyError) as error:
        raise ExplanationDatasetError(f"{path.name}: {error}") from error


# ------------------------------------------------------------------------- validation


def _vocabulary_problems(case: ExplanationEvalCase) -> list[str]:
    """Every fact value drawn from a closed set must be one production can emit."""
    problems: list[str] = []
    for fixture in case.facts.facts:
        vocabulary = CLOSED_VOCABULARIES.get(fixture.id)
        if vocabulary is not None and fixture.value not in set(vocabulary.values()):
            problems.append(
                f"{case.id}: {fixture.id.value} is {fixture.value!r}, which is not a phrase "
                f"promisepatch.domain.explanations emits"
            )
        if fixture.id is FactId.CONSTRAINT_CITED and not any(
            fixture.value.startswith(f"{prefix}, recorded by ") for prefix in CONSTRAINT_PREFIXES
        ):
            problems.append(
                f"{case.id}: constraint.cited is {fixture.value!r}, which is not one of "
                f"production's constraint phrases followed by who recorded it"
            )
        if fixture.id in _QUANTITY_FACTS and not _QUANTITY.match(fixture.value):
            problems.append(
                f"{case.id}: {fixture.id.value} is {fixture.value!r}, which is not a quantity "
                f"the renderer produces"
            )
        if fixture.id in _COUNT_FACTS and not _COUNT.match(fixture.value):
            problems.append(f"{case.id}: {fixture.id.value} is {fixture.value!r}, not a count")
        if fixture.id is FactId.APPROVAL_DEADLINE and not _DEADLINE.match(fixture.value):
            problems.append(
                f"{case.id}: approval.deadline is {fixture.value!r}, which is not the instant "
                f"the renderer produces"
            )
    return problems


_QUANTITY_FACTS: Final = frozenset(
    {FactId.RESOURCE_REQUIRED, FactId.RESOURCE_AVAILABLE, FactId.RESOURCE_SHORTFALL}
)
_COUNT_FACTS: Final = frozenset(
    {
        FactId.CASE_AFFECTED,
        FactId.CASE_UNAFFECTED,
        FactId.CASE_AUTOMATIC,
        FactId.CASE_APPROVAL,
        FactId.CASE_BLOCKED,
    }
)


def _shape_problems(case: ExplanationEvalCase) -> list[str]:
    """The facts must be a subsequence of what this surface's projection emits, in its order."""
    problems: list[str] = []
    surface = case.surface
    if case.facts.surface is not surface:
        problems.append(
            f"{case.id}: family {case.family.value} is asked on {surface.value}, and the "
            f"fixture declares {case.facts.surface.value}"
        )
        return problems

    order = FACT_ORDER[surface]
    present = [fixture.id for fixture in case.facts.facts]
    unknown = [fact_id.value for fact_id in present if fact_id not in order]
    if unknown:
        problems.append(
            f"{case.id}: {', '.join(sorted(unknown))} is not a fact the {surface.value} "
            f"projection emits"
        )
    elif not _is_subsequence(present, order):
        problems.append(
            f"{case.id}: the facts are not in the order the {surface.value} projection appends "
            f"them, so no production call could produce this fingerprint"
        )
    missing = sorted(
        fact_id.value for fact_id in ALWAYS_EMITTED[surface] if fact_id not in set(present)
    )
    if missing:
        problems.append(
            f"{case.id}: the {surface.value} projection always emits {', '.join(missing)}"
        )
    for fixture in case.facts.facts:
        label = FACT_LABELS.get((surface, fixture.id))
        if label is not None and fixture.label != label:
            problems.append(
                f"{case.id}: the {surface.value} projection labels {fixture.id.value} "
                f"{label!r}, and the fixture labels it {fixture.label!r}"
            )
    return problems


def _is_subsequence(present: Sequence[FactId], order: Sequence[FactId]) -> bool:
    iterator = iter(order)
    return all(any(candidate is fact_id for candidate in iterator) for fact_id in present)


def expected_required(facts: FactsFixture) -> tuple[FactId, ...] | None:
    """What production's own projection would mark required, given exactly these facts.

    ``None`` when the fixture is not shaped like anything a projection emits, in which case
    :func:`_shape_problems` has already said so and a second complaint would be noise.
    """
    present = {fixture.id for fixture in facts.facts}
    surface = facts.surface
    if surface is ExplanationSurface.PLAN_SUMMARY:
        return (FactId.CASE_EXCEPTION, FactId.CASE_AFFECTED, FactId.CASE_UNAFFECTED)
    if surface is ExplanationSurface.CUSTOMER_WAIT:
        return (FactId.APPROVAL_STATE, FactId.CONSENT_AUTHORITY)
    if surface is ExplanationSurface.REVALIDATION:
        required = [FactId.REVALIDATION_OUTCOME, FactId.REVALIDATION_NEXT]
        if FactId.REVALIDATION_CHECK in present:
            required.append(FactId.REVALIDATION_CHECK)
        return tuple(required)
    outcome = facts.value_of(FactId.IMPACT_OUTCOME)
    if outcome is None:
        return None
    required = [FactId.IMPACT_OUTCOME, FactId.IMPACT_REASON]
    if outcome == UNAFFECTED_PHRASE:
        required.append(FactId.IMPACT_REACHABILITY)
    if FactId.RESOURCE_SHORTFALL in present:
        required.append(FactId.RESOURCE_SHORTFALL)
    if FactId.RECOVERY_VARIANT in present:
        required.append(FactId.RECOVERY_VARIANT)
    if FactId.CONSTRAINT_CITED in present:
        required.append(FactId.CONSTRAINT_CITED)
    return tuple(required)


def _citation_problems(case: ExplanationEvalCase, classification: Classification) -> list[str]:
    """A cited constraint must be the one this sub-cause cites, and absent when it cites none."""
    reason = case.facts.value_of(FactId.IMPACT_REASON)
    detail = DETAIL_OF_REASON.get(reason or "")
    cited = case.facts.value_of(FactId.CONSTRAINT_CITED)
    expected_kind = None if detail is None else CONSTRAINT_FOR.get(detail)
    if expected_kind is None:
        if cited is not None:
            return [
                f"{case.id}: {classification.value} for {reason!r} cites no constraint, and the "
                f"fixture carries one"
            ]
        return []
    if cited is None:
        return [
            f"{case.id}: {reason!r} is a recorded {expected_kind.value} constraint, and the "
            f"fixture cites none"
        ]
    phrase = CONSTRAINT_PHRASE_OF[expected_kind]
    if not cited.startswith(f"{phrase}, recorded by "):
        return [
            f"{case.id}: {reason!r} cites a {expected_kind.value} constraint, and the fixture "
            f"cites {cited!r}"
        ]
    return []


def _recovery_problems(case: ExplanationEvalCase, classification: Classification) -> list[str]:
    """A recovery is described only where the classifier chose one.

    An unaffected or blocked promise has no chosen option, so the projection emits no recovery
    fact at all. A fixture carrying one would be handing a model an alternative to offer on a
    case whose whole finding is that there is none.
    """
    present = case.facts.ids()
    recovery = {
        FactId.RECOVERY_OPTION.value,
        FactId.RECOVERY_VARIANT.value,
        FactId.RECOVERY_SUBSTITUTE.value,
    }
    chose = classification in {Classification.AUTO_RECOVERABLE, Classification.APPROVAL_REQUIRED}
    if chose and FactId.RECOVERY_OPTION.value not in present:
        return [f"{case.id}: {classification.value} means an option was chosen, and none is here"]
    if not chose and present & recovery:
        return [
            f"{case.id}: {classification.value} chooses no option, and the fixture describes "
            f"{', '.join(sorted(present & recovery))}"
        ]
    if classification is Classification.UNAFFECTED and present & _RESOURCE_FACTS:
        return [
            f"{case.id}: an unaffected promise has no quantified shortfall, and the fixture "
            f"states {', '.join(sorted(present & _RESOURCE_FACTS))}"
        ]
    return []


_RESOURCE_FACTS: Final = frozenset(
    {
        FactId.RESOURCE_AFFECTED.value,
        FactId.RESOURCE_REQUIRED.value,
        FactId.RESOURCE_AVAILABLE.value,
        FactId.RESOURCE_SHORTFALL.value,
    }
)

CONSTRAINT_PHRASE_OF: Final[dict[ConstraintKind, str]] = {
    ConstraintKind.NO_SUBSTITUTION: "no substitution",
    ConstraintKind.PREAPPROVED_ALTERNATIVE: "a pre-approved alternative",
    ConstraintKind.ASK_BEFORE_VISIBLE_CHANGE: "ask before a visible change",
    ConstraintKind.EXCLUDE_RESOURCE: "an excluded ingredient",
}
"""Each constraint kind's rendered phrase. Asserted against production's own
:data:`~promisepatch.domain.explanations.CONSTRAINT_PREFIXES` by the dataset suite, so the four
strings cannot drift from the projection that emits them."""


def _outcome_problems(case: ExplanationEvalCase) -> list[str]:
    """A track family's outcome and reason must be a pair the classifier can actually produce."""
    if case.family not in CLASSIFICATION_OF:
        return []
    problems: list[str] = []
    classification = CLASSIFICATION_OF[case.family]
    outcome = case.facts.value_of(FactId.IMPACT_OUTCOME)
    expected_outcome = OUTCOME_PHRASE_OF[classification]
    if outcome != expected_outcome:
        problems.append(
            f"{case.id}: family {case.family.value} means {classification.value}, and the "
            f"fixture's outcome phrase is {outcome!r}"
        )
    reason = case.facts.value_of(FactId.IMPACT_REASON)
    allowed = {REASON_PHRASE_OF[detail] for detail in REASONS_FOR[classification]}
    if reason not in allowed:
        problems.append(f"{case.id}: {reason!r} is not a reason {classification.value} can carry")
    if classification is Classification.UNAFFECTED:
        reachability = case.facts.value_of(FactId.IMPACT_REACHABILITY)
        detail = DETAIL_OF_REASON.get(reason or "")
        if detail is not None and reachability != REACHABILITY_FOR[detail]:
            problems.append(
                f"{case.id}: reason {reason!r} and reachability {reachability!r} describe two "
                f"different unaffected readings"
            )
    problems.extend(_citation_problems(case, classification))
    problems.extend(_recovery_problems(case, classification))
    if classification is Classification.BLOCKED and case.expected.recovery_permitted:
        problems.append(
            f"{case.id}: a blocked promise's facts carry no permitted next action unless one "
            f"is stated, and this case states none"
        )
    return problems


def _revalidation_problems(case: ExplanationEvalCase) -> list[str]:
    """A revalidation fixture must name a real check, and the outcome that check produces.

    The engine runs the ten checks and picks the deciding one; the projection reads that off the
    result. A fixture pairing "the approval window closed" with the recipe-version check would be
    describing a revalidation the engine cannot reach, and would then measure a model on a story
    nobody can tell.
    """
    if case.family is not ExplanationFamily.REVALIDATION:
        return []
    problems: list[str] = []
    outcome_phrase = case.facts.value_of(FactId.REVALIDATION_OUTCOME)
    outcome = OUTCOME_OF_REVALIDATION_PHRASE.get(outcome_phrase or "")
    if outcome is None:
        return [f"{case.id}: {outcome_phrase!r} is not a revalidation outcome"]
    next_phrase = case.facts.value_of(FactId.REVALIDATION_NEXT)
    if next_phrase != NEXT_PHRASE_OF[outcome]:
        problems.append(
            f"{case.id}: {outcome.value} is followed by {NEXT_PHRASE_OF[outcome]!r}, and the "
            f"fixture says {next_phrase!r}"
        )
    check = case.facts.value_of(FactId.REVALIDATION_CHECK)
    if check is None:
        if outcome is not RevalidationOutcome.PROCEED:
            problems.append(
                f"{case.id}: only PROCEED reaches an outcome with no failing check, and this "
                f"case is {outcome.value}"
            )
        return problems
    if check not in REVALIDATION_CHECKS:
        problems.append(f"{case.id}: {check!r} is not one of the engine's ten checks")
    elif REVALIDATION_CHECKS[check] is not outcome:
        problems.append(
            f"{case.id}: the check {check!r} fails to {REVALIDATION_CHECKS[check].value}, and "
            f"the fixture claims {outcome.value}"
        )
    if FactId.REVALIDATION_COMPARISON not in {f.id for f in case.facts.facts}:
        problems.append(
            f"{case.id}: the projection emits the deciding check and its comparison together"
        )
    return problems


def _expectation_problems(case: ExplanationEvalCase) -> list[str]:
    """The declared hard constraints must be the ones the fixture actually implies."""
    problems: list[str] = []
    expected = case.expected
    if expected.word_limit != case.word_limit:
        problems.append(
            f"{case.id}: declares a {expected.word_limit}-word cap; {case.surface.value} is "
            f"{case.word_limit}"
        )
    computed = expected_required(case.facts)
    if computed is not None and tuple(case.facts.required) != computed:
        problems.append(
            f"{case.id}: production would require "
            f"{', '.join(fact_id.value for fact_id in computed)}, and the fixture requires "
            f"{', '.join(fact_id.value for fact_id in case.facts.required)}"
        )
    declared = tuple(expected.required_fact_refs)
    actual = tuple(fact_id.value for fact_id in case.facts.required)
    if declared != actual:
        problems.append(f"{case.id}: expected required refs {declared} do not match {actual}")
    if expected.decisive_fact not in case.facts.ids():
        problems.append(
            f"{case.id}: the decisive fact {expected.decisive_fact!r} is not one of its facts"
        )
    digits = tuple(sorted(supported_digits(case.facts)))
    if tuple(sorted(expected.supported_numbers)) != digits:
        problems.append(
            f"{case.id}: declares supported numbers {sorted(expected.supported_numbers)}, the "
            f"facts supply {list(digits)}"
        )
    if case.family is ExplanationFamily.CUSTOMER_WAIT and not expected.approval_outstanding:
        problems.append(
            f"{case.id}: every customer wait has a decision outstanding, and this one does not "
            f"declare it"
        )
    if case.family is not ExplanationFamily.CUSTOMER_WAIT and expected.approval_outstanding:
        problems.append(f"{case.id}: only a customer wait can have a decision outstanding")
    if case.family is ExplanationFamily.TRACK_UNAFFECTED and expected.decisive_fact not in {
        FactId.IMPACT_REACHABILITY.value,
        FactId.IMPACT_REASON.value,
    }:
        problems.append(
            f"{case.id}: an unaffected promise turns on its causal reason, so the decisive "
            f"fact must be its reachability or its reason"
        )
    if case.family is ExplanationFamily.REVALIDATION:
        wanted = (
            FactId.REVALIDATION_CHECK.value
            if FactId.REVALIDATION_CHECK.value in case.facts.ids()
            else FactId.REVALIDATION_OUTCOME.value
        )
        if expected.decisive_fact != wanted:
            problems.append(
                f"{case.id}: the engine already picked the deciding check, so the decisive "
                f"fact must be {wanted}"
            )
    return problems


def _production_problems(case: ExplanationEvalCase) -> list[str]:
    """Build the real request and render the real fallback. Production decides, not this module."""
    problems: list[str] = []
    facts = case.explanation_facts()
    try:
        request = facts.request()
    except (ValidationError, ValueError) as error:
        return [f"{case.id}: production refuses this request: {error}"]
    if request.word_limit != WORD_LIMITS[case.surface]:  # pragma: no cover - structural
        problems.append(f"{case.id}: the request's word limit is not the surface's")
    try:
        passage = render(facts)
    except KeyError as error:
        return [*problems, f"{case.id}: the deterministic renderer cannot phrase it: {error}"]
    if len(passage.split()) > case.word_limit:
        problems.append(
            f"{case.id}: the deterministic passage is {len(passage.split())} words against a "
            f"cap of {case.word_limit}"
        )
    decisive = case.facts.value_of(FactId(case.expected.decisive_fact))
    if decisive is not None and decisive.lower() not in passage.lower():
        problems.append(
            f"{case.id}: the deterministic passage does not carry {case.expected.decisive_fact}, "
            f"which this outcome cannot honestly be explained without"
        )
        # Compared case-insensitively because the renderer raises the first letter of whichever
        # value opens a sentence. That is the only transformation it applies to a fact's text.
    if len(case.reference.split()) > case.word_limit:
        problems.append(
            f"{case.id}: the reference passage is {len(case.reference.split())} words against a "
            f"cap of {case.word_limit}"
        )
    return problems


def _balance_problems(dataset: ExplanationDataset) -> list[str]:
    """Counts, families and splits. Says numbers and case ids; never says holdout prose."""
    problems: list[str] = []
    if len(dataset.cases) != TOTAL_CASES:
        problems.append(f"the dataset holds {len(dataset.cases)} cases, not {TOTAL_CASES}")
    for family in ExplanationFamily:
        cases = dataset.family(family)
        if len(cases) != CASES_PER_FAMILY:
            problems.append(f"{family.value} holds {len(cases)} cases, not {CASES_PER_FAMILY}")
        development = sum(case.split is EvalSplit.DEVELOPMENT for case in cases)
        holdout = sum(case.split is EvalSplit.HOLDOUT for case in cases)
        if development != DEVELOPMENT_PER_FAMILY:
            problems.append(
                f"{family.value} holds {development} development cases, not "
                f"{DEVELOPMENT_PER_FAMILY}"
            )
        if holdout != HOLDOUT_PER_FAMILY:
            problems.append(
                f"{family.value} holds {holdout} holdout cases, not {HOLDOUT_PER_FAMILY}"
            )
    return problems


def _duplicate_problems(cases: Iterable[ExplanationEvalCase]) -> list[str]:
    """Duplicate ids, duplicate fact fingerprints, and duplicate reference prose."""
    seen_ids: set[str] = set()
    seen_facts: dict[str, str] = {}
    seen_reference: dict[str, str] = {}
    problems: list[str] = []
    for case in cases:
        if case.id in seen_ids:
            problems.append(f"{case.id}: duplicate case id")
        seen_ids.add(case.id)
        fingerprint = case.explanation_facts().fingerprint()
        if fingerprint in seen_facts:
            problems.append(
                f"{case.id}: the same facts already appear as {seen_facts[fingerprint]}"
            )
        seen_facts[fingerprint] = case.id
        key = " ".join(case.reference.lower().split())
        if key in seen_reference:
            problems.append(
                f"{case.id}: the same reference passage already appears as {seen_reference[key]}"
            )
        seen_reference[key] = case.id
    return problems


REQUIRED_TAGS: Final[frozenset[ExplanationTag]] = frozenset(
    {
        ExplanationTag.CANONICAL,
        ExplanationTag.QUANTITY,
        ExplanationTag.MULTIPLE_NUMBERS,
        ExplanationTag.NUMBER_WORDS,
        ExplanationTag.INSTRUCTION_LIKE_DATA,
        ExplanationTag.AUTHORITY_SENSITIVE,
        ExplanationTag.UNAFFECTED_PRECISION,
        ExplanationTag.STALE_REASON,
        ExplanationTag.SIMILAR_REASON_CODES,
        ExplanationTag.NEGATIVE_FACT,
    }
)
"""Coverage this dataset claims. A tag nobody uses is a dimension nobody is measuring."""


def _coverage_problems(dataset: ExplanationDataset) -> list[str]:
    used = {tag for case in dataset.cases for tag in case.tags}
    missing = sorted(tag.value for tag in REQUIRED_TAGS - used)
    problems = [f"no case covers {', '.join(missing)}"] if missing else []
    canonical = [
        case
        for case in dataset.cases
        if ExplanationTag.CANONICAL in case.tags and case.split is EvalSplit.DEVELOPMENT
    ]
    if len(canonical) < 4:
        problems.append(
            f"the four canonical Hollow Oak outcomes anchor the development split; "
            f"{len(canonical)} canonical development cases are present"
        )
    return problems


def validate_explanation_dataset(dataset: ExplanationDataset) -> tuple[str, ...]:
    """Everything wrong with this dataset, or an empty tuple.

    Returns problems rather than raising on the first, so a broken dataset is fixed in one pass.
    No message contains a case's reference or its fact values beyond the one that is wrong, and
    none prints a passage merely to say a count is off.
    """
    problems: list[str] = [
        *_balance_problems(dataset),
        *_duplicate_problems(dataset.cases),
        *_coverage_problems(dataset),
    ]
    for case in dataset.cases:
        shape = _shape_problems(case)
        problems.extend(shape)
        problems.extend(_vocabulary_problems(case))
        if not shape:
            problems.extend(_outcome_problems(case))
            problems.extend(_expectation_problems(case))
            problems.extend(_revalidation_problems(case))
        problems.extend(_production_problems(case))
    return tuple(problems)


def manifest_problems(
    dataset: ExplanationDataset, manifest: ExplanationManifest
) -> tuple[str, ...]:
    """Whether the committed manifest still describes the dataset beside it."""
    computed = dataset.manifest()
    if computed == manifest:
        return ()
    return (
        "the committed explanation manifest does not describe this dataset; regenerate it with "
        f"`python -m evals explanation-manifest --write` (hash on disk "
        f"{manifest.content_hash[:12]}, computed {computed.content_hash[:12]})",
    )


def calibration_problems(
    dataset: ExplanationDataset, examples: Sequence[CalibrationExample]
) -> tuple[str, ...]:
    """The calibration set must be five development cases, each with a coherent expectation."""
    problems: list[str] = []
    if len(examples) != 5:
        problems.append(f"the calibration set holds {len(examples)} examples, not 5")
    by_id = {case.id: case for case in dataset.cases}
    for example in examples:
        case = by_id.get(example.case_id)
        if case is None:
            problems.append(f"{example.id}: names {example.case_id}, which is not in the dataset")
            continue
        if case.split is not EvalSplit.DEVELOPMENT:
            problems.append(f"{example.id}: calibration may only use development cases")
        if len(example.candidate.split()) > case.word_limit:
            problems.append(
                f"{example.id}: the candidate passage is longer than the surface's word cap, so "
                f"production would have refused it before a judge saw it"
            )
        for name, (low, high) in example.ranges().items():
            if not 1 <= low <= high <= 5:
                problems.append(f"{example.id}: {name} range {low}..{high} is not inside 1..5")
    return tuple(problems)


__all__ = [
    "ALWAYS_EMITTED",
    "CALIBRATION_FILE",
    "CASES_FILE",
    "CASES_PER_FAMILY",
    "CLASSIFICATION_OF",
    "CONSTRAINT_FOR",
    "CONSTRAINT_PHRASE_OF",
    "DATASET_DIR",
    "DATASET_NAME",
    "DETAIL_OF_REASON",
    "DEVELOPMENT_PER_FAMILY",
    "FACT_LABELS",
    "FACT_ORDER",
    "HOLDOUT_PER_FAMILY",
    "MANIFEST_FILE",
    "NEXT_PHRASE_OF",
    "OUTCOME_OF_REVALIDATION_PHRASE",
    "OUTCOME_PHRASE_OF",
    "REACHABILITY_FOR",
    "REASONS_FOR",
    "REASON_PHRASE_OF",
    "REQUIRED_TAGS",
    "REVALIDATION_CHECKS",
    "TOTAL_CASES",
    "UNAFFECTED_PHRASE",
    "CalibrationExample",
    "ExplanationDataset",
    "ExplanationDatasetError",
    "ExplanationManifest",
    "calibration_problems",
    "expected_required",
    "load_calibration",
    "load_explanation_dataset",
    "load_manifest",
    "manifest_problems",
    "validate_explanation_dataset",
    "write_manifest",
]
