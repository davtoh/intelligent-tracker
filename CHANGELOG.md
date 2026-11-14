# Changelog

## [2026-11-14] docs: Step 6 Milestone 3: Sphinx Docs Sync, Dead Import Cleanup & Packaging Polish
- **Type**: docs
- **Summary**: Updated Sphinx docs for pipeline/world/memory/cli/recording/models APIs, synced README.rst and pyproject.toml readme field, removed 28 unused imports across 21 modules while preserving availability probes, and verified 541/541 tests + Sphinx -W build.
- **Files** (31):
  - `README.rst`
  - `dashboard/routers/videos.py`
  - `dashboard/services/frame_overlay.py`
  - `dashboard/services/shutdown_handler.py`
  - `documentation/dashboard.rst`
  - `documentation/deployment.rst`
  - `documentation/index.rst`
  - `documentation/intelligent_tracker.rst`
  - ... (+23 more)
- **Verification**: python -m unittest discover tests && python -m sphinx -a -W --keep-going documentation/ documentation/_build/html/

## [2026-11-14] feat: Step 6 Milestone 2: CLI Benchmarking, Model Verification & WorldGraph Parity
- **Type**: feat
- **Summary**: Added BenchmarkCollector (--benchmark/--benchmark-output/--check-models), GET/POST /api/system/models*, GET /api/world/snapshot|entities, and intelligent-tracker-ctl world|models subcommands.
- **Files** (12):
  - `.TODO/step_6_cli_dashboard_operator_parity.md`
  - `dashboard/routers/system.py`
  - `dashboard/routers/world.py`
  - `intelligent_tracker/cli/__init__.py`
  - `intelligent_tracker/cli/arguments.py`
  - `intelligent_tracker/cli/ctl.py`
  - `intelligent_tracker/cli/pipeline_builder.py`
  - `intelligent_tracker/cli/runner.py`
  - ... (+4 more)
- **Verification**: python -m unittest tests/test_cli_operator_parity.py tests/test_cli_runner.py tests/test_cli_ask.py tests/test_world_query_api.py tests/test_entrypoints.py tests/test_modernization.py tests/test_camera_recording.py

## [2026-11-13] feat: Step 5 Milestone 4: World Query API, CLI ask Parity & Sphinx Docs
- **Type**: feat
- **Summary**: Added /api/world/query, /api/world/confidence/{entity_id}, /api/world/timeline FastAPI routes, get_world_query_engine DI, intelligent-tracker ask and intelligent-tracker-ctl ask CLI parity, Sphinx documentation, and API/CLI parity tests.
- **Files** (14):
  - `dashboard/routers/world.py`
  - `dashboard/routers/__init__.py`
  - `dashboard/dependencies.py`
  - `dashboard/schemas.py`
  - `dashboard/app.py`
  - `intelligent_tracker/cli/ask.py`
  - `intelligent_tracker/cli/runner.py`
  - `intelligent_tracker/cli/ctl.py`
  - ... (+6 more)
- **Verification**: 522/522 unittest pass + Sphinx -W clean + arch-map compliant

## [2026-11-13] feat: Step 4 Milestone 4: Multi-Camera Handoff, FOV Deduplication & Tactical World Minimap
- **Type**: feat
- **Summary**: Implemented MultiCameraHandoffCoordinator, WorldTacticalMinimap, GET /api/topology/world-map, and golden two-camera handoff tests.
- **Files** (7):
  - `intelligent_tracker/world/handoff.py`
  - `intelligent_tracker/world/_handoff_helpers.py`
  - `intelligent_tracker/world/minimap.py`
  - `intelligent_tracker/world/_minimap_render.py`
  - `intelligent_tracker/world/__init__.py`
  - `dashboard/routers/topology.py`
  - `tests/test_multi_camera_handoff.py`
- **Verification**: 495/495 unittest pass + Sphinx -W clean + arch-map compliant

## [2026-11-13] refactor: Step 3 Milestone 4: index.html Partial Decomposition & Step 3 Sign-Off
- **Type**: refactor
- **Summary**: Decomposed dashboard/static/index.html into 9 tab partials and 4 modal partials rendered via Jinja2 on GET /, and added Step 3 architecture budget verification tests.
- **Files** (4):
  - `dashboard/app.py`
  - `dashboard/static/index.html`
  - `dashboard/static/partials/`
  - `tests/test_step3_architecture_budgets.py`
- **Verification**: python -m unittest discover tests (471 passed)

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
