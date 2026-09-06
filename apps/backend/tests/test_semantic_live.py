"""Two real calls to a real model, through the real workflow. Opt-in, and never in CI.

Everything else in the semantic suites uses a scripted provider, which is the right default:
those tests are about PromisePatch's rules, and rules are better asserted than sampled. What a
script cannot prove is that the whole path -- durable step, candidate set, prompt, Converse,
forced tool use, strict schema, grounding, deterministic resolution, governed transaction --
holds together against structured output that a model actually produced.

So this file exists, it is two cases, and it is deselected by default::

    AWS_PROFILE=promisepatch PP_LLM_PROVIDER=bedrock PP_AWS_REGION=us-east-1 \\
      PP_BEDROCK_MODEL_ID=us.amazon.nova-2-lite-v1:0 \\
      uv run python scripts/with_local_env.py -- uv run pytest -m "bedrock_live and integration"

It is deliberately not an evaluation. Two sentences say nothing about a model's accuracy, and
this suite makes no claim about it: what it asserts is that a real answer is *consumable*, and
that the fail-closed rules hold when the answer is a real model's rather than a test's. Which
model PromisePatch ships with is decided by the evaluation gate, not here.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from _intake_support import Intake
from _intake_support import physical as physical
from _semantic_support import DECK_OVEN, DECK_OVEN_DOWN, THE_BERRIES

from promise_graph.model import ExceptionCategory
from promisepatch.config import LlmProvider, Settings
from promisepatch.domain.observation import (
    CASE_CLARIFYING,
    CASE_NEEDS_HUMAN,
    SOURCE_SEMANTIC_ASSISTED,
    STEP_INTERPRET_SEMANTICALLY,
)
from promisepatch.integrations import build_semantic_provider
from promisepatch.worker import Worker

pytestmark = [pytest.mark.integration, pytest.mark.bedrock_live]


def live_worker(physical: Intake) -> Worker:
    settings = Settings()
    if settings.llm_provider is not LlmProvider.BEDROCK:
        pytest.skip("set PP_LLM_PROVIDER=bedrock to run the live semantic acceptance")
    return physical.worker(semantic=build_semantic_provider(settings))


async def semantic_step(physical: Intake, case_id: UUID) -> Any:
    steps = [
        step for step in await physical.steps(case_id) if step.kind == STEP_INTERPRET_SEMANTICALLY
    ]
    assert steps, "the deterministic reader resolved this sentence; no model was asked"
    return steps[-1]


async def test_a_real_model_reads_a_sentence_the_lexicon_cannot(physical: Intake) -> None:
    """One live call. Grounded against the candidates we supplied, consumed by the workflow.

    The assertion is not "the model got it right" -- it is that whatever it returned passed
    the schema, named only what it was offered, and was turned into a worker-attested fact by
    the ordinary deterministic path, with the baker on the record as the attestor.
    """
    worker = live_worker(physical)
    opened = await physical.report(DECK_OVEN_DOWN)
    await physical.drain_intake(opened.case_id, worker=worker)

    step = await semantic_step(physical, opened.case_id)
    stored = step.result["semantic"]
    assert stored["provider"] == "bedrock"
    assert stored["model_id"]

    exception = await physical.exception(opened.case_id)
    assert exception is not None
    assert exception.category == ExceptionCategory.EQUIPMENT_UNAVAILABLE.value
    assert exception.resource_id == DECK_OVEN
    assert exception.reported_by == "maya"
    assert step.result["interpretation_source"] == SOURCE_SEMANTIC_ASSISTED


async def test_a_real_model_cannot_talk_the_application_out_of_failing_closed(
    physical: Intake,
) -> None:
    """The second live call, on a sentence the bakery's vocabulary does not resolve.

    A capable model will pick a berry, confidently, and may well pick the one a reader would.
    It changes nothing: "berries" is not a name or an alias this bakery authored, so the
    binding is dropped and the case goes to a person with both lines still expected.
    """
    worker = live_worker(physical)
    opened = await physical.report(THE_BERRIES)
    await physical.drain_intake(opened.case_id, worker=worker)

    case = await physical.case(opened.case_id)
    assert case.state in {CASE_NEEDS_HUMAN, CASE_CLARIFYING}
    assert await physical.facts(opened.case_id) == []
    for line in ("cl-vp-today-raspberries", "cl-vp-today-strawberries"):
        assert (await physical.line(line)).received_state == "EXPECTED"
