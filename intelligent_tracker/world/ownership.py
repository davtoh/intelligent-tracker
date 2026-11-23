"""Person+Bag ownership association and unattended-item detection engine."""

from dataclasses import dataclass
import threading
import time
from typing import Any

from intelligent_tracker.events.types import UnattendedItemAlert
from intelligent_tracker.world._ownership_helpers import (
    build_unattended_alert,
    euclidean_distance,
    resolve_entity_ref,
    track_center,
)
from intelligent_tracker.world.edges import WorldEdge
from intelligent_tracker.world.graph import WorldGraph

_DEFAULT_CARRY_LABELS = ("backpack", "handbag", "suitcase")
_DEFAULT_PERSON_LABELS = ("person", "mock_person")


@dataclass
class _OwnershipBinding:
    """Mutable association state for a carried bag track."""

    camera_id: str
    bag_track_id: int
    bag_world_entity_id: str
    item_label: str
    owner_track_id: int
    owner_entity_id: int | None
    owner_world_entity_id: str
    owner_name: str
    established_at: float
    separated_since: float | None = None
    last_alert_at: float | None = None
    alert_active: bool = False


class OwnershipAssociationEngine:
    """Tracks person+bag proximity to build CARRIES/OWNED_BY edges and unattended alerts."""

    def __init__(
        self,
        world_graph: WorldGraph,
        *,
        carry_labels: tuple[str, ...] = _DEFAULT_CARRY_LABELS,
        person_labels: tuple[str, ...] = _DEFAULT_PERSON_LABELS,
        proximity_px: float = 120.0,
        min_carry_seconds: float = 1.0,
        unattended_seconds: float = 5.0,
        separation_px: float = 180.0,
        alert_cooldown_seconds: float = 30.0,
    ) -> None:
        self.world_graph = world_graph
        self.carry_labels = frozenset(str(lbl).strip().lower() for lbl in carry_labels)
        self.person_labels = frozenset(str(lbl).strip().lower() for lbl in person_labels)
        self.proximity_px = max(1.0, float(proximity_px))
        self.min_carry_seconds = max(0.0, float(min_carry_seconds))
        self.unattended_seconds = max(0.0, float(unattended_seconds))
        self.separation_px = max(self.proximity_px, float(separation_px))
        self.alert_cooldown_seconds = max(0.0, float(alert_cooldown_seconds))
        self._lock = threading.Lock()
        self._candidates: dict[tuple[str, int, int], float] = {}
        self._bindings: dict[tuple[str, int], _OwnershipBinding] = {}

    def _partition_tracks(
        self, tracks: dict[int, Any],
    ) -> tuple[dict[int, Any], dict[int, Any]]:
        """Split active tracks into candidate persons and carryable items."""
        persons: dict[int, Any] = {}
        bags: dict[int, Any] = {}
        for tid, trk in tracks.items():
            lbl = str(getattr(trk, "label", "") or "").strip().lower()
            if lbl in self.person_labels or "person" in lbl:
                persons[tid] = trk
            elif lbl in self.carry_labels:
                bags[tid] = trk
        return persons, bags

    def _find_nearest_person(
        self, bag_center: tuple[float, float], persons: dict[int, Any],
    ) -> tuple[int, Any, float] | None:
        """Return (person_tid, person_trk, distance_px) for the closest person."""
        best: tuple[int, Any, float] | None = None
        for pid, ptrk in persons.items():
            dist = euclidean_distance(bag_center, track_center(ptrk))
            if best is None or dist < best[2]:
                best = (pid, ptrk, dist)
        return best

    def _find_owner_track(
        self, binding: _OwnershipBinding, persons: dict[int, Any],
    ) -> tuple[int, Any] | None:
        """Locate the bound owner's current Track by track_id or persistent entity_id."""
        if binding.owner_track_id in persons:
            return binding.owner_track_id, persons[binding.owner_track_id]
        if binding.owner_entity_id is not None:
            for pid, ptrk in persons.items():
                if getattr(ptrk, "entity_id", None) == binding.owner_entity_id:
                    return pid, ptrk
        return None

    def _upsert_world_edges(self, binding: _OwnershipBinding, now: float) -> None:
        """Write symmetric CARRIES and OWNED_BY edges into WorldGraph."""
        meta = {
            "owner_track_id": binding.owner_track_id,
            "bag_track_id": binding.bag_track_id,
            "item_label": binding.item_label,
        }
        self.world_graph.upsert_edge(WorldEdge(
            source_id=binding.owner_world_entity_id,
            target_id=binding.bag_world_entity_id,
            relation="CARRIES",
            camera_id=binding.camera_id,
            metadata=dict(meta),
            updated_at=now,
        ))
        self.world_graph.upsert_edge(WorldEdge(
            source_id=binding.bag_world_entity_id,
            target_id=binding.owner_world_entity_id,
            relation="OWNED_BY",
            camera_id=binding.camera_id,
            metadata=dict(meta),
            updated_at=now,
        ))

    def _remove_world_edges(self, binding: _OwnershipBinding) -> None:
        """Remove CARRIES and OWNED_BY edges for a pruned bag binding."""
        self.world_graph.remove_edge(
            f"{binding.owner_world_entity_id}:CARRIES:{binding.bag_world_entity_id}"
        )
        self.world_graph.remove_edge(
            f"{binding.bag_world_entity_id}:OWNED_BY:{binding.owner_world_entity_id}"
        )

    def _evaluate_bound_bag(
        self,
        binding: _OwnershipBinding,
        bag_trk: Any,
        persons: dict[int, Any],
        now: float,
        zone_lookup: dict[int, str],
        frame: Any,
    ) -> UnattendedItemAlert | None:
        """Check owner proximity for a bound bag and emit UnattendedItemAlert if abandoned."""
        bag_center = track_center(bag_trk)
        owner_match = self._find_owner_track(binding, persons)
        owner_present = False
        if owner_match is not None:
            owner_tid, owner_trk = owner_match
            binding.owner_track_id = owner_tid
            _, ent_id, name = resolve_entity_ref(self.world_graph, binding.camera_id, owner_tid, owner_trk)
            if ent_id is not None:
                binding.owner_entity_id = ent_id
            binding.owner_name = name
            owner_present = euclidean_distance(bag_center, track_center(owner_trk)) <= self.separation_px

        if owner_present:
            binding.separated_since = None
            binding.alert_active = False
            return None

        if binding.separated_since is None:
            binding.separated_since = now
            return None

        unattended_dur = now - binding.separated_since
        if unattended_dur < self.unattended_seconds:
            return None
        if binding.last_alert_at is not None and (now - binding.last_alert_at) < self.alert_cooldown_seconds:
            return None

        binding.last_alert_at = now
        binding.alert_active = True
        return build_unattended_alert(self.world_graph, binding, bag_trk, now, unattended_dur, zone_lookup, frame)

    def _decorate_tracks(
        self, camera_id: str, tracks: dict[int, Any], bindings: list[_OwnershipBinding],
    ) -> None:
        """Attach carrying/carried_by metadata onto Track objects for telemetry."""
        carrying_by_owner: dict[int, list[dict[str, Any]]] = {}
        carried_by_bag: dict[int, dict[str, Any]] = {}
        for b in bindings:
            if b.camera_id != camera_id:
                continue
            carrying_by_owner.setdefault(b.owner_track_id, []).append({
                "track_id": b.bag_track_id,
                "label": b.item_label,
                "unattended": b.alert_active,
            })
            carried_by_bag[b.bag_track_id] = {
                "track_id": b.owner_track_id,
                "entity_id": b.owner_entity_id,
                "name": b.owner_name,
                "unattended": b.alert_active,
            }
        for tid, trk in tracks.items():
            trk.carrying = carrying_by_owner.get(tid, [])
            trk.carried_by = carried_by_bag.get(tid)

    def _prune_stale_locked(
        self, camera_id: str, persons: dict[int, Any], bags: dict[int, Any],
    ) -> list[_OwnershipBinding]:
        """Prune vanished bag bindings and candidates under lock."""
        stale_keys = [k for k in self._bindings if k[0] == camera_id and k[1] not in bags]
        removed = [self._bindings.pop(key) for key in stale_keys]
        stale_cands = [
            ck for ck in self._candidates if ck[0] == camera_id and (ck[1] not in persons or ck[2] not in bags)
        ]
        for ck in stale_cands:
            self._candidates.pop(ck, None)
        return removed

    def _try_bind_bag_locked(
        self,
        camera_id: str,
        bag_tid: int,
        bag_trk: Any,
        persons: dict[int, Any],
        now: float,
    ) -> _OwnershipBinding | None:
        """Establish a new person+bag ownership binding if proximity persists >= min_carry_seconds."""
        nearest = self._find_nearest_person(track_center(bag_trk), persons)
        if nearest is None or nearest[2] > self.proximity_px:
            return None
        person_tid, person_trk, _ = nearest
        ckey = (camera_id, person_tid, bag_tid)
        first_ts = self._candidates.setdefault(ckey, now)
        if (now - first_ts) < self.min_carry_seconds:
            return None
        owner_we_id, owner_ent_id, owner_name = resolve_entity_ref(
            self.world_graph, camera_id, person_tid, person_trk
        )
        bag_we_id, _, _ = resolve_entity_ref(self.world_graph, camera_id, bag_tid, bag_trk)
        binding = _OwnershipBinding(
            camera_id=camera_id,
            bag_track_id=bag_tid,
            bag_world_entity_id=bag_we_id,
            item_label=str(getattr(bag_trk, "label", "bag") or "bag"),
            owner_track_id=person_tid,
            owner_entity_id=owner_ent_id,
            owner_world_entity_id=owner_we_id,
            owner_name=owner_name,
            established_at=now,
        )
        self._bindings[(camera_id, bag_tid)] = binding
        self._candidates.pop(ckey, None)
        return binding

    def update(
        self,
        camera_id: str,
        tracks: dict[int, Any],
        *,
        timestamp: float | None = None,
        zone_lookup: dict[int, str] | None = None,
        frame: Any = None,
    ) -> list[UnattendedItemAlert]:
        """Evaluate person+bag associations, update WorldGraph edges, and return alerts."""
        now = float(timestamp) if timestamp is not None else time.time()
        zones = zone_lookup or {}
        persons, bags = self._partition_tracks(tracks)
        alerts: list[UnattendedItemAlert] = []
        edges_to_upsert: list[_OwnershipBinding] = []

        with self._lock:
            edges_to_remove = self._prune_stale_locked(camera_id, persons, bags)
            for bag_tid, bag_trk in bags.items():
                binding = self._bindings.get((camera_id, bag_tid))
                if binding is not None:
                    alert = self._evaluate_bound_bag(binding, bag_trk, persons, now, zones, frame)
                    if alert is not None:
                        alerts.append(alert)
                else:
                    created = self._try_bind_bag_locked(camera_id, bag_tid, bag_trk, persons, now)
                    if created is not None:
                        edges_to_upsert.append(created)
            active_bindings = list(self._bindings.values())

        for binding in edges_to_remove:
            self._remove_world_edges(binding)
        for binding in edges_to_upsert:
            self._upsert_world_edges(binding, now)
        self._decorate_tracks(camera_id, tracks, active_bindings)
        return alerts
