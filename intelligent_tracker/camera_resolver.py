#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Environment-Agnostic Camera & Path Resolver.

Provides:
- Bidirectional normalization of video file paths between Docker (/app/data/...) and host (data/...).
- Dynamic hardware device re-mapping using persistent device friendly names (e.g. 'GoPro Webcam').
- Safe resolution of 'real' / 'auto' physical sources that strictly rejects virtual loopback devices (OBS).
"""

import os
import sys
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
        Strips redundant '/app/' container prefixes when running on host.
        """
        if not path_str or not isinstance(path_str, str):
            return ""

        cleaned = path_str.strip().replace("\\", "/")

        # If running on host and path starts with /app/, strip container prefix
        if not CameraDeviceHandler.is_container_environment():
            if cleaned.startswith("/app/"):
                cleaned = cleaned[5:]  # Strip '/app/' -> e.g. 'data/videos/...'
            elif cleaned.startswith("app/"):
                cleaned = cleaned[4:]

        return cleaned

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
        filename = Path(raw).name

        # Candidates to probe
        candidates = [
            Path(raw),
            Path(normalized),
            cls.get_workspace_root() / raw.lstrip("/\\"),
            cls.get_workspace_root() / normalized.lstrip("/\\"),
            cls.get_workspace_root() / "data" / "videos" / filename,
            Path("data/videos") / filename,
        ]

        # Add Docker-specific candidate if running in container
        if CameraDeviceHandler.is_container_environment():
            candidates.append(Path("/app") / normalized.lstrip("/\\"))
            candidates.append(Path("/app/data/videos") / filename)

        for candidate in candidates:
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
    def resolve_camera_source(
        cls,
        source: Union[str, int],
        device_name: Optional[str] = None,
        prefer_physical: bool = True,
    ) -> Tuple[Union[str, int], Dict[str, Any]]:
        """
        Resolve camera source to a live runtime handle (int device index, file path, or URL).

        Args:
            source: Source string, integer, or identifier.
            device_name: Optional persistent friendly name (e.g. 'GoPro Webcam', 'USB Camera 2').
            prefer_physical: If True, filters out virtual devices when resolving 'real'/'auto'.

        Returns:
            Tuple of (resolved_source, metadata_dict)
        """
        s_str = str(source).strip()
        lower_s = s_str.lower()

        # 1. Synthetic / Mock stream
        if lower_s in ("synthetic", "mock", "test"):
            return "synthetic", {"resolved_by": "synthetic", "status": "ok"}

        # 2. RTSP or HTTP Network Stream
        if lower_s.startswith(("rtsp://", "rtsps://", "http://", "https://")):
            return s_str, {"resolved_by": "network_stream", "status": "ok"}

        # 3. Raspberry Pi Libcamera / GStreamer source
        if lower_s in ("libcamera", "rpi", "picamera", "rpicam") or lower_s.startswith("libcamerasrc"):
            return "libcamera", {"resolved_by": "libcamera", "status": "ok"}

        # 4. 'Real' / 'Auto' / 'Physical' auto-detection
        if lower_s in ("real", "auto", "physical", "hardware", "webcam"):
            idx = CameraDeviceHandler.find_first_working_camera(prefer_physical=True)
            if idx is not None:
                dev_name = CameraDeviceHandler.get_friendly_name(idx)
                return idx, {
                    "resolved_by": "auto_detect",
                    "device_index": idx,
                    "device_name": dev_name,
                    "status": "ok",
                }

            # Safety fallback: do NOT blindly default to 0 if device 0 is virtual!
            known_names = CameraDeviceHandler.get_device_names()
            physical_indices = [
                i for i, name in enumerate(known_names)
                if not CameraDeviceHandler.is_virtual_device(name)
            ]
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
            }

        # 5. Numeric index with optional device_name matching
        if s_str.isdigit() or isinstance(source, int):
            target_idx = int(source)
            known_names = CameraDeviceHandler.get_device_names()

            # If friendly name is provided, verify whether indices shifted
            if device_name:
                clean_target_name = device_name.strip().lower()
                for cur_idx, name in enumerate(known_names):
                    if clean_target_name in name.lower():
                        if cur_idx != target_idx:
                            logger.info(
                                "Hardware device '%s' shifted from index #%d to index #%d",
                                device_name, target_idx, cur_idx
                            )
                        return cur_idx, {
                            "resolved_by": "device_name_match",
                            "device_index": cur_idx,
                            "device_name": name,
                            "original_index": target_idx,
                            "status": "ok",
                        }

            # Fallback to configured numeric index
            resolved_name = known_names[target_idx] if target_idx < len(known_names) else f"USB Camera {target_idx}"
            is_virt = CameraDeviceHandler.is_virtual_device(resolved_name)
            return target_idx, {
                "resolved_by": "numeric_index",
                "device_index": target_idx,
                "device_name": resolved_name,
                "is_virtual": is_virt,
                "status": "ok",
            }

        # 6. Friendly name substring match (e.g. 'gopro', 'usb camera 2')
        known_names = CameraDeviceHandler.get_device_names()
        for i, name in enumerate(known_names):
            if lower_s in name.lower():
                return i, {
                    "resolved_by": "friendly_name_string",
                    "device_index": i,
                    "device_name": name,
                    "status": "ok",
                }

        # 7. Video file source (e.g. .mp4, .avi, or container path)
        resolved_file, err_code, attempted = cls.resolve_file_source(s_str)
        if resolved_file:
            return resolved_file, {
                "resolved_by": "file_system",
                "file_path": resolved_file,
                "status": "ok",
            }

        # File missing or invalid
        return s_str, {
            "resolved_by": "unresolved_file",
            "status": "error",
            "error_code": err_code or "FILE_NOT_FOUND",
            "attempted_paths": attempted,
        }

