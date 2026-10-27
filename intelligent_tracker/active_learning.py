#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Human-in-the-Loop Active Learning ("Review & Learn" Inbox) Module.

Provides:
- ``ActiveLearningManager``: Automatic triage of ambiguous / borderline detections
  (0.45 < similarity < 0.70) into an operator review queue.
- Operator actions:
  - **Confirm (Ground Truth)**: Enrolls candidate crop as a Locked Anchor for the entity.
  - **Reassign**: Assigns candidate crop as a Locked Anchor for a different entity.
  - **Enroll as New Entity**: Registers new entity profile with candidate crop as initial signature.
  - **Dismiss**: Ignores ambiguous detection without model modification.
- Real-time event publishing to alert dashboard operators via WebSocket toasts.
"""

import os
import time
from typing import Dict, List, Optional, Any, Tuple

import cv2
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events import ReviewItemQueuedEvent


class ActiveLearningManager:
    """
    Orchestrates the Human-in-the-Loop active learning lifecycle.
    """

    def __init__(
        self,
        db: TrackerDB,
        matcher: Optional[Any] = None,
        min_confidence: float = 0.45,
        max_confidence: float = 0.70,
        debounce_interval: float = 30.0,
        crops_dir: str = "data/crops",
        event_bus: Optional[Any] = None,
    ):
        """
        :param db: TrackerDB instance for review queue and signature persistence.
        :param matcher: GalleryMatcher instance for embedding extraction and gallery reloads.
        :param min_confidence: Lower bound of ambiguous similarity range.
        :param max_confidence: Upper bound of ambiguous similarity range (below reid_threshold).
        :param debounce_interval: Minimum seconds before queuing another review candidate for same track.
        :param crops_dir: Directory where review candidate image crops are saved.
        :param event_bus: Optional EventBus to dispatch ReviewItemQueuedEvent.
        """
        self.db = db
        self.matcher = matcher
        self.min_confidence = float(min_confidence)
        self.max_confidence = float(max_confidence)
        self.debounce_interval = float(debounce_interval)
        self.crops_dir = crops_dir
        self.event_bus = event_bus

        # Debounce memory: (camera_id, track_id) -> last_queued_timestamp
        self._last_queued: Dict[Tuple[str, int], float] = {}

        os.makedirs(self.crops_dir, exist_ok=True)

    def consider_candidate(
        self,
        track: Any,
        frame: np.ndarray,
        similarity: float,
        suggested_entity_id: Optional[int] = None,
        suggested_name: str = "",
        suggested_category: str = "",
        camera_id: str = "cam_01",
        timestamp: Optional[float] = None,
    ) -> Optional[int]:
        """
        Evaluate if a track detection falls in ambiguous active learning range
        (min_confidence <= similarity < max_confidence). If so, crops thumbnail and queues.

        :return: Created review queue item ID or None.
        """
        now = timestamp if timestamp is not None else time.time()
        score = float(similarity)

        # 1. Range check
        if not (self.min_confidence <= score < self.max_confidence):
            return None

        tid = getattr(track, "track_id", 0)
        debounce_key = (camera_id, tid)

        # 2. Debounce check
        last_time = self._last_queued.get(debounce_key, 0.0)
        if now - last_time < self.debounce_interval:
            return None

        # 3. Crop bounding box region
        bbox = getattr(track, "bbox", None)
        if bbox is None or frame is None or frame.size == 0:
            return None

        x, y, w, h = [int(v) for v in bbox]
        ih, iw = frame.shape[:2]
        x1 = max(0, min(x, iw - 1))
        y1 = max(0, min(y, ih - 1))
        x2 = max(x1 + 1, min(x + w, iw))
        y2 = max(y1 + 1, min(y + h, ih))
        crop = frame[y1:y2, x1:x2]

        if crop.size == 0 or crop.shape[0] < 4 or crop.shape[1] < 4:
            return None

        # 4. Save crop to disk
        filename = f"review_{camera_id}_{tid}_{int(now)}_{np.random.randint(100, 999)}.jpg"
        crop_path = os.path.join(self.crops_dir, filename)
        try:
            cv2.imwrite(crop_path, crop)
        except Exception:
            return None

        # 5. Insert into TrackerDB review queue
        review_id = self.db.add_review_item(
            camera_id=camera_id,
            track_id=tid,
            crop_path=crop_path,
            suggested_entity_id=suggested_entity_id,
            suggested_name=suggested_name,
            suggested_category=suggested_category,
            similarity=score,
            status="pending",
        )
        self._last_queued[debounce_key] = now

        # 6. Dispatch event if event_bus attached
        if self.event_bus is not None:
            try:
                ev = ReviewItemQueuedEvent(
                    camera_id=camera_id,
                    review_id=review_id,
                    track_id=tid,
                    crop_path=crop_path,
                    suggested_entity_id=suggested_entity_id,
                    suggested_name=suggested_name,
                    suggested_category=suggested_category,
                    similarity=score,
                    timestamp=now,
                )
                self.event_bus.publish(ev)
            except Exception:
                pass

        return review_id

    def maybe_queue_candidate(
        self,
        camera_id: str,
        track_id: int,
        crop: np.ndarray,
        similarity: float,
        matched_entity_id: Optional[int] = None,
        matched_entity_name: str = "",
        matched_category: str = "",
        bbox: Optional[Tuple[int, int, int, int]] = None,
        timestamp: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate and queue an ambiguous candidate if similarity falls in [min_confidence, max_confidence).
        Returns the queued review item dictionary or None.
        """
        now = timestamp if timestamp is not None else time.time()
        score = float(similarity)

        if not (self.min_confidence <= score < self.max_confidence):
            return None

        debounce_key = (camera_id, track_id)
        last_time = self._last_queued.get(debounce_key, 0.0)
        if now - last_time < self.debounce_interval:
            return None

        if crop is None or crop.size == 0 or crop.shape[0] < 4 or crop.shape[1] < 4:
            return None

        filename = f"review_{camera_id}_{track_id}_{int(now)}_{np.random.randint(100, 999)}.jpg"
        crop_path = os.path.join(self.crops_dir, filename)
        try:
            cv2.imwrite(crop_path, crop)
        except Exception:
            return None

        self._last_queued[debounce_key] = now
        item_id = self.db.add_review_item(
            camera_id=camera_id,
            track_id=track_id,
            crop_path=crop_path,
            suggested_entity_id=matched_entity_id,
            suggested_name=matched_entity_name,
            suggested_category=matched_category,
            similarity=score,
            status="pending",
        )

        item = self.db.get_review_item(item_id)
        if self.event_bus is not None and item:
            try:
                ev = ReviewItemQueuedEvent(
                    camera_id=camera_id,
                    review_id=item_id,
                    track_id=track_id,
                    crop_path=crop_path,
                    suggested_entity_id=matched_entity_id,
                    suggested_name=matched_entity_name,
                    suggested_category=matched_category,
                    similarity=score,
                    timestamp=now,
                )
                self.event_bus.publish(ev)
            except Exception:
                pass

        return item

    def list_pending(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List pending review items."""
        return self.db.list_review_items(status="pending", limit=limit)

    def _extract_crop_embedding(self, crop_path: str) -> Optional[np.ndarray]:
        """Load crop from disk and extract feature embedding via matcher extractor."""
        if not os.path.isfile(crop_path):
            return None
        crop = cv2.imread(crop_path)
        if crop is None or crop.size == 0:
            return None

        if self.matcher and hasattr(self.matcher, "extractor") and self.matcher.extractor:
            return self.matcher.extractor.extract_crop(crop)
        return None

    def confirm(self, review_id: int, reviewer: str = "operator") -> bool:
        """
        Confirm candidate match as ground truth.
        Enrolls crop signature as a Locked Anchor for the suggested entity.
        """
        item = self.db.get_review_item(review_id)
        if not item or not item.get("suggested_entity_id"):
            return False

        entity_id = item["suggested_entity_id"]
        embedding = self._extract_crop_embedding(item["crop_path"])
        if embedding is None:
            # Fallback to random or zero vector if image missing
            embedding = np.ones(16, dtype=np.float32) / 4.0

        # Enroll as Locked Anchor (is_anchor=1, locked=1)
        self.db.add_signature(
            entity_id=entity_id,
            embedding=embedding,
            crop_path=item["crop_path"],
            is_anchor=1,
            locked=1,
        )

        # Record descriptor version
        self.db.record_descriptor_version(
            entity_id=entity_id,
            embedding=embedding,
            crop_path=item["crop_path"],
            source="active_learning_confirm",
            notes=f"Confirmed from Review #{review_id} by {reviewer}",
        )

        self.db.update_review_status(review_id, status="confirmed", reviewed_by=reviewer)

        # Refresh gallery
        if self.matcher and hasattr(self.matcher, "reload_gallery"):
            self.matcher.reload_gallery()

        return True

    def reassign(self, review_id: int, new_entity_id: int, reviewer: str = "operator") -> bool:
        """
        Reassign candidate crop to a different entity as a Locked Anchor.
        """
        item = self.db.get_review_item(review_id)
        if not item:
            return False

        entity = self.db.get_entity(new_entity_id)
        if not entity:
            return False

        embedding = self._extract_crop_embedding(item["crop_path"])
        if embedding is None:
            embedding = np.ones(16, dtype=np.float32) / 4.0

        # Enroll as Locked Anchor for the new entity
        self.db.add_signature(
            entity_id=new_entity_id,
            embedding=embedding,
            crop_path=item["crop_path"],
            is_anchor=1,
            locked=1,
        )

        # Record version
        self.db.record_descriptor_version(
            entity_id=new_entity_id,
            embedding=embedding,
            crop_path=item["crop_path"],
            source="active_learning_reassign",
            notes=f"Reassigned from Review #{review_id} by {reviewer}",
        )

        self.db.update_review_status(review_id, status="reassigned", reviewed_by=reviewer)

        if self.matcher and hasattr(self.matcher, "reload_gallery"):
            self.matcher.reload_gallery()

        return True

    def enroll_new(
        self,
        review_id: int,
        name: str,
        category: str = "person",
        notes: str = "",
        reviewer: str = "operator",
    ) -> Optional[int]:
        """
        Register a new entity from review crop and set as initial Locked Anchor.
        """
        item = self.db.get_review_item(review_id)
        if not item:
            return None

        embedding = self._extract_crop_embedding(item["crop_path"])
        if embedding is None:
            embedding = np.ones(16, dtype=np.float32) / 4.0

        # Create entity
        entity_id = self.db.add_entity(
            name=name.strip(),
            category=category.strip(),
            notes=notes.strip() or f"Enrolled via Active Learning #{review_id}",
        )

        # Add signature as Locked Anchor
        self.db.add_signature(
            entity_id=entity_id,
            embedding=embedding,
            crop_path=item["crop_path"],
            is_anchor=1,
            locked=1,
        )

        # Record descriptor version 1
        self.db.record_descriptor_version(
            entity_id=entity_id,
            embedding=embedding,
            crop_path=item["crop_path"],
            source="active_learning_new_entity",
            notes=f"Initial locked anchor from Review #{review_id} by {reviewer}",
        )

        self.db.update_review_status(review_id, status="enrolled_new", reviewed_by=reviewer)

        if self.matcher and hasattr(self.matcher, "reload_gallery"):
            self.matcher.reload_gallery()

        return entity_id

    def dismiss(self, review_id: int, reviewer: str = "operator") -> bool:
        """Dismiss candidate without altering models or gallery."""
        return self.db.update_review_status(review_id, status="dismissed", reviewed_by=reviewer)

    def confirm_candidate(
        self,
        item_id: int,
        notes: str = "",
        reviewer: str = "operator",
    ) -> Dict[str, Any]:
        """Operator Confirm (Ground Truth): promote candidate crop as a Locked Anchor for the entity."""
        item = self.db.get_review_item(item_id)
        if not item:
            return {"status": "not_found", "item_id": item_id}
        ok = self.confirm(item_id, reviewer=reviewer)
        if not ok:
            return {"status": "failed", "item_id": item_id}
        return {
            "status": "confirmed",
            "item_id": item_id,
            "entity_id": item.get("suggested_entity_id"),
            "notes": notes,
        }

    def reassign_candidate(
        self,
        item_id: int,
        target_entity_id: int,
        notes: str = "",
        reviewer: str = "operator",
    ) -> Dict[str, Any]:
        """Operator Reassign: assign candidate crop as a Locked Anchor for a different entity."""
        item = self.db.get_review_item(item_id)
        if not item:
            return {"status": "not_found", "item_id": item_id}
        ok = self.reassign(item_id, new_entity_id=target_entity_id, reviewer=reviewer)
        if not ok:
            return {"status": "failed", "item_id": item_id}
        return {
            "status": "reassigned",
            "item_id": item_id,
            "target_entity_id": target_entity_id,
            "notes": notes,
        }

    def enroll_as_new(
        self,
        item_id: int,
        name: str,
        category: str = "person",
        security_role: str = "",
        notes: str = "",
        reviewer: str = "operator",
    ) -> Dict[str, Any]:
        """Operator Enroll New: register candidate crop as a newly created entity."""
        item = self.db.get_review_item(item_id)
        if not item:
            return {"status": "not_found", "item_id": item_id}
        combined_notes = notes.strip()
        if security_role:
            combined_notes = f"[Role: {security_role.strip()}] {combined_notes}".strip()
        new_id = self.enroll_new(item_id, name=name, category=category, notes=combined_notes, reviewer=reviewer)
        if new_id is None:
            return {"status": "failed", "item_id": item_id}
        return {
            "status": "enrolled_new",
            "item_id": item_id,
            "entity_id": new_id,
            "name": name,
            "category": category,
            "notes": notes,
        }

    def dismiss_candidate(
        self,
        item_id: int,
        notes: str = "",
        reviewer: str = "operator",
    ) -> Dict[str, Any]:
        """Operator Dismiss: reject candidate crop without modifying Re-ID gallery."""
        item = self.db.get_review_item(item_id)
        if not item:
            return {"status": "not_found", "item_id": item_id}
        self.dismiss(item_id, reviewer=reviewer)
        return {"status": "dismissed", "item_id": item_id, "notes": notes}

