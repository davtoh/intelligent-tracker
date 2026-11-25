"""Service for inspecting Re-ID gallery dimension health and mismatch counts."""

from typing import Any

from intelligent_tracker.reid.profile import resolve_reid_profile


def inspect_gallery_health(db: Any, expected_dim: int | None = None) -> dict[str, Any]:
    """Return gallery embedding dimension distribution and mismatch metrics."""
    profile = resolve_reid_profile()
    target_dim = int(expected_dim if expected_dim is not None else (profile.expected_dim or 608))
    sigs = db.get_signatures() if db is not None and hasattr(db, "get_signatures") else []
    dim_histogram: dict[str, int] = {}
    matching = 0
    mismatched = 0
    for sig in sigs:
        emb = sig.get("embedding")
        dim = int(emb.shape[0]) if hasattr(emb, "shape") and len(emb.shape) > 0 else 0
        key = str(dim)
        dim_histogram[key] = dim_histogram.get(key, 0) + 1
        if dim == target_dim:
            matching += 1
        else:
            mismatched += 1
    skipped_last = int(getattr(db, "_last_gallery_mismatch_count", 0) or 0) if db is not None else 0
    return {
        "canonical_model": profile.model_name or "dual",
        "expected_dim": target_dim,
        "total_signatures": len(sigs),
        "matching_signatures": matching,
        "mismatched_signatures": mismatched,
        "last_skipped_count": skipped_last,
        "dim_histogram": dim_histogram,
        "healthy": mismatched == 0,
    }
