"""Dataclasses and event representations for tracking identities and sessions."""

from collections import deque
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple, Any
import numpy as np


@dataclass
class EntityIdentifiedEvent:
    """Event emitted when a tracked entity is recognized in the gallery."""

    entity_id: int
    name: str
    category: str
    track_id: int
    similarity: float
    source: str
    timestamp: float
    zone_id: str = ""
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["similarity"] = round(float(self.similarity), 3)
        return d


@dataclass
class SessionEntity:
    """Represents an automatically tracked canonical identity in the current video session.

    Maintains temporal feature buffer and exit boundary telemetry for dead-reckoning re-linking.
    """

    session_id: int
    label: str  # e.g., "Person #1"
    category: str  # e.g., "person"
    feature_history: deque  # deque of 1D L2-normalized feature vectors
    first_seen: float
    last_seen: float
    last_centroid: Tuple[float, float]
    exit_point: Optional[Tuple[float, float]] = None
    exit_time: Optional[float] = None
    assigned_track_ids: Optional[List[int]] = None

    def __post_init__(self):
        if self.assigned_track_ids is None:
            self.assigned_track_ids = []

    def get_embedding(self) -> Optional[np.ndarray]:
        """Compute temporal smoothed L2-normalized embedding."""
        if not self.feature_history:
            return None
        arr = np.array(self.feature_history, dtype=np.float32)
        mean_vec = np.mean(arr, axis=0)
        norm = np.linalg.norm(mean_vec)
        if norm > 1e-7:
            mean_vec = mean_vec / norm
        return mean_vec

