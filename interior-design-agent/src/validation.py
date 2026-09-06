"""Pre-agent input validation.

Catches malformed briefs before spending an API call on them: an
unsupported room type (this MVP is scoped to Living Room only) or a
missing/invalid required numeric field. This is a product-scope decision,
not something the LLM should be asked to adjudicate, so it's enforced here
rather than as another submit_plan status.
"""
SUPPORTED_ROOM_TYPE = "Living Room"
REQUIRED_NUMERIC_FIELDS = ["length_cm", "width_cm", "ceiling_cm", "budget_inr"]


def validate_brief(brief: dict) -> tuple:
    room_type = brief.get("room_type")
    if room_type != SUPPORTED_ROOM_TYPE:
        return False, (
            f"Unsupported room type '{room_type}'. This MVP only supports "
            f"'{SUPPORTED_ROOM_TYPE}' briefs."
        )

    for field in REQUIRED_NUMERIC_FIELDS:
        value = brief.get(field)
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return False, f"Missing or invalid required field: '{field}'."

    return True, ""
