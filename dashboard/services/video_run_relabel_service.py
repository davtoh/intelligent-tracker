#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Retroactive Video Run Relabeling & CachedReplayProvider Invalidation Service."""

import json
import logging
import os
from typing import Any

from dashboard.services.camera_pool_queries import snapshot_pool_streams

logger = logging.getLogger("intelligent_tracker.dashboard.services.video_run_relabel_service")


def invalidate_pool_replay_caches(pool: Any) -> int:
    """Clear CachedReplayProvider and FileDetectionReplayProvider caches across all pool streams."""
    if pool is None:
        return 0
    invalidated = 0
    for sm in snapshot_pool_streams(pool).values():
        for attr in ("_cached_replay_provider", "replay_provider"):
            provider = getattr(sm, attr, None)
            if provider is not None and hasattr(provider, "invalidate"):
                provider.invalidate()
                invalidated += 1
    return invalidated


def _clear_track_identity(trk: dict[str, Any]) -> bool:
    """Clear entity identity fields on a serialized track dictionary."""
    if trk.get("entity_id") is None and trk.get("entity_name") is None and trk.get("identity_label") is None:
        return False
    trk["entity_id"] = None
    trk["entity_name"] = None
    trk["identity_label"] = None
    trk.pop("entity_category", None)
    return True


def _apply_track_identity(trk: dict[str, Any], entity_id: int, name: str, category: str) -> bool:
    """Assign or refresh entity identity fields on a serialized track dictionary."""
    changed = (
        trk.get("entity_id") != entity_id
        or trk.get("entity_name") != name
        or trk.get("identity_label") != name
        or trk.get("entity_category") != category
    )
    trk["entity_id"] = entity_id
    trk["entity_name"] = name
    trk["identity_label"] = name
    trk["entity_category"] = category
    return changed


def _relabel_run_records(
    records: list[dict[str, Any]],
    *,
    filename_matches: bool,
    deleted_entity_id: int | None,
    updated_entity: dict[str, Any] | None,
    discouraged_entity_id: int | None,
    track_id: int | None,
) -> bool:
    """Apply entity mutation relabeling across serialized frame detection records."""
    modified = False
    for rec in records:
        if not isinstance(rec, dict):
            continue
        for trk in rec.get("tracks") or []:
            if not isinstance(trk, dict):
                continue
            eid = trk.get("entity_id")
            tid = trk.get("track_id")
            if deleted_entity_id is not None and eid == deleted_entity_id:
                modified = _clear_track_identity(trk) or modified
            if discouraged_entity_id is not None and (
                (filename_matches and track_id is not None and tid == track_id)
                or (eid == discouraged_entity_id and (track_id is None or tid == track_id))
            ):
                modified = _clear_track_identity(trk) or modified
            if updated_entity is not None:
                ueid = int(updated_entity["id"])
                uname = str(updated_entity.get("name") or "")
                ucat = str(updated_entity.get("category") or "")
                if eid == ueid or (filename_matches and track_id is not None and tid == track_id):
                    modified = _apply_track_identity(trk, ueid, uname, ucat) or modified
    return modified


def _fetch_runs_with_detections(db: Any) -> list[Any]:
    """Load video_runs rows that have serialized frame_detections_json."""
    with db._lock:
        cur = db._conn.cursor()
        try:
            cur.execute(
                "SELECT run_id, video_filename, frame_detections_json FROM video_runs "
                "WHERE frame_detections_json IS NOT NULL AND frame_detections_json != ''"
            )
            return cur.fetchall()
        finally:
            cur.close()


def relabel_video_runs_on_entity_mutation(
    db: Any,
    *,
    pool: Any = None,
    deleted_entity_id: int | None = None,
    updated_entity_id: int | None = None,
    discouraged_entity_id: int | None = None,
    video_filename: str | None = None,
    track_id: int | None = None,
) -> int:
    """Retroactively update video_runs.frame_detections_json and invalidate replay caches."""
    if db is None or getattr(db, "_conn", None) is None:
        return 0
    updated_entity = db.get_entity(updated_entity_id) if updated_entity_id is not None else None
    target_name = os.path.basename(str(video_filename or "").strip())
    updated_runs = 0
    for row in _fetch_runs_with_detections(db):
        run_id = str(row["run_id"])
        row_name = os.path.basename(str(row["video_filename"] or "").strip())
        try:
            records = json.loads(row["frame_detections_json"])
        except Exception:
            continue
        if isinstance(records, list) and _relabel_run_records(
            records,
            filename_matches=bool(target_name and row_name == target_name),
            deleted_entity_id=deleted_entity_id,
            updated_entity=updated_entity,
            discouraged_entity_id=discouraged_entity_id,
            track_id=track_id,
        ):
            if db.update_video_run_payload(run_id, frame_detections=records):
                updated_runs += 1
    invalidate_pool_replay_caches(pool)
    return updated_runs
