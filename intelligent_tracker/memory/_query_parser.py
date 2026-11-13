"""Deterministic Natural-Language Query Parser for WorldQueryEngine."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import time
from typing import Any

_RELATIVE_TIME_RE = re.compile(
    r"\b(?:last|past)\s+(\d+)?\s*(second|sec|minute|min|hour|hr|day|week)s?\b",
    re.IGNORECASE,
)
_UNIT_SECONDS = {
    "second": 1.0, "sec": 1.0,
    "minute": 60.0, "min": 60.0,
    "hour": 3600.0, "hr": 3600.0,
    "day": 86400.0, "week": 604800.0,
}
_EVENT_TYPE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("rsac", "violation", "violations", "unauthorized", "breach", "breaches"), "rsac_violation"),
    (("intrusion", "trespass"), "intrusion_alert"),
    (("restricted", "blacklist", "banned"), "restricted_entity_alert"),
    (("pet", "pets", "dog", "cat"), "pet_activity"),
    (("tripwire", "crossed", "crossing", "crossings"), "tripwire_cross"),
    (("dwell", "loiter", "lingered"), "zone_dwell"),
    (("entered", "enter"), "zone_enter"),
    (("exited", "exit", "left"), "zone_exit"),
    (("caption", "captions", "clip"), "clip_caption"),
    (("sighting", "sightings", "spotted"), "sighting"),
)
_NOISE_WORDS = frozenset({
    "a", "about", "activity", "alert", "alerts", "all", "an", "and", "any", "are",
    "around", "at", "be", "been", "breach", "breaches", "by", "camera", "cameras",
    "check", "confidence", "confident", "crossed", "crossing", "crossings", "currently",
    "did", "do", "does", "entity", "event", "events", "find", "for", "from", "happened",
    "has", "have", "how", "in", "into", "is", "last", "list", "location", "me", "near",
    "of", "on", "or", "past", "please", "present", "recent", "rsac", "score", "seen",
    "show", "sighting", "sightings", "tell", "the", "there", "to", "today", "violation",
    "violations", "was", "we", "were", "what", "when", "where", "which", "who", "with",
    "zone", "zones",
})


@dataclass
class ParsedWorldQuery:
    """Structured filters and intent extracted deterministically from a user query."""

    raw_query: str
    intent: str = "timeline"
    fts_query: str = ""
    entity_id: int | None = None
    entity_name: str | None = None
    camera_id: str | None = None
    zone_id: str | None = None
    event_type: str | None = None
    start_time: float | None = None
    end_time: float | None = None

    def to_filter_dict(self) -> dict[str, Any]:
        """Serialize resolved filters for diagnostics and API responses."""
        return {
            "intent": self.intent,
            "fts_query": self.fts_query,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "camera_id": self.camera_id,
            "zone_id": self.zone_id,
            "event_type": self.event_type,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


def detect_query_intent(lower_q: str) -> str:
    """Classify the primary query intent deterministically."""
    if any(w in lower_q for w in ("confidence", "confident", "score", "certain", "trust", "reliable")):
        return "confidence"
    if any(w in lower_q for w in ("rsac", "violation", "intrusion", "alert", "breach", "restricted", "unauthorized")):
        return "security"
    if any(w in lower_q for w in ("where", "location", "currently", "zone", "camera")):
        return "location"
    if any(w in lower_q for w in ("who is", "present", "active", "around")):
        return "presence"
    return "timeline"


def extract_time_window(lower_q: str, now: float) -> tuple[float | None, float | None]:
    """Parse relative time expressions like 'last 2 hours' or 'today'."""
    match = _RELATIVE_TIME_RE.search(lower_q)
    if match:
        qty = int(match.group(1) or 1)
        unit = match.group(2).lower()
        return now - qty * _UNIT_SECONDS[unit], now
    if "today" in lower_q:
        dt = datetime.fromtimestamp(now, tz=timezone.utc)
        start_of_day = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return start_of_day, now
    return None, None


def _match_entity(lower_q: str, known_entities: list[dict[str, Any]]) -> tuple[int | None, str | None]:
    """Match the longest known entity name appearing in the query."""
    best_match: tuple[int, int, str] | None = None
    for ent in known_entities:
        name = str(ent.get("name") or ent.get("entity_name") or "").strip()
        eid = ent.get("id", ent.get("entity_id"))
        if not name or eid is None:
            continue
        pattern = rf"\b{re.escape(name.lower())}\b"
        if re.search(pattern, lower_q):
            if best_match is None or len(name) > best_match[0]:
                best_match = (len(name), int(eid), name)
    if best_match is not None:
        return best_match[1], best_match[2]
    return None, None


def _match_symbol(lower_q: str, candidates: list[str]) -> str | None:
    """Match a known camera_id or zone_id in the query (case-insensitive)."""
    ordered = sorted({c.strip() for c in candidates if c and c.strip()}, key=len, reverse=True)
    for item in ordered:
        normalized = item.lower().replace("_", "[_ ]?")
        if re.search(rf"\b{normalized}\b", lower_q):
            return item
    return None


def _extract_fts_keywords(raw_query: str, resolved_symbols: tuple[str | None, ...]) -> str:
    """Extract remaining content-bearing tokens for FTS5 BM25 matching."""
    cleaned = _RELATIVE_TIME_RE.sub(" ", raw_query or "")
    excluded = set(_NOISE_WORDS)
    for sym in resolved_symbols:
        if sym:
            excluded.update(tok.lower() for tok in re.findall(r"[A-Za-z0-9_]+", sym))
    tokens = re.findall(r"[A-Za-z0-9_]+", cleaned)
    kept = [t for t in tokens if t.lower() not in excluded and not t.isdigit()]
    return " ".join(kept)


def parse_world_query(
    query: str,
    *,
    known_entities: list[dict[str, Any]] | None = None,
    known_cameras: list[str] | None = None,
    known_zones: list[str] | None = None,
    now: float | None = None,
) -> ParsedWorldQuery:
    """Parse natural-language query into structured filters + FTS5 keywords."""
    ref_now = float(now) if now is not None else time.time()
    lower_q = (query or "").strip().lower()
    intent = detect_query_intent(lower_q)
    entity_id, entity_name = _match_entity(lower_q, known_entities or [])
    camera_id = _match_symbol(lower_q, known_cameras or [])
    zone_id = _match_symbol(lower_q, known_zones or [])
    start_time, end_time = extract_time_window(lower_q, ref_now)

    event_type: str | None = None
    for keywords, mapped_type in _EVENT_TYPE_HINTS:
        if any(re.search(rf"\b{re.escape(kw)}\b", lower_q) for kw in keywords):
            event_type = mapped_type
            break

    fts_query = _extract_fts_keywords(query, (entity_name, camera_id, zone_id))
    return ParsedWorldQuery(
        raw_query=query,
        intent=intent,
        fts_query=fts_query,
        entity_id=entity_id,
        entity_name=entity_name,
        camera_id=camera_id,
        zone_id=zone_id,
        event_type=event_type,
        start_time=start_time,
        end_time=end_time,
    )
