"""Active Learning Operator Review Resolution Actions.

Executes ground-truth confirmation, entity reassignment, new entity enrollment,
and candidate dismissal, with full ``SourceRef`` sighting provenance,
``review_decisions`` audit logging, and ``ConfidenceEngine`` feedback hooks.
"""

import logging
import os
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np

from intelligent_tracker.database import TrackerDB

logger = logging.getLogger(__name__)


def _emit_feedback(
    on_feedback: Callable[[dict[str, Any]], None] | None, action: str,
    entity_id: int | None, review_id: int, item: dict[str, Any] | None,
    reviewer: str, previous_entity_id: int | None = None,
    confidence_engine: Any | None = None,
) -> None:
    """Invoke optional confidence engine & feedback hook without breaking DB resolution."""
    if confidence_engine is not None:
        try:
            sim = item.get("similarity") if isinstance(item, dict) else None
            cam_id = item.get("camera_id") if isinstance(item, dict) else None
            zone_id = item.get("zone_id") if isinstance(item, dict) else None
            confidence_engine.record_human_feedback(
                entity_id=entity_id, action=action, previous_entity_id=previous_entity_id,
                similarity=sim, reviewer=reviewer, camera_id=cam_id, zone_id=zone_id,
            )
        except Exception as exc:
            logger.warning("Active learning confidence_engine update failed: %s", exc)
    if on_feedback is None:
        return
    payload = {
        "action": action, "entity_id": entity_id, "previous_entity_id": previous_entity_id,
        "review_id": review_id, "item": item, "reviewer": reviewer,
    }
    try:
        on_feedback(payload)
    except Exception as exc:
        logger.warning("Active learning on_feedback callback failed: %s", exc)


def _build_prior_state(item: dict[str, Any]) -> dict[str, Any]:
    """Snapshot reversible ``review_queue`` provenance before applying an action."""
    return {
        "status": item.get("status", "pending"),
        "reviewed_by": item.get("reviewed_by") or "",
        "reviewed_at": item.get("reviewed_at"),
        "camera_id": item.get("camera_id") or "",
        "track_id": item.get("track_id"),
        "video_filename": item.get("video_filename") or "",
        "media_offset_sec": float(item.get("media_offset_sec") or 0.0),
        "run_id": item.get("run_id") or "",
        "suggested_name": item.get("suggested_name") or "",
        "suggested_category": item.get("suggested_category") or "",
        "crop_path": item.get("crop_path") or "",
        "bbox_json": item.get("bbox_json") or "",
    }


def _finalize_anchor_resolution(
    db: TrackerDB, matcher: Any | None, entity_id: int, embedding: np.ndarray,
    item: dict[str, Any], review_id: int, status: str, source: str, notes: str, reviewer: str,
) -> dict[str, int | None]:
    """Persist locked anchor signature, descriptor version, sighting, and review status."""
    crop_path = str(item.get("crop_path") or "")
    sig_id = db.add_signature(entity_id=entity_id, embedding=embedding, crop_path=crop_path, is_anchor=1, locked=1)
    ver_id = db.record_descriptor_version(
        entity_id=entity_id, embedding=embedding, crop_path=crop_path, source=source, notes=notes, is_anchor=1,
    )
    sighting_id: int | None = None
    if hasattr(db, "add_sighting"):
        cam_id = str(item.get("camera_id") or "").strip()
        vfile = str(item.get("video_filename") or "").strip()
        sighting_id = db.add_sighting(
            entity_id=entity_id,
            track_id=item.get("track_id"),
            source=vfile or cam_id or source or "active_learning",
            zone_id="active_learning",
            bbox=item.get("bbox_json") or "",
            confidence=1.0,
            snapshot_path=crop_path,
            video_filename=vfile,
            media_offset_sec=float(item.get("media_offset_sec") or 0.0),
            camera_id=cam_id,
            run_id=str(item.get("run_id") or "").strip(),
        )
    db.update_review_status(review_id, status=status, reviewed_by=reviewer)
    if matcher and hasattr(matcher, "reload_gallery"):
        matcher.reload_gallery()
    return {
        "signature_id": sig_id,
        "descriptor_version_id": ver_id,
        "sighting_id": sighting_id,
        "negative_exemplar_id": None,
    }


def _record_decision(
    db: TrackerDB,
    *,
    review_id: int,
    action: str,
    item: dict[str, Any],
    new_entity_id: int | None,
    artifacts: dict[str, int | None] | None = None,
    created_entity_id: int | None = None,
    reviewer: str = "operator",
    notes: str = "",
) -> int | None:
    """Persist a ``review_decisions`` audit row when the DB supports v5 schema."""
    if not hasattr(db, "record_review_decision"):
        return None
    art = artifacts or {}
    return db.record_review_decision(
        review_id=review_id,
        action=action,
        prior_status=str(item.get("status") or "pending"),
        prior_entity_id=item.get("suggested_entity_id"),
        new_entity_id=new_entity_id,
        created_signature_id=art.get("signature_id"),
        created_descriptor_version_id=art.get("descriptor_version_id"),
        created_sighting_id=art.get("sighting_id"),
        created_negative_exemplar_id=art.get("negative_exemplar_id"),
        created_entity_id=created_entity_id,
        prior_state=_build_prior_state(item),
        reviewer=reviewer,
        notes=notes,
    )


class ActiveLearningActions:
    """Processes operator review actions and emits audit + confidence feedback."""

    def __init__(
        self, db: TrackerDB, matcher: Any | None = None,
        on_feedback: Callable[[dict[str, Any]], None] | None = None,
        confidence_engine: Any | None = None,
    ) -> None:
        self.db = db
        self.matcher = matcher
        self.on_feedback = on_feedback
        self.confidence_engine = confidence_engine
        self.last_decision_id: int | None = None

    def _extract_crop_embedding(self, crop_path: str) -> np.ndarray | None:
        """Load crop from disk and extract feature embedding via matcher extractor."""
        if not os.path.isfile(crop_path):
            return None
        crop = cv2.imread(crop_path)
        if crop is None or crop.size == 0:
            return None
        if self.matcher and hasattr(self.matcher, "extractor") and self.matcher.extractor:
            return self.matcher.extractor.extract_crop(crop)
        return None

    def _resolve_embedding(self, crop_path: str) -> np.ndarray:
        """Extract embedding for ``crop_path`` or return normalized fallback vector."""
        embedding = self._extract_crop_embedding(crop_path)
        return embedding if embedding is not None else np.ones(16, dtype=np.float32) / 4.0

    def confirm(self, review_id: int, reviewer: str = "operator", notes: str = "") -> bool:
        """Confirm candidate match as ground truth and enroll as Locked Anchor."""
        item = self.db.get_review_item(review_id)
        if not item or not item.get("suggested_entity_id"):
            self.last_decision_id = None
            return False
        entity_id = item["suggested_entity_id"]
        art = _finalize_anchor_resolution(
            self.db, self.matcher, entity_id, self._resolve_embedding(item["crop_path"]),
            item, review_id, "confirmed", "active_learning_confirm",
            notes or f"Confirmed from Review #{review_id} by {reviewer}", reviewer,
        )
        self.last_decision_id = _record_decision(
            self.db, review_id=review_id, action="confirm", item=item,
            new_entity_id=entity_id, artifacts=art, reviewer=reviewer, notes=notes,
        )
        _emit_feedback(
            self.on_feedback, "confirm", entity_id, review_id, item, reviewer,
            confidence_engine=self.confidence_engine,
        )
        return True

    def reassign(self, review_id: int, new_entity_id: int, reviewer: str = "operator", notes: str = "") -> bool:
        """Reassign candidate crop to a different entity as a Locked Anchor."""
        item = self.db.get_review_item(review_id)
        if not item or not self.db.get_entity(new_entity_id):
            self.last_decision_id = None
            return False
        art = _finalize_anchor_resolution(
            self.db, self.matcher, new_entity_id, self._resolve_embedding(item["crop_path"]),
            item, review_id, "reassigned", "active_learning_reassign",
            notes or f"Reassigned from Review #{review_id} by {reviewer}", reviewer,
        )
        self.last_decision_id = _record_decision(
            self.db, review_id=review_id, action="reassign", item=item,
            new_entity_id=new_entity_id, artifacts=art, reviewer=reviewer, notes=notes,
        )
        _emit_feedback(
            self.on_feedback, "reassign", new_entity_id, review_id, item, reviewer,
            previous_entity_id=item.get("suggested_entity_id"),
            confidence_engine=self.confidence_engine,
        )
        return True

    def enroll_new(
        self, review_id: int, name: str, category: str = "person", notes: str = "", reviewer: str = "operator",
    ) -> int | None:
        """Register a new entity from review crop and set as initial Locked Anchor."""
        item = self.db.get_review_item(review_id)
        if not item:
            self.last_decision_id = None
            return None
        entity_id = self.db.add_entity(
            name=name.strip(), category=category.strip(),
            notes=notes.strip() or f"Enrolled via Active Learning #{review_id}",
        )
        art = _finalize_anchor_resolution(
            self.db, self.matcher, entity_id, self._resolve_embedding(item["crop_path"]),
            item, review_id, "enrolled_new", "active_learning_new_entity",
            f"Initial locked anchor from Review #{review_id} by {reviewer}", reviewer,
        )
        self.last_decision_id = _record_decision(
            self.db, review_id=review_id, action="enroll_new", item=item,
            new_entity_id=entity_id, artifacts=art, created_entity_id=entity_id,
            reviewer=reviewer, notes=notes,
        )
        _emit_feedback(
            self.on_feedback, "enroll_new", entity_id, review_id, item, reviewer,
            previous_entity_id=item.get("suggested_entity_id"),
            confidence_engine=self.confidence_engine,
        )
        return entity_id

    def dismiss(self, review_id: int, reviewer: str = "operator", notes: str = "") -> bool:
        """Dismiss candidate without altering models or gallery."""
        item = self.db.get_review_item(review_id)
        updated = self.db.update_review_status(review_id, status="dismissed", reviewed_by=reviewer)
        self.last_decision_id = None
        if updated and item is not None:
            self.last_decision_id = _record_decision(
                self.db, review_id=review_id, action="dismiss", item=item,
                new_entity_id=None, reviewer=reviewer, notes=notes,
            )
            _emit_feedback(
                self.on_feedback, "dismiss", item.get("suggested_entity_id"), review_id, item, reviewer,
                confidence_engine=self.confidence_engine,
            )
        return updated

    def confirm_candidate(self, item_id: int, notes: str = "", reviewer: str = "operator") -> dict[str, Any]:
        """Operator Confirm (Ground Truth): promote candidate crop as a Locked Anchor."""
        item = self.db.get_review_item(item_id)
        if not item:
            return {"status": "not_found", "item_id": item_id}
        if not self.confirm(item_id, reviewer=reviewer, notes=notes):
            return {"status": "failed", "item_id": item_id}
        return {
            "status": "confirmed", "item_id": item_id, "entity_id": item.get("suggested_entity_id"),
            "notes": notes, "decision_id": self.last_decision_id,
        }

    def reassign_candidate(
        self, item_id: int, target_entity_id: int, notes: str = "", reviewer: str = "operator",
    ) -> dict[str, Any]:
        """Operator Reassign: assign candidate crop as a Locked Anchor for another entity."""
        item = self.db.get_review_item(item_id)
        if not item:
            return {"status": "not_found", "item_id": item_id}
        if not self.reassign(item_id, new_entity_id=target_entity_id, reviewer=reviewer, notes=notes):
            return {"status": "failed", "item_id": item_id}
        return {
            "status": "reassigned", "item_id": item_id, "target_entity_id": target_entity_id,
            "notes": notes, "decision_id": self.last_decision_id,
        }

    def enroll_as_new(
        self, item_id: int, name: str, category: str = "person",
        security_role: str = "", notes: str = "", reviewer: str = "operator",
    ) -> dict[str, Any]:
        """Operator Enroll New: register candidate crop as a newly created entity."""
        item = self.db.get_review_item(item_id)
        if not item:
            return {"status": "not_found", "item_id": item_id}
        combined_notes = f"[Role: {security_role.strip()}] {notes.strip()}".strip() if security_role else notes.strip()
        new_id = self.enroll_new(item_id, name=name, category=category, notes=combined_notes, reviewer=reviewer)
        if new_id is None:
            return {"status": "failed", "item_id": item_id}
        return {
            "status": "enrolled_new", "item_id": item_id, "entity_id": new_id,
            "name": name, "category": category, "notes": notes, "decision_id": self.last_decision_id,
        }

    def dismiss_candidate(self, item_id: int, notes: str = "", reviewer: str = "operator") -> dict[str, Any]:
        """Operator Dismiss: reject candidate crop without modifying Re-ID gallery."""
        item = self.db.get_review_item(item_id)
        if not item:
            return {"status": "not_found", "item_id": item_id}
        self.dismiss(item_id, reviewer=reviewer, notes=notes)
        return {"status": "dismissed", "item_id": item_id, "notes": notes, "decision_id": self.last_decision_id}
