"""Unified Track <-> WorldEntity <-> Persistent Entity synchronization bridge."""

import threading
import time
from typing import Any

from intelligent_tracker.world._bridge_helpers import (
    decorate_track_identity,
    detach_track_from_other_entities,
    extract_global_xy,
    promote_session_node,
    remove_track_from_zones,
    scoped_session_id,
    scoped_zone_id,
)
from intelligent_tracker.world._lifecycle import list_entities_snapshot
from intelligent_tracker.world.graph import WorldGraph
from intelligent_tracker.world.nodes import WorldEntity

_RESTRICTED_CATEGORIES = frozenset({"restricted", "banned", "blacklisted"})


class WorldEntityBridge:
    """Single source of truth coordinating Track, WorldEntity, and persistent TrackerDB Entity."""

    def __init__(
        self,
        world_graph: WorldGraph,
        db: Any = None,
        *,
        sync_interval: float = 0.5,
        stale_ttl: float = 30.0,
    ) -> None:
        self.world_graph = world_graph
        self.db = db
        self.sync_interval = max(0.0, float(sync_interval))
        self.stale_ttl = max(0.0, float(stale_ttl))
        self._lock = threading.Lock()
        self._last_sync: dict[tuple[str, int], tuple[float, str, str]] = {}

    def _resolve_entity_meta(
        self,
        entity_id: int,
        track: Any,
        name: str,
        category: str,
    ) -> tuple[str, str]:
        """Resolve entity name and category from overrides, track attributes, or TrackerDB."""
        resolved_name = name or getattr(track, "entity_name", "") or ""
        resolved_cat = category or getattr(track, "entity_category", "") or ""
        if (not resolved_name or not resolved_cat) and self.db is not None:
            record = self.db.get_entity(int(entity_id))
            if record:
                resolved_name = resolved_name or record.get("name", "")
                resolved_cat = resolved_cat or record.get("category", "person")
        return (
            resolved_name or f"Entity {entity_id}",
            resolved_cat or getattr(track, "label", None) or "person",
        )

    def sync_track_identification(
        self,
        camera_id: str,
        track: Any,
        entity_id: int,
        *,
        name: str = "",
        category: str = "",
        confidence: float = 0.0,
        zone_id: str = "",
        timestamp: float | None = None,
    ) -> WorldEntity:
        """Bind an identified Track to its canonical cross-camera WorldEntity node."""
        now = float(timestamp) if timestamp is not None else time.time()
        resolved_name, resolved_cat = self._resolve_entity_meta(entity_id, track, name, category)
        decorate_track_identity(track, int(entity_id), resolved_name, resolved_cat, confidence)

        target_we_id = f"entity:{int(entity_id)}"
        existing = self.world_graph.get_node(target_we_id, node_type="entity")
        entity = (
            existing
            if isinstance(existing, WorldEntity)
            else WorldEntity(entity_id=int(entity_id), last_seen=now)
        )

        promote_session_node(self.world_graph, camera_id, track, entity, target_we_id)
        detach_track_from_other_entities(
            self.world_graph, camera_id, int(track.track_id), target_we_id, entity, now
        )

        entity.name = resolved_name
        entity.category = resolved_cat
        entity.confidence = max(entity.confidence, float(confidence))
        entity.restricted = entity.restricted or (resolved_cat.lower() in _RESTRICTED_CATEGORIES)
        return self._finalize_entity_sync(entity, camera_id, track, zone_id, now)

    def sync_session_track(
        self,
        camera_id: str,
        track: Any,
        session_id: int | str,
        *,
        label: str = "",
        category: str = "",
        zone_id: str = "",
        timestamp: float | None = None,
    ) -> WorldEntity:
        """Register or update a temporary session-scoped WorldEntity for an unenrolled Track."""
        now = float(timestamp) if timestamp is not None else time.time()
        scoped_sid = scoped_session_id(camera_id, session_id)
        target_we_id = f"session:{scoped_sid}"
        existing = self.world_graph.get_node(target_we_id, node_type="entity")
        entity = (
            existing
            if isinstance(existing, WorldEntity)
            else WorldEntity(world_entity_id=target_we_id, session_id=scoped_sid, last_seen=now)
        )

        detach_track_from_other_entities(
            self.world_graph, camera_id, int(track.track_id), target_we_id, entity, now
        )
        entity.session_id = scoped_sid
        entity.name = label or getattr(track, "identity_label", "") or f"Session {session_id}"
        entity.category = category or getattr(track, "label", None) or "unknown"
        return self._finalize_entity_sync(entity, camera_id, track, zone_id, now)

    def _finalize_entity_sync(
        self,
        entity: WorldEntity,
        camera_id: str,
        track: Any,
        zone_id: str,
        now: float,
    ) -> WorldEntity:
        """Update common camera/position/zone fields, upsert WorldEntity, and cache throttle stamp."""
        tid = int(track.track_id)
        entity.camera_tracks[camera_id] = tid
        xy = extract_global_xy(track)
        if xy is not None:
            entity.global_xy = xy
        entity.last_seen = max(entity.last_seen, now)

        scoped_zone = scoped_zone_id(self.world_graph, camera_id, zone_id)
        if scoped_zone:
            entity.active_zones.setdefault(camera_id, set()).add(scoped_zone)

        result = self.world_graph.upsert_entity(entity)
        with self._lock:
            self._last_sync[(camera_id, tid)] = (now, entity.world_entity_id, scoped_zone)
        return result

    def sync_camera_tracks(
        self,
        camera_id: str,
        tracks: dict[int, Any],
        *,
        zone_lookup: dict[int, str] | None = None,
        timestamp: float | None = None,
        force: bool = False,
    ) -> list[WorldEntity]:
        """Push state-change or throttled track updates into WorldGraph for 30 FPS efficiency."""
        now = float(timestamp) if timestamp is not None else time.time()
        updated: list[WorldEntity] = []
        for tid, trk in tracks.items():
            raw_zone = (zone_lookup.get(tid, "") if zone_lookup else "") or getattr(trk, "current_zone", "") or ""
            synced = self._sync_single_camera_track(camera_id, tid, trk, raw_zone, now, force)
            if synced is not None:
                updated.append(synced)
        return updated

    def _sync_single_camera_track(
        self,
        camera_id: str,
        tid: int,
        trk: Any,
        raw_zone: str,
        now: float,
        force: bool,
    ) -> WorldEntity | None:
        """Sync one track if its identity/zone changed or its throttle interval elapsed."""
        entity_id = getattr(trk, "entity_id", None)
        session_id = getattr(trk, "session_id", None)
        if entity_id is not None:
            target_we_id = f"entity:{int(entity_id)}"
        elif session_id is not None:
            target_we_id = f"session:{scoped_session_id(camera_id, session_id)}"
        else:
            return None

        scoped_zone = scoped_zone_id(self.world_graph, camera_id, raw_zone)
        with self._lock:
            prev = self._last_sync.get((camera_id, int(tid)))
        if not force and prev is not None and prev[1] == target_we_id and prev[2] == scoped_zone:
            if (now - prev[0]) < self.sync_interval:
                return None

        if entity_id is not None:
            return self.sync_track_identification(
                camera_id, trk, int(entity_id),
                name=getattr(trk, "entity_name", "") or "",
                category=getattr(trk, "entity_category", "") or "",
                confidence=float(getattr(trk, "reid_score", 0.0) or 0.0),
                zone_id=raw_zone, timestamp=now,
            )
        return self.sync_session_track(
            camera_id, trk, session_id,
            label=getattr(trk, "identity_label", "") or "",
            category=getattr(trk, "label", "") or "",
            zone_id=raw_zone, timestamp=now,
        )

    def reassign_track(
        self,
        camera_id: str,
        track: Any,
        new_entity_id: int,
        *,
        name: str = "",
        category: str = "",
        confidence: float = 1.0,
        timestamp: float | None = None,
    ) -> bool:
        """Reassign a Track to a different persistent Entity and update WorldGraph atomically."""
        resolved_name, resolved_cat = name, category
        if (not resolved_name or not resolved_cat) and self.db is not None:
            record = self.db.get_entity(int(new_entity_id))
            if not record:
                return False
            resolved_name = resolved_name or record.get("name", "")
            resolved_cat = resolved_cat or record.get("category", "person")

        self.sync_track_identification(
            camera_id, track, int(new_entity_id),
            name=resolved_name, category=resolved_cat or "person",
            confidence=confidence, timestamp=timestamp,
        )
        return True

    def prune_stale_tracks(
        self,
        *,
        camera_id: str | None = None,
        active_track_ids: set[int] | None = None,
        max_age: float | None = None,
        timestamp: float | None = None,
    ) -> list[str]:
        """Detach disappeared or expired track bindings and prune empty WorldEntity nodes."""
        now = float(timestamp) if timestamp is not None else time.time()
        ttl = self.stale_ttl if max_age is None else max(0.0, float(max_age))
        pruned_ids: list[str] = []

        for entity in list_entities_snapshot(self.world_graph, camera_id=camera_id):
            stale_cams = [
                cam for cam, tid in entity.camera_tracks.items()
                if (camera_id is None or cam == camera_id)
                and (
                    (tid not in active_track_ids and (max_age is None or (now - entity.last_seen) >= ttl))
                    if active_track_ids is not None
                    else (now - entity.last_seen) >= ttl
                )
            ]
            if not stale_cams:
                continue
            self._detach_stale_cameras(entity, stale_cams, now)
            pruned_ids.append(entity.world_entity_id)

        return pruned_ids

    def _detach_stale_cameras(
        self,
        entity: WorldEntity,
        stale_cams: list[str],
        now: float,
    ) -> None:
        """Strip stale camera bindings from one WorldEntity and remove node if orphaned."""
        for cam in stale_cams:
            tid = entity.camera_tracks.pop(cam, None)
            entity.active_zones.pop(cam, None)
            remove_track_from_zones(self.world_graph, cam, tid, entity.world_entity_id)
            if tid is not None:
                with self._lock:
                    self._last_sync.pop((cam, int(tid)), None)

        if not entity.camera_tracks:
            self.world_graph.remove_node(entity.world_entity_id)
        else:
            entity.updated_at = now
            self.world_graph.upsert_entity(entity)
