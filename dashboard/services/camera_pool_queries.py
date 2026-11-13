#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - CameraPool Property & Query Mixins.

Provides backward-compatible state/telemetry properties and stream queries
for CameraPool while keeping the main facade under method/line budgets.
"""

from typing import Any

from dashboard.services.camera_diagnostics import CameraHealthManager
from dashboard.stream_manager import StreamManager


def build_camera_status_row(
    cam_id: str,
    cfg: dict[str, Any],
    mgr: StreamManager | None,
) -> dict[str, Any]:
    """Assemble the public status and telemetry dictionary for one camera channel."""
    telemetry = mgr.get_latest_telemetry() if mgr else {}
    is_running = mgr.is_running if mgr else False
    res_str = "640x480"
    is_synth = False
    if mgr and mgr.video_source:
        res_str = f"{mgr.video_source.width}x{mgr.video_source.height}"
        is_synth = mgr.video_source.is_synthetic

    health = CameraHealthManager().get_health(cam_id)
    health_status = (
        "paused"
        if not cfg.get("enabled", True)
        else (health.status if health.status != "unknown" else ("online" if is_running else "offline"))
    )
    if is_running and health.status == "error":
        health_status = "error"

    return {
        "id": cam_id,
        "name": cfg.get("name", f"Camera {cam_id}"),
        "source": str(cfg.get("source", "synthetic")),
        "type": cfg.get("type", "synthetic" if is_synth else "rtsp"),
        "detector": cfg.get("detector", "yolov8"),
        "tracker": cfg.get("tracker", "centroid"),
        "confidence": cfg.get("confidence", 0.40),
        "classes": cfg.get("classes"),
        "enabled": cfg.get("enabled", True),
        "status": health_status,
        "error_code": health.error_code if health.error_code != "OK" else None,
        "error_message": health.last_error,
        "suggested_action": health.suggested_action,
        "device_name": cfg.get("device_name") or (cfg.get("details") or {}).get("device_name"),
        "fps": round(telemetry.get("fps", 0.0), 1),
        "resolution": res_str,
        "active_tracks_count": len(telemetry.get("active_tracks", [])),
        "source_type": "synthetic" if is_synth else "physical",
    }


class CameraPoolStateMixin:
    """Property facade exposing live ``camera_configs`` and ``streams`` mappings."""

    @property
    def camera_configs(self) -> dict[str, dict[str, Any]]:
        """Return the active camera configuration mapping."""
        return self._config_store.camera_configs

    @camera_configs.setter
    def camera_configs(self, value: dict[str, dict[str, Any]]) -> None:
        """Replace the active camera configuration mapping."""
        self._config_store.camera_configs = value

    @property
    def streams(self) -> dict[str, Any]:
        """Return the active StreamManager mapping."""
        return self._coordinator.streams

    @streams.setter
    def streams(self, value: dict[str, Any]) -> None:
        """Replace the active StreamManager mapping."""
        self._coordinator.streams = value


class CameraPoolQueryMixin:
    """Read-only properties, stream lookup, and gallery reload helpers for CameraPool."""

    @property
    def primary_stream(self) -> StreamManager | None:
        """Return the primary or first active StreamManager for backward compatibility."""
        return self._coordinator.get_stream(None)

    @property
    def rsac_manager(self) -> Any | None:
        """Return the primary stream's RSACManager."""
        sm = self.primary_stream
        return sm.rsac_manager if sm else None

    @property
    def active_learning(self) -> Any | None:
        """Return the primary stream's ActiveLearningManager."""
        sm = self.primary_stream
        return sm.active_learning if sm else None

    @property
    def enrollment_manager(self) -> Any | None:
        """Return the primary stream's UniversalEnrollmentManager."""
        sm = self.primary_stream
        return sm.enrollment_manager if sm else None

    def reload_all_galleries(self) -> None:
        """Reload Re-ID galleries and RSAC policies across all active streams."""
        with self._lock:
            for sm in self.streams.values():
                if sm.gallery_matcher:
                    sm.gallery_matcher.reload_gallery()
                if sm.rsac_manager:
                    sm.rsac_manager.reload()

    def get_stream(self, camera_id: str | None = None) -> StreamManager | None:
        """Retrieve StreamManager for ``camera_id``, or primary stream when omitted."""
        return self._coordinator.get_stream(camera_id)

    def get_latest_frame_jpeg(self, camera_id: str | None = None) -> bytes | None:
        """Return latest encoded JPEG frame bytes for a camera channel."""
        mgr = self.get_stream(camera_id)
        return mgr.get_latest_frame_jpeg() if mgr else None

    def list_cameras(self) -> list[dict[str, Any]]:
        """Return real-time status and telemetry for all configured cameras."""
        with self._lock:
            return [
                build_camera_status_row(cam_id, cfg, self.streams.get(cam_id))
                for cam_id, cfg in self.camera_configs.items()
            ]

