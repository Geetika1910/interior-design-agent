"""Zero-cost tests for the malformed submit_plan fallback in src/agent.py.
Mocks the OpenAI client entirely — no real API calls.

Covers a real, observed failure: the model's submit_plan tool call can
occasionally omit or mis-set the required "status" field while still
producing a complete, well-reasoned rationale/trade_offs/message_to_customer.
Previously this silently fell back to "agent_error", discarding a
potentially-correct answer. It should now surface as its own distinct,
diagnosable status instead.
"""
import json
from unittest.mock import MagicMock, patch

from src.agent import run_agent

BRIEF = {
    "room_type": "Living Room", "length_cm": 480, "width_cm": 360, "ceiling_cm": 300,
    "budget_inr": 250000, "style_preference": "Scandinavian", "must_haves": "Sofa",
    "constraints": "none", "customer_note": "",
}


def _make_tool_call(call_id, name, arguments_dict):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments_dict)
    return tc


def _make_response(tool_calls):
    message = MagicMock()
    message.tool_calls = tool_calls
    message.content = None
    message.model_dump.return_value = {"role": "assistant", "content": None, "tool_calls": []}
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    response.usage.prompt_tokens = 100
    response.usage.completion_tokens = 50
    return response


def _run_with_mocked_submit(submit_args):
    tool_call = _make_tool_call("call_1", "submit_plan", submit_args)
    response = _make_response([tool_call])
    with patch("src.agent.OpenAI") as MockOpenAI:
        client = MagicMock()
        client.chat.completions.create.return_value = response
        MockOpenAI.return_value = client
        return run_agent(BRIEF)


def test_missing_status_field_becomes_malformed_submission():
    result = _run_with_mocked_submit({
        "item_ids": [], "rationale": "Real reasoning.", "trade_offs": "Real trade-offs.",
        "message_to_customer": "Real message.",
        # "status" deliberately omitted
    })
    assert result.status == "malformed_submission"
    assert result.rationale == "Real reasoning."  # content preserved, not discarded


def test_invalid_status_value_becomes_malformed_submission():
    result = _run_with_mocked_submit({
        "item_ids": [], "status": "not_a_real_status",
        "rationale": "r", "trade_offs": "t", "message_to_customer": "m",
    })
    assert result.status == "malformed_submission"


def test_valid_status_passes_through_unchanged():
    result = _run_with_mocked_submit({
        "item_ids": [], "status": "infeasible_budget",
        "rationale": "r", "trade_offs": "t", "message_to_customer": "m",
    })
    assert result.status == "infeasible_budget"


if __name__ == "__main__":
    import sys
    from tests._runner import run_module
    ok = run_module(sys.modules[__name__])
    sys.exit(0 if ok else 1)
