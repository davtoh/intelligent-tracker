"""Pre-Indexed File-Camera Detection Replay Provider.

Enables ``video_file`` cameras with a completed ``TrackerDB`` run to replay
timestamp/frame-aligned ``video_detections`` in the live stream pipeline
without redundant real-time YOLOv8 inference, falling back seamlessly to
live inference when no matching detection stream exists.
"""

from dataclasses import dataclass, field
import logging
import os
import time
from typing import Any

from intelligent_tracker.pipeline import FrameStepResult
from intelligent_tracker.repositories.video_schema import safe_video_basename

logger = logging.getLogger("intelligent_tracker.dashboard.file_detection_replay")


@dataclass
class ReplayTrack:
    """Lightweight Track-compatible adapter hydrated from stored ``frame_detections``."""

    id: int
    bbox: tuple[int, int, int, int]
    centroid: tuple[float, float] = (0.0, 0.0)
    velocity: tuple[float, float] = (0.0, 0.0)
    label: str = "object"
    confidence: float = 1.0
    dwell_time: float = 0.0
    entity_id: int | None = None
    entity_name: str | None = None
    identity_label: str | None = None
    category: str = "person"
    entity_category: str | None = None
    is_cluttered: bool = False
    clutter_partner_id: int | None = None
    state: str = "confirmed"
    history: list[tuple[float, float, float]] = field(default_factory=list)

    @property
    def track_id(self) -> int:
        """Return track identifier compatible with Track.track_id."""
        return self.id

    def to_dict(self) -> dict[str, Any]:
        """Serialize replay track to telemetry dictionary."""
        return {
            "track_id": self.id, "bbox": self.bbox, "centroid": self.centroid,
            "velocity": self.velocity, "label": self.label, "confidence": self.confidence,
            "dwell_time": self.dwell_time, "entity_id": self.entity_id,
            "entity_name": self.entity_name, "identity_label": self.identity_label,
            "category": self.category, "entity_category": self.entity_category or self.category,
            "state": self.state,
        }


def _hydrate_replay_track(raw: dict[str, Any], index: int) -> tuple[int, ReplayTrack] | None:
    """Convert a serialized detection track dict into a ``(track_id, ReplayTrack)`` pair."""
    bbox_raw = raw.get("bbox")
    if not isinstance(bbox_raw, (list, tuple)) or len(bbox_raw) < 4:
        return None
    bx, by, bw, bh = int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3])
    tid = int(raw.get("id", raw.get("track_id", index + 1)))
    c_raw = raw.get("centroid")
    cx, cy = (float(c_raw[0]), float(c_raw[1])) if isinstance(c_raw, (list, tuple)) and len(c_raw) >= 2 else (bx + bw / 2.0, by + bh / 2.0)
    v_raw = raw.get("velocity")
    vx, vy = (float(v_raw[0]), float(v_raw[1])) if isinstance(v_raw, (list, tuple)) and len(v_raw) >= 2 else (0.0, 0.0)
    ent_name = raw.get("entity_name") or raw.get("identity_label")
    cat = str(raw.get("entity_category") or raw.get("category") or "person")
    raw_eid = raw.get("entity_id")
    track = ReplayTrack(
        id=tid, bbox=(bx, by, bw, bh), centroid=(cx, cy), velocity=(vx, vy),
        label=str(raw.get("label") or "object"), confidence=float(raw.get("confidence", 1.0)),
        dwell_time=float(raw.get("dwell_time", 0.0)),
        entity_id=int(raw_eid) if raw_eid is not None else None,
        entity_name=str(ent_name) if ent_name else None, identity_label=str(ent_name) if ent_name else None,
        category=cat, entity_category=cat,
        is_cluttered=bool(raw.get("is_cluttered", False)), clutter_partner_id=raw.get("clutter_partner_id"),
        state=str(raw.get("state") or "confirmed"),
    )
    return tid, track


def _scale_bbox_tracks(
    tracks: dict[int, ReplayTrack],
    src_res: list[int] | None,
    frame_shape: tuple[int, ...],
) -> dict[int, ReplayTrack]:
    """Scale track bboxes/centroids when current frame dimensions differ from source_resolution."""
    if not tracks or not isinstance(src_res, (list, tuple)) or len(src_res) < 2:
        return tracks
    if len(frame_shape) < 2:
        return tracks
    src_w, src_h = int(src_res[0] or 0), int(src_res[1] or 0)
    cur_h, cur_w = int(frame_shape[0] or 0), int(frame_shape[1] or 0)
    if src_w <= 0 or src_h <= 0 or cur_w <= 0 or cur_h <= 0:
        return tracks
    if src_w == cur_w and src_h == cur_h:
        return tracks
    sx, sy = cur_w / float(src_w), cur_h / float(src_h)
    scaled: dict[int, ReplayTrack] = {}
    for tid, trk in tracks.items():
        bx, by, bw, bh = trk.bbox
        sbx, sby = int(round(bx * sx)), int(round(by * sy))
        sbw, sbh = max(1, int(round(bw * sx))), max(1, int(round(bh * sy)))
        scaled[tid] = ReplayTrack(
            id=trk.id, bbox=(sbx, sby, sbw, sbh),
            centroid=(trk.centroid[0] * sx, trk.centroid[1] * sy),
            velocity=(trk.velocity[0] * sx, trk.velocity[1] * sy),
            label=trk.label, confidence=trk.confidence, dwell_time=trk.dwell_time,
            entity_id=trk.entity_id, entity_name=trk.entity_name, identity_label=trk.identity_label,
            category=trk.category, entity_category=trk.entity_category,
            is_cluttered=trk.is_cluttered, clutter_partner_id=trk.clutter_partner_id, state=trk.state,
        )
    return scaled


def _find_closest_by_frame(
    records: list[dict[str, Any]],
    target_frame: int,
    max_frame_gap: int,
) -> dict[str, Any] | None:
    """Fallback linear frame-index match within max_frame_gap."""
    best_f, best_f_diff = None, max_frame_gap + 1
    for rec in records:
        rf = rec.get("frame")
        if rf is not None:
            f_diff = abs(int(rf) - int(target_frame))
            if f_diff <= max_frame_gap and f_diff < best_f_diff:
                best_f_diff, best_f = f_diff, rec
    return best_f


def _find_closest_record(
    records: list[dict[str, Any]],
    target_frame: int | None,
    target_time_s: float | None,
    fps: float,
    tolerance_s: float = 0.45,
) -> dict[str, Any] | None:
    """Locate the closest pre-indexed detection record by frame index or media timestamp."""
    if not records:
        return None
    query_t = target_time_s
    if query_t is None and target_frame is not None and fps > 0:
        query_t = max(0.0, float(target_frame)) / float(fps)
    if query_t is not None:
        low, high = 0, len(records) - 1
        while low <= high:
            mid = (low + high) >> 1
            rec_t = float(records[mid].get("time", 0.0))
            if rec_t < query_t:
                low = mid + 1
            elif rec_t > query_t:
                high = mid - 1
            else:
                return records[mid]
        best_rec, best_diff = None, float("inf")
        for idx in (low, high):
            if 0 <= idx < len(records):
                diff = abs(float(records[idx].get("time", 0.0)) - query_t)
                if diff < best_diff:
                    best_diff, best_rec = diff, records[idx]
        if best_rec is not None and best_diff <= tolerance_s:
            return best_rec
    if target_frame is not None:
        return _find_closest_by_frame(records, target_frame, max(3, int(round(fps * tolerance_s))))
    return None


class FileDetectionReplayProvider:
    """Replays pre-indexed ``video_runs`` detections for file-backed camera streams."""

    def __init__(
        self,
        db: Any,
        video_source: Any,
        *,
        run_id: str | None = None,
        tolerance_s: float = 0.45,
        empty_retry_ttl_s: float = 5.0,
    ) -> None:
        self.db = db
        self.video_source = video_source
        self.run_id = run_id
        self.tolerance_s = float(tolerance_s)
        self._empty_retry_ttl_s = max(0.0, float(empty_retry_ttl_s))
        self._loaded = False
        self._last_empty_check_at: float | None = None
        self._last_db_changes: int | None = None
        self._stream: dict[str, Any] | None = None
        self._records: list[dict[str, Any]] = []
        self._source_res: list[int] | None = None
        self._source_fps: float = 30.0

    def _resolve_filename(self) -> str:
        """Extract canonical video basename from video_source if it is a file source."""
        vs = self.video_source
        if vs is None or not getattr(vs, "is_file", False):
            return ""
        raw = str(getattr(vs, "source", "") or "").strip()
        return safe_video_basename(os.path.basename(raw.replace("\\", "/")))

    def ensure_loaded(self) -> bool:
        """Query TrackerDB for the newest completed detection stream, with bounded empty TTL."""
        if self._loaded and self._records:
            return True
        now = time.monotonic()
        db_changes = getattr(getattr(self.db, "_conn", None), "total_changes", None)
        if self._loaded and self._last_empty_check_at is not None:
            same_db = db_changes is None or db_changes == self._last_db_changes
            if same_db and (now - self._last_empty_check_at) < self._empty_retry_ttl_s:
                return False
        self._loaded = True
        self._last_empty_check_at = now
        self._last_db_changes = db_changes
        filename = self._resolve_filename()
        if not filename or self.db is None or not hasattr(self.db, "get_video_detection_stream"):
            return False
        try:
            stream = self.db.get_video_detection_stream(filename, run_id=self.run_id)
        except Exception as exc:
            logger.debug("FileDetectionReplayProvider lookup failed for %s: %s", filename, exc)
            return False
        if not stream or not isinstance(stream.get("frame_detections"), list):
            return False
        self._stream = stream
        self._records = sorted(
            [r for r in stream["frame_detections"] if isinstance(r, dict)],
            key=lambda r: float(r.get("time", 0.0)),
        )
        res = stream.get("source_resolution")
        self._source_res = list(res) if isinstance(res, (list, tuple)) and len(res) >= 2 else None
        vs_fps = float(getattr(self.video_source, "source_fps", 0.0) or 0.0)
        db_fps = float(stream.get("source_fps") or 0.0)
        self._source_fps = db_fps if db_fps > 0 else (vs_fps if vs_fps > 0 else 30.0)
        return bool(self._records)

    def resolve_media_time(self, frame_seq: int, *, media_time_s: float | None = None) -> float:
        """Resolve wrapped media timestamp in seconds for a 1-based frame_seq."""
        if media_time_s is not None:
            return float(media_time_s)
        total_records_last_t = float(self._records[-1].get("time", 0.0)) if self._records else 0.0
        fps = max(1.0, self._source_fps)
        raw_t = max(0, int(frame_seq) - 1) / fps
        return (raw_t % (total_records_last_t + (1.0 / fps))) if total_records_last_t > 0 else raw_t

    def lookup_tracks(
        self,
        frame_seq: int,
        frame_shape: tuple[int, ...],
        *,
        media_time_s: float | None = None,
    ) -> dict[int, ReplayTrack] | None:
        """Return frame-aligned ReplayTrack dict if a pre-indexed run exists, else None."""
        if not self.ensure_loaded():
            return None
        fps = max(1.0, self._source_fps)
        zero_based = max(0, int(frame_seq) - 1)
        resolved_t = self.resolve_media_time(frame_seq, media_time_s=media_time_s)
        rec = _find_closest_record(
            self._records, target_frame=zero_based, target_time_s=resolved_t,
            fps=fps, tolerance_s=self.tolerance_s,
        )
        if rec is None:
            return {}
        raw_tracks = rec.get("tracks") or []
        tracks: dict[int, ReplayTrack] = {}
        for idx, item in enumerate(raw_tracks):
            if isinstance(item, dict):
                hydrated = _hydrate_replay_track(item, idx)
                if hydrated is not None:
                    tracks[hydrated[0]] = hydrated[1]
        rec_res = rec.get("source_resolution") or self._source_res
        return _scale_bbox_tracks(tracks, rec_res, frame_shape)

    def build_step_result(
        self,
        frame: Any,
        now: float,
        frame_seq: int,
        fps: float = 0.0,
        *,
        media_time_s: float | None = None,
    ) -> FrameStepResult | None:
        """Build a synchronous ``FrameStepResult`` with zero inference lag if replay is active."""
        tracks = self.lookup_tracks(frame_seq, getattr(frame, "shape", ()), media_time_s=media_time_s)
        if tracks is None:
            return None
        res = FrameStepResult(
            frame=frame,
            tracks=tracks,
            timestamp=now,
            fps=fps if fps > 0 else self._source_fps,
            frame_count=frame_seq,
        )
        setattr(res, "inference_frame_seq", frame_seq)
        setattr(res, "inference_timestamp", now)
        setattr(res, "inference_lag_ms", 0.0)
        return res
