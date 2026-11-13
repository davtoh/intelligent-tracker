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

logger = logging.getLogger("intelligent_tracker.camera_config_store")


def _seed_default_camera() -> dict[str, Any]:
    """Build the initial default primary camera entry, honoring STREAM_SOURCE."""
    env_source = os.environ.get("STREAM_SOURCE", "").strip()
    if not env_source:
        return {
            "id": "cam_01",
            "name": "Main Entrance (Synthetic)",
            "source": "synthetic",
            "type": "synthetic",
            "enabled": True,
            "detector": "mock",
            "tracker": "centroid",
        }

    is_synth = env_source.lower() in ("synthetic", "mock")
    if is_synth:
        cam_type = "synthetic"
    elif env_source.isdigit():
        cam_type = "usb"
    else:
        cam_type = "rtsp"

    return {
        "id": "cam_01",
        "name": "Main Entrance (Synthetic)" if is_synth else "Main Entrance",
        "source": env_source,
        "type": cam_type,
        "enabled": True,
        "detector": "mock" if is_synth else "yolov8",
        "tracker": "centroid",
    }


class CameraConfigStore:
    """Thread-safe JSON-backed repository for camera channel configurations."""

    def __init__(
        self,
        config_file: str = "configs/cameras.json",
        lock: Any = None,
    ) -> None:
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
                        data = json.load(f)
                    if isinstance(data, list):
                        loaded = {c["id"]: c for c in data if isinstance(c, dict) and "id" in c}
                        configs_loaded = True
                    elif isinstance(data, dict):
                        loaded = data
                        configs_loaded = True
                except Exception as exc:
                    logger.warning("Failed to load %s: %s", self.config_file, exc)

            seeded = False
            if not configs_loaded or not loaded:
                loaded = {"cam_01": _seed_default_camera()}
                seeded = True

            self.camera_configs.clear()
            self.camera_configs.update(loaded)
            return self.camera_configs, seeded

    def save_cameras(self) -> None:
        """Persist current camera configurations atomically to JSON."""
        with self._lock:
            os.makedirs(os.path.dirname(self.config_file) or ".", exist_ok=True)
            try:
                with open(self.config_file, "w", encoding="utf-8") as f:
                    json.dump(list(self.camera_configs.values()), f, indent=2)
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
    ) -> dict[str, Any]:
        """Create or replace a camera config entry in memory under lock."""
        resolved_device_name = device_name or (details.get("device_name") if details else None)
        is_synth = str(cam_type).lower() in ("synthetic", "mock") or str(source).lower() in ("synthetic", "mock")
        det_default = "mock" if is_synth else "yolov8"
        entry = {
            "id": camera_id,
            "name": name,
            "source": source,
            "type": cam_type,
            "enabled": enabled,
            "detector": detector or det_default,
            "tracker": tracker or "centroid",
            "confidence": float(confidence) if confidence is not None else 0.40,
            "classes": classes,
            "details": details or {},
            "device_name": resolved_device_name,
            "created_at": time.time(),
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
            needs_restart = (
                (updates.get("source") is not None and updates["source"] != cfg.get("source"))
                or (updates.get("enabled") is not None and updates["enabled"] != cfg.get("enabled"))
                or (updates.get("device_name") is not None and updates["device_name"] != cfg.get("device_name"))
                or (updates.get("detector") is not None and updates["detector"] != cfg.get("detector"))
                or (updates.get("tracker") is not None and updates["tracker"] != cfg.get("tracker"))
                or (updates.get("confidence") is not None and updates["confidence"] != cfg.get("confidence"))
                or (updates.get("classes") is not None and updates["classes"] != cfg.get("classes"))
            )

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
