#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - On-Demand ROI Recognition & Tag Commit Service.

Supports live camera frames, recorded video frame seeking, and direct base64
crops for on-demand object classification, Re-ID gallery matching, and tag
commitment into SQLite TrackerDB.
"""

import base64
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from dashboard.services.entity_tagger import EntityTaggerService
from intelligent_tracker.detectors import DetectorFactory
from intelligent_tracker.memory.confidence import ConfidenceEngine
from intelligent_tracker.reid import batch_cosine_similarity
from intelligent_tracker.reid.factory import ReIDExtractorFactory

logger = logging.getLogger(__name__)


class RoiNotFoundError(LookupError):
    """Raised when a requested camera, video, or frame cannot be located."""


class RoiUnavailableError(RuntimeError):
    """Raised when a live camera stream has no frame buffered yet."""


def _resolve_roi_services(
    db: Any, stream_manager: Any, camera_pool: Any, confidence_engine: Any, fts_index: Any,
) -> tuple[Any, Any]:
    """Resolve ConfidenceEngine and EventFTSIndex from explicit args, stream, or pool."""
    ce = confidence_engine or getattr(stream_manager, "confidence_engine", None) or getattr(camera_pool, "confidence_engine", None)
    if ce is None and db is not None:
        ce = ConfidenceEngine(db=db)
    fts = fts_index or getattr(stream_manager, "event_fts_index", None) or getattr(camera_pool, "event_fts_index", None)
    return ce, fts


def _record_roi_side_effects(
    svc: Any, *, entity_id: int, entity_name: str, category: str, emb: np.ndarray,
    crop_path: str, notes: str, source: str, track_id: int | None,
    camera_id: str | None, video_filename: str, media_offset_sec: float,
) -> None:
    """Record descriptor version, confidence feedback, FTS sighting, and live track sync."""
    if hasattr(svc.db, "record_descriptor_version"):
        svc.db.record_descriptor_version(
            entity_id=entity_id, embedding=emb, crop_path=crop_path,
            source="manual_roi", notes=notes or "ROI tag anchor", is_anchor=1,
        )
    if svc.confidence_engine is not None:
        try:
            svc.confidence_engine.record_human_feedback(
                entity_id=entity_id, action="confirm", camera_id=source, zone_id="manual_roi",
            )
        except Exception as exc:
            logger.debug("ROI confidence feedback skipped: %s", exc)
    if svc.fts_index is not None:
        try:
            svc.fts_index.index_sighting(
                entity_id=entity_id, entity_name=entity_name, category=category,
                camera_id=source, zone_id="manual_roi", confidence=1.0,
                metadata={"track_id": track_id or 0}, video_filename=video_filename, media_offset_sec=media_offset_sec,
            )
        except Exception as exc:
            logger.debug("ROI FTS indexing skipped: %s", exc)
    mgr = svc.stream_manager or (svc.camera_pool.get_stream(camera_id) if camera_id and svc.camera_pool else None)
    if mgr is not None:
        EntityTaggerService._update_live_track_identity(
            getattr(mgr, "tracker", None), track_id, entity_name, category,
            getattr(mgr, "gallery_matcher", None), entity_id=entity_id,
            camera_id=camera_id or source, world_bridge=getattr(mgr, "world_bridge", None),
        )


def _resolve_roi_models(stream_manager: Any, camera_pool: Any) -> tuple[Any, Any]:
    """Resolve configured detector and Re-ID extractor from stream, pool, or factories."""
    det = getattr(stream_manager, "detector", None) if stream_manager else None
    reid = getattr(stream_manager, "reid_extractor", None) if stream_manager else None
    if (det is None or reid is None) and camera_pool is not None:
        from dashboard.services.camera_pool_queries import snapshot_pool_streams

        for mgr in snapshot_pool_streams(camera_pool).values():
            det = det or getattr(mgr, "detector", None)
            reid = reid or getattr(mgr, "reid_extractor", None)
            if det is not None and reid is not None:
                break
    if det is None:
        try:
            det = DetectorFactory.create("yolov8")
        except Exception:
            det = None
    if reid is None:
        for model_name in ("osnet", "color"):
            try:
                reid = ReIDExtractorFactory.create(model_name)
                break
            except Exception:
                continue
    return det, reid


class RoiRecognitionService:
    """Service for on-demand ROI recognition and tag commitment."""

    def __init__(
        self, db: Any, stream_manager: Any = None, camera_pool: Any = None,
        videos_dir: str = os.path.join("data", "videos"), crops_dir: str = os.path.join("data", "crops"),
        confidence_engine: Any = None, fts_index: Any = None,
    ) -> None:
        self.db, self.stream_manager, self.camera_pool = db, stream_manager, camera_pool
        self.videos_dir, self.crops_dir = videos_dir, crops_dir
        self.confidence_engine, self.fts_index = _resolve_roi_services(
            db, stream_manager, camera_pool, confidence_engine, fts_index
        )

    @staticmethod
    def _decode_base64_image(crop_base64: str) -> np.ndarray:
        """Decode a raw or data-URI base64 image string into a BGR ndarray."""
        payload = crop_base64.strip()
        if "," in payload and payload.lower().startswith("data:"):
            payload = payload.split(",", 1)[1]
        try:
            raw_bytes = base64.b64decode(payload, validate=True)
        except Exception as exc:
            raise ValueError("Invalid base64 image payload") from exc
        arr = np.frombuffer(raw_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            raise ValueError("Could not decode image bytes from crop_base64")
        return img

    @staticmethod
    def _encode_jpeg_base64(crop: np.ndarray) -> str:
        """Encode a BGR crop into a data-URI JPEG base64 string."""
        ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            return ""
        b64 = base64.b64encode(buf.tobytes()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"

    def _read_live_frame(self, camera_id: str) -> np.ndarray:
        """Read the latest unannotated BGR frame from the target camera."""
        mgr = self.stream_manager
        if mgr is None and self.camera_pool is not None:
            mgr = self.camera_pool.get_stream(camera_id)
        if mgr is None:
            raise RoiNotFoundError(f"Camera '{camera_id}' not found")
        with mgr._lock:
            raw = mgr._latest_raw_frame
            frame = raw.copy() if raw is not None else None
        if frame is None or frame.size == 0:
            raise RoiUnavailableError(f"No video frame available for '{camera_id}' yet")
        return frame

    def _read_video_frame(self, video_filename: str, timestamp_sec: float | None) -> np.ndarray:
        """Seek and decode a BGR frame from a recorded video file."""
        safe_name = os.path.basename(video_filename.strip())
        if not safe_name:
            raise ValueError("Invalid video_filename")
        base_dir = Path(self.videos_dir).resolve()
        target = (base_dir / safe_name).resolve()
        if target.parent != base_dir or not target.is_file():
            raise RoiNotFoundError(f"Video '{safe_name}' not found")
        cap = cv2.VideoCapture(str(target))
        if not cap.isOpened():
            raise RoiUnavailableError(f"Could not open video '{safe_name}'")
        try:
            ts_ms = max(0.0, float(timestamp_sec or 0.0)) * 1000.0
            if ts_ms > 0:
                cap.set(cv2.CAP_PROP_POS_MSEC, ts_ms)
            ok, frame = cap.read()
            if not ok or frame is None or frame.size == 0:
                if ts_ms > 0:
                    raise RoiUnavailableError(
                        f"Could not decode frame from '{safe_name}' at {timestamp_sec}s"
                    )
                raise RoiUnavailableError(f"Could not decode frame from '{safe_name}'")
            return frame
        finally:
            cap.release()

    def resolve_roi_frame(
        self, camera_id: str | None = None, video_filename: str | None = None,
        timestamp_sec: float | None = None, crop_base64: str | None = None,
    ) -> tuple[np.ndarray, bool]:
        """Resolve source frame or direct crop from base64, video, or live camera."""
        if crop_base64 and crop_base64.strip():
            return self._decode_base64_image(crop_base64), True
        if video_filename and video_filename.strip():
            return self._read_video_frame(video_filename, timestamp_sec), False
        if camera_id and camera_id.strip():
            return self._read_live_frame(camera_id), False
        raise ValueError("Provide crop_base64, video_filename, or camera_id")

    @staticmethod
    def extract_roi_crop(
        frame: np.ndarray, bbox: list[int] | None, is_direct_crop: bool = False,
    ) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        """Extract a clamped BGR crop and [x, y, w, h] tuple from a frame."""
        fh, fw = frame.shape[:2]
        if is_direct_crop:
            return frame, (0, 0, fw, fh)
        if not bbox or len(bbox) != 4:
            raise ValueError("A 4-element [x, y, w, h] bbox is required")
        bx, by, bw, bh = [int(v) for v in bbox]
        if bw <= 0 or bh <= 0:
            raise ValueError("Bounding box width and height must be positive")
        crop, box = EntityTaggerService._extract_bounded_crop(frame, [bx, by, bw, bh])
        if crop.size == 0:
            raise ValueError("Extracted ROI crop is empty")
        return crop, box

    @staticmethod
    def classify_roi_crop(crop: np.ndarray, detector: Any = None) -> dict[str, Any]:
        """Classify an ROI crop via active detector or aspect/color heuristic fallback."""
        if detector is not None and hasattr(detector, "detect"):
            try:
                detections = detector.detect(crop) or []
                if detections:
                    best = max(detections, key=lambda d: float(getattr(d, "confidence", 0.0)))
                    return {"label": str(getattr(best, "label", "object") or "object"),
                            "confidence": round(float(getattr(best, "confidence", 0.5)), 4), "method": "detector"}
            except Exception as exc:
                logger.warning("Detector ROI classification fallback triggered: %s", exc)
        ch, cw = crop.shape[:2]
        aspect = ch / max(1.0, float(cw))
        if aspect >= 1.25:
            return {"label": "person", "confidence": 0.62, "method": "heuristic"}
        if aspect <= 0.72 and cw >= 48:
            return {"label": "vehicle", "confidence": 0.55, "method": "heuristic"}
        return {"label": "object", "confidence": 0.5, "method": "heuristic"}

    def match_crop_to_gallery(
        self, crop: np.ndarray, top_k: int = 3, reid_extractor: Any = None,
    ) -> dict[str, Any]:
        """Compute crop embedding and return top-K cosine similarity gallery matches."""
        if reid_extractor is None:
            _, reid_extractor = _resolve_roi_models(self.stream_manager, self.camera_pool)
        emb = EntityTaggerService._compute_deterministic_embedding(crop, reid_extractor)
        mat, ids, names, categories = self.db.get_gallery_embeddings(expected_dim=int(emb.shape[0]))
        if mat.size == 0 or not ids:
            return {"embedding_dim": int(emb.shape[0]), "candidates": [], "best_match": None}
        best_by_entity: dict[int, dict[str, Any]] = {}
        for idx, sim in enumerate(batch_cosine_similarity(mat, emb)):
            eid, score_val = int(ids[idx]), round(float(sim), 4)
            prev = best_by_entity.get(eid)
            if prev is None or score_val > prev["similarity"]:
                best_by_entity[eid] = {"entity_id": eid, "name": names[idx], "category": categories[idx], "similarity": score_val}
        ranked = sorted(best_by_entity.values(), key=lambda c: c["similarity"], reverse=True)
        candidates = ranked[: max(1, int(top_k))]
        return {"embedding_dim": int(emb.shape[0]), "candidates": candidates, "best_match": candidates[0] if candidates else None}

    def recognize_roi(
        self, camera_id: str | None = None, video_filename: str | None = None,
        timestamp_sec: float | None = None, bbox: list[int] | None = None,
        crop_base64: str | None = None, top_k: int = 3,
    ) -> dict[str, Any]:
        """Run end-to-end on-demand ROI crop extraction, classification, and Re-ID."""
        frame, is_direct = self.resolve_roi_frame(camera_id, video_filename, timestamp_sec, crop_base64)
        crop, box = self.extract_roi_crop(frame, bbox, is_direct_crop=is_direct)
        detector, reid_ext = _resolve_roi_models(self.stream_manager, self.camera_pool)
        classification = self.classify_roi_crop(crop, detector=detector)
        matching = self.match_crop_to_gallery(crop, top_k=top_k, reid_extractor=reid_ext)
        return {
            "bbox": list(box), "classification": classification, "candidates": matching["candidates"],
            "best_match": matching["best_match"], "embedding_dim": matching["embedding_dim"],
            "crop_base64": self._encode_jpeg_base64(crop),
        }

    def _persist_roi_tag(
        self,
        entity_name: str, category: str, entity_id: int | None, notes: str,
        crop: np.ndarray, emb: np.ndarray, box: tuple[int, int, int, int],
        source: str, track_id: int | None, *, video_filename: str = "",
        media_offset_sec: float = 0.0, camera_id: str | None = None,
    ) -> dict[str, Any]:
        """Upsert entity, write crop thumbnail, and record locked anchor, sighting, and side effects."""
        target = self.db.get_entity(entity_id) if entity_id is not None else self.db.get_entity_by_name(entity_name)
        if target is not None:
            resolved_id, resolved_name = int(target["id"]), target["name"]
            if category:
                self.db.update_entity(resolved_id, category=category, notes=notes)
        else:
            resolved_id = int(self.db.add_entity(name=entity_name, category=category, notes=notes))
            resolved_name = entity_name
        slug = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in resolved_name.lower())
        crop_path = os.path.join(
            self.crops_dir, f"{slug}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}.jpg"
        ).replace("\\", "/")
        os.makedirs(os.path.dirname(os.path.abspath(crop_path)), exist_ok=True)
        cv2.imwrite(os.path.abspath(crop_path), crop)
        sig_id = int(self.db.add_signature(entity_id=resolved_id, embedding=emb, crop_path=crop_path, is_anchor=1, locked=1))
        bx, by, bw, bh = box
        sighting_id = int(self.db.record_sighting(
            entity_id=resolved_id, track_id=track_id or 0, source=source,
            zone_id="manual_roi", bbox=f"{bx},{by},{bw},{bh}", confidence=1.0,
            snapshot_path=crop_path, video_filename=video_filename, media_offset_sec=media_offset_sec,
        ))
        _record_roi_side_effects(
            self, entity_id=resolved_id, entity_name=resolved_name, category=category, emb=emb,
            crop_path=crop_path, notes=notes, source=source, track_id=track_id,
            camera_id=camera_id, video_filename=video_filename, media_offset_sec=media_offset_sec,
        )
        from dashboard.services.review_sync_service import sync_studio_feedback_to_review_queue
        review_sync = sync_studio_feedback_to_review_queue(
            self.db, action="commit", camera_id=camera_id, video_filename=video_filename,
            media_offset_sec=media_offset_sec, track_id=track_id, bbox=list(box),
        )
        return {"entity_id": resolved_id, "entity_name": resolved_name, "category": category, "signature_id": sig_id, "sighting_id": sighting_id, "crop_path": crop_path, "bbox": list(box), "review_sync": review_sync}

    def commit_roi_tag(
        self, entity_name: str, category: str = "person", entity_id: int | None = None,
        camera_id: str | None = None, video_filename: str | None = None,
        timestamp_sec: float | None = None, bbox: list[int] | None = None,
        crop_base64: str | None = None, notes: str = "", track_id: int | None = None,
    ) -> dict[str, Any]:
        """Persist ROI crop, signature, entity record, and sighting into TrackerDB."""
        frame, is_direct = self.resolve_roi_frame(camera_id, video_filename, timestamp_sec, crop_base64)
        crop, box = self.extract_roi_crop(frame, bbox, is_direct_crop=is_direct)
        _, reid_ext = _resolve_roi_models(self.stream_manager, self.camera_pool)
        emb = EntityTaggerService._compute_deterministic_embedding(crop, reid_ext)
        source = video_filename or camera_id or "manual_roi"
        return self._persist_roi_tag(
            entity_name, category, entity_id, notes, crop, emb, box, source, track_id,
            video_filename=str(video_filename or "").strip(),
            media_offset_sec=float(timestamp_sec or 0.0),
            camera_id=camera_id,
        )
