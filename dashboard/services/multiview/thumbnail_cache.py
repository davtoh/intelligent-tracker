#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Per-Camera Multi-View Thumbnail Cache.

Encodes scaled JPEG thumbnails (640 / 480 / 320 px wide) ONLY when at least one
active lease requests that tier, gated by the highest leased FPS for that tier.
Uses the already-rendered annotated frame when available, else the raw frame,
never triggering extra overlay renders (invariant E9).
"""

from dataclasses import dataclass
import threading
import time
from typing import Any

import cv2
import numpy as np

from dashboard.services.multiview.limits import get_multiview_limits

THUMB_TIERS: tuple[int, ...] = (320, 480, 640)


@dataclass(frozen=True)
class ThumbnailSlot:
    """Latest encoded thumbnail frame for a single tier."""

    seq: int
    ts_ms: int
    data: bytes


def normalize_tier(width: int) -> int:
    """Snap a requested max_width to one of the 3 canonical tiers (320/480/640)."""
    if width <= 320:
        return 320
    if width <= 480:
        return 480
    return 640


def _encode_tier_jpeg(frame: np.ndarray, tier: int, quality: int) -> bytes | None:
    """Resize frame proportionally to <= tier width and encode as JPEG."""
    if frame is None or frame.size == 0:
        return None
    height, width = frame.shape[:2]
    if width <= 0 or height <= 0:
        return None
    target = frame
    if width > tier:
        new_h = max(1, int(round(height * (tier / float(width)))))
        target = cv2.resize(frame, (tier, new_h), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", target, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        return None
    return buf.tobytes()


class ThumbnailCache:
    """Thread-safe per-camera thumbnail cache with tier leases and FPS gating."""

    def __init__(self, camera_id: str, quality: int | None = None) -> None:
        self.camera_id = camera_id
        self._quality = quality if quality is not None else get_multiview_limits().thumb_quality
        self._lock = threading.Lock()
        self._leases: dict[str, tuple[int, float]] = {}
        self._slots: dict[int, ThumbnailSlot] = {}
        self._last_encode_ts: dict[int, float] = {}

    def acquire_lease(self, lease_id: str, max_width: int, max_fps: float) -> int:
        """Register or update a viewer lease and return its normalized tier width."""
        tier = normalize_tier(int(max_width))
        fps = max(1.0, float(max_fps))
        with self._lock:
            self._leases[str(lease_id)] = (tier, fps)
        return tier

    def release_lease(self, lease_id: str) -> None:
        """Remove a viewer lease and prune cached slots for unleased tiers."""
        with self._lock:
            self._leases.pop(str(lease_id), None)
            active = {tier for tier, _ in self._leases.values()}
            for tier in list(self._slots):
                if tier not in active:
                    self._slots.pop(tier, None)
                    self._last_encode_ts.pop(tier, None)

    def has_leases(self) -> bool:
        """Return True when at least one viewer holds a thumbnail lease."""
        with self._lock:
            return bool(self._leases)

    def active_tier_fps(self) -> dict[int, float]:
        """Return {tier: max_requested_fps} for all currently leased tiers."""
        with self._lock:
            tiers: dict[int, float] = {}
            for tier, fps in self._leases.values():
                prev = tiers.get(tier, 0.0)
                if fps > prev:
                    tiers[tier] = fps
            return tiers

    def update_frame(self, frame: Any, seq: int, timestamp_s: float | None = None) -> list[int]:
        """Encode thumbnails for due leased tiers; return list of updated tier widths."""
        now = time.time() if timestamp_s is None else float(timestamp_s)
        due_tiers = self._collect_due_tiers(now)
        if not due_tiers:
            return []

        ts_ms = max(0, int(round(now * 1000.0)))
        encoded: dict[int, ThumbnailSlot] = {}
        for tier in due_tiers:
            jpeg = _encode_tier_jpeg(frame, tier, self._quality)
            if jpeg is not None:
                encoded[tier] = ThumbnailSlot(seq=int(seq), ts_ms=ts_ms, data=jpeg)

        if not encoded:
            return []
        with self._lock:
            for tier, slot in encoded.items():
                if any(t == tier for t, _ in self._leases.values()):
                    self._slots[tier] = slot
                    self._last_encode_ts[tier] = now
        return list(encoded.keys())

    def _collect_due_tiers(self, now: float) -> list[int]:
        """Return leased tiers whose min interval (1 / max_fps) has elapsed."""
        with self._lock:
            tiers: dict[int, float] = {}
            for tier, fps in self._leases.values():
                if fps > tiers.get(tier, 0.0):
                    tiers[tier] = fps
            due: list[int] = []
            for tier, fps in tiers.items():
                last_ts = self._last_encode_ts.get(tier)
                if last_ts is None or (now - last_ts) >= (1.0 / fps) - 1e-6 or now < last_ts:
                    due.append(tier)
            return due

    def get_latest(self, tier: int) -> ThumbnailSlot | None:
        """Return the latest ThumbnailSlot for ``tier`` if present."""
        with self._lock:
            return self._slots.get(normalize_tier(int(tier)))

    def clear(self) -> None:
        """Drop all leases, slots, and encode timestamps."""
        with self._lock:
            self._leases.clear()
            self._slots.clear()
            self._last_encode_ts.clear()


def maybe_update_manager_thumbnail(manager: Any, frame: Any, seq: int, timestamp_s: float) -> None:
    """Update ``manager.thumbnail_cache`` if present and at least one tier is leased."""
    cache = getattr(manager, "thumbnail_cache", None)
    if cache is not None and cache.has_leases():
        cache.update_frame(frame, seq, timestamp_s)
