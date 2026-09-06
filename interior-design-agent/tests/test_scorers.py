"""Zero-cost tests for the deterministic eval scorers (no API calls).

Exercises eval/scorers.py against hand-built AgentResult objects instead of
real agent runs — this is what lets the scoring logic itself be verified
without spending API credits. Only judge_case() (the LLM-as-judge) needs a
real call, and it's intentionally not covered here.
"""
from src.agent import AgentResult
from src.tools import budget_calculator, layout_fit_check
from eval.scorers import run_deterministic_scorers
from eval.golden_set import load_golden_set

CASES = {c["id"]: c for c in load_golden_set()}


def make_result(status, item_ids, budget_inr=None, room=None, transcript=None):
    budget_summary = None
    if item_ids and budget_inr:
        budget_summary = budget_calculator(item_ids, budget_inr)
    elif item_ids == [] and budget_inr is not None:
        budget_summary = budget_calculator([], budget_inr)

    fit_summary = layout_fit_check(item_ids, room[0], room[1], room[2]) if item_ids and room else None

    return AgentResult(
        status=status, item_ids=item_ids, rationale="r", trade_offs="t", message_to_customer="m",
        items=budget_summary["items"] if budget_summary else [],
        budget_summary=budget_summary, fit_summary=fit_summary,
        transcript=transcript or [], iterations_used=1,
    )


def scores_by_name(case_id, result):
    return {s["name"]: s["passed"] for s in run_deterministic_scorers(CASES[case_id], result)}


def test_valid_ok_plan_passes_all_universal_checks():
    t = [
        {"tool": "catalog_search", "input": {}, "result": {"count": 1, "items": []}},
        {"tool": "budget_calculator", "input": {}, "result": {"over_budget": False}},
        {"tool": "layout_fit_check", "input": {}, "result": {"fits": True}},
        {"tool": "submit_plan", "input": {"status": "ok"}},
    ]
    result = make_result("ok", ["SOF-001", "CFT-001", "TVU-003", "RUG-001"], 250000, (480, 360, 300), t)
    s = scores_by_name("TC-01", result)
    assert all(s[k] for k in ("catalog_validity", "price_validity", "budget_validity", "layout_validity", "status_correctness", "tool_use"))


def test_broken_plan_fails_the_right_checks():
    """An out-of-stock item, over budget, with the required tools never called."""
    t = [{"tool": "catalog_search", "input": {}, "result": {"count": 1, "items": []}}]
    result = make_result("ok", ["SOF-006"], 260000, (460, 360, 300), t)
    s = scores_by_name("TC-08", result)
    assert s["no_out_of_stock"] is False
    assert s["budget_validity"] is False
    assert s["tool_use"] is False
    assert s["must_not_include_item_id"] is False


def test_exact_categories_rejects_unrequested_extra_item():
    t = [
        {"tool": "catalog_search", "input": {}, "result": {"count": 1, "items": []}},
        {"tool": "budget_calculator", "input": {}, "result": {"over_budget": False}},
        {"tool": "layout_fit_check", "input": {}, "result": {"fits": True}},
    ]
    ok_result = make_result("ok", ["SOF-008", "CFT-001", "RUG-002"], 70000, (480, 360, 300), t)
    assert scores_by_name("TC-11", ok_result)["exact_categories"] is True

    with_extra = make_result("ok", ["SOF-008", "CFT-001", "RUG-002", "ACH-002"], 87000, (480, 360, 300), t)
    assert scores_by_name("TC-11", with_extra)["exact_categories"] is False


def test_replanning_scorer_detects_a_failing_call_before_success():
    with_replan = [
        {"tool": "budget_calculator", "input": {}, "result": {"over_budget": True}},
        {"tool": "budget_calculator", "input": {}, "result": {"over_budget": False}},
    ]
    result = make_result("ok", ["SOF-002", "CFT-003", "TVU-001", "RUG-002"], 120000, (480, 360, 300), with_replan)
    assert scores_by_name("TC-10", result)["replanning"] is True

    no_replan = [{"tool": "budget_calculator", "input": {}, "result": {"over_budget": False}}]
    result2 = make_result("ok", ["SOF-002", "CFT-003", "TVU-001", "RUG-002"], 120000, (480, 360, 300), no_replan)
    assert scores_by_name("TC-10", result2)["replanning"] is False


def test_max_price_in_category_selection_quality_check():
    result_cheap = make_result("ok", ["SOF-007"], 100000, (480, 360, 300), [])
    assert scores_by_name("TC-25", result_cheap)["max_price_in_category"] is True

    result_pricier = make_result("ok", ["SOF-001"], 100000, (480, 360, 300), [])
    assert scores_by_name("TC-25", result_pricier)["max_price_in_category"] is False


def test_non_ok_status_must_have_no_items():
    result = make_result("infeasible_budget", [], 20000, None, [])
    assert scores_by_name("TC-04", result)["non_ok_has_no_items"] is True

    bad_result = AgentResult(
        status="infeasible_budget", item_ids=["SOF-001"], rationale="", trade_offs="",
        message_to_customer="", items=[], budget_summary=None, fit_summary=None, transcript=[], iterations_used=1,
    )
    assert scores_by_name("TC-04", bad_result)["non_ok_has_no_items"] is False


if __name__ == "__main__":
    import sys
    from tests._runner import run_module
    ok = run_module(sys.modules[__name__])
    sys.exit(0 if ok else 1)
