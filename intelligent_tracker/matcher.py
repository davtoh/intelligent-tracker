#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Gallery Matcher & Re-Appearance Engine Module.

Combines short-term frame-to-frame multi-object tracking (Track) with long-term
visual Re-ID gallery matching against TrackerDB:
- Multi-frame feature pooling & temporal feature smoothing per track.
- Fast vectorized cosine similarity matrix search across enrolled entity signatures.
- Cross-session re-appearance recognition linking track IDs to persistent Entity IDs.
- Debounced sighting audit trail logging.
- Event emission for identified entities.
"""

from __future__ import division, print_function, absolute_import

import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple, Any, Union

import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import BaseFeatureExtractor, batch_cosine_similarity
from intelligent_tracker.tracker import Track


@dataclass
class EntityIdentifiedEvent(object):
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


class GalleryMatcher(object):
    """
    Coordinates gallery Re-ID matching between active tracks and persistent TrackerDB.
    """

    def __init__(
        self,
        db: TrackerDB,
        extractor: BaseFeatureExtractor,
        reid_threshold: float = 0.65,
        feature_history_len: int = 10,
        sighting_interval: float = 4.0,
        min_track_hits: int = 2,
    ):
        """
        :param db: TrackerDB database instance.
        :param extractor: BaseFeatureExtractor instance (ColorHistogramExtractor or OnnxReIDExtractor).
        :param reid_threshold: Minimum cosine similarity required to link track to entity [0.0, 1.0].
        :param feature_history_len: Number of high-confidence feature vectors to pool per track.
        :param sighting_interval: Minimum seconds between successive database sightings for the same track.
        :param min_track_hits: Minimum confirmed track updates before attempting Re-ID.
        """
        self.db = db
        self.extractor = extractor
        self.reid_threshold = float(reid_threshold)
        self.feature_history_len = int(feature_history_len)
        self.sighting_interval = float(sighting_interval)
        self.min_track_hits = int(min_track_hits)

        # Track feature memory: track_id -> deque of 1D embeddings
        self._track_features: Dict[int, deque] = {}

        # Sighting debounce memory: track_id -> last_logged_timestamp
        self._last_sighting_time: Dict[int, float] = {}

        # Track identification state: track_id -> {entity_id, name, category, similarity}
        self._identified_tracks: Dict[int, Dict[str, Any]] = {}

        # In-memory gallery cache
        self.gallery_matrix = np.empty((0, 0), dtype=np.float32)
        self.gallery_entity_ids: List[int] = []
        self.gallery_names: List[str] = []
        self.gallery_categories: List[str] = []

        self.reload_gallery()

    def reload_gallery(self):
        """Reload and vectorize all enrolled active signatures from SQLite database."""
        mat, ids, names, categories = self.db.get_gallery_embeddings()
        self.gallery_matrix = mat
        self.gallery_entity_ids = ids
        self.gallery_names = names
        self.gallery_categories = categories

    @property
    def gallery_size(self) -> int:
        return len(self.gallery_entity_ids)

    def _get_smoothed_embedding(self, track_id: int) -> Optional[np.ndarray]:
        """Compute mean feature vector from accumulated history."""
        buf = self._track_features.get(track_id)
        if not buf:
            return None
        arr = np.array(buf, dtype=np.float32)
        mean_vec = np.mean(arr, axis=0)
        norm = np.linalg.norm(mean_vec)
        if norm > 1e-7:
            mean_vec = mean_vec / norm
        return mean_vec

    def match_track(
        self,
        track: Track,
        frame: np.ndarray,
        source: str = "",
        timestamp: Optional[float] = None,
        zone_id: str = "",
    ) -> Optional[EntityIdentifiedEvent]:
        """
        Process a single track: extract feature, smooth embedding, and query gallery.

        :return: EntityIdentifiedEvent if newly identified, else None.
        """
        now = timestamp if timestamp is not None else time.time()
        tid = track.track_id

        # Skip tracks that haven't met minimum hits or have invalid bbox
        if track.hits < self.min_track_hits or track.bbox[2] <= 4 or track.bbox[3] <= 4:
            return None

        # 1. Feature Extraction & Temporal Pooling
        if tid not in self._track_features:
            self._track_features[tid] = deque(maxlen=self.feature_history_len)

        # Extract feature vector for current frame
        feat = self.extractor.extract(frame, track.bbox)
        self._track_features[tid].append(feat)

        # If gallery is empty, nothing to match against
        if self.gallery_size == 0:
            return None

        # 2. Get temporal smoothed embedding
        query_vec = self._get_smoothed_embedding(tid)
        if query_vec is None:
            return None

        # 3. Vectorized batch similarity search
        similarities = batch_cosine_similarity(self.gallery_matrix, query_vec)
        if similarities.size == 0:
            return None

        best_idx = int(np.argmax(similarities))
        best_score = float(similarities[best_idx])

        # 4. Check recognition threshold
        event = None
        if best_score >= self.reid_threshold:
            entity_id = self.gallery_entity_ids[best_idx]
            name = self.gallery_names[best_idx]
            category = self.gallery_categories[best_idx]

            # Decorate track object with Re-ID attributes
            track.entity_id = entity_id
            track.entity_name = name
            track.entity_category = category
            track.reid_score = best_score

            was_identified = tid in self._identified_tracks
            prev_eid = self._identified_tracks[tid]["entity_id"] if was_identified else None

            # First identification or entity switch
            if not was_identified or prev_eid != entity_id:
                self._identified_tracks[tid] = {
                    "entity_id": entity_id,
                    "name": name,
                    "category": category,
                    "similarity": best_score,
                }
                event = EntityIdentifiedEvent(
                    entity_id=entity_id,
                    name=name,
                    category=category,
                    track_id=tid,
                    similarity=best_score,
                    source=source,
                    timestamp=now,
                    zone_id=zone_id,
                    bbox=track.bbox,
                )

            # 5. Debounced Sighting Logging to SQLite
            last_log = self._last_sighting_time.get(tid)
            if last_log is None or (now - last_log >= self.sighting_interval) or (now < last_log):
                self.db.add_sighting(
                    entity_id=entity_id,
                    track_id=tid,
                    source=source,
                    timestamp=now,
                    zone_id=zone_id,
                    bbox=track.bbox,
                    confidence=best_score,
                )
                self._last_sighting_time[tid] = now

        return event

    def match_tracks(
        self,
        tracks: Dict[int, Track],
        frame: np.ndarray,
        source: str = "",
        timestamp: Optional[float] = None,
        zone_lookup: Optional[Dict[int, str]] = None,
    ) -> List[EntityIdentifiedEvent]:
        """
        Process all active tracks, update gallery Re-ID status, and return identification events.

        :param tracks: Dictionary of active Track objects {track_id: Track}.
        :param frame: Current BGR image frame.
        :param source: Name or URL of video source / camera.
        :param timestamp: Frame timestamp.
        :param zone_lookup: Optional mapping {track_id: current_zone_name}.
        :return: List of EntityIdentifiedEvent for newly recognized tracks in this frame.
        """
        now = timestamp if timestamp is not None else time.time()
        events = []

        # Clean up stale tracks from memory
        active_tids = set(tracks.keys())
        stale_tids = [tid for tid in self._track_features if tid not in active_tids]
        for tid in stale_tids:
            self._track_features.pop(tid, None)
            self._last_sighting_time.pop(tid, None)
            self._identified_tracks.pop(tid, None)

        # Match active tracks
        for tid, trk in tracks.items():
            zid = zone_lookup.get(tid, "") if zone_lookup else ""
            ev = self.match_track(trk, frame, source=source, timestamp=now, zone_id=zid)
            if ev is not None:
                events.append(ev)

        return events

    def reassign_track(
        self,
        track: Track,
        new_entity_id: int,
        frame: Optional[np.ndarray] = None,
    ) -> bool:
        """
        Manually reassign a track to a different entity and optionally enroll
        the current crop as a new signature to improve future matching.
        """
        entity = self.db.get_entity(new_entity_id)
        if not entity:
            return False

        track.entity_id = new_entity_id
        track.entity_name = entity["name"]
        track.entity_category = entity["category"]
        track.reid_score = 1.0

        self._identified_tracks[track.track_id] = {
            "entity_id": new_entity_id,
            "name": entity["name"],
            "category": entity["category"],
            "similarity": 1.0,
        }

        # If frame provided, enroll this perspective as a new signature
        if frame is not None:
            feat = self.extractor.extract(frame, track.bbox)
            self.db.add_signature(new_entity_id, feat)
            self.reload_gallery()

        return True
