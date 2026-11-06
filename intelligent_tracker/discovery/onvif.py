"""ONVIF WS-Discovery Probing Module.

Broadcasts WS-Discovery SOAP Probe messages via UDP multicast
to discover Network Video Transmitters (NVT) conforming to ONVIF standards.
"""

import logging
import select
import socket
import time
from typing import List, Optional, Set, Tuple

from intelligent_tracker.discovery.types import DiscoveredCamera

logger = logging.getLogger("intelligent_tracker.discovery.onvif")

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
    'http://schemas.xmlsoap.org/ws/2005:04:discovery/Probe</wsa:Action>'
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


def _create_multicast_socket(timeout: float) -> socket.socket:
    """Creates and configures a UDP multicast socket for WS-Discovery."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)
    return sock


def _parse_onvif_packet(data: bytes, addr: Tuple[str, int]) -> Optional[DiscoveredCamera]:
    """Parses raw UDP packet bytes into a DiscoveredCamera instance."""
    ip = addr[0]
    xml_str = data.decode("utf-8", errors="ignore")
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
    return DiscoveredCamera(
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
    )


def _collect_onvif_responses(sock: socket.socket, timeout: float) -> List[DiscoveredCamera]:
    """Listens for and collects UDP response packets until timeout expires."""
    discovered: List[DiscoveredCamera] = []
    seen_ips: Set[str] = set()
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

            cam = _parse_onvif_packet(data, addr)
            if cam is not None:
                discovered.append(cam)
        except socket.timeout:
            break
        except Exception as e:
            logger.debug("Error receiving ONVIF packet: %s", e)
            break

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
    sock = _create_multicast_socket(timeout)
    try:
        sock.sendto(WS_DISCOVERY_PROBE_XML.encode("utf-8"), (multicast_ip, port))
        return _collect_onvif_responses(sock, timeout)
    except Exception as e:
        logger.debug("ONVIF WS-Discovery probe failed: %s", e)
        return []
    finally:
        sock.close()
