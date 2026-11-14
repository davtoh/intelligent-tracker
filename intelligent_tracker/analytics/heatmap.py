#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""2D Spatial Density Heatmap Engine for retail and occupancy analytics."""

import csv
import os
from typing import Any

import cv2
import numpy as np


def _generate_gaussian_kernel(r: int) -> np.ndarray:
    """Create a 2D Gaussian footprint normalized to peak 1.0."""
    size = 2 * r + 1
    x = np.arange(0, size, 1, float)
    y = x[:, np.newaxis]
    x0 = y0 = size // 2
    sigma = r / 2.5
    kernel = np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (2.0 * sigma ** 2))
    return kernel.astype(np.float32)


def _extract_centroids(
    tracks: dict[int, Any] | list[Any] | tuple[Any, ...],
) -> list[tuple[float, float]]:
    """Extract (cx, cy) centroids from a track mapping or sequence."""
    items = tracks.values() if isinstance(tracks, dict) else (
        tracks if isinstance(tracks, (list, tuple)) else ()
    )
    centroids: list[tuple[float, float]] = []
    for item in items:
        c = getattr(item, "centroid", None)
        if c is None and isinstance(item, (tuple, list)) and len(item) >= 2:
            c = item[:2]
        if c is not None:
            centroids.append(c)
    return centroids


class OccupancyHeatmap:
    """
    2D Spatial Density Heatmap Engine.

    Accumulates entity centroids over time, applies Gaussian kernel dispersion,
    supports continuous temporal decay (fading older dwell points), and renders
    translucent colormap overlays onto video frames.

    Parameters:
    -----------
    width : int
        Width of the video frame in pixels.
    height : int
        Height of the video frame in pixels.
    decay_rate : float | None
        Frame-by-frame exponential decay multiplier (e.g. 0.995). None = cumulative.
    radius : int
        Gaussian footprint radius in pixels around each centroid.
    colormap : int
        OpenCV colormap enum (e.g. cv2.COLORMAP_JET, cv2.COLORMAP_INFERNO).
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        decay_rate: float | None = 0.998,
        radius: int = 25,
        colormap: int = cv2.COLORMAP_JET,
    ):
        self.width = int(width)
        self.height = int(height)
        self.decay_rate = float(decay_rate) if decay_rate is not None else None
        self.radius = max(5, int(radius))
        self.colormap = colormap

        self.density = np.zeros((self.height, self.width), dtype=np.float32)
        self._kernel = _generate_gaussian_kernel(self.radius)

    def update(self, tracks: dict[int, Any] | list[Any] | tuple[Any, ...]):
        """
        Accumulate density from current tracked entities.

        :param tracks: dict[track_id, Track] or list of Track / centroid objects
        """
        if self.decay_rate is not None and 0.0 < self.decay_rate < 1.0:
            self.density *= self.decay_rate

        r = self.radius
        for cx, cy in _extract_centroids(tracks):
            cx_int = int(round(cx))
            cy_int = int(round(cy))

            x_min = max(0, cx_int - r)
            x_max = min(self.width, cx_int + r + 1)
            y_min = max(0, cy_int - r)
            y_max = min(self.height, cy_int + r + 1)
            if x_min >= x_max or y_min >= y_max:
                continue

            k_xmin = x_min - (cx_int - r)
            k_xmax = k_xmin + (x_max - x_min)
            k_ymin = y_min - (cy_int - r)
            k_ymax = k_ymin + (y_max - y_min)
            self.density[y_min:y_max, x_min:x_max] += self._kernel[k_ymin:k_ymax, k_xmin:k_xmax]

    def get_normalized(self, min_threshold: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
        """
        Normalize density map to uint8 [0, 255] and compute heat mask.
        :return: (normalized_density: np.ndarray, mask: np.ndarray)
        """
        max_val = np.max(self.density)
        if max_val <= 0.0:
            return (
                np.zeros((self.height, self.width), dtype=np.uint8),
                np.zeros((self.height, self.width), dtype=bool),
            )

        norm = self.density / max_val
        mask = norm >= min_threshold
        norm_uint8 = (norm * 255.0).astype(np.uint8)
        return norm_uint8, mask

    def get_colored_map(self, colormap: int | None = None) -> np.ndarray:
        """
        Render standalone false-color mapped heatmap image.
        :return: Colorized BGR image (H, W, 3)
        """
        cmap = colormap if colormap is not None else self.colormap
        norm_uint8, _ = self.get_normalized(min_threshold=0.0)
        return cv2.applyColorMap(norm_uint8, cmap)

    def draw(
        self,
        frame: np.ndarray,
        alpha: float = 0.5,
        colormap: int | None = None,
        min_threshold: float = 0.05,
    ) -> np.ndarray:
        """
        Render colormap overlay blended on top of video frame.

        :param frame: Video frame (H, W, 3) BGR
        :param alpha: Transparency blending weight (0.0 = only frame, 1.0 = only heatmap)
        :param colormap: OpenCV colormap enum
        :param min_threshold: Minimum normalized density threshold to display heat
        :return: Blended output frame
        """
        cmap = colormap if colormap is not None else self.colormap
        norm_uint8, mask = self.get_normalized(min_threshold=min_threshold)
        if not np.any(mask):
            return frame

        heat_bgr = cv2.applyColorMap(norm_uint8, cmap)
        # Alpha blend only in active heat mask regions to preserve clean background
        out_frame = frame.copy()
        mask_3ch = np.repeat(mask[:, :, np.newaxis], 3, axis=2)
        blended = cv2.addWeighted(out_frame, 1.0 - alpha, heat_bgr, alpha, 0)
        out_frame[mask_3ch] = blended[mask_3ch]
        return out_frame

    def export_image(
        self,
        filepath: str,
        frame: np.ndarray | None = None,
        alpha: float = 0.5,
        colormap: int | None = None,
    ) -> bool:
        """Save a snapshot of the heatmap (or blended on a background frame) to PNG/JPG."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        cmap = colormap if colormap is not None else self.colormap

        if frame is not None:
            rendered = self.draw(frame, alpha=alpha, colormap=cmap)
        else:
            norm_uint8, _ = self.get_normalized(min_threshold=0.0)
            rendered = cv2.applyColorMap(norm_uint8, cmap)

        return cv2.imwrite(filepath, rendered)

    def export_csv(self, filepath: str, grid_cells_x: int = 32, grid_cells_y: int = 24) -> bool:
        """Downsample the density array into an aggregated grid matrix and save to CSV."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        cell_w = self.width / float(grid_cells_x)
        cell_h = self.height / float(grid_cells_y)

        grid = np.zeros((grid_cells_y, grid_cells_x), dtype=np.float32)
        for gy in range(grid_cells_y):
            for gx in range(grid_cells_x):
                y0, y1 = int(gy * cell_h), int((gy + 1) * cell_h)
                x0, x1 = int(gx * cell_w), int((gx + 1) * cell_w)
                grid[gy, gx] = np.sum(self.density[y0:y1, x0:x1])

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["grid_y", "grid_x", "density_sum", "bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"])
            for gy in range(grid_cells_y):
                for gx in range(grid_cells_x):
                    writer.writerow([
                        gy,
                        gx,
                        round(float(grid[gy, gx]), 4),
                        int(gx * cell_w),
                        int(gy * cell_h),
                        int((gx + 1) * cell_w),
                        int((gy + 1) * cell_h),
                    ])
        return True

    def reset(self):
        """Clear density accumulation."""
        self.density.fill(0.0)

