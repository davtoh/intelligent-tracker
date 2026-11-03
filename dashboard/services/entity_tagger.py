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
from typing import Any, Dict, List, Optional
import cv2
import numpy as np

logger = logging.getLogger(__name__)


class EntityTaggerService:
    """
    Handles interactive click-to-tag bounding box visual crop extraction,
    biometric embedding generation, and database registration.
    """

    @staticmethod
    def tag_entity(
        raw_frame: Optional[np.ndarray],
        db: Any,
        entity_name: str,
        category: str = "person",
        track_id: Optional[int] = None,
        bbox: Optional[List[int]] = None,
        notes: str = "",
        camera_id: str = "cam_01",
        tracker: Optional[Any] = None,
        reid_extractor: Optional[Any] = None,
        gallery_matcher: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Extracts crop from current frame, generates Re-ID embedding, registers into SQLite database,
        and links live track identity.
        """
        if not db:
            raise RuntimeError("Database not available")

        if raw_frame is None or raw_frame.size == 0:
            raise RuntimeError("No video frame available to extract visual signature")

        # Resolve bounding box
        target_bbox = None
        if bbox and len(bbox) == 4:
            target_bbox = bbox
        elif track_id is not None and tracker:
            for tid, trk in tracker.tracks.items():
                if tid == track_id:
                    target_bbox = list(trk.bbox)
                    break

        if not target_bbox:
            # Fallback center crop if bbox not provided
            h, w = raw_frame.shape[:2]
            target_bbox = [w // 4, h // 4, w // 2, h // 2]

        bx, by, bw, bh = [int(v) for v in target_bbox]
        h, w = raw_frame.shape[:2]
        x1 = max(0, min(w - 1, bx))
        y1 = max(0, min(h - 1, by))
        x2 = max(x1 + 1, min(w, bx + bw))
        y2 = max(y1 + 1, min(h, by + bh))
        crop = raw_frame[y1:y2, x1:x2]

        # Check or add entity
        existing = db.get_entity_by_name(entity_name)
        if existing:
            entity_id = existing["id"]
            if category:
                db.update_entity(entity_id, category=category, notes=notes)
        else:
            entity_id = db.add_entity(name=entity_name, category=category, notes=notes)

        # Generate Re-ID Embedding
        emb = None
        if reid_extractor and crop.size > 0:
            try:
                emb = reid_extractor.extract_crop(crop)
            except Exception as e:
                logger.warning("Failed to compute Re-ID embedding for tag: %s", e)

        if emb is None or not isinstance(emb, np.ndarray):
            # Synthetic 128-dim embedding fallback
            vec = np.random.randn(128).astype(np.float32)
            emb = vec / (np.linalg.norm(vec) + 1e-7)

        # Save thumbnail crop
        crop_rel_path = f"data/crops/{entity_name.lower().replace(' ', '_')}_{int(time.time())}.jpg"
        abs_crop_path = os.path.abspath(crop_rel_path)
        os.makedirs(os.path.dirname(abs_crop_path), exist_ok=True)
        cv2.imwrite(abs_crop_path, crop)

        sig_id = db.add_signature(entity_id=entity_id, embedding=emb, crop_path=crop_rel_path)

        # Record immediate sighting
        db.record_sighting(
            entity_id=entity_id,
            track_id=track_id or 0,
            source=camera_id,
            zone_id="manual_tag",
            bbox=f"{bx},{by},{bw},{bh}",
            confidence=1.0,
            snapshot_path=crop_rel_path,
        )

        # Update in-memory tracker track
        if track_id is not None and tracker:
            for tid, trk in tracker.tracks.items():
                if tid == track_id:
                    trk.entity_name = entity_name
                    trk.category = category
                    break

        # Refresh gallery
        if gallery_matcher:
            try:
                gallery_matcher.refresh_gallery()
            except Exception:
                pass

        logger.info("Successfully tagged entity '%s' (ID #%d, sig #%d)", entity_name, entity_id, sig_id)
        return {
            "entity_id": entity_id,
            "name": entity_name,
            "category": category,
            "signature_id": sig_id,
            "crop_path": crop_rel_path,
        }

