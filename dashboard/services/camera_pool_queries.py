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


def snapshot_pool_streams(pool: Any) -> dict[str, Any]:
    """Return a thread-safe shallow copy of ``pool.streams``."""
    if pool is None:
        return {}
    lock = getattr(pool, "_lock", None)
    if lock is not None and hasattr(lock, "__enter__"):
        with lock:
            return dict(getattr(pool, "streams", None) or {})
    return dict(getattr(pool, "streams", None) or {})


def _resolve_health_status(cam_id: str, cfg: dict[str, Any], is_running: bool, mgr: Any = None) -> tuple[str, Any, bool]:
    """Resolve effective camera health status label, CameraHealth snapshot, and hibernation flag."""
    health = CameraHealthManager().get_health(cam_id)
    health_status = (
        "paused"
        if not cfg.get("enabled", True)
        else (health.status if health.status != "unknown" else ("online" if is_running else "offline"))
    )
    if is_running and health.status == "error":
        health_status = "error"
    is_hib = bool(getattr(mgr, "is_hibernating", False)) if mgr else False
    if is_hib and cfg.get("enabled", True):
        svc = getattr(mgr, "_processing_mode_service", None)
        if getattr(svc, "mode", None) == "paused":
            health_status = "paused"
        elif health_status not in ("error", "offline"):
            health_status = "hibernating"
    return health_status, health, is_hib


def build_camera_status_row(
    cam_id: str,
    cfg: dict[str, Any],
    mgr: StreamManager | None,
) -> dict[str, Any]:
    """Assemble the public status and telemetry dictionary for one camera channel."""
    telemetry = mgr.get_latest_telemetry() if mgr else {}
    is_running = mgr.is_running if mgr else False
    res_str = f"{mgr.video_source.width}x{mgr.video_source.height}" if (mgr and mgr.video_source) else "640x480"
    is_synth = bool(mgr and mgr.video_source and mgr.video_source.is_synthetic)
    health_status, health, is_hib = _resolve_health_status(cam_id, cfg, is_running, mgr=mgr)
    rec_state = telemetry.get("recording") or {"camera_id": cam_id, "is_recording": False, "status": "idle"}

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
        "is_hibernating": is_hib,
        "error_code": health.error_code if health.error_code != "OK" else None,
        "error_message": health.last_error,
        "suggested_action": health.suggested_action,
        "device_name": cfg.get("device_name") or (cfg.get("details") or {}).get("device_name"),
        "fps": round(telemetry.get("fps", 0.0), 1),
        "resolution": res_str,
        "active_tracks_count": len(telemetry.get("active_tracks", [])),
        "source_type": "synthetic" if is_synth else "physical",
        "recording": rec_state,
        "armed": bool(getattr(mgr, "is_armed", cfg.get("armed", False))),
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

    @property
    def confidence_engine(self) -> Any | None:
        """Return shared or active stream ConfidenceEngine across multi-camera pools."""
        shared = getattr(self, "_confidence_engine", None)
        if shared is not None:
            return shared
        sm = self.primary_stream
        if sm is not None and getattr(sm, "confidence_engine", None) is not None:
            return sm.confidence_engine
        for stream in snapshot_pool_streams(self).values():
            eng = getattr(stream, "confidence_engine", None)
            if eng is not None:
                return eng
        return None

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

    def get_latest_frame_jpeg(
        self, camera_id: str | None = None, annotated: bool = True
    ) -> bytes | None:
        """Return latest encoded JPEG frame bytes for a camera channel."""
        mgr = self.get_stream(camera_id)
        return mgr.get_latest_frame_jpeg(annotated=annotated) if mgr else None

    def list_cameras(self) -> list[dict[str, Any]]:
        """Return real-time status and telemetry for all configured cameras."""
        with self._lock:
            return [
                build_camera_status_row(cam_id, cfg, self.streams.get(cam_id))
                for cam_id, cfg in self.camera_configs.items()
            ]

    def get_active_usb_indices(self) -> set[int]:
        """Return hardware USB indices currently owned by running streams."""
        indices: set[int] = set()
        with self._lock:
            for cam_id, mgr in (self.streams or {}).items():
                if not mgr or not getattr(mgr, "is_running", False):
                    continue
                cfg = (self.camera_configs or {}).get(cam_id, {})
                src = getattr(mgr, "source_override", None)
                if src is None:
                    src = cfg.get("source")
                if src is None and getattr(mgr, "video_source", None) is not None:
                    src = getattr(mgr.video_source, "source", None)
                if isinstance(src, int) and not isinstance(src, bool):
                    indices.add(src)
                elif isinstance(src, str) and src.strip().isdigit():
                    if str(cfg.get("type", "")).lower() in ("", "usb", "webcam"):
                        indices.add(int(src.strip()))
        return indices

