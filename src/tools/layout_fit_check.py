"""Tool: layout_fit_check.

A simple, sensible heuristic (not a CAD engine) for whether the selected
pieces physically fit the room with room left to walk around:

1. Total furniture footprint (sum of width x depth) must not exceed a
   configurable share of the floor area (default 55%) — the rest is assumed
   circulation space.
2. No single item's width/depth may exceed the room's width/length minus a
   minimum clearance (default 75cm), i.e. it must be physically placeable
   with a walkway on at least one side.
3. No item's height may exceed the ceiling height minus a clearance margin
   (default 20cm).

Items with missing width/depth are skipped from the footprint math (none
exist in the current catalog, but the brief notes dimensions "may be NULL",
so this is handled defensively) and surfaced as a warning instead of
silently ignored.
"""
from typing import List, Optional

from .. import config, db

# Floor coverings and wall-mounted pieces don't need a walking clearance the
# way freestanding furniture does — a rug can span close to a room's full
# width, and wall art/mirrors/curtains hang flat against a wall. They're
# still exempt only from the *individual-item* clearance check below, not
# from the overall floor-coverage total.
NO_CLEARANCE_CATEGORIES = {"Rug", "Wall Art", "Mirror", "Curtains"}


def layout_fit_check(
    item_ids: List[str],
    room_length_cm: int,
    room_width_cm: int,
    ceiling_cm: Optional[int] = None,
) -> dict:
    room_area_m2 = room_length_cm * room_width_cm / 10000

    if not item_ids:
        return {
            "fits": True,
            "room_area_m2": round(room_area_m2, 2),
            "furniture_footprint_m2": 0.0,
            "coverage_ratio": 0.0,
            "max_coverage_allowed": config.MAX_FURNITURE_COVERAGE,
            "oversized_items": [],
            "height_conflicts": [],
            "warnings": [],
        }

    placeholders = ",".join("?" for _ in item_ids)
    with db.get_connection() as conn:
        rows = conn.execute(
            f"SELECT item_id, name, category, width_cm, depth_cm, height_cm "
            f"FROM catalog WHERE item_id IN ({placeholders})",
            item_ids,
        ).fetchall()

    items = [dict(row) for row in rows]

    footprint_m2 = 0.0
    oversized_items = []
    height_conflicts = []
    warnings = []

    found_ids = {item["item_id"] for item in items}
    unknown_item_ids = [i for i in item_ids if i not in found_ids]
    if unknown_item_ids:
        warnings.append(
            f"item_id(s) not found in catalog, excluded from the fit check: "
            f"{', '.join(unknown_item_ids)}"
        )

    for item in items:
        w, d, h = item["width_cm"], item["depth_cm"], item["height_cm"]
        if w is None or d is None:
            warnings.append(
                f"{item['item_id']} ({item['name']}) has no dimensions on file "
                f"— cannot verify it fits."
            )
            continue

        footprint_m2 += (w * d) / 10000

        needs_clearance = item["category"] not in NO_CLEARANCE_CATEGORIES
        if needs_clearance and (
            w > room_width_cm - config.MIN_CLEARANCE_CM or d > room_length_cm - config.MIN_CLEARANCE_CM
        ):
            oversized_items.append(item["item_id"])

        if ceiling_cm and h and h > ceiling_cm - config.MIN_CEILING_CLEARANCE_CM:
            height_conflicts.append(item["item_id"])

    coverage_ratio = round(footprint_m2 / room_area_m2, 3) if room_area_m2 else 0.0
    over_coverage = coverage_ratio > config.MAX_FURNITURE_COVERAGE

    if over_coverage:
        warnings.append(
            f"Selected pieces cover {coverage_ratio:.0%} of the floor area, "
            f"above the {config.MAX_FURNITURE_COVERAGE:.0%} comfort threshold "
            f"for circulation space."
        )
    if oversized_items:
        warnings.append(f"Item(s) too large for the room footprint: {', '.join(oversized_items)}")
    if height_conflicts:
        warnings.append(f"Item(s) too tall for the ceiling height: {', '.join(height_conflicts)}")

    fits = not over_coverage and not oversized_items and not height_conflicts

    return {
        "fits": fits,
        "room_area_m2": round(room_area_m2, 2),
        "furniture_footprint_m2": round(footprint_m2, 2),
        "coverage_ratio": coverage_ratio,
        "max_coverage_allowed": config.MAX_FURNITURE_COVERAGE,
        "oversized_items": oversized_items,
        "height_conflicts": height_conflicts,
        "warnings": warnings,
    }
