"""Unit and parity tests for `intelligent-tracker ask` and `intelligent-tracker-ctl ask`."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import bind_app_state, clear_app_state
from intelligent_tracker.cli import ctl, run_cli
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.memory import ConfidenceEngine


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


class TestCliAskParity(unittest.TestCase):
    """Verify offline, remote, and error branches for CLI `ask` subcommands."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = os.path.join(self.tmpdir.name, "cli_ask.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)

        now = time.time()
        self.alice_id = self.db.add_entity("Alice", category="staff")
        ConfidenceEngine(db=self.db).record_observation(
            entity_id=self.alice_id,
            visual_similarity=0.89,
            face_score=0.92,
            body_score=0.85,
            camera_id="cam_01",
            zone_id="lobby",
            timestamp=now - 3.0,
        )
        self.db.index_timeline_event(
            event_type="sighting",
            entity_id=self.alice_id,
            entity_name="Alice",
            category="staff",
            camera_id="cam_01",
            zone_id="lobby",
            timestamp=now - 3.0,
            confidence=0.92,
            title="Alice sighted",
            summary="Alice arrived at lobby on cam_01",
        )
        self.db.index_timeline_event(
            event_type="rsac_violation",
            entity_id=None,
            entity_name="Unknown Visitor",
            category="visitor",
            camera_id="cam_02",
            zone_id="vault",
            timestamp=now - 1.0,
            confidence=0.75,
            title="Vault alert",
            summary="Unauthorized entry into vault on cam_02",
        )

    def test_runner_ask_offline_json_and_sys_argv_dispatch(self) -> None:
        """`intelligent-tracker ask --db ... --json` matches local WorldQueryEngine results."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            run_cli(["ask", "Where", "was", "Alice?", "--db", self.db_path, "--json"])
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["provider"], "local_deterministic")
        self.assertIn("Alice", payload["answer"])
        self.assertEqual(len(payload["citations"]), 1)

        buf2 = io.StringIO()
        with patch.object(sys, "argv", ["intelligent-tracker", "ask", "What is Alice confidence?", "--db", self.db_path, "--json"]):
            with redirect_stdout(buf2):
                run_cli()
        payload2 = json.loads(buf2.getvalue())
        self.assertEqual(payload2["intent"], "confidence")
        self.assertGreater(payload2["entities"][0]["confidence"], 0.7)

    def test_ctl_ask_human_output_and_offline_env_override(self) -> None:
        """`intelligent-tracker-ctl ask` supports offline queries even if TRACKER_DASHBOARD_URL is set."""
        buf = io.StringIO()
        with patch.dict(os.environ, {"TRACKER_DASHBOARD_URL": "http://remote-tracker.invalid"}):
            with redirect_stdout(buf):
                ctl.main(["ask", "Show RSAC violations", "--offline", "--db", self.db_path])
        text = buf.getvalue()
        self.assertIn("Answer   :", text)
        self.assertIn("rsac_violation", text)
        self.assertIn("vault", text)

    def test_api_and_remote_cli_parity_via_testclient(self) -> None:
        """Remote CLI `ask --url ...` produces identical results to POST /api/world/query."""
        bind_app_state(app, db=self.db)
        self.addCleanup(lambda: clear_app_state(app))
        client = TestClient(app)

        api_resp = client.post("/api/world/query", json={"query": "Where was Alice?"}).json()

        def _fake_urlopen(req, timeout=10.0):
            body = json.loads(req.data.decode("utf-8"))
            resp = client.post("/api/world/query", json=body)
            return _FakeHttpResponse(resp.content)

        buf = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            with redirect_stdout(buf):
                ctl.main(["ask", "Where was Alice?", "--url", "http://dashboard.test", "--json"])
        cli_resp = json.loads(buf.getvalue())
        self.assertEqual(cli_resp["answer"], api_resp["answer"])
        self.assertEqual(cli_resp["citations"], api_resp["citations"])

    def test_ask_error_branches(self) -> None:
        """Verify exit codes for missing DB file, whitespace query, and remote connection failure."""
        missing_db = os.path.join(self.tmpdir.name, "missing.db")
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            with self.assertRaises(SystemExit) as cm_db:
                run_cli(["ask", "Where was Alice?", "--db", missing_db])
        self.assertEqual(cm_db.exception.code, 1)
        self.assertIn("Database file not found", err_buf.getvalue())

        blank_err = io.StringIO()
        with redirect_stderr(blank_err):
            with self.assertRaises(SystemExit) as cm_blank:
                ctl.main(["ask", "   ", "--db", self.db_path])
        self.assertEqual(cm_blank.exception.code, 2)

        net_err = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            with redirect_stderr(net_err):
                with self.assertRaises(SystemExit) as cm_net:
                    ctl.main(["--url", "http://dashboard.test", "ask", "Where was Alice?"])
        self.assertEqual(cm_net.exception.code, 1)
        self.assertIn("World query failed", net_err.getvalue())


if __name__ == "__main__":
    unittest.main()

