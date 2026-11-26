"""Canonical SourceRef Builder and Normalizer (ADR-15)."""

import json
from typing import Any


def snapshot_path_to_url(snapshot_path: str | None) -> str:
    """Convert a local crop/snapshot path into a safe ``/api/crops/<name>`` URL."""
    raw = str(snapshot_path or "").strip()
    if not raw:
        return ""
    if raw.startswith(("/api/crops/", "http://", "https://")):
        return raw
    norm = raw.replace("\\", "/")
    parts = [part for part in norm.split("/") if part]
    if not parts or ".." in parts:
        return ""
    basename = parts[-1]
    if not basename or basename in {".", ".."}:
        return ""
    return f"/api/crops/{basename}"


def _normalize_bbox(bbox: Any) -> list[int] | None:
    """Normalize a JSON string or 4-element sequence into ``[x1, y1, x2, y2]`` ints."""
    raw = bbox
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(raw, (list, tuple)) or len(raw) < 4:
        return None
    try:
        return [int(round(float(v))) for v in raw[:4]]
    except (TypeError, ValueError):
        return None


def _resolve_media_offset(media_offset_sec: float | None, video_filename: str) -> float | None:
    """Return rounded media offset when video-scoped or explicitly non-zero."""
    if media_offset_sec is None or media_offset_sec == "":
        return None
    try:
        offset = round(float(media_offset_sec), 3)
    except (TypeError, ValueError):
        return None
    return offset if (video_filename or offset != 0.0) else None


def build_source_ref(
    *,
    kind: str = "",
    camera_id: str = "",
    video_filename: str = "",
    run_id: str = "",
    media_offset_sec: float | None = None,
    ts: float | int | str | None = None,
    track_id: int | None = None,
    entity_id: int | None = None,
    zone_id: str = "",
    bbox: Any = None,
    snapshot_url: str = "",
    snapshot_path: str = "",
) -> dict[str, Any]:
    """Build a canonical ADR-15 SourceRef dictionary omitting empty values."""
    cam, vfile = str(camera_id or "").strip(), str(video_filename or "").strip()
    resolved_kind = str(kind or "").strip() or ("video" if vfile else ("camera" if cam else ""))
    resolved_snap = str(snapshot_url or "").strip() or snapshot_path_to_url(snapshot_path)
    ref: dict[str, Any] = {
        k: v
        for k, v in (
            ("kind", resolved_kind), ("camera_id", cam), ("video_filename", vfile),
            ("run_id", str(run_id or "").strip()), ("zone_id", str(zone_id or "").strip()),
            ("snapshot_url", resolved_snap),
            ("media_offset_sec", _resolve_media_offset(media_offset_sec, vfile)),
            ("bbox", _normalize_bbox(bbox)),
        )
        if v is not None and v != ""
    }
    if ts is not None and ts != "":
        ref["ts"] = ts
    if track_id is not None:
        ref["track_id"] = int(track_id)
    if entity_id is not None:
        ref["entity_id"] = int(entity_id)
    return ref


def source_ref_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Construct a canonical ``SourceRef`` dictionary from a DB row."""
    raw_meta = row.get("metadata")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    vfile = str(row.get("video_filename") or meta.get("video_filename") or "").strip()
    raw_cam = row.get("camera_id") or ("" if vfile else row.get("source") or "") or ""
    raw_off = row.get("media_offset_sec") if row.get("media_offset_sec") is not None else meta.get("media_offset_sec")
    raw_tid = row.get("track_id") if row.get("track_id") is not None else meta.get("track_id")
    raw_eid = row.get("entity_id")
    snap_path = (
        row.get("snapshot_path") or row.get("crop_path")
        or meta.get("snapshot_path") or meta.get("crop_path") or ""
    )
    return build_source_ref(
        camera_id=str(raw_cam),
        video_filename=vfile,
        run_id=str(row.get("run_id") or meta.get("run_id") or ""),
        media_offset_sec=raw_off,
        ts=row.get("ts") if row.get("ts") is not None else row.get("timestamp"),
        track_id=int(raw_tid) if raw_tid is not None and raw_tid != "" else None,
        entity_id=int(raw_eid) if raw_eid is not None and raw_eid != "" else None,
        zone_id=str(row.get("zone_id") or meta.get("zone_id") or ""),
        bbox=row.get("bbox") if row.get("bbox") not in (None, "") else meta.get("bbox"),
        snapshot_url=str(row.get("snapshot_url") or meta.get("snapshot_url") or ""),
        snapshot_path=str(snap_path),
    )
