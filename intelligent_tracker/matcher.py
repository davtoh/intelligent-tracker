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


@dataclass
class SessionEntity(object):
    """
    Represents an automatically tracked canonical identity in the current video session.
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


class GalleryMatcher(object):
    """
    Coordinates gallery Re-ID matching between active tracks and persistent TrackerDB,
    as well as in-memory automatic session gallery tracking for consistent canonical identities.
    """

    def __init__(
        self,
        db: Optional[TrackerDB] = None,
        extractor: Optional[BaseFeatureExtractor] = None,
        reid_threshold: float = 0.65,
        feature_history_len: int = 10,
        sighting_interval: float = 4.0,
        min_track_hits: int = 2,
        auto_session_gallery: bool = True,
        session_reid_threshold: float = 0.55,
        spatial_bonus_radius: float = 200.0,
        spatial_bonus_max_dt: float = 60.0,
    ):
        """
        :param db: TrackerDB database instance (optional, for persistent enrollment).
        :param extractor: BaseFeatureExtractor instance (ColorHistogramExtractor or OnnxReIDExtractor).
        :param reid_threshold: Minimum cosine similarity required to link track to persistent entity [0.0, 1.0].
        :param feature_history_len: Number of high-confidence feature vectors to pool per track.
        :param sighting_interval: Minimum seconds between successive database sightings for the same track.
        :param min_track_hits: Minimum confirmed track updates before attempting Re-ID.
        :param auto_session_gallery: Automatically assign canonical labels ('Person #1') and re-link dropouts.
        :param session_reid_threshold: Similarity + spatial threshold to re-link returning session entities.
        :param spatial_bonus_radius: Pixel radius for spatial exit proximity boost.
        :param spatial_bonus_max_dt: Max seconds elapsed since exit to receive spatial proximity boost.
        """
        self.db = db
        self.extractor = extractor
        self.reid_threshold = float(reid_threshold)
        self.feature_history_len = int(feature_history_len)
        self.sighting_interval = float(sighting_interval)
        self.min_track_hits = int(min_track_hits)

        self.auto_session_gallery = bool(auto_session_gallery)
        self.session_reid_threshold = float(session_reid_threshold)
        self.spatial_bonus_radius = float(spatial_bonus_radius)
        self.spatial_bonus_max_dt = float(spatial_bonus_max_dt)

        # Automatic session gallery: session_id -> SessionEntity
        self.session_entities: Dict[int, SessionEntity] = {}
        self.next_session_id: int = 1
        self._active_tracks_cache: Dict[int, Track] = {}

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
        if self.db is None:
            self.gallery_matrix = np.empty((0, 0), dtype=np.float32)
            self.gallery_entity_ids = []
            self.gallery_names = []
            self.gallery_categories = []
            return
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

        if self.extractor is None:
            return None

        # 1. Feature Extraction & Temporal Pooling
        if tid not in self._track_features:
            self._track_features[tid] = deque(maxlen=self.feature_history_len)

        # Extract feature vector for current frame
        feat = self.extractor.extract(frame, track.bbox)
        self._track_features[tid].append(feat)

        query_vec = self._get_smoothed_embedding(tid)
        if query_vec is None:
            return None

        event = None

        # 2. Vectorized batch similarity search against persistent TrackerDB
        if self.gallery_size > 0:
            similarities = batch_cosine_similarity(self.gallery_matrix, query_vec)
            if similarities.size > 0:
                best_idx = int(np.argmax(similarities))
                best_score = float(similarities[best_idx])

                if best_score >= self.reid_threshold:
                    entity_id = self.gallery_entity_ids[best_idx]
                    name = self.gallery_names[best_idx]
                    category = self.gallery_categories[best_idx]

                    # Decorate track object with Re-ID attributes
                    track.entity_id = entity_id
                    track.entity_name = name
                    track.entity_category = category
                    track.reid_score = best_score
                    track.identity_label = name

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

                    # Debounced Sighting Logging to SQLite
                    if self.db is not None:
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

        # 3. Automatic Session Gallery Matching (if enabled and not enrolled in persistent DB)
        if self.auto_session_gallery and getattr(track, "entity_name", None) is None:
            if track.session_id is not None and track.session_id in self.session_entities:
                # Already linked to a session entity, update its history & position
                ent = self.session_entities[track.session_id]
                ent.feature_history.append(feat)
                ent.last_seen = now
                ent.last_centroid = track.centroid
                ent.exit_point = None
                ent.exit_time = None
                track.identity_label = ent.label
            else:
                # Try to re-link to an existing dormant session entity using fused affinity
                best_ent = None
                best_fused_score = -1.0

                for ent in self.session_entities.values():
                    # Category match check (case-insensitive)
                    if ent.category.lower() != (track.label or "object").lower():
                        continue

                    # Don't steal identity from another track currently active in this frame
                    is_active_elsewhere = False
                    for other_tid, other_trk in self._active_tracks_cache.items():
                        if other_tid != tid and other_trk.session_id == ent.session_id and other_trk.missed_frames == 0:
                            is_active_elsewhere = True
                            break
                    if is_active_elsewhere:
                        continue

                    ent_vec = ent.get_embedding()
                    if ent_vec is None:
                        continue

                    # Visual cosine similarity
                    visual_sim = float(np.dot(ent_vec, query_vec))

                    # Spatial proximity bonus if entity exited near current detection
                    spatial_bonus = 0.0
                    ref_point = ent.exit_point if ent.exit_point is not None else ent.last_centroid
                    ref_time = ent.exit_time if ent.exit_time is not None else ent.last_seen
                    dt = max(0.0, now - ref_time)
                    if dt <= self.spatial_bonus_max_dt and ref_point is not None:
                        dx = track.centroid[0] - ref_point[0]
                        dy = track.centroid[1] - ref_point[1]
                        dist = float(np.hypot(dx, dy))
                        if dist <= self.spatial_bonus_radius:
                            spatial_bonus = 0.15 * (1.0 - dist / self.spatial_bonus_radius)

                    fused_score = visual_sim + spatial_bonus

                    if fused_score > best_fused_score:
                        best_fused_score = fused_score
                        best_ent = ent

                if best_ent is not None and best_fused_score >= self.session_reid_threshold:
                    # Successfully re-identified returning entity!
                    track.session_id = best_ent.session_id
                    track.identity_label = best_ent.label
                    best_ent.assigned_track_ids.append(tid)
                    best_ent.feature_history.append(feat)
                    best_ent.last_seen = now
                    best_ent.last_centroid = track.centroid
                    best_ent.exit_point = None
                    best_ent.exit_time = None
                else:
                    # Allocate new canonical session entity
                    sess_id = self.next_session_id
                    self.next_session_id += 1
                    cat_name = (track.label or "object").capitalize()
                    label = "{} #{}".format(cat_name, sess_id)

                    new_ent = SessionEntity(
                        session_id=sess_id,
                        label=label,
                        category=track.label or "object",
                        feature_history=deque([feat], maxlen=self.feature_history_len),
                        first_seen=now,
                        last_seen=now,
                        last_centroid=track.centroid,
                        assigned_track_ids=[tid],
                    )
                    self.session_entities[sess_id] = new_ent
                    track.session_id = sess_id
                    track.identity_label = label

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
        self._active_tracks_cache = tracks

        # Clean up stale track feature buffers
        active_tids = set(tracks.keys())
        stale_tids = [tid for tid in self._track_features if tid not in active_tids]
        for tid in stale_tids:
            self._track_features.pop(tid, None)
            self._last_sighting_time.pop(tid, None)
            self._identified_tracks.pop(tid, None)

        # Update exit telemetry on session entities for tracks that just disappeared
        for ent in self.session_entities.values():
            if ent.exit_point is None:
                # Check if all assigned tracks for this entity are no longer active
                active_for_ent = [t for t in ent.assigned_track_ids if t in tracks and tracks[t].missed_frames == 0]
                if not active_for_ent:
                    ent.exit_point = ent.last_centroid
                    ent.exit_time = ent.last_seen

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
