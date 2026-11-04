"""Multi-Object Tracking (MOT) Package.

Re-exports 100% of public tracking primitives, Kalman filters, centroid association,
occlusion reasoning, and tracker factories to preserve backward compatibility.
"""

from intelligent_tracker.tracker.centroid import CentroidTracker
from intelligent_tracker.tracker.factory import TrackerFactory
from intelligent_tracker.tracker.occlusion import check_track_occlusions
from intelligent_tracker.tracker.sort import KalmanBoxTracker, SortTracker
from intelligent_tracker.tracker.track import Track
from intelligent_tracker.tracker.utils import (
    _HAS_SCIPY,
    compute_iou,
    compute_iou_matrix,
    greedy_assignment,
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

