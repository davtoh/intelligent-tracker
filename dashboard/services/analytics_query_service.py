"""Analytics query helpers for time-bucketed traffic flows and heatmap metadata."""

from typing import Any, Optional

import numpy as np

_COLORMAP_NAMES = {
    2: "JET",
    11: "HOT",
    14: "INFERNO",
    20: "TURBO",
}

_DEFAULT_HEATMAP_STOPS = [
    {"ratio": 0.0, "color": "#1d4ed8", "label": "Low"},
    {"ratio": 0.35, "color": "#06b6d4", "label": "Moderate"},
    {"ratio": 0.7, "color": "#f59e0b", "label": "Elevated"},
    {"ratio": 1.0, "color": "#ef4444", "label": "Peak"},
]


def resolve_bucket_sec(range_sec: int, bucket_sec: Optional[int]) -> int:
    """Resolve an explicit or range-proportional time bucket width in seconds."""
    if bucket_sec is not None:
        return max(1, int(bucket_sec))
    if range_sec <= 900:
        return 60
    if range_sec <= 3600:
        return 300
    if range_sec <= 21600:
        return 900
    if range_sec <= 86400:
        return 3600
    return 21600


def build_heatmap_json(mgr: Any, camera_id: Optional[str]) -> dict[str, Any]:
    """Build enriched JSON metadata payload for the spatial density heatmap."""
    resolved_cam = camera_id or getattr(mgr, "camera_id", None)
    if not mgr.analytics or not mgr.analytics.heatmap:
        return {"density": [], "initialized": False, "camera_id": resolved_cam}
    hm = mgr.analytics.heatmap
    cmap_val = getattr(hm, "colormap", 2)
    cmap_name = (
        _COLORMAP_NAMES.get(int(cmap_val), str(cmap_val))
        if isinstance(cmap_val, int)
        else str(cmap_val)
    )
    return {
        "initialized": True,
        "camera_id": resolved_cam,
        "resolution": [hm.width, hm.height],
        "max_value": float(np.max(hm.density)),
        "mean_value": float(np.mean(hm.density)),
        "colormap": cmap_name,
        "decay_rate": getattr(hm, "decay_rate", None),
        "radius": getattr(hm, "radius", None),
        "stops": _DEFAULT_HEATMAP_STOPS,
    }
