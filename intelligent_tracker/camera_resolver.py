#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Environment-Agnostic Camera & Path Resolver.

Provides:
- Bidirectional normalization of video file paths between Docker (/app/data/...) and host (data/...).
- Dynamic hardware device re-mapping using persistent device friendly names (e.g. 'GoPro Webcam').
- Safe resolution of 'real' / 'auto' physical sources that strictly rejects virtual loopback devices (OBS).
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any

from intelligent_tracker.camera_device import CameraDeviceHandler

logger = logging.getLogger("intelligent_tracker.camera_resolver")

# Project root directory (intelligent_tracker repository root)
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


class CameraPathResolver:
    """
    Environment-agnostic camera source and storage path resolver.
    Guarantees container-host parity and resilient device indexing across reboots.
    """

    @staticmethod
    def get_workspace_root() -> Path:
        """Return the absolute Path to the workspace root directory."""
        return WORKSPACE_ROOT

    @classmethod
    def normalize_source_path(cls, path_str: str) -> str:
        """
        Normalize video file paths to cross-platform POSIX relative standards where possible.
        Strips redundant '/app/' container prefixes and host-absolute workspace prefixes.
        """
        if not path_str or not isinstance(path_str, str):
            return ""

        cleaned = path_str.strip().replace("\\", "/")
        if cleaned.startswith("./"):
            cleaned = cleaned[2:]

        ws_prefix = cls.get_workspace_root().as_posix().rstrip("/") + "/"
        if cleaned.lower().startswith(ws_prefix.lower()):
            cleaned = cleaned[len(ws_prefix):]
        elif not CameraDeviceHandler.is_container_environment() or cleaned.startswith(("/app/data/", "app/data/")):
            if cleaned.startswith("/app/"):
                cleaned = cleaned[5:]
            elif cleaned.startswith("app/"):
                cleaned = cleaned[4:]

        return cleaned

    @classmethod
    def _build_file_candidates(cls, raw: str, normalized: str, filename: str) -> List[Path]:
        """Construct ordered candidate file paths across host and container environments."""
        ws_root = cls.get_workspace_root()
        candidates = [
            Path(raw),
            Path(normalized),
            ws_root / raw.lstrip("/\\"),
            ws_root / normalized.lstrip("/\\"),
            ws_root / "data" / "videos" / filename,
            Path("data/videos") / filename,
        ]
        if CameraDeviceHandler.is_container_environment():
            candidates.append(Path("/app") / normalized.lstrip("/\\"))
            candidates.append(Path("/app/data/videos") / filename)
        return candidates

    @classmethod
    def resolve_file_source(cls, source_path: str) -> Tuple[Optional[str], Optional[str], List[str]]:
        """
        Search for a video file source across host and container paths.

        Returns:
            Tuple of (resolved_path_or_None, error_code_or_None, attempted_paths_list)
        """
        attempted: List[str] = []
        raw = str(source_path).strip()
        if not raw:
            return None, "EMPTY_SOURCE", attempted

        normalized = cls.normalize_source_path(raw)
        filename = Path(normalized).name
        for candidate in cls._build_file_candidates(raw, normalized, filename):
            cand_str = str(candidate)
            if cand_str not in attempted:
                attempted.append(cand_str)
            try:
                if candidate.is_file():
                    logger.debug("Resolved video file '%s' to '%s'", raw, candidate)
                    return str(candidate.resolve()), None, attempted
            except (OSError, ValueError):
                continue

        logger.warning("Video file not found for source '%s'. Attempted: %s", raw, attempted)
        return None, "FILE_NOT_FOUND", attempted

    @classmethod
    def _resolve_auto_camera(cls, prefer_physical: bool = True) -> Tuple[Union[str, int], Dict[str, Any]]:
        """Resolve 'real'/'auto' sources while preferring non-virtual cameras."""
        idx = CameraDeviceHandler.find_first_working_camera(prefer_physical=prefer_physical)
        if idx is not None:
            return idx, {
                "resolved_by": "auto_detect",
                "device_index": idx,
                "device_name": CameraDeviceHandler.get_friendly_name(idx),
                "status": "ok",
            }
        known_names = CameraDeviceHandler.get_device_names()
        physical_indices = [i for i, n in enumerate(known_names) if not CameraDeviceHandler.is_virtual_device(n)]
        if physical_indices:
            fallback_idx = physical_indices[0]
            fallback_name = known_names[fallback_idx]
            logger.warning("Auto-detect had no open stream; falling back to physical device #%d (%s)", fallback_idx, fallback_name)
            return fallback_idx, {
                "resolved_by": "physical_registry_fallback",
                "device_index": fallback_idx,
                "device_name": fallback_name,
                "status": "ok",
            }
        logger.error("No physical camera found; virtual device present at index 0 rejected for 'real'")
        return 0, {
            "resolved_by": "emergency_fallback",
            "device_index": 0,
            "status": "warning_virtual_camera",
            "error": "NO_PHYSICAL_CAMERA_AVAILABLE",
            "error_code": "NO_PHYSICAL_CAMERA_AVAILABLE",
        }

    @classmethod
    def _resolve_numeric_camera(
        cls, target_idx: int, device_name: Optional[str]
    ) -> Tuple[Union[str, int], Dict[str, Any]]:
        """Resolve a numeric camera index with friendly-name drift remapping and registry metadata."""
        known_names = CameraDeviceHandler.get_device_names()
        if device_name:
            clean_target = device_name.strip().lower()
            for cur_idx, name in enumerate(known_names):
                if clean_target in name.lower():
                    if cur_idx != target_idx:
                        logger.info("Hardware device '%s' shifted from index #%d to index #%d", device_name, target_idx, cur_idx)
                    return cur_idx, {
                        "resolved_by": "device_name_match",
                        "device_index": cur_idx,
                        "device_name": name,
                        "original_index": target_idx,
                        "status": "ok",
                    }
        in_registry = (0 <= target_idx < len(known_names)) if known_names else None
        resolved_name = known_names[target_idx] if in_registry else f"USB Camera {target_idx}"
        return target_idx, {
            "resolved_by": "numeric_index",
            "device_index": target_idx,
            "device_name": resolved_name,
            "is_virtual": CameraDeviceHandler.is_virtual_device(resolved_name),
            "device_in_registry": in_registry,
            "available_device_count": len(known_names),
            "status": "ok",
        }

    @classmethod
    def resolve_camera_source(
        cls,
        source: Union[str, int],
        device_name: Optional[str] = None,
        prefer_physical: bool = True,
    ) -> Tuple[Union[str, int], Dict[str, Any]]:
        """Resolve camera source to a live runtime handle (int device index, file path, or URL)."""
        s_str = str(source).strip()
        lower_s = s_str.lower()
        if lower_s in ("synthetic", "mock", "test"):
            return "synthetic", {"resolved_by": "synthetic", "status": "ok"}
        if lower_s.startswith(("rtsp://", "rtsps://", "http://", "https://")):
            return s_str, {"resolved_by": "network_stream", "status": "ok"}
        if lower_s in ("libcamera", "rpi", "picamera", "rpicam") or lower_s.startswith("libcamerasrc"):
            return "libcamera", {"resolved_by": "libcamera", "status": "ok"}
        if lower_s in ("real", "auto", "physical", "hardware", "webcam"):
            return cls._resolve_auto_camera(prefer_physical=prefer_physical)
        if s_str.isdigit() or isinstance(source, int):
            return cls._resolve_numeric_camera(int(source), device_name)

        for i, name in enumerate(CameraDeviceHandler.get_device_names()):
            if lower_s in name.lower():
                return i, {"resolved_by": "friendly_name_string", "device_index": i, "device_name": name, "status": "ok"}

        resolved_file, err_code, attempted = cls.resolve_file_source(s_str)
        if resolved_file:
            return resolved_file, {"resolved_by": "file_system", "file_path": resolved_file, "status": "ok"}
        return s_str, {
            "resolved_by": "unresolved_file",
            "status": "error",
            "error_code": err_code or "FILE_NOT_FOUND",
            "attempted_paths": attempted,
        }

