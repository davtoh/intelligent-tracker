#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Retail & Occupancy Analytics Engine.

Provides:

- ``OccupancyHeatmap``: Real-time 2D spatial density accumulation with Gaussian
  dispersion, temporal decay, false-color overlay, and PNG/CSV exports.
- ``AnalyticsEngine``: Orchestrates multi-zone occupancy, tripwire crossing
  tallies, dwell times, event logging, and telemetry reporting.
"""

from intelligent_tracker.analytics.engine import AnalyticsEngine
from intelligent_tracker.analytics.heatmap import OccupancyHeatmap

__all__ = ["OccupancyHeatmap", "AnalyticsEngine"]

