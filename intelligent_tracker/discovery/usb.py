"""Physical Hardware & USB Webcam Discovery Module.

Probes local video capture indices across OS-specific backends
(DirectShow on Windows, V4L2 on Linux, AVFoundation on macOS).
"""

import sys
from typing import List

from intelligent_tracker.camera_device import CameraDeviceHandler
from intelligent_tracker.discovery.types import DiscoveredCamera


def find_physical_cameras(max_devices: int = 6) -> List[DiscoveredCamera]:
    """
    Probes physical hardware indices to detect connected USB webcams
    and local video capture devices using CameraDeviceHandler.

    Args:
        max_devices: Maximum device index count to probe (default: 6).

    Returns:
        List of DiscoveredCamera objects for detected devices.
    """
    discovered: List[DiscoveredCamera] = []
    usb_devs = CameraDeviceHandler.discover_usb_cameras(max_devices=max_devices)
    for dev in usb_devs:
        idx = dev["index"]
        device_id = f"usb_{idx}"
        dev_name = dev.get("name") or f"USB Camera {idx}"
        is_virt = dev.get("is_virtual", False)
        backend_default = "DirectShow" if sys.platform.startswith("win") else "V4L2"
        discovered.append(DiscoveredCamera(
            id=device_id,
            name=dev_name,
            source=idx,
            type="usb",
            resolution=dev.get("resolution", "640x480"),
            fps=dev.get("fps", 30.0),
            details={
                "index": idx,
                "backend": dev.get("backend", backend_default),
                "is_virtual": is_virt,
            },
        ))
    return discovered

