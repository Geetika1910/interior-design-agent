"""Turns the agent's raw tool-call transcript into short, human-readable
lines for the Streamlit "agent activity" panel. No raw JSON here — that's
kept behind a debug expander in the UI instead.
"""


def summarize_transcript(transcript: list) -> list:
    lines = []
    for entry in transcript:
        tool = entry["tool"]

        if tool == "_nudge":
            continue

        if tool == "catalog_search":
            inp = entry["input"]
            result = entry["result"]
            filters = []
            if inp.get("category"):
                filters.append(inp["category"])
            if inp.get("style"):
                filters.append(f"{inp['style']} style")
            if inp.get("max_price"):
                filters.append(f"under ₹{inp['max_price']:,}")
            if inp.get("in_stock_only"):
                filters.append("in stock")
            desc = ", ".join(filters) if filters else "all items"
            lines.append(f"🔍 Searched catalog for {desc} — found {result['count']} option(s)")

        elif tool == "budget_calculator":
            r = entry["result"]
            note = "over budget, replanning" if r["over_budget"] else "within budget"
            lines.append(
                f"💰 Checked budget for {len(entry['input']['item_ids'])} item(s) — "
                f"₹{r['total_spent_inr']:,} of ₹{r['budget_inr']:,} ({note})"
            )

        elif tool == "layout_fit_check":
            r = entry["result"]
            n = len(entry["input"]["item_ids"])
            if r["fits"]:
                lines.append(f"📐 Checked room fit for {n} item(s) — fits comfortably")
            else:
                reason = r["warnings"][0] if r["warnings"] else "doesn't fit"
                lines.append(f"📐 Checked room fit for {n} item(s) — doesn't fit, replanning ({reason})")

        elif tool == "submit_plan":
            status = entry["input"].get("status", "unknown")
            if status == "ok":
                lines.append("✅ Finalized the design plan")
            else:
                lines.append(f"⚠️ Could not finalize a standard plan — status: {status}")

    return lines


STATUS_LABELS = {
    "ok": "Design plan ready",
    "infeasible_budget": "⚠️ Budget too low for this brief",
    "infeasible_layout": "⚠️ Requested pieces don't fit the room",
    "out_of_scope": "🚫 Outside furniture/design scope",
    "unavailable_items": "🚫 Requested items aren't in our catalog",
    "agent_error": "⚠️ The agent could not complete this request",
    "max_iterations_exceeded": "⚠️ The agent could not converge on a plan",
}
