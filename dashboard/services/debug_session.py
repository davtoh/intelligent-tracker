#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Isolated debug session management, runtime crash capture, and error deduplication."""

from logging.handlers import RotatingFileHandler
from pathlib import Path
import faulthandler
import hashlib
import json
import logging
import os
import threading
import time
import traceback
from typing import Any, IO, Optional

from dashboard.services.data_reset_service import wipe_debug_session
from dashboard.services.debug_triage import get_issue_context, summarize_debug_session

_STATE_LOCK = threading.Lock()
_INSTALLED_DIR: Optional[Path] = None
_ATTACHED_HANDLERS: list[logging.Handler] = []
_FAULT_FILE: Optional[IO[str]] = None

__all__ = [
    "StructuredJsonlHandler",
    "compute_event_fingerprint",
    "get_debug_session_dir",
    "get_issue_context",
    "install_debug_runtime",
    "is_debug_mode",
    "prepare_debug_session_env",
    "record_debug_event",
    "record_user_observation",
    "summarize_debug_session",
    "uninstall_debug_runtime",
]


def is_debug_mode() -> bool:
    """Return True when IT_DEBUG_MODE is enabled in the environment."""
    return os.getenv("IT_DEBUG_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def get_debug_session_dir() -> Path:
    """Resolve the active debug session directory."""
    raw = os.getenv("TRACKER_DEBUG_DIR", "").strip()
    return Path(raw) if raw else Path("data") / "debug_session"


def prepare_debug_session_env(debug_dir: Optional[Path] = None, *, clean: bool = False) -> dict[str, str]:
    """Prepare isolated debug directories and export environment variables for server and reloader."""
    target = Path(debug_dir) if debug_dir else get_debug_session_dir()
    if clean:
        wipe_debug_session(target)
    else:
        (target / "crops").mkdir(parents=True, exist_ok=True)
        (target / "reports").mkdir(parents=True, exist_ok=True)

    env_values = {
        "IT_DEBUG_MODE": "1",
        "TRACKER_DEBUG_DIR": str(target),
        "TRACKER_DB_PATH": str(target / "tracker.db"),
        "TRACKER_DB": str(target / "tracker.db"),
        "CAMERAS_CONFIG_PATH": str(target / "cameras.json"),
        "SCENARIOS_CONFIG_PATH": str(target / "scenarios.yaml"),
        "TRACKER_CROPS_DIR": str(target / "crops"),
        "TRACKER_REPORTS_DIR": str(target / "reports"),
        "PYTHONASYNCIODEBUG": "1",
        "FRONTIER_DEBUG_OBSERVATIONS": os.environ.get("FRONTIER_DEBUG_OBSERVATIONS") or "1",
    }
    os.environ.update(env_values)
    return env_values


def compute_event_fingerprint(
    level: str,
    logger_name: str,
    exc_type: str,
    top_frame: str,
    message: str,
) -> str:
    """Compute a stable 10-char fingerprint grouping identical warnings/errors."""
    norm_msg = " ".join((message or "").split())[:160]
    seed = f"{level}|{logger_name}|{exc_type}|{top_frame}|{norm_msg}"
    return hashlib.sha1(seed.encode("utf-8", errors="replace")).hexdigest()[:10]


def _extract_frames_from_exc(exc_info: Any) -> tuple[str, list[str], str]:
    """Return (exc_type, top_frames, full_traceback) from a sys.exc_info tuple."""
    if not exc_info or not exc_info[0]:
        return "", [], ""
    exc_type = getattr(exc_info[0], "__name__", str(exc_info[0]))
    tb_obj = exc_info[2]
    frames: list[str] = []
    if tb_obj is not None:
        for frame in traceback.extract_tb(tb_obj)[-4:]:
            frames.append(f"{Path(frame.filename).name}:{frame.lineno} in {frame.name}")
    full_tb = "".join(traceback.format_exception(*exc_info))
    return exc_type, frames, full_tb


def _append_jsonl(jsonl_path: Path, payload: dict[str, Any], lock: threading.Lock) -> None:
    """Thread-safely append one JSON object line to events.jsonl."""
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False)
    with lock:
        with open(jsonl_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


class StructuredJsonlHandler(logging.Handler):
    """Logging handler writing WARNING+ events with deduplication fingerprints to events.jsonl."""

    def __init__(self, jsonl_path: Path, level: int = logging.WARNING) -> None:
        super().__init__(level=level)
        self.jsonl_path = Path(jsonl_path)
        self._write_lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        """Format and append log record without raising into application threads."""
        try:
            msg = record.getMessage()
            exc_type, frames, full_tb = _extract_frames_from_exc(record.exc_info)
            top_frame = frames[-1] if frames else f"{record.filename}:{record.lineno}"
            fp = compute_event_fingerprint(record.levelname, record.name, exc_type, top_frame, msg)
            payload = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
                "epoch": round(record.created, 3),
                "level": record.levelname,
                "logger": record.name,
                "fingerprint": fp,
                "exc_type": exc_type,
                "message": msg[:500],
                "top_frames": frames,
                "traceback": full_tb[-3000:] if full_tb else "",
                "http_method": getattr(record, "http_method", ""),
                "http_path": getattr(record, "http_path", ""),
            }
            _append_jsonl(self.jsonl_path, payload, self._write_lock)
        except Exception:
            pass


def record_debug_event(
    exc: BaseException,
    *,
    http_method: str = "",
    http_path: str = "",
    debug_dir: Optional[Path] = None,
) -> Optional[str]:
    """Directly record an HTTP/runtime exception into the debug session events.jsonl."""
    target = Path(debug_dir) if debug_dir else get_debug_session_dir()
    exc_info = (type(exc), exc, exc.__traceback__)
    exc_type, frames, full_tb = _extract_frames_from_exc(exc_info)
    msg = str(exc) or exc_type
    top_frame = frames[-1] if frames else ""
    fp = compute_event_fingerprint("ERROR", "dashboard.http", exc_type, top_frame, msg)
    payload = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "epoch": round(time.time(), 3),
        "level": "ERROR",
        "logger": "dashboard.http",
        "fingerprint": fp,
        "exc_type": exc_type,
        "message": msg[:500],
        "top_frames": frames,
        "traceback": full_tb[-3000:],
        "http_method": http_method,
        "http_path": http_path,
    }
    _append_jsonl(target / "events.jsonl", payload, _STATE_LOCK)
    return fp


def _sanitize_breadcrumbs(breadcrumbs: Optional[list[Any]], max_items: int = 30) -> list[dict[str, Any]]:
    """Keep at most the last max_items breadcrumb dicts with bounded scalar field lengths."""
    if not breadcrumbs:
        return []
    cleaned: list[dict[str, Any]] = []
    for item in list(breadcrumbs)[-max_items:]:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {}
        for k, v in list(item.items())[:10]:
            key = str(k)[:40]
            if isinstance(v, (int, float, bool)) or v is None:
                entry[key] = v
            else:
                entry[key] = str(v)[:200]
        if entry:
            cleaned.append(entry)
    return cleaned


def _sanitize_viewport(viewport: Optional[dict[str, Any]]) -> dict[str, int]:
    """Extract bounded integer width/height dimensions from a viewport payload."""
    if not isinstance(viewport, dict):
        return {}
    result: dict[str, int] = {}
    for key in ("width", "height"):
        val = viewport.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
            result[key] = min(int(val), 16384)
    return result


def record_user_observation(
    note: str,
    tab: str = "",
    url: str = "",
    breadcrumbs: Optional[list[dict[str, Any]]] = None,
    viewport: Optional[dict[str, Any]] = None,
    debug_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Record a structured user observation with bounded breadcrumbs into events.jsonl."""
    clean_note = " ".join(str(note or "").split())[:1000]
    if not clean_note:
        raise ValueError("Observation note cannot be empty")
    clean_tab = str(tab or "").strip()[:120]
    clean_url = str(url or "").strip()[:500]
    epoch = round(time.time(), 3)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))
    fp = compute_event_fingerprint("OBSERVATION", "dashboard.observation", "", clean_tab, clean_note)
    payload: dict[str, Any] = {
        "ts": ts,
        "epoch": epoch,
        "level": "OBSERVATION",
        "logger": "dashboard.observation",
        "fingerprint": fp,
        "note": clean_note,
        "message": clean_note[:500],
        "tab": clean_tab,
        "url": clean_url,
        "breadcrumbs": _sanitize_breadcrumbs(breadcrumbs, max_items=30),
        "viewport": _sanitize_viewport(viewport),
    }
    target = Path(debug_dir) if debug_dir else get_debug_session_dir()
    _append_jsonl(target / "events.jsonl", payload, _STATE_LOCK)
    return payload


def install_debug_runtime(debug_dir: Optional[Path] = None) -> dict[str, Any]:
    """Attach rotating debug.log, structured events.jsonl, and faulthandler idempotently."""
    global _INSTALLED_DIR, _FAULT_FILE
    target = Path(debug_dir) if debug_dir else get_debug_session_dir()
    target.mkdir(parents=True, exist_ok=True)
    with _STATE_LOCK:
        if _INSTALLED_DIR == target and _ATTACHED_HANDLERS:
            return {"debug_dir": str(target), "already_installed": True}
        uninstall_debug_runtime_unlocked()

        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s")
        rot = RotatingFileHandler(target / "debug.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        rot.setLevel(logging.DEBUG)
        rot.setFormatter(fmt)

        jsonl_handler = StructuredJsonlHandler(target / "events.jsonl", level=logging.WARNING)

        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        for name in ("intelligent_tracker", "dashboard"):
            logging.getLogger(name).setLevel(logging.DEBUG)
        root.addHandler(rot)
        root.addHandler(jsonl_handler)
        _ATTACHED_HANDLERS.extend([rot, jsonl_handler])

        _FAULT_FILE = open(target / "faulthandler.log", "a", encoding="utf-8")
        faulthandler.enable(file=_FAULT_FILE, all_threads=True)
        _INSTALLED_DIR = target

    return {
        "debug_dir": str(target),
        "debug_log": str(target / "debug.log"),
        "events_jsonl": str(target / "events.jsonl"),
        "faulthandler_log": str(target / "faulthandler.log"),
    }


def uninstall_debug_runtime_unlocked() -> None:
    """Detach debug handlers and close faulthandler file (caller holds _STATE_LOCK)."""
    global _INSTALLED_DIR, _FAULT_FILE
    root = logging.getLogger()
    for h in list(_ATTACHED_HANDLERS):
        try:
            root.removeHandler(h)
            h.close()
        except Exception:
            pass
    _ATTACHED_HANDLERS.clear()
    try:
        if faulthandler.is_enabled():
            faulthandler.disable()
    except Exception:
        pass
    if _FAULT_FILE is not None:
        try:
            _FAULT_FILE.close()
        except Exception:
            pass
        _FAULT_FILE = None
    _INSTALLED_DIR = None


def uninstall_debug_runtime() -> None:
    """Thread-safely detach debug handlers and release open log files."""
    with _STATE_LOCK:
        uninstall_debug_runtime_unlocked()
