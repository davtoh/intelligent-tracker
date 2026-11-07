#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Diagnostic Trace Bridge & FastAPI Exception Middleware.

Integrates the Universal Runtime Diagnostic Trace Recorder with FastAPI.
Captures unhandled request panics, background thread exceptions, and
records contextual metadata (path, method, client) into .diagnostics/traces/.
"""

import sys
import logging
from pathlib import Path
from typing import Any, Optional
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("intelligent_tracker.diagnostic_bridge")

# Attempt importing trace_recorder from standard locations or skills directory
_recorder_mod: Optional[Any] = None

try:
    import trace_recorder as _recorder_mod  # type: ignore
except ImportError:
    # Try locating system-diagnostics/scripts dynamically
    _candidates = [
        Path.home() / ".gemini" / "config" / "skills" / "system-diagnostics" / "scripts",
        Path(__file__).resolve().parents[2] / "skills" / "system-diagnostics" / "scripts",
    ]
    for _p in _candidates:
        if _p.is_dir() and str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
            try:
                import trace_recorder as _recorder_mod  # type: ignore
                break
            except ImportError:
                continue


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


class DiagnosticTraceMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware capturing unhandled HTTP 500 exceptions into trace catalog."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            context = {
                "http_method": request.method,
                "http_path": request.url.path,
                "client_host": request.client.host if request.client else "unknown",
            }
            capture_runtime_exception(exc, context=context)
            raise exc

