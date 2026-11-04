"""Discovery Type Definitions and Data Representations.

Provides the DiscoveredCamera dataclass used to represent video source devices
discovered via physical hardware, ONVIF WS-Discovery, or RTSP network probing.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional


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

