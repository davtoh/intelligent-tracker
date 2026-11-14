"""Active Learning Operator Review Resolution Actions.

Executes ground-truth confirmation, entity reassignment, new entity enrollment,
and candidate dismissal, with an optional ``on_feedback`` callback hook for
ConfidenceEngine reinforcement.
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
            confidence_engine.record_human_feedback(
                entity_id=entity_id, action=action, previous_entity_id=previous_entity_id,
                similarity=sim, reviewer=reviewer,
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


def _finalize_anchor_resolution(
    db: TrackerDB, matcher: Any | None, entity_id: int, embedding: np.ndarray,
    crop_path: str, review_id: int, status: str, source: str, notes: str, reviewer: str,
) -> None:
    """Persist locked anchor signature, descriptor version, review status, and reload gallery."""
    db.add_signature(entity_id=entity_id, embedding=embedding, crop_path=crop_path, is_anchor=1, locked=1)
    db.record_descriptor_version(entity_id=entity_id, embedding=embedding, crop_path=crop_path, source=source, notes=notes)
    db.update_review_status(review_id, status=status, reviewed_by=reviewer)
    if matcher and hasattr(matcher, "reload_gallery"):
        matcher.reload_gallery()


class ActiveLearningActions:
    """Processes operator review actions and emits optional confidence feedback."""

    def __init__(
        self, db: TrackerDB, matcher: Any | None = None,
        on_feedback: Callable[[dict[str, Any]], None] | None = None,
        confidence_engine: Any | None = None,
    ) -> None:
        self.db = db
        self.matcher = matcher
        self.on_feedback = on_feedback
        self.confidence_engine = confidence_engine

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

    def confirm(self, review_id: int, reviewer: str = "operator") -> bool:
        """Confirm candidate match as ground truth and enroll as Locked Anchor."""
        item = self.db.get_review_item(review_id)
        if not item or not item.get("suggested_entity_id"):
            return False
        entity_id = item["suggested_entity_id"]
        _finalize_anchor_resolution(
            self.db, self.matcher, entity_id, self._resolve_embedding(item["crop_path"]),
            item["crop_path"], review_id, "confirmed", "active_learning_confirm",
            f"Confirmed from Review #{review_id} by {reviewer}", reviewer,
        )
        _emit_feedback(
            self.on_feedback, "confirm", entity_id, review_id, item, reviewer,
            confidence_engine=self.confidence_engine,
        )
        return True

    def reassign(self, review_id: int, new_entity_id: int, reviewer: str = "operator") -> bool:
        """Reassign candidate crop to a different entity as a Locked Anchor."""
        item = self.db.get_review_item(review_id)
        if not item or not self.db.get_entity(new_entity_id):
            return False
        _finalize_anchor_resolution(
            self.db, self.matcher, new_entity_id, self._resolve_embedding(item["crop_path"]),
            item["crop_path"], review_id, "reassigned", "active_learning_reassign",
            f"Reassigned from Review #{review_id} by {reviewer}", reviewer,
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
            return None
        entity_id = self.db.add_entity(
            name=name.strip(), category=category.strip(),
            notes=notes.strip() or f"Enrolled via Active Learning #{review_id}",
        )
        _finalize_anchor_resolution(
            self.db, self.matcher, entity_id, self._resolve_embedding(item["crop_path"]),
            item["crop_path"], review_id, "enrolled_new", "active_learning_new_entity",
            f"Initial locked anchor from Review #{review_id} by {reviewer}", reviewer,
        )
        _emit_feedback(
            self.on_feedback, "enroll_new", entity_id, review_id, item, reviewer,
            previous_entity_id=item.get("suggested_entity_id"),
            confidence_engine=self.confidence_engine,
        )
        return entity_id

    def dismiss(self, review_id: int, reviewer: str = "operator") -> bool:
        """Dismiss candidate without altering models or gallery."""
        item = self.db.get_review_item(review_id)
        updated = self.db.update_review_status(review_id, status="dismissed", reviewed_by=reviewer)
        if updated and item is not None:
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
        if not self.confirm(item_id, reviewer=reviewer):
            return {"status": "failed", "item_id": item_id}
        return {"status": "confirmed", "item_id": item_id, "entity_id": item.get("suggested_entity_id"), "notes": notes}

    def reassign_candidate(
        self, item_id: int, target_entity_id: int, notes: str = "", reviewer: str = "operator",
    ) -> dict[str, Any]:
        """Operator Reassign: assign candidate crop as a Locked Anchor for another entity."""
        item = self.db.get_review_item(item_id)
        if not item:
            return {"status": "not_found", "item_id": item_id}
        if not self.reassign(item_id, new_entity_id=target_entity_id, reviewer=reviewer):
            return {"status": "failed", "item_id": item_id}
        return {"status": "reassigned", "item_id": item_id, "target_entity_id": target_entity_id, "notes": notes}

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
        return {"status": "enrolled_new", "item_id": item_id, "entity_id": new_id, "name": name, "category": category, "notes": notes}

    def dismiss_candidate(self, item_id: int, notes: str = "", reviewer: str = "operator") -> dict[str, Any]:
        """Operator Dismiss: reject candidate crop without modifying Re-ID gallery."""
        item = self.db.get_review_item(item_id)
        if not item:
            return {"status": "not_found", "item_id": item_id}
        self.dismiss(item_id, reviewer=reviewer)
        return {"status": "dismissed", "item_id": item_id, "notes": notes}
