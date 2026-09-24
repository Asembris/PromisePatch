"""The runner: what it refuses, and what it writes down before anything may be repaired.

Two claims are under test here, and they are the two the predeclared protocol rests on.

**A scored run over a subset cannot be produced.** ``--scored`` is the intent-to-record flag, and
while any of the sixteen scenarios is unwired it exits non-zero, names the unwired ones, executes
nothing and writes no capture. Every scenario is wired now, so the precondition has to be
constructed to be proved: the wiring is narrowed for the length of the test and the refusal is
asserted exactly as it always was. Nothing about the assertion is softened -- what changed is the
world it is asserted against, and a guarantee that can only be demonstrated while it happens to
bind is not one anybody should rely on afterwards.

**A run's record is complete and is assembled before a repair.** The denominator is the
manifest's sixteen and never the number of scenarios that reported; a wired scenario that reached
no verdict is a ``HARNESS_FAILURE`` rather than an absent row; a development capture carries no
score at all.

Nothing here executes a scenario, touches a database or opens a socket -- the directory's own
guard refuses anything that is not loopback.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripts.run_effect_sets import (
    CAPTURE_DIRECTORY,
    CAPTURE_V2_DIRECTORY,
    CAPTURES,
    FAIL,
    HARNESS_FAILURE,
    MANIFEST_VARIABLE,
    PASS,
    PUBLISHED,
    PUBLISHED_SHA,
    PUBLISHED_V2_SHA,
    RUNNER_VERSION,
    WIRED,
    Outcome,
    capture,
    execute,
    main,
    read_sink,
    reconcile,
    write_capture,
)
from scripts.verify_effect_set_manifest import MANIFEST_PATHS, Manifest, load

EXPECTED_SCENARIOS = 16


@pytest.fixture
def manifest() -> Manifest:
    return load()


def moment() -> datetime:
    return datetime(2026, 9, 15, 11, 30, tzinfo=UTC)


# ------------------------------------------------------------------------------- the wiring


def test_the_runner_scores_the_document_whose_hash_was_published(manifest: Manifest) -> None:
    """The identity is checked before anything runs, so a run always names its labels."""
    assert manifest.content_hash == PUBLISHED_SHA


def test_every_wired_scenario_is_a_scenario_the_manifest_holds(manifest: Manifest) -> None:
    identifiers = {str(scenario["id"]) for scenario in manifest.scenarios}
    assert set(WIRED) <= identifiers
    assert len(set(WIRED)) == len(WIRED)


def test_the_wiring_partitions_the_sixteen_and_the_runner_knows_which_side(
    manifest: Manifest,
) -> None:
    """Stated rather than implied. A gap, whenever there is one, is reported and not a silence."""
    unwired = [
        str(scenario["id"]) for scenario in manifest.scenarios if scenario["id"] not in WIRED
    ]
    assert len(WIRED) + len(unwired) == EXPECTED_SCENARIOS
    assert set(unwired).isdisjoint(WIRED)


def test_every_scenario_of_the_manifest_has_an_executable_path(manifest: Manifest) -> None:
    """All sixteen are wired, which is what makes a scored run possible at all.

    Possible, and not taken: what this asserts is that no scenario is missing an executable
    path. Whether the sixteen agree with their frozen labels is a different question, and it is
    answered by the first scored run rather than here.
    """
    assert set(WIRED) == {str(scenario["id"]) for scenario in manifest.scenarios}


# -------------------------------------------------------------------- the refusal that matters


def test_a_scored_run_is_refused_while_any_scenario_is_unwired(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The protocol's central guarantee: a scored run over a subset is not producible.

    The wiring is narrowed for the length of this test because every scenario now has an
    executable path, which is the one state in which this guarantee cannot demonstrate itself.
    What is asserted is unchanged: non-zero, the unwired ones named, nothing executed and no
    capture written.
    """
    executed: list[Any] = []

    def refuse_to_run(*args: Any, **kwargs: Any) -> int:
        executed.append(args)
        return 0

    monkeypatch.setattr("scripts.run_effect_sets.execute", refuse_to_run)
    monkeypatch.setattr("scripts.run_effect_sets.WIRED", tuple(sorted(set(WIRED) - {"S07"})))

    code = main(["--scored", "--capture-directory", str(tmp_path)])

    assert code == 1
    assert executed == [], "a refused scored run must execute nothing"
    assert list(tmp_path.iterdir()) == [], "a refused scored run must write no capture"
    printed = capsys.readouterr().out
    assert "REFUSED" in printed
    assert "S07" in printed


def test_the_check_mode_needs_no_database_and_reports_the_wiring(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The clean-clone step: identity, coherence and wiring, with nothing else running."""
    assert main(["--check"]) == 0

    printed = capsys.readouterr().out
    assert PUBLISHED_SHA in printed
    assert f"wired         {len(WIRED)}" in printed
    assert f"unwired       {EXPECTED_SCENARIOS - len(WIRED)}" in printed
    for scenario in WIRED:
        assert scenario in printed


# ------------------------------------------------------------------- reading what was reported


def test_a_verdict_file_is_read_back_as_the_outcomes_it_holds(tmp_path: Path) -> None:
    sink = tmp_path / "verdicts.jsonl"
    sink.write_text(
        json.dumps({"scenario": "S02", "outcome": PASS, "diffs": []})
        + "\n"
        + json.dumps(
            {
                "scenario": "S11",
                "outcome": FAIL,
                "reason": "",
                "diffs": [
                    {
                        "checkpoint": "SETTLED",
                        "aspect": "partition",
                        "subject": "blocked",
                        "expected": "{ord-c}",
                        "observed": "{}",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    found = read_sink(sink)
    assert found["S02"].outcome == PASS
    assert found["S11"].outcome == FAIL
    assert found["S11"].diffs[0]["subject"] == "blocked"


def test_a_sink_that_does_not_exist_is_an_empty_report_rather_than_a_crash(tmp_path: Path) -> None:
    """A run whose suite never started reports nothing, and every scenario is then a nonpass."""
    assert read_sink(tmp_path / "absent.jsonl") == {}


def test_a_scenario_reported_twice_is_a_harness_failure(tmp_path: Path) -> None:
    """The last one does not win: a run that said a scenario twice cannot say which it means."""
    sink = tmp_path / "verdicts.jsonl"
    sink.write_text(
        json.dumps({"scenario": "S02", "outcome": FAIL, "diffs": []})
        + "\n"
        + json.dumps({"scenario": "S02", "outcome": PASS, "diffs": []})
        + "\n",
        encoding="utf-8",
    )

    assert read_sink(sink)["S02"].outcome == HARNESS_FAILURE


# ------------------------------------------------------------------------- the denominator


def test_the_denominator_is_the_manifest_and_never_what_reported(manifest: Manifest) -> None:
    """Sixteen outcomes, in manifest order, whatever the run managed to do."""
    outcomes = reconcile(manifest, {})

    assert len(outcomes) == EXPECTED_SCENARIOS
    assert [outcome.scenario for outcome in outcomes] == [
        str(scenario["id"]) for scenario in manifest.scenarios
    ]
    assert all(outcome.outcome == HARNESS_FAILURE for outcome in outcomes)


def test_an_unwired_scenario_is_a_nonpass_that_says_why(
    monkeypatch: pytest.MonkeyPatch, manifest: Manifest
) -> None:
    """Narrowed wiring again, for the same reason and with the same assertion."""
    monkeypatch.setattr("scripts.run_effect_sets.WIRED", tuple(sorted(set(WIRED) - {"S07"})))
    outcomes = {outcome.scenario: outcome for outcome in reconcile(manifest, {})}

    assert outcomes["S07"].outcome == HARNESS_FAILURE
    assert "not wired" in outcomes["S07"].reason


def test_a_wired_scenario_that_reached_no_verdict_is_a_harness_failure(manifest: Manifest) -> None:
    """It raised, timed out or never ran. Either way the harness could not tell, and says so."""
    reported = {"S02": Outcome(scenario="S02", outcome=PASS)}
    outcomes = {outcome.scenario: outcome for outcome in reconcile(manifest, reported)}

    assert outcomes["S02"].outcome == PASS
    assert outcomes["S11"].outcome == HARNESS_FAILURE
    assert "no verdict" in outcomes["S11"].reason


# ----------------------------------------------------------------------------- the capture


def development_capture(manifest: Manifest) -> dict[str, Any]:
    return capture(
        manifest=manifest,
        kind="development",
        command=["scripts/run_effect_sets.py"],
        started_at=moment(),
        finished_at=moment(),
        outcomes=reconcile(manifest, {"S02": Outcome(scenario="S02", outcome=PASS)}),
    )


def test_a_capture_records_what_a_reader_needs_to_reproduce_the_run(manifest: Manifest) -> None:
    document = development_capture(manifest)

    assert document["manifest_sha"] == PUBLISHED_SHA
    assert document["manifest_version"] == manifest.version
    assert document["runner_version"] == RUNNER_VERSION
    assert document["command"] == ["scripts/run_effect_sets.py"]
    assert document["implementation_sha"]
    assert "working_tree_dirty" in document
    assert document["protocol"] == "docs/effect-set-run-protocol.md"


def test_a_development_capture_carries_no_score_at_all(manifest: Manifest) -> None:
    """It is not a score, it has no denominator of sixteen, and none is computed."""
    assert development_capture(manifest)["score"] is None


def test_a_capture_names_every_scenario_whether_or_not_it_is_wired(manifest: Manifest) -> None:
    document = development_capture(manifest)

    assert len(document["outcomes"]) == EXPECTED_SCENARIOS
    assert document["wired"] == list(WIRED)
    assert len(document["unwired"]) == EXPECTED_SCENARIOS - len(WIRED)


def test_a_capture_discloses_whether_anything_that_could_spend_was_configured(
    manifest: Manifest,
) -> None:
    """Names and booleans only: a capture is committed, so it holds no value it reports on."""
    environment = development_capture(manifest)["environment"]

    assert set(environment) == {
        "python",
        "platform",
        "model_provider_configured",
        "aws_credentials_configured",
        "transport_fixtures",
    }
    assert isinstance(environment["model_provider_configured"], bool)
    assert "not proof of live delivery" in environment["transport_fixtures"]


def test_a_capture_is_written_as_one_json_file_named_for_its_kind(
    manifest: Manifest, tmp_path: Path
) -> None:
    path = write_capture(development_capture(manifest), directory=tmp_path)

    assert path.parent == tmp_path
    assert path.name.endswith("-development.json")
    assert json.loads(path.read_text(encoding="utf-8"))["manifest_sha"] == PUBLISHED_SHA


# ---------------------------------------------------------- v2: the separately versioned correction


def test_the_corrected_manifest_is_pinned_and_is_not_the_original() -> None:
    corrected = load(MANIFEST_PATHS["v2"])
    assert corrected.content_hash == PUBLISHED_V2_SHA
    assert corrected.version == "2.0.0"


def test_the_runner_judges_v1_unless_told_otherwise() -> None:
    """The default is the original, so CI's expected-red job and every old command are unchanged."""
    assert PUBLISHED["v1"] == PUBLISHED_SHA
    assert CAPTURES["v1"] == CAPTURE_DIRECTORY
    assert CAPTURES["v2"] == CAPTURE_V2_DIRECTORY
    assert CAPTURE_V2_DIRECTORY != CAPTURE_DIRECTORY


def test_the_child_judges_the_manifest_the_run_names_and_never_an_inherited_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[dict[str, str]] = []

    def record_environment(*args: Any, **kwargs: Any) -> Any:
        seen.append(dict(kwargs["env"]))
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr("scripts.run_effect_sets.subprocess.run", record_environment)
    monkeypatch.setenv(MANIFEST_VARIABLE, "v2")

    execute(tmp_path / "sink.jsonl")
    execute(tmp_path / "sink.jsonl", choice="v2")

    assert [environment[MANIFEST_VARIABLE] for environment in seen] == ["v1", "v2"]


def test_the_check_mode_verifies_the_corrected_manifest_against_its_own_pin(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--manifest", "v2", "--check"]) == 0

    printed = capsys.readouterr().out
    assert PUBLISHED_V2_SHA in printed
    assert "v2.0.0" in printed
    assert PUBLISHED_SHA not in printed


def test_a_corrected_run_captures_its_own_manifest_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    choices: list[str] = []

    def pretend_to_run(sink: Path, *, choice: str = "v1", **kwargs: Any) -> int:
        choices.append(choice)
        return 0

    monkeypatch.setattr("scripts.run_effect_sets.execute", pretend_to_run)

    main(["--manifest", "v2", "--capture-directory", str(tmp_path)])

    assert choices == ["v2"]
    (path,) = tmp_path.iterdir()
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["manifest_sha"] == PUBLISHED_V2_SHA
    assert document["manifest_version"] == "2.0.0"
    assert document["runner_version"] == RUNNER_VERSION
    assert document["kind"] == "development"
