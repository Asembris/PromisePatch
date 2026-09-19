"""Measure what one arms-B-and-C attempt actually spends waiting, against the live local stack.

The dress rehearsal recorded 243.5s and 244.7s for two attempts whose work had finished in about
three seconds, against a frozen 300s per-attempt wall-clock ceiling. This is the measurement that
says why, and it is here rather than in a paragraph because the answer turned on a single field.

**Not a benchmark.** It opens one ordinary case on the Hollow Oak demo world through the
product's own MCP surface and drives it the way a worker does -- say what happened, answer the
one question, approve the plan, confirm it. No ``SUR-1`` scenario is prepared, no arm object is
constructed, no model is called, no scorer runs, no evidence bundle is collected and no capture
is written to a run directory. It consumes no ``SUR-1`` outcome.

**Both drives start from the same world.** The order system and the demo fixture are reset
before each, because the second drive on a world the first one amended would be a different
case and the comparison would be between two attempts rather than between two rules.

**What the second drive changes, and only that.**
The settling fingerprint is swapped back to the one that was there before the fix -- over the
whole ``status`` answer, so the transport's per-call ``correlation_id`` counts as the case
having moved. Its deadline is shortened to thirty seconds so the demonstration is bounded: at the
binding's real deadline the same wait costs four minutes, which is the rehearsal's number.

    uv run python scripts/with_local_env.py -- uv run python -m scripts.measure_sur1_wait
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from scripts.rehearsal.run import stack
from scripts.sur1.bindings import promisepatch as binding
from scripts.sur1.bindings.promisepatch import live_worker_surface

REPO: Final = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT: Final = REPO / "docs" / "sur1-realisation"

UTTERANCE: Final = "the raspberry delivery from Valley Produce did not arrive this morning"
ANSWER: Final = "just the raspberries"
"""One of the two options the product's own clarification offers on this demo world."""

NOT_A_BENCHMARK: Final = (
    "This document measures how long the SUR-1 worker surface waits, on the ordinary Hollow Oak "
    "demo world. No SUR-1 scenario was prepared, no arm was driven, no model was called, no "
    "scorer ran and no comparative number exists. It is not a SUR-1 run."
)


def surface() -> Any:
    config = stack()
    return live_worker_surface(
        mcp_url=config.mcp_url,
        bearer_token=config.mcp_bearer_token,
        api_base_url=config.api_base_url,
        origin=config.workspace_origin,
        username=config.workspace_worker,
        password=config.workspace_password,
    )


def _whole_answer(reading: Any) -> str:
    """The settling fingerprint as it was before the fix: every field the answer carried."""
    return json.dumps(dict(reading), sort_keys=True, default=str)


def differing_keys(first: Any, second: Any) -> list[str]:
    """Which fields two consecutive readings of one motionless case disagree on."""
    return sorted(key for key in set(first) | set(second) if first.get(key) != second.get(key))


def timed(live: Any, what: str, call: Any) -> dict[str, Any]:
    before = live.tools.calls.count("status")
    started = time.monotonic()
    answer = call()
    return {
        "after": what,
        "waited_seconds": round(time.monotonic() - started, 2),
        "status_calls": live.tools.calls.count("status") - before,
        "ended_with": answer.get("needs"),
        "plan_id": answer.get("plan_id"),
    }


def drive(label: str, *, defect: bool, deadline: float) -> dict[str, Any]:
    """One whole attempt on the demo world, with every wait timed and counted."""
    # The defect, reinstated exactly: the settling rule's fingerprint over the whole answer,
    # correlation id and all. Swapping the function rather than emptying ``NOT_THE_CASE`` puts
    # back the code that was there instead of approximating it, and the constant stays ``Final``
    # because nothing in the harness reassigns it. Restored in the ``finally`` below.
    original = binding._fingerprint
    if defect:
        binding._fingerprint = _whole_answer
    try:
        live = surface()
        live.deadline_seconds = deadline
        waits = [timed(live, "report", lambda: live.report_exception(UTTERANCE))]
        if waits[-1]["ended_with"] == "clarification":
            waits.append(timed(live, "clarify", lambda: live.answer_clarification(ANSWER)))
        if waits[-1]["ended_with"] == "confirmation":
            plan = str(waits[-1]["plan_id"])
            waits.append(timed(live, "confirm", lambda: live.confirm_plan(plan)))
        first = live.status()
        second = live.status()
        return {
            "label": label,
            "correlation_id_in_the_fingerprint": defect,
            "deadline_seconds": deadline,
            "case_id": live.case_id,
            "waits": waits,
            "total_waited_seconds": round(sum(wait["waited_seconds"] for wait in waits), 2),
            "two_consecutive_readings_of_one_case_differ_in": differing_keys(first, second),
        }
    finally:
        binding._fingerprint = original


def reset() -> None:
    """Both systems back to the Hollow Oak demo, so the two drives start from one world."""
    import httpx2

    httpx2.post(f"{stack().order_system_base_url}/admin/reset", timeout=30.0).raise_for_status()
    subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/with_local_env.py",
            "--",
            "uv",
            "run",
            "pp",
            "reset-demo-state",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    time.sleep(2.0)


def measure(*, defect_deadline: float = 30.0) -> dict[str, Any]:
    reset()
    with_the_fix = drive("with the fix", defect=False, deadline=240.0)
    reset()
    with_the_defect = drive(
        "with the correlation id back in the fingerprint",
        defect=True,
        deadline=defect_deadline,
    )
    reset()
    terminal = [
        run["waits"][-1]
        for run in (with_the_fix, with_the_defect)
        if run["waits"][-1]["ended_with"] is None
    ]
    return {
        "not_a_benchmark": NOT_A_BENCHMARK,
        "measured_at": datetime.now(UTC).isoformat(),
        "frozen_wall_clock_ceiling_seconds": 300,
        "binding_deadline_seconds": 240.0,
        "same_world_for_both": True,
        "runs": [with_the_fix, with_the_defect],
        "terminal_wait": {
            "with_the_fix": terminal[0] if terminal else None,
            "with_the_defect": terminal[1] if len(terminal) > 1 else None,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="measure-sur1-wait",
        description="Time every wait in one attempt on the demo world, with and without the fix.",
    )
    parser.add_argument("--out", default="")
    parser.add_argument("--defect-deadline", type=float, default=30.0)
    arguments = parser.parse_args(argv)

    report = measure(defect_deadline=arguments.defect_deadline)
    destination = (
        Path(arguments.out)
        if arguments.out
        else EVIDENCE_ROOT / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-wait-measurement.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"written to {destination.relative_to(REPO)}")
    return 0


if __name__ == "__main__":  # pragma: no cover - a command line, exercised through main()
    raise SystemExit(main())
