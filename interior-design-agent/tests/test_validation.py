"""Zero-cost tests for pre-agent input validation (no API calls)."""
from src.validation import validate_brief

GOOD_BRIEF = {"room_type": "Living Room", "length_cm": 480, "width_cm": 360, "ceiling_cm": 300, "budget_inr": 250000}


def test_valid_brief_passes():
    is_valid, message = validate_brief(GOOD_BRIEF)
    assert is_valid is True
    assert message == ""


def test_unsupported_room_type_rejected():
    is_valid, message = validate_brief(dict(GOOD_BRIEF, room_type="Kitchen"))
    assert is_valid is False
    assert "room type" in message.lower()


def test_missing_budget_rejected():
    brief = dict(GOOD_BRIEF)
    brief["budget_inr"] = None
    is_valid, message = validate_brief(brief)
    assert is_valid is False
    assert "budget_inr" in message


def test_zero_budget_rejected():
    is_valid, _ = validate_brief(dict(GOOD_BRIEF, budget_inr=0))
    assert is_valid is False


def test_missing_dimension_rejected():
    brief = dict(GOOD_BRIEF)
    del brief["length_cm"]
    is_valid, message = validate_brief(brief)
    assert is_valid is False
    assert "length_cm" in message


if __name__ == "__main__":
    import sys
    from tests._runner import run_module
    ok = run_module(sys.modules[__name__])
    sys.exit(0 if ok else 1)
