"""Shared SQL & In-Memory Event Filtering Helpers (Severity Hierarchy, Normalized & Multi-Term)."""

from collections.abc import Iterable
from typing import Any

SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}
_ORDERED_SEVERITIES: tuple[str, ...] = ("info", "warning", "critical")


def normalize_zone_name(zone_id: str | None) -> str:
    """Strip camera-scoped prefixes (``<cam>:zone:<name>``) and trim whitespace."""
    raw = str(zone_id or "").strip()
    if not raw:
        return ""
    if ":zone:" in raw:
        return raw.rsplit(":zone:", 1)[-1].strip()
    return raw


def split_filter_terms(raw: str | None) -> list[str]:
    """Split a comma-separated filter string into trimmed non-empty lowercase terms."""
    if not raw:
        return []
    return [part.strip().lower() for part in str(raw).split(",") if part.strip()]


def severity_levels_for_min(min_severity: str | None) -> list[str]:
    """Return ordered severity levels at or above ``min_severity`` (empty if invalid/unset)."""
    key = str(min_severity or "").strip().lower()
    if key not in SEVERITY_RANK:
        return []
    floor = SEVERITY_RANK[key]
    return [sev for sev in _ORDERED_SEVERITIES if SEVERITY_RANK[sev] >= floor]


def dedupe_normalized_zones(raw_zones: Iterable[str]) -> list[str]:
    """Normalize scoped/unscoped zone names and return deduplicated sorted list."""
    seen: dict[str, str] = {}
    for raw in raw_zones:
        norm = normalize_zone_name(raw)
        if not norm:
            continue
        low = norm.lower()
        if low not in seen:
            seen[low] = norm
    return sorted(seen.values(), key=str.lower)


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _append_multi_like(
    clauses: list[str],
    params: list[Any],
    column_expr: str,
    terms: list[str],
) -> None:
    if not terms:
        return
    sub: list[str] = []
    for term in terms:
        sub.append(f"LOWER(COALESCE({column_expr}, '')) LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(term)}%")
    clauses.append(f"({' OR '.join(sub)})")


def _append_severity_clause(
    clauses: list[str],
    params: list[Any],
    prefix: str,
    levels: list[str],
) -> None:
    if not levels:
        return
    meta_expr = f"COALESCE(NULLIF(LOWER(TRIM(json_extract({prefix}metadata_json, '$.severity'))), ''), 'info')"
    tags_expr = f"(',' || LOWER(COALESCE({prefix}tags, '')) || ',')"
    placeholders = ", ".join("?" for _ in levels)
    sub = [f"{meta_expr} IN ({placeholders})"]
    params.extend(levels)
    for lvl in levels:
        if lvl != "info":
            sub.append(f"{tags_expr} LIKE ?")
            params.append(f"%,{lvl},%")
    clauses.append(f"({' OR '.join(sub)})")


def build_event_filter_clauses(
    *,
    table_alias: str = "", entity_id: int | None = None, camera_id: str | None = None,
    zone_id: str | None = None, event_type: str | None = None,
    start_time: float | None = None, end_time: float | None = None,
    severity: str | None = None, min_severity: str | None = None, read_only: bool = False,
) -> tuple[list[str], list[Any]]:
    """Build parameterized SQL WHERE clauses shared by MemoryMixin and EventsAdminMixin."""
    p = f"{table_alias}." if table_alias else ""
    clauses: list[str] = []
    params: list[Any] = []
    for clause, val in (
        (f"{p}entity_id = ?", int(entity_id) if entity_id is not None else None),
        (f"{p}camera_id = ?", camera_id.strip() if camera_id and camera_id.strip() else None),
        (f"{p}timestamp >= ?", float(start_time) if start_time is not None else None),
        (f"{p}timestamp <= ?", float(end_time) if end_time is not None else None),
    ):
        if val is not None:
            clauses.append(clause)
            params.append(val)
    if zone_id and zone_id.strip():
        zone_terms = [normalize_zone_name(t).lower() for t in split_filter_terms(zone_id)]
        _append_multi_like(clauses, params, f"{p}zone_id", [t for t in zone_terms if t])
    if event_type and event_type.strip():
        _append_multi_like(clauses, params, f"{p}event_type", split_filter_terms(event_type))
    sev = severity.strip().lower() if severity else ""
    if sev:
        _append_severity_clause(clauses, params, p, [sev])
    min_levels = severity_levels_for_min(min_severity)
    if min_levels:
        _append_severity_clause(clauses, params, p, min_levels)
    if read_only:
        clauses.append(f"COALESCE({p}is_read, 0) = 1")
    return clauses, params


def _extract_item_severity(item: dict[str, Any]) -> str:
    raw_meta = item.get("metadata")
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    sev = str(item.get("severity") or meta.get("severity") or "").strip().lower()
    if sev in SEVERITY_RANK:
        return sev
    tags = f",{str(item.get('tags') or '').lower()},"
    for candidate in ("critical", "warning"):
        if f",{candidate}," in tags:
            return candidate
    return "info"


def matches_event_filters(
    item: dict[str, Any],
    *,
    camera_id: str | None = None,
    severity: str | None = None,
    min_severity: str | None = None,
    event_type: str | None = None,
    zone_id: str | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
) -> bool:
    """In-memory parity filter matching SQL semantics for EventBus fallback queries."""
    if camera_id and str(item.get("camera_id") or "") != camera_id.strip():
        return False
    if event_type and event_type.strip():
        ev_val = str(item.get("event_type") or "").lower()
        terms = split_filter_terms(event_type)
        if terms and not any(t in ev_val for t in terms):
            return False
    if zone_id and zone_id.strip():
        zone_val = normalize_zone_name(item.get("zone_id")).lower()
        terms = [normalize_zone_name(t).lower() for t in split_filter_terms(zone_id)]
        if terms and not any(t in zone_val for t in terms if t):
            return False
    ts = float(item.get("timestamp") or 0.0)
    if start_time is not None and ts < float(start_time):
        return False
    if end_time is not None and ts > float(end_time):
        return False
    item_sev = _extract_item_severity(item)
    if severity and severity.strip():
        if item_sev != severity.strip().lower():
            return False
    min_levels = severity_levels_for_min(min_severity)
    if min_levels and item_sev not in min_levels:
        return False
    return True
