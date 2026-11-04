"""Track occlusion reasoning and cluttered track state management.

Evaluates pairwise track intersections to detect occlusion and clutter (Milestone 9).
When IoU > iou_threshold (0.3), marks intersecting tracks as 'is_cluttered = True'
to freeze Re-ID identity updates and prevent identity swapping.
"""

import math
import time
from typing import Any, Dict, List, Optional, Tuple

from intelligent_tracker.tracker.utils import compute_iou


def _evaluate_track_separation(
    trk: Any,
    partner: Any,
    separation_iou: float,
) -> bool:
    """Check if previously cluttered track has achieved safe physical separation."""
    iou = compute_iou(trk.bbox, partner.bbox)
    dx = trk.centroid[0] - partner.centroid[0]
    dy = trk.centroid[1] - partner.centroid[1]
    dist = math.hypot(dx, dy)
    min_sep = max(trk.bbox[2], partner.bbox[2], trk.bbox[3], partner.bbox[3]) * 0.4
    return bool(iou <= separation_iou and dist > min_sep)


def _find_cluttered_pairs(
    tids: List[int],
    tracks: Dict[int, Any],
    iou_threshold: float,
) -> Tuple[Dict[int, int], List[Tuple[int, int]]]:
    """Identify overlapping track pairs exceeding the IoU threshold."""
    newly_cluttered: Dict[int, int] = {}
    cluttered_pairs: List[Tuple[int, int]] = []
    n = len(tids)

    for i in range(n):
        tid1 = tids[i]
        trk1 = tracks[tid1]
        for j in range(i + 1, n):
            tid2 = tids[j]
            trk2 = tracks[tid2]
            if compute_iou(trk1.bbox, trk2.bbox) > iou_threshold:
                newly_cluttered[tid1] = tid2
                newly_cluttered[tid2] = tid1
                cluttered_pairs.append((tid1, tid2))

    return newly_cluttered, cluttered_pairs


def check_track_occlusions(
    tracks: Dict[int, Any],
    iou_threshold: float = 0.3,
    separation_iou: float = 0.1,
    timestamp: Optional[float] = None,
) -> List[Tuple[int, int]]:
    """Evaluate pairwise track intersections to detect occlusion and clutter (Milestone 9).

    :param tracks: Dictionary of active Track objects.
    :param iou_threshold: IoU overlap threshold to trigger cluttered state.
    :param separation_iou: IoU threshold below which clutter is cleared if distance is safe.
    :param timestamp: Frame timestamp.
    :return: List of overlapping track ID tuples [(t1, t2), ...].
    """
    now = timestamp if timestamp is not None else time.time()
    tids = [
        tid for tid, trk in tracks.items()
        if getattr(trk, "hits", 0) >= 1 and getattr(trk, "missed_frames", 0) == 0
    ]
    newly_cluttered, cluttered_pairs = _find_cluttered_pairs(tids, tracks, iou_threshold)

    for tid in tids:
        trk = tracks[tid]
        if tid in newly_cluttered:
            if not getattr(trk, "is_cluttered", False):
                trk.is_cluttered = True
                trk.clutter_start_time = now
            trk.clutter_partner_id = newly_cluttered[tid]
        elif getattr(trk, "is_cluttered", False):
            partner_id = getattr(trk, "clutter_partner_id", None)
            if partner_id not in tracks or partner_id not in tids:
                trk.is_cluttered = False
                trk.clutter_partner_id = None
            elif _evaluate_track_separation(trk, tracks[partner_id], separation_iou):
                trk.is_cluttered = False
                trk.clutter_partner_id = None

    return cluttered_pairs


__all__ = ["check_track_occlusions"]
