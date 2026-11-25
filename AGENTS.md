# Intelligent Tracker - Agent Guidelines & Architecture Contract

This file defines repository-wide architecture invariants and execution standards for `intelligent_tracker` (kept strictly under `< 10 KB` so it is never truncated by the 24 KB rule limit). Detailed domain rules load on demand from `.agents/rules/`:
- **Backend, Pipeline, Scheduler & DB**: `.agents/rules/pipeline_and_db_invariants.md` (`trigger: model_decision`)
- **Frontend, Multiview & Node VM Tests**: `.agents/rules/frontend_and_multiview_invariants.md` (`trigger: model_decision`)
- **Cross-Project Ecosystem (`enterprise-website`)**: `.agents/rules/cross_project_ecosystem.md` (`trigger: model_decision`)

---

## 1. Authoritative Architecture & Module Placement ("Split-Before-You-Grow")
- **Blueprints**: Follow `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (Layers 1–5, ADRs 01–20), `docs/architecture/CURRENT_ARCHITECTURE.md`, `.TODO/reid_unification_traceability_and_studio_ux_master_roadmap.md`, and `.TODO/integration_seams_entity_persistence_master_roadmap.md`.
- **Dependency Direction**: Never put CV/domain pipeline logic inside `dashboard/` or `cli/`, and never let `intelligent_tracker/` import `dashboard/` or `scripts/`.
- **Live Modularity Audit**: Before planning or editing near-limit modules, run `diagnose.py arch-map --path .` and `diagnose.py audit --path <targets>` to inspect current line counts ($\le 350\text{L}$ soft / $500\text{L}$ hard), class method counts ($\le 12$), and function lengths ($\le 40\text{L}$).
- **Mandatory Placement for New Code**:
  1. **Web Routes & Services**: Place new routes in `dashboard/routers/<domain>.py` ($\le 15–25\text{L}$/route; never expand `rsac.py` `352L`) and logic in `dashboard/services/<domain>_service.py` (never expand `dashboard/app.py` or `dashboard/stream_manager.py`).
  2. **Database Queries**: Place new queries in `intelligent_tracker/repositories/<domain>_repo.py` ($\le 12$ methods/class) and compose via `TrackerDB` (never expand `intelligent_tracker/database.py`). Every write method (including `SignatureMixin`) MUST call `self._conn.rollback()` in `except` before re-raising.
  3. **Frontend JS & CSS**: Place new scripts in `dashboard/static/js/<feature>.js` (multiview under `dashboard/static/js/multiview/`) and styles in `dashboard/static/css/<component>.css` (never expand near-limit `studio.js` `349L`, `universal_enrollment.js` `345L`, `interactive_canvas.js` `239L`, `entity_modals.html` `237L`, `camera_modals.html` `238L`, `app.js`, or `styles.css`). Reuse `OverlayControlBar`, `UnifiedCanvasOverlay`, and `MediaEmptyState`; **ask before creating any new overlapping UI component**.
  4. **Responsive Overlay & Script Order**: Never pin inline `style.width/height` on responsive multiview overlay canvases without a `ResizeObserver`; never clear active `RoiDrawTagger` drag overlays on `mousemove`/telemetry; keep `nav_tabs_manager.js` loaded *after* `app.js`.

---

## 2. Python 3.12+ Modernization & Domain Comment Preservation
- **Modern Python 3.10–3.12+ Only**: Zero `from __future__ import ...` (enforced by `tests/test_modernization.py`), zero `six`/`future`/`past` shims, native `class Foo:`, `raise ... from err`, and `collections.abc`.
- **Preserve Domain Math & Reference Comments**: Never delete computer vision docstrings, OpenCV matrix/homography equations, Kalman/IoU formulas, or reference URLs.

---

## 3. Core Runtime, Concurrency & Dual-Clock Invariants
- **Dual-Clock Domain Boundary (`P0-1`)**: Use `time.monotonic()` strictly for `AnalyticsScheduler`, `ProcessingModeService`, FPS pacing, lag deltas, and cooldowns (isolating wall-clock calls in `_wall_now()` helpers when bridging domains); pass Unix epoch `time.time()` (or `base_epoch + video_ts` + `media_offset_sec` in `VideoIndexer`) into `FrameProcessor.step()`, `RSACSchedule`, `TrackerDB`, `EventFTSIndex`, `ConfidenceEngine`, `EventBus`, and `ThumbnailCache.capture_ts_ms`.
- **Pool-Scoped Singletons, App DB & Lock Order (`P0-2`, `P0-5`)**: Share one `EventBus`, `WorldGraph`, `ConfidenceEngine`, and `EventFTSIndex` across `CameraPool`, `StreamManager`, `create_video_indexer()`, and `app.state`. Keep `app.state.db` independent of individual `StreamManager`/`PipelineBundle` teardown. Never nest `ProcessingModeService._lock`/`StreamRecordingController._lock` or `CameraPool._lock`/`CameraHealthManager._lock`, and never hold locks across blocking SQLite/JSON I/O or `thread.join()`.
- **Canonical `DualModel` Re-ID, Feedback & Sighting Crops (`ADR-10`)**: Keep Enrollment, live pipelines (`probe_db_reid=True`), `VideoIndexer`, and `RoiRecognitionService` (`"onnx"`/`DualModel`, never `"osnet"`) on compatible `DualModel` embeddings; invalidate `video_runs.frame_detections_json`, `CachedReplayProvider`, `OverlayLayers.streamCache`, and pool galleries (`reload_all_galleries`) on entity mutations. Save throttled auto-sighting crops (with entity avatar fallback); ensure `ConfidenceEngine.record_human_feedback()` accepts `"reject"` and `camera_id`/`zone_id`.
- **Category SSOT, Real Unread Alerts & Opt-In Demo (`ADR-11`, `ADR-12`, `ADR-14`)**: Unify categories on `custom_categories` (`/api/rsac/categories`); drive alert badges and `/events` strictly from SQLite `is_read` state (write-through `EventBus`, never bus-shadows-DB); load `configs/alert_demo.yaml` only via `--demo` / `IT_LOAD_DEMO_SCENARIOS=1`.
- **Effective Config, `ReidProfile` & `SourceRef` Seams (`ADRs 13, 15, 16, 20`)**: Deep-merge camera configs over `default.yaml` (explicit `null` clears `classes`); resolve `DualModel` via one `ReidProfile` SSOT (warn + surface mismatched dims instead of silent skip); route all cross-tab jumps via `App.navigate(tab, SourceRef)`; persist `sightings.camera_id`/`run_id` with enrollment seeds and relabel backfills; require workspace probes to pass outright (never `INFRA_UNAVAILABLE`) for sign-off.
- **No `primary_stream` Aliasing & No ROI Double-Crop**: Never fall back to `primary_stream` when an explicit `camera_id` is requested in `/stream/{id}`, `/ws/{id}`, or `/freeze_frame` — return explicit offline/error status. `RoiRecognitionService.extract_roi_crop()` must never apply full-frame `bbox` coordinates to an already-cropped `crop_base64` payload.
- **Interruptible Sleeps & Two-Pass Teardown**: Always use `self._stop_event.wait(timeout=delay)` (never `time.sleep()`), broadcast `signal_stop()` across workers before parallel joining, and close owned `TrackerDB` + `EventBus` instances in `StreamManager.stop()` / `PipelineBundle.close()`.

---

## 4. Testing, Verification & Documentation Standards (OS-Agnostic)
- **Virtualenv & Timeout Guard**: Always execute tests and diagnostics via `.venv\Scripts\python.exe` (Windows) or `.venv/bin/python` (POSIX) using `diagnose.py tests` (`180s` timeout guard) and full suite sign-off (`MPLBACKEND=Agg python -m unittest discover tests`).
- **Strict Test Isolation & Lightweight Fixtures**:
  - Never touch live `configs/cameras.json`, `data/*.db`, or `data/reports/`; inject `tempfile.TemporaryDirectory()` and register reverse-order `addCleanup()` teardown (`worker.stop()`, `pool.close()`, `db.close()`).
  - Never run full-video YOLO inference, unmocked `TestClient(app)` lifespans, or hardware camera index `0` in automated tests/probes; use `detector=mock`, `sample_rate=10`, and synthetic 5–10 frame MP4 fixtures.
  - Kill any background test servers (`manage_task kill`) and cancel active test video jobs before ending a turn.
- **Documentation & Changelog**: Keep Sphinx builds warning-free (`python -m sphinx -W --keep-going documentation/ documentation/_build/html/`), record milestones via `diagnose.py changelog add` (never `MIGRATION_LOG.md`), and never commit `file:///` URIs, local absolute paths, or hardcoded `localhost` URLs.
- **UI & Test Helpers**: Keep `dashboard/routers/topology.py` under `240L`; pass `showFeaturePills=true` to `OverlayControlBar.renderScrubberBar` when `descriptors=[]` in modal previews; use a `ConnProxy` in tests for C-level read-only `sqlite3.Connection.rollback`.
