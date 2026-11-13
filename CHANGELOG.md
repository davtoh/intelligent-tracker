# Changelog

## [2026-11-13] feat: Step 2 Milestone 4: Dead Import Cleanup, Legacy Compatibility & Final Sign-Off
- **Type**: feat
- **Summary**: Removed dead high_objects/unused imports from scenarios.py and topology.py, added optional WorldGraph sync hooks in ScenarioManager, documented legacy compatibility boundaries in spaces.py and high_objects.py, guarded closed DB fallback in video_analytics_service.py, and verified all 450 unit/integration tests and Sphinx docs build.
- **Files** (8):
  - `dashboard/app.py`
  - `dashboard/services/video_analytics_service.py`
  - `intelligent_tracker/core/spaces.py`
  - `intelligent_tracker/high_objects.py`
  - `intelligent_tracker/scenarios.py`
  - `intelligent_tracker/topology.py`
  - `tests/test_scenario_api.py`
  - `tests/test_world_legacy_compat.py`
- **Verification**: python -m unittest discover tests

## [2026-11-13] feat: Step 1 Milestone 4: pyproject.toml & Package Entrypoints
- **Type**: feat
- **Summary**: Extracted intelligent_tracker/cli/ctl.py and dashboard/server.py from scripts/, converted scripts/stream_ctl.py and scripts/run_dashboard.py to thin wrappers, added PEP 621 pyproject.toml with console_scripts, and added tests/test_entrypoints.py.
- **Files** (7):
  - `intelligent_tracker/cli/ctl.py`
  - `scripts/stream_ctl.py`
  - `dashboard/server.py`
  - `scripts/run_dashboard.py`
  - `pyproject.toml`
  - `tests/test_entrypoints.py`
  - `tests/test_pipeline_config.py`
- **Verification**: 427/427 unit tests passed (unittest discover tests); arch-map verified zero new modularity warnings

## [2026-11-12] feat: CaptureReadGuard Concurrency & COM Hardening
- **Type**: feat
- **Summary**: Hardened VideoSource and CameraPool against Windows COM DirectShow deadlocks and race conditions. Initialized COM on reader and safe driver unbind worker threads, removed unguarded reads during video looping, and made CameraPool remove_camera and update_camera lock-free during stream teardown.
- **Files** (4):
  - `intelligent_tracker/video/capture_guard.py`
  - `intelligent_tracker/video/capture_worker.py`
  - `dashboard/camera_pool.py`
  - `tests/test_capture_circuit_breaker.py`
- **Verification**: Ran 409 tests in 50.7s: 100% passed

## [2026-11-11] feat: Milestone 3: Layer-Isolated Scaling & Policy-Governed Scrubber Timeline Persistence
- **Type**: feat
- **Summary**: Removed primary-layer sourceResolution cross-contamination in ScrubberOverlay.render(), extracted ScrubberPlaybackState & ScrubberLibraryBridge to keep VideoScrubber modular (<390L), persisted per-stem playback timestamps across original/_h264 pairs & recordings honoring #scrubber-tab-policy, and verified 372/372 unit tests plus headless CDP.
- **Files** (6):
  - `dashboard/static/js/scrubber_overlay.js`
  - `dashboard/static/js/scrubber_playback_state.js`
  - `dashboard/static/js/scrubber_library_bridge.js`
  - `dashboard/static/video_scrubber.js`
  - `dashboard/static/index.html`
  - `tests/test_scrubber_ux_fixes.py`
- **Verification**: MPLBACKEND=Agg python -m unittest discover tests (372 passed); headless CDP audit passed (0 warnings, 3 concurrent layers, slider persistence across keep-paused/auto-resume/reset)

## [2026-11-11] test: Video Studio Automated Verification & Multi-Layer JS Runtime Suite
- **Type**: test
- **Summary**: Added Node VM runtime tests for 2688x1520 vs 1920x1086 resolution-aware overlay scaling, reactive parent/_h264 cache invalidation, concurrent multi-layer compositing, and paired H.264 UI switching; split progressive stream and unified report store tests under modularity budgets and synced documentation/vms.rst.
- **Files** (4):
  - `documentation/vms.rst`
  - `tests/test_video_pairing_and_layers.py`
  - `tests/test_progressive_stream.py`
  - `tests/test_video_report_store.py`
- **Verification**: python -m unittest discover tests (352 passed); python -m sphinx -W --keep-going documentation/ documentation/_build/html/ (0 warnings)

## [2026-11-11] feat: Reactive Cache Invalidation & Progressive Detection Streaming (M2)
- **Type**: feat
- **Summary**: Purged stale parent and _h264 client report cache aliases on job-finished in video_batch.js; added progressive 30-frame chunk flush callback in VideoIndexer.process_video, thread-safe progressive_stream_store.py buffer, GET /api/videos/{filename}/jobs/{job_id}/stream endpoint with incremental ?since= slicing and alias/persisted fallback, and live ScrubberOverlay progressive polling during active analytics.
- **Files** (8):
  - `intelligent_tracker/batch.py`
  - `dashboard/services/progressive_stream_store.py`
  - `dashboard/services/video_report_store.py`
  - `dashboard/routers/video_jobs.py`
  - `dashboard/static/js/video_batch.js`
  - `dashboard/static/js/scrubber_overlay.js`
  - `documentation/vms.rst`
  - `tests/test_video_pairing_and_layers.py`
- **Verification**: unittest discover tests (348 OK); Milestone 2 suites (26 OK via plan_engine verify); sphinx -W --keep-going (0 warnings); headless diagnose.py ui live browser audit OK

## [2026-11-11] feat: Video Pairing, Idempotent Transcode & Resolution-Aware Overlay (M1)
- **Type**: feat
- **Summary**: Added H.264 pair detection in /api/videos, idempotent /transcode with force flag, unified _h264/base report and detection storage, container PTS + source_resolution propagation in BatchAnalyzer and VideoReportStore, Switch/Re-convert library and codec notice UI controls, and letterbox/pillarbox-compensated source_resolution overlay scaling.
- **Files** (13):
  - `intelligent_tracker/batch.py`
  - `dashboard/services/video_transcoder.py`
  - `dashboard/services/video_report_store.py`
  - `dashboard/routers/videos.py`
  - `dashboard/routers/video_jobs.py`
  - `dashboard/static/js/scrubber_overlay.js`
  - `dashboard/static/js/video_jobs.js`
  - `dashboard/static/js/video_library.js`
  - ... (+5 more)
- **Verification**: unittest discover tests (344 OK); Milestone 1 suites (22 OK via plan_engine verify); sphinx -W --keep-going (0 warnings); headless diagnose.py ui audit OK

## [2026-11-10] feat: Video Studio SOTA Analytics, Canvas Overlay & Stacked Persistence Architecture
- **Type**: feat
- **Summary**: Implemented disk-backed stacked report history (`data/reports/{video}_reports.json`) and per-frame detection streaming (`data/reports/{video}_{run_id}_detections.json`). Separated raw detected objects (`total_detections`) from enrolled gallery sightings (`identifications_count`). Added synchronized real-time canvas bounding box overlay (`#scrubber-overlay-canvas`) over Scrubber player. Hardened `.video-file-card` selection, history run switcher dropdown, and active job container isolation.
- **Files** (8):
  - `intelligent_tracker/batch.py`
  - `dashboard/routers/video_jobs.py`
  - `dashboard/services/video_report_store.py`
  - `dashboard/static/js/scrubber_overlay.js`
  - `dashboard/static/js/video_batch.js`
  - `dashboard/static/js/video_library.js`
  - `dashboard/static/video_scrubber.js`
  - `tests/test_video_jobs.py`
- **Verification**: 337/337 tests pass (36.96s); 15/15 dedicated video jobs tests pass (1.09s); 0 warnings Sphinx HTML documentation build

## [2026-11-10] feat: Video Job Concurrency, Progress Engine & Interactive Cancellation (Milestone 17)
- **Type**: feat
- **Summary**: Implemented thread-safe VideoJobManager coordinator with BoundedSemaphore(2), per-video mutual exclusion, joinable cancellation, and job polling. Decoupled async job router into video_jobs.py. Added VideoJobClient frontend coordinator with animated progress bars, background task pills, and interactive 409 conflict modal. Added 12 unit and integration tests.
- **Files** (13):
  - `dashboard/routers/videos.py`
  - `dashboard/schemas.py`
  - `dashboard/services/video_jobs_service.py`
  - `dashboard/services/video_transcoder.py`
  - `dashboard/static/index.html`
  - `dashboard/static/js/video_batch.js`
  - `dashboard/static/js/video_jobs.js`
  - `dashboard/static/js/video_library.js`
  - ... (+5 more)
- **Verification**: 334/334 tests pass (37.2s); 12/12 dedicated video jobs tests pass (0.89s); 0 warnings Sphinx docs build

## [2026-11-09] feat: System Capabilities API & Camera AI Configuration Modal (Milestone 2)
- **Type**: feat
- **Summary**: Implemented dynamic AI capabilities discovery endpoint (`/api/system/capabilities`) exposing detectors, trackers, Re-ID extractors, and COCO classes. Extended the VMS camera modal with an AI Detector & Tracking Intelligence section, bidirectional confidence slider/numeric inputs, class filter presets, and quick physical webcam presets. Normalized SortTracker and CentroidTracker kwargs (`max_age` / `max_disappeared`).
- **Files** (8):
  - `dashboard/routers/system.py`
  - `dashboard/camera_pool.py`
  - `dashboard/services/pipeline_factory.py`
  - `intelligent_tracker/tracker/sort.py`
  - `dashboard/static/css/camera_ai_config.css`
  - `dashboard/static/js/camera_ai_config.js`
  - `dashboard/static/camera_manager.js`
  - `dashboard/static/index.html`
  - `tests/test_camera_detector_config.py`
- **Verification**: 317/317 tests pass (36.71s); 0 warnings Sphinx HTML build.

## [2026-11-09] feat: Dynamic Detector & Pipeline Configuration (Milestone 1)
- **Type**: feat
- **Summary**: Implemented dynamic Edge AI detector selection, confidence thresholds, and class filtering contracts across Pydantic schemas, CameraPool orchestrator, StreamPipelineFactory, and VideoRouter. Fixed broken VideoIndexer offline batch occurrence analytics import and parameterized feed promotion.
- **Files** (7):
  - `dashboard/schemas.py`
  - `dashboard/camera_pool.py`
  - `dashboard/routers/cameras.py`
  - `dashboard/routers/videos.py`
  - `dashboard/services/pipeline_factory.py`
  - `intelligent_tracker/batch.py`
  - `tests/test_camera_detector_config.py`
- **Verification**: 315/315 tests pass (36.01s); Sphinx HTML build succeeds with 0 warnings.
