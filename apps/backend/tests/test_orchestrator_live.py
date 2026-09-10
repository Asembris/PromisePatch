"""One bounded live conversation: a real model choosing real verbs, over the real transport.

G5 item 9 asks for exactly this and no more -- one conversational smoke that verifies the
actual tools and the latency, once an implementation exists. It is deselected by default and
never runs in CI::

    AWS_PROFILE=promisepatch PP_LLM_PROVIDER=bedrock PP_AWS_REGION=us-east-1 \\
      PP_BEDROCK_MODEL_ID=us.amazon.nova-2-lite-v1:0 \\
      uv run python scripts/with_local_env.py -- \\
      uv run pytest apps/backend/tests/test_orchestrator_live.py -m "bedrock_live and integration"

It is **not** an evaluation and makes no claim about the model's accuracy. Six turns say
nothing about how often a verb is chosen correctly, and this file does not pretend otherwise.
What it establishes is that the whole path holds together when the answers are a real model's:
the prompt, the forced tool call, the strict schema, the phase check, the confirmation gate,
the MCP client, the Streamable HTTP hop, the intent API, the domain and PostgreSQL.

Every turn is written the way a baker would say it, not the way a test would. If the model
reads them differently the assertions fail, which is the point: an unexpected verb is a finding
rather than something to smooth over.

The record it writes -- turn by turn, with the verb chosen, the tools called, the latency and
the tokens each call cost -- is the evidence the phase document quotes. Nothing in it is
computed by hand.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from _intake_support import BAKER, CANONICAL_REPORT, Intake
from _intake_support import physical as physical
from _mcp_support import BEARER, SERVICE_TOKEN, mcp_over_http, serve

from promisepatch.config import LlmProvider, Settings
from promisepatch.integrations import build_semantic_provider
from promisepatch.main import create_app
from promisepatch.orchestrator import Conversation, Orchestrator, connect
from promisepatch.semantic.contracts import ConversationPhase, SemanticRequest
from promisepatch.semantic.provider import SemanticProvider, SemanticResult

pytestmark = [pytest.mark.integration, pytest.mark.bedrock_live]

RECORD_PATH = Path(os.environ.get("PP_LIVE_SMOKE_RECORD", "live-smoke.json"))

TURNS: tuple[tuple[str, str], ...] = (
    (CANONICAL_REPORT, "REPORT"),
    ("what do you need from me?", "STATUS"),
    ("just raspberries - the strawberries came", "CLARIFY"),
    ("ok, what's the plan then?", "STATUS"),
    ("yes, go ahead", "CONFIRM"),
    ("where does that leave us?", "STATUS"),
)
"""The canonical conversation, and the verb each turn is asking for.

Written as a baker would say them. The expected verb is what a competent reading produces; it
is asserted rather than logged, because a conversation that opened a case out of "what do you
need from me?" would be a finding.
"""


@dataclass
class TurnRecord:
    """What one live turn cost and what it did. Measured, never estimated."""

    said: str
    expected: str
    chose: str | None
    called: list[str]
    latency_ms: int
    model_latency_ms: int | None
    attempts: int
    input_tokens: int | None
    output_tokens: int | None
    phase_after: str
    blocked: str | None
    refusal: str | None


class RecordingProvider:
    """The configured provider, with the telemetry of each call kept for the record.

    A wrapper rather than a change to the loop: what a call cost is a property of the call, and
    the orchestrator has no business carrying one. Behaviour is unchanged -- the same value
    comes back and the same exception propagates.
    """

    def __init__(self, inner: SemanticProvider) -> None:
        self._inner = inner
        self.name = inner.name
        self.results: list[SemanticResult] = []

    async def run(self, request: SemanticRequest) -> SemanticResult:
        result = await self._inner.run(request)
        self.results.append(result)
        return result


def live_settings() -> Settings:
    settings = Settings()
    if settings.llm_provider is not LlmProvider.BEDROCK:
        pytest.skip("set PP_LLM_PROVIDER=bedrock to run the live conversational smoke")
    return settings


def api_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "internal_service_token": SERVICE_TOKEN,
        "surface_worker_id": BAKER,
    }
    values.update(overrides)
    return Settings(**values)


@pytest_asyncio.fixture
async def chain(physical: Intake) -> AsyncIterator[str]:
    async with serve(create_app(api_settings())) as api_base, mcp_over_http(api_base) as server:
        yield server.url


async def test_a_real_model_carries_the_canonical_conversation(
    chain: str, physical: Intake
) -> None:
    """Six spoken turns, a real Nova reading each one, and the rows they leave behind.

    The model is asked one question per turn -- which permitted verb is this -- and supplies
    nothing else. Everything that reaches a tool is the worker's own words or an identity the
    server rendered, so the assertions below about durable state are assertions about the
    deterministic protocol, with a real model in the loop rather than instead of one.
    """
    settings = live_settings()
    provider = RecordingProvider(build_semantic_provider(settings))
    records: list[TurnRecord] = []
    conversation = Conversation()
    case_id: UUID | None = None

    async with connect(chain, token=BEARER, timeout_seconds=60.0) as surface:
        loop = Orchestrator(provider=provider, surface=surface)
        for index, (said, expected) in enumerate(TURNS):
            started = time.perf_counter()
            result = await loop.take_turn(conversation, said, correlation_id=str(uuid4()))
            elapsed = int((time.perf_counter() - started) * 1000)
            conversation = result.conversation
            telemetry = provider.results[-1].telemetry if provider.results else None
            records.append(
                TurnRecord(
                    said=said,
                    expected=expected,
                    chose=result.selected.value if result.selected else None,
                    called=list(result.calls),
                    latency_ms=elapsed,
                    model_latency_ms=telemetry.usage.latency_ms if telemetry else None,
                    attempts=telemetry.attempts if telemetry else 0,
                    input_tokens=telemetry.usage.input_tokens if telemetry else None,
                    output_tokens=telemetry.usage.output_tokens if telemetry else None,
                    phase_after=conversation.phase.value,
                    blocked=result.blocked.value if result.blocked else None,
                    refusal=result.refusal.value if result.refusal else None,
                )
            )

            # The worker process runs where it would in the product: after the sentence that
            # gives it something to do, and never as part of a turn.
            if index == 0:
                assert conversation.case_id is not None
                case_id = UUID(conversation.case_id)
                await physical.drain_intake(case_id)
            if index == 2:
                await physical.drain()

    _write(records, model_id=settings.bedrock_model_id, region=settings.aws_region)

    assert case_id is not None
    assert [record.chose for record in records] == [expected for _, expected in TURNS]
    assert all(record.blocked is None and record.refusal is None for record in records)
    assert all(len(record.called) <= 2 for record in records)
    assert conversation.phase is ConversationPhase.WORKING

    # The durable consequence, read over a separate connection: the worker's own words, twice,
    # attributed by the server, and a case that a real yes moved.
    reports = await physical.reports(case_id)
    assert [row.raw_text for row in reports] == [TURNS[0][0], TURNS[2][0]]
    assert all(row.reported_by == BAKER for row in reports)
    assert (await physical.case(case_id)).state == "EXECUTING"


def _write(records: list[TurnRecord], *, model_id: str, region: str) -> None:
    """The evidence file the phase document quotes. Measured values only."""
    payload = {
        "model_id": model_id,
        "region": region,
        "turns": [asdict(record) for record in records],
        "model_calls": len(records),
        "input_tokens": sum(r.input_tokens or 0 for r in records),
        "output_tokens": sum(r.output_tokens or 0 for r in records),
        "wall_clock_ms": sum(r.latency_ms for r in records),
    }
    RECORD_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
