"""Network Scanning & Subnet Inspection Utilities.

Provides lightweight socket probes to check TCP port accessibility and
generate candidate IP addresses in local subnets for LAN discovery.
"""

import socket
from typing import List, Tuple


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


def _determine_local_ip() -> str:
    """Determines the local non-loopback IPv4 address."""
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
    return local_ip


def _generate_subnet_candidates(local_ip: str, max_hosts: int) -> List[str]:
    """Generates prioritized candidate host IPs in the local /24 subnet."""
    parts = local_ip.split(".")
    prefix = ".".join(parts[:3])
    current_host = int(parts[3])

    candidates: List[str] = []

    # 1. Immediate neighbors around local host IP first for speed
    for offset in range(-15, 16):
        h = current_host + offset
        if 1 <= h <= 254:
            candidates.append(f"{prefix}.{h}")

    # 2. Common gateway, router, and static camera device IPs
    for common in [1, 2, 10, 20, 50, 100, 200, 254]:
        ip_str = f"{prefix}.{common}"
        if ip_str not in candidates:
            candidates.append(ip_str)

    # 3. Remaining hosts up to max_hosts
    for h in range(1, 255):
        ip_str = f"{prefix}.{h}"
        if ip_str not in candidates:
            candidates.append(ip_str)
        if len(candidates) >= max_hosts:
            break

    return candidates


def get_local_subnet_ips(max_hosts: int = 64) -> Tuple[str, List[str]]:
    """
    Determines the local non-loopback IPv4 address and generates
    candidate host IPs in the local /24 subnet.
    """
    local_ip = _determine_local_ip()
    if local_ip.startswith("127."):
        return local_ip, ["127.0.0.1"]

    candidates = _generate_subnet_candidates(local_ip, max_hosts)
    return local_ip, candidates

