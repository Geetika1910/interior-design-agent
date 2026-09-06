"""Read-only queries that populate the Streamlit form from the real catalog,
so style/category options are never hardcoded — they come from whatever is
actually in the database.
"""
from . import db


def get_living_room_styles() -> list:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT style_tags FROM catalog "
            "WHERE room_types LIKE '%Living Room%' AND style_tags IS NOT NULL"
        ).fetchall()

    styles = set()
    for row in rows:
        for tag in row["style_tags"].split(","):
            tag = tag.strip()
            if tag:
                styles.add(tag)
    return sorted(styles)


def get_living_room_categories() -> list:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM catalog "
            "WHERE room_types LIKE '%Living Room%' ORDER BY category"
        ).fetchall()
    return [row["category"] for row in rows]


def get_living_room_sample_briefs() -> list:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM room_briefs WHERE room_type = 'Living Room' ORDER BY brief_id"
        ).fetchall()
    return [dict(row) for row in rows]


def get_items_by_ids(item_ids: list) -> list:
    """Full catalog rows for display (dimensions, color/finish included),
    in the same order as item_ids. The catalog has no image column — this
    is the complete real product data available."""
    if not item_ids:
        return []
    placeholders = ",".join("?" for _ in item_ids)
    with db.get_connection() as conn:
        rows = conn.execute(f"SELECT * FROM catalog WHERE item_id IN ({placeholders})", item_ids).fetchall()
    by_id = {row["item_id"]: dict(row) for row in rows}
    return [by_id[i] for i in item_ids if i in by_id]
