#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Helper builders extracted from dashboard.dependencies to keep DI facade under 350L."""

import os
from typing import Any, Optional

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.enrollment import UniversalEnrollmentManager
from intelligent_tracker.memory import ConfidenceEngine, GeminiSemanticProvider, WorldQueryEngine


def _build_fallback_enrollment_mgr(db: TrackerDB, mgr: Any = None) -> UniversalEnrollmentManager:
    """Build a fallback UniversalEnrollmentManager using the canonical ReidProfile SSOT."""
    from intelligent_tracker.reid.factory import ReIDExtractorFactory
    from intelligent_tracker.reid.profile import resolve_reid_profile

    model_name = resolve_reid_profile(getattr(mgr, "cfg", None)).model_name or "dual"
    ext = ReIDExtractorFactory.create(model_name)
    return UniversalEnrollmentManager(db=db, extractor=ext)


def _build_world_query_engine(
    db: TrackerDB,
    *,
    state_confidence_engine: Optional[ConfidenceEngine] = None,
    pool: Any = None,
    mgr: Any = None,
    scen_mgr: Any = None,
) -> WorldQueryEngine:
    """Build a WorldQueryEngine wired to active ConfidenceEngine, WorldGraph, and optional provider."""
    conf_engine = (
        state_confidence_engine
        or getattr(pool, "confidence_engine", None)
        or getattr(mgr, "confidence_engine", None)
        or ConfidenceEngine(db=db)
    )
    world_graph = (
        getattr(pool, "world_graph", None)
        or getattr(scen_mgr, "world_graph", None)
        or getattr(mgr, "world_graph", None)
    )
    provider = GeminiSemanticProvider() if os.getenv("WORLD_QUERY_PROVIDER", "").strip().lower() == "gemini" else None
    return WorldQueryEngine(db=db, confidence_engine=conf_engine, world_graph=world_graph, provider=provider)
