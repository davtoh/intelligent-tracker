"""2D Kinematic Kalman Box Tracker for SORT."""

import math
import time
from typing import Optional, Tuple
import numpy as np


class KalmanBoxTracker:
    """2D Kinematic Kalman Filter for bounding box tracking in pure NumPy.

    State: ``[x, y, s, r, vx, vy, vs]`` where:
    - ``(x, y)`` = center of bbox
    - ``s`` = area (w * h)
    - ``r`` = aspect ratio (w / h)
    """

    count = 0

    def __init__(self, bbox: Tuple[int, int, int, int], timestamp: Optional[float] = None):
        KalmanBoxTracker.count += 1
        self.id = KalmanBoxTracker.count

        # Initial state x: [7, 1]
        self.x = np.zeros((7, 1), dtype=np.float32)
        cx = bbox[0] + bbox[2] / 2.0
        cy = bbox[1] + bbox[3] / 2.0
        s = float(bbox[2] * bbox[3])
        r = float(bbox[2]) / float(bbox[3]) if bbox[3] > 0 else 1.0
        self.x[:4, 0] = [cx, cy, s, r]

        # State transition matrix F (constant velocity)
        self.F = np.eye(7, dtype=np.float32)
        for i in range(3):
            self.F[i, i + 4] = 1.0

        # Measurement matrix H
        self.H = np.zeros((4, 7), dtype=np.float32)
        self.H[:4, :4] = np.eye(4, dtype=np.float32)

        # Covariance matrices
        self.P = np.eye(7, dtype=np.float32) * 10.0
        self.P[4:, 4:] *= 100.0
        self.Q = np.eye(7, dtype=np.float32)
        self.Q[4:, 4:] *= 0.01
        self.R = np.eye(4, dtype=np.float32) * 1.0
        self.R[2:, 2:] *= 10.0

        self.time_since_update = 0
        self.history: list = []
        self.hits = 1
        self.hit_streak = 1
        self.age = 0
        self.last_seen: float = float(timestamp) if timestamp is not None else time.time()

    def predict(self) -> Tuple[int, int, int, int]:
        """Advance the state vector and return the predicted bounding box."""
        if (self.x[6, 0] + self.x[2, 0]) <= 0:
            self.x[6, 0] = 0.0
        self.x = np.dot(self.F, self.x)
        self.P = np.dot(np.dot(self.F, self.P), self.F.T) + self.Q
        self.age += 1
        if self.time_since_update > 0:
            self.hit_streak = 0
        self.time_since_update += 1
        return self.get_state()

    def update(self, bbox: Tuple[int, int, int, int], timestamp: Optional[float] = None) -> None:
        """Update the state vector with observed bounding box."""
        self.time_since_update = 0
        self.history = []
        self.hits += 1
        self.hit_streak += 1
        self.last_seen = float(timestamp) if timestamp is not None else time.time()

        cx = bbox[0] + bbox[2] / 2.0
        cy = bbox[1] + bbox[3] / 2.0
        s = float(bbox[2] * bbox[3])
        r = float(bbox[2]) / float(bbox[3]) if bbox[3] > 0 else 1.0
        z = np.array([[cx], [cy], [s], [r]], dtype=np.float32)

        y = z - np.dot(self.H, self.x)
        S = np.dot(np.dot(self.H, self.P), self.H.T) + self.R
        K = np.dot(np.dot(self.P, self.H.T), np.linalg.inv(S))
        self.x = self.x + np.dot(K, y)
        eye = np.eye(7, dtype=np.float32)
        self.P = np.dot(eye - np.dot(K, self.H), self.P)

    def get_state(self) -> Tuple[int, int, int, int]:
        """Convert current state back to (x, y, w, h) bounding box."""
        cx, cy = self.x[0, 0], self.x[1, 0]
        s = max(1.0, self.x[2, 0])
        r = max(0.01, self.x[3, 0])
        w = math.sqrt(s * r)
        h = s / w if w > 0 else 0
        return (int(cx - w / 2.0), int(cy - h / 2.0), int(w), int(h))
