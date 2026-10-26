#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Dual Camera Auto-Discovery, RTSP Presets & Diagnostics (Milestone 7).
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

from intelligent_tracker.discovery import (
    DiscoveredCamera,
    find_physical_cameras,
    probe_onvif_devices,
    discover_rtsp_devices,
    discover_all_cameras,
    test_camera_connection,
    build_preset_rtsp_url,
    check_port_open,
    get_local_subnet_ips,
    CAMERA_PRESETS,
)


class TestCameraDiscovery(unittest.TestCase):

    def test_01_discovered_camera_dataclass(self):
        """Verify DiscoveredCamera attributes and dictionary serialization."""
        cam = DiscoveredCamera(
            id="usb_0",
            name="HD Pro Webcam",
            source=0,
            type="usb",
            resolution="1920x1080",
            fps=30.0,
            details={"vendor": "Logitech"},
        )
        data = cam.to_dict()
        self.assertEqual(data["id"], "usb_0")
        self.assertEqual(data["name"], "HD Pro Webcam")
        self.assertEqual(data["source"], 0)
        self.assertEqual(data["type"], "usb")
        self.assertEqual(data["resolution"], "1920x1080")
        self.assertEqual(data["fps"], 30.0)
        self.assertEqual(data["status"], "available")
        self.assertEqual(data["details"]["vendor"], "Logitech")

    def test_02_build_preset_rtsp_url_hikvision(self):
        """Verify Hikvision RTSP URL construction with URL encoding."""
        # Main stream
        url_main = build_preset_rtsp_url(
            preset="hikvision",
            ip="192.168.1.100",
            port=554,
            username="admin",
            password="pass@123#word",
            channel=2,
            stream="main",
        )
        self.assertEqual(url_main, "rtsp://admin:pass%40123%23word@192.168.1.100/Streaming/Channels/201")

        # Sub stream on non-standard port
        url_sub = build_preset_rtsp_url(
            preset="hikvision",
            ip="10.0.0.50",
            port=8554,
            username="viewer",
            password="secret",
            channel=1,
            stream="sub",
        )
        self.assertEqual(url_sub, "rtsp://viewer:secret@10.0.0.50:8554/Streaming/Channels/102")

    def test_03_build_preset_rtsp_url_tapo(self):
        """Verify TP-Link Tapo stream1 (HD) and stream2 (SD) URLs."""
        url_hd = build_preset_rtsp_url(
            preset="tapo",
            ip="192.168.1.55",
            username="tapo_user",
            password="tapopassword",
            stream="main",
        )
        self.assertEqual(url_hd, "rtsp://tapo_user:tapopassword@192.168.1.55/stream1")

        url_sd = build_preset_rtsp_url(
            preset="tapo",
            ip="192.168.1.55",
            username="tapo_user",
            password="tapopassword",
            stream="sub",
        )
        self.assertEqual(url_sd, "rtsp://tapo_user:tapopassword@192.168.1.55/stream2")

    def test_04_build_preset_rtsp_url_ezviz(self):
        """Verify EZVIZ RTSP URL using verification code."""
        url_ezviz = build_preset_rtsp_url(
            preset="ezviz",
            ip="192.168.1.75",
            password="ABCDEF",
            channel=1,
            stream="main",
        )
        self.assertEqual(url_ezviz, "rtsp://admin:ABCDEF@192.168.1.75/h264/ch1/main")

    def test_05_build_preset_rtsp_url_dahua(self):
        """Verify Dahua realmonitor URL format."""
        url_dahua = build_preset_rtsp_url(
            preset="dahua",
            ip="192.168.1.80",
            username="admin",
            password="password",
            channel=3,
            stream="main",
        )
        self.assertEqual(url_dahua, "rtsp://admin:password@192.168.1.80/cam/realmonitor?channel=3&subtype=0")

    def test_06_build_preset_rtsp_url_generic(self):
        """Verify generic RTSP fallback."""
        url_generic = build_preset_rtsp_url(
            preset="generic",
            ip="10.10.1.20",
            port=554,
            username="operator",
            password="op",
        )
        self.assertEqual(url_generic, "rtsp://operator:op@10.10.1.20/live")

    def test_07_presets_catalog(self):
        """Verify preset metadata registry."""
        self.assertGreaterEqual(len(CAMERA_PRESETS), 5)
        ids = [p["id"] for p in CAMERA_PRESETS]
        self.assertIn("hikvision", ids)
        self.assertIn("tapo", ids)
        self.assertIn("ezviz", ids)
        self.assertIn("dahua", ids)
        self.assertIn("generic", ids)

    def test_08_test_camera_connection_synthetic(self):
        """Verify connection tester on synthetic video feed."""
        res = test_camera_connection("synthetic")
        self.assertTrue(res["success"])
        self.assertEqual(res["resolution"], "640x480")
        self.assertEqual(res["width"], 640)
        self.assertEqual(res["height"], 480)
        self.assertGreaterEqual(res["fps"], 25.0)
        self.assertIsNotNone(res["snapshot_base64"])
        self.assertGreater(len(res["snapshot_base64"]), 100)

    def test_09_test_camera_connection_invalid(self):
        """Verify connection tester handles unreachable or non-existent streams gracefully."""
        res = test_camera_connection("rtsp://192.0.2.1:554/invalid_stream_path", timeout=0.5)
        self.assertFalse(res["success"])
        self.assertIn("error", res)

    def test_10_local_subnet_resolution(self):
        """Verify local subnet IP generation."""
        local_ip, hosts = get_local_subnet_ips(max_hosts=16)
        self.assertIsInstance(local_ip, str)
        self.assertIsInstance(hosts, list)
        self.assertGreater(len(hosts), 0)

    def test_11_discover_all_cameras_mock_fallback(self):
        """Verify discovery returns synthetic test feed when no physical devices are found."""
        results = discover_all_cameras(
            include_usb=False,
            include_onvif=False,
            include_lan_rtsp=False,
            mock_fallback=True,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].type, "synthetic")
        self.assertEqual(results[0].id, "synthetic_01")


if __name__ == "__main__":
    unittest.main()
