# Changelog

## [2026-11-14] feat: Step 2 M4: #videos Scrubber Overlay Parity & Budget Reduction
- **Type**: feat
- **Summary**: Delegated ScrubberOverlay, ScrubberOverlayRenderer, and OverlayLayers to UnifiedCanvasOverlay, added 6 feature toggle pills to OverlayLayerToolbar, and reduced scrubber_overlay.js (326L) and overlay_layers.js (338L) under 350L.
- **Files** (8):
  - `dashboard/static/css/scrubber_overlays.css`
  - `dashboard/static/js/overlay_layer_toolbar.js`
  - `dashboard/static/js/overlay_layers.js`
  - `dashboard/static/js/scrubber_overlay.js`
  - `dashboard/static/js/scrubber_overlay_renderer.js`
  - `tests/test_step1_demo_mode_ui.py`
  - `tests/test_step2_clean_streaming.py`
  - `tests/test_step2_video_scrubber_parity.py`
- **Verification**: python -m unittest discover tests (590 passed)

## [2026-11-14] feat: Step 2 Milestone 3: #live Client-Side Vector Overlay Delegation
- **Type**: feat
- **Summary**: Wired #live primary stream to ?annotated=false (preserving multi-grid ?annotated=true) and delegated InteractiveCanvas to UnifiedCanvasOverlay HiDPI vector rendering.
- **Files** (7):
  - `dashboard/static/app.js`
  - `dashboard/static/js/camera_ai_config.js`
  - `dashboard/static/js/camera_grid.js`
  - `dashboard/static/js/interactive_canvas.js`
  - `dashboard/static/js/live_player.js`
  - `dashboard/static/partials/tabs/live.html`
  - `tests/test_step2_live_canvas_delegation.py`
- **Verification**: python -m unittest discover -s tests -p test_step2_*.py

## [2026-11-14] feat: Step 2 Milestone 2: Shared UnifiedCanvasOverlay Engine
- **Type**: feat
- **Summary**: Added 225L HiDPI client-side <canvas> overlay engine (window.UnifiedCanvasOverlay) with contain geometry, DPR scaling, tracks, velocity vectors, zones, tripwires, and heatmap rendering, loaded before interactive_canvas.js.
- **Files** (3):
  - `dashboard/static/index.html`
  - `dashboard/static/js/unified_canvas_overlay.js`
  - `tests/test_step2_unified_canvas_engine.py`
- **Verification**: python -m unittest discover -s tests -p test_step2_unified_canvas_engine.py

## [2026-11-14] feat: Step 2 Milestone 1: Clean Un-Burned MJPEG Streaming & streaming.py Budget Fix
- **Type**: feat
- **Summary**: Added _encode_raw_frame, annotated=True|False in get_latest_frame_jpeg and /stream/{camera_id}, and extracted _stream_frame_generator.
- **Files** (8):
  - `.TODO/step_2_unified_client_canvas_overlay.md`
  - `.agents/rules/pipeline_and_db_invariants.md`
  - `dashboard/routers/streaming.py`
  - `dashboard/services/camera_pool_queries.py`
  - `dashboard/services/stream_media.py`
  - `dashboard/services/stream_worker.py`
  - `dashboard/stream_manager.py`
  - `tests/test_step2_clean_streaming.py`
- **Verification**: python -m unittest discover -s tests -p test_step2_clean_streaming.py

## [2026-11-14] feat: Step 1 Milestone 4: Frontend Demo Simulation Gating & Initial Camera Focus Sync
- **Type**: feat
- **Summary**: Gate Synthetic Mock detector as Demo Simulation Only in camera_ai_config.js, auto-sync initial focusedCameraId/activeCameraId when cam_01 is absent, compact camera_config_store.py under 180L, and complete Step 1 verification.
- **Files** (5):
  - `.agents/rules/pipeline_and_db_invariants.md`
  - `dashboard/services/camera_config_store.py`
  - `dashboard/static/camera_manager.js`
  - `dashboard/static/js/camera_ai_config.js`
  - `tests/test_step1_demo_mode_ui.py`
- **Verification**: python -m unittest discover tests

## [2026-11-14] refactor: Step 1 Milestone 3: EntityTaggerService Decomposition & Deterministic Re-ID
- **Type**: refactor
- **Summary**: Decomposed EntityTaggerService.tag_entity into <=35L helpers, replaced blind center-50% crop with ValueError guard, and replaced random Re-ID fallback with deterministic color descriptor.
- **Files** (2):
  - `dashboard/services/entity_tagger.py`
  - `tests/test_step1_entity_tagger_refactor.py`
- **Verification**: python -m unittest discover -s tests -p test_step1_entity_tagger_refactor.py

## [2026-11-14] feat: Step 1 Milestone 2: CameraConfigStore Legacy Mock Healing & Telemetry Status
- **Type**: feat
- **Summary**: Added heal_non_synthetic_mock_cameras in CameraConfigStore, cleaned configs/cameras.json, and exposed detector_model/detector_status in StreamWorker telemetry.
- **Files** (3):
  - `dashboard/services/camera_config_store.py`
  - `dashboard/services/stream_worker.py`
  - `tests/test_step1_camera_config_healing.py`
- **Verification**: python -m unittest discover -s tests -p test_step1_camera_config_healing.py

## [2026-11-14] feat: Step 1 M1: Pipeline Detector Guardrails & _detector_setup.py
- **Type**: feat
- **Summary**: Added is_synthetic_source, EmptyDetector live-source fallback, detector_status/detector_error on PipelineBundle, and StreamPipelineFactory live-vs-synthetic gating.
- **Files** (8):
  - `.TODO/live_video_studio_master_roadmap.md`
  - `.TODO/step_1_production_detection_and_demo_isolation.md`
  - `dashboard/services/pipeline_factory.py`
  - `intelligent_tracker/pipeline/bundle.py`
  - `intelligent_tracker/pipeline/config.py`
  - `intelligent_tracker/pipeline/engine.py`
  - `intelligent_tracker/pipeline/_detector_setup.py`
  - `tests/test_step1_pipeline_detector_guard.py`
- **Verification**: python -m unittest discover -s tests -p test_step1_pipeline_detector_guard.py

## [2026-11-14] feat: Dashboard Live MP4 Recording UI
- **Type**: feat
- **Summary**: Added dedicated Jinja2 partial, responsive CSS without !important, CameraRecording JS controller with per-camera mismatch guards and Video Studio handoff, multi-grid tile recording actions, and Node vm mock-DOM + live CDP layout verification.
- **Files** (11):
  - `dashboard/app.py`
  - `dashboard/dependencies.py`
  - `dashboard/services/camera_pool_queries.py`
  - `dashboard/static/index.html`
  - `dashboard/static/js/camera_grid.js`
  - `dashboard/static/js/telemetry.js`
  - `dashboard/static/partials/tabs/live.html`
  - `dashboard/static/css/camera_recording.css`
  - ... (+3 more)
- **Verification**: python -m unittest discover tests (550 passed) & diagnose.py audit (PASS)

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

## [2026-11-13] refactor: Step 3 Milestone 4: index.html Partial Decomposition & Step 3 Sign-Off
- **Type**: refactor
- **Summary**: Decomposed dashboard/static/index.html into 9 tab partials and 4 modal partials rendered via Jinja2 on GET /, and added Step 3 architecture budget verification tests.
- **Files** (4):
  - `dashboard/app.py`
  - `dashboard/static/index.html`
  - `dashboard/static/partials/`
  - `tests/test_step3_architecture_budgets.py`
- **Verification**: python -m unittest discover tests (471 passed)
