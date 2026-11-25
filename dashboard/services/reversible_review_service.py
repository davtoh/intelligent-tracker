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
    if prior_eid is not None and db.get_entity(int(prior_eid)) is not None and decision.get("action") in ("reassign", "enroll_new"):
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
    act = str(decision.get("action") or "")
    target_eid = decision.get("prior_entity_id") if act == "dismiss" else decision.get("new_entity_id")
    try:
        confidence_engine.revert_human_feedback(
            entity_id=target_eid,
            prior_action=act,
            previous_entity_id=decision.get("prior_entity_id"),
            camera_id=prior.get("camera_id") or None,
            zone_id=prior.get("zone_id") or None,
        )
        return True
    except Exception as exc:
        logger.warning("Failed to revert confidence feedback for decision %s: %s", decision.get("id"), exc)
        return False


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

    reverted = _revert_created_artifacts(db, decision)
    prior = decision.get("prior_state") or {}
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
