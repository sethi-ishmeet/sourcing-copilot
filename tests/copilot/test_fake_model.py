"""The fake model is a test double, but it still has to be predictable."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from sourcing_copilot.copilot.fake_model import FakeChatModel
from sourcing_copilot.copilot.prompts import screen_request
from sourcing_copilot.copilot.tools import make_lookup_tools, submit_scorecard_tool
from tests.conftest import TODAY


def test_fake_model_calls_tools_in_order_then_submits(sample_data):
    role = sample_data.role("role_backend_sr")
    lookup = make_lookup_tools(sample_data, TODAY, "cand_001", [])
    model = FakeChatModel(data=sample_data).bind_tools([*lookup.values(), submit_scorecard_tool])
    messages = [SystemMessage("x"), HumanMessage(screen_request(role, "cand_001"))]

    reply = model.invoke(messages)
    assert reply.tool_calls[0]["name"] == "get_profile"
    messages += [
        reply,
        ToolMessage(
            lookup["get_profile"].invoke(reply.tool_calls[0]["args"]),
            tool_call_id=reply.tool_calls[0]["id"],
            name="get_profile",
        ),
    ]

    reply = model.invoke(messages)
    assert reply.tool_calls[0]["name"] == "check_do_not_contact"
    messages += [
        reply,
        ToolMessage(
            lookup["check_do_not_contact"].invoke(reply.tool_calls[0]["args"]),
            tool_call_id=reply.tool_calls[0]["id"],
            name="check_do_not_contact",
        ),
    ]

    reply = model.invoke(messages)
    call = reply.tool_calls[0]
    assert call["name"] == "submit_scorecard"
    assert [s["requirement_id"] for s in call["args"]["scores"]] == [
        "python_backend",
        "cloud",
        "postgres",
        "regulated",
    ]
    assert call["args"]["recommend"] is True
    assert reply.usage_metadata["input_tokens"] > 0


def test_fake_model_reports_token_usage(sample_data):
    model = FakeChatModel(data=sample_data).bind_tools([submit_scorecard_tool])
    reply = model.invoke([HumanMessage("Role id: role_backend_sr\nCandidate id: cand_001")])
    assert reply.usage_metadata["total_tokens"] >= 1
