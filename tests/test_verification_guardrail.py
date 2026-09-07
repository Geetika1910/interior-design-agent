"""Zero-cost tests for the "never trust a self-reported ok" guardrail in
src/agent.py. Only the OpenAI client is mocked — budget_calculator and
layout_fit_check run for real against the actual catalog, so these tests
exercise genuine over-budget/doesn't-fit detection, not simulated results.

Covers a real, observed failure: the model checked layout on a smaller
subset of items, then added more afterward believing (wrongly) they were
"free," and submitted status="ok" without re-checking the full set. Our
independent recompute caught it (coverage_ratio=1.36 in the real eval run).
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


def _run_with_submitted_items(item_ids, brief=None):
    tool_call = _make_tool_call("call_1", "submit_plan", {
        "item_ids": item_ids, "status": "ok",
        "rationale": "r", "trade_offs": "t",
        "message_to_customer": "Here's your plan, all set!",
    })
    response = _make_response([tool_call])
    with patch("src.agent.OpenAI") as MockOpenAI:
        client = MagicMock()
        client.chat.completions.create.return_value = response
        MockOpenAI.return_value = client
        return run_agent(brief or BRIEF)


def test_self_reported_ok_overridden_when_actually_over_budget():
    # SOF-001 (Nordby sofa) is real-price 58,000 — over a 50,000 budget.
    result = _run_with_submitted_items(
        ["SOF-001"], brief=dict(BRIEF, budget_inr=50000)
    )
    assert result.status == "verification_failed"
    assert result.item_ids == []
    assert "didn't actually pass" in result.message_to_customer


def test_self_reported_ok_overridden_when_actually_oversized():
    # SOF-004 (Marrakech sectional, 300x170) cannot fit a 220x180 room.
    tiny_room = dict(BRIEF, length_cm=220, width_cm=180, ceiling_cm=260, budget_inr=300000)
    result = _run_with_submitted_items(["SOF-004"], brief=tiny_room)
    assert result.status == "verification_failed"
    assert result.item_ids == []


def test_genuinely_valid_ok_plan_is_not_overridden():
    # SOF-001 + CFT-001 comfortably fit a spacious room and budget.
    result = _run_with_submitted_items(["SOF-001", "CFT-001"])
    assert result.status == "ok"
    assert result.item_ids == ["SOF-001", "CFT-001"]
    assert result.message_to_customer == "Here's your plan, all set!"


def test_duplicate_item_ids_are_deduped():
    result = _run_with_submitted_items(["SOF-001", "SOF-001", "CFT-001"])
    assert result.item_ids == ["SOF-001", "CFT-001"]  # order preserved, no duplicate
    assert result.status == "ok"
    assert result.budget_summary["total_spent_inr"] == 58000 + 16000  # not double-counted


if __name__ == "__main__":
    import sys
    from tests._runner import run_module
    ok = run_module(sys.modules[__name__])
    sys.exit(0 if ok else 1)
