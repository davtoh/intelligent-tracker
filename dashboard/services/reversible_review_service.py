"""Reversible Active Learning Review Orchestration Service.

Coordinates audited review actions (confirm, reassign, enroll_new, dismiss)
and full transactional/cross-subsystem undo across SQLite artifacts,
``video_runs``, ``ConfidenceEngine``, ``CachedReplayProvider``, and
``CameraPool`` galleries.
"""

import logging
from collections.abc import Callable
from typing import Any

from dashboard.services.review_sync_service import sync_review_resolution_to_video_runs
from dashboard.services.video_run_relabel_service import (
    invalidate_pool_replay_caches,
    relabel_video_runs_on_entity_mutation,
)

logger = logging.getLogger(__name__)


def _dispatch_review_action(
    al_mgr: Any,
    *,
    action: str,
    item_id: int,
    target_entity_id: int | None,
    name: str,
    category: str,
    security_role: str,
    notes: str,
    reviewer: str,
) -> dict[str, Any]:
    """Invoke the matching ``ActiveLearningManager`` action method."""
    if action == "confirm":
        return al_mgr.confirm_candidate(item_id=item_id, notes=notes, reviewer=reviewer)
    if action == "reassign":
        return al_mgr.reassign_candidate(
            item_id=item_id, target_entity_id=int(target_entity_id or 0), notes=notes, reviewer=reviewer,
        )
    if action == "enroll_new":
        return al_mgr.enroll_as_new(
            item_id=item_id, name=name, category=category,
            security_role=security_role, notes=notes, reviewer=reviewer,
        )
    if action == "dismiss":
        return al_mgr.dismiss_candidate(item_id=item_id, notes=notes, reviewer=reviewer)
    raise ValueError(f"Unsupported review action: {action!r}")


def execute_review_action_with_audit(
    db: Any,
    al_mgr: Any,
    *,
    action: str,
    item_id: int,
    request: Any = None,
    reload_galleries: Callable[..., Any] | None = None,
    pool: Any = None,
    target_entity_id: int | None = None,
    name: str = "",
    category: str = "person",
    security_role: str = "",
    notes: str = "",
    reviewer: str = "operator",
) -> dict[str, Any]:
    """Execute an audited review action, reload galleries, and sync ``video_runs``."""
    item = db.get_review_item(item_id)
    res = _dispatch_review_action(
        al_mgr, action=action, item_id=item_id, target_entity_id=target_entity_id,
        name=name, category=category, security_role=security_role, notes=notes, reviewer=reviewer,
    )
    if res.get("status") in ("not_found", "failed"):
        return res
    if action != "dismiss":
        _reload_and_invalidate(reload_galleries, request, pool)
    sync_entity_id = target_entity_id if action == "reassign" else res.get("entity_id")
    sync_meta = sync_review_resolution_to_video_runs(
        db,
        item=item,
        action=action,
        entity_id=sync_entity_id,
        entity_name=name if action == "enroll_new" else "",
        category=category if action == "enroll_new" else "",
    )
    invalidate_pool_replay_caches(pool)
    return {**res, "decision_id": res.get("decision_id"), "sync": sync_meta}


def _reload_and_invalidate(
    reload_galleries: Callable[..., Any] | None, request: Any, pool: Any,
) -> None:
    """Reload Re-ID galleries and clear replay caches without raising on optional hooks."""
    if reload_galleries is not None:
        reload_galleries(conn=request)
    elif pool is not None and hasattr(pool, "reload_all_galleries"):
        pool.reload_all_galleries()
    invalidate_pool_replay_caches(pool)


def _revert_created_artifacts(db: Any, decision: dict[str, Any]) -> dict[str, bool]:
    """Delete signatures, negative exemplars, sightings, descriptor versions, and orphan entities."""
    reverted = {
        "signature": False, "negative_exemplar": False, "sighting": False,
        "descriptor_version": False, "created_entity": False,
    }
    sig_id = decision.get("created_signature_id")
    if sig_id is not None and hasattr(db, "delete_signature"):
        reverted["signature"] = bool(db.delete_signature(int(sig_id)))
    neg_id = decision.get("created_negative_exemplar_id")
    if neg_id is not None and hasattr(db, "delete_negative_exemplar"):
        reverted["negative_exemplar"] = bool(db.delete_negative_exemplar(int(neg_id)))
    sighting_id = decision.get("created_sighting_id")
    if sighting_id is not None and hasattr(db, "delete_sighting_by_id"):
        reverted["sighting"] = bool(db.delete_sighting_by_id(int(sighting_id)))
    ver_id = decision.get("created_descriptor_version_id")
    if ver_id is not None and hasattr(db, "prune_descriptor_version"):
        reverted["descriptor_version"] = bool(db.prune_descriptor_version(int(ver_id)))
    created_eid = decision.get("created_entity_id")
    if created_eid is not None and hasattr(db, "get_signatures") and hasattr(db, "delete_entity"):
        remaining = db.get_signatures(entity_id=int(created_eid))
        if not remaining:
            reverted["created_entity"] = bool(db.delete_entity(int(created_eid)))
    return reverted


def _relabel_runs_for_undo(
    db: Any, decision: dict[str, Any], *, entity_deleted: bool, pool: Any,
) -> int:
    """Restore ``video_runs.frame_detections_json`` to pre-decision labels."""
    prior = decision.get("prior_state") or {}
    vfile = str(prior.get("video_filename") or "").strip()
    track_id = prior.get("track_id")
    prior_eid = decision.get("prior_entity_id")
    new_eid = decision.get("new_entity_id")
    created_eid = decision.get("created_entity_id")
    if not vfile and not prior.get("run_id") and not entity_deleted:
        return 0
    if prior_eid is not None and db.get_entity(int(prior_eid)) is not None and decision.get("action") in ("reassign", "enroll_new", "correct"):
        return relabel_video_runs_on_entity_mutation(
            db, pool=pool,
            deleted_entity_id=int(created_eid) if entity_deleted and created_eid is not None else None,
            updated_entity_id=int(prior_eid),
            video_filename=vfile or None,
            track_id=int(track_id) if track_id is not None else None,
        )
    if entity_deleted and created_eid is not None:
        return relabel_video_runs_on_entity_mutation(
            db, pool=pool, deleted_entity_id=int(created_eid),
            video_filename=vfile or None,
            track_id=int(track_id) if track_id is not None else None,
        )
    if new_eid is not None and decision.get("action") != "dismiss":
        return relabel_video_runs_on_entity_mutation(
            db, pool=pool, discouraged_entity_id=int(new_eid),
            video_filename=vfile or None,
            track_id=int(track_id) if track_id is not None else None,
        )
    return 0


def _revert_confidence(confidence_engine: Any, decision: dict[str, Any]) -> bool:
    """Invoke ``ConfidenceEngine.revert_human_feedback`` when available."""
    if confidence_engine is None or not hasattr(confidence_engine, "revert_human_feedback"):
        return False
    prior = decision.get("prior_state") or {}
    raw_act = str(decision.get("action") or "")
    act = "reassign" if raw_act == "correct" else ("dismiss" if raw_act == "report_wrong" else raw_act)
    target_eid = decision.get("prior_entity_id") if act == "dismiss" else decision.get("new_entity_id")
    try:
        confidence_engine.revert_human_feedback(
            entity_id=target_eid, prior_action=act,
            previous_entity_id=decision.get("prior_entity_id"),
            camera_id=prior.get("camera_id") or None, zone_id=prior.get("zone_id") or None,
        )
        return True
    except Exception as exc:
        logger.warning("Failed to revert confidence feedback for decision %s: %s", decision.get("id"), exc)
        return False


def _restore_correction_sightings(db: Any, decision: dict[str, Any], prior: dict[str, Any]) -> None:
    """Restore reassigned sightings from ``new_entity_id`` back to ``prior_entity_id`` before entity pruning."""
    if (
        decision.get("action") == "correct"
        and decision.get("prior_entity_id") is not None
        and decision.get("new_entity_id") is not None
        and hasattr(db, "reassign_sightings_by_provenance")
    ):
        db.reassign_sightings_by_provenance(
            from_entity_id=int(decision["new_entity_id"]), to_entity_id=int(decision["prior_entity_id"]),
            camera_id=str(prior.get("camera_id") or ""), run_id=str(prior.get("run_id") or ""),
            video_filename=str(prior.get("video_filename") or ""),
            track_id=int(prior["track_id"]) if prior.get("track_id") is not None else None,
        )


def undo_review_decision(
    db: Any, *, decision_id: int | None = None, review_id: int | None = None,
    confidence_engine: Any = None, pool: Any = None, request: Any = None,
    reload_galleries: Callable[..., Any] | None = None, undone_by: str = "operator",
) -> dict[str, Any]:
    """Undo a persisted ``review_decisions`` row and restore DB/gallery/replay state."""
    decision = (
        db.get_review_decision(int(decision_id)) if decision_id is not None
        else (db.get_latest_decision_for_review(int(review_id), include_undone=False) if review_id is not None else None)
    )
    if decision is None:
        return {"status": "not_found", "decision_id": decision_id, "review_id": review_id}
    if decision.get("undone"):
        return {"status": "already_undone", "decision_id": decision["id"], "review_id": decision["review_id"]}
    prior = decision.get("prior_state") or {}
    _restore_correction_sightings(db, decision, prior)
    reverted = _revert_created_artifacts(db, decision)
    db.update_review_status(
        int(decision["review_id"]),
        status=str(decision.get("prior_status") or "pending"),
        reviewed_by=str(prior.get("reviewed_by") or ""),
    )
    relabelled = _relabel_runs_for_undo(db, decision, entity_deleted=reverted["created_entity"], pool=pool)
    reverted["confidence"] = _revert_confidence(confidence_engine, decision)
    db.mark_decision_undone(int(decision["id"]), undone_by=undone_by)
    _reload_and_invalidate(reload_galleries, request, pool)
    return {
        "status": "undone", "decision_id": int(decision["id"]), "review_id": int(decision["review_id"]),
        "action": str(decision.get("action") or ""), "reverted": reverted, "relabelled_runs": relabelled,
    }


def report_wrong_sighting(
    db: Any, *, sighting_id: int | None = None, entity_id: int | None = None,
    camera_id: str = "", video_filename: str = "", media_offset_sec: float = 0.0,
    track_id: int = 0, run_id: str = "", crop_path: str = "",
    bbox: list[int] | None = None, notes: str = "", reviewer: str = "operator",
    confidence_engine: Any = None,
) -> dict[str, Any]:
    """Queue a timeline false-positive sighting into ``review_queue`` with audit decision."""
    row = db.get_sighting_by_id(int(sighting_id)) if (sighting_id is not None and hasattr(db, "get_sighting_by_id")) else None
    eff_eid = entity_id if entity_id is not None else (row.get("entity_id") if row else None)
    eff_cam = str(camera_id or (row or {}).get("camera_id") or (row or {}).get("source") or "cam_01").strip()
    eff_vid = str(video_filename or (row or {}).get("video_filename") or "").strip()
    eff_off = float(media_offset_sec or (row or {}).get("media_offset_sec") or 0.0)
    eff_tid = int(track_id or (row or {}).get("track_id") or 0)
    eff_run = str(run_id or (row or {}).get("run_id") or "").strip()
    eff_crop = str(crop_path or (row or {}).get("snapshot_path") or "").strip()
    ent = db.get_entity(int(eff_eid)) if (eff_eid is not None and hasattr(db, "get_entity")) else None
    review_id = db.add_review_item(
        camera_id=eff_cam, track_id=eff_tid, crop_path=eff_crop,
        suggested_entity_id=int(eff_eid) if eff_eid is not None else None,
        suggested_name=str((ent or {}).get("name") or ""),
        suggested_category=str((ent or {}).get("category") or "person"),
        similarity=0.0, status="pending", video_filename=eff_vid,
        media_offset_sec=eff_off, bbox=bbox, run_id=eff_run, reason="timeline_flag",
    )
    if confidence_engine is not None and eff_eid is not None and hasattr(confidence_engine, "record_human_feedback"):
        confidence_engine.record_human_feedback(int(eff_eid), "reject", camera_id=eff_cam or None)
    decision_id = db.record_review_decision(
        review_id, "report_wrong", prior_status="dismissed",
        prior_entity_id=int(eff_eid) if eff_eid is not None else None,
        prior_state={"sighting_id": sighting_id, "camera_id": eff_cam, "video_filename": eff_vid, "track_id": eff_tid, "run_id": eff_run},
        reviewer=reviewer, notes=notes or "Reported wrong from timeline",
    ) if hasattr(db, "record_review_decision") else None
    return {"status": "flagged", "review_id": int(review_id), "decision_id": decision_id, "entity_id": int(eff_eid) if eff_eid is not None else None, "reason": "timeline_flag"}


def _record_correction_negative(
    neg_svc: Any, confidence_engine: Any, prior_entity_id: int, prior_name: str,
    *, camera_id: str | None, video_filename: str | None, timestamp_sec: float | None,
    bbox: list[int] | None, crop_base64: str | None, notes: str, track_id: int | None,
) -> int | None:
    """Record a negative exemplar or rejection feedback against ``prior_entity_id``."""
    neg_id: int | None = None
    if neg_svc is not None:
        try:
            res = neg_svc.discourage_roi(
                entity_id=int(prior_entity_id), label=prior_name, camera_id=camera_id,
                video_filename=video_filename, timestamp_sec=timestamp_sec, bbox=bbox,
                crop_base64=crop_base64, notes=notes or "Corrected mistaken identity", track_id=track_id,
            )
            raw_id = res.get("exemplar_id") or res.get("id") if isinstance(res, dict) else None
            neg_id = int(raw_id) if raw_id is not None else None
        except Exception as exc:
            logger.debug("Negative exemplar fallback on correction for entity %s: %s", prior_entity_id, exc)
    if neg_id is None and confidence_engine is not None and hasattr(confidence_engine, "record_human_feedback"):
        confidence_engine.record_human_feedback(int(prior_entity_id), "reject", camera_id=camera_id)
    return neg_id


def correct_known_entity_match(
    db: Any, roi_svc: Any, neg_svc: Any, *, prior_entity_id: int, entity_name: str, category: str = "person",
    entity_id: int | None = None, camera_id: str | None = None, video_filename: str | None = None,
    timestamp_sec: float | None = None, bbox: list[int] | None = None, crop_base64: str | None = None,
    notes: str = "", track_id: int | None = None, run_id: str = "", reviewer: str = "operator",
    pool: Any = None, request: Any = None, reload_galleries: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Correct a Known-state entity match with negative exemplar, relabel, and undoable audit."""
    prior_ent, existed_before = (db.get_entity(int(prior_entity_id)) if hasattr(db, "get_entity") else None), (entity_id is not None)
    commit_data = roi_svc.commit_roi_tag(
        entity_name=entity_name, category=category, entity_id=entity_id, camera_id=camera_id,
        video_filename=video_filename, timestamp_sec=timestamp_sec, bbox=bbox, crop_base64=crop_base64, notes=notes, track_id=track_id,
    )
    new_eid, prior_name = int(commit_data["entity_id"]), str((prior_ent or {}).get("name") or "")
    neg_id = _record_correction_negative(
        neg_svc, getattr(roi_svc, "confidence_engine", None), int(prior_entity_id), prior_name,
        camera_id=camera_id, video_filename=video_filename, timestamp_sec=timestamp_sec,
        bbox=bbox, crop_base64=crop_base64, notes=notes, track_id=track_id,
    )
    cam_s, vid_s, run_s = str(camera_id or ""), str(video_filename or ""), str(run_id or "")
    moved = db.reassign_sightings_by_provenance(
        from_entity_id=int(prior_entity_id), to_entity_id=new_eid, camera_id=cam_s, run_id=run_s, video_filename=vid_s, track_id=track_id,
    ) if hasattr(db, "reassign_sightings_by_provenance") else 0
    relabel_video_runs_on_entity_mutation(db, pool=pool, updated_entity_id=new_eid, video_filename=video_filename, track_id=track_id)
    review_id = db.add_review_item(
        camera_id=cam_s or "cam_01", track_id=int(track_id or 0), crop_path=str(commit_data.get("crop_path") or ""),
        suggested_entity_id=int(prior_entity_id), suggested_name=prior_name, suggested_category=category, similarity=0.0,
        status="reassigned", video_filename=vid_s, media_offset_sec=float(timestamp_sec or 0.0), bbox=bbox, run_id=run_s, reason="tag_correction",
    )
    prior_state = {"camera_id": cam_s, "video_filename": vid_s, "track_id": track_id, "run_id": run_s}
    decision_id = db.record_review_decision(
        review_id, "correct", prior_status="pending", prior_entity_id=int(prior_entity_id), new_entity_id=new_eid,
        created_signature_id=commit_data.get("signature_id"), created_sighting_id=commit_data.get("sighting_id"),
        created_negative_exemplar_id=neg_id, created_entity_id=None if existed_before else new_eid,
        prior_state=prior_state, reviewer=reviewer, notes=notes or "Known-state correction",
    ) if hasattr(db, "record_review_decision") else None
    _reload_and_invalidate(reload_galleries, request, pool)
    return {"status": "corrected", "decision_id": decision_id, "review_id": int(review_id), "prior_entity_id": int(prior_entity_id), "entity_id": new_eid, "negative_exemplar_id": neg_id, "reassigned_sightings": moved, "data": commit_data}
