"""Camera hardware discovery and device source resolution utilities."""

from typing import List, Optional, Union
import cv2

from intelligent_tracker.camera_device import CameraDeviceHandler


def is_physical_camera(cap: cv2.VideoCapture) -> bool:
    """Determine if an open VideoCapture corresponds to a physical hardware webcam

    delivering real visual data.
    """
    if not cap or not cap.isOpened():
        return False
    for prop in (
        cv2.CAP_PROP_BRIGHTNESS,
        cv2.CAP_PROP_CONTRAST,
        cv2.CAP_PROP_SHARPNESS,
        cv2.CAP_PROP_GAIN,
        cv2.CAP_PROP_SATURATION,
    ):
        val = cap.get(prop)
        if val >= 0.0:
            return True
    try:
        ret, frame = cap.read()
        if ret and CameraDeviceHandler.validate_frame(frame):
            return True
    except Exception:
        pass
    return False


def find_physical_cameras(max_devices: int = 5) -> List[int]:
    """Probe camera device indices (0..max_devices-1) and return indices of physical webcams."""
    cams = CameraDeviceHandler.discover_usb_cameras(max_devices=max_devices)
    return [c["index"] for c in cams]


def find_first_real_camera(max_devices: int = 5) -> Optional[int]:
    """Probe camera device indices (0..max_devices-1) and return the first working index."""
    return CameraDeviceHandler.find_first_working_camera(max_devices=max_devices)


def resolve_camera_source(source: Union[str, int]) -> Union[str, int]:
    """Resolve camera source string or integer:

    - If 'auto', 'real', 'physical', 'hardware', or 'webcam':
      Automatically finds and returns index of the first camera delivering real sensor data.
    - If friendly name substring (e.g. 'gopro', 'obs'):
      Resolves to matching device index.
    - If numeric index (e.g. 0, 1, '0', '1'):
      Strictly preserves the configured index without alteration.
    - If synthetic/mock/file/rtsp:
      Preserved as-is.
    """
    from intelligent_tracker.camera_resolver import CameraPathResolver

    resolved, meta = CameraPathResolver.resolve_camera_source(source)
    if isinstance(resolved, int):
        dev_name = meta.get("device_name") or CameraDeviceHandler.get_friendly_name(resolved)
        print(f"[INFO] Resolved camera source '{source}' to device index #{resolved} ({dev_name})")
    return resolved


__all__ = [
    "is_physical_camera",
    "find_physical_cameras",
    "find_first_real_camera",
    "resolve_camera_source",
]

