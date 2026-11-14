"""Bounded benchmark telemetry collector and JSON reporter for CLI runs."""

import json
import math
import os
import time
from typing import Any


class BenchmarkCollector:
    """Collects per-frame step latencies and computes summary statistics."""

    def __init__(self) -> None:
        self._start_perf = time.perf_counter()
        self._step_latencies_ms: list[float] = []
        self._total_tracks_observed = 0

    @property
    def frame_count(self) -> int:
        """Number of recorded processing steps."""
        return len(self._step_latencies_ms)

    def record_step(self, latency_ms: float, *, track_count: int = 0) -> None:
        """Record a single frame processing duration in milliseconds."""
        self._step_latencies_ms.append(max(0.0, float(latency_ms)))
        self._total_tracks_observed += max(0, int(track_count))

    def summary(self, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Compute latency quantiles, effective FPS, and run metadata."""
        elapsed_s = max(1e-9, time.perf_counter() - self._start_perf)
        count = len(self._step_latencies_ms)
        if count == 0:
            stats = {"min_ms": 0.0, "mean_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
            effective_fps = 0.0
        else:
            ordered = sorted(self._step_latencies_ms)
            p95_idx = min(count - 1, max(0, math.ceil(0.95 * count) - 1))
            stats = {
                "min_ms": round(ordered[0], 3),
                "mean_ms": round(sum(ordered) / count, 3),
                "p95_ms": round(ordered[p95_idx], 3),
                "max_ms": round(ordered[-1], 3),
            }
            effective_fps = round(count / elapsed_s, 2)

        payload: dict[str, Any] = {
            "frames": count,
            "elapsed_s": round(elapsed_s, 4),
            "effective_fps": effective_fps,
            **stats,
            "total_tracks_observed": self._total_tracks_observed,
        }
        if metadata:
            payload["metadata"] = dict(metadata)
        return payload

    def export_json(
        self,
        output_path: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write benchmark summary JSON to ``output_path`` and return the payload."""
        report = self.summary(metadata=metadata)
        parent = os.path.dirname(os.path.abspath(output_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        return report


def format_benchmark_report(report: dict[str, Any]) -> str:
    """Format a benchmark summary dictionary for terminal output."""
    lines = [
        "Benchmark Metrics:",
        f"  Frames Sampled   : {report.get('frames', 0)}",
        f"  Effective FPS    : {report.get('effective_fps', 0.0):.2f} FPS",
        (
            "  Step Latency (ms): "
            f"min={report.get('min_ms', 0.0):.3f}  "
            f"mean={report.get('mean_ms', 0.0):.3f}  "
            f"p95={report.get('p95_ms', 0.0):.3f}  "
            f"max={report.get('max_ms', 0.0):.3f}"
        ),
    ]
    return "\n".join(lines)
