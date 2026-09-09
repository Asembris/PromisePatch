"""The append-only record a live explanation run writes, and the identity that gates reopening it.

Nothing here reaches a provider: the passages are produced by the offline scripted factory the
whole gate is exercised with, and what is under test is the file -- that a passage is on disk
the moment it exists, that reopening a run continues it rather than starting a second one, and
that a file belonging to a different experiment is refused rather than appended to.

The refusal is the point. A resumed run that silently blended two commits, two datasets or two
prompts into one summary would produce a number nobody could interpret, and it would look
exactly like a number somebody could.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from evals.budget import BudgetGuard, EvalBudget
from evals.cases import EvalSplit
from evals.explanation_dataset import DATASET_NAME, ExplanationDataset, load_explanation_dataset
from evals.explanation_judge import (
    CountedJudge,
    ScriptedJudge,
    StructuredJudge,
)
from evals.explanation_results import ExplanationJudgeResult, NovaExplanationResult
from evals.explanation_runner import (
    LIVE_MODE,
    ScriptedExplanations,
    generate,
    judge_explanations,
    scripted_provider,
    scripted_verdicts,
)
from evals.explanation_store import (
    GENERATION_KIND,
    HEADER_KIND,
    IDENTITY_FIELDS,
    ExplanationResultStore,
    ExplanationRunHeader,
    ExplanationStoreError,
    read_run,
)
from evals.prompts import prompt_identity

from promisepatch.semantic import SemanticJob

RUN_ID = "runstore0001"


@pytest.fixture(scope="module")
def development() -> ExplanationDataset:
    return load_explanation_dataset().split([EvalSplit.DEVELOPMENT])


@pytest.fixture(scope="module")
def two(development: ExplanationDataset) -> ExplanationDataset:
    """Two cases is enough to prove a file: one to write, one to resume onto."""
    return ExplanationDataset(
        version=development.version,
        provenance=development.provenance,
        cases=development.cases[:2],
    )


def header_for(dataset: ExplanationDataset) -> ExplanationRunHeader:
    prompt = prompt_identity(SemanticJob.VERBALISE)
    return ExplanationRunHeader(
        run_id=RUN_ID,
        started_at="2026-09-09T00:00:00+00:00",
        git_sha="0123456789abcdef",
        dataset_name=DATASET_NAME,
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        provider="fake",
        model_id=None,
        mode=LIVE_MODE,
        splits=(EvalSplit.DEVELOPMENT.value,),
        prompt_system_hash=prompt.system_hash,
        schema_hash=prompt.schema_hash,
    )


async def passages(dataset: ExplanationDataset) -> tuple[NovaExplanationResult, ...]:
    outcome = await generate(
        dataset,
        scripted_provider(ScriptedExplanations.from_file()),
        guard=BudgetGuard(EvalBudget(), price=None, live=False),
        provider_name="fake",
        git_sha="0123456789abcdef",
        run_id=RUN_ID,
    )
    return outcome.results


async def verdicts(
    dataset: ExplanationDataset, results: tuple[NovaExplanationResult, ...]
) -> tuple[ExplanationJudgeResult, ...]:
    judge = CountedJudge(StructuredJudge(ScriptedJudge(scripted_verdicts())))
    outcome = await judge_explanations(dataset, results, judge, run_id=RUN_ID)
    return outcome.results


async def test_a_passage_is_on_disk_the_moment_it_exists(
    two: ExplanationDataset, tmp_path: Path
) -> None:
    """The property the whole file exists for: a crash after case one keeps case one."""
    path = tmp_path / "run.jsonl"
    store = ExplanationResultStore(path, header_for(two))
    written: list[str] = []

    async def record() -> None:
        for result in await passages(two):
            store.record_generation(result)
            written.append(result.case_id)
            _, stored, _ = read_run(path)
            assert [item.case_id for item in stored] == written

    await record()
    assert len(written) == 2


async def test_a_run_is_reopened_and_continued_rather_than_restarted(
    two: ExplanationDataset, tmp_path: Path
) -> None:
    path = tmp_path / "run.jsonl"
    first = ExplanationResultStore(path, header_for(two))
    results = await passages(two)
    first.record_generation(results[0])

    second = ExplanationResultStore(path, header_for(two))
    assert second.completed() == {results[0].case_id}
    assert second.header.run_id == RUN_ID
    assert path.read_text(encoding="utf-8").count(f'"kind":"{HEADER_KIND}"') == 1


async def test_verdicts_land_beside_the_passages_without_disturbing_them(
    two: ExplanationDataset, tmp_path: Path
) -> None:
    path = tmp_path / "run.jsonl"
    store = ExplanationResultStore(path, header_for(two))
    results = await passages(two)
    for result in results:
        store.record_generation(result)
    for verdict in await verdicts(two, results):
        store.record_judgement(verdict)

    _header, stored, judged = read_run(path)
    assert [item.case_id for item in stored] == [item.case_id for item in results]
    assert judged
    assert store.judged() == {item.case_id for item in judged}
    assert {item.case_id for item in judged} <= {item.case_id for item in stored}


async def test_a_record_is_stamped_with_when_it_was_written(
    two: ExplanationDataset, tmp_path: Path
) -> None:
    store = ExplanationResultStore(tmp_path / "run.jsonl", header_for(two))
    results = await passages(two)
    assert results[0].recorded_at is None
    stamped = store.record_generation(results[0])
    assert stamped.recorded_at is not None
    _header, stored, _ = read_run(store.path)
    assert stored[0].recorded_at == stamped.recorded_at


type Move = Callable[[ExplanationRunHeader], ExplanationRunHeader]

MOVED: list[tuple[str, Move]] = [
    ("git_sha", lambda header: replace(header, git_sha="ffffffffffffffff")),
    ("dataset_name", lambda header: replace(header, dataset_name="another-dataset")),
    ("dataset_hash", lambda header: replace(header, dataset_hash="0" * 64)),
    ("dataset_version", lambda header: replace(header, dataset_version="9.9.9")),
    ("provider", lambda header: replace(header, provider="bedrock")),
    ("model_id", lambda header: replace(header, model_id="another-model")),
    ("mode", lambda header: replace(header, mode="replay")),
    ("prompt_system_hash", lambda header: replace(header, prompt_system_hash="moved")),
    ("schema_hash", lambda header: replace(header, schema_hash="moved")),
    ("splits", lambda header: replace(header, splits=(EvalSplit.HOLDOUT.value,))),
]
"""Every identity field, one move each. The list is the contract, checked one line at a time."""


@pytest.mark.parametrize(("field", "move"), MOVED, ids=[field for field, _ in MOVED])
async def test_a_file_from_a_different_experiment_is_refused(
    two: ExplanationDataset, tmp_path: Path, field: str, move: Move
) -> None:
    """Every identity field, one at a time. A resume is not a filename match."""
    path = tmp_path / "run.jsonl"
    ExplanationResultStore(path, header_for(two)).record_generation((await passages(two))[0])

    with pytest.raises(ExplanationStoreError) as refused:
        ExplanationResultStore(path, move(header_for(two)))
    assert field in str(refused.value)


def test_every_identity_field_is_covered_by_a_move() -> None:
    """The list above is only a contract if it is the whole of one."""
    assert {field for field, _ in MOVED} == set(IDENTITY_FIELDS)


async def test_the_run_id_is_not_an_identity_field(two: ExplanationDataset, tmp_path: Path) -> None:
    """A resumed run is the same run: the file's id wins, and a second id is not minted."""
    path = tmp_path / "run.jsonl"
    ExplanationResultStore(path, header_for(two))
    reopened = ExplanationResultStore(path, replace(header_for(two), run_id="different0001"))
    assert reopened.header.run_id == RUN_ID


def test_a_file_that_is_not_a_run_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "not-a-run.jsonl"
    path.write_text('{"kind":"something-else"}\n', encoding="utf-8")
    with pytest.raises(ExplanationStoreError):
        read_run(path)


def test_an_absent_file_is_refused_rather_than_read_as_empty(tmp_path: Path) -> None:
    with pytest.raises(ExplanationStoreError):
        read_run(tmp_path / "missing.jsonl")


async def test_lines_of_another_kind_are_ignored_rather_than_misread(
    two: ExplanationDataset, tmp_path: Path
) -> None:
    """A file gains kinds over time. A reader that guessed at an unknown one would be wrong."""
    path = tmp_path / "run.jsonl"
    store = ExplanationResultStore(path, header_for(two))
    store.record_generation((await passages(two))[0])
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind":"note","text":"written by a later version"}\n')

    _header, stored, judged = read_run(path)
    assert len(stored) == 1
    assert judged == ()
    assert f'"kind":"{GENERATION_KIND}"' in path.read_text(encoding="utf-8")


async def test_a_stored_verdict_still_names_the_judge_that_formed_it(
    two: ExplanationDataset, tmp_path: Path
) -> None:
    """Judge identity survives the file. A verdict whose judge was lost is an anonymous opinion."""
    path = tmp_path / "run.jsonl"
    store = ExplanationResultStore(path, header_for(two))
    results = await passages(two)
    formed = await verdicts(two, results)
    for verdict in formed:
        store.record_judgement(verdict)

    _header, _stored, judged = read_run(path)
    assert judged
    for stored_verdict, original in zip(judged, formed, strict=True):
        assert stored_verdict.identity.judge_provider == original.identity.judge_provider
        assert stored_verdict.identity.judge_model_id == original.identity.judge_model_id
        assert stored_verdict.identity.rubric_version == original.identity.rubric_version
        assert (
            stored_verdict.identity.generation_fingerprint
            == original.identity.generation_fingerprint
        )
