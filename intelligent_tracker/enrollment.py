#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Universal Artifact & Face Enrollment Module.

Provides:
- ``UniversalEnrollmentManager``: Universal enrollment for any real-world entity:
  human face, full person, vehicle, package, tool, or pet.
- Dual-model visual biometric extraction (YuNet ONNX Face Detector + OSNet Re-ID / Color).
- Automatic Locked Anchor protection and descriptor versioning.
- Role-based category assignment and access permission configuration.
- Real-time gallery hot-reloading for immediate multi-camera identification.
"""

import os
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import BaseFeatureExtractor, DualModelFeatureExtractor, batch_cosine_similarity


class UniversalEnrollmentManager:
    """
    Coordinates universal entity enrollment from freeze-frame crops, uploaded images,
    or live video bounding box selections.
    """

    def __init__(
        self,
        db: TrackerDB,
        extractor: Optional[BaseFeatureExtractor] = None,
        crops_dir: str = "data/crops",
        matcher: Optional[Any] = None,
    ):
        """
        :param db: TrackerDB database instance.
        :param extractor: Feature extractor (defaults to DualModelFeatureExtractor).
        :param crops_dir: Target directory for persistent thumbnail crops.
        :param matcher: Optional active GalleryMatcher to trigger reload on enrollment.
        """
        self.db = db
        self.extractor = extractor or DualModelFeatureExtractor()
        self.crops_dir = crops_dir
        self.matcher = matcher
        os.makedirs(self.crops_dir, exist_ok=True)

    @staticmethod
    def _resolve_target_crop(
        frame: Optional[np.ndarray] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
        crop: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """Extract and validate a >= 4x4 BGR crop from direct crop or frame+bbox."""
        target_crop = None
        if crop is not None and crop.size > 0:
            target_crop = crop
        elif frame is not None and bbox is not None:
            x, y, w, h = [int(v) for v in bbox]
            ih, iw = frame.shape[:2]
            x1, y1 = max(0, min(x, iw - 1)), max(0, min(y, ih - 1))
            x2, y2 = max(x1 + 1, min(x + w, iw)), max(y1 + 1, min(y + h, ih))
            target_crop = frame[y1:y2, x1:x2]
        if target_crop is None or target_crop.size == 0 or target_crop.shape[0] < 4 or target_crop.shape[1] < 4:
            raise ValueError("Valid image crop or frame with bounding box must be provided for enrollment")
        return target_crop

    def _save_crop_thumbnail(self, name: str, target_crop: np.ndarray) -> str:
        """Persist enrollment crop JPEG thumbnail and return file path."""
        clean_name = name.strip().replace(" ", "_").lower() or "entity"
        crop_filename = f"entity_{clean_name}_{int(time.time())}_{int(np.random.randint(1000, 9999))}.jpg"
        crop_path = os.path.join(self.crops_dir, crop_filename)
        cv2.imwrite(crop_path, target_crop)
        return crop_path

    def _resolve_or_create_entity(
        self,
        name: str,
        category: str,
        notes: str,
        security_role: str,
        merge_entity_id: Optional[int] = None,
        force_create_new: bool = False,
    ) -> Tuple[int, str, str]:
        """Resolve merge target, existing entity by name, or create a new entity record."""
        combined_notes = notes.strip()
        if security_role:
            combined_notes = f"[Role: {security_role.strip()}] {combined_notes}".strip()
        if merge_entity_id is not None:
            target = self.db.get_entity(int(merge_entity_id))
            if not target:
                raise ValueError(f"Merge target entity {merge_entity_id} not found")
            return int(merge_entity_id), str(target.get("name") or name), str(target.get("category") or category)
        if not force_create_new:
            existing = self.db.get_entity_by_name(name)
            if existing:
                entity_id = int(existing["id"])
                self.db.update_entity(entity_id, category=category, notes=combined_notes)
                return entity_id, name, category
        entity_id = int(self.db.add_entity(name=name, category=category, notes=combined_notes))
        return entity_id, name, category

    def check_collision(
        self,
        frame: Optional[np.ndarray] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
        crop: Optional[np.ndarray] = None,
        threshold: float = 0.72,
        top_k: int = 3,
    ) -> Dict[str, Any]:
        """Check if a candidate crop collides visually with existing gallery entities."""
        target_crop = self._resolve_target_crop(frame=frame, bbox=bbox, crop=crop)
        embedding = self.extractor.extract_crop(target_crop)
        mat, entity_ids, names, categories = self.db.get_gallery_embeddings()
        if mat is None or len(entity_ids) == 0:
            return {"has_collision": False, "threshold": float(threshold), "matches": []}
        sims = batch_cosine_similarity(mat, embedding)
        best_by_entity: Dict[int, Dict[str, Any]] = {}
        for idx, sim in enumerate(sims):
            score = float(sim)
            if score < float(threshold):
                continue
            eid = int(entity_ids[idx])
            if eid not in best_by_entity or score > best_by_entity[eid]["similarity"]:
                best_by_entity[eid] = {
                    "entity_id": eid,
                    "name": str(names[idx]),
                    "category": str(categories[idx]),
                    "similarity": round(score, 4),
                }
        matches: List[Dict[str, Any]] = sorted(
            best_by_entity.values(), key=lambda m: m["similarity"], reverse=True
        )[: max(1, int(top_k))]
        return {"has_collision": len(matches) > 0, "threshold": float(threshold), "matches": matches}

    def enroll(
        self,
        name: str,
        category: str = "person",
        frame: Optional[np.ndarray] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
        crop: Optional[np.ndarray] = None,
        notes: str = "",
        security_role: str = "",
        is_anchor: bool = True,
        merge_entity_id: Optional[int] = None,
        force_create_new: bool = False,
        camera_id: str = "",
        source: str = "",
        zone_id: str = "",
        track_id: Optional[int] = None,
        video_filename: str = "",
        media_offset_sec: float = 0.0,
        run_id: str = "",
    ) -> Dict[str, Any]:
        """Universally enroll an entity with dual-model feature extraction."""
        target_crop = self._resolve_target_crop(frame=frame, bbox=bbox, crop=crop)
        embedding = self.extractor.extract_crop(target_crop)
        crop_path = self._save_crop_thumbnail(name, target_crop)
        entity_id, resolved_name, resolved_cat = self._resolve_or_create_entity(
            name, category, notes, security_role,
            merge_entity_id=merge_entity_id, force_create_new=force_create_new,
        )
        signature_id = self.db.add_signature(
            entity_id=entity_id, embedding=embedding, crop_path=crop_path,
            is_anchor=1 if is_anchor else 0, locked=1 if is_anchor else 0,
        )
        ver_note = f"Universal Enrollment ({resolved_cat})" + (" - Locked Anchor" if is_anchor else "")
        self.db.record_descriptor_version(
            entity_id=entity_id, embedding=embedding, crop_path=crop_path,
            source="manual_enrollment", notes=ver_note, is_anchor=1 if is_anchor else 0,
        )
        if hasattr(self.db, "add_sighting"):
            resolved_source = str(source or camera_id or video_filename or "enrollment").strip()
            self.db.add_sighting(
                entity_id=entity_id, track_id=track_id, source=resolved_source,
                zone_id=zone_id or "enrollment", bbox=bbox or "", confidence=1.0,
                snapshot_path=crop_path, video_filename=video_filename,
                media_offset_sec=media_offset_sec, camera_id=camera_id, run_id=run_id,
            )
        if self.matcher and hasattr(self.matcher, "reload_gallery"):
            self.matcher.reload_gallery()
        return {
            "status": "success", "entity_id": entity_id, "signature_id": signature_id,
            "name": resolved_name, "category": resolved_cat, "crop_path": crop_path,
            "is_anchor": is_anchor, "embedding_dim": len(embedding),
            "merged": merge_entity_id is not None,
        }
