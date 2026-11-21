# Step 2: P0 Runtime Stabilization & Pool-Scoped Ownership (`P0-1`..`P0-5`)

> **Parent Roadmap**: `.TODO/integration_hardening_master_roadmap.md` (`Step 2 of 4` | `--parent integration_hardening_master_roadmap --milestone 2`).
> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADR-01`, `ADR-02`, `ADR-03`, `ADR-06`, Section 6.1) & `AGENTS.md` (Sections 8, 12–15).
> **Pre-Flight Modularity Audit (`diagnose.py arch-map` & AST Budget Gate)**:
> - `dashboard/services/stream_worker.py` (`279L`, constrained `<= 285L` in `tests/test_step3_architecture_budgets.py`; `StreamWorker` at `12/12` methods)
> - `dashboard/services/camera_config_store.py` (`173L`, constrained `< 180L` & `<= 8` methods in `tests/test_dashboard_di.py`)
> - `dashboard/services/stream_pool_coordinator.py` (`224L`, constrained `< 240L` & `11/11` methods in `tests/test_dashboard_di.py`)
> - `dashboard/camera_pool.py` (`185L`, constrained `< 250L` & `10/10` methods in `tests/test_dashboard_di.py`)
> - `dashboard/services/processing_mode_service.py` (`216L`, constrained `<= 220L`; `ProcessingModeService` at `12/12` methods)
> - `dashboard/dependencies.py` (`345L`, `5L` headroom below `350L` soft warning)
> - `dashboard/services/frame_overlay.py` (`159L`; `FrameOverlayRenderer.render` is `134L` > `40L` function cap)
> - `dashboard/services/cached_replay_provider.py` (`143L`; `build_step_result` at `40/40L` cap)
> - `intelligent_tracker/matching/_gallery_signals.py` (`160L`; `emit_periodic_sighting` at `40/40L` cap)
> - `dashboard/services/camera_source_bootstrap.py` (`161L`; `bootstrap_camera_stream` at `40/40L` cap)
> - **Split-Before-You-Grow Rule**: Extract module-level helpers or sibling functions rather than adding methods to capped classes (`StreamWorker`, `ProcessingModeService`, `CameraPool`, `StreamPoolCoordinator`) and split `FrameOverlayRenderer.render` into `<= 40L` helpers.

---

## Milestone 1: Dual-Clock Domain Separation (`P0-1`), Non-Destructive `1280px` Coordinate Rescaling (`P0-3`) & Dynamic-Shape Heatmap Rendering (`P0-4`)

- [x] **dashboard/services/async_inference_worker.py** + **dashboard/services/stream_worker.py** + **dashboard/services/cached_replay_provider.py** + **dashboard/services/multiview/thumbnail_cache.py**: Separate `time.monotonic()` (strictly for `AnalyticsScheduler` windows, FPS pacing, `_last_encode_ts` rate gating, `inference_lag_ms` deltas, and cooldowns) from Unix wall-clock epoch `time.time()` (stamped into `FrameProcessor.step()`, `CachedReplayProvider.build_step_result()`, `evaluate_tracks_governance()`, `FrameStepResult.timestamp`, and `ThumbnailSlot.ts_ms` / `capture_ts_ms`), keeping `stream_worker.py <= 285L` (`<= 12` methods) and `CachedReplayProvider.build_step_result <= 40L`.
- [x] **intelligent_tracker/batch.py** + **intelligent_tracker/batch_reporting.py** + **intelligent_tracker/active_learning_triage.py** + **intelligent_tracker/matching/_gallery_signals.py** + **dashboard/services/video_analytics_service.py**: Pass `base_epoch + video_ts` (`start_wall_time + video_ts`) into `FrameProcessor.step()` during offline `VideoIndexer.process_video()` while propagating `video_filename` and `media_offset_sec = video_ts` into `db.add_sighting()`, `EventFTSIndex.index_sighting()`, `ActiveLearningTriage`, offline `EventBus` alert tagging (`_tag_and_collect`), and `frame_detections` occurrence records (`"time": round(video_ts, 3)` for Scrubber/replay lookup), keeping `emit_periodic_sighting <= 40L`.
- [x] **intelligent_tracker/pipeline/frame_processor.py**: Update `_rescale_tracks_and_detections()` to clone (`copy.copy`) and rescale returned `Track` and `Detection` instances (`bbox`, `centroid`, `velocity`) non-destructively so `CentroidTracker.tracks` retains internal inference-resolution coordinates across `1920x1080` -> `1280x720` frames (`P0-3`) while keeping `res.frame = processed`.
- [x] **dashboard/services/frame_overlay.py** + **intelligent_tracker/analytics/heatmap.py**: Decompose `FrameOverlayRenderer.render()` (`134L` -> `<= 40L` helpers) and replace non-existent `analytics.draw_heatmap_overlay(...)` with `analytics.heatmap.draw(annotated, alpha=0.55)` (`P0-4`); update `OccupancyHeatmap.draw()` to dynamically resize `norm_uint8` and `mask` to `(frame.shape[1], frame.shape[0])` when the target frame dimensions differ from `(self.height, self.width)`.
- [x] **.diagnostics/probes/replay_pipeline_probe.py** + **tests/test_step2_clock_and_coordinates.py** *(New)*: Update `_check_hd_scale_and_centroid` (using 4-int `MockDetector(preset_boxes=...)`) and `_check_overlay_heatmap` (seeding non-zero heatmap density before rendering `1280x720`) in `replay_pipeline_probe.py`, and add unit tests (`<= 40L`/method) verifying real-clock `AsyncInferenceWorker` epoch vs. monotonic separation, offline `VideoIndexer` `base_epoch + video_ts` + `media_offset_sec`, multi-frame `1920x1080` `CentroidTracker` ID stability, and cross-resolution `OccupancyHeatmap.draw()`.

---

## Milestone 2: Lock-Order Deadlock Elimination (`P0-2`), Pool-Scoped Singletons (`P0-5`) & `CameraConfigStore` Boot Hardening (`TRC-017`)

- [ ] **dashboard/services/processing_mode_service.py** + **dashboard/services/stream_recording.py**: Eliminate the `ProcessingModeService._lock` <-> `StreamRecordingController._lock` AB-BA deadlock (`P0-2`) by snapshotting service state under `ProcessingModeService._lock` and releasing it prior to `_build_camera_states(pool)`, and reading/updating `ProcessingModeService` outside `StreamRecordingController._lock`, keeping `processing_mode_service.py <= 220L` (`<= 12` methods).
- [ ] **dashboard/camera_pool.py** + **dashboard/services/stream_pool_coordinator.py** + **dashboard/services/camera_pool_queries.py** + **dashboard/services/camera_source_bootstrap.py** + **dashboard/routers/cameras.py** + **dashboard/routers/camera_recording.py** + **dashboard/routers/system.py** + **dashboard/services/camera_diagnostics.py** + **dashboard/services/roi_recognition_service.py** + **intelligent_tracker/lifecycle.py**: Guard all `pool.streams` iterations and lookups with a thread-safe snapshot under `pool._lock` (`P0-2`), preserving `< 240L` (`<= 11` methods) on `StreamPoolCoordinator` and `< 250L` (`<= 10` methods) on `CameraPool`.
- [ ] **dashboard/services/camera_config_store.py**: Harden `CameraConfigStore.load_cameras()` (`TRC-017`, `P0-5`) via a module-level payload normalizer that unwraps `{"cameras": [...]}` / `{"cameras": {...}}` wrappers and filters out non-dict or malformed entries while preserving intentional empty-camera test fixtures and keeping `camera_config_store.py < 180L` (`<= 8` methods).
- [ ] **intelligent_tracker/pipeline/bundle.py** + **intelligent_tracker/pipeline/engine.py** + **dashboard/services/pipeline_factory.py** + **dashboard/stream_manager.py** + **dashboard/camera_pool.py** + **dashboard/dependencies.py** + **dashboard/app.py**: Instantiate pool-scoped singletons for `EventBus`, `WorldGraph` (bound to the shared `EventBus`), `ConfidenceEngine`, and `EventFTSIndex` on `CameraPool`, inject them through `StreamPoolCoordinator` -> `StreamManager` -> `PipelineEngine.build()` and `bind_app_state()` (`app.state.world_graph`, `app.state.event_bus`, `app.state.confidence_engine`, `app.state.event_fts_index`), and guard `PipelineBundle.close()` / `StreamManager.stop()` so single-stream stops do not tear down pool-owned singletons (`P0-5`), keeping `dependencies.py < 350L`.
- [ ] **.diagnostics/probes/cold_boot_world_probe.py** + **tests/test_step2_pool_singletons_and_locks.py** *(New)*: Upgrade `_check_restart_and_lock_order` in `cold_boot_world_probe.py` to concurrently stress `ProcessingModeService.get_state(pool)` against `StreamRecordingController` lifecycle calls, verify `cold_boot_world_probe` passes 100% **Green**, and add unit tests (`<= 40L`/method) covering AB-BA lock stress, `pool.streams` thread safety, `TRC-017` `cameras.json` payload variants, and pool-scoped singletons across camera restarts.
- [ ] **CHANGELOG.md**: Record milestone completion via `'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'`.

---

## Scenario Combinations Matrix

| Scenario / Objective | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Milestone 1 Targeted Unit Tests** | Headless unittest (`P0-1`, `P0-3`, `P0-4`) | `tests.test_step2_clock_and_coordinates` | `python skills/system-diagnostics/scripts/diagnose.py tests tests.test_step2_clock_and_coordinates tests.test_pipeline_parity tests.test_analytics_scheduler` |
| **Milestone 1 Replay & Clock Probe** | Unmocked workspace probe | `replay_pipeline_probe` | `python skills/system-diagnostics/scripts/diagnose.py probe run replay_pipeline_probe` |
| **Milestone 2 Targeted Unit Tests** | Headless unittest (`P0-2`, `P0-5`, `TRC-017`) | `tests.test_step2_pool_singletons_and_locks` | `python skills/system-diagnostics/scripts/diagnose.py tests tests.test_step2_pool_singletons_and_locks tests.test_dashboard_di tests.test_step3_architecture_budgets` |
| **Milestone 2 Cold Boot & Deadlock Probe** | Unmocked workspace probe | `cold_boot_world_probe` | `python skills/system-diagnostics/scripts/diagnose.py probe run cold_boot_world_probe` |
| **Modularity, Scan & Typecheck Gate** | Static & budget verification | `--max-lines 350 --max-fn-lines 40 --typecheck` | `python skills/system-diagnostics/scripts/diagnose.py audit --path intelligent_tracker dashboard --max-lines 350 --max-fn-lines 40 --typecheck; python skills/system-diagnostics/scripts/diagnose.py scan --path intelligent_tracker dashboard --strict` |
| **Full Product Regression Suite** | All unit & integration tests | `MPLBACKEND=Agg` | `MPLBACKEND=Agg python -m unittest discover tests` |
