"""Unit and API tests for Step 2 Milestone 1: Category SSOT, Boot Migration, Preset Export/Import, and Validation."""

import base64
import json
import os
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import numpy as np

from dashboard.dependencies import (
    get_active_learning_mgr,
    get_camera_pool,
    get_db,
    get_enrollment_mgr,
    get_rsac_mgr,
    set_shutting_down,
)
from dashboard.routers import (
    analytics_router,
    categories_router,
    review_router,
    rsac_router,
    tagging_router,
)
from dashboard.services.category_service import (
    delete_category_guarded,
    ensure_known_categories,
    ensure_known_category,
    export_categories,
    import_categories,
)
from intelligent_tracker.analytics.zone_stats import _evaluate_zone_access_events
from intelligent_tracker.category_registry import (
    DEFAULT_CUSTOM_CATEGORIES,
    LEGACY_DEMO_CATEGORY_IDS,
    is_valid_category_slug,
    map_detector_label_to_category,
    normalize_category_slug,
)
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.rsac import RSACManager


def _make_db(tmp_dir: str, name: str = "test.db") -> TrackerDB:
    return TrackerDB(db_path=os.path.join(tmp_dir, name))


def _seed_legacy_fixture(db_path: str) -> None:
    """Populate an existing SQLite DB with legacy demo rows, references, and custom edits."""
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT OR REPLACE INTO custom_categories (id, name, color, badge_icon, description) VALUES (?, ?, ?, ?, ?)",
        [
            ("family_car", "Family Car", "#10B981", "car", ""),
            ("delivery_truck", "Delivery Truck", "#F59E0B", "truck", ""),
            ("cleaning_crew", "Cleaning Crew", "#8B5CF6", "sparkles", ""),
            ("guard_dog", "Guard Dog", "#EC4899", "shield", ""),
            ("vip", "VIP Resident", "#6366F1", "star", "untouched"),
            ("pet", "My Custom Pet", "#06B6D4", "🐶", "edited by user"),
        ],
    )
    conn.execute("INSERT OR IGNORE INTO pet_whitelist (category_or_label, notes) VALUES ('guard_dog', 'old')")
    conn.execute("INSERT INTO entities (name, category) VALUES ('Van 1', 'delivery_truck')")
    conn.execute("INSERT INTO entities (name, category) VALUES ('Alex', 'Contractor')")
    conn.execute("INSERT INTO entities (name, category) VALUES ('Bad', 'bad!cat')")
    conn.execute(
        "INSERT INTO rsac_zone_rules (camera_id, zone_id, allowed_categories_json) VALUES (?, ?, ?)",
        ("cam_01", "vault", json.dumps(["cleaning_crew"])),
    )
    conn.commit()
    conn.close()


class TestCategoryRegistryAndMigration(unittest.TestCase):
    """Verify universal default categories, legacy migration, slug normalization, and COCO mapping."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        set_shutting_down(False)

    def test_fresh_db_seeds_universal_defaults_without_legacy_demos(self) -> None:
        db = _make_db(self._tmp.name, "fresh.db")
        self.addCleanup(db.close)
        cats = {c["id"] for c in db.get_custom_categories()}
        expected = {c["id"] for c in DEFAULT_CUSTOM_CATEGORIES}
        self.assertEqual(cats, expected)
        for legacy in LEGACY_DEMO_CATEGORY_IDS:
            self.assertNotIn(legacy, cats)
        self.assertNotIn("guard_dog", set(db.get_pet_whitelist()))

    def test_legacy_migration_prunes_unreferenced_preserves_referenced_and_is_idempotent(self) -> None:
        db_path = os.path.join(self._tmp.name, "legacy.db")
        TrackerDB(db_path=db_path).close()
        _seed_legacy_fixture(db_path)

        db1 = TrackerDB(db_path=db_path)
        self.addCleanup(db1.close)
        cats = {c["id"]: c for c in db1.get_custom_categories()}
        self.assertNotIn("family_car", cats)
        self.assertNotIn("guard_dog", cats)
        self.assertNotIn("guard_dog", set(db1.get_pet_whitelist()))
        self.assertIn("delivery_truck", cats)
        self.assertIn("cleaning_crew", cats)
        self.assertIn("contractor", cats)
        self.assertNotIn("bad!cat", cats)
        self.assertEqual(cats["vip"]["name"], "VIP")
        self.assertEqual(cats["vip"]["badge_icon"], "⭐")
        self.assertEqual(cats["pet"]["name"], "My Custom Pet")
        self.assertEqual(cats["pet"]["badge_icon"], "🐶")

        db1.close()
        db2 = TrackerDB(db_path=db_path)
        self.addCleanup(db2.close)
        self.assertEqual({c["id"] for c in db2.get_custom_categories()}, set(cats.keys()))

    def test_slug_normalization_and_coco_mapping(self) -> None:
        self.assertEqual(normalize_category_slug("  VIP Guest.1 "), "vip_guest_1")
        self.assertTrue(is_valid_category_slug("vip_guest-1"))
        self.assertFalse(is_valid_category_slug("_bad"))
        self.assertFalse(is_valid_category_slug("bad!slug"))
        self.assertFalse(is_valid_category_slug("a" * 49))

        self.assertEqual(map_detector_label_to_category("person"), "person")
        self.assertEqual(map_detector_label_to_category("mock_person"), "person")
        self.assertEqual(map_detector_label_to_category("truck"), "vehicle")
        self.assertEqual(map_detector_label_to_category("backpack"), "bag_parcel")
        self.assertEqual(map_detector_label_to_category("dog"), "pet")
        self.assertEqual(map_detector_label_to_category("laptop"), "asset")
        self.assertEqual(map_detector_label_to_category(""), "object")

    def test_zone_stats_uses_coco_fallback_without_overwriting_explicit_category(self) -> None:
        bus = MagicMock()
        rsac = MagicMock()
        rsac.evaluate_access.return_value = SimpleNamespace(allowed=True, is_pet_suppressed=False, reason="ok", severity="info")
        z_ev = SimpleNamespace(zone_id="z1", track_id=1, event_type="enter")

        _evaluate_zone_access_events(z_ev, SimpleNamespace(label="truck", entity_id=None), "c1", bus, rsac, None, None, 1.0)
        self.assertEqual(rsac.evaluate_access.call_args.kwargs["entity_category"], "vehicle")

        _evaluate_zone_access_events(
            z_ev, SimpleNamespace(label="person", entity_category="vip", entity_id=7), "c1", bus, rsac, None, None, 2.0
        )
        self.assertEqual(rsac.evaluate_access.call_args.kwargs["entity_category"], "vip")


class TestCategoryServiceAndRoutes(unittest.TestCase):
    """Verify category validation, preset export/import, guarded delete, and HTTP endpoints."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = _make_db(self._tmp.name, "api.db")
        self.addCleanup(self.db.close)
        self.rsac = RSACManager(db=self.db)

        self.app = FastAPI()
        for router in (categories_router, analytics_router, review_router, tagging_router, rsac_router):
            self.app.include_router(router)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_rsac_mgr] = lambda: self.rsac
        self.app.dependency_overrides[get_camera_pool] = lambda: None
        self.app.dependency_overrides[get_enrollment_mgr] = lambda: MagicMock()
        self.app.dependency_overrides[get_active_learning_mgr] = lambda: MagicMock()
        self.client = TestClient(self.app)

    def test_ensure_known_category_and_guarded_delete(self) -> None:
        self.assertEqual(ensure_known_category(self.rsac, ""), "person")
        self.assertEqual(ensure_known_category(self.rsac, " Staff "), "staff")
        self.assertEqual(ensure_known_category(self.rsac, "object"), "asset")
        with self.assertRaises(HTTPException) as ctx:
            ensure_known_category(self.rsac, "unknown_role")
        self.assertEqual(ctx.exception.status_code, 422)
        with self.assertRaises(HTTPException):
            ensure_known_categories(self.rsac, ["staff", "missing_role"])

        with self.assertRaises(HTTPException) as ctx_person:
            delete_category_guarded(self.rsac, self.db, "person")
        self.assertEqual(ctx_person.exception.status_code, 409)

        self.rsac.register_category("vendor", "Vendor")
        self.db.add_entity("Acme Driver", category="vendor")
        with self.assertRaises(HTTPException) as ctx_ref:
            delete_category_guarded(self.rsac, self.db, "vendor")
        self.assertEqual(ctx_ref.exception.status_code, 409)

    def test_export_and_import_merge_replace_and_limits(self) -> None:
        exported = export_categories(self.rsac)
        self.assertEqual(exported["format"], "intelligent-tracker.categories")
        self.assertEqual(exported["version"], 1)
        self.assertEqual(len(exported["categories"]), 9)

        self.db.add_entity("Guard", category="staff")
        self.rsac.set_rule("cam_1", "z_1", allowed_categories=["vip"])
        merged = import_categories(
            self.rsac, self.db, [{"id": "courier", "name": "Courier"}, {"id": "bad!id", "name": "Bad"}], mode="merge"
        )
        self.assertEqual(merged["imported"], 1)
        self.assertEqual(merged["skipped"], [{"id": "bad!id", "reason": "invalid_slug"}])

        replaced = import_categories(self.rsac, self.db, [{"id": "courier", "name": "Courier"}], mode="replace")
        remaining = {c["id"] for c in replaced["categories"]}
        self.assertIn("person", remaining)
        self.assertIn("staff", remaining)
        self.assertIn("vip", remaining)
        self.assertIn("courier", remaining)
        self.assertNotIn("asset", remaining)

        with self.assertRaises(HTTPException) as ctx_max:
            import_categories(self.rsac, self.db, [{"id": f"c_{i}", "name": f"C {i}"} for i in range(201)], mode="merge")
        self.assertEqual(ctx_max.exception.status_code, 422)

    def test_category_routes_export_import_and_guarded_delete(self) -> None:
        with patch("dashboard.routers.categories._reload_galleries"):
            self.assertEqual(len(self.client.get("/api/rsac/categories").json()), 9)
            bad = self.client.post("/api/rsac/categories", json={"id": "bad!slug", "name": "Bad"})
            self.assertEqual(bad.status_code, 422)
            ok = self.client.post("/api/rsac/categories", json={"id": "auditor", "name": "Auditor"})
            self.assertEqual(ok.status_code, 200)
            exp = self.client.get("/api/rsac/categories/export")
            self.assertEqual(exp.status_code, 200)
            self.assertEqual(exp.json()["format"], "intelligent-tracker.categories")
            imp = self.client.post(
                "/api/rsac/categories/import",
                json={"mode": "merge", "categories": [{"id": "inspector", "name": "Inspector"}]},
            )
            self.assertEqual(imp.status_code, 200)
            self.assertEqual(imp.json()["imported"], 1)
            self.assertEqual(self.client.delete("/api/rsac/categories/person").status_code, 409)
            self.assertEqual(self.client.delete("/api/rsac/categories/inspector").status_code, 200)

    def test_write_routes_reject_unknown_categories_with_422(self) -> None:
        ok, buf = cv2.imencode(".jpg", np.zeros((16, 16, 3), dtype=np.uint8))
        self.assertTrue(ok)
        b64 = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
        self.assertEqual(self.client.post("/entities", json={"name": "X", "category": "ghost_cat"}).status_code, 422)
        self.assertEqual(
            self.client.post("/api/enroll", json={"name": "X", "category": "ghost_cat", "crop_base64": b64}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post("/api/review/1/enroll-new", json={"name": "X", "category": "ghost_cat"}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post("/api/active-learning/1/enroll-new", json={"name": "X", "category": "ghost_cat"}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post("/api/tag/commit", json={"entity_name": "X", "category": "ghost_cat", "crop_base64": b64}).status_code,
            422,
        )
        with patch("dashboard.routers.analytics.get_active_stream_manager", return_value=MagicMock(rsac_manager=self.rsac)):
            self.assertEqual(
                self.client.post("/tag", json={"entity_name": "X", "category": "ghost_cat", "bbox": [0, 0, 10, 10]}).status_code,
                422,
            )
        self.assertEqual(
            self.client.post("/api/rsac/rules", json={"camera_id": "c1", "zone_id": "z1", "allowed_categories": ["ghost_cat"]}).status_code,
            422,
        )


if __name__ == "__main__":
    unittest.main()
