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
from typing import Dict, Optional, Any, Tuple

import cv2
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import BaseFeatureExtractor, DualModelFeatureExtractor


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
    ) -> Dict[str, Any]:
        """
        Universally enroll an entity with dual-model feature extraction.

        :param name: Entity name (e.g. 'Alice Smith', 'Blue Sedan', 'Delivery Van #3').
        :param category: Semantic category badge (e.g. 'person', 'family_car', 'delivery_truck', 'guard_dog', 'pet', 'tool', 'package').
        :param frame: Full image frame (used if bbox is provided).
        :param bbox: (x, y, w, h) bounding box within frame.
        :param crop: Direct crop image (used if frame+bbox not provided).
        :param notes: Metadata notes.
        :param security_role: Optional role or clearance description.
        :param is_anchor: Whether to flag this signature as a ground-truth Locked Anchor.
        :return: Dict containing entity_id, signature_id, crop_path, category, and name.
        """
        target_crop = None

        if crop is not None and crop.size > 0:
            target_crop = crop
        elif frame is not None and bbox is not None:
            x, y, w, h = [int(v) for v in bbox]
            ih, iw = frame.shape[:2]
            x1 = max(0, min(x, iw - 1))
            y1 = max(0, min(y, ih - 1))
            x2 = max(x1 + 1, min(x + w, iw))
            y2 = max(y1 + 1, min(y + h, ih))
            target_crop = frame[y1:y2, x1:x2]

        if target_crop is None or target_crop.size == 0 or target_crop.shape[0] < 4 or target_crop.shape[1] < 4:
            raise ValueError("Valid image crop or frame with bounding box must be provided for enrollment")

        # 1. Dual-Model Feature Extraction (Artifact + Face)
        embedding = self.extractor.extract_crop(target_crop)

        # 2. Save thumbnail crop
        clean_name = name.strip().replace(" ", "_").lower()
        now_ts = int(time.time())
        rand_id = np.random.randint(1000, 9999)
        crop_filename = f"entity_{clean_name}_{now_ts}_{rand_id}.jpg"
        crop_path = os.path.join(self.crops_dir, crop_filename)
        cv2.imwrite(crop_path, target_crop)

        # 3. Create or update entity record in TrackerDB
        combined_notes = notes.strip()
        if security_role:
            combined_notes = f"[Role: {security_role.strip()}] {combined_notes}".strip()

        existing = self.db.get_entity_by_name(name)
        if existing:
            entity_id = existing["id"]
            self.db.update_entity(entity_id, category=category, notes=combined_notes)
        else:
            entity_id = self.db.add_entity(name=name, category=category, notes=combined_notes)

        # 4. Enroll signature as Locked Anchor
        signature_id = self.db.add_signature(
            entity_id=entity_id,
            embedding=embedding,
            crop_path=crop_path,
            is_anchor=1 if is_anchor else 0,
            locked=1 if is_anchor else 0,
        )

        # 5. Record descriptor version history
        self.db.record_descriptor_version(
            entity_id=entity_id,
            embedding=embedding,
            crop_path=crop_path,
            source="manual_enrollment",
            notes=f"Universal Enrollment ({category}) - Locked Anchor" if is_anchor else f"Universal Enrollment ({category})",
            is_anchor=1 if is_anchor else 0,
        )

        # 6. Hot-reload gallery matcher for immediate recognition
        if self.matcher and hasattr(self.matcher, "reload_gallery"):
            self.matcher.reload_gallery()

        return {
            "status": "success",
            "entity_id": entity_id,
            "signature_id": signature_id,
            "name": name,
            "category": category,
            "crop_path": crop_path,
            "is_anchor": is_anchor,
            "embedding_dim": len(embedding),
        }
