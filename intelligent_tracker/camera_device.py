#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Sturdy Hardware Camera Device Handler.

Provides centralized, thread-safe camera hardware acquisition, device discovery,
multi-backend fallback (DirectShow -> Media Foundation -> V4L2 -> AVFoundation),
and safe release with driver cooldowns to prevent COM unbind collisions on Windows.
"""

from __future__ import annotations

import os
import sys
import time
import logging
import threading
from typing import Dict, List, Optional, Tuple, Union, Any

import cv2
import numpy as np

logger = logging.getLogger("intelligent_tracker.camera_device")


class CameraDeviceHandler:
    """
    Centralized, thread-safe hardware video capture manager.
    Prevents device blocking, unifies multi-backend fallback, and ensures safe release.
    """

    # Process-wide lock to prevent concurrent device acquisition collisions on Windows COM
    _device_lock = threading.RLock()

    @staticmethod
    def is_container_environment() -> bool:
        """Return True if executing inside a Docker or OCI container."""
        return (
            os.path.exists("/.dockerenv")
            or os.environ.get("CONTAINER") == "docker"
            or os.path.exists("/run/.containerenv")
        )

    @classmethod
    def get_preferred_backends(cls) -> List[int]:
        """Return prioritized list of OpenCV VideoCapture backend APIs for current OS."""
        if sys.platform.startswith("win"):
            # DirectShow first for predictable low-latency frame polling, then Media Foundation, then ANY
            return [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        elif sys.platform.startswith("linux"):
            backend_v4l2 = getattr(cv2, "CAP_V4L2", 0)
            return [backend_v4l2, cv2.CAP_ANY] if backend_v4l2 else [cv2.CAP_ANY]
        elif sys.platform == "darwin":
            backend_av = getattr(cv2, "CAP_AVFOUNDATION", 0)
            return [backend_av, cv2.CAP_ANY] if backend_av else [cv2.CAP_ANY]
        return [cv2.CAP_ANY]

    @classmethod
    def safe_release(cls, cap: Optional[cv2.VideoCapture], settle_delay: float = 0.25) -> None:
        """
        Safely release a cv2.VideoCapture instance and wait for OS driver graph unbind.
        DirectShow COM on Windows requires ~0.25s to teardown before a device can be re-opened.
        """
        acquired = cls._device_lock.acquire(timeout=2.0)
        try:
            if cap is None:
                return
            try:
                if hasattr(cap, "isOpened") and cap.isOpened():
                    cap.release()
                elif hasattr(cap, "release"):
                    cap.release()
            except Exception as e:
                logger.debug("Exception while releasing capture: %s", e)
            finally:
                if sys.platform.startswith("win") and settle_delay > 0:
                    time.sleep(settle_delay)
        finally:
            if acquired:
                cls._device_lock.release()

    @classmethod
    def validate_frame(cls, frame: Optional[np.ndarray], min_std: float = 0.5) -> bool:
        """
        Validate that a captured frame contains real, decoded image data
        rather than an empty buffer, uninitialized array, or pitch-black sensor fault.
        """
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return False
        if frame.ndim >= 2:
            try:
                # Fast variance check: active physical sensors have non-zero lighting variance
                return bool(frame.std() >= min_std or frame.max() > 5)
            except Exception:
                return True
        return True

    @classmethod
    def open_camera(
        cls,
        source: Union[int, str],
        preferred_backend: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        test_read: bool = True,
    ) -> Tuple[Optional[cv2.VideoCapture], str]:
        """
        Open video capture device with automatic backend fallback and dimension configuration.

        Args:
            source: Integer device index, numeric string, file path, or RTSP URL.
            preferred_backend: Optional explicit OpenCV backend (e.g. cv2.CAP_DSHOW).
            width: Optional requested frame width.
            height: Optional requested frame height.
            test_read: If True, tests reading 1 valid frame before returning capture.

        Returns:
            Tuple of (VideoCapture instance or None, backend_name string)
        """
        with cls._device_lock:
            if isinstance(source, str) and source.isdigit():
                source = int(source)

            # File or network RTSP stream
            if isinstance(source, str):
                backend = cv2.CAP_FFMPEG if source.startswith("rtsp://") else 0
                cap = cv2.VideoCapture(source, backend) if backend else cv2.VideoCapture(source)
                if cap and cap.isOpened():
                    cls._configure_resolution(cap, width, height)
                    return cap, "FFMPEG" if backend else "DEFAULT"
                cls.safe_release(cap, settle_delay=0.05)
                return None, "FAILED"

            # Physical device index
            backends = [preferred_backend] if preferred_backend is not None else cls.get_preferred_backends()

            for b in backends:
                try:
                    cap = cv2.VideoCapture(source, b) if b != cv2.CAP_ANY else cv2.VideoCapture(source)
                    if cap and cap.isOpened():
                        if test_read:
                            ret, frame = cap.read()
                            if ret and cls.validate_frame(frame):
                                cls._configure_resolution(cap, width, height)
                                b_name = getattr(cap, "getBackendName", lambda: str(b))()
                                return cap, b_name
                            cls.safe_release(cap, settle_delay=0.15)
                        else:
                            cls._configure_resolution(cap, width, height)
                            b_name = getattr(cap, "getBackendName", lambda: str(b))()
                            return cap, b_name
                    else:
                        cls.safe_release(cap, settle_delay=0.05)
                except Exception as e:
                    logger.debug("Backend %s failed for device #%s: %s", b, source, e)
                    cls.safe_release(None, settle_delay=0.05)

            return None, "FAILED"

    @classmethod
    def _configure_resolution(cls, cap: cv2.VideoCapture, width: Optional[int], height: Optional[int]) -> None:
        """Apply target frame dimensions to capture device if requested."""
        if width and height and cap and cap.isOpened():
            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
            except Exception:
                pass

    @classmethod
    def get_device_names(cls) -> List[str]:
        """
        Enumerate friendly hardware names of connected video devices for current OS.
        Returns a list of device names in device index order.
        """
        if sys.platform.startswith("win"):
            return cls._get_windows_device_names()
        elif sys.platform.startswith("linux"):
            return cls._get_linux_device_names()
        return []

    @classmethod
    def _get_windows_device_names(cls) -> List[str]:
        names = []
        clsid = r"CLSID\{860BB310-5D01-11D0-BD3B-00A0C911CE86}\Instance"
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, clsid) as key:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, sub) as subkey:
                            try:
                                fname, _ = winreg.QueryValueEx(subkey, "FriendlyName")
                                if fname and fname not in names:
                                    names.append(str(fname))
                            except OSError:
                                pass
                        i += 1
                    except OSError:
                        break
        except Exception as e:
            logger.debug("Windows DirectShow registry enumeration error: %s", e)
        return names

    @classmethod
    def _get_linux_device_names(cls) -> List[str]:
        names = []
        try:
            import glob
            for v4l_path in sorted(glob.glob("/sys/class/video4linux/video*")):
                name_file = os.path.join(v4l_path, "name")
                if os.path.isfile(name_file):
                    with open(name_file, "r", encoding="utf-8", errors="ignore") as f:
                        name = f.read().strip()
                        if name:
                            names.append(name)
        except Exception as e:
            logger.debug("Linux v4l2 device name error: %s", e)
        return names

    @classmethod
    def get_friendly_name(cls, index: int) -> str:
        """Return the friendly device name at index, or fallback to 'USB Camera {index}'."""
        names = cls.get_device_names()
        if 0 <= index < len(names):
            return names[index]
        return f"USB Camera {index}"

    @classmethod
    def is_virtual_device(cls, name: str) -> bool:
        """Return True if device name corresponds to a virtual loopback/software camera."""
        lower = str(name).lower()
        virtual_keywords = ("virtual", "obs", "unity", "vysor", "droidcam", "splitcam", "manycam")
        return any(k in lower for k in virtual_keywords)

    @classmethod
    def probe_device(cls, index: int) -> Optional[Dict[str, Any]]:
        """
        Probe a single camera index safely without driver locking.
        Returns device metadata dict or None if invalid.
        """
        with cls._device_lock:
            cap, backend_name = cls.open_camera(index, test_read=True)
            if not cap or not cap.isOpened():
                return None

            try:
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
                fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
                if fps <= 0.0 or np.isnan(fps):
                    fps = 30.0

                friendly_name = cls.get_friendly_name(index)
                is_virt = cls.is_virtual_device(friendly_name)

                return {
                    "index": index,
                    "name": friendly_name,
                    "resolution": f"{w}x{h}",
                    "width": w,
                    "height": h,
                    "fps": round(fps, 1),
                    "backend": backend_name,
                    "valid": True,
                    "is_virtual": is_virt,
                }
            finally:
                cls.safe_release(cap, settle_delay=0.25)

    @classmethod
    def discover_usb_cameras(cls, max_devices: int = 6) -> List[Dict[str, Any]]:
        """
        Probe connected USB/local cameras sequentially with driver settle delays.
        Returns list of working device dictionaries.
        """
        with cls._device_lock:
            discovered = []
            for idx in range(max_devices):
                dev_info = cls.probe_device(idx)
                if dev_info:
                    discovered.append(dev_info)
                if sys.platform.startswith("win"):
                    time.sleep(0.1)
            return discovered

    @classmethod
    def find_first_working_camera(cls, max_devices: int = 6, prefer_physical: bool = True) -> Optional[int]:
        """
        Find and return device index of first working hardware camera delivering valid frames.
        If prefer_physical is True, physical hardware cameras are prioritized over virtual feeds.
        """
        with cls._device_lock:
            working_devices = []
            for idx in range(max_devices):
                dev_info = cls.probe_device(idx)
                if dev_info:
                    working_devices.append(dev_info)
                if sys.platform.startswith("win"):
                    time.sleep(0.1)

            if not working_devices:
                return None

            if prefer_physical:
                physical = [d for d in working_devices if not d.get("is_virtual", False)]
                if physical:
                    chosen = physical[0]
                    logger.info("Selected physical camera #%d (%s, %s)", chosen.get("index"), chosen.get("name"), chosen.get("resolution", "unknown"))
                    return chosen.get("index")

            chosen = working_devices[0]
            logger.info("Selected camera #%d (%s, %s)", chosen.get("index"), chosen.get("name"), chosen.get("resolution", "unknown"))
            return chosen.get("index")

    @classmethod
    def resolve_source(
        cls,
        source: Union[int, str],
        device_name: Optional[str] = None,
        prefer_physical: bool = True,
    ) -> Union[int, str]:
        """
        Resolve source identifier by delegating to canonical CameraPathResolver.

        Preserves backwards-compatibility for callers while enforcing
        Single Source of Truth (SSOT) resolution: container-to-host path normalization,
        dynamic hardware index re-mapping, and virtual camera rejection.
        """
        from intelligent_tracker.camera_resolver import CameraPathResolver

        resolved, _ = CameraPathResolver.resolve_camera_source(
            source, device_name=device_name, prefer_physical=prefer_physical
        )
        return resolved
