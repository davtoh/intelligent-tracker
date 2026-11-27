#!/usr/bin/env python3
"""Wire Contract v1 tests for the debug observation connector in FastAPI."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.services import diagnostic_bridge
from dashboard.services.diagnostic_bridge import register_observation_routes

_HAS_OBS_ENGINE = diagnostic_bridge._obs is not None
_SKIP_NO_OBS = "system-diagnostics observation_routes engine not installed"


class TestDiagnosticsContract(unittest.TestCase):
    """Verify Wire Contract v1 gating, loopback access, limits, redaction, and vectors."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name)

    def _build_client(self, *, client_host: str = "127.0.0.1", enabled: bool = True) -> tuple[TestClient, FastAPI]:
        env_val = "1" if enabled else "0"
        patcher = patch.dict(os.environ, {"FRONTIER_DEBUG_OBSERVATIONS": env_val}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = FastAPI()
        register_observation_routes(app, workspace_root=self.workspace)
        return TestClient(app, client=(client_host, 50000)), app

    def test_gating_flag_off_registers_no_routes_and_returns_404(self) -> None:
        for flag in (None, "0", "false"):
            env_patch = {} if flag is None else {"FRONTIER_DEBUG_OBSERVATIONS": flag}
            with patch.dict(os.environ, env_patch, clear=False):
                if flag is None:
                    os.environ.pop("FRONTIER_DEBUG_OBSERVATIONS", None)
                app = create_app()
                diag_paths = [
                    getattr(r, "path", "")
                    for r in app.routes
                    if str(getattr(r, "path", "")).startswith("/api/diagnostics")
                ]
                self.assertEqual(diag_paths, [])
                client = TestClient(app, client=("127.0.0.1", 50000))
                for method, path in (
                    ("GET", "/api/diagnostics/health"),
                    ("POST", "/api/diagnostics/observation"),
                    ("GET", "/api/diagnostics/observations"),
                    ("GET", "/api/diagnostics/observations/OBS-001"),
                    ("GET", "/api/diagnostics/hud.js"),
                ):
                    resp = client.request(method, path)
                    self.assertEqual(resp.status_code, 404, f"{method} {path} should be 404 when disabled")

    def test_missing_engine_degrades_gracefully_even_when_flag_enabled(self) -> None:
        with patch.dict(os.environ, {"FRONTIER_DEBUG_OBSERVATIONS": "1"}, clear=False):
            with patch.object(diagnostic_bridge, "_obs", None):
                self.assertFalse(diagnostic_bridge.observations_enabled())
                app = FastAPI()
                self.assertFalse(register_observation_routes(app, workspace_root=self.workspace))
                status, headers, payload = diagnostic_bridge.handle_diagnostics_request(
                    "GET", "/health", "", {}, "127.0.0.1", b"", self.workspace
                )
                self.assertEqual(status, 404)
                self.assertEqual(headers.get("X-Diagnostics-Contract"), "1")
                self.assertIn(b"engine unavailable", payload)

    @unittest.skipUnless(_HAS_OBS_ENGINE, _SKIP_NO_OBS)
    def test_create_app_mounts_diagnostics_when_flag_enabled(self) -> None:
        with patch.dict(os.environ, {"FRONTIER_DEBUG_OBSERVATIONS": "1"}, clear=False):
            app = create_app()
            client = TestClient(app, client=("127.0.0.1", 50000))
            resp = client.get("/api/diagnostics/health")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("X-Diagnostics-Contract"), "1")
            self.assertEqual(
                resp.json(),
                {"schema": 1, "enabled": True, "contract_version": 1, "store": "ok"},
            )

    @unittest.skipUnless(_HAS_OBS_ENGINE, _SKIP_NO_OBS)
    def test_non_loopback_client_receives_403_with_contract_header(self) -> None:
        client, _ = self._build_client(client_host="203.0.113.10")
        for method, path in (
            ("GET", "/api/diagnostics/health"),
            ("POST", "/api/diagnostics/observation"),
            ("GET", "/api/diagnostics/observations"),
            ("GET", "/api/diagnostics/observations/OBS-001"),
            ("GET", "/api/diagnostics/hud.js"),
        ):
            resp = client.request(method, path)
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(resp.headers.get("X-Diagnostics-Contract"), "1")
            self.assertEqual(resp.json().get("error"), "forbidden")

    @unittest.skipUnless(_HAS_OBS_ENGINE, _SKIP_NO_OBS)
    def test_post_error_codes_and_dry_run(self) -> None:
        client, _ = self._build_client()

        r_json = client.post(
            "/api/diagnostics/observation",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(r_json.status_code, 400)
        self.assertEqual(r_json.json()["error"], "invalid_json")

        r_rec = client.post("/api/diagnostics/observation", json={"kind": "bogus"})
        self.assertEqual(r_rec.status_code, 400)
        self.assertEqual(r_rec.json()["error"], "invalid_record")

        r_ctype = client.post(
            "/api/diagnostics/observation",
            content=b'{"kind":"note","message":"hi"}',
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(r_ctype.status_code, 415)
        self.assertEqual(r_ctype.json()["error"], "unsupported_media_type")

        oversize = {"kind": "note", "message": "x", "attrs": {"pad": "p" * 70000}}
        r_big = client.post("/api/diagnostics/observation", json=oversize)
        self.assertEqual(r_big.status_code, 413)
        self.assertEqual(r_big.json()["error"], "payload_too_large")

        r_dry = client.post(
            "/api/diagnostics/observation?dry_run=1",
            json={"schema": 1, "ts": "2026-11-26T12:00:00Z", "kind": "note", "page_path": "/x", "message": "check"},
        )
        self.assertEqual(r_dry.status_code, 200)
        self.assertTrue(r_dry.json()["dry_run"])
        self.assertEqual(client.get("/api/diagnostics/observations").json()["count"], 0)

    @unittest.skipUnless(_HAS_OBS_ENGINE, _SKIP_NO_OBS)
    def test_create_dedup_and_redaction(self) -> None:
        client, _ = self._build_client()
        payload = {
            "schema": 1,
            "kind": "element",
            "page_path": "/dashboard",
            "selector": "main > button#save",
            "message": "Save does nothing",
            "value": "secret-val",
            "password": "secret-pw",
            "attrs": {"id": "save", "authorization": "Bearer secret-tok", "cookie": "sid=secret-cookie"},
        }
        r1 = client.post("/api/diagnostics/observation", json=payload)
        self.assertEqual(r1.status_code, 201)
        body1 = r1.json()
        self.assertEqual(body1["status"], "open")
        self.assertFalse(body1["deduplicated"])

        r2 = client.post("/api/diagnostics/observation", json=payload)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()["deduplicated"])
        self.assertEqual(r2.json()["id"], body1["id"])

        r_get = client.get(f"/api/diagnostics/observations/{body1['id']}")
        self.assertEqual(r_get.status_code, 200)
        entry = r_get.json()
        dumped = str(entry)
        for leaked in ("secret-val", "secret-pw", "secret-tok", "secret-cookie"):
            self.assertNotIn(leaked, dumped)
        self.assertNotIn("value", entry)
        self.assertNotIn("password", entry)
        self.assertNotIn("authorization", entry["attrs"])
        self.assertNotIn("cookie", entry["attrs"])
        self.assertEqual(entry["attrs"]["id"], "save")

    @unittest.skipUnless(_HAS_OBS_ENGINE, _SKIP_NO_OBS)
    def test_list_get_not_found_and_hud(self) -> None:
        client, _ = self._build_client()
        created = client.post(
            "/api/diagnostics/observation",
            json={"schema": 1, "kind": "element", "page_path": "/dashboard", "message": "Save does nothing"},
        )
        self.assertEqual(created.status_code, 201)

        r_list_default = client.get("/api/diagnostics/observations")
        self.assertEqual(r_list_default.status_code, 200)
        self.assertEqual(r_list_default.json()["count"], 1)
        self.assertEqual(client.get("/api/diagnostics/observations?kind=idea").json()["count"], 0)
        self.assertEqual(client.get("/api/diagnostics/observations?status=bogus").status_code, 400)
        self.assertEqual(client.get("/api/diagnostics/observations/OBS-DOES-NOT-EXIST").status_code, 404)

        r_hud = client.get("/api/diagnostics/hud.js")
        self.assertEqual(r_hud.status_code, 200)
        self.assertIn("javascript", r_hud.headers.get("Content-Type", ""))
        self.assertIn("no-store", r_hud.headers.get("Cache-Control", ""))
        self.assertEqual(r_hud.headers.get("X-Diagnostics-Contract"), "1")
        self.assertGreater(len(r_hud.text.strip()), 20)

    @unittest.skipUnless(_HAS_OBS_ENGINE, _SKIP_NO_OBS)
    def test_fingerprint_test_vectors(self) -> None:
        client, _ = self._build_client()
        vectors = [
            (
                {"kind": "element", "page_path": "/dashboard", "selector": "main > button#save", "message": "Save   does NOTHING"},
                "OBS-ELEMENT-fdd3fe",
            ),
            (
                {"kind": "error", "page_path": "/tracker", "selector": "/api/frames", "message": "Request 123456 failed at 0xDEADBEEF"},
                "OBS-ERROR-f93b8a",
            ),
            (
                {"kind": "idea", "page_path": "/dashboard", "message": "Add a pause button"},
                "OBS-IDEA-eca73f",
            ),
        ]
        for rec, expected_fp in vectors:
            resp = client.post("/api/diagnostics/observation?dry_run=1", json=rec)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["fingerprint"], expected_fp)

    @unittest.skipUnless(_HAS_OBS_ENGINE, _SKIP_NO_OBS)
    def test_patch_and_delete_observations(self) -> None:
        client, _ = self._build_client()
        created = client.post(
            "/api/diagnostics/observation",
            json={"schema": 1, "kind": "note", "page_path": "/#studio", "message": "initial"},
        )
        self.assertEqual(created.status_code, 201)
        obs_id = created.json()["id"]

        patched = client.patch(
            f"/api/diagnostics/observations/{obs_id}",
            json={
                "kind": "element",
                "message": "updated direction handle note",
                "selector": "#studio-drawing-canvas",
                "recording_id": "rec-123456",
                "attrs": {"tag": "canvas", "password": "secret"},
            },
        )
        self.assertEqual(patched.status_code, 200)
        body = patched.json()
        self.assertEqual(body["kind"], "element")
        self.assertEqual(body["message"], "updated direction handle note")
        self.assertEqual(body["selector"], "#studio-drawing-canvas")
        self.assertEqual(body["recording_id"], "rec-123456")
        self.assertNotIn("password", body["attrs"])

        self.assertEqual(client.patch("/api/diagnostics/observations/OBS-999", json={"message": "x"}).status_code, 404)
        deleted = client.delete(f"/api/diagnostics/observations/{obs_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])
        self.assertEqual(client.get(f"/api/diagnostics/observations/{obs_id}").status_code, 404)

        remote, _ = self._build_client(client_host="203.0.113.10")
        self.assertEqual(remote.patch(f"/api/diagnostics/observations/{obs_id}", json={"message": "x"}).status_code, 403)
        self.assertEqual(remote.delete(f"/api/diagnostics/observations/{obs_id}").status_code, 403)


if __name__ == "__main__":
    unittest.main()
