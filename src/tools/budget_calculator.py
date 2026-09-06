"""Tool: budget_calculator.

Sums the real catalog price of the agent's selected items, compares to the
customer's budget, and reports what's left. Also surfaces two failure modes
the agent must not paper over: items it picked that have no confirmed price,
and item_ids that don't actually exist in the catalog (a hallucination
guardrail — this should never be non-empty in a correct run).
"""
from typing import List


from .. import db


def budget_calculator(item_ids: List[str], budget_inr: int) -> dict:
    if not item_ids:
        return {
            "items": [],
            "total_spent_inr": 0,
            "budget_inr": budget_inr,
            "remaining_inr": budget_inr,
            "over_budget": False,
            "unpriced_items": [],
            "unknown_item_ids": [],
        }

    placeholders = ",".join("?" for _ in item_ids)
    with db.get_connection() as conn:
        rows = conn.execute(
            f"SELECT item_id, category, name, price_inr FROM catalog "
            f"WHERE item_id IN ({placeholders})",
            item_ids,
        ).fetchall()

    found = {row["item_id"]: dict(row) for row in rows}
    unknown_item_ids = [i for i in item_ids if i not in found]

    priced = [found[i] for i in item_ids if i in found and found[i]["price_inr"] is not None]
    unpriced = [found[i] for i in item_ids if i in found and found[i]["price_inr"] is None]

    total_spent = sum(item["price_inr"] for item in priced)
    remaining = budget_inr - total_spent

    return {
        "items": priced,
        "total_spent_inr": total_spent,
        "budget_inr": budget_inr,
        "remaining_inr": remaining,
        "over_budget": total_spent > budget_inr,
        "unpriced_items": unpriced,
        "unknown_item_ids": unknown_item_ids,
    }
