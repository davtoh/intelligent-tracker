#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OS-specific hardware camera device name enumeration helpers."""

import json
import logging
import os
import subprocess
from typing import List

logger = logging.getLogger("intelligent_tracker.camera_device")


def get_windows_device_names() -> List[str]:
    """Enumerate DirectShow camera friendly names via Windows Registry."""
    names: List[str] = []
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
                            if fname:
                                names.append(str(fname))
                        except OSError:
                            pass
                    i += 1
                except OSError:
                    break
    except Exception as e:
        logger.debug("Windows DirectShow registry enumeration error: %s", e)
    return names


def get_linux_device_names() -> List[str]:
    """Enumerate V4L2 camera friendly names from /sys/class/video4linux."""
    names: List[str] = []
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


def get_darwin_device_names() -> List[str]:
    """Bounded macOS camera enumeration via system_profiler SPCameraDataType."""
    names: List[str] = []
    try:
        proc = subprocess.run(
            ["system_profiler", "SPCameraDataType", "-json"],
            capture_output=True, text=True, timeout=3.0, check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            return names
        payload = json.loads(proc.stdout)
        for item in payload.get("SPCameraDataType", []):
            if isinstance(item, dict):
                name = str(item.get("_name") or item.get("spcamera_model-id") or "").strip()
                if name and name not in names:
                    names.append(name)
    except Exception as e:
        logger.debug("macOS SPCameraDataType enumeration error: %s", e)
    return names
