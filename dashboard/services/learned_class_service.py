"""Service layer for exemplar learned classes, collision guards, and per-camera COCO overrides."""

import logging
import os
import uuid
from typing import Any

import cv2
import numpy as np

from dashboard.services.roi_recognition_service import RoiRecognitionService
from intelligent_tracker.matching.learned_class_matcher import LearnedClassMatcher
from intelligent_tracker.reid import ReIDExtractorFactory

logger = logging.getLogger(__name__)


def _extract_roi_from_frame(frame: np.ndarray, bbox: list[float] | tuple[float, ...] | None) -> np.ndarray:
    """Crop (x, y, w, h) ROI from frame, or return full frame when bbox is omitted."""
    if bbox is None or len(bbox) < 4:
        return frame
    h, w = int(frame.shape[0]), int(frame.shape[1])
    x1 = max(0, int(round(float(bbox[0]))))
    y1 = max(0, int(round(float(bbox[1]))))
    x2 = min(w, int(round(float(bbox[0]) + float(bbox[2]))))
    y2 = min(h, int(round(float(bbox[1]) + float(bbox[3]))))
    if x2 <= x1 or y2 <= y1:
        raise ValueError("Invalid ROI bbox coordinates")
    return frame[y1:y2, x1:x2]


def _resolve_crop(
    camera_pool: Any,
    crop_base64: str,
    camera_id: str,
    bbox: list[float] | None,
) -> np.ndarray:
    """Decode base64 crop or extract ROI from live camera frame."""
    if crop_base64 and crop_base64.strip():
        return RoiRecognitionService._decode_base64_image(crop_base64)
    if not camera_id or camera_pool is None:
        raise ValueError("Provide either crop_base64 or an active camera_id")
    sm = camera_pool.get_stream(camera_id)
    if sm is None:
        raise LookupError(f"Camera '{camera_id}' not found")
    with sm._lock:
        raw = getattr(sm, "_latest_raw_frame", None)
        frame = raw.copy() if raw is not None else None
    if frame is None or frame.size == 0:
        raise RuntimeError(f"No frame available for camera '{camera_id}'")
    return _extract_roi_from_frame(frame, bbox)


def _save_crop_file(crops_dir: str, crop: np.ndarray) -> str:
    """Persist exemplar crop JPEG under crops_dir/learned_classes."""
    out_dir = os.path.join(crops_dir, "learned_classes")
    os.makedirs(out_dir, exist_ok=True)
    filename = f"lc_{uuid.uuid4().hex[:12]}.jpg"
    cv2.imwrite(os.path.join(out_dir, filename), crop)
    return f"/crops/learned_classes/{filename}"


class LearnedClassService:
    """Coordinates learned class CRUD, DualModel exemplar enrollment, and live matcher reloads."""

    def __init__(
        self,
        db: Any,
        camera_pool: Any = None,
        crops_dir: str = os.path.join("data", "crops"),
        extractor: Any = None,
    ) -> None:
        self.db = db
        self.camera_pool = camera_pool
        self.crops_dir = crops_dir
        self._extractor = extractor

    def _resolve_extractor(self) -> Any:
        """Resolve canonical DualModel Re-ID extractor via active pool or factory."""
        if self._extractor is not None:
            return self._extractor
        if self.camera_pool is not None:
            streams = getattr(self.camera_pool, "_streams", None) or {}
            for sm in streams.values():
                bundle = getattr(sm, "_bundle", None) or getattr(sm, "bundle", None)
                ext = getattr(bundle, "reid_extractor", None)
                if ext is not None:
                    self._extractor = ext
                    return ext
        try:
            self._extractor = ReIDExtractorFactory.create("onnx")
        except Exception as exc:
            logger.warning("LearnedClassService: falling back to mock extractor: %s", exc)
            self._extractor = ReIDExtractorFactory.create("mock")
        return self._extractor

    def reload_pool_matchers(self, camera_id: str | None = None) -> None:
        """Reload LearnedClassMatcher across active camera pool streams."""
        if self.camera_pool is None:
            return
        streams = getattr(self.camera_pool, "_streams", None) or {}
        for cam_key, sm in list(streams.items()):
            if camera_id and str(cam_key) != str(camera_id):
                continue
            bundle = getattr(sm, "_bundle", None) or getattr(sm, "bundle", None)
            matcher = getattr(bundle, "learned_class_matcher", None)
            if matcher is not None and hasattr(matcher, "reload"):
                try:
                    matcher.reload()
                except Exception as exc:
                    logger.debug("LearnedClassService: matcher reload failed for %s: %s", cam_key, exc)

    def list_classes(self) -> list[dict[str, Any]]:
        """List all learned classes with exemplar counts."""
        return self.db.list_learned_classes()

    def create_class(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a learned class and reload live matchers."""
        record = self.db.create_learned_class(
            name=payload.get("name", ""),
            slug=payload.get("slug", ""),
            parent_coco_class=payload.get("parent_coco_class", ""),
            color=payload.get("color", "#06B6D4"),
            threshold=float(payload.get("threshold", 0.65)),
            description=payload.get("description", ""),
        )
        self.reload_pool_matchers()
        return record

    def update_class(self, class_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Update a learned class and reload live matchers."""
        record = self.db.update_learned_class(class_id, **payload)
        if record is not None:
            self.reload_pool_matchers()
        return record

    def delete_class(self, class_id: int) -> bool:
        """Delete a learned class and reload live matchers."""
        deleted = self.db.delete_learned_class(class_id)
        if deleted:
            self.reload_pool_matchers()
        return deleted

    def enroll_exemplar(
        self,
        class_id: int,
        *,
        crop_base64: str = "",
        camera_id: str = "",
        bbox: list[float] | None = None,
        notes: str = "",
        force: bool = False,
        collision_threshold: float = 0.78,
    ) -> dict[str, Any]:
        """Extract DualModel embedding, run collision guard, and persist exemplar."""
        if self.db.get_learned_class(class_id) is None:
            raise LookupError(f"Learned class {class_id} not found")
        crop = _resolve_crop(self.camera_pool, crop_base64, camera_id, bbox)
        extractor = self._resolve_extractor()
        embedding = extractor.extract(crop)
        collisions = LearnedClassMatcher(self.db, extractor=extractor).check_collision(
            embedding, threshold=collision_threshold, exclude_class_id=class_id,
        )
        if collisions and not force:
            return {"status": "collision", "enrolled": False, "class_id": class_id, "collisions": collisions}
        crop_path = _save_crop_file(self.crops_dir, crop)
        exemplar_id = self.db.add_learned_class_exemplar(
            class_id=class_id, embedding=embedding, crop_path=crop_path, source_camera_id=camera_id, notes=notes,
        )
        self.reload_pool_matchers()
        return {"status": "ok", "enrolled": True, "class_id": class_id, "exemplar_id": exemplar_id, "crop_path": crop_path, "collisions": collisions}

    def delete_exemplar(self, exemplar_id: int) -> bool:
        """Delete a single exemplar and reload live matchers."""
        deleted = self.db.delete_learned_class_exemplar(exemplar_id)
        if deleted:
            self.reload_pool_matchers()
        return deleted

    def get_camera_overrides(self, camera_id: str) -> list[dict[str, Any]]:
        """List per-camera COCO class suppress/relabel overrides."""
        return self.db.get_camera_class_overrides(camera_id)

    def set_camera_override(
        self,
        camera_id: str,
        coco_class: str,
        action: str = "suppress",
        relabel_to: str = "",
    ) -> dict[str, Any]:
        """Upsert a per-camera COCO class override and reload that camera's matcher."""
        record = self.db.set_camera_class_override(camera_id, coco_class, action=action, relabel_to=relabel_to)
        self.reload_pool_matchers(camera_id=camera_id)
        return record

    def delete_camera_override(self, camera_id: str, coco_class: str) -> bool:
        """Delete a per-camera COCO class override and reload that camera's matcher."""
        deleted = self.db.delete_camera_class_override(camera_id, coco_class)
        if deleted:
            self.reload_pool_matchers(camera_id=camera_id)
        return deleted
