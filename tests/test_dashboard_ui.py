#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Unit & Regression Tests for Modernized VMS Dashboard UI.
Milestone 10 Deliverable (Responsive Layout, Ergonomics, In-Page Modals, Telemetry API).
"""

import os
import tempfile
import unittest
from fastapi.testclient import TestClient

from dashboard.app import app
import dashboard.app as app_module
from intelligent_tracker.database import TrackerDB
from dashboard.camera_pool import CameraPool


class TestDashboardUI(unittest.TestCase):
    """Test suite for VMS Dashboard frontend HTML structure, modals, static assets, and telemetry API."""

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.tmp_dir, "test_dashboard_ui.db")
        cls.cam_cfg = os.path.join(cls.tmp_dir, "cameras.json")
        cls.db = TrackerDB(cls.db_path)

        cls.pool = CameraPool(
            config_file=cls.cam_cfg,
            db_path=cls.db_path,
            autostart=False,
        )
        app_module.camera_pool = cls.pool
        app_module.stream_manager = cls.pool.primary_stream
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.pool.stop_all()
        cls.db.close()
        import shutil
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def test_dashboard_index_html_structure_and_tabs(self):
        """Verify dashboard index.html returns HTTP 200 and renders all 9 tabs + mobile navigation."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # 9 Core VMS Navigation Tabs
        required_tabs = [
            'id="tab-live"',
            'id="tab-videos"',
            'id="tab-gallery"',
            'id="tab-timeline"',
            'id="tab-analytics"',
            'id="tab-alerts"',
            'id="tab-studio"',
            'id="tab-journey"',
            'id="tab-review"',
        ]
        for tab_id in required_tabs:
            self.assertIn(tab_id, html, f"Missing required tab pane {tab_id}")

        # Milestone 10 Responsive Header elements
        self.assertIn('id="btn-mobile-menu"', html, "Missing mobile hamburger button")
        self.assertIn('id="nav-tabs-wrapper"', html, "Missing nav-tabs-wrapper auto-scroll container")
        self.assertIn('id="mobile-nav-drawer"', html, "Missing mobile navigation drawer")
        self.assertIn('id="toast-container"', html, "Missing toast notification container")

    def test_live_player_hud_controls(self):
        """Verify Live Monitor HUD toolbar buttons and telemetry displays."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        self.assertIn('class="live-player-hud', html)
        self.assertIn('id="btn-stream-pause-play"', html)
        self.assertIn('id="btn-stream-reconnect"', html)
        self.assertIn('id="live-stream-status-badge"', html)
        self.assertIn('id="stream-telemetry-hud"', html)
        self.assertIn('id="btn-quick-tag"', html)
        self.assertIn('id="btn-snapshot-save"', html)
        self.assertIn('id="btn-fullscreen-toggle"', html)

    def test_standardized_dialogs_and_modal_scroll(self):
        """Verify all Milestone 10 modal dialogs contain scrollable bodies (.modal-body-scroll)."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        modals = [
            'id="modal-camera-manager"',
            'id="modal-universal-enrollment"',
            'id="modal-backup-manager"',
            'id="modal-descriptor-versions"',
            'id="modal-review-reassign"',
            'id="modal-studio-zone"',
            'id="modal-studio-tripwire"',
            'id="modal-studio-homography"',
            'id="modal-studio-transition"',
            'id="modal-quick-enroll-entity"',
        ]
        for m in modals:
            self.assertIn(m, html, f"Missing modal {m}")

        # Count occurrences of modal-body-scroll ensuring scroll containment
        scroll_count = html.count('class="modal-body-scroll')
        self.assertGreaterEqual(scroll_count, 8, "Expected at least 8 scroll-contained modal dialog bodies")

    def test_static_assets_integrity(self):
        """Verify static CSS and JS assets are served with HTTP 200 and contain expected modernization symbols."""
        css_res = self.client.get("/static/styles.css")
        self.assertEqual(css_res.status_code, 200)
        self.assertIn('css/player.css', css_res.text)
        self.assertIn('css/layout.css', css_res.text)

        # Verify modular component stylesheets are served and contain modernization classes
        player_css = self.client.get("/static/css/player.css").text
        self.assertIn(".live-player-hud", player_css)

        layout_css = self.client.get("/static/css/layout.css").text
        self.assertIn(".nav-tabs-wrapper", layout_css)

        responsive_css = self.client.get("/static/css/responsive.css").text
        self.assertIn(".mobile-nav-drawer", responsive_css)

        modals_css = self.client.get("/static/css/modals.css").text
        self.assertIn(".modal-body-scroll", modals_css)

        js_res = self.client.get("/static/app.js")
        self.assertEqual(js_res.status_code, 200)
        js = js_res.text
        self.assertIn("showToast", js)
        self.assertIn("STANDBY_POSTER_SVG", js)
        self.assertIn("detachLiveStream", js)
        self.assertIn("attachLiveStream", js)

        # Verify modular feature JS assets are also served with HTTP 200
        live_js = self.client.get("/static/js/features/live_player.js")
        self.assertEqual(live_js.status_code, 200)
        self.assertIn("attachLiveStream", live_js.text)

    def test_rest_telemetry_snapshot_endpoint(self):
        """Verify GET /api/cameras/{camera_id}/telemetry endpoint contract for Enterprise Hub canvas overlay."""
        res = self.client.get("/api/cameras/cam_01/telemetry")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["camera_id"], "cam_01")
        self.assertIn("status", data)
        self.assertIn("fps", data)
        self.assertIn("resolution", data)
        self.assertIn("active_tracks", data)
        self.assertIn("zones", data)
        self.assertIn("tripwires", data)
        self.assertIsInstance(data["active_tracks"], list)
        self.assertIsInstance(data["zones"], list)
        self.assertIsInstance(data["tripwires"], list)

        # 404 for non-existent camera
        err_res = self.client.get("/api/cameras/non_existent_camera_99/telemetry")
        self.assertEqual(err_res.status_code, 404)


if __name__ == "__main__":
    unittest.main()

