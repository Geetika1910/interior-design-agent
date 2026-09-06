"""Deterministic scorers + the LLM-as-judge scorer.

Every deterministic scorer here checks a PROPERTY of the agent's structured
result — recomputed against the real catalog — never a specific expected
item_id, unless a case explicitly requires avoiding/including one real item
(e.g. "must not recommend the out-of-stock item"). This keeps the eval valid
even though multiple different item combinations could legitimately satisfy
the same brief.

Every scorer returns (passed: bool, detail: str).
"""
import json

from openai import OpenAI

from src import config, db
from eval.judge_rubric import JUDGE_RUBRIC, JUDGE_SYSTEM_PROMPT, JUDGE_TOOL

TOOL_REQUIREMENTS = {
    "ok": {"catalog_search", "budget_calculator", "layout_fit_check"},
    "infeasible_budget": {"budget_calculator"},
    "infeasible_layout": {"layout_fit_check", "catalog_search"},
    "unavailable_items": {"catalog_search"},
    "contingent_catalog_search": {"catalog_search"},
    "out_of_scope": set(),
}


def _tools_called(transcript: list) -> set:
    return {entry["tool"] for entry in transcript if entry["tool"] not in ("submit_plan", "_nudge")}


def _get_categories(item_ids: list) -> dict:
    """item_id -> {category, name, in_stock, price_inr}, straight from the DB (not the agent's claims)."""
    if not item_ids:
        return {}
    placeholders = ",".join("?" for _ in item_ids)
    with db.get_connection() as conn:
        rows = conn.execute(
            f"SELECT item_id, category, name, in_stock, price_inr FROM catalog WHERE item_id IN ({placeholders})",
            item_ids,
        ).fetchall()
    return {row["item_id"]: dict(row) for row in rows}


# ---- Universal checks (applied to every agent-invoking case) ----

def check_catalog_validity(result) -> tuple:
    if not result.item_ids:
        return True, "no items submitted"
    unknown = result.budget_summary["unknown_item_ids"] if result.budget_summary else result.item_ids
    return (not unknown), f"unknown_item_ids={unknown}"


def check_price_validity(result) -> tuple:
    if not result.item_ids:
        return True, "no items submitted"
    unpriced = [i["item_id"] for i in result.budget_summary["unpriced_items"]] if result.budget_summary else []
    return (not unpriced), f"unpriced_items={unpriced}"


def check_budget_validity(result) -> tuple:
    if result.status != "ok":
        return True, "not applicable (status != ok)"
    if not result.budget_summary:
        return False, "status=ok but no budget_summary computed"
    ok = not result.budget_summary["over_budget"]
    return ok, f"total={result.budget_summary['total_spent_inr']} budget={result.budget_summary['budget_inr']}"


def check_layout_validity(result) -> tuple:
    if result.status != "ok":
        return True, "not applicable (status != ok)"
    if not result.fit_summary:
        return False, "status=ok but no fit_summary computed"
    return result.fit_summary["fits"], f"coverage_ratio={result.fit_summary.get('coverage_ratio')}"


def check_status_correctness(case, result) -> tuple:
    expected = case["expected_status"]
    if isinstance(expected, str):
        expected = [expected]
    return (result.status in expected), f"expected one of {expected}, got '{result.status}'"


def check_no_out_of_stock(result) -> tuple:
    if result.status != "ok" or not result.item_ids:
        return True, "not applicable"
    cats = _get_categories(result.item_ids)
    out_of_stock = [i for i in result.item_ids if cats.get(i, {}).get("in_stock") == 0]
    return (not out_of_stock), f"out_of_stock_in_final_plan={out_of_stock}"


def check_non_ok_has_no_items(result) -> tuple:
    if result.status == "ok":
        return True, "not applicable"
    return (not result.item_ids), f"expected no items for status={result.status}, got {result.item_ids}"


def check_tool_use(case, result) -> tuple:
    mode = case["checks"].get("tool_use")
    if mode is None:
        return True, "no tool_use requirement configured"
    required = TOOL_REQUIREMENTS[mode]
    used = _tools_called(result.transcript)
    missing = required - used
    return (not missing), f"required={sorted(required)} used={sorted(used)} missing={sorted(missing)}"


# ---- Case-specific checks (opt-in via case['checks']) ----

def check_forbidden_categories(case, result) -> tuple:
    forbidden = case["checks"].get("forbidden_categories")
    if not forbidden:
        return True, "not configured"
    cats = _get_categories(result.item_ids)
    hits = [i for i in result.item_ids if cats.get(i, {}).get("category") in forbidden]
    return (not hits), f"forbidden_categories={forbidden} hits={hits}"


def check_forbidden_name_keywords(case, result) -> tuple:
    keywords = case["checks"].get("forbidden_name_keywords")
    if not keywords:
        return True, "not configured"
    cats = _get_categories(result.item_ids)
    hits = [
        i for i in result.item_ids
        if any(k.lower() in cats.get(i, {}).get("name", "").lower() for k in keywords)
    ]
    return (not hits), f"forbidden_keywords={keywords} hits={hits}"


def check_exact_categories(case, result) -> tuple:
    if not case["checks"].get("exact_categories"):
        return True, "not configured"
    if result.status != "ok":
        return True, "not applicable (status != ok)"
    requested = {c.strip() for c in case["brief"]["must_haves"].split(",")}
    cats = _get_categories(result.item_ids)
    actual = {cats[i]["category"] for i in result.item_ids if i in cats}
    return (actual == requested), f"requested={requested} actual={actual}"


def check_must_have_categories_present(case, result) -> tuple:
    required = case["checks"].get("must_have_categories_present")
    if not required:
        return True, "not configured"
    if result.status != "ok":
        return True, "not applicable (status != ok)"
    cats = _get_categories(result.item_ids)
    actual = {cats[i]["category"] for i in result.item_ids if i in cats}
    missing = set(required) - actual
    return (not missing), f"required={required} actual={sorted(actual)} missing={sorted(missing)}"


def check_min_category_counts(case, result) -> tuple:
    requirements = case["checks"].get("min_category_counts")
    if not requirements:
        return True, "not configured"
    if result.status != "ok":
        return True, "not applicable (status != ok)"
    cats = _get_categories(result.item_ids)
    counts = {}
    for i in result.item_ids:
        c = cats.get(i, {}).get("category")
        counts[c] = counts.get(c, 0) + 1
    shortfalls = {cat: (n, counts.get(cat, 0)) for cat, n in requirements.items() if counts.get(cat, 0) < n}
    return (not shortfalls), f"requirements={requirements} actual_counts={counts} shortfalls={shortfalls}"


def check_must_not_include_item_id(case, result) -> tuple:
    forbidden_id = case["checks"].get("must_not_include_item_id")
    if not forbidden_id:
        return True, "not configured"
    return (forbidden_id not in result.item_ids), f"forbidden_id={forbidden_id} item_ids={result.item_ids}"


def check_max_price_in_category(case, result) -> tuple:
    """Selection-quality guardrail (TC-25): when two same-category items are otherwise
    comparable (style, stock, dimensions) and no premium/value preference is stated,
    the agent shouldn't gratuitously pick the pricier one. Checks a price ceiling, not
    a specific expected item_id — any item at or below the ceiling passes."""
    config = case["checks"].get("max_price_in_category")
    if not config:
        return True, "not configured"
    if result.status != "ok":
        return True, "not applicable (status != ok)"

    cats = _get_categories(result.item_ids)
    matches = [i for i in result.item_ids if cats.get(i, {}).get("category") == config["category"]]
    if not matches:
        return True, f"no items in category {config['category']} (not applicable)"

    violations = [i for i in matches if (cats[i]["price_inr"] or 0) > config["max_price"]]
    prices = {i: cats[i]["price_inr"] for i in matches}
    return (not violations), f"max_allowed={config['max_price']} prices={prices} violations={violations}"


def check_replanning(case, result) -> tuple:
    if not case["checks"].get("replanning_required"):
        return True, "not configured"
    for entry in result.transcript:
        if entry["tool"] == "budget_calculator" and entry["result"].get("over_budget"):
            return True, "observed an over-budget budget_calculator call before submit_plan"
        if entry["tool"] == "layout_fit_check" and not entry["result"].get("fits", True):
            return True, "observed a failing layout_fit_check call before submit_plan"
    return False, "no failing tool result found in transcript — agent may have succeeded on the first attempt"


DETERMINISTIC_SCORERS = [
    ("catalog_validity", lambda case, result: check_catalog_validity(result)),
    ("price_validity", lambda case, result: check_price_validity(result)),
    ("budget_validity", lambda case, result: check_budget_validity(result)),
    ("layout_validity", lambda case, result: check_layout_validity(result)),
    ("status_correctness", check_status_correctness),
    ("no_out_of_stock", lambda case, result: check_no_out_of_stock(result)),
    ("non_ok_has_no_items", lambda case, result: check_non_ok_has_no_items(result)),
    ("tool_use", check_tool_use),
    ("forbidden_categories", check_forbidden_categories),
    ("forbidden_name_keywords", check_forbidden_name_keywords),
    ("exact_categories", check_exact_categories),
    ("must_have_categories_present", check_must_have_categories_present),
    ("min_category_counts", check_min_category_counts),
    ("must_not_include_item_id", check_must_not_include_item_id),
    ("max_price_in_category", check_max_price_in_category),
    ("replanning", check_replanning),
]


def run_deterministic_scorers(case: dict, result) -> list:
    scored = []
    for name, fn in DETERMINISTIC_SCORERS:
        passed, detail = fn(case, result)
        scored.append({"name": name, "passed": passed, "detail": detail})
    return scored


# ---- LLM-as-judge ----

def judge_case(case: dict, result) -> dict:
    cats = _get_categories(result.item_ids)
    with db.get_connection() as conn:
        placeholders = ",".join("?" for _ in result.item_ids) if result.item_ids else None
        items_detail = []
        if placeholders:
            rows = conn.execute(
                f"SELECT item_id, name, category, style_tags, price_inr, color_finish "
                f"FROM catalog WHERE item_id IN ({placeholders})",
                result.item_ids,
            ).fetchall()
            items_detail = [dict(r) for r in rows]

    payload = {
        "brief": {
            "room_dimensions_cm": {
                "length": case["brief"]["length_cm"],
                "width": case["brief"]["width_cm"],
                "ceiling": case["brief"]["ceiling_cm"],
            },
            "budget_inr": case["brief"]["budget_inr"],
            "style_preference": case["brief"].get("style_preference"),
            "must_haves": case["brief"].get("must_haves"),
            "constraints": case["brief"].get("constraints"),
            "customer_note": case["brief"].get("customer_note"),
        },
        "agent_result": {
            "status": result.status,
            "selected_items": items_detail,
            "rationale": result.rationale,
            "trade_offs": result.trade_offs,
            "message_to_customer": result.message_to_customer,
        },
    }

    client = OpenAI(api_key=config.AI_GATEWAY_API_KEY, base_url=config.AI_GATEWAY_BASE_URL)
    response = client.chat.completions.create(
        model=config.JUDGE_MODEL,
        max_tokens=1024,
        tools=[JUDGE_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_scores"}},
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT + "\n\n" + JUDGE_RUBRIC},
            {"role": "user", "content": json.dumps(payload, indent=2)},
        ],
    )

    message = response.choices[0].message
    if message.tool_calls:
        return json.loads(message.tool_calls[0].function.arguments)

    return {"error": "judge did not return scores", "raw": message.model_dump()}
