#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Camera Auto-Discovery & Source Diagnostics.

Provides dual auto-discovery capabilities:
1. Physical USB webcams & local capture devices (DirectShow, V4L2, AVFoundation).
2. LAN network cameras via ONVIF WS-Discovery (UDP 3702) & RTSP port scanning (554, 8554, 8000).
3. Pre-configured vendor RTSP URL builders with credential encoding (Hikvision, Tapo, EZVIZ, Dahua, Generic).
4. One-click connection testing and live snapshot extraction.
"""

import os
import sys
import time
import socket
import select
import logging
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any

import cv2
import numpy as np

from intelligent_tracker.events import frame_to_base64

logger = logging.getLogger("intelligent_tracker.discovery")

# Standard ONVIF WS-Discovery Probe Message (XML SOAP)
WS_DISCOVERY_PROBE_XML = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Envelope xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
    'xmlns="http://www.w3.org/2003/05/soap-envelope">'
    '<Header>'
    '<wsa:MessageID xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">'
    'uuid:c8b4172a-1dd1-11b2-a083-000c299c8f00</wsa:MessageID>'
    '<wsa:To xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">'
    'urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>'
    '<wsa:Action xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">'
    'http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>'
    '</Header>'
    '<Body>'
    '<Probe xmlns="http://schemas.xmlsoap.org/ws/2005/04/discovery">'
    '<Types xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
    'dn:NetworkVideoTransmitter</Types>'
    '</Probe>'
    '</Body>'
    '</Envelope>'
)

WS_DISCOVERY_MULTICAST_GROUP = "239.255.255.250"
WS_DISCOVERY_PORT = 3702


@dataclass
class DiscoveredCamera:
    """Represents a discovered video source device."""
    id: str
    name: str
    source: Any
    type: str  # 'usb', 'onvif', 'rtsp_scan', 'synthetic'
    ip: Optional[str] = None
    port: Optional[int] = None
    resolution: Optional[str] = None
    fps: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)
    status: str = "available"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize discovered camera to dictionary."""
        return asdict(self)


def find_physical_cameras(max_devices: int = 6) -> List[DiscoveredCamera]:
    """
    Probes physical hardware indices to detect connected USB webcams
    and local video capture devices.

    Args:
        max_devices: Maximum device index count to probe (default: 6).

    Returns:
        List of DiscoveredCamera objects for detected devices.
    """
    discovered: List[DiscoveredCamera] = []
    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else 0

    for idx in range(max_devices):
        try:
            cam = cv2.VideoCapture(idx, backend) if backend else cv2.VideoCapture(idx)
            if cam.isOpened():
                ret, frame = cam.read()
                w = int(cam.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
                h = int(cam.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
                fps = float(cam.get(cv2.CAP_PROP_FPS) or 30.0)
                cam.release()

                if ret and frame is not None and frame.size > 0:
                    device_id = f"usb_{idx}"
                    discovered.append(DiscoveredCamera(
                        id=device_id,
                        name=f"USB Camera {idx}",
                        source=idx,
                        type="usb",
                        resolution=f"{w}x{h}",
                        fps=round(fps, 1),
                        details={
                            "index": idx,
                            "backend": "DirectShow" if sys.platform.startswith("win") else "V4L2/Default",
                        },
                    ))
            else:
                cam.release()
        except Exception as e:
            logger.debug("Probing device index %d failed: %s", idx, e)

    return discovered


def probe_onvif_devices(
    timeout: float = 1.5,
    multicast_ip: str = WS_DISCOVERY_MULTICAST_GROUP,
    port: int = WS_DISCOVERY_PORT,
) -> List[DiscoveredCamera]:
    """
    Broadcasts ONVIF WS-Discovery SOAP Probe message over UDP
    and listens for network video transmitter (NVT) responses.

    Args:
        timeout: Socket listening timeout in seconds.
        multicast_ip: WS-Discovery multicast address (239.255.255.250).
        port: WS-Discovery UDP port (3702).

    Returns:
        List of discovered ONVIF cameras.
    """
    discovered: List[DiscoveredCamera] = []
    seen_ips = set()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)

    try:
        sock.sendto(WS_DISCOVERY_PROBE_XML.encode("utf-8"), (multicast_ip, port))
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            ready = select.select([sock], [], [], 0.3)
            if not ready[0]:
                continue

            try:
                data, addr = sock.recvfrom(65535)
                ip = addr[0]
                if ip in seen_ips:
                    continue
                seen_ips.add(ip)

                xml_str = data.decode("utf-8", errors="ignore")
                # Parse ONVIF XAddrs or endpoint from response
                xaddr = ""
                if "XAddrs>" in xml_str:
                    try:
                        xaddr = xml_str.split("XAddrs>")[1].split("<")[0].strip()
                    except Exception:
                        pass

                name = f"ONVIF Device ({ip})"
                if "onvif" in xaddr.lower():
                    name = f"ONVIF Camera ({ip})"

                device_id = f"onvif_{ip.replace('.', '_')}"
                discovered.append(DiscoveredCamera(
                    id=device_id,
                    name=name,
                    source=f"rtsp://{ip}:554/live",
                    type="onvif",
                    ip=ip,
                    port=554,
                    details={
                        "xaddr": xaddr,
                        "raw_addr": addr,
                        "onvif_service": xaddr or f"http://{ip}/onvif/device_service",
                    },
                ))
            except socket.timeout:
                break
            except Exception as e:
                logger.debug("Error receiving ONVIF packet: %s", e)
                break
    except Exception as e:
        logger.debug("ONVIF WS-Discovery probe failed: %s", e)
    finally:
        sock.close()

    return discovered


def check_port_open(ip: str, port: int, timeout: float = 0.25) -> bool:
    """Check if TCP port is open on specified IP address with short timeout."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((ip, port))
        return result == 0
    except Exception:
        return False
    finally:
        sock.close()


def get_local_subnet_ips(max_hosts: int = 64) -> Tuple[str, List[str]]:
    """
    Determines the local non-loopback IPv4 address and generates
    candidate host IPs in the local /24 subnet.
    """
    local_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            local_ip = "127.0.0.1"

    if local_ip.startswith("127."):
        return local_ip, ["127.0.0.1"]

    # Generate /24 subnet IPs (bounded by max_hosts)
    parts = local_ip.split(".")
    prefix = ".".join(parts[:3])
    current_host = int(parts[3])

    # Sample around local host IP first for speed
    candidates = []
    # Immediate neighbors
    for offset in range(-15, 16):
        h = current_host + offset
        if 1 <= h <= 254:
            candidates.append(f"{prefix}.{h}")

    # Common router and device IPs
    for common in [1, 2, 10, 20, 50, 100, 200, 254]:
        ip_str = f"{prefix}.{common}"
        if ip_str not in candidates:
            candidates.append(ip_str)

    # Remaining hosts up to max_hosts
    for h in range(1, 255):
        ip_str = f"{prefix}.{h}"
        if ip_str not in candidates:
            candidates.append(ip_str)
        if len(candidates) >= max_hosts:
            break

    return local_ip, candidates


def discover_rtsp_devices(
    subnet_ips: Optional[List[str]] = None,
    ports: Tuple[int, ...] = (554, 8554),
    timeout: float = 0.25,
    max_workers: int = 32,
) -> List[DiscoveredCamera]:
    """
    Scans local subnet IP addresses for open RTSP streaming ports (554, 8554).
    """
    discovered: List[DiscoveredCamera] = []
    if subnet_ips is None:
        _, subnet_ips = get_local_subnet_ips()

    tasks = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for ip in subnet_ips:
            for port in ports:
                tasks.append(executor.submit(
                    lambda _ip, _p: (_ip, _p, check_port_open(_ip, _p, timeout=timeout)),
                    ip, port
                ))

        for future in as_completed(tasks):
            try:
                ip, port, is_open = future.result()
                if is_open:
                    device_id = f"rtsp_{ip.replace('.', '_')}_{port}"
                    discovered.append(DiscoveredCamera(
                        id=device_id,
                        name=f"Network Camera ({ip}:{port})",
                        source=f"rtsp://{ip}:{port}/live",
                        type="rtsp_scan",
                        ip=ip,
                        port=port,
                        details={"open_port": port},
                    ))
            except Exception as e:
                logger.debug("RTSP scan task failed: %s", e)

    return discovered


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

    if not results and mock_fallback:
        results.append(DiscoveredCamera(
            id="synthetic_01",
            name="Synthetic Test Feed (Simulation)",
            source="synthetic",
            type="synthetic",
            resolution="640x480",
            fps=30.0,
            details={"notes": "Synthetic fallback camera for automated testing"},
        ))

    return results


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
    # 1. Handle synthetic feed immediately
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

    # 2. Fast reachability check for network RTSP/HTTP streams to prevent FFmpeg 30s block
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

    # 3. Try opening physical or network source
    cap = None
    try:
        backend = cv2.CAP_DSHOW if (isinstance(source, int) and sys.platform.startswith("win")) else 0
        if backend:
            cap = cv2.VideoCapture(source, backend)
        else:
            cap = cv2.VideoCapture(source)

        if not cap.isOpened():
            return {
                "success": False,
                "source": str(source),
                "error": "Could not open video capture device or RTSP stream",
            }

        # Read test frame
        ret, frame = cap.read()
        if not ret or frame is None or frame.size == 0:
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
            "snapshot_base64": snapshot,
        }
    except Exception as e:
        return {
            "success": False,
            "source": str(source),
            "error": str(e),
        }
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


def build_preset_rtsp_url(
    preset: str,
    ip: str,
    port: int = 554,
    username: str = "",
    password: str = "",
    channel: int = 1,
    stream: str = "main",
) -> str:
    """
    Constructs vendor-specific RTSP stream URLs with URL-encoded credentials.

    Supported Presets:
    - hikvision: `rtsp://{user}:{pass}@{ip}:{port}/Streaming/Channels/{channel}01` (main) or `02` (sub)
    - tapo:      `rtsp://{user}:{pass}@{ip}:{port}/stream1` (HD) or `/stream2` (SD)
    - ezviz:     `rtsp://admin:{verification_code}@{ip}:{port}/h264/ch{channel}/main`
    - dahua:     `rtsp://{user}:{pass}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype={0|1}`
    - generic:   `rtsp://{user}:{pass}@{ip}:{port}/live`

    Args:
        preset: Vendor preset name.
        ip: Camera IP address or hostname.
        port: RTSP port (default 554).
        username: Username / admin account.
        password: Password or verification code.
        channel: Channel index (default 1).
        stream: 'main' or 'sub'.

    Returns:
        Formatted RTSP URL string.
    """
    preset = (preset or "generic").strip().lower()
    user_enc = urllib.parse.quote(username, safe="") if username else ""
    pass_enc = urllib.parse.quote(password, safe="") if password else ""

    auth_part = ""
    if user_enc and pass_enc:
        auth_part = f"{user_enc}:{pass_enc}@"
    elif user_enc:
        auth_part = f"{user_enc}@"

    netloc = f"{auth_part}{ip}:{port}" if port != 554 else f"{auth_part}{ip}"

    if preset in ("hikvision", "hik"):
        stream_suffix = "01" if stream.lower() == "main" else "02"
        return f"rtsp://{netloc}/Streaming/Channels/{channel}{stream_suffix}"

    elif preset in ("tapo", "tp-link"):
        stream_path = "stream1" if stream.lower() == "main" else "stream2"
        return f"rtsp://{netloc}/{stream_path}"

    elif preset in ("ezviz",):
        # EZVIZ commonly uses 'admin' as user with camera verification code
        auth_ez = f"admin:{pass_enc}@" if pass_enc else (auth_part or "")
        netloc_ez = f"{auth_ez}{ip}:{port}" if port != 554 else f"{auth_ez}{ip}"
        stream_suffix = "main" if stream.lower() == "main" else "sub"
        return f"rtsp://{netloc_ez}/h264/ch{channel}/{stream_suffix}"

    elif preset in ("dahua", "imou"):
        subtype = 0 if stream.lower() == "main" else 1
        return f"rtsp://{netloc}/cam/realmonitor?channel={channel}&subtype={subtype}"

    else:
        # Generic RTSP
        return f"rtsp://{netloc}/live"


CAMERA_PRESETS = [
    {
        "id": "hikvision",
        "name": "Hikvision NVR / IP Camera",
        "default_port": 554,
        "template": "rtsp://{user}:{pass}@{ip}:554/Streaming/Channels/{channel}01",
        "notes": "Main stream uses {channel}01, sub-stream uses {channel}02",
    },
    {
        "id": "tapo",
        "name": "TP-Link Tapo (C200 / C310 / C500)",
        "default_port": 554,
        "template": "rtsp://{user}:{pass}@{ip}:554/stream1",
        "notes": "stream1 = 1080p/2K HD, stream2 = 360p SD. Create camera account in Tapo App settings.",
    },
    {
        "id": "ezviz",
        "name": "EZVIZ Security Camera",
        "default_port": 554,
        "template": "rtsp://admin:{verification_code}@{ip}:554/h264/ch1/main",
        "notes": "Username is always 'admin', password is the 6-character Verification Code printed on camera sticker.",
    },
    {
        "id": "dahua",
        "name": "Dahua / Imou IP Camera",
        "default_port": 554,
        "template": "rtsp://{user}:{pass}@{ip}:554/cam/realmonitor?channel={channel}&subtype=0",
        "notes": "subtype=0 for main stream, subtype=1 for sub stream.",
    },
    {
        "id": "generic",
        "name": "Generic RTSP Stream / NVR Channel",
        "default_port": 554,
        "template": "rtsp://{user}:{pass}@{ip}:{port}/live",
        "notes": "Standard RTSP endpoint URI.",
    },
]
