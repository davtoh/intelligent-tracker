"""Concurrent RTSP Port Scanning Module.

Scans local subnet IP addresses concurrently using a thread pool
for open RTSP streaming ports (e.g. 554, 8554).
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

from intelligent_tracker.discovery.network import check_port_open, get_local_subnet_ips
from intelligent_tracker.discovery.types import DiscoveredCamera

logger = logging.getLogger("intelligent_tracker.discovery.rtsp")


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

