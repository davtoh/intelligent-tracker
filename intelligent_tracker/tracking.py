"""Forwarding alias for intelligent_tracker.tracker."""

from intelligent_tracker.tracker import (
    Track,
    CentroidTracker,
    KalmanBoxTracker,
    SortTracker,
    TrackerFactory,
    compute_iou,
    compute_iou_matrix,
    greedy_assignment,
    check_track_occlusions,
    _HAS_SCIPY,
)

__all__ = [
    "Track",
    "CentroidTracker",
    "KalmanBoxTracker",
    "SortTracker",
    "TrackerFactory",
    "compute_iou",
    "compute_iou_matrix",
    "greedy_assignment",
    "check_track_occlusions",
    "_HAS_SCIPY",
]

