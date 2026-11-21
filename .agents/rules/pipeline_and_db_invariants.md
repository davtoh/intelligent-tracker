---
trigger: model_decision
description: Apply when editing intelligent_tracker/ pipeline, world, memory, database, repositories, batch/VideoIndexer, VideoSource, CaptureReadGuard, gallery/matching, rsac, or dashboard/ services/routers (CameraPool, StreamManager, StreamWorker, AsyncInferenceWorker, ProcessingModeService, AnalyticsScheduler, CachedReplayProvider, StreamRecordingController, CameraConfigStore, EntityTaggerService, video_report_store).
---

# Backend Pipeline, Scheduler, Camera Pool & DB Invariants

## 1. Dual-Clock Domain, Scheduler & Replay Invariants
- **Dual-Clock Domain Boundary (`P0-1`)**: Keep `time.monotonic()` strictly for `AnalyticsScheduler`, `ProcessingModeService`, `AsyncInferenceWorker` cadence, FPS pacing, lag deltas, and cooldowns; always pass Unix wall-clock epoch `time.time()` (or `base_epoch + video_ts` + `media_offset_sec` in offline `VideoIndexer`) into `FrameProcessor.step()`, `RSACSchedule`, `TrackerDB`, `EventFTSIndex`, `ConfidenceEngine`, `EventBus` alerts, and `ThumbnailCache.capture_ts_ms`.
- **Dual-Clock `_wall_now()` Helper Pattern**: When a module bridges `time.monotonic()` scheduler/cooldown windows and Unix wall-clock epoch timestamps (`time.time()`), isolate wall-clock acquisition in a dedicated `_wall_now()` helper so static AST clock-domain checks (`MIXED_CLOCK_DOMAIN`) remain unambiguous.
- **Debounce & Wrapper Guards**: Initialize scheduler debounce/cooldown timestamps (`last_shed_notify_at`, `_last_refinement_at`, `ActiveLearningTriage` `last=None`) to `None` rather than `0.0` so small monotonic or `timestamp=0.0` offline frames are never suppressed. Preserve backward-compatible positional defaults (or inspect `inspect.signature`) when extending worker wrapper signatures.
- **Armed `is_armed` Default & P1 Scheduling**: `ProcessingModeService.should_run_vision_step(camera_id, is_recording=False, is_armed=False)` MUST keep `is_armed=False` as default for legacy invariant tests while scheduling `is_armed=True` cameras at `P1` (`1.0 FPS` idle floor -> `8.0 FPS` motion burst, `15.0 s` P1->P0 alarm hold) even in `focus_only`.
- **Zero-GPU `CachedReplayProvider` & Post-Detection Governance**: Pre-indexed `video_file` cameras bypass `AnalyticsScheduler` GPU slots (`priority_tier="REPLAY"`) while running live `evaluate_tracks_governance()` (`intelligent_tracker/pipeline/post_detection_governance.py`) and resetting zone/tripwire state on video-loop wrap-around; unindexed `video_file` cameras fall back to standard P0/P1/P2 scheduling.
- **Standalone `StreamManager` Hibernation (`focus_only`)**: `ProcessingModeService.should_hibernate_camera()` must return `True` when `not in_camera_pool` and `subscriber_count <= 0` in `focus_only` mode; in `StreamWorker._should_hibernate()`, distinguish `frame_count` from `subscriber_count`.

## 2. Pool-Scoped Singletons, Lock Order & Camera Config
- **Pool-Scoped Singletons (`P0-5`)**: Share one `EventBus`, `WorldGraph`, `ConfidenceEngine`, and `EventFTSIndex` across `CameraPool`, all `StreamManager` instances, and `app.state`; preserve `CameraNode` homography/pose and `ScenarioManager` overlays on camera restarts.
- **Lock-Order Invariant (`P0-2`)**: Never nest `ProcessingModeService._lock` and `StreamRecordingController._lock` (eliminate AB-BA cycles by querying state outside locks), and always snapshot `list(pool.streams.items())` under `pool._lock`.
- **Lazy DI Imports**: Import `get_processing_mode_service` lazily inside `StreamManager.__init__` and `StreamPoolCoordinator.__init__` (and import `save_report_run` lazily inside `StreamRecordingController._persist_live_capture_run`) to avoid circular imports with `dashboard.dependencies -> CameraPool -> StreamManager`. Inject `mode_service_getter` into `StreamRecordingController`.
- **Camera Index `0` Falsy Trap**: Never use truthy `or` fallbacks for camera/source overrides (`source_override or default`), because integer webcam index `0` evaluates to `False`. Always use `source_override if source_override is not None else ...`.
- **`CameraConfigStore` Healing & Budget**: Persist healed camera configs in `load_cameras()` only when `configs_loaded` is `True` (validating dict entries per `TRC-017`). Keep `dashboard/services/camera_config_store.py < 180` lines (`tests/test_dashboard_di.py`).
- **Synthetic MP4 Probe Sources**: Always use synthetic temporary MP4 files (never hardware webcam index `0`) in isolated `CameraPool` probes and unit tests to avoid triggering Windows DirectShow/MSMF hardware locks and the 4s shutdown watchdog.

## 3. SQLite Repository, Signatures & Resource Teardown Invariants
- **SQLite Repository Rollback Invariant**: Every SQLite repository write method (`intelligent_tracker/repositories/*_repo.py`) MUST call `self._conn.rollback()` inside `except` blocks before re-raising or returning on `sqlite3.Error` / `IntegrityError`, so failed `INSERT`/`UPDATE` statements never leave an uncommitted transaction holding a write lock on the shared connection.
- **Deterministic SQLite & EventBus Teardown**: `StreamManager.stop()` and `PipelineBundle.close()` must close owned `TrackerDB` handles and stop both primary and fallback `EventBus` instances (which must call `.start()` on creation) to prevent Windows SQLite file locks. Guard `_conn is not None` across repository resolvers.
- **Key Domain Signatures**:
  - `PipelineConfig` uses `detector_confidence` and `detector_classes`.
  - `ScenarioManager` uses `config_path`, `save_zone`, and `save_tripwire`.
  - `TrackerDB` exposes `get_signatures()` (returns deserialized numpy embeddings), `set_rsac_rule(allowed_categories=...)`, `get_review_item(item_id)`, `add_entity()`, and `add_sighting()`.
  - `Track` instances without an identified entity must not define an unconditional `entity_id=None` attribute (`hasattr(trk, 'entity_id') == False`; use `getattr(self, 'entity_id', None)` in `to_dict()`).
  - Non-destructively clone/rescale `tracks` and `detections` outside `CentroidTracker` internal state (`P0-3`), and align `FrameOverlayRenderer` heatmap shape dynamically via `analytics.heatmap.draw()` (`P0-4`).
- **ROI Tagging & FastAPI Schema Parity**: Reuse `EntityTaggerService._compute_deterministic_embedding` and `_extract_bounded_crop` with injectable `crops_dir` / `videos_dir`. When adding controller return fields (e.g. `report_run_id`), declare them on Pydantic `response_model` schemas (`CameraRecordStatusResponse`). Offload sync SQLite/gallery calls in `async def` routes (`rsac.py`) via `asyncio.to_thread`.

## 4. Backend & Pipeline Unit Test Isolation Rules
- **Zero Unmocked `TestClient(app)` Lifespan**: Never enter `with TestClient(app) as client:` without mocking `lifespan` / `CameraPool` (`configs/cameras.json`), because live lifespan opens cameras and starts `ShutdownWatchdogGuard`. Reset FastAPI `app_module` overrides and `set_shutting_down(False)` in `setUp`/`addCleanup`. Mount static `/ws/multiview` before wildcard `/ws/{camera_id}`.
- **Temp `TrackerDB` & `CameraPool` Cleanup**: Always pass isolated `tempfile.TemporaryDirectory()` paths (`CameraPool(..., autostart=False)` with cameras marked `enabled=False`, `TrackerDB(db_path=...)`) and register `worker.stop()`, `mgr.stop()`, `pool.close()`, `db.close()` in `addCleanup()` in reverse creation order. When monkeypatching `video_report_store.REPORTS_DIR`, open a scoped `TrackerDB` in `os.path.dirname(REPORTS_DIR)` and close it in `finally`.
- **Async & Worker Test Sync**:
  - Wait on a `step_done` event before asserting `mock_proc.step.assert_called_once()` on async `StreamWorker`.
  - Construct `asyncio.Event()` inside the active `asyncio.run(...)` coroutine (Python 3.12+ loop binding).
  - `VideoSource._capture_worker` must set `self._ready_event.set()` in `finally`; default `warmup_timeout=None` (`read_timeout * 2.5`).
  - In `StreamWorker` tests, never pass `name=...` to `MagicMock(...)`, explicitly set `_processing_mode_service = None`, and seed `_latest_raw_jpeg` / `_latest_jpeg` when testing mode switching. Filter class-level `FrameProcessor.step` spies by `self.db`.
- **Enforced Backend Line Budgets**:
  - `intelligent_tracker/journey_segmenter.py < 160` lines (`tests/test_step4_preflight_budgets.py`)
  - `dashboard/services/camera_config_store.py < 180` lines (`tests/test_dashboard_di.py`)
  - `dashboard/services/processing_mode_service.py <= 220` lines
  - `dashboard/services/stream_pool_coordinator.py < 240` lines (`tests/test_dashboard_di.py`)
  - `dashboard/services/stream_worker.py <= 285` lines (`tests/test_step3_architecture_budgets.py`)
  - `StreamSubscriberRegistry <= 12` methods (store boolean flags like `is_hibernating` as plain attributes on the registry).
