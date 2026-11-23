#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Persistent Camera Configuration Store.

Manages thread-safe loading, saving, seeding (including legacy ``STREAM_SOURCE``
bootstrapping), and atomic in-memory updates for ``configs/cameras.json``.
"""

import json
import logging
import os
import threading
import time
from typing import Any

from intelligent_tracker.camera_resolver import CameraPathResolver
from intelligent_tracker.pipeline.config import is_synthetic_source

logger = logging.getLogger("intelligent_tracker.camera_config_store")


def _normalize_cfg_source(source: Any) -> Any:
    """Normalize local file source paths for cross-platform config portability."""
    if not isinstance(source, str):
        return source
    cleaned = source.strip()
    if not cleaned or cleaned.lower().startswith(("rtsp://", "rtsps://", "http://", "https://")):
        return cleaned
    return CameraPathResolver.normalize_source_path(cleaned) if ("/" in cleaned or "\\" in cleaned) else cleaned


def heal_non_synthetic_mock_cameras(configs: dict[str, dict[str, Any]]) -> bool:
    """Upgrade non-synthetic ``detector='mock'`` entries and normalize portable source paths."""
    changed = False
    notice = configs.get("docker_notice")
    if isinstance(notice, dict) and is_synthetic_source(notice.get("source"), notice.get("type")):
        configs.pop("docker_notice", None)
        changed = True
    for entry in configs.values():
        if not isinstance(entry, dict):
            continue
        norm_src = _normalize_cfg_source(entry.get("source"))
        if norm_src != entry.get("source"):
            entry["source"], changed = norm_src, True
        det = str(entry.get("detector", "")).strip().lower()
        if det == "mock" and not is_synthetic_source(entry.get("source"), entry.get("type")):
            entry["detector"], changed = "yolov8", True
    return changed


def _seed_default_camera() -> dict[str, Any]:
    """Build the initial default primary camera entry, honoring STREAM_SOURCE."""
    source = os.environ.get("STREAM_SOURCE", "").strip() or "synthetic"
    is_synth = source.lower() in ("synthetic", "mock")
    cam_type = "synthetic" if is_synth else ("usb" if source.isdigit() else "rtsp")
    return {
        "id": "cam_01",
        "name": "Main Entrance (Synthetic)" if is_synth else "Main Entrance",
        "source": source,
        "type": cam_type,
        "enabled": True,
        "armed": False,
        "detector": "mock" if is_synth else "yolov8",
        "tracker": "centroid",
    }


def _normalize_camera_payload(data: Any) -> tuple[dict[str, dict[str, Any]], bool]:
    """Unwrap ``{"cameras": ...}`` payloads and filter malformed entries."""
    if isinstance(data, dict) and isinstance(data.get("cameras"), (list, dict)):
        data = data["cameras"]
    if isinstance(data, list):
        return {c["id"]: c for c in data if isinstance(c, dict) and isinstance(c.get("id"), str) and c["id"].strip()}, True
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, dict)}, True
    return {}, False


class CameraConfigStore:
    """Thread-safe JSON-backed repository for camera channel configurations."""

    def __init__(self, config_file: str = "configs/cameras.json", lock: Any = None) -> None:
        self.config_file = config_file
        self._lock = lock or threading.RLock()
        self.camera_configs: dict[str, dict[str, Any]] = {}

    def load_cameras(self) -> tuple[dict[str, dict[str, Any]], bool]:
        """Load camera configs from JSON; returns ``(configs, seeded_default)``."""
        with self._lock:
            loaded: dict[str, dict[str, Any]] = {}
            configs_loaded = False
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, "r", encoding="utf-8") as f:
                        loaded, configs_loaded = _normalize_camera_payload(json.load(f))
                except Exception as exc:
                    logger.warning("Failed to load %s: %s", self.config_file, exc)

            seeded = False
            if not configs_loaded:
                loaded = {"cam_01": _seed_default_camera()}
                seeded = True

            healed = heal_non_synthetic_mock_cameras(loaded)
            self.camera_configs.clear()
            self.camera_configs.update(loaded)
            if healed and configs_loaded:
                self.save_cameras()
            return self.camera_configs, seeded

    def save_cameras(self) -> None:
        """Persist current camera configurations atomically to JSON."""
        with self._lock:
            snapshot = [dict(cfg) for cfg in self.camera_configs.values()]
        os.makedirs(os.path.dirname(self.config_file) or ".", exist_ok=True)
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save camera configuration to %s: %s", self.config_file, exc)

    def build_and_store_entry(
        self,
        camera_id: str,
        name: str,
        source: Any,
        cam_type: str = "rtsp",
        detector: str | None = None,
        tracker: str | None = None,
        confidence: float | None = None,
        classes: list[str] | None = None,
        enabled: bool = True,
        details: dict[str, Any] | None = None,
        device_name: str | None = None,
        armed: bool = False,
    ) -> dict[str, Any]:
        """Create or replace a camera config entry in memory under lock."""
        resolved_device_name = device_name or (details.get("device_name") if details else None)
        norm_source = _normalize_cfg_source(source)
        is_synth = str(cam_type).lower() in ("synthetic", "mock") or str(norm_source).lower() in ("synthetic", "mock")
        det_default = "mock" if is_synth else "yolov8"
        entry = {
            "id": camera_id, "name": name, "source": norm_source, "type": cam_type,
            "enabled": enabled, "armed": bool(armed),
            "detector": detector or det_default, "tracker": tracker or "centroid",
            "confidence": float(confidence) if confidence is not None else 0.40,
            "classes": classes, "details": details or {},
            "device_name": resolved_device_name, "created_at": time.time(),
        }
        with self._lock:
            self.camera_configs[camera_id] = entry
        return entry

    def update_entry(self, camera_id: str, **updates: Any) -> tuple[bool, bool, dict[str, Any] | None]:
        """Apply partial updates to an existing entry; returns ``(found, needs_restart, cfg)``."""
        with self._lock:
            if camera_id not in self.camera_configs:
                return False, False, None

            cfg = self.camera_configs[camera_id]
            if updates.get("source") is not None:
                updates["source"] = _normalize_cfg_source(updates["source"])
            restart_keys = ("source", "enabled", "device_name", "detector", "tracker", "confidence", "classes")
            needs_restart = any(updates.get(k) is not None and updates[k] != cfg.get(k) for k in restart_keys)

            field_map = {"cam_type": "type"}
            for key, val in updates.items():
                if val is None:
                    continue
                target_key = field_map.get(key, key)
                cfg[target_key] = float(val) if target_key == "confidence" else val

            return True, needs_restart, cfg

    def remove_entry(self, camera_id: str) -> dict[str, Any] | None:
        """Remove and return a camera config entry under lock."""
        with self._lock:
            return self.camera_configs.pop(camera_id, None)
