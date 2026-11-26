"""Pure domain SSOT for semantic categories, COCO label mapping, and SQLite migrations."""

from dataclasses import asdict, dataclass
import json
import re
import sqlite3
from typing import Any

CATEGORY_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")

DEFAULT_CUSTOM_CATEGORIES: list[dict[str, str]] = [
    {"id": "person", "name": "Person", "color": "#3B82F6", "badge_icon": "👤", "description": "General person"},
    {"id": "staff", "name": "Staff", "color": "#10B981", "badge_icon": "🪪", "description": "Authorized staff or personnel"},
    {"id": "visitor", "name": "Visitor", "color": "#F59E0B", "badge_icon": "🎫", "description": "Registered guest or visitor"},
    {"id": "vip", "name": "VIP", "color": "#6366F1", "badge_icon": "⭐", "description": "High-priority VIP individual"},
    {"id": "restricted", "name": "Restricted / Watchlist", "color": "#EF4444", "badge_icon": "⛔", "description": "Watchlist or unauthorized presence"},
    {"id": "vehicle", "name": "Vehicle", "color": "#0EA5E9", "badge_icon": "🚗", "description": "Motor vehicle or transport"},
    {"id": "pet", "name": "Pet", "color": "#06B6D4", "badge_icon": "🐾", "description": "Domestic animal or pet"},
    {"id": "bag_parcel", "name": "Bag / Parcel", "color": "#A855F7", "badge_icon": "📦", "description": "Luggage, backpack, or parcel"},
    {"id": "asset", "name": "Asset", "color": "#64748B", "badge_icon": "🏷️", "description": "Tracked equipment or object"},
]

LEGACY_DEMO_CATEGORY_IDS: tuple[str, ...] = (
    "family_car",
    "delivery_truck",
    "cleaning_crew",
    "guard_dog",
)

LEGACY_DEFAULT_OVERRIDES: dict[str, tuple[str, str]] = {
    "person": ("Person", "user"),
    "pet": ("Household Pet", "paw"),
    "vip": ("VIP Resident", "star"),
    "restricted": ("Restricted / Watchlist", "alert-triangle"),
}

CATEGORY_ALIASES: dict[str, str] = {
    "object": "asset",
    "other": "asset",
    "custom": "asset",
}

COCO_CATEGORY_MAP: dict[str, str] = {
    "person": "person",
    "mock_person": "person",
    "car": "vehicle",
    "truck": "vehicle",
    "bus": "vehicle",
    "motorcycle": "vehicle",
    "bicycle": "vehicle",
    "train": "vehicle",
    "boat": "vehicle",
    "airplane": "vehicle",
    "backpack": "bag_parcel",
    "suitcase": "bag_parcel",
    "handbag": "bag_parcel",
    "dog": "pet",
    "cat": "pet",
    "bird": "pet",
    "horse": "pet",
    "sheep": "pet",
    "cow": "pet",
}


@dataclass
class CustomCategory:
    """Semantic category with display color and metadata."""

    id: str
    name: str
    color: str = "#3B82F6"
    badge_icon: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize custom category fields to dictionary."""
        return asdict(self)


def normalize_category_slug(raw: str | None) -> str:
    """Normalize raw category text into lowercase slug form."""
    clean = str(raw or "").strip().lower()
    return re.sub(r"[\s.]+", "_", clean)


def resolve_category_alias(slug: str) -> str:
    """Map legacy UI/heuristic fallback category aliases to canonical slugs."""
    return CATEGORY_ALIASES.get(slug, slug)


def is_valid_category_slug(slug: str) -> bool:
    """Return True when ``slug`` matches the strict category identifier pattern."""
    return bool(isinstance(slug, str) and CATEGORY_SLUG_RE.match(slug))


def map_detector_label_to_category(label: str | None) -> str:
    """Map a detector label (COCO or mock) into a canonical semantic category slug."""
    clean = str(label or "").strip().lower()
    if not clean:
        return "object"
    return COCO_CATEGORY_MAP.get(clean, "asset")


def _json_contains_category(raw_json: Any, cat_id: str) -> bool:
    """Check whether a serialized JSON category array references ``cat_id``."""
    if not raw_json:
        return False
    target = cat_id.strip().lower()
    try:
        parsed = json.loads(raw_json)
        if isinstance(parsed, list):
            return any(str(v).strip().lower() == target for v in parsed)
    except (TypeError, ValueError):
        pass
    return f'"{target}"' in str(raw_json).lower()


def _is_legacy_category_referenced(cursor: sqlite3.Cursor, cat_id: str) -> bool:
    """Return True if any entity or RSAC zone rule references ``cat_id``."""
    cursor.execute(
        "SELECT 1 FROM entities WHERE LOWER(TRIM(category)) = ? LIMIT 1",
        (cat_id,),
    )
    if cursor.fetchone() is not None:
        return True
    cursor.execute("SELECT allowed_categories_json, denied_categories_json FROM rsac_zone_rules")
    for row in cursor.fetchall():
        if _json_contains_category(row[0], cat_id) or _json_contains_category(row[1], cat_id):
            return True
    return False


def _prune_unreferenced_legacy_categories(cursor: sqlite3.Cursor) -> None:
    """Remove legacy demo categories and guard_dog pet whitelist entry when unreferenced."""
    for legacy_id in LEGACY_DEMO_CATEGORY_IDS:
        if _is_legacy_category_referenced(cursor, legacy_id):
            continue
        cursor.execute("DELETE FROM custom_categories WHERE id = ?", (legacy_id,))
        if legacy_id == "guard_dog":
            cursor.execute("DELETE FROM pet_whitelist WHERE LOWER(TRIM(category_or_label)) = ?", ("guard_dog",))


def _register_entity_categories(cursor: sqlite3.Cursor) -> None:
    """Auto-register distinct valid categories found in ``entities.category``."""
    cursor.execute("SELECT DISTINCT category FROM entities WHERE category IS NOT NULL AND TRIM(category) != ''")
    for row in cursor.fetchall():
        slug = normalize_category_slug(row[0])
        if not is_valid_category_slug(slug):
            continue
        title = slug.replace("_", " ").replace("-", " ").title()
        cursor.execute(
            "INSERT OR IGNORE INTO custom_categories (id, name, color, badge_icon, description) VALUES (?, ?, ?, ?, ?)",
            (slug, title, "#94A3B8", "🏷️", "Migrated from existing entities"),
        )


def migrate_category_registry(cursor: sqlite3.Cursor) -> None:
    """Idempotently seed universal defaults, upgrade untouched icons, prune legacy demos, and migrate entity categories."""
    cursor.executemany(
        "INSERT OR IGNORE INTO custom_categories (id, name, color, badge_icon, description) VALUES (?, ?, ?, ?, ?)",
        [(c["id"], c["name"], c["color"], c["badge_icon"], c["description"]) for c in DEFAULT_CUSTOM_CATEGORIES],
    )
    defaults_by_id = {c["id"]: c for c in DEFAULT_CUSTOM_CATEGORIES}
    for cat_id, (old_name, old_icon) in LEGACY_DEFAULT_OVERRIDES.items():
        new_def = defaults_by_id[cat_id]
        cursor.execute(
            "UPDATE custom_categories SET name = ?, badge_icon = ? WHERE id = ? AND name = ? AND badge_icon = ?",
            (new_def["name"], new_def["badge_icon"], cat_id, old_name, old_icon),
        )
    _prune_unreferenced_legacy_categories(cursor)
    _register_entity_categories(cursor)
