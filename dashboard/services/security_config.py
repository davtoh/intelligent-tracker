#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - WebSocket & CORS Security Configuration.

Provides origin allowlist parsing, same-origin / allowlist validation,
and HMAC-SHA256 signed short-lived token utilities for WebSocket handshakes.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Iterable
from urllib.parse import urlsplit

from fastapi import WebSocket

MAX_TOKEN_TTL_S = 300


def _normalize_origin(origin: str) -> str:
    """Normalize an origin string to lowercase ``scheme://netloc`` without trailing slash."""
    cleaned = origin.strip().rstrip("/")
    if not cleaned or cleaned == "*":
        return cleaned
    parsed = urlsplit(cleaned)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    return cleaned.lower()


def parse_allowed_origins(raw: str | None = None) -> list[str]:
    """Parse comma-separated allowed origins from ``raw`` or ``ALLOWED_ORIGINS`` env var."""
    source = os.getenv("ALLOWED_ORIGINS", "") if raw is None else raw
    origins: list[str] = []
    for item in source.split(","):
        norm = _normalize_origin(item)
        if norm and norm not in origins:
            origins.append(norm)
    return origins


def get_multiview_token_secret() -> str:
    """Return the configured HMAC secret for WebSocket tokens (empty when disabled)."""
    return os.getenv("MULTIVIEW_TOKEN_SECRET", "").strip()


def is_origin_allowed(
    origin: str | None,
    host_header: str | None,
    allowlist: Iterable[str] | None = None,
) -> bool:
    """Return True if ``origin`` is absent (non-browser), same-origin with ``host_header``, or in ``allowlist``."""
    if origin is None or not origin.strip():
        return True

    norm_origin = _normalize_origin(origin)
    parsed = urlsplit(norm_origin)
    if parsed.scheme in ("http", "https") and parsed.netloc and host_header:
        if parsed.netloc.lower() == host_header.strip().lower():
            return True

    allowed = parse_allowed_origins() if allowlist is None else [_normalize_origin(o) for o in allowlist if o.strip()]
    if "*" in allowed:
        return True
    return norm_origin in allowed


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(token_part: str) -> bytes:
    padding = "=" * (-len(token_part) % 4)
    return base64.urlsafe_b64decode((token_part + padding).encode("ascii"))


def sign_token(
    subject: str,
    ttl_s: int = MAX_TOKEN_TTL_S,
    secret: str | None = None,
    now: float | None = None,
) -> str:
    """Create an HMAC-SHA256 signed token with ``exp`` clamped to ``1..300`` seconds."""
    resolved_secret = get_multiview_token_secret() if secret is None else secret
    if not resolved_secret:
        raise ValueError("MULTIVIEW_TOKEN_SECRET is not configured")

    clamped_ttl = min(max(int(ttl_s), 1), MAX_TOKEN_TTL_S)
    issued_at = int(time.time() if now is None else now)
    payload_bytes = json.dumps(
        {"sub": subject, "exp": issued_at + clamped_ttl},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)
    sig = hmac.new(
        resolved_secret.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{payload_b64}.{_b64url_encode(sig)}"


def verify_token(
    token: str | None,
    secret: str | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Verify an HMAC-SHA256 token and expiration; returns decoded payload or ``None``."""
    resolved_secret = get_multiview_token_secret() if secret is None else secret
    if not resolved_secret or not token or "." not in token:
        return None

    try:
        payload_b64, sig_b64 = token.split(".", 1)
        expected_sig = hmac.new(
            resolved_secret.encode("utf-8"),
            payload_b64.encode("ascii"),
            hashlib.sha256,
        ).digest()
        provided_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, provided_sig):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if not isinstance(payload, dict) or "exp" not in payload:
            return None
        now_ts = time.time() if now is None else float(now)
        if float(payload["exp"]) < now_ts:
            return None
        return payload
    except Exception:
        return None


def authorize_websocket(
    websocket: WebSocket,
    allowlist: Iterable[str] | None = None,
    token_secret: str | None = None,
) -> tuple[bool, str]:
    """Validate WebSocket handshake Origin and optional HMAC ``?token=`` before ``accept()``."""
    origin = websocket.headers.get("origin")
    host_header = websocket.headers.get("host")
    if not is_origin_allowed(origin, host_header, allowlist=allowlist):
        return False, "Origin not allowed"

    resolved_secret = get_multiview_token_secret() if token_secret is None else token_secret
    if resolved_secret:
        token = websocket.query_params.get("token", "")
        if verify_token(token, secret=resolved_secret) is None:
            return False, "Invalid or missing token"

    return True, ""
