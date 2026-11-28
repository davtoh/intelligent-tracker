"""SQLite Repository Mixin for Alert Promotion Rules & Alert Policy Settings."""

import json
import sqlite3
from typing import Any

VALID_ALERT_SEVERITIES = frozenset({"info", "warning", "critical"})
_UNSET = object()

_RULE_COLUMNS = (
    "id", "name", "enabled", "event_type", "zone_id", "camera_id",
    "category", "min_dwell_time", "target_severity", "add_tags",
    "created_at", "updated_at",
)
_UPDATABLE_RULE_FIELDS = frozenset({
    "name", "enabled", "event_type", "zone_id", "camera_id",
    "category", "min_dwell_time", "target_severity", "add_tags",
})


def _validate_severity(value: str) -> str:
    sev = str(value or "warning").strip().lower()
    if sev not in VALID_ALERT_SEVERITIES:
        raise ValueError(f"Invalid target_severity {value!r}; expected one of {sorted(VALID_ALERT_SEVERITIES)}")
    return sev


def _hydrate_rule(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["id"] = int(data["id"])
    data["enabled"] = bool(data.get("enabled", 1))
    if data.get("min_dwell_time") is not None:
        data["min_dwell_time"] = float(data["min_dwell_time"])
    return data


def _default_policy() -> dict[str, Any]:
    return {
        "dwell_override": None,
        "alert_sensitivity": 1.0,
        "quiet_hours": None,
        "extra": {},
        "updated_at": None,
    }


def _hydrate_policy(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return _default_policy()
    data = dict(row)
    try:
        quiet_hours = json.loads(data["quiet_hours_json"]) if data.get("quiet_hours_json") else None
    except (TypeError, ValueError):
        quiet_hours = None
    try:
        extra = json.loads(data["extra_json"]) if data.get("extra_json") else {}
        if not isinstance(extra, dict):
            extra = {}
    except (TypeError, ValueError):
        extra = {}
    raw_sens = data.get("alert_sensitivity")
    return {
        "dwell_override": float(data["dwell_override"]) if data.get("dwell_override") is not None else None,
        "alert_sensitivity": float(raw_sens) if raw_sens is not None else 1.0,
        "quiet_hours": quiet_hours,
        "extra": extra,
        "updated_at": data.get("updated_at"),
    }


class AlertRulesMixin:
    """CRUD operations for alert promotion rules and global alert policy settings."""

    _conn: Any
    _lock: Any

    def list_alert_rules(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        """Return all alert promotion rules ordered by id ascending."""
        with self._lock:
            if self._conn is None:
                return []
            cur = self._conn.cursor()
            try:
                where = " WHERE enabled = 1" if enabled_only else ""
                rows = cur.execute(
                    f"SELECT {', '.join(_RULE_COLUMNS)} FROM alert_promotion_rules{where} ORDER BY id ASC"
                ).fetchall()
                return [_hydrate_rule(r) for r in rows]
            finally:
                cur.close()

    def get_alert_rule(self, rule_id: int) -> dict[str, Any] | None:
        """Return a single alert promotion rule by id, or None."""
        with self._lock:
            if self._conn is None:
                return None
            cur = self._conn.cursor()
            try:
                row = cur.execute(
                    f"SELECT {', '.join(_RULE_COLUMNS)} FROM alert_promotion_rules WHERE id = ?",
                    (int(rule_id),),
                ).fetchone()
                return _hydrate_rule(row) if row is not None else None
            finally:
                cur.close()

    def create_alert_rule(
        self, *, name: str, event_type: str = "", zone_id: str = "", camera_id: str = "",
        category: str = "", min_dwell_time: float | None = None, target_severity: str = "warning",
        enabled: bool = True, add_tags: str = "",
    ) -> dict[str, Any]:
        """Insert a new alert promotion rule and return the hydrated record."""
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("Rule name is required")
        sev = _validate_severity(target_severity)
        dwell = float(min_dwell_time) if min_dwell_time is not None else None
        params = (
            clean_name, 1 if enabled else 0, str(event_type or "").strip(),
            str(zone_id or "").strip(), str(camera_id or "").strip(),
            str(category or "").strip(), dwell, sev, str(add_tags or "").strip(),
        )
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database connection is closed")
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO alert_promotion_rules "
                    "(name, enabled, event_type, zone_id, camera_id, category, min_dwell_time, target_severity, add_tags) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    params,
                )
                rule_id = int(cur.lastrowid)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()
        return self.get_alert_rule(rule_id) or {"id": rule_id, "name": clean_name}

    def update_alert_rule(self, rule_id: int, **updates: Any) -> dict[str, Any] | None:
        """Update mutable fields of an existing alert promotion rule."""
        sets: list[str] = []
        params: list[Any] = []
        for key, val in updates.items():
            if key not in _UPDATABLE_RULE_FIELDS:
                continue
            if key == "name":
                clean = str(val or "").strip()
                if not clean:
                    raise ValueError("Rule name cannot be empty")
                val = clean
            elif key == "target_severity":
                val = _validate_severity(val)
            elif key == "enabled":
                val = 1 if val else 0
            elif key == "min_dwell_time":
                val = float(val) if val is not None else None
            else:
                val = str(val or "").strip()
            sets.append(f"{key} = ?")
            params.append(val)
        if not sets:
            return self.get_alert_rule(rule_id)
        sets.append("updated_at = CURRENT_TIMESTAMP")
        params.append(int(rule_id))
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database connection is closed")
            cur = self._conn.cursor()
            try:
                cur.execute(f"UPDATE alert_promotion_rules SET {', '.join(sets)} WHERE id = ?", params)
                changed = cur.rowcount
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()
        return self.get_alert_rule(rule_id) if changed > 0 else None

    def delete_alert_rule(self, rule_id: int) -> bool:
        """Delete an alert promotion rule by id."""
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM alert_promotion_rules WHERE id = ?", (int(rule_id),))
                deleted = cur.rowcount > 0
                self._conn.commit()
                return deleted
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def get_alert_policy(self) -> dict[str, Any]:
        """Return the singleton global alert policy settings (with defaults if unset)."""
        with self._lock:
            if self._conn is None:
                return _default_policy()
            cur = self._conn.cursor()
            try:
                row = cur.execute(
                    "SELECT dwell_override, alert_sensitivity, quiet_hours_json, extra_json, updated_at "
                    "FROM alert_policy_settings WHERE id = 1"
                ).fetchone()
                return _hydrate_policy(row)
            finally:
                cur.close()

    def update_alert_policy(
        self, *, dwell_override: Any = _UNSET, alert_sensitivity: float | None = None,
        quiet_hours: Any = _UNSET, extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Upsert singleton global alert policy settings and return the updated dict."""
        cur_pol = self.get_alert_policy()
        new_dwell = cur_pol["dwell_override"] if dwell_override is _UNSET else (
            float(dwell_override) if dwell_override is not None else None
        )
        new_sens = cur_pol["alert_sensitivity"] if alert_sensitivity is None else max(0.0, float(alert_sensitivity))
        new_quiet = cur_pol["quiet_hours"] if quiet_hours is _UNSET else quiet_hours
        new_extra = {**cur_pol["extra"], **extra} if isinstance(extra, dict) else cur_pol["extra"]
        params = (
            new_dwell, new_sens,
            json.dumps(new_quiet) if new_quiet is not None else None,
            json.dumps(new_extra),
        )
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database connection is closed")
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO alert_policy_settings "
                    "(id, dwell_override, alert_sensitivity, quiet_hours_json, extra_json, updated_at) "
                    "VALUES (1, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(id) DO UPDATE SET dwell_override = excluded.dwell_override, "
                    "alert_sensitivity = excluded.alert_sensitivity, quiet_hours_json = excluded.quiet_hours_json, "
                    "extra_json = excluded.extra_json, updated_at = CURRENT_TIMESTAMP",
                    params,
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()
        return self.get_alert_policy()
