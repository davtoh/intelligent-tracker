"""Unit & Integration Tests for EventFTSIndex, Semantic Providers, PrivacyMaskingFilter, and WorldQueryEngine."""

import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events import (
    EntityIdentifiedEvent,
    EventBus,
    PetActivityEvent,
    RSACViolationEvent,
    TripwireCrossEvent,
    ZoneEvent,
)
from intelligent_tracker.memory import (
    ConfidenceEngine,
    EventFTSIndex,
    GeminiSemanticProvider,
    LocalDeterministicProvider,
    MockSemanticProvider,
    PrivacyMaskingFilter,
    SemanticProvider,
    WorldQueryEngine,
)
from intelligent_tracker.pipeline import PipelineEngine
from intelligent_tracker.world import CameraNode, WorldEntity, WorldGraph, ZoneNode
from intelligent_tracker.world.events import EntityStateChangedEvent


class TestEventFTSIndex(unittest.TestCase):
    """Verify EventBus ingestion, clip captions, cooldowns, and FK resilience."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = os.path.join(self.tmpdir.name, "fts_index.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)
        self.alice_id = self.db.add_entity("Alice", "staff")
        self.bus = EventBus(capacity=100)
        self.bus.start()
        self.addCleanup(self.bus.stop)
        self.indexer = EventFTSIndex(self.db, event_bus=self.bus)
        self.addCleanup(self.indexer.detach)

    def _publish_sample_events(self, now: float) -> None:
        events = [
            EntityIdentifiedEvent(
                camera_id="cam_01", track_id=1, entity_id=self.alice_id,
                name="Alice", category="staff", similarity=0.91, zone_id="lobby", timestamp=now,
            ),
            ZoneEvent(
                camera_id="cam_01", zone_id="lobby", track_id=1, action="enter",
                entity_id=self.alice_id, entity_name="Alice", entity_category="staff", timestamp=now + 1,
            ),
            TripwireCrossEvent(
                camera_id="cam_01", tripwire_id="main_door", track_id=1, direction="in",
                entity_id=self.alice_id, entity_name="Alice", entity_category="staff", timestamp=now + 2,
            ),
            RSACViolationEvent(
                camera_id="cam_02", zone_id="server_room", track_id=2, entity_id=None,
                entity_name="Guest", entity_category="visitor",
                reason="Unauthorized visitor in server room", severity="critical", timestamp=now + 3,
            ),
            PetActivityEvent(
                camera_id="cam_01", zone_id="porch", track_id=3, entity_id=None,
                entity_name="Rex", entity_category="pet", timestamp=now + 4,
            ),
            EntityStateChangedEvent(
                camera_id="cam_01", world_entity_id=f"entity:{self.alice_id}",
                entity_id=self.alice_id, change_type="updated",
                camera_tracks={"cam_01": 1}, active_zones={"cam_01": ["lobby"]},
                global_xy=(2.5, 4.0), timestamp=now + 5,
                metadata={"entity_name": "Alice", "category": "staff"},
            ),
        ]
        for ev in events:
            self.bus.publish(ev)

    def test_event_bus_ingestion_across_event_types_and_clip_captions(self) -> None:
        """All supported event dataclasses and clip captions index into FTS5 asynchronously."""
        now = 1_700_000_000.0
        self._publish_sample_events(now)
        self.assertTrue(self.bus.wait_until_empty(timeout=3.0))

        self.indexer.index_clip_caption(
            "Alice carrying a brown delivery package near main_door",
            camera_id="cam_01", zone_id="lobby", entity_id=self.alice_id,
            entity_name="Alice", timestamp=now + 6,
        )

        all_events = self.db.search_timeline_events(query="", limit=20)
        self.assertEqual(len(all_events), 7)
        self.assertEqual(len(self.db.search_timeline_events(query="delivery package")), 1)
        self.assertEqual(len(self.db.search_timeline_events(query="", event_type="rsac_violation")), 1)
        self.assertEqual(len(self.db.search_timeline_events(query="", event_type="pet_activity")), 1)
        self.assertEqual(len(self.db.search_timeline_events(query="", event_type="tripwire_cross")), 1)

    def test_synthetic_entity_fk_fallback_and_state_cooldown(self) -> None:
        """Unlinked synthetic entity IDs still index cleanly and cooldown throttles noisy updates."""
        cooldown_indexer = EventFTSIndex(self.db, state_event_cooldown=30.0)
        row_id = cooldown_indexer.handle_event(EntityStateChangedEvent(
            camera_id="cam_01", world_entity_id="entity:999999",
            entity_id=999999, change_type="updated",
            camera_tracks={"cam_01": 8}, active_zones={}, timestamp=1000.0,
        ))
        self.assertIsNotNone(row_id)
        stored = self.db.get_timeline_event(row_id)
        self.assertIsNone(stored["entity_id"])
        self.assertEqual(stored["metadata"]["unlinked_entity_id"], 999999)

        throttled = cooldown_indexer.handle_event(EntityStateChangedEvent(
            camera_id="cam_01", world_entity_id="entity:999999",
            entity_id=999999, change_type="updated",
            camera_tracks={"cam_01": 8}, active_zones={}, timestamp=1005.0,
        ))
        self.assertIsNone(throttled)


class TestWorldQueryEngineAndProviders(unittest.TestCase):
    """Verify offline Q&A, Confidence/WorldGraph fusion, providers, and privacy masking."""

    def _seed_timeline_and_graph(self) -> None:
        self.graph = WorldGraph()
        self.graph.register_camera(CameraNode(camera_id="cam_01", name="Front Lobby", enabled=True))
        self.graph.register_camera(CameraNode(camera_id="cam_02", name="Server Wing", enabled=True))
        self.graph.register_zone(ZoneNode(zone_id="lobby", camera_id="cam_01", name="lobby"))
        self.graph.register_zone(ZoneNode(zone_id="server_room", camera_id="cam_02", name="server_room"))
        self.graph.upsert_entity(WorldEntity(
            entity_id=self.alice_id, name="Alice", category="staff", confidence=0.91,
            camera_tracks={"cam_01": 4}, active_zones={"cam_01": {"lobby"}},
            global_xy=(3.0, 6.0), last_seen=self.now - 10.0,
        ))
        self.indexer = EventFTSIndex(self.db)
        self.indexer.index_sighting(
            entity_id=self.alice_id, entity_name="Alice", category="staff",
            camera_id="cam_01", zone_id="lobby", confidence=0.91, timestamp=self.now - 60.0,
        )
        self.indexer.handle_event(RSACViolationEvent(
            camera_id="cam_02", zone_id="server_room", track_id=9, entity_id=self.bob_id,
            entity_name="Bob", entity_category="visitor",
            reason="Unauthorized visitor in server_room", severity="critical", timestamp=self.now - 120.0,
        ))
        self.indexer.index_clip_caption(
            "Alice carrying a silver laptop into lobby", camera_id="cam_01",
            zone_id="lobby", entity_id=self.alice_id, entity_name="Alice", timestamp=self.now - 20.0,
        )

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db = TrackerDB(os.path.join(self.tmpdir.name, "world_query.db"))
        self.addCleanup(self.db.close)
        self.alice_id = self.db.add_entity("Alice", "staff")
        self.bob_id = self.db.add_entity("Bob", "visitor")
        self.confidence = ConfidenceEngine(db=self.db, decay_grace_s=120.0)
        self.now = 1_700_005_000.0
        self.confidence.record_observation(
            entity_id=self.alice_id, face_score=0.90, body_score=0.84,
            topology_prior=0.30, camera_id="cam_01", zone_id="lobby", timestamp=self.now - 30.0,
        )
        self._seed_timeline_and_graph()
        self.engine = WorldQueryEngine(
            db=self.db, confidence_engine=self.confidence, world_graph=self.graph,
        )

    def test_offline_queries_location_confidence_security_and_time_window(self) -> None:
        """Offline LocalDeterministicProvider answers location, confidence, RSAC, and caption queries."""
        self.assertIsInstance(LocalDeterministicProvider(), SemanticProvider)

        loc_res = self.engine.ask("Where was Alice last seen?", now=self.now)
        self.assertEqual(loc_res.intent, "location")
        self.assertEqual(loc_res.provider, "local_deterministic")
        self.assertFalse(loc_res.fallback_used)
        self.assertIn("Alice", loc_res.answer)
        self.assertIn("lobby", loc_res.answer)
        self.assertGreaterEqual(len(loc_res.citations), 1)
        self.assertEqual(loc_res.entities[0]["live_zones"], ["lobby"])

        conf_res = self.engine.ask("What is Alice confidence score?", now=self.now)
        self.assertEqual(conf_res.intent, "confidence")
        self.assertIn("confidence is", conf_res.answer)
        self.assertGreater(conf_res.entities[0]["confidence"], 0.7)

        sec_res = self.engine.ask("Any RSAC violations in server_room last 1 hour?", now=self.now)
        self.assertEqual(sec_res.intent, "security")
        self.assertEqual(sec_res.parsed_filters["event_type"], "rsac_violation")
        self.assertEqual(sec_res.parsed_filters["zone_id"], "server_room")
        self.assertEqual(len(sec_res.citations), 1)
        self.assertIn("Bob", sec_res.answer)

        cap_res = self.engine.ask("silver laptop", now=self.now)
        self.assertEqual(len(cap_res.citations), 1)
        self.assertIn("silver laptop", cap_res.citations[0]["summary"])

        empty_res = self.engine.ask("quantum unicorn sightings", now=self.now)
        self.assertIn("No matching timeline records", empty_res.answer)

    def test_privacy_masking_filter_strips_crops_paths_and_pii(self) -> None:
        """PrivacyMaskingFilter removes raw media, embeddings, paths, credentials, and PII."""
        guard = PrivacyMaskingFilter(metadata_only=True, anonymize_entities=True)
        sanitized = guard.sanitize_context({
            "entities": [{"entity_id": 5, "entity_name": "Alice Smith", "crop_path": "/tmp/crop.jpg"}],
            "citations": [{
                "summary": "Alert for alice@example.com on rtsp://admin:secret@10.0.0.5/cam1 call 555-123-4567",
                "snapshot_base64": "AAAA",
                "embedding": [0.1, 0.2],
            }],
        })
        ent = sanitized["entities"][0]
        cit = sanitized["citations"][0]
        self.assertEqual(ent["entity_name"], "Entity #5")
        self.assertNotIn("crop_path", ent)
        self.assertNotIn("snapshot_base64", cit)
        self.assertNotIn("embedding", cit)
        self.assertNotIn("alice@example.com", cit["summary"])
        self.assertNotIn("secret", cit["summary"])
        self.assertNotIn("555-123-4567", cit["summary"])
        self.assertIn("[REDACTED_EMAIL]", cit["summary"])
        self.assertIn("[REDACTED_PHONE]", cit["summary"])

    def test_mock_provider_swapping_and_error_fallback(self) -> None:
        """MockSemanticProvider receives sanitized context and falls back cleanly on error."""
        mock = MockSemanticProvider(response="Mock answer: Alice is in lobby.")
        self.engine.set_provider(mock)
        res = self.engine.ask("Where is Alice?", now=self.now)
        self.assertEqual(res.provider, "mock")
        self.assertFalse(res.fallback_used)
        self.assertEqual(res.answer, "Mock answer: Alice is in lobby.")
        self.assertEqual(len(mock.calls), 1)

        failing = MockSemanticProvider(error=RuntimeError("provider offline"))
        self.engine.set_provider(failing)
        fb_res = self.engine.ask("Where is Alice?", now=self.now)
        self.assertTrue(fb_res.fallback_used)
        self.assertEqual(fb_res.provider, "local_deterministic")
        self.assertIn("provider offline", fb_res.fallback_reason or "")
        self.assertIn("Alice", fb_res.answer)

    def test_gemini_provider_unconfigured_and_mocked_http_branches(self) -> None:
        """GeminiSemanticProvider falls back cleanly when unconfigured and works when mocked."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            gemini = GeminiSemanticProvider()
            self.assertFalse(gemini.is_configured)
            self.engine.set_provider(gemini)
            res = self.engine.ask("Where is Alice?", now=self.now)
            self.assertTrue(res.fallback_used)
            self.assertEqual(res.provider, "local_deterministic")
            self.assertIn("GEMINI_API_KEY", res.fallback_reason or "")

        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Gemini: Alice was seen in lobby."}]}}]
        }
        with patch("intelligent_tracker.memory.providers.requests.post", return_value=fake_resp) as post_mock:
            gemini_ok = GeminiSemanticProvider(api_key="test-key", model="gemini-2.5-flash")
            self.assertTrue(gemini_ok.is_configured)
            self.engine.set_provider(gemini_ok)
            ok_res = self.engine.ask("Where is Alice?", now=self.now)
            self.assertFalse(ok_res.fallback_used)
            self.assertEqual(ok_res.provider, "gemini")
            self.assertEqual(ok_res.answer, "Gemini: Alice was seen in lobby.")
            post_mock.assert_called_once()


class TestPipelineMemoryIndexingWiring(unittest.TestCase):
    """Verify PipelineEngine attaches EventFTSIndex to EventBus and detaches on close."""

    def test_pipeline_engine_wires_and_detaches_event_fts_index(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db_path = os.path.join(tmpdir.name, "pipe_mem.db")

        bundle = PipelineEngine.from_dict(
            {"video": {"source": "synthetic"}, "detector": {"model": "mock"}, "reid": {"model": "none"}},
            db_path=db_path,
            enable_event_bus_fallback=True,
            enable_memory_indexing=True,
        )
        self.addCleanup(bundle.close)
        self.assertIsNotNone(bundle.event_fts_index)

        bundle.event_bus.publish(ZoneEvent(
            camera_id="default", zone_id="entry", track_id=1, action="enter", timestamp=time.time(),
        ))
        self.assertTrue(bundle.event_bus.wait_until_empty(timeout=3.0))
        hits = bundle.db.search_timeline_events(query="entry")
        self.assertEqual(len(hits), 1)
        bundle.close()

        bundle_disabled = PipelineEngine.from_dict(
            {"video": {"source": "synthetic"}, "detector": {"model": "mock"}, "reid": {"model": "none"}},
            db_path=db_path,
            enable_event_bus_fallback=True,
            enable_memory_indexing=False,
        )
        self.addCleanup(bundle_disabled.close)
        self.assertIsNone(bundle_disabled.event_fts_index)


if __name__ == "__main__":
    unittest.main()
