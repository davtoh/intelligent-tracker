"""Pluggable Semantic Q&A Providers and Privacy Egress Guard."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import re
from typing import Any, Protocol, runtime_checkable

import requests

_MEDIA_AND_PATH_KEYS = frozenset({
    "snapshot_base64", "frame", "frame_base64", "crop", "crop_base64",
    "image", "image_base64", "embedding", "embeddings", "crop_path",
    "snapshot_path", "video_path", "raw_frame", "raw_crop",
})
_CREDENTIAL_URL_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^/\s@]+)@")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+\d{1,3}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}(?!\d)")


def _fmt_ts(ts: float | int | None) -> str:
    """Format a UNIX epoch timestamp into compact UTC ISO-8601 text."""
    if not ts:
        return "unknown time"
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@runtime_checkable
class SemanticProvider(Protocol):
    """Protocol implemented by local and cloud semantic Q&A synthesis providers."""

    name: str

    def synthesize(self, query: str, context: dict[str, Any]) -> str:
        """Generate a grounded natural-language response from structured context."""
        ...


class PrivacyMaskingFilter:
    """Metadata-only egress guard stripping raw crops, embeddings, paths, and PII."""

    def __init__(
        self,
        *,
        metadata_only: bool = True,
        allow_raw_media: bool = False,
        redact_pii: bool = True,
        anonymize_entities: bool = False,
        extra_blocked_keys: tuple[str, ...] = (),
    ) -> None:
        self.metadata_only = bool(metadata_only)
        self.allow_raw_media = bool(allow_raw_media)
        self.redact_pii = bool(redact_pii)
        self.anonymize_entities = bool(anonymize_entities)
        self.blocked_keys = _MEDIA_AND_PATH_KEYS | frozenset(k.lower() for k in extra_blocked_keys)

    def _scrub_string(self, text: str) -> str:
        """Redact credentialed URLs, email addresses, and phone numbers."""
        if not self.redact_pii or not text:
            return text
        cleaned = _CREDENTIAL_URL_RE.sub(r"\1[REDACTED]@", text)
        cleaned = _EMAIL_RE.sub("[REDACTED_EMAIL]", cleaned)
        return _PHONE_RE.sub("[REDACTED_PHONE]", cleaned)

    def _sanitize_value(self, value: Any, key_hint: str = "") -> Any:
        """Recursively sanitize nested dictionaries, lists, and strings."""
        if isinstance(value, dict):
            eid = value.get("entity_id")
            out: dict[str, Any] = {}
            for k, v in value.items():
                lower_k = str(k).lower()
                if (self.metadata_only or not self.allow_raw_media) and lower_k in self.blocked_keys:
                    continue
                if self.anonymize_entities and lower_k in ("entity_name", "name") and v:
                    out[k] = f"Entity #{eid}" if eid is not None else "[REDACTED_ENTITY]"
                else:
                    out[k] = self._sanitize_value(v, lower_k)
            return out
        if isinstance(value, list):
            return [self._sanitize_value(item, key_hint) for item in value]
        if isinstance(value, str):
            return self._scrub_string(value)
        return value

    def sanitize_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return a sanitized deep copy safe for external semantic providers."""
        return self._sanitize_value(deepcopy(context or {}))


def _format_entity_lead(lead: dict[str, Any], intent: str) -> str:
    """Format the primary matched entity's confidence and last known location."""
    label = lead.get("entity_name") or lead.get("name") or f"Entity {lead.get('entity_id')}"
    conf = lead.get("confidence")
    cam = lead.get("last_camera_id") or lead.get("camera_id") or ""
    zone = lead.get("last_zone_id") or lead.get("zone_id") or ""
    loc = " / ".join(p for p in (cam, zone) if p) or "unknown location"
    seen = _fmt_ts(lead.get("last_seen_at") or lead.get("last_seen"))
    if intent == "confidence" and conf is not None:
        return (
            f"{label} confidence is {float(conf):.2f} "
            f"(face={float(lead.get('face_score', 0.0)):.2f}, "
            f"body={float(lead.get('body_score', 0.0)):.2f}, "
            f"streak={int(lead.get('streak_count', 0))}, "
            f"confirmations={int(lead.get('confirmation_count', 0))}); "
            f"last seen at {loc} ({seen})."
        )
    if conf is not None:
        return f"{label} (confidence {float(conf):.2f}) was last seen at {loc} ({seen})."
    return f"{label} is tracked at {loc} ({seen})."


class LocalDeterministicProvider:
    """Zero-dependency offline formatter producing grounded answers from memory context."""

    name: str = "local_deterministic"

    def synthesize(self, query: str, context: dict[str, Any]) -> str:
        """Format entity confidence, live world state, and timeline citations offline."""
        intent = str(context.get("intent", "timeline"))
        entities = list(context.get("entities") or [])
        citations = list(context.get("citations") or [])
        parts: list[str] = []
        if entities:
            parts.append(_format_entity_lead(entities[0], intent))
        if citations:
            bullets = [f"[{_fmt_ts(c.get('timestamp'))}] {c.get('summary', '')}" for c in citations[:3]]
            parts.append("Matching events: " + " | ".join(bullets))
        if not parts:
            counts = context.get("world_summary", {}).get("counts", {})
            return (
                f"No matching timeline records found for '{query}'. "
                f"Active world has {counts.get('entities', 0)} entities across {counts.get('cameras', 0)} cameras."
            )
        return " ".join(parts)


class MockSemanticProvider:
    """Deterministic test double recording sanitized invocations and supporting error injection."""

    name: str = "mock"

    def __init__(
        self,
        response: str | None = None,
        *,
        error: Exception | None = None,
        name: str = "mock",
    ) -> None:
        self.name = name
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def synthesize(self, query: str, context: dict[str, Any]) -> str:
        """Record sanitized call arguments and return mock synthesis or raise error."""
        self.calls.append({"query": query, "context": deepcopy(context)})
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        return f"[Mock synthesis for '{query}'] {LocalDeterministicProvider().synthesize(query, context)}"


class GeminiSemanticProvider:
    """Optional Gemini API semantic adapter configured strictly via environment variables."""

    name: str = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        endpoint_base: str | None = None,
        timeout_s: float = 15.0,
        privacy_filter: PrivacyMaskingFilter | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
        self.model = (model if model is not None else os.getenv("GEMINI_MODEL", "gemini-2.5-flash")).strip()
        self.endpoint_base = (
            endpoint_base
            if endpoint_base is not None
            else os.getenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com")
        ).strip().rstrip("/")
        self.timeout_s = max(1.0, float(timeout_s))
        self.privacy_filter = privacy_filter or PrivacyMaskingFilter(metadata_only=True)

    @property
    def is_configured(self) -> bool:
        """Return True when an API key is present in configuration/environment."""
        return bool(self.api_key)

    def synthesize(self, query: str, context: dict[str, Any]) -> str:
        """Synthesize a grounded answer via Gemini API after applying PrivacyMaskingFilter."""
        if not self.is_configured:
            raise RuntimeError("GeminiSemanticProvider is not configured (missing GEMINI_API_KEY)")

        safe_context = self.privacy_filter.sanitize_context(context)
        prompt = (
            "Answer the surveillance timeline query strictly from the provided JSON metadata.\n"
            f"Query: {query}\nContext JSON:\n{json.dumps(safe_context, default=str)}"
        )
        url = f"{self.endpoint_base}/v1beta/models/{self.model}:generateContent"
        resp = requests.post(
            url,
            params={"key": self.api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        payload = resp.json()
        candidates = payload.get("candidates") or []
        parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
        text = "".join(str(p.get("text", "")) for p in parts).strip()
        if not text:
            raise RuntimeError("Gemini API returned an empty response")
        return text
