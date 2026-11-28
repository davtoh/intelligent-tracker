"""Alert Promotion Rules Engine: Elevates Event Severity During Write-Through Indexing."""

import logging
import threading
from typing import Any

from intelligent_tracker.repositories._event_filter_sql import (
    SEVERITY_RANK,
    normalize_zone_name,
    split_filter_terms,
)

logger = logging.getLogger(__name__)


def _rule_matches_doc(rule: dict[str, Any], doc: dict[str, Any]) -> bool:
    """Return True if a single enabled promotion rule matches the event document."""
    if not rule.get("enabled", True):
        return False

    ev_terms = split_filter_terms(rule.get("event_type"))
    if ev_terms:
        ev_val = str(doc.get("event_type") or "").strip().lower()
        if not any(t in ev_val for t in ev_terms):
            return False

    zone_terms = [normalize_zone_name(t).lower() for t in split_filter_terms(rule.get("zone_id"))]
    if zone_terms:
        zone_val = normalize_zone_name(doc.get("zone_id")).lower()
        if not zone_val or not any(t in zone_val for t in zone_terms if t):
            return False

    cam_terms = split_filter_terms(rule.get("camera_id"))
    if cam_terms:
        cam_val = str(doc.get("camera_id") or "").strip().lower()
        if cam_val not in cam_terms:
            return False

    raw_meta = doc.get("metadata")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    cat_terms = split_filter_terms(rule.get("category"))
    if cat_terms:
        cat_val = str(doc.get("category") or meta.get("category") or "").strip().lower()
        if cat_val not in cat_terms:
            return False

    min_dwell = rule.get("min_dwell_time")
    if min_dwell is not None:
        raw_dwell = meta.get("dwell_time")
        if raw_dwell is None:
            return False
        try:
            if float(raw_dwell) < float(min_dwell):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _merge_tags(existing_tags: str, additions: list[str]) -> str:
    """Append deduplicated tags preserving original order."""
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in existing_tags.split(",") + additions:
        tok = raw.strip()
        if not tok:
            continue
        low = tok.lower()
        if low not in seen:
            seen.add(low)
            ordered.append(tok)
    return ",".join(ordered)


class AlertPromotionEngine:
    """Evaluates DB-backed alert promotion rules and syncs WorldGraph policy settings."""

    def __init__(self, db: Any = None, world_graph: Any = None) -> None:
        self._db = db
        self._world_graph = world_graph
        self._lock = threading.RLock()
        self._rules: list[dict[str, Any]] = []
        self.reload()

    def reload(self) -> list[dict[str, Any]]:
        """Reload enabled alert promotion rules from TrackerDB into memory."""
        rules: list[dict[str, Any]] = []
        if self._db is not None and not getattr(self._db, "_closed", False) and hasattr(self._db, "list_alert_rules"):
            try:
                rules = list(self._db.list_alert_rules(enabled_only=True))
            except Exception as exc:
                logger.debug("AlertPromotionEngine.reload skipped: %s", exc)
        with self._lock:
            self._rules = rules
            return list(self._rules)

    def get_rules(self) -> list[dict[str, Any]]:
        """Return a snapshot of cached enabled rules."""
        with self._lock:
            return list(self._rules)

    def sync_policy(self, policy: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Load persisted alert policy (if needed) and push updates to WorldGraph."""
        resolved = policy
        if resolved is None and self._db is not None and not getattr(self._db, "_closed", False):
            if hasattr(self._db, "get_alert_policy"):
                try:
                    resolved = self._db.get_alert_policy()
                except Exception as exc:
                    logger.debug("AlertPromotionEngine.sync_policy read failed: %s", exc)
        if resolved is None:
            return None
        wg = self._world_graph
        if wg is not None:
            updater = getattr(wg, "update_policy", None) or getattr(wg, "set_policy", None)
            if callable(updater):
                updates: dict[str, Any] = {}
                for field_name in ("dwell_override", "alert_sensitivity", "quiet_hours", "extra"):
                    if field_name in resolved:
                        updates[field_name] = resolved[field_name]
                if updates:
                    try:
                        updater(**updates)
                    except Exception as exc:
                        logger.warning("AlertPromotionEngine failed syncing WorldGraph policy: %s", exc)
        return resolved

    def evaluate(self, doc: dict[str, Any]) -> dict[str, Any]:
        """Evaluate cached rules against a normalized event doc; upgrade severity (never downgrade)."""
        with self._lock:
            rules = list(self._rules)
        if not rules:
            return doc

        matched = [r for r in rules if _rule_matches_doc(r, doc)]
        if not matched:
            return doc

        meta = dict(doc.get("metadata") or {}) if isinstance(doc.get("metadata"), dict) else {}
        cur_sev = str(meta.get("severity") or doc.get("severity") or "info").strip().lower()
        orig_rank = SEVERITY_RANK.get(cur_sev, 0)
        best_rank = orig_rank
        best_sev = cur_sev if cur_sev in SEVERITY_RANK else "info"
        winning_rule: dict[str, Any] | None = None
        extra_tags: list[str] = ["promoted"]

        for rule in matched:
            target = str(rule.get("target_severity") or "warning").strip().lower()
            rank = SEVERITY_RANK.get(target, 0)
            if rank > best_rank:
                best_rank = rank
                best_sev = target
                winning_rule = rule
            raw_add = str(rule.get("add_tags") or "")
            extra_tags.extend(t.strip() for t in raw_add.split(",") if t.strip())

        if winning_rule is None or best_rank <= orig_rank:
            return doc

        meta["severity"] = best_sev
        meta["promoted_by_rule"] = str(winning_rule.get("name") or "")
        meta["promoted_by_rule_id"] = int(winning_rule["id"]) if winning_rule.get("id") is not None else None
        extra_tags.append(best_sev)

        updated = dict(doc)
        updated["severity"] = best_sev
        updated["metadata"] = meta
        updated["tags"] = _merge_tags(str(doc.get("tags") or ""), extra_tags)
        return updated
