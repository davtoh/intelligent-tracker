"""Persistent gallery matching helpers with class/category compatibility guards."""

from typing import Any, Dict, List, Optional
import logging
import numpy as np

from intelligent_tracker.matching.types import EntityIdentifiedEvent
from intelligent_tracker.matching._gallery_signals import (
    apply_topology_priors,
    apply_track_confidence_signals,
    process_confirmed_identification,
)
from intelligent_tracker.reid import batch_cosine_similarity
from intelligent_tracker.tracker import Track

logger = logging.getLogger(__name__)


def _crop_path_to_avatar_url(crop_path: Optional[str]) -> Optional[str]:
    """Normalize a stored signature crop path into an HTTP-servable ``/crops/<file>`` URL."""
    raw = str(crop_path or "").strip()
    if not raw:
        return None
    if raw.startswith(("/", "http://", "https://", "data:")):
        return raw
    import os
    return f"/crops/{os.path.basename(raw.replace(chr(92), '/'))}"


def resolve_entity_avatars(db: Any) -> Dict[int, str]:
    """Build ``{entity_id: avatar_url}`` lookup preferring anchor signatures with crops."""
    if db is None or not hasattr(db, "get_signatures"):
        return {}
    try:
        sigs = db.get_signatures()
    except Exception:
        return {}
    avatars: Dict[int, str] = {}
    for sig in sigs or ():
        eid = sig.get("entity_id")
        url = _crop_path_to_avatar_url(sig.get("crop_path"))
        if eid is None or not url:
            continue
        if int(eid) not in avatars or int(sig.get("is_anchor") or 0) == 1:
            avatars[int(eid)] = url
    return avatars


def log_skipped_signature_dims(matcher: Any, expected_dim: Optional[int], ids: List[int]) -> None:
    """Log active signatures skipped during gallery load due to embedding dimension mismatch."""
    if expected_dim is None or len(ids) > 0 or matcher.db is None:
        return
    try:
        all_sigs = matcher.db.get_signatures()
        if all_sigs:
            other_dims = {(s["embedding"].shape[0] if hasattr(s.get("embedding"), "shape") else 0) for s in all_sigs}
            logger.info(
                "GalleryMatcher: %d active signatures skipped (dim mismatch: %s vs %s dim=%d).",
                len(all_sigs), ", ".join(str(d) for d in sorted(other_dims) if d > 0),
                matcher.extractor.__class__.__name__, expected_dim,
            )
    except Exception:
        pass

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
    matcher: Any, track: Track, frame: np.ndarray, best_idx: Optional[int], best_score: float,
    source: str, now: float, track_dwell_sec: Optional[float] = None,
) -> None:
    """Send borderline or recurring-unknown candidate to active learning triage."""
    if matcher.active_learning is None:
        return
    score = max(0.0, float(best_score))
    min_conf = float(getattr(matcher.active_learning, "min_confidence", 0.45))
    valid_idx = best_idx is not None and 0 <= best_idx < len(matcher.gallery_entity_ids)
    idx_val = best_idx if valid_idx and best_idx is not None else -1
    cand_eid = matcher.gallery_entity_ids[idx_val] if (idx_val >= 0 and score >= min_conf) else None
    cand_name = matcher.gallery_names[idx_val] if (idx_val >= 0 and score >= min_conf) else ""
    cand_cat = (
        matcher.gallery_categories[idx_val]
        if (idx_val >= 0 and idx_val < len(matcher.gallery_categories))
        else str(getattr(track, "label", "") or "")
    )
    dwell = float(track_dwell_sec) if track_dwell_sec is not None else float(getattr(track, "dwell_time", 0.0) or 0.0)
    matcher.active_learning.consider_candidate(
        track=track, frame=frame, similarity=score,
        suggested_entity_id=cand_eid, suggested_name=cand_name,
        suggested_category=cand_cat, camera_id=source, timestamp=now,
        video_filename=str(getattr(matcher, "video_filename", "") or "").strip(),
        media_offset_sec=float(getattr(matcher, "current_media_offset_sec", 0.0) or 0.0),
        run_id=str(getattr(matcher, "run_id", "") or "").strip(),
        track_dwell_sec=dwell,
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


def _reinforce_locked_track(
    matcher: Any, track: Track, locked: Any, source: str, now: float, zone_id: str,
) -> None:
    """Re-apply hysteresis lock onto ``track`` and reinforce ``WorldEntity`` binding."""
    matcher.hysteresis.apply_to_track(track, locked)
    if matcher.world_bridge is not None:
        matcher.world_bridge.sync_track_identification(
            source, track, locked.entity_id, name=locked.entity_name,
            category=locked.entity_category, confidence=locked.similarity,
            zone_id=zone_id, timestamp=now,
        )


def _unbind_contradicted_track(matcher: Any, track: Track, source: str) -> None:
    """Clear track identity, feature-buffer cache, and WorldEntity camera link after M contradictions."""
    prev_eid = getattr(track, "entity_id", None)
    matcher.hysteresis.clear_track(track.track_id, track)
    setattr(track, "_identity_unbound", True)
    matcher._identified_tracks.pop(track.track_id, None)
    if prev_eid is not None and matcher.world_bridge is not None:
        we = matcher.world_bridge.world_graph.get_node(f"entity:{int(prev_eid)}", node_type="entity")
        if we is not None and getattr(we, "camera_tracks", {}).get(source) == int(track.track_id):
            we.camera_tracks.pop(source, None)


def _observe_gallery_miss(matcher: Any, track: Track, source: str, now: float, zone_id: str) -> None:
    """Advance hysteresis on an incompatible, suppressed, or sub-threshold frame."""
    hyst = getattr(matcher, "hysteresis", None)
    if hyst is None:
        return
    locked, _ = hyst.observe(track.track_id, None, 0.0, now=now, threshold=matcher.reid_threshold)
    if locked is not None:
        _reinforce_locked_track(matcher, track, locked, source, now, zone_id)


def _score_compatible_gallery(
    matcher: Any, track: Track, query_vec: np.ndarray, source: str, zone_id: str, now: float,
) -> tuple[Optional[np.ndarray], Optional[np.ndarray], dict]:
    """Compute compatible, topology-boosted, negative-suppressed gallery similarities."""
    similarities = batch_cosine_similarity(matcher.gallery_matrix, query_vec)
    if similarities.size == 0:
        return None, None, {}
    t_label = getattr(track, "label", "object")
    compatible_mask = np.array([is_gallery_category_compatible(t_label, c) for c in matcher.gallery_categories], dtype=bool)
    allowed_cats = getattr(matcher, "tracked_categories", None)
    if allowed_cats:
        allowed_set = {str(c).strip().lower() for c in allowed_cats if str(c).strip()}
        if allowed_set:
            cat_mask = np.array([str(c or "").strip().lower() in allowed_set for c in matcher.gallery_categories], dtype=bool)
            compatible_mask = compatible_mask & cat_mask
    if not np.any(compatible_mask):
        return None, None, {}
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
        return None, None, {"_globally_suppressed": True}
    return similarities, raw_similarities, matched_priors


def _passes_hysteresis_gate(
    matcher: Any, track: Track, best_idx: int, best_score: float,
    source: str, now: float, zone_id: str,
) -> bool:
    """Return True when hysteresis confirms or reinforces ``best_idx``; else hold/unbind."""
    hyst = getattr(matcher, "hysteresis", None)
    if hyst is None:
        return True
    cand_eid = matcher.gallery_entity_ids[best_idx]
    avatar_url = (getattr(matcher, "entity_avatars", None) or {}).get(cand_eid)
    locked, status = hyst.observe(
        track.track_id, cand_eid, best_score,
        entity_name=matcher.gallery_names[best_idx],
        entity_category=matcher.gallery_categories[best_idx],
        avatar_url=avatar_url, now=now, threshold=matcher.reid_threshold,
    )
    if status == "pending":
        return False
    if status == "held" and locked is not None:
        _reinforce_locked_track(matcher, track, locked, source, now, zone_id)
        return False
    if status == "unbound":
        _unbind_contradicted_track(matcher, track, source)
        return False
    return True


def match_persistent_gallery(
    matcher: Any, track: Track, query_vec: np.ndarray, frame: np.ndarray,
    source: str, now: float, zone_id: str,
) -> Optional[EntityIdentifiedEvent]:
    """Query persistent database gallery with class compatibility, priors, hysteresis, and triage."""
    similarities, raw_similarities, matched_priors = _score_compatible_gallery(
        matcher, track, query_vec, source, zone_id, now,
    )
    hyst = getattr(matcher, "hysteresis", None)
    unlocked = hyst is None or hyst.get_locked(track.track_id) is None
    if similarities is None:
        if unlocked and not matched_priors.get("_globally_suppressed"):
            _notify_active_learning(matcher, track, frame, None, 0.0, source, now)
        _observe_gallery_miss(matcher, track, source, now, zone_id)
        return None
    best_idx = int(np.argmax(similarities))
    best_score = float(similarities[best_idx])
    if best_score < 0.0:
        if unlocked:
            _notify_active_learning(matcher, track, frame, None, 0.0, source, now)
        _observe_gallery_miss(matcher, track, source, now, zone_id)
        return None
    if best_score < matcher.reid_threshold:
        if unlocked:
            _notify_active_learning(matcher, track, frame, best_idx, best_score, source, now)
        _observe_gallery_miss(matcher, track, source, now, zone_id)
        return None
    if not _passes_hysteresis_gate(matcher, track, best_idx, best_score, source, now, zone_id):
        return None
    setattr(track, "_identity_unbound", False)
    return _confirm_gallery_match(
        matcher, track, query_vec, similarities, raw_similarities,
        matched_priors, best_idx, best_score, source, now, zone_id, frame=frame,
    )


def enforce_unique_entity_bindings(
    matcher: Any,
    tracks: Dict[int, Track],
    events: List[EntityIdentifiedEvent],
    source: str,
) -> List[EntityIdentifiedEvent]:
    """Ensure at most one active track per camera claims a given ``entity_id`` in a frame."""
    claims: Dict[int, List[tuple[tuple[float, int, float, int], int, Track]]] = {}
    hyst = getattr(matcher, "hysteresis", None)
    for tid, trk in tracks.items():
        eid = getattr(trk, "entity_id", None)
        if eid is None:
            continue
        locked = hyst.get_locked(tid) if hyst is not None else None
        score = float(getattr(trk, "reid_score", locked.similarity if locked is not None else 0.0) or 0.0)
        is_locked = 1 if locked is not None else 0
        locked_at = float(locked.locked_at) if locked is not None else float("inf")
        claims.setdefault(int(eid), []).append(((score, is_locked, -locked_at, -int(tid)), int(tid), trk))
    dropped: set[tuple[int, int]] = set()
    for eid, contenders in claims.items():
        if len(contenders) <= 1:
            continue
        contenders.sort(key=lambda item: item[0], reverse=True)
        for _, loser_tid, loser_trk in contenders[1:]:
            if hyst is not None:
                hyst.clear_track(loser_tid, loser_trk)
            else:
                loser_trk.entity_name, loser_trk.identity_label = None, None
                if hasattr(loser_trk, "entity_id"):
                    delattr(loser_trk, "entity_id")
            matcher._identified_tracks.pop(loser_tid, None)
            dropped.add((loser_tid, eid))
    if not dropped:
        return events
    return [ev for ev in events if (int(ev.track_id), int(getattr(ev, "entity_id", -1))) not in dropped]
