"""Canonical Re-ID profile SSOT for Intelligent Tracker."""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CANONICAL_REID_MODEL = "dual"
CANONICAL_REID_DIM = 2560


def resolve_canonical_reid_dim(extractor: Any = None) -> int:
    """Return canonical DualModel embedding dimension, dynamically verified from extractor if available."""
    dim = getattr(extractor, "embedding_dim", None) if extractor is not None else None
    if isinstance(dim, int) and dim > 0:
        return dim
    return CANONICAL_REID_DIM


def _normalize_reid_name(raw_name: Any) -> str | None:
    """Normalize Re-ID model name, returning None when unset or empty."""
    if raw_name is None:
        return None
    text = str(raw_name).strip().lower()
    return text or None


def _parse_tracked_categories(raw: Any) -> list[str] | None:
    """Normalize optional tracked_categories list from config."""
    if raw is None:
        return None
    if isinstance(raw, str):
        items = [part.strip().lower() for part in raw.split(",") if part.strip()]
        return items or None
    if isinstance(raw, (list, tuple, set)):
        items = [str(item).strip().lower() for item in raw if str(item).strip()]
        return items or None
    return None


@dataclass(frozen=True)
class ReidProfile:
    """Resolved canonical Re-ID profile shared across live, batch, and ROI paths."""

    model_name: str | None = CANONICAL_REID_MODEL
    expected_dim: int | None = CANONICAL_REID_DIM
    threshold: float = 0.65
    tracked_categories: list[str] | None = None
    advisory_model: str | None = None
    is_canonical: bool = True


def resolve_reid_profile(
    cfg: dict[str, Any] | None = None,
    *,
    strict_canonical: bool = True,
    extractor: Any = None,
) -> ReidProfile:
    """Resolve canonical DualModel Re-ID profile; YAML reid.model is advisory."""
    data: dict[str, Any] = cfg if isinstance(cfg, dict) else {}
    raw_reid = data.get("reid")
    reid_cfg: dict[str, Any] = raw_reid if isinstance(raw_reid, dict) else {}
    advisory = _normalize_reid_name(reid_cfg.get("model"))
    threshold = float(reid_cfg.get("threshold", 0.65))
    raw_cats = reid_cfg.get("tracked_categories")
    tracked = _parse_tracked_categories(raw_cats if raw_cats is not None else data.get("tracked_categories"))

    if advisory == "none":
        return ReidProfile(None, None, threshold, tracked, "none", False)

    if advisory is not None and advisory not in ("dual", "dual_model"):
        logger.warning(
            "Advisory config reid.model=%r does not match canonical DualModel (%r); "
            "enforcing canonical %r profile.",
            advisory, CANONICAL_REID_MODEL, CANONICAL_REID_MODEL,
        )
        if not strict_canonical:
            return ReidProfile(advisory, None, threshold, tracked, advisory, False)

    expected_dim = resolve_canonical_reid_dim(extractor)
    return ReidProfile(CANONICAL_REID_MODEL, expected_dim, threshold, tracked, advisory, True)
