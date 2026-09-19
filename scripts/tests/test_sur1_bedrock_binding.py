"""The baseline's model binding, proved against no provider and no account.

The one claim worth making about this binding is that the request it would send is the request
the frozen contract describes. That is provable without a socket, because
:func:`~scripts.sur1.bindings.bedrock.build_converse_request` is pure -- and it is provable
*only* without one, because a test that called Bedrock would be the first comparative attempt.

Everything here runs beneath ``scripts/tests/conftest.py``, which raises on any connection that
is not loopback. No AWS endpoint is reached, no credential is resolved, and the spend
authorisation is untouched.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from scripts.sur1.adapters import ARGUMENTS, KICKOFF, BaselineArm, tool_specifications
from scripts.sur1.arms import AttemptRequest, ModelReply
from scripts.sur1.bindings import is_real
from scripts.sur1.bindings.bedrock import (
    BedrockConverseClient,
    ModelConfigurationError,
    ModelIdentity,
    build_converse_request,
    converse_messages,
    read_reply,
    tool_configuration,
)
from scripts.sur1.budget import AttemptBudget
from scripts.sur1.doubles import FakeClock, SyntheticWorld
from scripts.sur1.frozen import Contract
from scripts.sur1.manifest import AttemptIdentity

REGION = "eu-west-1"


class RecordingTransport:
    """A Converse transport that records the request and answers from a script.

    It is not a mock of the binding: the binding builds the whole request and this object is
    what a provider would be. What a test reads back is therefore the payload that would have
    gone over the wire.
    """

    def __init__(self, answers: list[Mapping[str, Any]]) -> None:
        self.answers = answers
        self.requests: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> Mapping[str, Any]:
        self.requests.append(dict(kwargs))
        if not self.answers:
            raise AssertionError("the transport was called more times than the test scripted")
        return self.answers.pop(0)


def identity() -> ModelIdentity:
    return ModelIdentity.frozen(Contract.load(), region=REGION)


def request_for(**overrides: Any) -> AttemptRequest:
    contract = Contract.load()
    scenario = contract.scenario(contract.scenario_ids[0])
    return AttemptRequest(
        identity=AttemptIdentity(
            run_id="unit", arm_token="tok-unit", scenario_id=str(scenario["id"]), attempt=1
        ),
        scenario={key: value for key, value in scenario.items() if key != "ground_truth"},
        contract=contract,
        budget=AttemptBudget(ceilings=contract.ceilings, clock=FakeClock()),
        world=overrides.get("world", SyntheticWorld()),
    )


def test_the_model_identity_is_read_from_the_frozen_contract_and_never_restated() -> None:
    contract = Contract.load()
    read = identity()

    assert read.model_id == contract.model_configuration.model_id
    assert read.temperature == contract.model_configuration.temperature
    assert read.api == contract.model_configuration.api
    assert read.max_output_tokens == contract.ceilings.output_tokens
    assert read.region == REGION


def test_a_contract_configuring_another_provider_refuses_this_binding() -> None:
    contract = Contract.load()
    elsewhere = Contract(
        identity=contract.identity,
        document={
            **contract.document,
            "model_configuration": {
                **contract.document["model_configuration"],
                "provider": "openai",
            },
        },
    )

    with pytest.raises(ModelConfigurationError):
        ModelIdentity.frozen(elsewhere, region=REGION)


def test_the_request_carries_the_frozen_model_temperature_and_output_ceiling() -> None:
    contract = Contract.load()
    request = build_converse_request(
        identity=identity(),
        system="the frozen prompt",
        messages=[{"role": "user", "content": KICKOFF}],
        tools=tool_specifications(request_for()),
    )

    assert request["modelId"] == contract.model_configuration.model_id
    assert request["inferenceConfig"] == {
        "temperature": contract.model_configuration.temperature,
        "maxTokens": contract.ceilings.output_tokens,
    }
    assert request["system"] == [{"text": "the frozen prompt"}]
    assert request["messages"] == [{"role": "user", "content": [{"text": KICKOFF}]}]


def test_the_tool_config_publishes_the_eleven_frozen_actions_and_forces_none_of_them() -> None:
    contract = Contract.load()
    configured = tool_configuration(tool_specifications(request_for()))
    published = [tool["toolSpec"]["name"] for tool in configured["tools"]]

    assert published == [*contract.read_tools, *contract.write_tools]
    assert len(published) == 11
    assert "toolChoice" not in configured


def test_every_argument_of_a_frozen_action_is_required_and_typed() -> None:
    configured = tool_configuration(tool_specifications(request_for()))
    by_name = {tool["toolSpec"]["name"]: tool["toolSpec"] for tool in configured["tools"]}

    amend = by_name["amend_order"]["inputSchema"]["json"]
    assert amend["required"] == sorted(ARGUMENTS["amend_order"])
    assert amend["properties"]["expected_version"] == {"type": "integer"}
    assert amend["properties"]["external_id"] == {"type": "string"}
    assert by_name["report_outcome"]["inputSchema"]["json"]["properties"]["report"] == {
        "type": "object"
    }


def test_an_argument_shape_that_names_no_json_type_is_refused_rather_than_defaulted() -> None:
    with pytest.raises(ModelConfigurationError):
        tool_configuration([{"name": "invented", "arguments": {"thing": "a vibe"}}])


def test_a_tool_result_is_paired_to_the_call_it_answers() -> None:
    turns = converse_messages(
        [
            {"role": "user", "content": KICKOFF},
            {
                "role": "assistant",
                "content": "looking",
                "tools": [
                    {"id": "u1", "name": "get_orders", "arguments": {}},
                    {"id": "u2", "name": "get_stock", "arguments": {}},
                ],
            },
            {"role": "tool", "name": "get_orders", "content": {"orders": []}},
            {"role": "tool", "name": "get_stock", "content": {"on_hand": {}}},
        ]
    )

    assert [turn["role"] for turn in turns] == ["user", "assistant", "user"]
    results = turns[2]["content"]
    assert [block["toolResult"]["toolUseId"] for block in results] == ["u1", "u2"]
    assert results[0]["toolResult"]["content"] == [{"json": {"orders": []}}]


def test_two_calls_of_one_name_are_answered_in_the_order_they_were_made() -> None:
    turns = converse_messages(
        [
            {"role": "user", "content": KICKOFF},
            {
                "role": "assistant",
                "content": "",
                "tools": [
                    {"id": "first", "name": "amend_order", "arguments": {"external_id": "EXT-A"}},
                    {"id": "second", "name": "amend_order", "arguments": {"external_id": "EXT-B"}},
                ],
            },
            {"role": "tool", "name": "amend_order", "content": {"status_code": 200}},
            {"role": "tool", "name": "amend_order", "content": {"status_code": 409}},
        ]
    )

    assert [block["toolResult"]["toolUseId"] for block in turns[2]["content"]] == [
        "first",
        "second",
    ]


def test_a_reply_is_read_with_its_calls_its_tokens_and_no_optimism() -> None:
    reply = read_reply(
        {
            "output": {
                "message": {
                    "content": [
                        {"text": "reading the world"},
                        {
                            "toolUse": {
                                "toolUseId": "u9",
                                "name": "get_tasks",
                                "input": {"a": 1},
                            }
                        },
                    ]
                }
            },
            "usage": {"inputTokens": 120, "outputTokens": 34},
            "stopReason": "tool_use",
        }
    )

    assert reply.text == "reading the world"
    assert reply.tool_calls == ({"id": "u9", "name": "get_tasks", "arguments": {"a": 1}},)
    assert (reply.input_tokens, reply.output_tokens) == (120, 34)
    assert reply.stop_reason == "tool_use"


@pytest.mark.parametrize(
    "envelope",
    [{}, {"output": None}, {"output": {"message": None}}, {"output": {"message": {"content": 7}}}],
)
def test_a_malformed_envelope_reads_as_an_empty_answer_rather_than_raising(
    envelope: Mapping[str, Any],
) -> None:
    reply = read_reply(envelope)

    assert reply.text == ""
    assert reply.tool_calls == ()
    assert (reply.input_tokens, reply.output_tokens) == (0, 0)


def test_the_client_sends_exactly_the_built_request_and_opens_nothing_until_it_does() -> None:
    transport = RecordingTransport(
        [{"output": {"message": {"content": [{"text": "hello"}]}}, "usage": {}}]
    )
    opened: list[int] = []

    def open_transport() -> RecordingTransport:
        opened.append(1)
        return transport

    client = BedrockConverseClient(identity_=identity(), open_transport=open_transport)
    assert opened == [], "a client that opened a transport at construction resolves credentials"

    tools = tool_specifications(request_for())
    reply = client.converse(
        system="system", messages=[{"role": "user", "content": "x"}], tools=tools
    )

    assert opened == [1]
    assert reply.text == "hello"
    assert transport.requests[0] == build_converse_request(
        identity=identity(),
        system="system",
        messages=[{"role": "user", "content": "x"}],
        tools=tools,
    )


def test_the_client_declares_itself_a_real_binding_and_the_doubles_do_not() -> None:
    from scripts.sur1.doubles import ScriptedModel

    client = BedrockConverseClient(
        identity_=identity(), open_transport=lambda: RecordingTransport([])
    )

    assert is_real(client)
    assert not is_real(ScriptedModel(replies=[]))


def test_the_baseline_arm_drives_this_binding_with_the_frozen_prompt_as_the_bytes_on_disk() -> None:
    """One end-to-end pass through the arm, the binding and a scripted provider.

    The scenario here is the first of the frozen nine only because the arm reads a scenario's
    identity; the world is synthetic, no receiver is touched, nothing is captured and no verdict
    is produced. It buys nothing and consumes nothing.
    """
    transport = RecordingTransport(
        [
            {
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "u1",
                                    "name": "report_outcome",
                                    "input": {"report": {}},
                                }
                            }
                        ]
                    }
                },
                "usage": {"inputTokens": 10, "outputTokens": 2},
            }
        ]
    )
    client = BedrockConverseClient(identity_=identity(), open_transport=lambda: transport)
    request = request_for()

    BaselineArm(model=client).run(request)

    sent = transport.requests[0]
    assert sent["system"] == [{"text": request.contract.baseline_prompt()}]
    assert request.budget.spend.model_calls == 1
    assert request.budget.spend.input_tokens == 10


def sent_tool_names(request: Mapping[str, Any]) -> Sequence[str]:
    return [tool["toolSpec"]["name"] for tool in request["toolConfig"]["tools"]]


def test_a_scripted_reply_cannot_be_mistaken_for_a_provider() -> None:
    from scripts.sur1.doubles import ScriptedModel, ScriptExhaustedError

    model = ScriptedModel(replies=[ModelReply(text="one")])
    model.converse(system="s", messages=[], tools=[])

    with pytest.raises(ScriptExhaustedError):
        model.converse(system="s", messages=[], tools=[])
