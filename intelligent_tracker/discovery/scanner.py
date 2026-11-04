"""Multi-Protocol Camera Discovery Aggregator.

Coordinates concurrent hardware USB capture probing, ONVIF WS-Discovery,
and LAN RTSP port sweeping into a unified device inventory.
"""

from typing import List

from intelligent_tracker.camera_device import CameraDeviceHandler
from intelligent_tracker.discovery.network import get_local_subnet_ips
from intelligent_tracker.discovery.onvif import probe_onvif_devices
from intelligent_tracker.discovery.rtsp import discover_rtsp_devices
from intelligent_tracker.discovery.types import DiscoveredCamera
from intelligent_tracker.discovery.usb import find_physical_cameras


def _resolve_empty_fallbacks(mock_fallback: bool) -> List[DiscoveredCamera]:
    """Generates synthetic or Docker notice fallback camera when no devices are detected."""
    if CameraDeviceHandler.is_container_environment():
        return [
            DiscoveredCamera(
                id="docker_notice",
                name="Host USB Camera Pass-through Required (Docker)",
                source="synthetic",
                type="synthetic",
                resolution="640x480",
                fps=30.0,
                details={
                    "notes": (
                        "Container has no /dev/video* devices mapped. "
                        "Run on host OS (`python main.py`) to access USB webcams."
                    )
                },
            )
        ]
    if mock_fallback:
        return [
            DiscoveredCamera(
                id="synthetic_01",
                name="Synthetic Test Feed (Simulation)",
                source="synthetic",
                type="synthetic",
                resolution="640x480",
                fps=30.0,
                details={"notes": "Synthetic fallback camera for automated testing"},
            )
        ]
    return []


def discover_all_cameras(
    include_usb: bool = True,
    include_onvif: bool = True,
    include_lan_rtsp: bool = True,
    mock_fallback: bool = False,
) -> List[DiscoveredCamera]:
    """
    Central discovery routine scanning USB webcams, ONVIF devices,
    and open RTSP LAN ports concurrently.
    """
    results: List[DiscoveredCamera] = []

    if include_usb:
        usb_cams = find_physical_cameras()
        results.extend(usb_cams)

    if include_onvif:
        onvif_cams = probe_onvif_devices(timeout=1.0)
        results.extend(onvif_cams)

    if include_lan_rtsp:
        # Avoid redundant scans for already found ONVIF IPs
        existing_ips = {c.ip for c in results if c.ip}
        _, subnet_ips = get_local_subnet_ips(max_hosts=32)
        filtered_ips = [ip for ip in subnet_ips if ip not in existing_ips]
        rtsp_cams = discover_rtsp_devices(subnet_ips=filtered_ips, timeout=0.2, max_workers=24)
        results.extend(rtsp_cams)

    if not results:
        results.extend(_resolve_empty_fallbacks(mock_fallback))

    return results

