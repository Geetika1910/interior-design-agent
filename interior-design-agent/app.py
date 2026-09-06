"""Streamlit front end for the Interior Design Agent (Living Room MVP).

Thin by design: this file only collects a brief, calls the agent, and
renders what comes back. All the real logic (tools, agent loop, guardrails)
lives in src/. The agent's full tool-call transcript is still captured on
the result object (used by the eval harness in eval/) — this file simply
doesn't render it to the end user, who should see a design product, not an
AI debugging console.
"""
import streamlit as st

from src.agent import run_agent
from src.catalog_meta import (
    get_items_by_ids,
    get_living_room_categories,
    get_living_room_sample_briefs,
    get_living_room_styles,
)
from src.ui_text import STATUS_LABELS
from src.validation import validate_brief

st.set_page_config(page_title="Interior Design Agent", page_icon="🛋️")

st.title("🛋️ AI Interior Design Agent")
st.caption(
    "Living Room MVP — turns a room brief into a real, budget-fitting design plan "
    "using only products from the Interior Company catalog."
)


def render_brief_summary(brief: dict) -> None:
    st.write(
        f"**Room:** {brief['room_type']}, {brief['length_cm'] / 100:.1f}m x "
        f"{brief['width_cm'] / 100:.1f}m, {brief['ceiling_cm'] / 100:.1f}m ceiling"
    )
    st.write(f"**Budget:** ₹{brief['budget_inr']:,}")
    st.write(f"**Style:** {brief.get('style_preference', 'unspecified')}")
    st.write(f"**Must-haves:** {brief.get('must_haves', 'unspecified')}")
    st.write(f"**Constraints:** {brief.get('constraints', 'none stated')}")
    if brief.get("customer_note"):
        st.write(f"**Customer note:** {brief['customer_note']}")


def collect_brief_from_form() -> dict:
    styles = get_living_room_styles()
    categories = get_living_room_categories()
    sample_briefs = get_living_room_sample_briefs()

    mode = st.radio("Brief source", ["Custom brief", "Try a sample brief"], horizontal=True)

    if mode == "Custom brief":
        st.subheader("Room brief")
        st.caption("Room type: Living Room (this MVP is scoped to one room type)")

        col1, col2, col3 = st.columns(3)
        with col1:
            length_m = st.number_input("Length (m)", min_value=1.5, max_value=15.0, value=4.8, step=0.1)
        with col2:
            width_m = st.number_input("Width (m)", min_value=1.5, max_value=15.0, value=3.6, step=0.1)
        with col3:
            ceiling_m = st.number_input("Ceiling height (m)", min_value=2.2, max_value=5.0, value=3.0, step=0.1)

        budget_inr = st.number_input(
            "Budget (INR)", min_value=0, max_value=10_000_000, value=250_000, step=5_000
        )

        default_style_index = styles.index("Scandinavian") if "Scandinavian" in styles else 0
        style_preference = st.selectbox("Style preference", styles, index=default_style_index)

        default_musts = [c for c in ["Sofa", "Coffee Table", "TV Unit", "Rug"] if c in categories]
        must_haves = st.multiselect("Must-have items", categories, default=default_musts)

        additional_context = st.text_area(
            "Additional context (optional)",
            placeholder=(
                "e.g. South-facing, lots of natural light; rented flat, prefer freestanding "
                "furniture; couple, no kids yet; want it calm and bright."
            ),
        )

        return {
            "room_type": "Living Room",
            "length_cm": int(round(length_m * 100)),
            "width_cm": int(round(width_m * 100)),
            "ceiling_cm": int(round(ceiling_m * 100)),
            "budget_inr": int(budget_inr),
            "style_preference": style_preference,
            "must_haves": ", ".join(must_haves) if must_haves else "unspecified",
            "constraints": "none stated",
            "customer_note": additional_context or "",
        }

    labels = [
        f"{b['brief_id']} — {b['style_preference']}, "
        f"{b['length_cm'] / 100:.1f}x{b['width_cm'] / 100:.1f}m, ₹{b['budget_inr']:,}"
        for b in sample_briefs
    ]
    idx = st.selectbox("Pick a sample brief", range(len(labels)), format_func=lambda i: labels[i])
    brief = sample_briefs[idx]

    with st.expander("Full brief details"):
        render_brief_summary(brief)

    return brief


def render_item_card(item: dict) -> None:
    with st.container(border=True):
        st.markdown(f"**{item['name']}**")
        st.caption(item["category"])
        st.write(f"₹{item['price_inr']:,}")
        dims = [item.get(d) for d in ("width_cm", "depth_cm", "height_cm")]
        if all(d is not None for d in dims):
            st.write(f"{dims[0]} x {dims[1]} x {dims[2]} cm (W x D x H)")
        if item.get("color_finish"):
            st.caption(item["color_finish"])


def render_usage_debug(result) -> None:
    """Debug-only API usage/cost for this run — not shown to end customers,
    just to whoever is testing/measuring spend."""
    with st.expander("API usage (debug)"):
        cost = result.estimated_cost_usd
        cost_str = f"${cost:.4f}" if cost is not None else "unknown model — no rate on file"
        st.write(f"**Agent API calls:** {result.api_call_count}")
        st.write(f"**Input tokens:** {result.total_input_tokens:,}")
        st.write(f"**Output tokens:** {result.total_output_tokens:,}")
        st.write(f"**Total tokens:** {result.total_tokens:,}")
        st.write(f"**Estimated cost:** {cost_str}")


def render_dashboard(brief: dict, result) -> None:
    with st.expander("Your Room Brief"):
        render_brief_summary(brief)

    if result.status != "ok":
        st.warning(STATUS_LABELS.get(result.status, result.status))
        st.write(result.message_to_customer)
        if result.trade_offs:
            st.subheader("Trade-offs & Decisions")
            st.write(result.trade_offs)
        render_usage_debug(result)
        return

    st.success(STATUS_LABELS["ok"])
    b = result.budget_summary
    spend_pct = (b["total_spent_inr"] / b["budget_inr"] * 100) if b["budget_inr"] else 0

    # A. Design overview — a factual one-liner computed from real structured
    # data (not additional LLM prose), so it can't drift from the actual plan.
    st.subheader("Design Overview")
    st.write(
        f"A {brief.get('style_preference', '')} {brief.get('room_type', 'Living Room')} plan "
        f"with {len(result.item_ids)} piece(s), using {spend_pct:.0f}% of your "
        f"₹{b['budget_inr']:,} budget."
    )

    # B. Recommended items — text-based cards; the catalog has no image column.
    st.subheader("Recommended Items")
    items = get_items_by_ids(result.item_ids)
    cols = st.columns(2)
    for i, item in enumerate(items):
        with cols[i % 2]:
            render_item_card(item)

    # C. Design rationale
    st.subheader("Why This Works")
    st.write(result.rationale)

    # D. Trade-offs & decisions
    st.subheader("Trade-offs & Decisions")
    st.write(result.trade_offs)

    # E. Itemised BOQ
    st.subheader("Itemised Bill of Quantities")
    running_total = 0
    rows = []
    for item in result.items:
        running_total += item["price_inr"]
        rows.append(
            {
                "Item ID": item["item_id"],
                "Product": item["name"],
                "Category": item["category"],
                "Price (INR)": item["price_inr"],
                "Running total (INR)": running_total,
            }
        )
    st.table(rows)

    # F. Budget summary
    st.subheader("Budget Summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total spend", f"₹{b['total_spent_inr']:,}")
    c2.metric("Customer budget", f"₹{b['budget_inr']:,}")
    c3.metric("Remaining", f"₹{b['remaining_inr']:,}")

    # G. Room fit
    st.subheader("Room Fit")
    fit = result.fit_summary
    if fit and fit["fits"]:
        st.write(
            f"All selected items fit within the room footprint while maintaining circulation "
            f"space ({fit['coverage_ratio']:.0%} floor coverage, under the "
            f"{fit['max_coverage_allowed']:.0%} comfort threshold)."
        )
    else:
        st.warning("This plan does not pass the room fit check.")
        for w in (fit.get("warnings") if fit else []) or []:
            st.write(f"- {w}")

    render_usage_debug(result)


if "result" not in st.session_state:
    brief = collect_brief_from_form()
    st.divider()

    if st.button("Generate Design Plan", type="primary"):
        is_valid, validation_error = validate_brief(brief)
        if not is_valid:
            st.error(validation_error)
            st.stop()

        with st.spinner("Designing your room — searching the catalog, checking budget and fit..."):
            result = run_agent(brief)

        st.session_state.result = result
        st.session_state.submitted_brief = brief
        st.rerun()

else:
    if st.button("🔄 Start a new design"):
        del st.session_state["result"]
        del st.session_state["submitted_brief"]
        st.rerun()

    render_dashboard(st.session_state.submitted_brief, st.session_state.result)
