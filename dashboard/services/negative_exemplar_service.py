#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Negative & Correction Exemplar Service.

Persists supervised negative/false-positive exemplars from live streams,
recorded videos, or direct base64 crops, records ConfidenceEngine rejection
feedback, and clears mismatched live track identities.
"""

import logging
import os
import time
import uuid
from typing import Any

import cv2
import numpy as np

from dashboard.services.entity_tagger import EntityTaggerService
from dashboard.services.roi_recognition_service import (
    RoiRecognitionService,
    _resolve_roi_models,
    _resolve_roi_services,
)

logger = logging.getLogger(__name__)


def _save_negative_crop(
    crops_dir: str, entity_id: int | None, crop: np.ndarray
) -> str:
    """Write a collision-free negative exemplar JPEG thumbnail and return its path."""
    tag = f"neg_e{entity_id}" if entity_id is not None else "neg_fp"
    rel_path = os.path.join(
        crops_dir, f"{tag}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}.jpg"
    ).replace("\\", "/")
    abs_path = os.path.abspath(rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    cv2.imwrite(abs_path, crop)
    return rel_path


def _clear_mismatched_live_track(
    mgr: Any, track_id: int | None, entity_id: int | None
) -> None:
    """Clear cached identity on a live track if it matches the discouraged entity."""
    if mgr is None or track_id is None:
        return
    gm = getattr(mgr, "gallery_matcher", None)
    identified = getattr(gm, "_identified_tracks", None) if gm is not None else None
    if isinstance(identified, dict) and track_id in identified:
        if entity_id is None or identified[track_id].get("entity_id") == entity_id:
            identified.pop(track_id, None)
    tracker = getattr(mgr, "tracker", None)
    tracks = getattr(tracker, "tracks", None) if tracker is not None else None
    if isinstance(tracks, dict) and track_id in tracks:
        trk = tracks[track_id]
        if entity_id is None or getattr(trk, "entity_id", None) == entity_id:
            for attr in ("entity_id", "entity_name", "entity_category", "identity_label"):
                if hasattr(trk, attr):
                    delattr(trk, attr)
            trk.reid_score = 0.0


class NegativeExemplarService:
    """Service for recording negative Re-ID exemplars and false-positive feedback."""

    def __init__(
        self,
        db: Any,
        stream_manager: Any = None,
        camera_pool: Any = None,
        videos_dir: str = os.path.join("data", "videos"),
        crops_dir: str = os.path.join("data", "crops"),
        confidence_engine: Any = None,
    ) -> None:
        self.db = db
        self.stream_manager = stream_manager
        self.camera_pool = camera_pool
        self.videos_dir = videos_dir
        self.crops_dir = crops_dir
        self.confidence_engine, _ = _resolve_roi_services(
            db, stream_manager, camera_pool, confidence_engine, None
        )
        self._roi_service = RoiRecognitionService(
            db=db,
            stream_manager=stream_manager,
            camera_pool=camera_pool,
            videos_dir=videos_dir,
            crops_dir=crops_dir,
            confidence_engine=self.confidence_engine,
        )

    def discourage_roi(
        self, *, entity_id: int | None = None, label: str = "", camera_id: str | None = None,
        video_filename: str | None = None, timestamp_sec: float | None = None,
        bbox: list[int] | None = None, crop_base64: str | None = None,
        notes: str = "", track_id: int | None = None,
    ) -> dict[str, Any]:
        """Extract ROI crop/embedding, persist negative exemplar, and clear live track."""
        frame, is_direct = self._roi_service.resolve_roi_frame(
            camera_id=camera_id, video_filename=video_filename,
            timestamp_sec=timestamp_sec, crop_base64=crop_base64,
        )
        crop, _ = self._roi_service.extract_roi_crop(frame, bbox, is_direct_crop=is_direct)
        _, reid = _resolve_roi_models(self.stream_manager, self.camera_pool)
        emb = EntityTaggerService._compute_deterministic_embedding(crop, reid)
        crop_path = _save_negative_crop(self.crops_dir, entity_id, crop)
        source = camera_id or (os.path.basename(video_filename) if video_filename else "manual_discourage")
        exemplar_id = self.db.add_negative_exemplar(
            embedding=emb, entity_id=entity_id, label=label,
            crop_path=crop_path, source=source, notes=notes,
        )
        if entity_id is not None and self.confidence_engine is not None:
            try:
                self.confidence_engine.record_human_feedback(
                    entity_id=entity_id, action="reject", camera_id=source, zone_id="manual_discourage"
                )
            except Exception as exc:
                logger.debug("Negative confidence feedback skipped: %s", exc)
        mgr = self.stream_manager or (self.camera_pool.get_stream(camera_id) if camera_id and self.camera_pool else None)
        _clear_mismatched_live_track(mgr, track_id, entity_id)
        return {"exemplar_id": exemplar_id, "entity_id": entity_id, "label": label, "crop_path": crop_path, "source": source}

    def list_negatives(self, entity_id: int | None = None) -> list[dict[str, Any]]:
        """List persisted negative exemplars."""
        return self.db.get_negative_exemplars(entity_id=entity_id)

    def delete_negative(self, exemplar_id: int) -> bool:
        """Delete a persisted negative exemplar by ID."""
        return bool(self.db.delete_negative_exemplar(exemplar_id))
