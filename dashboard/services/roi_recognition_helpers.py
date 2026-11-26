"""Helper functions for on-demand ROI recognition and tag commitment."""

import logging
from typing import Any

from dashboard.services.entity_tagger import EntityTaggerService, _to_avatar_url
from intelligent_tracker.detectors import DetectorFactory
from intelligent_tracker.memory.confidence import ConfidenceEngine
from intelligent_tracker.reid.factory import ReIDExtractorFactory
from intelligent_tracker.reid.profile import resolve_reid_profile

logger = logging.getLogger(__name__)


def resolve_roi_services(
    db: Any, stream_manager: Any, camera_pool: Any, confidence_engine: Any, fts_index: Any,
) -> tuple[Any, Any]:
    """Resolve ConfidenceEngine and EventFTSIndex from explicit args, stream, or pool."""
    ce = confidence_engine or getattr(stream_manager, "confidence_engine", None) or getattr(camera_pool, "confidence_engine", None)
    if ce is None and db is not None:
        ce = ConfidenceEngine(db=db)
    fts = fts_index or getattr(stream_manager, "event_fts_index", None) or getattr(camera_pool, "event_fts_index", None)
    return ce, fts


def record_roi_side_effects(
    svc: Any, *, entity_id: int, entity_name: str, category: str, emb: Any,
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
            avatar_url=_to_avatar_url(crop_path),
        )


def resolve_roi_models(stream_manager: Any, camera_pool: Any) -> tuple[Any, Any]:
    """Resolve configured detector and canonical DualModel Re-ID extractor."""
    det = getattr(stream_manager, "detector", None) if stream_manager else None
    reid = (
        getattr(stream_manager, "reid_extractor", None)
        or getattr(getattr(stream_manager, "gallery_matcher", None), "extractor", None)
    ) if stream_manager else None
    if (det is None or reid is None) and camera_pool is not None:
        from dashboard.services.camera_pool_queries import snapshot_pool_streams

        for mgr in snapshot_pool_streams(camera_pool).values():
            det = det or getattr(mgr, "detector", None)
            reid = reid or getattr(mgr, "reid_extractor", None) or getattr(getattr(mgr, "gallery_matcher", None), "extractor", None)
            if det is not None and reid is not None:
                break
    if det is None:
        try:
            det = DetectorFactory.create("yolov8")
        except Exception:
            det = None
    if reid is None:
        profile = resolve_reid_profile(getattr(stream_manager, "cfg", None))
        try:
            reid = ReIDExtractorFactory.create(profile.model_name or "dual")
        except Exception as exc:
            logger.warning("ROI canonical Re-ID instantiation failed: %s", exc)
            reid = None
    return det, reid
