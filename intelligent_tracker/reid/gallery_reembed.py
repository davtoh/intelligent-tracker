"""Idempotent startup re-embedding for dimension-mismatched gallery signatures."""

import logging
import os
from typing import Any

import cv2

from intelligent_tracker.reid.factory import ReIDExtractorFactory
from intelligent_tracker.reid.profile import ReidProfile, resolve_reid_profile

logger = logging.getLogger(__name__)


def _resolve_crop_candidate(db: Any, sig: dict[str, Any]) -> str | None:
    """Resolve an existing image path from signature crop_path or entity thumbnail."""
    crop_path = str(sig.get("crop_path") or "").strip()
    if crop_path and os.path.exists(crop_path):
        return crop_path
    entity_id = sig.get("entity_id")
    if entity_id is not None and hasattr(db, "get_entity"):
        entity = db.get_entity(int(entity_id))
        if isinstance(entity, dict):
            for key in ("thumbnail_path", "avatar_path", "crop_path"):
                cand = str(entity.get(key) or "").strip()
                if cand and os.path.exists(cand):
                    return cand
    return None


def _reembed_single_signature(
    db: Any, sig: dict[str, Any], target_dim: int, active_extractor: Any, profile: ReidProfile,
) -> tuple[bool, Any]:
    """Re-embed one mismatched signature; returns (succeeded, active_extractor)."""
    img_path = _resolve_crop_candidate(db, sig)
    if not img_path:
        return False, active_extractor
    img = cv2.imread(img_path)
    if img is None or img.size == 0:
        return False, active_extractor
    try:
        if active_extractor is None:
            active_extractor = ReIDExtractorFactory.create(profile.model_name or "dual")
        new_emb = active_extractor.extract(img)
        new_dim = int(new_emb.shape[0]) if hasattr(new_emb, "shape") and len(new_emb.shape) > 0 else 0
        if new_dim != target_dim:
            return False, active_extractor
        return bool(db.update_signature_embedding(int(sig["id"]), new_emb)), active_extractor
    except Exception as exc:
        logger.warning("Failed to re-embed signature id=%s: %s", sig.get("id"), exc)
        return False, active_extractor


def reembed_mismatched_signatures(
    db: Any,
    extractor: Any = None,
    expected_dim: int | None = None,
) -> dict[str, Any]:
    """Re-embed gallery signatures whose vector dim mismatches canonical DualModel."""
    profile = resolve_reid_profile()
    target_dim = int(expected_dim if expected_dim is not None else (profile.expected_dim or 608))
    sigs = db.get_signatures() if db is not None and hasattr(db, "get_signatures") else []
    checked, mismatched, reembedded, failed = len(sigs), 0, 0, 0
    active_extractor = extractor
    for sig in sigs:
        emb = sig.get("embedding")
        dim = int(emb.shape[0]) if hasattr(emb, "shape") and len(emb.shape) > 0 else 0
        if dim == target_dim:
            logger.debug("Gallery re-embed: signature id=%s already at target_dim=%d", sig.get("id"), target_dim)
            continue
        mismatched += 1
        ok, active_extractor = _reembed_single_signature(db, sig, target_dim, active_extractor, profile)
        reembedded += int(ok)
        failed += int(not ok)
    if mismatched:
        logger.warning(
            "Gallery re-embed audit: checked=%d mismatched=%d reembedded=%d failed=%d expected_dim=%d",
            checked, mismatched, reembedded, failed, target_dim,
        )
    return {"checked": checked, "mismatched": mismatched, "reembedded": reembedded, "failed": failed, "expected_dim": target_dim}
