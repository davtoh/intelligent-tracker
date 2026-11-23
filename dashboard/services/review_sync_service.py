"""Bidirectional Sync Service between ``#review`` Queue and Video Studio ``video_runs``."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _update_track_labels_in_frames(
    frames: list[dict[str, Any]],
    *,
    track_id: int,
    media_offset_sec: float | None,
    entity_id: int | None,
    entity_name: str,
    category: str,
) -> int:
    """Update matching track identity fields inside ``frame_detections``."""
    updated = 0
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        frame_time = float(frame.get("time") or 0.0)
        if track_id <= 0 and media_offset_sec is not None and abs(frame_time - media_offset_sec) > 2.0:
            continue
        for trk in frame.get("tracks") or []:
            if not isinstance(trk, dict):
                continue
            if track_id > 0 and int(trk.get("track_id") or 0) != track_id:
                continue
            if entity_id is not None:
                trk["entity_id"] = int(entity_id)
            if entity_name:
                trk["entity_name"] = entity_name
                trk["identity_label"] = entity_name
            if category:
                trk["entity_category"] = category
                trk["category"] = category
            updated += 1
    return updated


def _upsert_report_entity(
    report: dict[str, Any],
    *,
    entity_id: int | None,
    entity_name: str,
    category: str,
) -> bool:
    """Ensure ``report['entities']`` reflects the resolved entity identity."""
    if not isinstance(report, dict) or entity_id is None or not entity_name:
        return False
    entities = report.setdefault("entities", [])
    if not isinstance(entities, list):
        return False
    for entry in entities:
        ent = entry.get("entity") if isinstance(entry, dict) else None
        if isinstance(ent, dict) and int(ent.get("id") or 0) == int(entity_id):
            ent["name"] = entity_name
            if category:
                ent["category"] = category
            return True
    entities.append({
        "entity": {"id": int(entity_id), "name": entity_name, "category": category or "person"},
        "total_sightings": 1,
    })
    report["unique_entities_identified"] = len(entities)
    return True


def _resolve_target_runs(db: Any, video_filename: str, run_id: str) -> list[dict[str, Any]]:
    """Load matching ``video_runs`` rows with ``frame_detections`` hydrated."""
    if run_id and hasattr(db, "get_video_run"):
        run = db.get_video_run(run_id, video_filename=video_filename or None, include_detections=True)
        if run:
            return [run]
    if video_filename and hasattr(db, "list_video_runs"):
        return db.list_video_runs(video_filename=video_filename, include_detections=True)
    return []


def _resolve_identity_fields(
    db: Any, item: dict[str, Any], entity_id: int | None, entity_name: str, category: str,
) -> tuple[int | None, str, str]:
    """Resolve entity_id, entity_name, and category from args or DB."""
    resolved_id = entity_id if entity_id is not None else item.get("suggested_entity_id")
    resolved_name = (entity_name or item.get("suggested_name") or "").strip()
    resolved_cat = (category or item.get("suggested_category") or "").strip()
    if resolved_id is not None and not resolved_name and hasattr(db, "get_entity"):
        ent = db.get_entity(int(resolved_id))
        if ent:
            resolved_name = str(ent.get("name") or "").strip()
            resolved_cat = resolved_cat or str(ent.get("category") or "").strip()
    return (int(resolved_id) if resolved_id is not None else None), resolved_name, resolved_cat


def sync_review_resolution_to_video_runs(
    db: Any, *, item: dict[str, Any] | None, action: str,
    entity_id: int | None = None, entity_name: str = "", category: str = "",
) -> dict[str, Any]:
    """Propagate a ``#review`` resolution back to matching ``video_runs`` records."""
    if db is None or not item:
        return {"synced_runs": [], "updated_tracks": 0, "video_filename": ""}
    video_filename = str(item.get("video_filename") or "").strip()
    run_id = str(item.get("run_id") or "").strip()
    if (not video_filename and not run_id) or action == "dismiss":
        return {"synced_runs": [], "updated_tracks": 0, "video_filename": video_filename}

    rid_int, resolved_name, resolved_cat = _resolve_identity_fields(db, item, entity_id, entity_name, category)
    track_id = int(item.get("track_id") or 0)
    offset = float(item["media_offset_sec"]) if item.get("media_offset_sec") is not None else None
    synced_runs: list[str] = []
    updated_tracks = 0
    for run in _resolve_target_runs(db, video_filename, run_id):
        rid = str(run.get("run_id") or "")
        frames, report = run.get("frame_detections"), run.get("report")
        trk_hits = _update_track_labels_in_frames(
            frames, track_id=track_id, media_offset_sec=offset,
            entity_id=rid_int, entity_name=resolved_name, category=resolved_cat,
        ) if isinstance(frames, list) else 0
        rep_changed = _upsert_report_entity(
            report if isinstance(report, dict) else {},
            entity_id=rid_int, entity_name=resolved_name, category=resolved_cat,
        )
        if (trk_hits > 0 or rep_changed) and hasattr(db, "update_video_run_payload"):
            db.update_video_run_payload(rid, report=report if rep_changed else None, frame_detections=frames if trk_hits > 0 else None)
            synced_runs.append(rid)
            updated_tracks += trk_hits
    return {"synced_runs": synced_runs, "updated_tracks": updated_tracks, "video_filename": video_filename}


def sync_studio_feedback_to_review_queue(
    db: Any,
    *,
    action: str,
    camera_id: str | None = None,
    video_filename: str | None = None,
    media_offset_sec: float | None = None,
    track_id: int | None = None,
    bbox: Any = None,
) -> dict[str, Any]:
    """Auto-resolve matching pending ``review_queue`` items when Studio/ROI tags commit."""
    if db is None or not hasattr(db, "auto_resolve_matching_review_items"):
        return {"resolved_review_ids": [], "resolved_count": 0}
    target_status = "dismissed" if action == "discourage" else "confirmed"
    try:
        matched = db.auto_resolve_matching_review_items(
            video_filename=str(video_filename or "").strip(),
            camera_id=str(camera_id or "").strip(),
            track_id=track_id,
            media_offset_sec=media_offset_sec,
            bbox=bbox,
            status=target_status,
            reviewed_by="video_studio",
        )
    except Exception as exc:
        logger.debug("Review queue auto-resolve skipped: %s", exc)
        return {"resolved_review_ids": [], "resolved_count": 0}
    ids = [int(m["id"]) for m in matched if m.get("id") is not None]
    return {"resolved_review_ids": ids, "resolved_count": len(ids)}
