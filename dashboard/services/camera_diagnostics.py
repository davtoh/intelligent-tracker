#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Central Camera Health & Diagnostics Service.

Provides:
- Thread-safe tracking of camera stream health, failure states, and stack traces.
- Diagnostic error placeholder JPEG synthesis for unopenable or hung feeds.
- Hardware probe and targeted lock release orchestration.
"""

import time
import logging
import threading
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Union

import cv2
import numpy as np

from dashboard.services.logger_manager import DeduplicatingLogger

logger = logging.getLogger("intelligent_tracker.dashboard.services.camera_diagnostics")


@dataclass
class CameraHealthReport:
    """Structured health and error snapshot for an individual camera channel."""
    camera_id: str
    status: str = "online"  # online, error, degraded, reconnecting, paused, hibernating
    last_error: Optional[str] = None
    error_code: str = "OK"  # OK, FILE_NOT_FOUND, DEVICE_LOCKED, RTSP_TIMEOUT, NO_FRAMES_DECODED, CONFIG_ERROR
    traceback: Optional[str] = None
    suggested_action: Optional[str] = None
    attempted_paths: List[str] = field(default_factory=list)
    failure_count: int = 0
    fps: float = 0.0
    last_updated: float = field(default_factory=time.time)
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CameraHealthManager:
    """
    Singleton service managing camera channel operational telemetry,
    error tracking, failure diagnoses, and hardware release actions.
    """
    _instance = None
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._reports: Dict[str, CameraHealthReport] = {}
        self._initialized = True

    def set_online(self, camera_id: str, fps: float = 0.0, diagnostics: Optional[Dict[str, Any]] = None):
        """Mark camera channel healthy and reset failure counters."""
        with self._lock:
            report = self._reports.setdefault(camera_id, CameraHealthReport(camera_id=camera_id))
            was_error = (report.status == "error")
            report.status = "online"
            report.last_error = None
            report.error_code = "OK"
            report.traceback = None
            report.suggested_action = None
            report.failure_count = 0
            report.fps = round(fps, 1)
            report.last_updated = time.time()
            if diagnostics:
                report.diagnostics.update(diagnostics)
            if was_error:
                DeduplicatingLogger().reset(f"camera_error:{camera_id}")

    def set_error(
        self,
        camera_id: str,
        error_msg: str,
        error_code: str = "CONFIG_ERROR",
        traceback_str: Optional[str] = None,
        suggested_action: Optional[str] = None,
        attempted_paths: Optional[List[str]] = None,
        diagnostics: Optional[Dict[str, Any]] = None,
    ):
        """Record a failure event with diagnostic metadata and remediation hints."""
        with self._lock:
            report = self._reports.setdefault(camera_id, CameraHealthReport(camera_id=camera_id))
            report.status = "error"
            report.last_error = error_msg
            report.error_code = error_code
            report.traceback = traceback_str
            report.suggested_action = suggested_action or self._deduce_remediation(error_code, error_msg)
            report.failure_count += 1
            report.fps = 0.0
            report.last_updated = time.time()
            if attempted_paths:
                report.attempted_paths = list(attempted_paths)
            if diagnostics:
                report.diagnostics.update(diagnostics)
            DeduplicatingLogger().warning_once(
                f"camera_error:{camera_id}",
                "Camera [%s] reported error (%s): %s",
                camera_id,
                error_code,
                error_msg,
                target_logger=logger,
            )

    def get_health(self, camera_id: str) -> CameraHealthReport:
        """Retrieve health snapshot for a camera channel."""
        with self._lock:
            if camera_id not in self._reports:
                return CameraHealthReport(camera_id=camera_id, status="unknown")
            return self._reports[camera_id]

    def list_reports(self) -> Dict[str, Dict[str, Any]]:
        """Return all tracked camera channel health snapshots."""
        with self._lock:
            return {cid: rep.to_dict() for cid, rep in self._reports.items()}

    def _deduce_remediation(self, error_code: str, error_msg: str) -> str:
        """Produce helpful troubleshooting guidance based on error code."""
        if error_code == "FILE_NOT_FOUND":
            return "Video file missing on host. Ensure the file is placed in data/videos/ or update the path in Cameras Manager."
        elif error_code == "DEVICE_LOCKED":
            return "Camera hardware is locked by another process. Click 'Release Blocked' or select an available device."
        elif error_code == "RTSP_TIMEOUT":
            return "Network RTSP connection timed out. Verify camera IP, credentials, port 554, and RTSP stream URL."
        elif error_code == "NO_FRAMES_DECODED":
            return "Video source connected but no valid frames received. Verify video codec or physical sensor connection."
        return "Check camera configuration in Cameras Manager (#modal-camera-manager)."

    def create_error_placeholder_jpeg(
        self,
        camera_id: str,
        name: str = "Camera",
        width: int = 640,
        height: int = 480,
    ) -> bytes:
        """Render a dark glass-styled diagnostic error frame displaying error details."""
        report = self.get_health(camera_id)
        img = np.zeros((height, width, 3), dtype=np.uint8)
        img[:] = (22, 26, 35)  # Dark slate background

        # Red accent top banner
        cv2.rectangle(img, (0, 0), (width, 8), (0, 70, 230), -1)

        # Warning icon and status
        err_code = report.error_code if report.error_code != "OK" else "OFFLINE"
        cv2.putText(img, f"[!] {err_code}", (40, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 90, 255), 2)

        # Camera identifier & label
        display_name = f"{name} ({camera_id})"
        cv2.putText(img, display_name[:45], (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (240, 240, 240), 2)

        # Error details
        err_msg = report.last_error or "Source unavailable or configuration mismatch"
        cv2.putText(img, err_msg[:50], (40, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (160, 175, 200), 1)
        if len(err_msg) > 50:
            cv2.putText(img, err_msg[50:100], (40, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (160, 175, 200), 1)

        # Actionable hint
        hint = report.suggested_action or "Click 'Diagnose' or check Cameras Manager."
        cv2.putText(img, "Action:", (40, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 215, 255), 1)
        cv2.putText(img, hint[:60], (40, 310), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 215, 230), 1)
        if len(hint) > 60:
            cv2.putText(img, hint[60:120], (40, 335), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 215, 230), 1)

        # Footer badge
        cv2.putText(img, "Intelligent Tracker VMS Diagnostics", (40, height - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 115, 130), 1)

        ret, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return buf.tobytes() if ret else b""

    @classmethod
    def release_device_lock(cls, source: Union[str, int]) -> Dict[str, Any]:
        """Release DirectShow COM or process lock on a camera device."""
        from intelligent_tracker.camera_tool import release_camera_by_index

        try:
            idx = int(source)
            return release_camera_by_index(idx, force=False)
        except (ValueError, TypeError):
            # Non-numeric source (e.g. RTSP or file), return status
            return {"status": "skipped", "message": f"Source '{source}' is not a local DirectShow index."}

