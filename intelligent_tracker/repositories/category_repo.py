"""Repository mixin for semantic category reference counting."""

import json
from typing import TYPE_CHECKING, Any


def _row_references_category(raw_json: Any, target: str) -> bool:
    """Return True when a serialized JSON list contains ``target``."""
    if not raw_json:
        return False
    try:
        items = json.loads(raw_json)
        if isinstance(items, list):
            return any(str(v).strip().lower() == target for v in items)
    except (TypeError, ValueError):
        pass
    return f'"{target}"' in str(raw_json).lower()


class CategoryRepoMixin:
    """Provides category reference-counting queries for safe delete and preset replacement."""

    if TYPE_CHECKING:
        _lock: Any
        _conn: Any

    def count_category_references(self, cat_id: str) -> dict[str, int]:
        """Count entities and RSAC zone rules referencing ``cat_id``."""
        clean = str(cat_id or "").strip().lower()
        if not clean:
            return {"entities": 0, "rules": 0}
        with self._lock:
            if self._conn is None:
                return {"entities": 0, "rules": 0}
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "SELECT COUNT(*) FROM entities WHERE LOWER(TRIM(category)) = ?",
                    (clean,),
                )
                entities_count = int(cur.fetchone()[0])
                cur.execute("SELECT allowed_categories_json, denied_categories_json FROM rsac_zone_rules")
                rules_count = sum(
                    1
                    for row in cur.fetchall()
                    if _row_references_category(row[0], clean) or _row_references_category(row[1], clean)
                )
                return {"entities": entities_count, "rules": rules_count}
            finally:
                cur.close()
