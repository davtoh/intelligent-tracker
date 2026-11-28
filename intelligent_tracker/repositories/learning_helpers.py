"""Pure bbox, matching, and parameter helpers for ``learning_repo``."""

import json
import time
from typing import Any, Optional


def _serialize_bbox(bbox: Any, raw_json: str = "") -> str:
    """Serialize a 4-element bbox sequence to JSON string."""
    if raw_json:
        return str(raw_json).strip()
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        return json.dumps([int(round(float(v))) for v in bbox])
    return ""


def _parse_bbox_json(raw: str | None) -> list[int] | None:
    """Parse ``bbox_json`` into a 4-int list or None."""
    if not raw:
        return None
    try:
        vals = json.loads(raw)
        if isinstance(vals, list) and len(vals) == 4:
            return [int(v) for v in vals]
    except (TypeError, ValueError):
        pass
    return None


def _bbox_iou(a: list[int] | None, b: list[int] | None) -> float:
    """Compute IoU between two ``[x, y, w, h]`` boxes."""
    if not a or not b:
        return 0.0
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax1 + aw, bx1 + bw), min(ay1 + ah, by1 + bh)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = max(1, aw * ah + bw * bh - inter)
    return inter / union


def _matches_review_candidate(
    row: dict[str, Any],
    track_id: int | None,
    media_offset_sec: float | None,
    target_bbox: list[int] | None,
) -> bool:
    """Return True if a pending ``review_queue`` row matches the Studio/ROI target."""
    if track_id is not None and int(row.get("track_id") or 0) == int(track_id):
        if media_offset_sec is None:
            return True
        row_offset = float(row.get("media_offset_sec") or 0.0)
        return abs(row_offset - float(media_offset_sec)) <= 5.0
    if media_offset_sec is not None:
        row_offset = float(row.get("media_offset_sec") or 0.0)
        if abs(row_offset - float(media_offset_sec)) <= 2.0:
            row_bbox = _parse_bbox_json(row.get("bbox_json"))
            if target_bbox is None or row_bbox is None:
                return True
            return _bbox_iou(row_bbox, target_bbox) >= 0.3
    return False


def _build_review_insert_params(
    camera_id: str, track_id: int, crop_path: str, suggested_entity_id: Optional[int],
    suggested_name: str, suggested_category: str, similarity: float, status: str,
    video_filename: str, media_offset_sec: float, bbox: Any,
    frame_width: int, frame_height: int, run_id: str, reason: str, kwargs: dict[str, Any],
) -> tuple[Any, ...]:
    """Build parameter tuple for ``_INSERT_REVIEW_SQL``."""
    sim = float(kwargs.get("similarity_score", similarity))
    ent_id = suggested_entity_id if suggested_entity_id is not None else kwargs.get("matched_entity_id")
    s_name = (suggested_name or kwargs.get("matched_entity_name", "")).strip()
    s_cat = (suggested_category or kwargs.get("matched_category", "")).strip()
    bbox_str = _serialize_bbox(bbox, str(kwargs.get("bbox_json", "")))
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    resolved_reason = str(reason or kwargs.get("reason") or "borderline").strip() or "borderline"
    return (
        camera_id, track_id, crop_path.strip(), now, ent_id, s_name, s_cat,
        sim, status.strip(), str(video_filename or "").strip(), float(media_offset_sec or 0.0),
        bbox_str, int(frame_width or 0), int(frame_height or 0), str(run_id or "").strip(),
        resolved_reason,
    )
