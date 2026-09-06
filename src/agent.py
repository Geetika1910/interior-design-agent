"""The design agent: a tool-use loop over the three catalog tools, called via
the Vercel AI Gateway (an OpenAI-Chat-Completions-compatible endpoint that
proxies to the configured model — see config.AGENT_MODEL).

Flow: interpret brief -> search catalog -> propose items -> check budget ->
check layout -> re-plan on failure -> call submit_plan with a final,
structured result. The loop never accepts a design from the model's own
text; every item it recommends must come back from a real catalog_search
result, and the final answer is only ever recorded via the submit_plan tool
call, not by parsing prose.
"""
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import OpenAI, RateLimitError
import time
from . import config
from .tools import catalog_search, budget_calculator, layout_fit_check

MAX_ITERATIONS = 4
MAX_TOKENS = 1500
EMPTY_TURN_RETRIES = 0

# USD per 1M tokens, (input, output). For cost estimation/debugging only —
# not billing-accurate. Anthropic entries kept for reference in case the
# model is ever pointed back at Claude via the gateway; unknown models
# simply get no cost estimate (returns None).
MODEL_PRICING = {
    "zai/glm-5.3-flash": (0.15, 0.50),
    "zai/glm-5.3": (0.70, 2.20),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-fable-5-1": (10.00, 50.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    rates = MODEL_PRICING.get(model)
    if rates is None:
        return None
    input_rate, output_rate = rates
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


# Tool schemas in OpenAI function-calling format (the wire format the Vercel
# AI Gateway's /v1/chat/completions endpoint expects, regardless of which
# underlying model actually serves the request).
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "catalog_search",
            "description": (
                "Search the real product catalog. This is the ONLY source of "
                "products — never propose an item that hasn't come back from "
                "this tool. Returns items with price_confirmed=false when the "
                "catalog has no price on file for that item."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Exact category, e.g. 'Sofa', 'Coffee Table', 'Rug'."},
                    "style": {"type": "string", "description": "Style tag substring, e.g. 'Scandinavian'."},
                    "room_type": {"type": "string", "description": "e.g. 'Living Room'."},
                    "max_price": {"type": "integer", "description": "Maximum price in INR."},
                    "min_price": {"type": "integer", "description": "Minimum price in INR."},
                    "in_stock_only": {"type": "boolean", "description": "If true, only return in-stock items."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "budget_calculator",
            "description": (
                "Sum the real catalog price of the given item_ids and compare to "
                "the budget. Reports items with no confirmed price separately "
                "(unpriced_items) and any item_id not found in the catalog "
                "(unknown_item_ids) — both must be resolved before finalizing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_ids": {"type": "array", "items": {"type": "string"}},
                    "budget_inr": {"type": "integer"},
                },
                "required": ["item_ids", "budget_inr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "layout_fit_check",
            "description": (
                "Check whether the given item_ids physically fit the room with "
                "sensible circulation space. Returns fits=false with specific "
                "warnings (oversized items, height conflicts, floor coverage) "
                "when they don't — use those warnings to decide what to swap."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_ids": {"type": "array", "items": {"type": "string"}},
                    "room_length_cm": {"type": "integer"},
                    "room_width_cm": {"type": "integer"},
                    "ceiling_cm": {"type": "integer"},
                },
                "required": ["item_ids", "room_length_cm", "room_width_cm"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_plan",
            "description": (
                "Call this exactly once, as your final action, to deliver the "
                "result. This is the ONLY way to end the conversation — never "
                "just write a final plan as plain text. Use 'status' to say "
                "honestly what happened: 'ok' only if you have a budget-fitting, "
                "layout-fitting set of real, in-stock (or explicitly justified) "
                "items; otherwise pick the status that matches why you could not "
                "produce one, and explain the realistic alternative in "
                "message_to_customer instead of forcing a fake plan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": [
                            "ok",
                            "infeasible_budget",
                            "infeasible_layout",
                            "out_of_scope",
                            "unavailable_items",
                        ],
                        "description": (
                            "'ok': valid plan delivered. 'infeasible_budget': budget too low "
                            "for the must-haves even after substitutions. 'infeasible_layout': "
                            "no combination of suitable items fits the room. 'out_of_scope': the "
                            "request involves structural/electrical/plumbing work, not furniture "
                            "selection. 'unavailable_items': the requested/needed items aren't in "
                            "the catalog, in stock, or priced."
                        ),
                    },
                    "item_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Final selected catalog item_ids. Empty if status is not 'ok'.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Short design rationale: overall approach and key picks.",
                    },
                    "trade_offs": {
                        "type": "string",
                        "description": "What was prioritised, what was left out, and why.",
                    },
                    "message_to_customer": {
                        "type": "string",
                        "description": (
                            "Customer-facing message. For non-'ok' statuses, this must honestly "
                            "explain the limitation and offer the closest realistic alternative — "
                            "never a guaranteed delivery date or a final negotiated price."
                        ),
                    },
                },
                "required": ["status", "item_ids", "rationale", "trade_offs", "message_to_customer"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "catalog_search": catalog_search,
    "budget_calculator": budget_calculator,
    "layout_fit_check": layout_fit_check,
}

SYSTEM_PROMPT = """You are the Interior Company design agent for Living Rooms. You turn a \
customer's room brief into a real, budget-fitting design plan using ONLY the tools provided.

Process:
1. Interpret the brief (room size, budget, style, must-haves, constraints).
2. Use catalog_search to find real candidate items for each must-have category, filtered by \
style and room type. You can call multiple tools at once — issue a catalog_search for EVERY \
must-have category together in a single turn wherever possible, rather than one category per \
turn, to minimize round-trips.
3. Use budget_calculator on your candidate item_ids. If over_budget is true, swap a candidate \
for a cheaper in-stock alternative and check again.
4. Use layout_fit_check on your candidate item_ids with the room dimensions. If fits is false, \
use the warnings to swap the offending item(s) and check again.
5. Repeat 2-4, re-planning based on real tool results, until you have a set that passes both \
checks, or until you determine no valid set exists.
6. Call submit_plan exactly once as your final action with an honest status.

Hard rules:
- Never propose an item_id that did not come back from catalog_search.
- Never call submit_plan with status 'ok' unless your last budget_calculator call showed \
over_budget=false (with no unpriced_items or unknown_item_ids among the final selection) AND \
your last layout_fit_check call showed fits=true.
- Never call submit_plan with status 'infeasible_budget' without having called budget_calculator \
at least once on a real candidate set — even when it looks obviously too expensive from catalog \
prices alone, confirm it with the tool before declaring infeasibility.
- Give up gracefully instead of thrashing: if you've tried substituting items 2-3 times and \
budget_calculator or layout_fit_check still fails, stop searching for more combinations and call \
submit_plan with the appropriate infeasible_* status and an honest explanation, rather than \
continuing to search indefinitely.
- Do not call budget_calculator or layout_fit_check again with the exact same item_ids you just \
checked with that tool — only re-check a tool after you've actually changed the candidate set.
- Do not select an out-of-stock item as a normal available choice. It's fine to mention one \
only if you explicitly explain the lead-time trade-off in your rationale.
- Never state a price, total, or "fits" claim without having gotten it from a tool result.
- If an item catalog_search returns has price_inr=null (price_confirmed=false), do not include \
it in a final 'ok' plan — flag it as unpriced instead, or choose a priced alternative.
- If the must-haves cannot fit the budget even after substitutions, use status \
'infeasible_budget' and suggest the closest realistic trade-off (e.g. drop a must-have, or \
what budget would be needed) instead of quietly exceeding it.
- If no combination fits the room, use status 'infeasible_layout' and say what would need to \
change (fewer pieces, smaller alternatives, more room).
- If the request asks for structural, civil, electrical, or plumbing changes (e.g. removing a \
wall, rewiring), that is out of scope. Use status 'out_of_scope', do not attempt a furniture \
plan for it, and tell the customer to consult a qualified professional.
- If the customer names a specific designer/branded piece not in the catalog, never claim to \
source it. Either offer a similar in-catalog alternative and say so plainly, or use status \
'unavailable_items' if nothing suitable exists.
- Never promise a guaranteed delivery date or a final negotiated price — only lead times and \
list prices as returned by the tools.
- Keep rationale and trade_offs concise and specific to the actual items chosen, not generic.

When multiple items in the same category all satisfy the hard constraints (style, room fit, \
in stock, within budget), choose between them deliberately, not arbitrarily:
- If the customer signals a premium/luxury/high-end preference, you may pick the pricier of \
comparable options, but say why (e.g. materials, finish) in your rationale.
- If the customer signals being budget-conscious or value-focused, prefer the lower-cost option.
- If no preference is stated and the options are genuinely comparable, prefer the more \
cost-effective one and preserve the saved budget for other items rather than spending more for \
no stated reason.
"""


@dataclass
class AgentResult:
    status: str
    item_ids: list
    rationale: str
    trade_offs: str
    message_to_customer: str
    items: list = field(default_factory=list)
    budget_summary: Optional[dict] = None
    fit_summary: Optional[dict] = None
    transcript: list = field(default_factory=list)
    iterations_used: int = 0
    # Usage/cost, for debugging API spend — not part of the agent's own
    # decision-making, purely observational bookkeeping over the same
    # response.usage the SDK already returns on every call.
    api_call_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: Optional[float] = None


def _brief_to_prompt(brief: dict) -> str:
    return (
        f"Room type: {brief.get('room_type', 'Living Room')}\n"
        f"Room dimensions: {brief['length_cm']} cm (length) x {brief['width_cm']} cm (width) x "
        f"{brief['ceiling_cm']} cm (ceiling)\n"
        f"Budget: INR {brief['budget_inr']}\n"
        f"Style preference: {brief.get('style_preference', 'unspecified')}\n"
        f"Must-haves: {brief.get('must_haves', 'unspecified')}\n"
        f"Constraints: {brief.get('constraints', 'none stated')}\n"
        f"Customer note: {brief.get('customer_note', '')}\n"
    )


def _execute_tool(name: str, tool_input: dict) -> Any:
    func = TOOL_FUNCTIONS[name]
    return func(**tool_input)


def run_agent(brief: dict, max_iterations: int = MAX_ITERATIONS) -> AgentResult:
    client = OpenAI(
        api_key=config.AI_GATEWAY_API_KEY,
        base_url=config.AI_GATEWAY_BASE_URL,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _brief_to_prompt(brief)},
    ]

    transcript = []

    # Cache repeated budget/layout checks within the same run.
    dedupable_tool_cache = {}

    # API usage tracking.
    api_call_count = 0
    total_input_tokens = 0
    total_output_tokens = 0

    for iteration in range(1, max_iterations + 1):

        for attempt in range(EMPTY_TURN_RETRIES + 1):

            # Retry the API request once if we hit a 429 rate limit.
            response = None

            for rate_limit_attempt in range(2):
                try:
                    api_call_count += 1

                    response = client.chat.completions.create(
                        model=config.AGENT_MODEL,
                        max_tokens=MAX_TOKENS,
                        tools=TOOLS,
                        messages=messages,
                    )

                    # Request succeeded, so stop retrying.
                    break

                except RateLimitError:

                    # First 429 → wait and retry once.
                    if rate_limit_attempt == 0:
                        time.sleep(5)
                        continue

                    # Second 429 → return gracefully instead of crashing
                    # the Streamlit application.
                    return AgentResult(
                        status="rate_limited",
                        item_ids=[],
                        rationale="",
                        trade_offs="",
                        message_to_customer=(
                            "The AI service is temporarily receiving too many "
                            "requests. Please wait a few seconds and try again."
                        ),
                        transcript=transcript,
                        iterations_used=iteration,
                        api_call_count=api_call_count,
                        total_input_tokens=total_input_tokens,
                        total_output_tokens=total_output_tokens,
                        total_tokens=(
                            total_input_tokens + total_output_tokens
                        ),
                        estimated_cost_usd=estimate_cost_usd(
                            config.AGENT_MODEL,
                            total_input_tokens,
                            total_output_tokens,
                        ),
                    )

            # Track token usage from successful responses.
            if response.usage:
                total_input_tokens += (
                    response.usage.prompt_tokens or 0
                )
                total_output_tokens += (
                    response.usage.completion_tokens or 0
                )

            message = response.choices[0].message

            # Check whether the model actually returned something.
            has_content = (
                bool(message.tool_calls)
                or bool((message.content or "").strip())
            )

            if has_content:
                break

        else:
            return AgentResult(
                status="agent_error",
                item_ids=[],
                rationale="",
                trade_offs="",
                message_to_customer=(
                    "The agent produced an empty response. "
                    "Please try again."
                ),
                transcript=transcript,
                iterations_used=iteration,
                api_call_count=api_call_count,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                total_tokens=(
                    total_input_tokens + total_output_tokens
                ),
                estimated_cost_usd=estimate_cost_usd(
                    config.AGENT_MODEL,
                    total_input_tokens,
                    total_output_tokens,
                ),
            )

        messages.append(
            message.model_dump(exclude_none=True)
        )

        tool_calls = message.tool_calls or []

        # Model returned text but didn't call a tool.
        if not tool_calls:

            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You must call submit_plan to finish — it's the only "
                        "way to deliver a result. Call it now with your best "
                        "honest status."
                    ),
                }
            )

            transcript.append(
                {
                    "tool": "_nudge",
                    "input": None,
                    "result": {
                        "text_seen": (
                            message.content or ""
                        )[:300]
                    },
                }
            )

            continue

        submit_call = None

        for tool_call in tool_calls:

            name = tool_call.function.name
            tool_input = json.loads(
                tool_call.function.arguments
            )

            # Final submission.
            if name == "submit_plan":

                submit_call = tool_input

                transcript.append(
                    {
                        "tool": "submit_plan",
                        "input": tool_input,
                    }
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Plan submitted.",
                    }
                )

                continue

            # Cache repeated budget/layout checks.
            if name in (
                "budget_calculator",
                "layout_fit_check",
            ):

                cache_key = (
                    name,
                    json.dumps(
                        tool_input,
                        sort_keys=True,
                    ),
                )

                if cache_key in dedupable_tool_cache:

                    result = dedupable_tool_cache[
                        cache_key
                    ]

                    transcript.append(
                        {
                            "tool": name,
                            "input": tool_input,
                            "result": result,
                            "cached": True,
                        }
                    )

                else:

                    result = _execute_tool(
                        name,
                        tool_input,
                    )

                    dedupable_tool_cache[
                        cache_key
                    ] = result

                    transcript.append(
                        {
                            "tool": name,
                            "input": tool_input,
                            "result": result,
                        }
                    )

            else:

                result = _execute_tool(
                    name,
                    tool_input,
                )

                transcript.append(
                    {
                        "tool": name,
                        "input": tool_input,
                        "result": result,
                    }
                )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                }
            )

        # Agent submitted a final plan.
        if submit_call is not None:

            item_ids = submit_call.get(
                "item_ids",
                [],
            )

            budget_summary = (
                budget_calculator(
                    item_ids,
                    brief["budget_inr"],
                )
                if item_ids
                else None
            )

            fit_summary = (
                layout_fit_check(
                    item_ids,
                    brief["length_cm"],
                    brief["width_cm"],
                    brief.get("ceiling_cm"),
                )
                if item_ids
                else None
            )

            return AgentResult(
                status=submit_call.get(
                    "status",
                    "agent_error",
                ),
                item_ids=item_ids,
                rationale=submit_call.get(
                    "rationale",
                    "",
                ),
                trade_offs=submit_call.get(
                    "trade_offs",
                    "",
                ),
                message_to_customer=submit_call.get(
                    "message_to_customer",
                    "",
                ),
                items=(
                    budget_summary["items"]
                    if budget_summary
                    else []
                ),
                budget_summary=budget_summary,
                fit_summary=fit_summary,
                transcript=transcript,
                iterations_used=iteration,
                api_call_count=api_call_count,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                total_tokens=(
                    total_input_tokens
                    + total_output_tokens
                ),
                estimated_cost_usd=estimate_cost_usd(
                    config.AGENT_MODEL,
                    total_input_tokens,
                    total_output_tokens,
                ),
            )

        # Force the agent to finish when it is close
        # to the iteration limit.
        if iteration >= max_iterations - 2:

            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You are approaching the step limit. On your NEXT "
                        "response you must call submit_plan with your best "
                        "honest status based on everything you've learned so "
                        "far — do not call any more search or check tools."
                    ),
                }
            )

    # Agent used all iterations without submitting.
    return AgentResult(
        status="max_iterations_exceeded",
        item_ids=[],
        rationale="",
        trade_offs="",
        message_to_customer=(
            "The agent could not converge on a plan within "
            "the allowed number of steps."
        ),
        transcript=transcript,
        iterations_used=max_iterations,
        api_call_count=api_call_count,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_tokens=(
            total_input_tokens
            + total_output_tokens
        ),
        estimated_cost_usd=estimate_cost_usd(
            config.AGENT_MODEL,
            total_input_tokens,
            total_output_tokens,
        ),
    )
