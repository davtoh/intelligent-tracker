"""Persistent gallery matching helpers with class/category compatibility guards."""

from typing import Any, Optional
import numpy as np

from intelligent_tracker.matching.types import EntityIdentifiedEvent
from intelligent_tracker.matching._gallery_signals import (
    apply_topology_priors,
    apply_track_confidence_signals,
    process_confirmed_identification,
)
from intelligent_tracker.reid import batch_cosine_similarity
from intelligent_tracker.tracker import Track

_NON_PERSON_CLASSES = frozenset({
    "backpack", "bag", "handbag", "suitcase", "luggage", "package", "box",
    "chair", "couch", "sofa", "bed", "dining table", "table", "desk",
    "tv", "monitor", "laptop", "keyboard", "mouse", "cell phone", "phone",
    "bottle", "cup", "bowl", "book", "clock", "vase", "umbrella",
    "dog", "cat", "bird", "horse", "sheep", "cow", "pet", "animal",
    "car", "truck", "bus", "motorcycle", "bicycle", "vehicle",
})

_SYNONYM_GROUPS = (
    frozenset({"backpack", "handbag", "suitcase", "bag", "luggage"}),
    frozenset({"car", "truck", "bus", "motorcycle", "bicycle", "vehicle"}),
    frozenset({"couch", "sofa"}),
    frozenset({"dining table", "table", "desk"}),
    frozenset({"cell phone", "phone"}),
    frozenset({"dog", "cat", "pet", "animal"}),
)


def is_gallery_category_compatible(track_label: Optional[str], gallery_category: Optional[str]) -> bool:
    """Return True when a track's detector label is compatible with a gallery entity category."""
    t_lbl = str(track_label or "").strip().lower()
    g_cat = str(gallery_category or "").strip().lower()
    if not t_lbl or not g_cat or t_lbl == "object" or g_cat == "object":
        return True
    if t_lbl == g_cat:
        return True
    if t_lbl in {"person", "mock_person", "human", "pedestrian"}:
        return g_cat not in _NON_PERSON_CLASSES
    for group in _SYNONYM_GROUPS:
        if t_lbl in group and g_cat in group:
            return True
    return False


def _notify_active_learning(
    matcher: Any, track: Track, frame: np.ndarray, best_idx: int, best_score: float, source: str, now: float
) -> None:
    """Send low-confidence compatible candidate to active learning triage."""
    if matcher.active_learning is None or best_score < 0.0:
        return
    cand_eid = matcher.gallery_entity_ids[best_idx] if best_idx < len(matcher.gallery_entity_ids) else None
    cand_name = matcher.gallery_names[best_idx] if best_idx < len(matcher.gallery_names) else ""
    cand_cat = matcher.gallery_categories[best_idx] if best_idx < len(matcher.gallery_categories) else ""
    matcher.active_learning.consider_candidate(
        track=track, frame=frame, similarity=best_score,
        suggested_entity_id=cand_eid, suggested_name=cand_name,
        suggested_category=cand_cat, camera_id=source, timestamp=now,
        video_filename=str(getattr(matcher, "video_filename", "") or "").strip(),
        media_offset_sec=float(getattr(matcher, "current_media_offset_sec", 0.0) or 0.0),
        run_id=str(getattr(matcher, "run_id", "") or "").strip(),
    )


def _apply_negative_suppression(
    matcher: Any, query_vec: np.ndarray, similarities: np.ndarray
) -> tuple[np.ndarray, bool]:
    """Suppress candidates matching negative exemplars or global false-positive clutter."""
    neg_mat = getattr(matcher, "negative_matrix", None)
    if neg_mat is None or neg_mat.size == 0:
        return similarities, False
    neg_sims = batch_cosine_similarity(neg_mat, query_vec)
    neg_ids = getattr(matcher, "negative_entity_ids", [])
    global_thresh = float(getattr(matcher, "global_negative_threshold", 0.82))
    entity_thresh = float(getattr(matcher, "negative_suppression_threshold", 0.78))
    suppressed_eids: set[int] = set()
    for idx, sim in enumerate(neg_sims):
        eid = neg_ids[idx] if idx < len(neg_ids) else None
        if eid is None and float(sim) >= global_thresh:
            return similarities, True
        if eid is not None and float(sim) >= entity_thresh:
            suppressed_eids.add(eid)
    if suppressed_eids:
        keep_mask = np.array([eid not in suppressed_eids for eid in matcher.gallery_entity_ids], dtype=bool)
        similarities = np.where(keep_mask, similarities, -1.0)
    return similarities, False


def _confirm_gallery_match(
    matcher: Any, track: Track, query_vec: np.ndarray, similarities: np.ndarray,
    raw_similarities: Optional[np.ndarray], matched_priors: dict,
    best_idx: int, best_score: float, source: str, now: float, zone_id: str,
    frame: Optional[np.ndarray] = None,
) -> Optional[EntityIdentifiedEvent]:
    """Apply confidence signals, consume topology prior, and emit identification event."""
    apply_track_confidence_signals(
        track, extractor=matcher.extractor, query_vec=query_vec, gallery_matrix=matcher.gallery_matrix,
        gallery_entity_ids=matcher.gallery_entity_ids, similarities=similarities,
        raw_similarities=raw_similarities, matched_priors=matched_priors, best_idx=best_idx,
    )
    if matcher.topology is not None and best_idx in matched_priors:
        matcher.topology.consume_prior(matched_priors[best_idx].prior_id)
    return process_confirmed_identification(
        matcher, track, best_idx, best_score, query_vec, source, now, zone_id, frame=frame,
    )


def match_persistent_gallery(
    matcher: Any, track: Track, query_vec: np.ndarray, frame: np.ndarray,
    source: str, now: float, zone_id: str,
) -> Optional[EntityIdentifiedEvent]:
    """Query persistent database gallery with class compatibility, priors, and active learning."""
    similarities = batch_cosine_similarity(matcher.gallery_matrix, query_vec)
    if similarities.size == 0:
        return None
    t_label = getattr(track, "label", "object")
    compatible_mask = np.array([is_gallery_category_compatible(t_label, c) for c in matcher.gallery_categories], dtype=bool)
    allowed_cats = getattr(matcher, "tracked_categories", None)
    if allowed_cats:
        allowed_set = {str(c).strip().lower() for c in allowed_cats if str(c).strip()}
        if allowed_set:
            cat_mask = np.array([str(c or "").strip().lower() in allowed_set for c in matcher.gallery_categories], dtype=bool)
            compatible_mask = compatible_mask & cat_mask
    if not np.any(compatible_mask):
        return None
    similarities = np.where(compatible_mask, similarities, -1.0)
    matched_priors, raw_similarities = {}, None
    if matcher.topology is not None:
        raw_similarities = similarities.copy()
        matched_priors = apply_topology_priors(
            matcher.topology, matcher.gallery_entity_ids, matcher.gallery_names, similarities, source, zone_id, now,
        )
        similarities = np.where(compatible_mask, similarities, -1.0)
    similarities, globally_suppressed = _apply_negative_suppression(matcher, query_vec, similarities)
    if globally_suppressed:
        return None
    best_idx = int(np.argmax(similarities))
    best_score = float(similarities[best_idx])
    if best_score < 0.0:
        return None
    if best_score < matcher.reid_threshold:
        _notify_active_learning(matcher, track, frame, best_idx, best_score, source, now)
        return None
    return _confirm_gallery_match(
        matcher, track, query_vec, similarities, raw_similarities,
        matched_priors, best_idx, best_score, source, now, zone_id, frame=frame,
    )
