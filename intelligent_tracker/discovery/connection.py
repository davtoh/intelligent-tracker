"""Camera Source Connection Diagnostics & Frame Snapshot Prober.

Provides one-click connectivity testing, resolution detection, FPS measurement,
and base64 JPEG snapshot generation for video streams and physical capture devices.
"""

import urllib.parse
from typing import Any, Dict, Optional

import cv2
import numpy as np

from intelligent_tracker.camera_device import CameraDeviceHandler
from intelligent_tracker.discovery.network import check_port_open
from intelligent_tracker.events import frame_to_base64


def _test_synthetic_source(source: Any) -> Optional[Dict[str, Any]]:
    """Handles synthetic/mock simulated camera source immediately."""
    if str(source).lower() in ("synthetic", "mock"):
        h, w = 480, 640
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:, :, 0] = np.linspace(0, 180, h)[:, None].astype(np.uint8)
        frame[:, :, 1] = np.linspace(0, 180, w)[None, :].astype(np.uint8)
        cv2.putText(
            frame, "INTELLIGENT TRACKER TEST FEED",
            (40, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2
        )
        return {
            "success": True,
            "source": str(source),
            "resolution": f"{w}x{h}",
            "width": w,
            "height": h,
            "fps": 30.0,
            "snapshot_base64": frame_to_base64(frame),
        }
    return None


def _check_network_reachability(source: Any, timeout: float) -> Optional[Dict[str, Any]]:
    """Fast reachability check for RTSP/HTTP streams to prevent FFmpeg 30s block."""
    if isinstance(source, str) and (source.startswith("rtsp://") or source.startswith("http://")):
        try:
            parsed = urllib.parse.urlparse(source)
            host = parsed.hostname
            port = parsed.port or (554 if source.startswith("rtsp://") else 80)
            if host and not check_port_open(host, port, timeout=min(timeout, 0.4)):
                return {
                    "success": False,
                    "source": str(source),
                    "error": f"Network camera {host}:{port} is unreachable (port closed or host offline)",
                }
        except Exception:
            pass
    return None


def _format_capture_open_error(source: Any) -> str:
    """Provides specific diagnostic if device index is detected but locked."""
    dev_exists = False
    friendly_name = ""
    if isinstance(source, int) or (isinstance(source, str) and source.isdigit()):
        idx = int(source)
        names = CameraDeviceHandler.get_device_names()
        if 0 <= idx < len(names):
            dev_exists = True
            friendly_name = names[idx]

    if dev_exists:
        return (
            f"Device #{source} ('{friendly_name}') was detected, but is currently locked by another "
            f"process or streaming session. Close other video apps or release blocked cameras."
        )
    return f"Could not open video capture device #{source} or RTSP stream (device not present or inaccessible)."


def _decode_snapshot(cap: Any, source: Any, backend_name: str) -> Dict[str, Any]:
    """Reads a single frame from capture device, validates it, and generates JPEG snapshot."""
    ret, frame = cap.read()
    if not ret or not CameraDeviceHandler.validate_frame(frame):
        return {
            "success": False,
            "source": str(source),
            "error": "Stream opened but failed to decode video frame",
        }

    h, w = frame.shape[:2]
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    snapshot = frame_to_base64(frame)

    return {
        "success": True,
        "source": str(source),
        "resolution": f"{w}x{h}",
        "width": w,
        "height": h,
        "fps": round(fps, 1),
        "backend": backend_name,
        "snapshot_base64": snapshot,
    }


def test_camera_connection(source: Any, timeout: float = 3.0) -> Dict[str, Any]:
    """
    Tests connectivity to any video source (USB index, RTSP URL, HTTP URL, or file)
    and returns resolution, frame rate, and a base64 JPEG snapshot for live UI preview.

    Args:
        source: Video source (int device index, RTSP URL string, or file path).
        timeout: Maximum connection timeout in seconds.

    Returns:
        Dictionary with status, metrics, and base64 snapshot.
    """
    synthetic = _test_synthetic_source(source)
    if synthetic is not None:
        return synthetic

    reachability_err = _check_network_reachability(source, timeout)
    if reachability_err is not None:
        return reachability_err

    cap = None
    try:
        cap, backend_name = CameraDeviceHandler.open_camera(source, test_read=True)
        if not cap or not cap.isOpened():
            return {
                "success": False,
                "source": str(source),
                "error": _format_capture_open_error(source),
            }
        return _decode_snapshot(cap, source, backend_name)
    except Exception as e:
        return {
            "success": False,
            "source": str(source),
            "error": str(e),
        }
    finally:
        CameraDeviceHandler.safe_release(cap, settle_delay=0.2)

