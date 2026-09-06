"""Tool: catalog_search.

Queries the real product catalog. This is the agent's only way to learn what
products exist — it must never answer from the model's own "memory" of
furniture. Items with a NULL price are excluded whenever a price filter is
given, since affordability can't be verified for them.
"""
from typing import Optional

from .. import db


def catalog_search(
    category: Optional[str] = None,
    style: Optional[str] = None,
    room_type: Optional[str] = None,
    max_price: Optional[int] = None,
    min_price: Optional[int] = None,
    in_stock_only: bool = False,
) -> dict:
    clauses = []
    params: list = []

    if category:
        # Case-insensitive, bidirectional substring match: the model doesn't always
        # phrase categories exactly as they're stored (e.g. "Console Table" vs the
        # catalog's "Console"), so match either direction rather than requiring an
        # exact string — this only ever narrows to real catalog rows either way.
        clauses.append("(LOWER(category) LIKE '%' || LOWER(?) || '%' OR LOWER(?) LIKE '%' || LOWER(category) || '%')")
        params.extend([category, category])
    if style:
        clauses.append("style_tags LIKE ?")
        params.append(f"%{style}%")
    if room_type:
        clauses.append("room_types LIKE ?")
        params.append(f"%{room_type}%")
    if in_stock_only:
        clauses.append("in_stock = 1")
    if max_price is not None:
        clauses.append("price_inr IS NOT NULL AND price_inr <= ?")
        params.append(max_price)
    if min_price is not None:
        clauses.append("price_inr IS NOT NULL AND price_inr >= ?")
        params.append(min_price)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"SELECT * FROM catalog {where} ORDER BY category, price_inr"

    with db.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    items = [dict(row) for row in rows]
    for item in items:
        item["price_confirmed"] = item["price_inr"] is not None

    return {"count": len(items), "items": items}
