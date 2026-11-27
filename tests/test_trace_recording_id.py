#!/usr/bin/env python3
"""Unit tests for X-Debug-Recording-Id trace stamping, debug recording isolation, and legacy observation migration."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.services import diagnostic_bridge
from dashboard.services.debug_session import (
    get_debug_recordings_dir,
    prepare_debug_session_env,
    record_user_observation,
)
from dashboard.services.diagnostic_bridge import DiagnosticTraceMiddleware
from scripts import debug_inspect

_HAS_TRACE_RECORDER = diagnostic_bridge._recorder_mod is not None
_HAS_OBS_STORE = debug_inspect._load_observation_store() is not None
_SKIP_NO_RECORDER = "system-diagnostics trace_recorder engine not installed"
_SKIP_NO_OBS_STORE = "system-diagnostics observation_store engine not installed"


class TestTraceRecordingIdAndMigration(unittest.TestCase):
    """Verify trace recording_id stamping, debug recording dir isolation, and idempotent migration."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.workspace = self.root / "ws"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.debug_dir = self.root / "debug_session"

    def _build_boom_client(self) -> TestClient:
        app = FastAPI()
        app.add_middleware(DiagnosticTraceMiddleware, workspace_root=self.workspace)

        @app.get("/boom")
        def _boom() -> dict[str, str]:
            raise RuntimeError("synthetic trace boom")

        return TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50000))

    def _read_trace_events(self) -> list[dict]:
        traces_dir = self.workspace / ".diagnostics" / "traces"
        if not traces_dir.is_dir():
            return []
        events: list[dict] = []
        for path in sorted(traces_dir.glob("trace_*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    events.append(json.loads(line))
        return events

    def test_middleware_stamps_recording_id_in_captured_context(self) -> None:
        client = self._build_boom_client()
        captured: list[dict] = []

        def _fake_capture(exc, context=None, workspace_root=None):
            captured.append(dict(context or {}))
            return None

        with patch.dict(os.environ, {"IT_DEBUG_MODE": "0"}, clear=False):
            with patch("dashboard.services.diagnostic_bridge.capture_runtime_exception", side_effect=_fake_capture):
                self.assertEqual(client.get("/boom", headers={"X-Debug-Recording-Id": "rec-20261126-abc123"}).status_code, 500)
                self.assertEqual(client.get("/boom").status_code, 500)
                self.assertEqual(client.get("/boom", headers={"X-Debug-Recording-Id": "bad id; drop table"}).status_code, 500)

        self.assertEqual(len(captured), 3)
        self.assertEqual(captured[0].get("recording_id"), "rec-20261126-abc123")
        self.assertEqual(captured[0].get("http_path"), "/boom")
        self.assertNotIn("recording_id", captured[1])
        self.assertNotIn("recording_id", captured[2])

    @unittest.skipUnless(_HAS_TRACE_RECORDER, _SKIP_NO_RECORDER)
    def test_request_with_recording_id_header_stamps_trace_context(self) -> None:
        client = self._build_boom_client()
        env = {"DIAGNOSTICS_TRACE_IN_TESTS": "1", "IT_DEBUG_MODE": "0"}
        with patch.dict(os.environ, env, clear=False):
            resp = client.get("/boom", headers={"X-Debug-Recording-Id": "rec-20261126-abc123"})
        self.assertEqual(resp.status_code, 500)

        events = self._read_trace_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["context"].get("recording_id"), "rec-20261126-abc123")
        self.assertEqual(events[0]["context"].get("http_path"), "/boom")

    @unittest.skipUnless(_HAS_TRACE_RECORDER, _SKIP_NO_RECORDER)
    def test_request_without_header_or_invalid_header_has_no_recording_id(self) -> None:
        client = self._build_boom_client()
        env = {"DIAGNOSTICS_TRACE_IN_TESTS": "1", "IT_DEBUG_MODE": "0"}
        with patch.dict(os.environ, env, clear=False):
            r_none = client.get("/boom")
            r_bad = client.get("/boom", headers={"X-Debug-Recording-Id": "bad id; drop table"})
        self.assertEqual(r_none.status_code, 500)
        self.assertEqual(r_bad.status_code, 500)

        events = self._read_trace_events()
        self.assertEqual(len(events), 2)
        for ev in events:
            self.assertNotIn("recording_id", ev["context"])

    def test_debug_session_isolates_stored_recordings_directory(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STORED_RECORDINGS", None)
            os.environ.pop("TRACKER_VIDEOS_DIR", None)
            os.environ.pop("IT_DEBUG_MODE", None)
            os.environ.pop("TRACKER_DEBUG_DIR", None)

            default_dir = get_debug_recordings_dir()
            self.assertEqual(default_dir, Path("data") / "videos")

            env_vals = prepare_debug_session_env(self.debug_dir, clean=True)
            expected = self.debug_dir / "recordings"
            self.assertTrue(expected.is_dir())
            self.assertEqual(Path(env_vals["STORED_RECORDINGS"]), expected)
            self.assertEqual(Path(env_vals["TRACKER_VIDEOS_DIR"]), expected)
            self.assertEqual(get_debug_recordings_dir(), expected)

    def _run_migrate_cli(self) -> dict:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = debug_inspect.main([
                "--dir", str(self.debug_dir),
                "--workspace", str(self.workspace),
                "--migrate-observations",
                "--json",
            ])
        self.assertEqual(rc, 0)
        return json.loads(buf.getvalue())

    def test_migrate_observations_fails_cleanly_when_store_unavailable(self) -> None:
        err_buf = io.StringIO()
        with patch.object(debug_inspect, "_load_observation_store", return_value=None):
            with contextlib.redirect_stderr(err_buf):
                rc = debug_inspect.main([
                    "--dir", str(self.debug_dir),
                    "--workspace", str(self.workspace),
                    "--migrate-observations",
                ])
        self.assertEqual(rc, 1)
        self.assertIn("observation_store is unavailable", err_buf.getvalue())

    @unittest.skipUnless(_HAS_OBS_STORE, _SKIP_NO_OBS_STORE)
    def test_migrate_observations_is_idempotent(self) -> None:
        record_user_observation(
            note="Video stalled at 8x playback",
            tab="tab-videos",
            url="/#videos",
            breadcrumbs=[{"type": "click", "target": "button#scrubber-btn-play"}],
            viewport={"width": 1920, "height": 945},
            debug_dir=self.debug_dir,
        )
        record_user_observation(
            note="Multiview tile aspect ratio stretched",
            tab="tab-live",
            url="/#live",
            breadcrumbs=[{"type": "click", "target": "button.btn-sm"}],
            viewport={"width": 1920, "height": 945},
            debug_dir=self.debug_dir,
        )

        res1 = self._run_migrate_cli()
        self.assertEqual((res1["found"], res1["imported"], res1["skipped"]), (2, 2, 0))

        # Second run must be strictly idempotent (0 imported, 2 skipped, occurrence_count stays 1)
        res2 = self._run_migrate_cli()
        self.assertEqual((res2["found"], res2["imported"], res2["skipped"]), (2, 0, 2))

        catalog_path = self.workspace / ".diagnostics" / "observation_catalog.json"
        self.assertTrue(catalog_path.is_file())
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.assertEqual(len(catalog["observations"]), 2)
        for obs in catalog["observations"]:
            self.assertEqual(obs["occurrence_count"], 1)
            self.assertEqual(obs["kind"], "note")
            self.assertEqual(obs["attrs"]["migrated_from"], "debug_session/events.jsonl")

    @unittest.skipUnless(_HAS_OBS_STORE, _SKIP_NO_OBS_STORE)
    def test_debug_inspect_observations_shows_connector_and_legacy(self) -> None:
        store = debug_inspect._load_observation_store()
        self.assertIsNotNone(store)
        store.add_observation(
            self.workspace,
            {
                "kind": "element",
                "page_path": "/#studio",
                "selector": "#studio-drawing-canvas",
                "message": "Drawn lines should have an IN/OUT handle",
                "recording_id": "rec-abc123",
                "timeline": [{"t": 1, "type": "click", "target": "#studio-drawing-canvas"}],
            },
        )
        record_user_observation(
            note="Legacy note",
            tab="tab-live",
            url="/#live",
            breadcrumbs=[],
            viewport={"width": 1280, "height": 720},
            debug_dir=self.debug_dir,
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = debug_inspect.main([
                "--dir", str(self.debug_dir),
                "--workspace", str(self.workspace),
                "--observations",
            ])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("[CONNECTOR OBSERVATIONS]", out)
        self.assertIn("OBS-001", out)
        self.assertIn("#studio-drawing-canvas", out)
        self.assertIn("Drawn lines should have an IN/OUT handle", out)
        self.assertIn("[DEBUG OBSERVATIONS]", out)
        self.assertIn("Legacy note", out)


if __name__ == "__main__":
    unittest.main()
