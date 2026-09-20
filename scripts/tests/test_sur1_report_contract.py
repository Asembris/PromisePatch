"""``report_outcome``, from the frozen schema to a verdict, with no model anywhere near it.

Arm A's ``E4`` came back with no promises on 18 of 18 baseline attempts across two scored runs.
The Converse tool published ``report`` as a bare ``{"type": "object"}`` with no properties, and
the frozen prompt names the four outcomes without naming one field, so nothing anywhere told the
model that the array is called ``promises`` or that an entry names an ``order``. See
``docs/sur1-v3-forensic-audit.md`` section 5, F6.

**The proof is synthetic and end to end.** A report is built *by walking the published schema* --
never hand-written beside it -- handed to the world's own ``report_outcome``, read by
``_report_row``, and put through the scorer's own ``_report_is_valid``. If the schema ever stops
describing the report the scorer accepts, the generated one stops validating and this fails.

Nothing here opens a socket, calls a provider, drives a scenario or writes a capture.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from scripts.score_safe_useful_recovery import _report_is_valid
from scripts.sur1.adapters import ARGUMENTS, REPORT_TOOL, ReportSchemaError, run_report_schema
from scripts.sur1.bindings.bedrock import ModelConfigurationError, tool_configuration
from scripts.sur1.bindings.receivers import ChannelLedger
from scripts.sur1.bindings.world import LiveScenarioWorld
from scripts.sur1.evidence import FixtureMap, ReceiverEvidence, blind_bundle
from scripts.sur1.frozen import Contract

SCENARIO: Final = "C01"


def contract() -> Contract:
    return Contract.load()


def world_for(loaded: Contract) -> LiveScenarioWorld:
    return LiveScenarioWorld(
        orders=None,  # type: ignore[arg-type]
        channel=None,  # type: ignore[arg-type]
        kitchen=None,  # type: ignore[arg-type]
        database=None,  # type: ignore[arg-type]
        ledger=ChannelLedger(),
        fixture=loaded.document["fixture"]["orders"],
        scenario_id=SCENARIO,
    )


def scored_report(loaded: Contract, world: LiveScenarioWorld) -> Any:
    """The report as the scorer receives it: through the blinding projection, never directly.

    ``_report_is_valid`` reads the scorer's own ``RunReport``, which a harness ``WorkerReport``
    becomes only by going through :func:`~scripts.sur1.evidence.blind_bundle`. Handing the
    harness row straight to the scorer would prove a shape nothing ever produces.
    """
    bundle = blind_bundle(
        ReceiverEvidence(report=world.report),
        run_id="no-run",
        scenario_id=SCENARIO,
        arm_token="token",
        fixtures=FixtureMap.read(loaded.document),
    )
    return bundle.report


def value_for(name: str, schema: Any, *, order: str) -> Any:
    """One field, filled from what the schema itself says about it.

    Two fields carry an identity the schema can only describe the *type* of -- which scenario
    this is, and which order an entry is about -- and those two come from the frozen contract.
    Everything else comes out of the published property: an enumeration takes its first member,
    a nullable takes null, a boolean takes false, a string takes a short one.
    """
    if name == "scenario_id":
        return SCENARIO
    if name == "order":
        return order
    if "enum" in schema:
        first: Any = schema["enum"][0]
        return first
    declared = schema.get("type")
    if isinstance(declared, list):
        return None
    if declared == "boolean":
        return False
    if declared == "string":
        return "generated from the published schema"
    raise AssertionError(f"{name} is published as {schema!r}, which this generator cannot fill")


def generated_report(loaded: Contract) -> dict[str, Any]:
    """A whole ``RunReport``, assembled by reading the schema arm A is given and nothing else."""
    schema = run_report_schema(loaded)
    entry_schema = schema["properties"]["promises"]["items"]["properties"]
    report: dict[str, Any] = {}
    for name, shape in schema["properties"].items():
        if name == "promises":
            report[name] = [
                {
                    field: value_for(field, entry_schema[field], order=order)
                    for field in entry_schema
                }
                for order in loaded.case_universe
            ]
            continue
        report[name] = value_for(name, shape, order="")
    return report


# ----------------------------------------------------------- the schema is the frozen document


def test_the_report_argument_is_no_longer_an_object_with_no_properties() -> None:
    """The exact defect: what was published, and what is published now."""
    published = tool_configuration(
        [{"name": REPORT_TOOL, "description": "", "arguments": dict(ARGUMENTS[REPORT_TOOL])}]
    )
    bare = published["tools"][0]["toolSpec"]["inputSchema"]["json"]["properties"]["report"]

    assert bare == {"type": "object"}, "this is the shape two scored runs were taken with"

    schema = run_report_schema(contract())
    assert set(schema["properties"]) == {"scenario_id", "exception_recorded", "promises"}
    assert schema["properties"]["promises"]["items"]["properties"]


def test_every_published_property_is_read_out_of_the_frozen_manifest() -> None:
    loaded = contract()
    fields = loaded.document["run_report_schema"]["fields"]
    schema = run_report_schema(loaded)

    for name, shape in fields.items():
        head, marker, member = str(name).partition("[].")
        published = (
            schema["properties"][head]["items"]["properties"][member]
            if marker
            else schema["properties"][head]
        )
        assert published["description"] == shape, f"{name} does not carry the frozen words"


def test_the_schema_publishes_no_field_the_other_two_arms_cannot_fill() -> None:
    """``acknowledged_stops`` is read by the harness, is scored, and is not a frozen field.

    The predeclaration records it as empty for arms B and C. Publishing it to arm A alone would
    hand one arm a field its comparators structurally cannot produce.
    """
    schema = run_report_schema(contract())

    assert "acknowledged_stops" not in schema["properties"]
    assert "acknowledged_stops" not in schema["properties"]["promises"]["items"]["properties"]


def test_an_enumerated_field_publishes_the_words_the_scorer_accepts() -> None:
    from scripts.score_safe_useful_recovery import REPORT_OUTCOMES, WORK_STATES

    entry = run_report_schema(contract())["properties"]["promises"]["items"]["properties"]

    assert set(entry["outcome"]["enum"]) == set(REPORT_OUTCOMES)
    assert set(entry["work_state"]["enum"]) == set(WORK_STATES)


def test_a_field_shape_this_reader_cannot_read_is_refused_rather_than_defaulted() -> None:
    loaded = contract()
    broken = dict(loaded.document)
    broken["run_report_schema"] = {"fields": {"scenario_id": "quaternion, who knows"}}

    with pytest.raises(ReportSchemaError, match="names no JSON type"):
        run_report_schema(Contract(identity=loaded.identity, document=broken))


def test_an_array_whose_entries_nothing_describes_is_refused() -> None:
    loaded = contract()
    broken = dict(loaded.document)
    broken["run_report_schema"] = {"fields": {"promises": "array, one per order"}}

    with pytest.raises(ReportSchemaError, match="nothing describes"):
        run_report_schema(Contract(identity=loaded.identity, document=broken))


# -------------------------------------------------- schema -> arguments -> row -> validation


def test_a_report_built_only_from_the_published_schema_survives_the_scorer() -> None:
    """The whole projection, with no model and no run: this is the proof the defect is closed."""
    loaded = contract()
    world = world_for(loaded)

    result = world.invoke(REPORT_TOOL, {"report": generated_report(loaded)})

    assert result == {"received": True}
    row = world.report
    assert row is not None
    assert row.scenario_id == SCENARIO
    assert [promise.order for promise in row.promises] == list(loaded.case_universe)

    scored = scored_report(loaded, world)
    assert scored is not None
    assert _report_is_valid(scored, SCENARIO, loaded.case_universe)


def test_the_report_the_two_scored_runs_actually_produced_is_still_invalid() -> None:
    """An empty report is a nonpass and stays one. The schema does not repair a missing answer."""
    loaded = contract()
    world = world_for(loaded)

    world.invoke(REPORT_TOOL, {"report": {}})

    row = world.report
    assert row is not None and row.promises == ()

    scored = scored_report(loaded, world)
    assert scored is not None
    assert not _report_is_valid(scored, SCENARIO, loaded.case_universe)


def test_the_generated_report_reaches_converse_as_the_schema_the_arm_was_given() -> None:
    """The same schema the generator walked is the one the request would carry."""
    schema = run_report_schema(contract())

    published = tool_configuration(
        [{"name": REPORT_TOOL, "description": "", "arguments": {"report": schema}}]
    )
    json_schema = published["tools"][0]["toolSpec"]["inputSchema"]["json"]

    assert json_schema["properties"]["report"] == schema
    assert json_schema["required"] == ["report"]


def test_a_structured_argument_naming_no_type_is_refused_by_the_converse_binding() -> None:
    with pytest.raises(ModelConfigurationError, match="names no type"):
        tool_configuration(
            [{"name": REPORT_TOOL, "description": "", "arguments": {"report": {"properties": {}}}}]
        )
