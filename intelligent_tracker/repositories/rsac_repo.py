"""
Role-Based Spatial Access Control (RSAC) and Pet Whitelist Repository Mixin.

Manages camera zone permission rules, category restrictions, schedule windows,
and domestic pet detection whitelist entries.
"""

import json
import time
from typing import Optional, Dict, Any, List


_UPSERT_RSAC_RULE_SQL = """
INSERT INTO rsac_zone_rules (
    camera_id, zone_id, allowed_categories_json, denied_categories_json,
    schedules_json, entity_overrides_json, alarm_on_breach, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(camera_id, zone_id) DO UPDATE SET
    allowed_categories_json = excluded.allowed_categories_json,
    denied_categories_json = excluded.denied_categories_json,
    schedules_json = excluded.schedules_json,
    entity_overrides_json = excluded.entity_overrides_json,
    alarm_on_breach = excluded.alarm_on_breach,
    updated_at = excluded.updated_at
"""


class RsacMixin:
    """Provides RSAC zone rules and pet whitelist persistence."""

    def get_rsac_rules(self, camera_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List RSAC zone permission rules, optionally filtered by camera."""
        query = "SELECT * FROM rsac_zone_rules"
        params = []
        if camera_id:
            query += " WHERE camera_id = ?"
            params.append(camera_id)
        query += " ORDER BY camera_id, zone_id ASC"

        with self._lock:
            if self._conn is None:
                return []
            cur = self._conn.cursor()
            try:
                cur.execute(query, params)
                results = []
                for r in cur.fetchall():
                    d = dict(r)
                    d["allowed_categories"] = json.loads(d["allowed_categories_json"])
                    d["denied_categories"] = json.loads(d["denied_categories_json"])
                    d["schedules"] = json.loads(d["schedules_json"])
                    d["entity_overrides"] = json.loads(d["entity_overrides_json"])
                    d["alarm_on_breach"] = bool(d["alarm_on_breach"])
                    results.append(d)
                return results
            finally:
                cur.close()

    def get_rsac_rule(self, camera_id: str, zone_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve single RSAC rule for a camera zone."""
        with self._lock:
            if self._conn is None:
                return None
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM rsac_zone_rules WHERE camera_id = ? AND zone_id = ?", (camera_id, zone_id))
                row = cur.fetchone()
                if not row:
                    return None
                d = dict(row)
                d["allowed_categories"] = json.loads(d["allowed_categories_json"])
                d["denied_categories"] = json.loads(d["denied_categories_json"])
                d["schedules"] = json.loads(d["schedules_json"])
                d["entity_overrides"] = json.loads(d["entity_overrides_json"])
                d["alarm_on_breach"] = bool(d["alarm_on_breach"])
                return d
            finally:
                cur.close()

    def set_rsac_rule(
        self,
        camera_id: str,
        zone_id: str,
        allowed_categories: List[str],
        denied_categories: Optional[List[str]] = None,
        schedules: Optional[List[Dict[str, Any]]] = None,
        entity_overrides: Optional[Dict[str, str]] = None,
        alarm_on_breach: bool = True,
    ) -> bool:
        """Create or update RSAC permissions for a zone."""
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        params = (
            camera_id, zone_id, json.dumps(allowed_categories or []), json.dumps(denied_categories or []),
            json.dumps(schedules or []), json.dumps(entity_overrides or {}), 1 if alarm_on_breach else 0, now, now,
        )
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute(_UPSERT_RSAC_RULE_SQL, params)
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def delete_rsac_rule(self, camera_id: str, zone_id: str) -> bool:
        """Delete RSAC rule for a zone."""
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM rsac_zone_rules WHERE camera_id = ? AND zone_id = ?", (camera_id, zone_id))
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def get_pet_whitelist(self) -> List[str]:
        """List all whitelisted pet labels and categories."""
        with self._lock:
            if self._conn is None:
                return []
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT category_or_label FROM pet_whitelist ORDER BY id ASC")
                return [r[0] for r in cur.fetchall()]
            finally:
                cur.close()

    def add_pet_whitelist(self, label: str, notes: str = "") -> bool:
        """Add label or category to pet whitelist."""
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "INSERT OR IGNORE INTO pet_whitelist (category_or_label, notes) VALUES (?, ?)",
                    (label.strip().lower(), notes.strip()),
                )
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def remove_pet_whitelist(self, label: str) -> bool:
        """Remove label from pet whitelist."""
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM pet_whitelist WHERE category_or_label = ?", (label.strip().lower(),))
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

