"""Physical Hardware & USB Webcam Discovery Module.

Probes local video capture indices across OS-specific backends
(DirectShow on Windows, V4L2 on Linux, AVFoundation on macOS).
"""

import sys
from collections.abc import Collection
from typing import Any, Dict, List, Optional

from intelligent_tracker.camera_device import CameraDeviceHandler
from intelligent_tracker.discovery.types import DiscoveredCamera


def find_physical_cameras(
    max_devices: int = 6,
    active_indices: Optional[Collection[int]] = None,
    active_devices: Optional[Dict[int, Dict[str, Any]]] = None,
) -> List[DiscoveredCamera]:
    """Probe physical USB webcams while skipping already-active pool indices."""
    discovered: List[DiscoveredCamera] = []
    usb_devs = CameraDeviceHandler.discover_usb_cameras(
        max_devices=max_devices,
        active_indices=active_indices,
        active_devices=active_devices,
    )
    backend_default = "DirectShow" if sys.platform.startswith("win") else "V4L2"
    for dev in usb_devs:
        idx = dev["index"]
        in_use = bool(dev.get("in_use", False))
        discovered.append(DiscoveredCamera(
            id=f"usb_{idx}",
            name=dev.get("name") or f"USB Camera {idx}",
            source=idx,
            type="usb",
            resolution=dev.get("resolution", "640x480"),
            fps=dev.get("fps", 30.0),
            status="in_use" if in_use else "available",
            details={
                "index": idx,
                "backend": dev.get("backend", backend_default),
                "is_virtual": dev.get("is_virtual", False),
                "in_use": in_use,
            },
        ))
    return discovered

