#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Human-in-the-Loop Active Learning ("Review & Learn" Inbox) Module.

Provides:
- ``ActiveLearningManager``: Thin facade coordinating ``ActiveLearningTriage``
  (ambiguous detection gating, debouncing, cropping, event dispatch) and
  ``ActiveLearningActions`` (confirm, reassign, enroll_new, dismiss).
"""

from collections.abc import Callable
from typing import Any

import numpy as np

from intelligent_tracker.active_learning_actions import ActiveLearningActions
from intelligent_tracker.active_learning_triage import ActiveLearningTriage
from intelligent_tracker.database import TrackerDB


class ActiveLearningManager:
    """Orchestrates the Human-in-the-Loop active learning lifecycle."""

    def __init__(
        self,
        db: TrackerDB,
        matcher: Any | None = None,
        min_confidence: float = 0.45,
        max_confidence: float = 0.70,
        debounce_interval: float = 30.0,
        crops_dir: str = "data/crops",
        event_bus: Any | None = None,
        on_feedback: Callable[[dict[str, Any]], None] | None = None,
        confidence_engine: Any | None = None,
    ) -> None:
        self.db = db
        self.matcher = matcher
        self.min_confidence = float(min_confidence)
        self.max_confidence = float(max_confidence)
        self.debounce_interval = float(debounce_interval)
        self.crops_dir = crops_dir
        self.event_bus = event_bus
        self.on_feedback = on_feedback
        self.confidence_engine = confidence_engine

        self._triage = ActiveLearningTriage(
            db=db,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            debounce_interval=debounce_interval,
            crops_dir=crops_dir,
            event_bus=event_bus,
        )
        self._actions = ActiveLearningActions(
            db=db,
            matcher=matcher,
            on_feedback=on_feedback,
            confidence_engine=confidence_engine,
        )
        self._last_queued = self._triage._last_queued

    def consider_candidate(
        self,
        track: Any,
        frame: np.ndarray,
        similarity: float,
        suggested_entity_id: int | None = None,
        suggested_name: str = "",
        suggested_category: str = "",
        camera_id: str = "cam_01",
        timestamp: float | None = None,
    ) -> int | None:
        """Evaluate track detection in [min_confidence, max_confidence) and queue."""
        return self._triage.consider_candidate(
            track=track,
            frame=frame,
            similarity=similarity,
            suggested_entity_id=suggested_entity_id,
            suggested_name=suggested_name,
            suggested_category=suggested_category,
            camera_id=camera_id,
            timestamp=timestamp,
        )

    def maybe_queue_candidate(
        self,
        camera_id: str,
        track_id: int,
        crop: np.ndarray,
        similarity: float,
        matched_entity_id: int | None = None,
        matched_entity_name: str = "",
        matched_category: str = "",
        bbox: tuple[int, int, int, int] | None = None,
        timestamp: float | None = None,
    ) -> dict[str, Any] | None:
        """Evaluate pre-cropped candidate and return queued review item or None."""
        return self._triage.maybe_queue_candidate(
            camera_id=camera_id,
            track_id=track_id,
            crop=crop,
            similarity=similarity,
            matched_entity_id=matched_entity_id,
            matched_entity_name=matched_entity_name,
            matched_category=matched_category,
            bbox=bbox,
            timestamp=timestamp,
        )

    def list_pending(self, limit: int = 50) -> list[dict[str, Any]]:
        """List pending review items."""
        return self.db.list_review_items(status="pending", limit=limit)

    def confirm_candidate(
        self,
        item_id: int,
        notes: str = "",
        reviewer: str = "operator",
    ) -> dict[str, Any]:
        """Operator Confirm (Ground Truth): promote candidate crop as a Locked Anchor."""
        return self._actions.confirm_candidate(item_id=item_id, notes=notes, reviewer=reviewer)

    def reassign_candidate(
        self,
        item_id: int,
        target_entity_id: int,
        notes: str = "",
        reviewer: str = "operator",
    ) -> dict[str, Any]:
        """Operator Reassign: assign candidate crop as a Locked Anchor for another entity."""
        return self._actions.reassign_candidate(
            item_id=item_id,
            target_entity_id=target_entity_id,
            notes=notes,
            reviewer=reviewer,
        )

    def enroll_as_new(
        self,
        item_id: int,
        name: str,
        category: str = "person",
        security_role: str = "",
        notes: str = "",
        reviewer: str = "operator",
    ) -> dict[str, Any]:
        """Operator Enroll New: register candidate crop as a newly created entity."""
        return self._actions.enroll_as_new(
            item_id=item_id,
            name=name,
            category=category,
            security_role=security_role,
            notes=notes,
            reviewer=reviewer,
        )

    def dismiss_candidate(
        self,
        item_id: int,
        notes: str = "",
        reviewer: str = "operator",
    ) -> dict[str, Any]:
        """Operator Dismiss: reject candidate crop without modifying Re-ID gallery."""
        return self._actions.dismiss_candidate(item_id=item_id, notes=notes, reviewer=reviewer)

    def __getattr__(self, name: str) -> Any:
        """Delegate legacy methods (confirm, reassign, enroll_new, dismiss, _extract_crop_embedding)."""
        if hasattr(self._actions, name):
            return getattr(self._actions, name)
        if hasattr(self._triage, name):
            return getattr(self._triage, name)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
