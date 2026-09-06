"""The LLM-as-judge rubric and tool schema, kept in code (not a prompt buried
inline) so the evaluation is reproducible and inspectable.

The judge never re-derives budget/fit numbers — those are already ground
truth from the deterministic scorers. It only scores things that genuinely
require judgement: whether the result reads well and is honest.
"""

JUDGE_SYSTEM_PROMPT = """You are a strict, impartial quality reviewer for an AI interior design agent's \
output. You are given the customer's brief, the agent's final structured result (status, \
selected items with real catalog data, rationale, trade-offs, and customer-facing message), \
and you score it against the rubric below by calling submit_scores exactly once.

Ground every score in what's actually in front of you — the real item names/styles/prices \
provided, and the agent's own text. Do not use outside knowledge of real designers or brands \
beyond judging whether the agent itself made false claims. Do not reward flowery language; \
reward accuracy and usefulness to the customer. A score of 5 requires genuine excellence, not \
just "acceptable" — most competent outputs should score 3-4.
"""

JUDGE_RUBRIC = """Score each dimension 1 (poor) to 5 (excellent). Use null when a dimension does \
not apply to this case (explained per dimension below).

1. style_coherence — null unless status is "ok". Do the selected items' styles, materials, and \
colors form a genuinely coherent look matching the requested style_preference, or do they read \
as a mismatched grab-bag?

2. preference_alignment — null unless status is "ok". Does the plan respect the customer's \
explicit must-haves and stated context/constraints (e.g. "no TV", "rented home", "couple, no \
kids"), not just the budget and room size?

3. tradeoff_quality — always scored. Are the stated trade-offs (what was prioritised, what was \
left out, why) specific and grounded in the real prices/dimensions given, or generic filler that \
could apply to any brief?

4. explanation_quality — always scored. Is the rationale and customer message clear, concise, \
and specific to the actual items chosen, rather than vague marketing language?

5. honest_alternatives — null only if status is "ok" AND the rationale shows no substitution, \
compromise, or dropped preference was needed at all. Otherwise: when the plan couldn't fully \
satisfy the request, or substituted/left something out, does the message say so plainly and \
offer a realistic next step — rather than glossing over the gap or overpromising (e.g. a \
guaranteed delivery date, a "final" price, or a claim to source a product that isn't in the \
catalog)?
"""

# OpenAI function-calling format (the wire format the Vercel AI Gateway's
# /v1/chat/completions endpoint expects).
JUDGE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_scores",
        "description": "Submit your rubric scores for this case.",
        "parameters": {
            "type": "object",
            "properties": {
                "style_coherence": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
                "preference_alignment": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
                "tradeoff_quality": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
                "explanation_quality": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
                "honest_alternatives": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
                "comment": {"type": "string", "description": "One or two sentences justifying the scores."},
            },
            "required": [
                "style_coherence",
                "preference_alignment",
                "tradeoff_quality",
                "explanation_quality",
                "honest_alternatives",
                "comment",
            ],
        },
    },
}
