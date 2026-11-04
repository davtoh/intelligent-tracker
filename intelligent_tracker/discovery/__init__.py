"""Intelligent Tracker - Camera Auto-Discovery & Source Diagnostics Package.

Provides dual auto-discovery capabilities:
1. Physical USB webcams & local capture devices (DirectShow, V4L2, AVFoundation).
2. LAN network cameras via ONVIF WS-Discovery (UDP 3702) & RTSP port scanning (554, 8554, 8000).
3. Pre-configured vendor RTSP URL builders with credential encoding (Hikvision, Tapo, EZVIZ, Dahua, Generic).
4. One-click connection testing and live snapshot extraction.
"""

import logging

from intelligent_tracker.discovery.connection import test_camera_connection
from intelligent_tracker.discovery.network import check_port_open, get_local_subnet_ips
from intelligent_tracker.discovery.onvif import (
    WS_DISCOVERY_MULTICAST_GROUP,
    WS_DISCOVERY_PORT,
    WS_DISCOVERY_PROBE_XML,
    probe_onvif_devices,
)
from intelligent_tracker.discovery.presets import (
    CAMERA_PRESETS,
    build_preset_rtsp_url,
)
from intelligent_tracker.discovery.rtsp import discover_rtsp_devices
from intelligent_tracker.discovery.scanner import discover_all_cameras
from intelligent_tracker.discovery.types import DiscoveredCamera
from intelligent_tracker.discovery.usb import find_physical_cameras

logger = logging.getLogger("intelligent_tracker.discovery")

__all__ = [
    "DiscoveredCamera",
    "find_physical_cameras",
    "probe_onvif_devices",
    "WS_DISCOVERY_PROBE_XML",
    "WS_DISCOVERY_MULTICAST_GROUP",
    "WS_DISCOVERY_PORT",
    "check_port_open",
    "get_local_subnet_ips",
    "discover_rtsp_devices",
    "discover_all_cameras",
    "test_camera_connection",
    "build_preset_rtsp_url",
    "CAMERA_PRESETS",
    "logger",
]

