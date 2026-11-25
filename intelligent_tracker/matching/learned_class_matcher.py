"""Exemplar-based LearnedClassMatcher with per-camera COCO override enforcement."""

import copy
import logging
import threading
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    """Return an L2-normalized float32 1D vector, or empty array on zero norm."""
    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return np.empty(0, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    return (arr / norm) if norm > 1e-8 else np.empty(0, dtype=np.float32)


def _extract_crop(frame: np.ndarray, bbox: Any) -> np.ndarray | None:
    """Safely slice a (x, y, w, h) bounding box crop from a BGR frame."""
    if frame is None or not hasattr(frame, "shape") or bbox is None or len(bbox) < 4:
        return None
    h, w = int(frame.shape[0]), int(frame.shape[1])
    x1 = max(0, int(round(bbox[0])))
    y1 = max(0, int(round(bbox[1])))
    x2 = min(w, int(round(bbox[0] + bbox[2])))
    y2 = min(h, int(round(bbox[1] + bbox[3])))
    if x2 <= x1 or y2 <= y1:
        return None
    crop = frame[y1:y2, x1:x2]
    return crop if crop.size > 0 else None


def _clone_with_label(det: Any, new_label: str) -> Any:
    """Return a detection copy with updated class_name/label."""
    if isinstance(det, tuple) and hasattr(det, "_replace"):
        fields = getattr(det, "_fields", ())
        updates = {k: new_label for k in ("class_name", "label") if k in fields}
        return det._replace(**updates) if updates else det
    cloned = copy.copy(det)
    if hasattr(cloned, "class_name"):
        cloned.class_name = new_label
    if hasattr(cloned, "label"):
        cloned.label = new_label
    return cloned


class LearnedClassMatcher:
    """Scores ROI embeddings against learned class prototypes and applies COCO overrides."""

    def __init__(
        self,
        db: Any,
        extractor: Any = None,
        camera_id: str = "",
    ) -> None:
        self.db = db
        self.extractor = extractor
        self.camera_id = str(camera_id or "").strip()
        self._lock = threading.RLock()
        self._prototypes: list[dict[str, Any]] = []
        self._overrides: dict[str, dict[str, str]] = {}
        self.reload(self.camera_id)

    def reload(self, camera_id: str | None = None) -> None:
        """Reload learned class prototypes and per-camera COCO overrides from TrackerDB."""
        if camera_id is not None:
            self.camera_id = str(camera_id).strip()
        prototypes = self._build_prototypes()
        overrides = self._load_overrides(self.camera_id)
        with self._lock:
            self._prototypes = prototypes
            self._overrides = overrides

    def _build_prototypes(self) -> list[dict[str, Any]]:
        """Group exemplar embeddings by class_id and compute L2-normalized prototypes."""
        if self.db is None or not hasattr(self.db, "list_learned_class_exemplars"):
            return []
        try:
            exemplars = self.db.list_learned_class_exemplars()
        except Exception as exc:
            logger.debug("LearnedClassMatcher: failed loading exemplars: %s", exc)
            return []
        grouped: dict[int, dict[str, Any]] = {}
        for item in exemplars:
            vec = _l2_normalize(item.get("embedding", np.empty(0, dtype=np.float32)))
            if vec.size == 0:
                logger.debug("LearnedClassMatcher: skipping empty exemplar for class_id=%s", item.get("class_id"))
                continue
            cid = int(item["class_id"])
            bucket = grouped.setdefault(
                cid,
                {
                    "class_id": cid,
                    "name": item.get("class_name", ""),
                    "slug": item.get("slug", ""),
                    "parent_coco_class": str(item.get("parent_coco_class") or "").strip().lower(),
                    "color": item.get("color", "#06B6D4"),
                    "threshold": float(item.get("threshold", 0.65)),
                    "vectors": [],
                },
            )
            if not bucket["vectors"] or bucket["vectors"][0].shape == vec.shape:
                bucket["vectors"].append(vec)
        prototypes: list[dict[str, Any]] = []
        for bucket in grouped.values():
            mean_vec = _l2_normalize(np.mean(np.stack(bucket["vectors"], axis=0), axis=0))
            if mean_vec.size > 0:
                bucket["prototype"] = mean_vec
                bucket.pop("vectors", None)
                prototypes.append(bucket)
        return prototypes

    def _load_overrides(self, camera_id: str) -> dict[str, dict[str, str]]:
        """Load per-camera COCO suppress/relabel rules keyed by lowercase coco_class."""
        if not camera_id or self.db is None or not hasattr(self.db, "get_camera_class_overrides"):
            return {}
        try:
            rows = self.db.get_camera_class_overrides(camera_id)
        except Exception as exc:
            logger.debug("LearnedClassMatcher: failed loading overrides for %s: %s", camera_id, exc)
            return {}
        return {
            str(r.get("coco_class", "")).strip().lower(): {
                "action": str(r.get("action", "suppress")).strip().lower(),
                "relabel_to": str(r.get("relabel_to", "")).strip(),
            }
            for r in rows
            if r.get("coco_class")
        }

    def score_embedding(
        self,
        embedding: np.ndarray,
        parent_coco_class: str = "",
    ) -> dict[str, Any] | None:
        """Return the highest-scoring learned class prototype above threshold, or None."""
        probe = _l2_normalize(embedding)
        if probe.size == 0:
            return None
        parent = str(parent_coco_class or "").strip().lower()
        with self._lock:
            protos = list(self._prototypes)
        best: dict[str, Any] | None = None
        for proto in protos:
            req_parent = proto.get("parent_coco_class", "")
            if req_parent and parent and req_parent != parent:
                continue
            pvec = proto["prototype"]
            if pvec.shape != probe.shape:
                logger.warning(
                    "LearnedClassMatcher dim mismatch for '%s': proto=%s probe=%s",
                    proto.get("name"), pvec.shape, probe.shape,
                )
                continue
            score = float(np.dot(probe, pvec))
            if score >= float(proto["threshold"]) and (best is None or score > best["score"]):
                best = {
                    "class_id": proto["class_id"],
                    "name": proto["name"],
                    "slug": proto["slug"],
                    "color": proto["color"],
                    "threshold": proto["threshold"],
                    "score": round(score, 4),
                }
        return best

    def _check_gallery_collisions(self, probe: np.ndarray, threshold: float) -> list[dict[str, Any]]:
        """Score probe against enrolled gallery entity signatures."""
        if self.db is None or not hasattr(self.db, "get_gallery_embeddings"):
            return []
        hits: list[dict[str, Any]] = []
        try:
            matrix, entity_ids, names, _cats = self.db.get_gallery_embeddings(expected_dim=int(probe.shape[0]))
            for idx, entity_id in enumerate(entity_ids):
                evec = _l2_normalize(matrix[idx])
                if evec.shape == probe.shape:
                    score = float(np.dot(probe, evec))
                    if score >= threshold:
                        hits.append({"kind": "entity", "id": int(entity_id), "name": str(names[idx]), "score": round(score, 4)})
        except Exception as exc:
            logger.debug("LearnedClassMatcher: gallery collision check skipped: %s", exc)
        return hits

    def check_collision(
        self,
        embedding: np.ndarray,
        *,
        threshold: float = 0.78,
        exclude_class_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Check whether an exemplar embedding collides with existing learned classes or gallery entities."""
        probe = _l2_normalize(embedding)
        if probe.size == 0:
            return []
        collisions: list[dict[str, Any]] = []
        with self._lock:
            protos = list(self._prototypes)
        for proto in protos:
            if exclude_class_id is not None and proto["class_id"] == int(exclude_class_id):
                continue
            pvec = proto["prototype"]
            if pvec.shape == probe.shape:
                score = float(np.dot(probe, pvec))
                if score >= threshold:
                    collisions.append({"kind": "learned_class", "id": proto["class_id"], "name": proto["name"], "score": round(score, 4)})
        collisions.extend(self._check_gallery_collisions(probe, threshold))
        collisions.sort(key=lambda item: item["score"], reverse=True)
        return collisions

    def apply_to_detections(
        self,
        frame: np.ndarray,
        detections: list[Any],
        camera_id: str | None = None,
    ) -> list[Any]:
        """Enforce per-camera COCO overrides and annotate detections with learned class matches."""
        if not detections:
            return []
        if camera_id and camera_id != self.camera_id:
            self.reload(camera_id)
        with self._lock:
            overrides = dict(self._overrides)
            has_protos = bool(self._prototypes)
        filtered: list[Any] = []
        for det in detections:
            raw_cls = str(getattr(det, "class_name", getattr(det, "label", "")) or "").strip().lower()
            rule = overrides.get(raw_cls)
            if rule:
                if rule["action"] == "suppress":
                    continue
                if rule["action"] == "relabel" and rule["relabel_to"]:
                    det = _clone_with_label(det, rule["relabel_to"])
                    raw_cls = rule["relabel_to"].lower()
            if has_protos and self.extractor is not None:
                crop = _extract_crop(frame, getattr(det, "bbox", None))
                if crop is not None:
                    try:
                        emb = self.extractor.extract(crop)
                        match = self.score_embedding(emb, parent_coco_class=raw_cls)
                        if match is not None and not isinstance(det, tuple):
                            det.learned_class = match["name"]
                            det.learned_class_score = match["score"]
                    except Exception as exc:
                        logger.debug("LearnedClassMatcher: extract/score error: %s", exc)
            filtered.append(det)
        return filtered
