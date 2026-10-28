#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Milestone 7 Multi-Camera VMS, Video Upload & Backup REST API endpoints.
"""

import os
import io
import sys
import json
import time
import shutil
import tempfile
import unittest

from fastapi.testclient import TestClient

from dashboard.app import app
import dashboard.app as app_module
from dashboard.camera_pool import CameraPool
from intelligent_tracker.database import TrackerDB


class TestVmsApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="tracker_vms_api_test_")
        cls.config_file = os.path.join(cls.test_dir, "cameras.json")
        cls.db_path = os.path.join(cls.test_dir, "tracker.db")

        # Initialize test database
        cls.db = TrackerDB(cls.db_path)
        cls.db.add_entity("VIP Alice", category="vip")

        # Set up CameraPool in app
        cls.pool = CameraPool(
            config_file=cls.config_file,
            db_path=cls.db_path,
            autostart=False,
        )
        app_module.camera_pool = cls.pool
        app_module.stream_manager = cls.pool.primary_stream

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        if cls.pool:
            cls.pool.stop_all()
        if hasattr(cls, "db") and cls.db:
            cls.db.close()
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_get_camera_presets(self):
        """Verify GET /api/cameras/presets returns vendor presets list."""
        resp = self.client.get("/api/cameras/presets")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 5)
        ids = [p["id"] for p in data]
        self.assertIn("hikvision", ids)
        self.assertIn("tapo", ids)
        self.assertIn("ezviz", ids)
        self.assertIn("dahua", ids)

    def test_02_test_camera_connection_route(self):
        """Verify POST /api/cameras/test returns connection diagnostics."""
        resp = self.client.post(
            "/api/cameras/test",
            json={"source": "synthetic"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["resolution"], "640x480")
        self.assertIn("snapshot_base64", data)

    def test_03_discover_cameras_route(self):
        """Verify GET /api/cameras/discover returns discovered devices."""
        resp = self.client.get("/api/cameras/discover?include_usb=false&include_onvif=false&include_lan_rtsp=false")
        self.assertEqual(resp.status_code, 200)
        devices = resp.json()
        self.assertIsInstance(devices, list)
        self.assertGreaterEqual(len(devices), 1)
        self.assertEqual(devices[0]["type"], "synthetic")

    def test_04_camera_pool_crud_api(self):
        """Verify full lifecycle: Add, List, Get, Update, Toggle, Delete camera."""
        # 1. Add Camera
        add_resp = self.client.post(
            "/api/cameras",
            json={
                "id": "cam_dock",
                "name": "Loading Dock",
                "source": "synthetic",
                "type": "synthetic",
                "detector": "mock",
                "tracker": "centroid",
            }
        )
        self.assertEqual(add_resp.status_code, 200)
        self.assertEqual(add_resp.json()["status"], "success")

        # 2. List Cameras
        list_resp = self.client.get("/api/cameras")
        self.assertEqual(list_resp.status_code, 200)
        cams = list_resp.json()
        self.assertTrue(any(c["id"] == "cam_dock" for c in cams))

        # 3. Get Camera Info
        get_resp = self.client.get("/api/cameras/cam_dock")
        self.assertEqual(get_resp.status_code, 200)
        cam_info = get_resp.json()
        self.assertEqual(cam_info["name"], "Loading Dock")

        # 4. Update Camera
        update_resp = self.client.put(
            "/api/cameras/cam_dock",
            json={"name": "Loading Dock South (HD)"}
        )
        self.assertEqual(update_resp.status_code, 200)
        self.assertEqual(update_resp.json()["camera"]["name"], "Loading Dock South (HD)")

        # 5. Toggle Stream
        toggle_resp = self.client.post("/api/cameras/cam_dock/toggle", json={})
        self.assertEqual(toggle_resp.status_code, 200)

        # 6. Delete Camera
        del_resp = self.client.delete("/api/cameras/cam_dock")
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.json()["status"] == "success")

    def test_05_video_file_upload_and_management(self):
        """Verify video recording upload, listing, add as camera, and deletion."""
        # 1. Upload mock mp4 file
        mock_video_bytes = b"\x00\x00\x00 ftypisom\x00\x00\x02\x00isomiso2mp41\x00\x00\x00\x08free"
        upload_resp = self.client.post(
            "/api/videos/upload",
            files={"file": ("perimeter_test.mp4", io.BytesIO(mock_video_bytes), "video/mp4")}
        )
        self.assertEqual(upload_resp.status_code, 200)
        upload_data = upload_resp.json()
        self.assertEqual(upload_data["filename"], "perimeter_test.mp4")
        self.assertIn("web_compatible", upload_data)

        # 2. List Videos & Verify Codec Probing
        list_resp = self.client.get("/api/videos")
        self.assertEqual(list_resp.status_code, 200)
        videos = list_resp.json()
        target_video = next((v for v in videos if v["filename"] == "perimeter_test.mp4"), None)
        self.assertIsNotNone(target_video)
        self.assertIn("codec", target_video)
        self.assertIn("web_compatible", target_video)

        # 3. Verify HEAD request support for HTML5 video element preflight
        head_resp = self.client.head("/videos/perimeter_test.mp4")
        self.assertEqual(head_resp.status_code, 200)
        self.assertEqual(head_resp.headers["content-type"], "video/mp4")

        # 4. Transcode 404 test
        missing_transcode = self.client.post("/api/videos/non_existent.mp4/transcode")
        self.assertEqual(missing_transcode.status_code, 404)

        # 5. Add Video As Active Camera
        add_cam_resp = self.client.post("/api/videos/perimeter_test.mp4/add_as_camera")
        self.assertEqual(add_cam_resp.status_code, 200)
        cam_id = add_cam_resp.json()["camera_id"]
        self.assertIn(cam_id, self.pool.camera_configs)

        # Clean up added camera
        self.pool.remove_camera(cam_id)

        # 6. Delete Video
        del_resp = self.client.delete("/api/videos/perimeter_test.mp4")
        self.assertEqual(del_resp.status_code, 200)

    def test_06_backup_export_and_import_api(self):
        """Verify GET /api/backup/export and POST /api/backup/import."""
        # 1. Export Backup
        export_resp = self.client.get("/api/backup/export")
        self.assertEqual(export_resp.status_code, 200)
        self.assertEqual(export_resp.headers["content-type"], "application/zip")
        zip_content = export_resp.content
        self.assertGreater(len(zip_content), 100)

        # 2. Import Backup
        import_resp = self.client.post(
            "/api/backup/import",
            files={"file": ("restore_test.zip", io.BytesIO(zip_content), "application/zip")}
        )
        self.assertEqual(import_resp.status_code, 200)
        import_data = import_resp.json()
        self.assertEqual(import_data["status"], "success")
        self.assertTrue(import_data["details"]["success"])


if __name__ == "__main__":
    unittest.main()
