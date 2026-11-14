---
trigger: model_decision
description: Apply when editing camera source selection, pipeline overrides (where camera index 0 may be passed), CameraConfigStore, TrackerDB signature queries, /stream/{camera_id} endpoints, UnifiedCanvasOverlay / scrubber canvas overlays, or RoiRecognitionService / EntityTaggerService / /api/tag/* endpoints.
---

# Pipeline, Camera Config & DB Invariants

- **Camera Index `0` Falsy Trap**: Never use truthy `or` fallbacks for camera/source overrides (e.g., `source_override or default`), because integer webcam index `0` evaluates to `False` in Python. Always use explicit `is not None` checks (`source_override if source_override is not None else ...`).
- **`CameraConfigStore` Healing & Budget**:
  - Persist healed camera configs in `load_cameras()` only when `configs_loaded` is `True` so seeded defaults do not trigger redundant disk writes.
  - Keep `dashboard/services/camera_config_store.py` strictly under 180 lines as enforced by `tests/test_dashboard_di.py`.
- **`TrackerDB` Signature API**: `TrackerDB` exposes `get_signatures()` (not `get_all_signatures()`) and returns deserialized numpy embeddings directly.
- **Verification**: Check existing strict fallback tests (`tests/test_pipeline_config.py`) when splitting synthetic vs live-source detector error handling, and run `tests/test_dashboard_di.py` plus `python -m unittest discover tests` after modifying `CameraConfigStore` or DI services.
- **Clean vs. Annotated Stream Contract (`?annotated=false|true`)**: Preserve `annotated: bool = True` as the default on `GET /stream/{camera_id}` and `StreamManager.get_latest_frame_jpeg()` so `2x2`/`3x3` multi-grid tiles and external snapshot callers remain backward-compatible; pass `?annotated=false` explicitly on `#live`'s primary interactive viewport so freeze-frame ROI crops remain free of burned-in pixels.
- **HiDPI `<canvas>` Hit-Testing & Scrubber Toolbar Selector Isolation**:
  - When scaling an overlay `<canvas>` via `UnifiedCanvasOverlay.syncCanvasDpr(dpr)`, hover hit-testing and tooltip placement MUST divide by CSS layout dimensions (`canvas.style.width` / `canvas.style.height` or `getBoundingClientRect()`), never backing-store pixel dimensions (`canvas.width` / `canvas.height`).
  - In `#scrubber-overlay-layers`, use `.overlay-feature-pill` for feature visibility toggles (`BBoxes`, `IDs`, `Dwell`, `Velocity`, `Zones`, `Tripwires`) and reserve `.overlay-layer-chip` exclusively for analysis run layer chips.
- **Streaming Unit Test Isolation**: Always isolate or mock `get_shutdown_event()` in streaming generator tests (`_stream_frame_generator`) so shutdown event state never leaks across test files during full `python -m unittest discover tests` runs.
- **ROI Tagging & Crop/Video Isolation**: Reuse `EntityTaggerService._compute_deterministic_embedding` and `EntityTaggerService._extract_bounded_crop` in tagging/recognition services instead of duplicating OpenCV clamping or Re-ID fallback logic, and always accept injectable `crops_dir` / `videos_dir` (defaulting to `data/crops` and `data/videos`). In FastAPI `/api/tag/*` `TestClient` tests (including real `GalleryMatcher` E2E tests), isolate both directories with `tempfile.TemporaryDirectory()` and patch `dashboard.routers.tagging.VIDEOS_DIR` and `dashboard.routers.tagging.CROPS_DIR`.
- **Interactive Overlay Canvas `pointer-events` & HTML Partial Budgets**: When attaching pointer/ROI handlers to an overlay `<canvas>` (e.g., `#interactive-canvas`, `#scrubber-overlay-canvas`), verify its CSS sets `pointer-events: auto` (not `none`). After editing `dashboard/static/index.html` or `dashboard/static/partials/**/*.html`, run `tests/test_step3_architecture_budgets.py` alongside `diagnose.py audit` to catch HTML shell/partial line-budget overruns immediately.
- **Video Run Migration & Scoped `TrackerDB` Test Isolation**:
  - Legacy `sightings` migration tests must include a `timestamp` column because `SchemaManager._init_indexes` creates `idx_sightings_entity_ts`.
  - When tests monkeypatch `video_report_store.REPORTS_DIR`, `_resolve_db` must open a scoped `TrackerDB` in `os.path.dirname(REPORTS_DIR)` and close it in `finally` to avoid Windows SQLite file locks and `data/tracker.db` leakage.
- **`StreamRecordingController` Circular Import & Windows Handle Cleanup**:
  - `StreamRecordingController` must import `save_report_run` lazily inside `_persist_live_capture_run` to avoid circular imports with `dashboard.dependencies -> StreamManager`.
  - `StreamManager` tests must register `mgr.stop` in `addCleanup` to release SQLite handles on Windows.
- **FastAPI Response Schema Parity**: When adding controller/service return fields (e.g., `report_run_id`), explicitly declare them on the corresponding Pydantic `response_model` schema (`CameraRecordStatusResponse`) so FastAPI serialization does not strip them.
