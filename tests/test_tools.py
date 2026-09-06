"""Zero-cost tests for the three catalog tools — pure SQLite, no API calls.
Includes regression tests for two real bugs found during evaluation:
category-matching (TC-15) and the rug/wall-item clearance heuristic (TC-03).
"""
from src.tools import catalog_search, budget_calculator, layout_fit_check


def test_catalog_search_excludes_null_price_when_price_filtered():
    r = catalog_search(category="Coffee Table", max_price=100000)
    ids = [i["item_id"] for i in r["items"]]
    assert "CFT-004" not in ids, "null-price item must be excluded when a price filter is given"


def test_catalog_search_flags_null_price_when_unfiltered():
    r = catalog_search(category="Coffee Table")
    cft004 = next(i for i in r["items"] if i["item_id"] == "CFT-004")
    assert cft004["price_confirmed"] is False


def test_catalog_search_category_matching_is_forgiving():
    """Regression test for the TC-15 bug: the model said 'Console Table',
    the catalog category is 'Console' — must match either direction."""
    r = catalog_search(category="Console Table")
    ids = [i["item_id"] for i in r["items"]]
    assert "CON-001" in ids

    r2 = catalog_search(category="console")
    assert {"CON-001", "CON-002"} <= {i["item_id"] for i in r2["items"]}


def test_catalog_search_exact_category_does_not_bleed():
    r = catalog_search(category="Sofa")
    assert all(i["category"] == "Sofa" for i in r["items"])
    assert len(r["items"]) == 8


def test_budget_calculator_within_budget():
    r = budget_calculator(["SOF-001", "CFT-001"], 250000)
    assert r["total_spent_inr"] == 74000
    assert r["over_budget"] is False
    assert r["remaining_inr"] == 176000


def test_budget_calculator_over_budget():
    r = budget_calculator(["SOF-006"], 20000)
    assert r["over_budget"] is True


def test_budget_calculator_flags_unknown_item_id():
    """Hallucination guardrail: an item_id that isn't in the catalog must be surfaced, never silently priced."""
    r = budget_calculator(["SOF-001", "FAKE-999"], 250000)
    assert r["unknown_item_ids"] == ["FAKE-999"]
    assert r["total_spent_inr"] == 58000  # only the real item counted


def test_budget_calculator_flags_unpriced_item_and_excludes_from_total():
    r = budget_calculator(["CFT-004"], 50000)
    assert len(r["unpriced_items"]) == 1
    assert r["total_spent_inr"] == 0


def test_layout_fit_check_passes_for_sensible_plan():
    r = layout_fit_check(["SOF-001", "CFT-001", "TVU-003"], 480, 360, 300)
    assert r["fits"] is True
    assert r["oversized_items"] == []


def test_layout_fit_check_flags_oversized_sofa():
    r = layout_fit_check(["SOF-004"], 220, 180, 260)  # TC-14 scenario
    assert r["fits"] is False
    assert "SOF-004" in r["oversized_items"]


def test_layout_fit_check_rug_alone_is_never_oversized():
    """Regression test for the TC-03 bug: a rug lying flat on the floor
    doesn't need walk-around clearance the way furniture does."""
    r = layout_fit_check(["RUG-004"], 300, 240, 280)
    assert r["fits"] is True
    assert r["oversized_items"] == []


def test_layout_fit_check_coverage_threshold():
    r = layout_fit_check(
        ["SOF-004", "ART-001", "LMP-001", "TBL-001", "CFT-003", "RUG-002", "SDT-002"],
        280, 230, 270,
    )
    assert r["coverage_ratio"] is not None
    assert r["max_coverage_allowed"] == 0.55


if __name__ == "__main__":
    import sys
    from tests._runner import run_module
    ok = run_module(sys.modules[__name__])
    sys.exit(0 if ok else 1)
