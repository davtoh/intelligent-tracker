"""Per-camera custom pipeline configuration builder."""

from typing import Any

_TRACKER_TUNING_KEYS = (
    "min_hits",
    "iou_threshold",
    "max_disappeared",
    "high_conf_threshold",
    "low_conf_threshold",
)


def build_custom_cfg(cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Extract detector, tracker, and Re-ID override sections from a camera config entry."""
    custom_cfg: dict[str, Any] = {}
    det_dict: dict[str, Any] = {}
    if cfg.get("detector"):
        det_dict["model"] = cfg["detector"]
    for src, dst in (("confidence", "confidence"), ("classes", "classes"), ("agnostic_nms", "agnostic_nms")):
        if cfg.get(src) is not None:
            det_dict[dst] = cfg[src]
    if det_dict:
        custom_cfg["detector"] = det_dict

    trk_dict: dict[str, Any] = {}
    if cfg.get("tracker"):
        trk_dict["type"] = cfg["tracker"]
    nested_trk = cfg.get("tracker_config")
    for key in _TRACKER_TUNING_KEYS:
        val = cfg.get(key)
        if val is None and isinstance(nested_trk, dict):
            val = nested_trk.get(key)
        if val is not None:
            trk_dict[key] = val
    if trk_dict:
        custom_cfg["tracker"] = trk_dict

    if cfg.get("tracked_categories") is not None:
        custom_cfg["reid"] = {"tracked_categories": cfg["tracked_categories"]}
    return custom_cfg or None
