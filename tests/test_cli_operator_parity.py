"""Unit and integration tests for Milestone 2 CLI <-> Dashboard operator parity."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import bind_app_state, clear_app_state
from intelligent_tracker.cli import (
    BenchmarkCollector,
    CliAppRunner,
    build_pipeline,
    ctl,
    parse_args,
    resolve_pipeline_params,
    run_cli,
)
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors import model_loader
from intelligent_tracker.memory import ConfidenceEngine
from intelligent_tracker.world import CameraNode, WorldEntity, WorldGraph


class _FakeHttpResponse:
    """Minimal context-manager HTTP response adapter wrapping FastAPI TestClient."""

    def __init__(self, body_bytes: bytes) -> None:
        self._body = body_bytes

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class TestCliOperatorParity(unittest.TestCase):
    """Verify bounded benchmarking, model verification, and WorldGraph CLI/API parity."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = os.path.join(self.tmpdir.name, "parity.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)
        self.now = time.time()
        self.alice_id = self.db.add_entity("Alice", category="staff")
        self.bob_id = self.db.add_entity("Bob", category="visitor")
        self._seed_observations_and_world()

    def _seed_observations_and_world(self) -> None:
        """Populate calibrated confidence rows and WorldGraph test nodes."""
        conf = ConfidenceEngine(db=self.db)
        conf.record_observation(
            entity_id=self.alice_id, visual_similarity=0.92, face_score=0.94,
            body_score=0.88, camera_id="cam_01", zone_id="lobby", timestamp=self.now - 2.0,
        )
        conf.record_observation(
            entity_id=self.bob_id, visual_similarity=0.45, face_score=0.40,
            body_score=0.42, camera_id="cam_02", zone_id="dock", timestamp=self.now - 1.0,
        )
        self.world_graph = WorldGraph()
        self.world_graph.register_camera(CameraNode(camera_id="cam_01", name="Lobby", source="synthetic"))
        self.world_graph.register_camera(CameraNode(camera_id="cam_02", name="Dock", source="synthetic"))
        self.world_graph.upsert_entity(WorldEntity(
            entity_id=self.alice_id, name="Alice", category="staff", confidence=0.91,
            camera_tracks={"cam_01": 1}, active_zones={"cam_01": {"lobby"}}, last_seen=self.now - 2.0,
        ))
        self.world_graph.upsert_entity(WorldEntity(
            entity_id=self.bob_id, name="Bob", category="visitor", confidence=0.42,
            camera_tracks={"cam_02": 2}, active_zones={"cam_02": {"dock"}}, last_seen=self.now - 1.0,
        ))

    def test_benchmark_collector_and_headless_cli_json_export(self) -> None:
        """Headless `--frames 5 --benchmark --benchmark-output` emits summary and JSON."""
        empty_stats = BenchmarkCollector().summary()
        self.assertEqual(empty_stats["frames"], 0)
        self.assertEqual(empty_stats["effective_fps"], 0.0)

        out_json = os.path.join(self.tmpdir.name, "reports", "bench.json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            run_cli([
                "--source", "synthetic",
                "--detector", "mock",
                "--reid", "none",
                "--headless",
                "--frames", "5",
                "--benchmark",
                "--benchmark-output", out_json,
                "--db", self.db_path,
            ])

        stdout_text = buf.getvalue()
        self.assertIn("Benchmark Metrics:", stdout_text)
        self.assertIn("Effective FPS", stdout_text)
        self.assertTrue(os.path.isfile(out_json))

        with open(out_json, "r", encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(report["frames"], 5)
        self.assertGreater(report["effective_fps"], 0.0)
        for key in ("min_ms", "mean_ms", "p95_ms", "max_ms"):
            self.assertGreaterEqual(report[key], 0.0)
        self.assertLessEqual(report["min_ms"], report["mean_ms"])
        self.assertLessEqual(report["mean_ms"], report["max_ms"])
        self.assertEqual(report["metadata"]["detector"], "mock")

    def test_frames_limit_rules_for_gui_and_headless(self) -> None:
        """Explicit `--frames N` bounds non-headless runs while default GUI stays unbounded."""
        gui_default = resolve_pipeline_params(parse_args(["--source", "synthetic"]), {})
        self.assertEqual(gui_default["frames"], 0)

        bench_default = resolve_pipeline_params(parse_args(["--source", "synthetic", "--benchmark"]), {})
        self.assertEqual(bench_default["frames"], 60)
        self.assertTrue(bench_default["benchmark"])

        args = parse_args([
            "--source", "synthetic",
            "--detector", "mock",
            "--reid", "none",
            "--frames", "3",
            "--db", self.db_path,
        ])
        ctx = build_pipeline(args, {})
        runner = CliAppRunner(ctx)
        with (
            patch.object(runner.ui, "setup"),
            patch.object(runner.ui, "process_key_event", return_value=True),
            patch.object(runner.ui, "cleanup"),
            redirect_stdout(io.StringIO()),
        ):
            runner.run()
        self.assertEqual(runner.frame_count, 3)

    def _build_temp_models_fixture(self) -> tuple[str, dict[str, dict[str, object]]]:
        """Create a temp models dir with valid, corrupt, and missing model entries."""
        models_dir = os.path.join(self.tmpdir.name, "models")
        os.makedirs(models_dir, exist_ok=True)
        valid_bytes = b"valid-onnx-bytes"
        valid_sha = hashlib.sha256(valid_bytes).hexdigest()
        with open(os.path.join(models_dir, "yolov8n.onnx"), "wb") as f:
            f.write(valid_bytes)
        with open(os.path.join(models_dir, "osnet_x0_25.onnx"), "wb") as f:
            f.write(b"corrupted-bytes")
        patched_models: dict[str, dict[str, object]] = {
            "yolov8n": {"filename": "yolov8n.onnx", "urls": [], "sha256": valid_sha, "size_bytes": len(valid_bytes), "description": "YOLO"},
            "osnet_x0_25": {"filename": "osnet_x0_25.onnx", "urls": [], "sha256": "0" * 64, "size_bytes": 100, "description": "OSNet"},
            "yunet": {"filename": "yunet.onnx", "urls": [], "sha256": "1" * 64, "size_bytes": 50, "description": "YuNet"},
        }
        return models_dir, patched_models

    def test_cli_check_models_flag_and_system_models_api(self) -> None:
        """`--check-models`, `GET /api/system/models`, and `POST /api/system/models/verify` report integrity."""
        models_dir, patched_models = self._build_temp_models_fixture()
        with (
            patch.object(model_loader, "MODELS", patched_models),
            patch.object(model_loader, "DEFAULT_MODELS_DIR", models_dir),
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                run_cli(["--check-models"])
            self.assertIn("VALID", buf.getvalue())
            self.assertIn("CORRUPT", buf.getvalue())
            self.assertIn("MISSING", buf.getvalue())

            client = TestClient(app)
            unverified = client.get("/api/system/models", params={"verify": "false"})
            self.assertEqual(unverified.status_code, 200)
            by_name = {m["name"]: m for m in unverified.json()["models"]}
            self.assertEqual(by_name["yolov8n"]["status"], "present")
            self.assertEqual(by_name["yunet"]["status"], "missing")

            verified = client.post("/api/system/models/verify")
            self.assertEqual(verified.status_code, 200)
            v_data = verified.json()
            self.assertFalse(v_data["all_valid"])
            self.assertEqual(v_data["counts"], {"total": 3, "valid": 1, "missing": 1, "corrupt": 1, "present": 1})

            single = client.post("/api/system/models/verify", params={"model_name": "yolov8n"})
            self.assertEqual(single.status_code, 200)
            self.assertTrue(single.json()["all_valid"])
            self.assertEqual(client.post("/api/system/models/verify", params={"model_name": "unknown_net"}).status_code, 404)

    def _make_fake_pool(self) -> SimpleNamespace:
        """Return a minimal CameraPool stub with world_graph and stream-lookup interface."""
        return SimpleNamespace(
            world_graph=self.world_graph,
            db_path=self.db_path,
            primary_stream=None,
            get_stream=lambda cid=None: None,
        )

    def test_world_snapshot_and_entities_api_and_pool_fallback(self) -> None:
        """GET /api/world/snapshot and /api/world/entities filter and resolve WorldGraph cleanly."""
        bind_app_state(app, db=self.db, camera_pool=self._make_fake_pool())
        self.addCleanup(lambda: clear_app_state(app))
        client = TestClient(app)

        snap_resp = client.get("/api/world/snapshot")
        self.assertEqual(snap_resp.status_code, 200)
        snap = snap_resp.json()
        self.assertEqual(snap["counts"]["cameras"], 2)
        self.assertEqual(snap["counts"]["entities"], 2)

        ent_resp = client.get("/api/world/entities", params={"camera_id": "cam_01", "min_confidence": 0.8})
        self.assertEqual(ent_resp.status_code, 200)
        ent_data = ent_resp.json()
        self.assertEqual(ent_data["count"], 1)
        self.assertEqual(ent_data["entities"][0]["name"], "Alice")

        clear_app_state(app)
        bind_app_state(app, db=self.db)
        empty_resp = client.get("/api/world/snapshot")
        self.assertEqual(empty_resp.status_code, 200)
        self.assertEqual(empty_resp.json()["counts"]["entities"], 0)

    def test_ctl_world_offline_and_error_branches(self) -> None:
        """`intelligent-tracker-ctl world` supports offline YAML/JSON/DB and missing-file errors."""
        cams_json = os.path.join(self.tmpdir.name, "cameras.json")
        with open(cams_json, "w", encoding="utf-8") as handle:
            json.dump([{"id": "cam_01", "name": "Lobby", "source": "synthetic", "enabled": True}], handle)

        buf = io.StringIO()
        with redirect_stdout(buf):
            ctl.main(["world", "snapshot", "--config", cams_json, "--db", self.db_path, "--json"])
        offline_snap = json.loads(buf.getvalue())
        self.assertEqual(offline_snap["counts"]["cameras"], 1)
        self.assertEqual(offline_snap["counts"]["entities"], 2)

        ent_buf = io.StringIO()
        with redirect_stdout(ent_buf):
            ctl.main([
                "world", "entities", "--config", os.path.join("configs", "demo.yaml"),
                "--db", self.db_path, "--min-confidence", "0.7", "--json",
            ])
        filtered_ents = json.loads(ent_buf.getvalue())
        self.assertEqual(filtered_ents["count"], 1)
        self.assertEqual(filtered_ents["entities"][0]["name"], "Alice")

        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                ctl.main(["world", "summary", "--db", os.path.join(self.tmpdir.name, "missing.db")])
        self.assertEqual(cm.exception.code, 1)

    def test_ctl_world_remote_parity(self) -> None:
        """`intelligent-tracker-ctl world --url` matches remote `/api/world/entities`."""
        bind_app_state(app, db=self.db, camera_pool=self._make_fake_pool())
        self.addCleanup(lambda: clear_app_state(app))
        client = TestClient(app)

        def _fake_urlopen(req, timeout=8.0):
            path_and_qs = req.full_url.split("http://dashboard.test", 1)[1]
            resp = client.request(req.get_method(), path_and_qs)
            return _FakeHttpResponse(resp.content)

        remote_buf = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            with redirect_stdout(remote_buf):
                ctl.main(["world", "entities", "--camera", "cam_02", "--url", "http://dashboard.test", "--json"])
        remote_data = json.loads(remote_buf.getvalue())
        self.assertEqual(remote_data["count"], 1)
        self.assertEqual(remote_data["entities"][0]["name"], "Bob")

    def test_ctl_models_offline_remote_download_and_errors(self) -> None:
        """`intelligent-tracker-ctl models` covers offline check, remote verify, download, and errors."""
        models_dir = os.path.join(self.tmpdir.name, "models")
        os.makedirs(models_dir, exist_ok=True)
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            ctl.main(["models", "--verify", "--models-dir", models_dir, "--json"])
        local_payload = json.loads(out_buf.getvalue())
        self.assertEqual(local_payload["models_dir"], models_dir)
        self.assertTrue(local_payload["verified"])

        dl_buf = io.StringIO()
        with patch("intelligent_tracker.cli.ctl_world.download_model", return_value="models/yolov8n.onnx") as mock_dl:
            with redirect_stdout(dl_buf):
                ctl.main(["models", "--download", "yolov8n", "--models-dir", models_dir, "--json"])
        mock_dl.assert_called_once_with("yolov8n", output_dir=models_dir, force=False)
        self.assertEqual(json.loads(dl_buf.getvalue())["downloaded"], "yolov8n")

        client = TestClient(app)

        def _fake_urlopen(req, timeout=8.0):
            path = req.full_url.split("http://dashboard.test", 1)[1]
            resp = client.request(req.get_method(), path)
            return _FakeHttpResponse(resp.content)

        rem_buf = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            with redirect_stdout(rem_buf):
                ctl.main(["models", "--verify", "--url", "http://dashboard.test", "--json"])
        self.assertIn("models", json.loads(rem_buf.getvalue()))

        net_err = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            with redirect_stderr(net_err):
                with self.assertRaises(SystemExit) as cm:
                    ctl.main(["models", "--url", "http://dashboard.test"])
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
