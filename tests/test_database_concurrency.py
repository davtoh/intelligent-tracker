"""
Concurrency, Connection Coordination & Router DB Encapsulation Tests.

Verifies:
- ``SQLiteConnectionCoordinator`` path-keyed lock sharing, ``:memory:`` isolation,
  WAL/busy_timeout/synchronous PRAGMA setup, and refcounted last-close checkpointing.
- Idempotent ``TrackerDB.close()`` and ``__del__()`` behavior.
- Multi-instance multi-threaded SQLite write/read stress with zero ``database is locked`` errors.
- ``AnalyticsMixin.query_sighting_counts()`` and ``get_analytics_summary()``.
- Zero direct ``TrackerDB()`` calls in ``dashboard/routers/`` and zero raw ``db._conn``
  accesses in ``dashboard/routers/analytics.py``.
"""

import ast
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import get_db
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.repositories.connection import SQLiteConnectionCoordinator


ROOT_DIR = Path(__file__).resolve().parents[1]


class TestSQLiteConnectionCoordinator(unittest.TestCase):
    """Unit tests for path-keyed locks, PRAGMAs, and refcounted closes."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="tracker_conn_coord_")
        self.addCleanup(self.temp_dir.cleanup)
        self.coordinator = SQLiteConnectionCoordinator()

    def test_path_normalization_shares_lock_and_memory_isolates(self):
        """Equivalent file paths share one RLock; :memory: paths get distinct locks."""
        raw_a = os.path.join(self.temp_dir.name, "sub", "..", "shared.db")
        raw_b = os.path.abspath(os.path.join(self.temp_dir.name, "shared.db"))

        lock_a = self.coordinator.get_path_lock(raw_a)
        lock_b = self.coordinator.get_path_lock(raw_b)
        self.assertIs(lock_a, lock_b)

        mem_a = self.coordinator.get_path_lock(":memory:")
        mem_b = self.coordinator.get_path_lock(":memory:")
        self.assertIsNot(mem_a, mem_b)
        self.assertEqual(self.coordinator.get_ref_count(":memory:"), 0)

    def test_pragmas_and_idempotent_refcounted_close(self):
        """PRAGMAs apply cleanly and wal_checkpoint runs only when last instance closes."""
        db_path = os.path.join(self.temp_dir.name, "refcount.db")
        db1 = TrackerDB(db_path, coordinator=self.coordinator)
        db2 = TrackerDB(db_path, coordinator=self.coordinator)
        self.addCleanup(db1.close)
        self.addCleanup(db2.close)

        self.assertIs(db1._lock, db2._lock)
        self.assertEqual(self.coordinator.get_ref_count(db_path), 2)

        with db1._lock:
            cur = db1._conn.cursor()
            try:
                journal_mode = cur.execute("PRAGMA journal_mode;").fetchone()[0]
                busy_timeout = cur.execute("PRAGMA busy_timeout;").fetchone()[0]
                foreign_keys = cur.execute("PRAGMA foreign_keys;").fetchone()[0]
                synchronous = cur.execute("PRAGMA synchronous;").fetchone()[0]
            finally:
                cur.close()

        self.assertEqual(str(journal_mode).lower(), "wal")
        self.assertEqual(int(busy_timeout), 10000)
        self.assertEqual(int(foreign_keys), 1)
        self.assertEqual(int(synchronous), 1)  # NORMAL = 1

        # Closing db1 decrements refcount to 1 and leaves db2 fully functional.
        db1.close()
        db1.close()  # Idempotent second close must not decrement again
        db1.__del__()  # Idempotent __del__ must not decrement again
        self.assertEqual(self.coordinator.get_ref_count(db_path), 1)

        eid = db2.add_entity(name="Still Alive")
        self.assertGreater(eid, 0)

        # Closing final instance drops refcount to 0.
        db2.close()
        self.assertEqual(self.coordinator.get_ref_count(db_path), 0)


class TestMultiInstanceDatabaseConcurrency(unittest.TestCase):
    """Stress tests across independent TrackerDB instances sharing one SQLite file."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="tracker_db_stress_")
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = os.path.join(self.temp_dir.name, "stress.db")
        self.coordinator = SQLiteConnectionCoordinator()

    def test_four_concurrent_trackerdb_instances_zero_lock_errors(self):
        """Four simultaneous TrackerDB instances write/read without database is locked."""
        num_workers = 4
        items_per_worker = 15
        barrier = threading.Barrier(num_workers)
        errors: list[BaseException] = []
        errors_lock = threading.Lock()

        def worker(worker_idx: int) -> None:
            db: TrackerDB | None = None
            try:
                barrier.wait(timeout=10.0)
                db = TrackerDB(self.db_path, coordinator=self.coordinator)
                for item_idx in range(items_per_worker):
                    name = f"Worker{worker_idx}-Entity{item_idx}"
                    eid = db.add_entity(name=name, category="person")
                    db.update_entity(eid, notes=f"updated-{worker_idx}-{item_idx}")
                    db.add_sighting(
                        entity_id=eid,
                        track_id=worker_idx * 100 + item_idx,
                        source=f"cam_{worker_idx}",
                        zone_id="lobby",
                    )
                    counts = db.query_sighting_counts([eid])
                    if counts.get(eid) != 1:
                        raise AssertionError(f"Expected count 1 for {eid}, got {counts}")
            except BaseException as exc:
                with errors_lock:
                    errors.append(exc)
            finally:
                if db is not None:
                    db.close()

        threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(num_workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30.0)

        self.assertEqual(errors, [], f"Concurrent TrackerDB errors: {errors}")
        self.assertEqual(self.coordinator.get_ref_count(self.db_path), 0)

        verifier = TrackerDB(self.db_path, coordinator=self.coordinator)
        self.addCleanup(verifier.close)
        summary = verifier.get_analytics_summary()
        expected_total = num_workers * items_per_worker
        self.assertEqual(summary["total_entities"], expected_total)
        self.assertEqual(summary["total_sightings"], expected_total)
        self.assertEqual(summary["sightings_by_zone"].get("lobby"), expected_total)
        self.assertEqual(len(summary["sightings_by_entity"]), expected_total)
        self.assertEqual(verifier.query_sighting_counts([]), {})


class TestRouterDatabaseEncapsulation(unittest.TestCase):
    """Verify routers use repository methods and get_db DI without raw SQL/TrackerDB()."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="tracker_router_db_")
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = os.path.join(self.temp_dir.name, "router_test.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)

    def test_ast_zero_direct_trackerdb_calls_or_raw_conn_in_routers(self):
        """Routers must not instantiate TrackerDB() directly or touch db._conn."""
        routers_dir = ROOT_DIR / "dashboard" / "routers"
        direct_calls: list[str] = []
        raw_conn_access: list[str] = []

        for py_file in sorted(routers_dir.glob("*.py")):
            tree = ast.parse(py_file.read_bytes(), filename=str(py_file))
            rel = py_file.relative_to(ROOT_DIR).as_posix()
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "TrackerDB"
                ):
                    direct_calls.append(f"{rel}:{node.lineno}")
                if (
                    py_file.name == "analytics.py"
                    and isinstance(node, ast.Attribute)
                    and node.attr in {"_conn", "_lock"}
                ):
                    raw_conn_access.append(f"{rel}:{node.lineno} -> .{node.attr}")

        self.assertEqual(direct_calls, [], f"Direct TrackerDB() calls in routers: {direct_calls}")
        self.assertEqual(
            raw_conn_access,
            [],
            f"Raw db._conn/_lock access in analytics router: {raw_conn_access}",
        )

    def test_topology_journey_search_uses_injected_get_db(self):
        """GET /api/journey/search resolves DB via FastAPI get_db dependency."""
        eid = self.db.add_entity(name="Journey Subject", category="vip")
        self.db.add_sighting(
            entity_id=eid,
            track_id=12,
            source="cam_north",
            timestamp="2026-11-12 10:00:00",
            zone_id="gate",
        )

        app.dependency_overrides[get_db] = lambda: self.db
        self.addCleanup(lambda: app.dependency_overrides.pop(get_db, None))

        client = TestClient(app)
        resp = client.get(f"/api/journey/search?entity_id={eid}")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["entity_name"], "Journey Subject")
        self.assertGreaterEqual(payload["total_hops"], 1)

    def test_analytics_list_entities_uses_query_sighting_counts(self):
        """GET /entities computes appearance_count via repository method."""
        eid = self.db.add_entity(name="Counted Guest", category="visitor")
        self.db.add_sighting(entity_id=eid, track_id=1, source="cam_1")
        self.db.add_sighting(entity_id=eid, track_id=2, source="cam_2")

        class _StubMgr:
            def __init__(self, db):
                self.db = db

        with patch(
            "dashboard.routers.analytics.get_active_stream_manager",
            return_value=_StubMgr(self.db),
        ):
            client = TestClient(app)
            resp = client.get("/entities")

        self.assertEqual(resp.status_code, 200)
        entities = resp.json()
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["name"], "Counted Guest")
        self.assertEqual(entities[0]["appearance_count"], 2)


if __name__ == "__main__":
    unittest.main()

