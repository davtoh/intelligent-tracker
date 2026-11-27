#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Diagnostic Trace Bridge & FastAPI Exception Middleware.

Integrates the Universal Runtime Diagnostic Trace Recorder with FastAPI.
Captures unhandled request panics, background thread exceptions, and
records contextual metadata (path, method, client) into .diagnostics/traces/.
"""

import logging
import os
from pathlib import Path
import sys
from typing import Any, Optional

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("intelligent_tracker.diagnostic_bridge")

_SKILL = "system-diagnostics"


def _engine_candidates() -> list[Path]:
    """Return Runtime Parity candidate paths for the system-diagnostics engine."""
    here = Path(__file__).resolve()
    roots = list(here.parents)[:4]
    home = Path.home()
    found: list[Path] = []
    if os.environ.get("SYSTEM_DIAGNOSTICS_DIR"):
        found.append(Path(os.environ["SYSTEM_DIAGNOSTICS_DIR"]))
    found += [r / ".claude" / "skills" / _SKILL for r in roots]
    found.append(home / ".claude" / "skills" / _SKILL)
    found += [r.parent / _SKILL for r in roots]
    found += [r / "skills" / _SKILL for r in roots]
    found.append(home / ".gemini" / "config" / "skills" / _SKILL)
    return [c / "scripts" if (c / "scripts").is_dir() else c for c in found]


for _p in _engine_candidates():
    if (_p / "trace_recorder.py").is_file():
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
        break

_recorder_mod: Optional[Any] = None
_obs: Optional[Any] = None

try:
    import trace_recorder as _recorder_mod  # type: ignore
except ImportError:
    _recorder_mod = None

try:
    import observation_routes as _obs  # type: ignore
except ImportError:
    _obs = None

DIAGNOSTICS_BASE_PATH = "/api/diagnostics"
MAX_BODY_READ = 65537  # contract cap (64 KB) + 1 so oversize bodies still answer 413
RECORDING_ID_HEADER = "X-Debug-Recording-Id"
_MAX_RECORDING_ID = 64


def _clean_recording_id(value: Any) -> Optional[str]:
    """Return a validated recording id or None (request headers are untrusted input)."""
    text = str(value or "").strip()
    ok = bool(text) and text.isascii() and len(text) <= _MAX_RECORDING_ID and all(c.isalnum() or c in "-_." for c in text)
    return text if ok else None


def init_diagnostic_tracer(workspace_root: Optional[Path] = None) -> bool:
    """Initialize runtime trace recording hooks."""
    if _recorder_mod and hasattr(_recorder_mod, "install_trace_recorder"):
        ws = workspace_root or Path.cwd()
        _recorder_mod.install_trace_recorder(workspace_root=ws)
        logger.info("Initialized Universal Runtime Diagnostic Trace Recorder.")
        return True
    logger.debug("Runtime Diagnostic Trace Recorder not installed or not discoverable.")
    return False


def capture_runtime_exception(
    exc: BaseException,
    context: Optional[dict[str, Any]] = None,
    workspace_root: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Capture an explicit exception into .diagnostics/trace_catalog.json."""
    if _recorder_mod and hasattr(_recorder_mod, "record_exception"):
        return _recorder_mod.record_exception(exc, context=context, workspace_root=workspace_root)
    return None


def get_recent_traces(limit: int = 10, workspace_root: Optional[Path] = None) -> list[dict[str, Any]]:
    """Retrieve recent crash issues from .diagnostics/trace_catalog.json."""
    if _recorder_mod and hasattr(_recorder_mod, "TraceCatalogManager"):
        ws = workspace_root or Path(__file__).resolve().parents[2]
        mgr = _recorder_mod.TraceCatalogManager(ws)
        catalog = mgr.load_catalog()
        issues = catalog.get("issues", [])
        return sorted(issues, key=lambda x: x.get("last_seen", ""), reverse=True)[:limit]
    return []


class StaticNoCacheMiddleware:
    """Pure ASGI middleware adding Cache-Control: no-cache to /static/* without buffering /videos/*."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not str(scope.get("path", "")).startswith("/static/"):
            await self.app(scope, receive, send)
            return

        async def _send_wrapper(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                if not any(k.lower() == b"cache-control" for k, _ in headers):
                    headers.append((b"cache-control", b"no-cache"))
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send_wrapper)


class DiagnosticTraceMiddleware:
    """Pure ASGI middleware capturing unhandled HTTP 500 exceptions without buffering range streams.

    Copies validated ``X-Debug-Recording-Id`` request headers into the trace context as
    ``recording_id`` for correlation with HUD observations.
    """

    def __init__(self, app: Any, workspace_root: Optional[Path] = None) -> None:
        self.app = app
        self.workspace_root = workspace_root

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            headers = Headers(scope=scope)
            client = scope.get("client")
            method = str(scope.get("method", "GET"))
            path = str(scope.get("path", "/"))
            context: dict[str, Any] = {
                "http_method": method,
                "http_path": path,
                "client_host": str(client[0]) if client else "unknown",
            }
            recording_id = _clean_recording_id(headers.get(RECORDING_ID_HEADER))
            if recording_id:
                context["recording_id"] = recording_id
            capture_runtime_exception(exc, context=context, workspace_root=self.workspace_root)
            from dashboard.services.debug_session import is_debug_mode, record_debug_event

            if is_debug_mode():
                logger.exception("Unhandled HTTP 500 on %s %s", method, path)
                record_debug_event(exc, http_method=method, http_path=path)
            raise exc


def _readable(host: str) -> bool:
    return _obs is not None and host in _obs.LOOPBACK_HOSTS


def observations_enabled() -> bool:
    """Return True when the observation engine is available and FRONTIER_DEBUG_OBSERVATIONS=1."""
    return _obs is not None and _obs.enabled()


def handle_diagnostics_request(
    method: str,
    rel_path: str,
    query: Any,
    headers: dict[str, str],
    client_host: str,
    body: bytes = b"",
    workspace_root: Optional[Path] = None,
) -> tuple[int, dict[str, str], bytes]:
    """Framework-neutral entry point: returns (status, headers, body_bytes)."""
    if _obs is None:
        return 404, {"X-Diagnostics-Contract": "1"}, b'{"error": "not_found", "message": "engine unavailable"}'
    return _obs.handle(method, rel_path, query, headers, client_host, body, workspace_root)


def register_observation_routes(app: Any, workspace_root: Optional[Path] = None) -> bool:
    """Mount the Wire Contract v1 routes on a FastAPI app (only when FRONTIER_DEBUG_OBSERVATIONS=1)."""
    if not observations_enabled():
        return False

    @app.api_route(DIAGNOSTICS_BASE_PATH + "/{rest:path}", methods=["GET", "POST", "PATCH", "DELETE"], include_in_schema=False)
    async def _frontier_diagnostics(rest: str, request: Request) -> Response:
        host = request.client.host if request.client else ""
        body = b""
        if _readable(host):  # never buffer bodies for remote callers; cap the read for local ones
            async for chunk in request.stream():
                body += chunk
                if len(body) >= MAX_BODY_READ:
                    break
        status, headers, payload = handle_diagnostics_request(
            request.method, "/" + rest, request.url.query, dict(request.headers), host, body, workspace_root
        )
        return Response(content=payload, status_code=status, headers=headers)

    return True

