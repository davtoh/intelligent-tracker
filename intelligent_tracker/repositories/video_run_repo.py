"""Video Run Repository Mixin for TrackerDB.

Provides thread-safe SQLite CRUD, alias-aware lookup (``clip.mp4`` <->
``clip_h264.mp4``), and detection-stream retrieval over ``video_runs``.
"""

import json
import sqlite3
import time
import uuid
from typing import Any

from intelligent_tracker.repositories.video_schema import (
    UPSERT_VIDEO_RUN_SQL,
    canonical_video_base_name,
    expand_video_aliases,
    safe_video_basename,
)

_RUN_COLS = (
    "run_id, video_filename, base_filename, run_type, generated_at, timestamp, "
    "source_resolution, source_fps, config_json, metrics_json, report_json, "
    "(frame_detections_json IS NOT NULL) AS has_detections"
)


def _parse_json(raw: str | None, default: Any) -> Any:
    """Safely deserialize a JSON column with fallback."""
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _normalize_detector_sig(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize detector signature fields for replay compatibility checks."""
    data = cfg if isinstance(cfg, dict) else {}
    det = str(data.get("detector") or data.get("detector_model") or "").strip().lower()
    raw_classes = data.get("classes") if data.get("classes") is not None else data.get("detector_classes")
    if isinstance(raw_classes, str):
        classes = sorted(c.strip().lower() for c in raw_classes.split(",") if c.strip())
    elif isinstance(raw_classes, (list, tuple, set)):
        classes = sorted(str(c).strip().lower() for c in raw_classes if str(c).strip())
    else:
        classes = []
    raw_conf = data.get("confidence") if data.get("confidence") is not None else data.get("detector_confidence")
    conf = round(float(raw_conf), 3) if raw_conf is not None else None
    raw_nms = data.get("agnostic_nms") if data.get("agnostic_nms") is not None else data.get("detector_agnostic_nms")
    agnostic_nms = bool(True if raw_nms is None else raw_nms)
    return {"detector": det, "confidence": conf, "classes": classes, "agnostic_nms": agnostic_nms}


def detector_signature_matches(run_cfg: dict[str, Any] | None, expected_sig: dict[str, Any] | None) -> bool:
    """Return True when a cached video_run config matches the active detector signature."""
    if not expected_sig:
        return True
    exp, got = _normalize_detector_sig(expected_sig), _normalize_detector_sig(run_cfg)
    if exp["detector"] and got["detector"] and exp["detector"] != got["detector"]:
        return False
    if exp["confidence"] is not None and got["confidence"] is not None and exp["confidence"] != got["confidence"]:
        return False
    if exp["classes"] != got["classes"]:
        return False
    return exp["agnostic_nms"] == got["agnostic_nms"]


def _hydrate_video_run(row: sqlite3.Row, include_detections: bool = False) -> dict[str, Any]:
    """Convert a ``video_runs`` SQLite row into a clean dictionary."""
    data = dict(row)
    record: dict[str, Any] = {
        "run_id": data["run_id"],
        "filename": data["video_filename"],
        "video_filename": data["video_filename"],
        "base_filename": data["base_filename"],
        "run_type": data.get("run_type") or "batch",
        "generated_at": data.get("generated_at") or "",
        "timestamp": float(data.get("timestamp") or 0.0),
        "source_resolution": _parse_json(data.get("source_resolution"), None),
        "source_fps": data.get("source_fps"),
        "config": _parse_json(data.get("config_json"), {}),
        "metrics": _parse_json(data.get("metrics_json"), {}),
        "report": _parse_json(data.get("report_json"), {}),
        "has_detections": bool(data.get("has_detections")),
    }
    if include_detections:
        dets = _parse_json(data.get("frame_detections_json"), None)
        record["frame_detections"] = dets
        record["has_detections"] = dets is not None
    return record


def _build_save_params(
    video_filename: str, report: dict[str, Any], config: dict[str, Any] | None,
    frame_detections: list[dict[str, Any]] | None, source_resolution: list[int] | None,
    source_fps: float | None, run_type: str, base_filename: str | None,
    run_id: str | None, timestamp: float | None, generated_at: str | None,
    metrics: dict[str, Any] | None,
) -> tuple[str, tuple[Any, ...]]:
    """Validate and serialize arguments for ``UPSERT_VIDEO_RUN_SQL``."""
    safe_name = safe_video_basename(video_filename)
    if not safe_name:
        raise ValueError("video_filename must not be empty")
    canonical = safe_video_basename(base_filename) if base_filename else canonical_video_base_name(safe_name)
    rid = str(run_id).strip() if run_id else f"run_{uuid.uuid4().hex[:8]}"
    ts = float(timestamp) if timestamp is not None else time.time()
    gen_at = generated_at or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    resolved_metrics = metrics if metrics is not None else {
        k: report.get(k, 0) for k in (
            "frames_processed", "total_detections", "total_sightings", "unique_entities_identified"
        )
    }
    res_json = json.dumps(source_resolution) if source_resolution is not None else None
    det_json = json.dumps(frame_detections) if frame_detections is not None else None
    return rid, (
        rid, safe_name, canonical, run_type or "batch", gen_at, ts, res_json, source_fps,
        json.dumps(config or {}), json.dumps(resolved_metrics), json.dumps(report or {}), det_json,
    )


class VideoRunRepositoryMixin:
    """Provides SQLite persistence and alias-aware queries for ``video_runs``."""

    _conn: Any
    _lock: Any

    def save_video_run(
        self, video_filename: str, report: dict[str, Any],
        config: dict[str, Any] | None = None, frame_detections: list[dict[str, Any]] | None = None,
        source_resolution: list[int] | None = None, source_fps: float | None = None,
        run_type: str = "batch", base_filename: str | None = None, run_id: str | None = None,
        timestamp: float | None = None, generated_at: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist or update a video analytics run and optional detection stream."""
        rid, params = _build_save_params(
            video_filename, report, config, frame_detections, source_resolution,
            source_fps, run_type, base_filename, run_id, timestamp, generated_at, metrics,
        )
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database connection is closed")
            cur = self._conn.cursor()
            try:
                cur.execute(UPSERT_VIDEO_RUN_SQL, params)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()
        record = self.get_video_run(rid, include_detections=False) or {}
        if record and frame_detections is not None:
            record["frame_detections"] = frame_detections
            record["has_detections"] = True
        return record

    def get_video_run(
        self, run_id: str, video_filename: str | None = None, include_detections: bool = False
    ) -> dict[str, Any] | None:
        """Fetch a single video run by ``run_id`` (optionally scoped by aliases)."""
        cols = "*" if include_detections else _RUN_COLS
        params: list[Any] = [str(run_id).strip()]
        sql = f"SELECT {cols} FROM video_runs WHERE run_id = ?"
        if video_filename:
            aliases = expand_video_aliases(video_filename)
            if not aliases:
                return None
            ph = ",".join("?" for _ in aliases)
            sql += f" AND (video_filename IN ({ph}) OR base_filename IN ({ph}))"
            params.extend(aliases + aliases)
        with self._lock:
            if self._conn is None:
                return None
            row = self._conn.execute(sql, params).fetchone()
        return _hydrate_video_run(row, include_detections=include_detections) if row else None

    def list_video_runs(
        self, video_filename: str | None = None, include_detections: bool = False
    ) -> list[dict[str, Any]]:
        """List video runs (newest first), consolidated across recording aliases."""
        cols = "*" if include_detections else _RUN_COLS
        params: list[Any] = []
        sql = f"SELECT {cols} FROM video_runs"
        if video_filename is not None:
            aliases = expand_video_aliases(video_filename)
            if not aliases:
                return []
            ph = ",".join("?" for _ in aliases)
            sql += f" WHERE video_filename IN ({ph}) OR base_filename IN ({ph})"
            params.extend(aliases + aliases)
        with self._lock:
            if self._conn is None:
                return []
            rows = self._conn.execute(f"{sql} ORDER BY timestamp DESC", params).fetchall()
        return [_hydrate_video_run(r, include_detections=include_detections) for r in rows]

    def get_video_detection_stream(
        self, video_filename: str, run_id: str | None = None
    ) -> dict[str, Any] | None:
        """Retrieve frame detection stream for a video run (newest if ``run_id`` omitted)."""
        aliases = expand_video_aliases(video_filename)
        if not aliases:
            return None
        ph = ",".join("?" for _ in aliases)
        params: list[Any] = aliases + aliases
        sql = (
            "SELECT run_id, video_filename, base_filename, run_type, generated_at, "
            "source_resolution, source_fps, config_json, frame_detections_json "
            f"FROM video_runs WHERE (video_filename IN ({ph}) OR base_filename IN ({ph}))"
        )
        if run_id:
            sql += " AND run_id = ?"
            params.append(str(run_id).strip())
        with self._lock:
            if self._conn is None:
                return None
            row = self._conn.execute(f"{sql} ORDER BY timestamp DESC LIMIT 1", params).fetchone()
        if not row or row["frame_detections_json"] is None:
            return None
        detections = _parse_json(row["frame_detections_json"], [])
        dets_list = detections if isinstance(detections, list) else []
        return {
            "run_id": row["run_id"], "filename": row["video_filename"],
            "base_filename": row["base_filename"], "run_type": row["run_type"],
            "generated_at": row["generated_at"],
            "source_resolution": _parse_json(row["source_resolution"], None),
            "source_fps": row["source_fps"], "config": _parse_json(row["config_json"], {}),
            "frame_count": len(dets_list),
            "frame_detections": dets_list,
        }

    def get_latest_run_matching(
        self, video_filename: str, detector_signature: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Return newest detection stream for video_filename matching detector_signature."""
        aliases = expand_video_aliases(video_filename)
        if not aliases:
            return None
        ph = ",".join("?" for _ in aliases)
        params: list[Any] = aliases + aliases
        sql = (
            "SELECT run_id, video_filename, base_filename, run_type, generated_at, "
            "source_resolution, source_fps, config_json, frame_detections_json "
            f"FROM video_runs WHERE (video_filename IN ({ph}) OR base_filename IN ({ph})) "
            "AND frame_detections_json IS NOT NULL ORDER BY timestamp DESC"
        )
        with self._lock:
            if self._conn is None:
                return None
            rows = self._conn.execute(sql, params).fetchall()
        for row in rows:
            cfg = _parse_json(row["config_json"], {})
            if not detector_signature_matches(cfg, detector_signature):
                continue
            detections = _parse_json(row["frame_detections_json"], [])
            dets_list = detections if isinstance(detections, list) else []
            return {
                "run_id": row["run_id"], "filename": row["video_filename"],
                "base_filename": row["base_filename"], "run_type": row["run_type"],
                "generated_at": row["generated_at"],
                "source_resolution": _parse_json(row["source_resolution"], None),
                "source_fps": row["source_fps"], "config": cfg,
                "frame_count": len(dets_list), "frame_detections": dets_list,
            }
        return None

    def update_video_run_resolution(
        self, run_id: str, source_resolution: list[int] | None, source_fps: float | None = None
    ) -> bool:
        """Update inferred ``source_resolution`` (and optional ``source_fps``) on a run."""
        res_json = json.dumps(source_resolution) if source_resolution is not None else None
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "UPDATE video_runs SET source_resolution = ?, "
                    "source_fps = COALESCE(?, source_fps) WHERE run_id = ?",
                    (res_json, source_fps, str(run_id).strip()),
                )
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def update_video_run_payload(
        self,
        run_id: str,
        report: dict[str, Any] | None = None,
        frame_detections: list[dict[str, Any]] | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> bool:
        """Update serialized ``report_json``, ``frame_detections_json``, or ``metrics_json``."""
        rep_json = json.dumps(report) if report is not None else None
        det_json = json.dumps(frame_detections) if frame_detections is not None else None
        met_json = json.dumps(metrics) if metrics is not None else None
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "UPDATE video_runs SET "
                    "report_json = COALESCE(?, report_json), "
                    "frame_detections_json = COALESCE(?, frame_detections_json), "
                    "metrics_json = COALESCE(?, metrics_json) WHERE run_id = ?",
                    (rep_json, det_json, met_json, str(run_id).strip()),
                )
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def delete_video_run(self, video_filename: str, run_id: str) -> bool:
        """Delete a single video run across all recording aliases."""
        aliases = expand_video_aliases(video_filename)
        safe_rid = str(run_id or "").strip()
        if not aliases or not safe_rid:
            return False
        ph = ",".join("?" for _ in aliases)
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute(
                    f"DELETE FROM video_runs WHERE run_id = ? AND "
                    f"(video_filename IN ({ph}) OR base_filename IN ({ph}))",
                    [safe_rid] + aliases + aliases,
                )
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def clear_video_runs(self, video_filename: str) -> int:
        """Delete all archived video runs across all recording aliases."""
        aliases = expand_video_aliases(video_filename)
        if not aliases:
            return 0
        ph = ",".join("?" for _ in aliases)
        with self._lock:
            if self._conn is None:
                return 0
            cur = self._conn.cursor()
            try:
                cur.execute(
                    f"DELETE FROM video_runs WHERE video_filename IN ({ph}) OR base_filename IN ({ph})",
                    aliases + aliases,
                )
                self._conn.commit()
                return cur.rowcount
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()
