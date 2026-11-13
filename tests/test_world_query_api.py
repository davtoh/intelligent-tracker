"""Integration tests for FastAPI World Intelligence & Query endpoints."""

import os
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import bind_app_state, clear_app_state, get_world_query_engine
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.memory import (
    ConfidenceEngine,
    MockSemanticProvider,
    WorldQueryEngine,
)
from intelligent_tracker.world import CameraNode, WorldEntity, WorldGraph


class TestWorldQueryApi(unittest.TestCase):
    """Verify /api/world/query, /api/world/confidence/{id}, and /api/world/timeline."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = os.path.join(self.tmpdir.name, "world_api.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)

        self.now = time.time()
        self.alice_id = self.db.add_entity("Alice", category="staff")
        self.bob_id = self.db.add_entity("Bob", category="visitor")
        self.conf_engine = ConfidenceEngine(db=self.db, decay_grace_s=10.0, decay_half_life_s=60.0)
        self.conf_engine.record_observation(
            entity_id=self.alice_id,
            visual_similarity=0.88,
            face_score=0.90,
            body_score=0.84,
            camera_id="cam_01",
            zone_id="lobby",
            timestamp=self.now - 5.0,
        )
        self.db.index_timeline_event(
            event_type="sighting",
            entity_id=self.alice_id,
            entity_name="Alice",
            category="staff",
            camera_id="cam_01",
            zone_id="lobby",
            timestamp=self.now - 5.0,
            confidence=0.91,
            title="Alice sighted",
            summary="Alice entered lobby on cam_01 carrying badge",
        )
        self.db.index_timeline_event(
            event_type="rsac_violation",
            entity_id=self.bob_id,
            entity_name="Bob",
            category="visitor",
            camera_id="cam_02",
            zone_id="vault",
            timestamp=self.now - 2.0,
            confidence=0.77,
            title="Unauthorized vault access",
            summary="Bob entered restricted vault zone on cam_02",
        )

        self.world_graph = WorldGraph()
        self.world_graph.register_camera(CameraNode(camera_id="cam_01", name="Lobby Cam"))
        self.world_graph.upsert_entity(
            WorldEntity(
                entity_id=self.alice_id,
                name="Alice",
                category="staff",
                confidence=0.91,
                camera_tracks={"cam_01": 101},
                active_zones={"cam_01": ["lobby"]},
                last_seen=self.now - 5.0,
            )
        )
        bind_app_state(app, db=self.db)
        self.addCleanup(lambda: clear_app_state(app))
        self.addCleanup(lambda: app.dependency_overrides.clear())
        self.client = TestClient(app)

    def test_post_world_query_auto_di_and_whitespace_guard(self) -> None:
        """POST /api/world/query resolves answers from app.state.db and rejects blank input."""
        resp = self.client.post("/api/world/query", json={"query": "Where was Alice?"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["provider"], "local_deterministic")
        self.assertIn("Alice", data["answer"])
        self.assertGreaterEqual(len(data["citations"]), 1)
        self.assertEqual(data["citations"][0]["camera_id"], "cam_01")

        bad = self.client.post("/api/world/query", json={"query": "   "})
        self.assertEqual(bad.status_code, 400)

    def test_post_world_query_with_dependency_override_and_filters(self) -> None:
        """POST /api/world/query supports custom WorldQueryEngine overrides and structured filters."""
        mock_provider = MockSemanticProvider(response="Mock summary: Bob breached vault.")
        custom_engine = WorldQueryEngine(
            db=self.db,
            confidence_engine=self.conf_engine,
            world_graph=self.world_graph,
            provider=mock_provider,
        )
        app.dependency_overrides[get_world_query_engine] = lambda: custom_engine

        resp = self.client.post(
            "/api/world/query",
            json={
                "query": "Show vault breach",
                "camera_id": "cam_02",
                "event_type": "rsac_violation",
                "limit": 5,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["provider"], "mock")
        self.assertEqual(data["answer"], "Mock summary: Bob breached vault.")
        self.assertEqual(len(data["citations"]), 1)
        self.assertEqual(data["citations"][0]["entity_name"], "Bob")

    def test_get_entity_confidence_branches(self) -> None:
        """GET /api/world/confidence/{id} handles recorded, unrecorded, decayed, and missing entities."""
        recorded = self.client.get(f"/api/world/confidence/{self.alice_id}")
        self.assertEqual(recorded.status_code, 200)
        r_data = recorded.json()
        self.assertTrue(r_data["has_confidence_state"])
        self.assertEqual(r_data["entity_name"], "Alice")
        self.assertGreater(r_data["confidence"], 0.7)

        decayed = self.client.get(
            f"/api/world/confidence/{self.alice_id}",
            params={"timestamp": self.now + 500.0},
        )
        self.assertEqual(decayed.status_code, 200)
        self.assertLess(decayed.json()["confidence"], r_data["confidence"])

        cold = self.client.get(f"/api/world/confidence/{self.bob_id}")
        self.assertEqual(cold.status_code, 200)
        self.assertFalse(cold.json()["has_confidence_state"])
        self.assertEqual(cold.json()["entity_name"], "Bob")

        missing = self.client.get("/api/world/confidence/999999")
        self.assertEqual(missing.status_code, 404)

    def test_get_world_timeline_fts_and_filters(self) -> None:
        """GET /api/world/timeline supports q/query FTS search and structured filters."""
        resp = self.client.get("/api/world/timeline", params={"q": "badge"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["events"][0]["entity_name"], "Alice")

        filtered = self.client.get(
            "/api/world/timeline",
            params={"query": "vault", "camera_id": "cam_02", "event_type": "rsac_violation"},
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["count"], 1)
        self.assertEqual(filtered.json()["events"][0]["zone_id"], "vault")

        all_events = self.client.get("/api/world/timeline", params={"limit": 10})
        self.assertEqual(all_events.status_code, 200)
        self.assertEqual(all_events.json()["count"], 2)


if __name__ == "__main__":
    unittest.main()

