"""Typed entity-to-entity edge models and registry for WorldGraph."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import time
from typing import Any


@dataclass
class WorldEdge:
    """Directed typed relationship between two WorldGraph entities (e.g. CARRIES, OWNED_BY)."""

    source_id: str = ""
    target_id: str = ""
    relation: str = "CARRIES"
    edge_id: str = ""
    confidence: float = 1.0
    camera_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.edge_id and self.source_id and self.target_id and self.relation:
            self.edge_id = f"{self.source_id}:{self.relation}:{self.target_id}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize edge fields into a JSON-compatible dictionary."""
        return asdict(self)


class WorldEdgeRegistry:
    """In-memory registry for typed entity-to-entity WorldEdges with cascade pruning."""

    def __init__(self) -> None:
        self._edges: dict[str, WorldEdge] = {}

    def upsert(self, edge: WorldEdge, now: float | None = None) -> WorldEdge:
        """Insert or update a WorldEdge while preserving original created_at."""
        if not edge.source_id or not edge.target_id or not edge.relation:
            raise ValueError("WorldEdge requires non-empty source_id, target_id, and relation")
        ts = float(now) if now is not None else time.time()
        stored = deepcopy(edge)
        if not stored.edge_id:
            stored.edge_id = f"{stored.source_id}:{stored.relation}:{stored.target_id}"
        existing = self._edges.get(stored.edge_id)
        if existing is not None:
            stored.created_at = existing.created_at
        else:
            stored.created_at = ts
        stored.updated_at = ts
        self._edges[stored.edge_id] = stored
        return deepcopy(stored)

    def remove(self, edge_id: str) -> WorldEdge | None:
        """Remove an edge by edge_id and return a copy if it existed."""
        removed = self._edges.pop(edge_id, None)
        return deepcopy(removed) if removed is not None else None

    def get_edges(
        self,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
        relation: str | None = None,
    ) -> list[WorldEdge]:
        """Return isolated copies of edges matching optional source, target, and relation."""
        results: list[WorldEdge] = []
        for edge in self._edges.values():
            if source_id is not None and edge.source_id != source_id:
                continue
            if target_id is not None and edge.target_id != target_id:
                continue
            if relation is not None and edge.relation != relation:
                continue
            results.append(deepcopy(edge))
        return results

    def prune_for_entity(self, entity_id: str) -> list[str]:
        """Remove all edges where entity_id is either source or target."""
        matching = [
            eid
            for eid, edge in self._edges.items()
            if edge.source_id == entity_id or edge.target_id == entity_id
        ]
        for eid in matching:
            self._edges.pop(eid, None)
        return matching

    def prune_for_camera(self, camera_id: str) -> list[str]:
        """Remove all edges scoped to camera_id."""
        matching = [
            eid for eid, edge in self._edges.items() if edge.camera_id == camera_id
        ]
        for eid in matching:
            self._edges.pop(eid, None)
        return matching

    def to_dict(self) -> dict[str, dict[str, Any]]:
        """Serialize all registered edges into a JSON-compatible mapping."""
        return {eid: edge.to_dict() for eid, edge in self._edges.items()}

    def __len__(self) -> int:
        return len(self._edges)


class WorldGraphEdgeMixin:
    """Thread-safe edge operations mixed into WorldGraph."""

    _lock: Any
    _edges: WorldEdgeRegistry

    def upsert_edge(self, edge: WorldEdge) -> WorldEdge:
        """Insert or update a typed entity-to-entity WorldEdge."""
        with self._lock:
            return self._edges.upsert(edge, now=time.time())

    def remove_edge(self, edge_id: str) -> bool:
        """Remove a WorldEdge by edge_id, returning True if it existed."""
        with self._lock:
            return self._edges.remove(edge_id) is not None

    def get_edges(
        self,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
        relation: str | None = None,
    ) -> list[WorldEdge]:
        """Return isolated copies of WorldEdges matching optional filters."""
        with self._lock:
            return self._edges.get_edges(
                source_id=source_id, target_id=target_id, relation=relation
            )

