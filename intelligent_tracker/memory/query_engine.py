"""Pluggable Semantic World Query Engine combining FTS5, ConfidenceEngine, and WorldGraph."""

from dataclasses import asdict, dataclass, field
import logging
import time
from typing import Any

from intelligent_tracker.memory._query_parser import ParsedWorldQuery, parse_world_query
from intelligent_tracker.memory.providers import (
    LocalDeterministicProvider,
    PrivacyMaskingFilter,
    SemanticProvider,
)

logger = logging.getLogger(__name__)


@dataclass
class WorldQueryResult:
    """Structured semantic query answer with grounded citations and entity confidence."""

    query: str
    answer: str
    intent: str = "timeline"
    provider: str = "local_deterministic"
    fallback_used: bool = False
    fallback_reason: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    world_summary: dict[str, Any] = field(default_factory=dict)
    parsed_filters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize query result into a JSON-compatible dictionary."""
        return asdict(self)


def _format_citation(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a timeline event row into a structured citation entry."""
    return {
        "event_id": row.get("id"),
        "event_type": row.get("event_type", ""),
        "timestamp": row.get("timestamp"),
        "camera_id": row.get("camera_id", ""),
        "zone_id": row.get("zone_id", ""),
        "entity_id": row.get("entity_id"),
        "entity_name": row.get("entity_name", ""),
        "category": row.get("category", ""),
        "title": row.get("title", ""),
        "summary": row.get("summary", ""),
        "confidence": row.get("confidence", 1.0),
        "rank": row.get("rank", 0.0),
    }


def _merge_live_entity_into_profile(
    profile: dict[str, Any],
    live_ent: dict[str, Any],
) -> dict[str, Any]:
    """Overlay live WorldGraph location and active zones onto an entity summary."""
    cams = sorted((live_ent.get("camera_tracks") or {}).keys())
    active_zones = [
        z for zlist in (live_ent.get("active_zones") or {}).values() for z in zlist
    ]
    if cams and not profile.get("last_camera_id"):
        profile["last_camera_id"] = cams[0]
    if active_zones and not profile.get("last_zone_id"):
        profile["last_zone_id"] = active_zones[0]
    profile["live_cameras"] = cams
    profile["live_zones"] = sorted(set(active_zones))
    profile["global_xy"] = live_ent.get("global_xy")
    profile["last_seen"] = max(float(profile.get("last_seen_at") or 0.0), float(live_ent.get("last_seen") or 0.0))
    if not profile.get("confidence") and live_ent.get("confidence"):
        profile["confidence"] = live_ent.get("confidence")
    return profile


def _apply_explicit_overrides(
    parsed: ParsedWorldQuery,
    entity_id: int | None,
    camera_id: str | None,
    zone_id: str | None,
    event_type: str | None,
    start_time: float | None,
    end_time: float | None,
) -> None:
    """Apply explicit caller filter overrides onto a ParsedWorldQuery."""
    if entity_id is not None:
        parsed.entity_id = int(entity_id)
    if camera_id:
        parsed.camera_id = camera_id.strip()
    if zone_id:
        parsed.zone_id = zone_id.strip()
    if event_type:
        parsed.event_type = event_type.strip()
    if start_time is not None:
        parsed.start_time = float(start_time)
    if end_time is not None:
        parsed.end_time = float(end_time)


class WorldQueryEngine:
    """Offline-capable natural-language Q&A over FTS5 timelines, confidence, and WorldGraph."""

    def __init__(
        self,
        db: Any = None,
        *,
        confidence_engine: Any = None,
        world_graph: Any = None,
        provider: SemanticProvider | None = None,
        privacy_filter: PrivacyMaskingFilter | None = None,
    ) -> None:
        self.db = db
        self.confidence_engine = confidence_engine
        self.world_graph = world_graph
        self.default_provider = LocalDeterministicProvider()
        self.provider: SemanticProvider = provider if provider is not None else self.default_provider
        self.privacy_filter = privacy_filter or PrivacyMaskingFilter(metadata_only=True)

    def set_provider(self, provider: SemanticProvider | None) -> None:
        """Swap the active SemanticProvider (None resets to LocalDeterministicProvider)."""
        self.provider = provider if provider is not None else self.default_provider

    def _collect_known_symbols(
        self, world_snap: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
        """Gather known entity profiles, camera IDs, and zone IDs for deterministic parsing."""
        entities: list[dict[str, Any]] = []
        if self.db is not None:
            try:
                entities.extend(self.db.list_entities())
            except Exception:
                pass
        for live in (world_snap.get("entities") or {}).values():
            if live.get("entity_id") is not None and live.get("name"):
                entities.append({"id": live["entity_id"], "name": live["name"], "category": live.get("category", "")})

        cameras = list((world_snap.get("cameras") or {}).keys())
        zones = [
            str(z.get("zone_id") or zid)
            for zid, z in (world_snap.get("zones") or {}).items()
        ]
        if self.db is not None:
            try:
                for row in self.db.search_timeline_events(query="", limit=100):
                    if row.get("camera_id"):
                        cameras.append(str(row["camera_id"]))
                    if row.get("zone_id"):
                        zones.append(str(row["zone_id"]))
            except Exception:
                pass
        return entities, cameras, zones

    def _retrieve_citations(self, parsed: ParsedWorldQuery, limit: int) -> list[dict[str, Any]]:
        """Query FTS5 timeline using AND-matched content keywords plus structured filters."""
        if self.db is None:
            return []
        rows = self.db.search_timeline_events(
            query=parsed.fts_query,
            entity_id=parsed.entity_id,
            camera_id=parsed.camera_id,
            zone_id=parsed.zone_id,
            event_type=parsed.event_type,
            start_time=parsed.start_time,
            end_time=parsed.end_time,
            limit=limit,
            require_all=bool(parsed.fts_query),
        )
        return [_format_citation(row) for row in rows]

    def _build_entity_profile(self, eid: int, world_snap: dict[str, Any], now: float) -> dict[str, Any]:
        """Build a unified entity confidence + live location dictionary."""
        profile: dict[str, Any] = {"entity_id": eid}
        if self.db is not None:
            rec = self.db.get_entity(eid)
            if rec:
                profile.update({"entity_name": rec.get("name", ""), "category": rec.get("category", "")})
            conf_row = self.db.get_entity_confidence(eid)
            if conf_row:
                profile.update(conf_row)
        if self.confidence_engine is not None:
            state = self.confidence_engine.get_state(eid, timestamp=now)
            if state is not None:
                profile.update(state.to_dict())
        live = (world_snap.get("entities") or {}).get(f"entity:{eid}")
        if live:
            _merge_live_entity_into_profile(profile, live)
        return profile

    def _resolve_entities(
        self,
        parsed: ParsedWorldQuery,
        citations: list[dict[str, Any]],
        world_snap: dict[str, Any],
        now: float,
    ) -> list[dict[str, Any]]:
        """Collect confidence and live location profiles for all referenced entities."""
        entity_ids: list[int] = []
        if parsed.entity_id is not None:
            entity_ids.append(parsed.entity_id)
        for cit in citations:
            cid = cit.get("entity_id")
            if cid is not None and int(cid) not in entity_ids:
                entity_ids.append(int(cid))
        if not entity_ids and parsed.intent in ("confidence", "presence"):
            for eid_key, live in (world_snap.get("entities") or {}).items():
                if live.get("entity_id") is not None and int(live["entity_id"]) not in entity_ids:
                    entity_ids.append(int(live["entity_id"]))
        return [self._build_entity_profile(eid, world_snap, now) for eid in entity_ids[:10]]

    def _synthesize_answer(
        self, query: str, context: dict[str, Any]
    ) -> tuple[str, str, bool, str | None]:
        """Run active SemanticProvider with PrivacyMaskingFilter and safe local fallback."""
        active = self.provider or self.default_provider
        if active is self.default_provider or isinstance(active, LocalDeterministicProvider):
            return active.synthesize(query, context), active.name, False, None

        sanitized = self.privacy_filter.sanitize_context(context)
        try:
            answer = active.synthesize(query, sanitized)
            return answer, active.name, False, None
        except Exception as exc:
            logger.warning("SemanticProvider '%s' failed (%s); falling back to local", active.name, exc)
            fallback = self.default_provider.synthesize(query, sanitized)
            return fallback, self.default_provider.name, True, str(exc)

    def ask(
        self,
        query: str,
        *,
        entity_id: int | None = None,
        camera_id: str | None = None,
        zone_id: str | None = None,
        event_type: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        limit: int = 15,
        include_world_snapshot: bool = True,
        now: float | None = None,
    ) -> WorldQueryResult:
        """Resolve a query across FTS5, ConfidenceEngine, and WorldGraph."""
        ref_now = float(now) if now is not None else time.time()
        world_snap = self.world_graph.snapshot() if (include_world_snapshot and self.world_graph is not None) else {}
        known_entities, known_cameras, known_zones = self._collect_known_symbols(world_snap)
        parsed = parse_world_query(
            query, known_entities=known_entities, known_cameras=known_cameras, known_zones=known_zones, now=ref_now,
        )
        _apply_explicit_overrides(parsed, entity_id, camera_id, zone_id, event_type, start_time, end_time)
        citations = self._retrieve_citations(parsed, max(1, int(limit)))
        entities = self._resolve_entities(parsed, citations, world_snap, ref_now)
        world_summary = {"counts": world_snap.get("counts", {}), "cameras": sorted((world_snap.get("cameras") or {}).keys())}
        context = {
            "query": query, "intent": parsed.intent, "parsed_filters": parsed.to_filter_dict(),
            "entities": entities, "citations": citations, "world_summary": world_summary,
        }
        answer, provider_name, fallback_used, fallback_reason = self._synthesize_answer(query, context)
        return WorldQueryResult(
            query=query, answer=answer, intent=parsed.intent, provider=provider_name,
            fallback_used=fallback_used, fallback_reason=fallback_reason, citations=citations,
            entities=entities, world_summary=world_summary, parsed_filters=parsed.to_filter_dict(),
        )
