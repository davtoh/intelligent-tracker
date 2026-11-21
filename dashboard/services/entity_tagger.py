#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Entity Tagger Service.
Extracts bounding box visual crops from raw video frames, generates Re-ID
embeddings, persists thumbnails, and registers entities into SQLite TrackerDB.
"""

import logging
import os
import time
import uuid
from typing import Any

import cv2
import numpy as np

from intelligent_tracker.reid.factory import ReIDExtractorFactory

logger = logging.getLogger(__name__)
CROPS_DIR = os.path.join("data", "crops")


def _save_tag_crop_and_anchor(
    db: Any, entity_id: int, entity_name: str, notes: str, emb: np.ndarray, crop: np.ndarray
) -> tuple[int, str]:
    """Write collision-free crop image and persist locked anchor + descriptor version."""
    slug = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in entity_name.lower())
    crop_rel_path = os.path.join(
        CROPS_DIR, f"{slug}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}.jpg"
    ).replace("\\", "/")
    abs_crop_path = os.path.abspath(crop_rel_path)
    os.makedirs(os.path.dirname(abs_crop_path), exist_ok=True)
    cv2.imwrite(abs_crop_path, crop)
    sig_id = db.add_signature(entity_id=entity_id, embedding=emb, crop_path=crop_rel_path, is_anchor=1, locked=1)
    if hasattr(db, "record_descriptor_version"):
        db.record_descriptor_version(
            entity_id=entity_id, embedding=emb, crop_path=crop_rel_path,
            source="manual_tag", notes=notes or "Manual tag anchor", is_anchor=1,
        )
    return sig_id, crop_rel_path


def _sync_matcher_and_bridge(
    gallery_matcher: Any, world_bridge: Any, track_id: int | None,
    entity_id: int | None, entity_name: str, category: str, camera_id: str,
) -> None:
    """Update GalleryMatcher cache and WorldEntityBridge assignment after tagging."""
    if gallery_matcher is not None:
        if track_id is not None and isinstance(getattr(gallery_matcher, "_identified_tracks", None), dict):
            gallery_matcher._identified_tracks[track_id] = {
                "entity_id": entity_id, "entity_name": entity_name, "category": category, "reid_score": 1.0,
            }
        try:
            gallery_matcher.refresh_gallery()
        except Exception:
            pass
    if world_bridge is not None and track_id is not None and entity_id is not None and hasattr(world_bridge, "reassign_track"):
        try:
            world_bridge.reassign_track(
                camera_id=camera_id, track_id=track_id, entity_id=entity_id, name=entity_name, category=category,
            )
        except Exception:
            pass


class EntityTaggerService:
    """Handles click-to-tag crop extraction, Re-ID embedding, and DB registration."""

    @staticmethod
    def _resolve_target_bbox(
        bbox: list[int] | None,
        track_id: int | None,
        tracker: Any,
    ) -> list[int]:
        """Resolve a 4-element [x, y, w, h] box from explicit bbox or active track."""
        if bbox and len(bbox) == 4:
            return [int(v) for v in bbox]
        if track_id is not None and tracker is not None:
            tracks = getattr(tracker, "tracks", {}) or {}
            trk = tracks.get(track_id)
            if trk is not None and getattr(trk, "bbox", None) is not None:
                return [int(v) for v in trk.bbox]
        raise ValueError("Select or draw a bounding box on the video before tagging")

    @staticmethod
    def _extract_bounded_crop(
        raw_frame: np.ndarray,
        target_bbox: list[int],
    ) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        """Clamp [x, y, w, h] to frame bounds and slice the BGR crop."""
        bx, by, bw, bh = target_bbox
        h, w = raw_frame.shape[:2]
        x1 = max(0, min(w - 1, bx))
        y1 = max(0, min(h - 1, by))
        x2 = max(x1 + 1, min(w, bx + bw))
        y2 = max(y1 + 1, min(h, by + bh))
        return raw_frame[y1:y2, x1:x2], (bx, by, bw, bh)

    @staticmethod
    def _compute_deterministic_embedding(
        crop: np.ndarray,
        reid_extractor: Any = None,
    ) -> np.ndarray:
        """Compute visual Re-ID embedding, falling back to deterministic color descriptor."""
        emb = None
        if reid_extractor is not None and crop.size > 0:
            try:
                emb = reid_extractor.extract_crop(crop)
            except Exception as exc:
                logger.warning("Failed to compute Re-ID embedding for tag: %s", exc)
        if emb is None or not isinstance(emb, np.ndarray):
            emb = ReIDExtractorFactory.create("color").extract_crop(crop)
        return emb

    @staticmethod
    def _upsert_entity_and_signature(
        db: Any,
        entity_name: str,
        category: str,
        notes: str,
        emb: np.ndarray,
        crop: np.ndarray,
        camera_id: str,
        track_id: int | None,
        bbox_tuple: tuple[int, int, int, int],
    ) -> tuple[int, int, str]:
        """Persist entity, thumbnail crop, Re-ID signature, and manual sighting."""
        existing = db.get_entity_by_name(entity_name)
        if existing:
            entity_id = existing["id"]
            if category:
                db.update_entity(entity_id, category=category, notes=notes)
        else:
            entity_id = db.add_entity(name=entity_name, category=category, notes=notes)

        sig_id, crop_rel_path = _save_tag_crop_and_anchor(db, entity_id, entity_name, notes, emb, crop)
        bx, by, bw, bh = bbox_tuple
        db.record_sighting(
            entity_id=entity_id, track_id=track_id or 0, source=camera_id,
            zone_id="manual_tag", bbox=f"{bx},{by},{bw},{bh}",
            confidence=1.0, snapshot_path=crop_rel_path,
        )
        return entity_id, sig_id, crop_rel_path

    @staticmethod
    def _update_live_track_identity(
        tracker: Any,
        track_id: int | None,
        entity_name: str,
        category: str,
        gallery_matcher: Any,
        *,
        entity_id: int | None = None,
        camera_id: str = "cam_01",
        world_bridge: Any = None,
    ) -> None:
        """Propagate newly tagged identity to active tracker track, gallery matcher, and world bridge."""
        if track_id is not None and tracker is not None:
            trk = (getattr(tracker, "tracks", {}) or {}).get(track_id)
            if trk is not None:
                if entity_id is not None:
                    trk.entity_id = entity_id
                trk.entity_name = entity_name
                trk.category = category
                trk.entity_category = category
                trk.identity_label = entity_name
                trk.reid_score = 1.0
        _sync_matcher_and_bridge(gallery_matcher, world_bridge, track_id, entity_id, entity_name, category, camera_id)

    @staticmethod
    def tag_entity(
        raw_frame: np.ndarray | None,
        db: Any,
        entity_name: str,
        category: str = "person",
        track_id: int | None = None,
        bbox: list[int] | None = None,
        notes: str = "",
        camera_id: str = "cam_01",
        tracker: Any = None,
        reid_extractor: Any = None,
        gallery_matcher: Any = None,
        world_bridge: Any = None,
    ) -> dict[str, Any]:
        """Extract frame crop, compute deterministic Re-ID embedding, and register entity."""
        if not db:
            raise RuntimeError("Database not available")
        if raw_frame is None or raw_frame.size == 0:
            raise RuntimeError("No video frame available to extract visual signature")

        target_bbox = EntityTaggerService._resolve_target_bbox(bbox, track_id, tracker)
        crop, bbox_tuple = EntityTaggerService._extract_bounded_crop(raw_frame, target_bbox)
        emb = EntityTaggerService._compute_deterministic_embedding(crop, reid_extractor)
        entity_id, sig_id, crop_rel_path = EntityTaggerService._upsert_entity_and_signature(
            db, entity_name, category, notes, emb, crop, camera_id, track_id, bbox_tuple)
        EntityTaggerService._update_live_track_identity(
            tracker, track_id, entity_name, category, gallery_matcher,
            entity_id=entity_id, camera_id=camera_id, world_bridge=world_bridge)
        logger.info("Successfully tagged entity '%s' (ID #%d, sig #%d)", entity_name, entity_id, sig_id)
        return {"entity_id": entity_id, "name": entity_name, "category": category,
                "signature_id": sig_id, "crop_path": crop_rel_path}

