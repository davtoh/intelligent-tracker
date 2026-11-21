# Changelog

## [2026-11-21] feat: Step 1: Diagnostics Upgrades, Unmocked Probes & Red Baseline
- **Type**: feat
- **Summary**: Upgraded system-diagnostics/frontier-architect tooling, added ruff/mypy dev tooling, hardened 4 unmocked workspace probes (including spa_nine_tab_cdp_probe), resolved stale test traces, and captured verified Red baseline.
- **Files** (3):
  - `.diagnostics/probes/cold_boot_world_probe.py`
  - `.diagnostics/probes/replay_pipeline_probe.py`
  - `.diagnostics/probes/video_studio_contract_probe.py`
- **Verification**: python -m unittest discover tests

## [2026-11-20] fix: Integration Diagnostics Remediation Milestone 3
- **Type**: fix
- **Summary**: Fixed scrubber reports/media URLs, entities+alerts timeline extraction, BEV telemetry wiring, Studio video overlay gating, armed UI/AsyncInferenceWorker sync, boot stream gating, and zero active scan/surface defects
- **Files** (22):
  - `.TODO/integration_diagnostics_and_remediation_plan.md`
  - `dashboard/camera_pool.py`
  - `dashboard/services/async_inference_worker.py`
  - `dashboard/services/process_supervisor.py`
  - `dashboard/services/stream_worker.py`
  - `dashboard/static/app.js`
  - `dashboard/static/camera_manager.js`
  - `dashboard/static/js/bev_minimap.js`
  - ... (+14 more)
- **Verification**: MPLBACKEND=Agg python -m unittest discover tests

## [2026-11-19] feat: Step 2 Milestone 3: Scheduler HUD, Schema Telemetry & Docs
- **Type**: feat
- **Summary**: Extended ProcessingModeStatusResponse with scheduler telemetry, fixed data.camera_states lookup in processing_mode.js, added scheduler_hud.js tier and load-shed pills, documented scheduler and CachedReplayProvider in dashboard.rst and AGENTS.md, and verified 858 tests plus Sphinx -W.
- **Files** (10):
  - `AGENTS.md`
  - `dashboard/schemas.py`
  - `dashboard/services/processing_mode_service.py`
  - `dashboard/static/css/processing_mode.css`
  - `dashboard/static/index.html`
  - `dashboard/static/js/live_player.js`
  - `dashboard/static/js/processing_mode.js`
  - `documentation/dashboard.rst`
  - ... (+2 more)
- **Verification**: python -m unittest discover tests

## [2026-11-19] feat: Step 2 Milestone 2: Zero-GPU CachedReplayProvider & Runtime Pool Scheduler Wiring
- **Type**: feat
- **Summary**: Extracted shared post_detection_governance.py (FrameProcessor 14->7 methods), implemented zero-GPU CachedReplayProvider with live zone/tripwire/RSAC governance and loop wrap-around resets, wired AnalyticsScheduler & armed P1 gating into StreamWorker/AsyncInferenceWorker, and exposed scheduler/armed telemetry.
- **Files** (9):
  - `dashboard/services/async_inference_worker.py`
  - `dashboard/services/cached_replay_provider.py`
  - `dashboard/services/camera_pool_queries.py`
  - `dashboard/services/file_detection_replay.py`
  - `dashboard/services/stream_telemetry.py`
  - `dashboard/services/stream_worker.py`
  - `intelligent_tracker/pipeline/frame_processor.py`
  - `intelligent_tracker/pipeline/post_detection_governance.py`
  - ... (+1 more)
- **Verification**: python -m unittest tests.test_cached_replay_and_pool_scheduler tests.test_live_studio_sync tests.test_step3_worker_hibernation_and_ai_gating tests.test_dashboard_di tests.test_step3_architecture_budgets tests.test_cross_platform_pipeline_hardening tests.test_analytics_scheduler

## [2026-11-19] feat: Step 2 Milestone 1: Core AnalyticsScheduler, 64x36 MotionGate, dt-Aware Trackers & Armed P1
- **Type**: feat
- **Summary**: Implemented 64x36 luma MotionGate, P0/P1/P2 AnalyticsScheduler with 3-stage load shedding and IdleRefinementHook, dt-aware persistence in SortTracker/CentroidTracker, and armed P1 vision gating in ProcessingModeService.
- **Files** (6):
  - `dashboard/services/processing_mode_service.py`
  - `intelligent_tracker/tracker/centroid.py`
  - `intelligent_tracker/tracker/sort.py`
  - `intelligent_tracker/pipeline/analytics_scheduler.py`
  - `intelligent_tracker/pipeline/motion_gate.py`
  - `tests/test_analytics_scheduler.py`
- **Verification**: MPLBACKEND=Agg python -m unittest tests.test_analytics_scheduler tests.test_tracker tests.test_processing_mode tests.test_processing_mode_invariants tests.test_step3_processing_mode_api tests.test_modernization

## [2026-11-19] feat: Step 1.5 Milestone 2: Live Monitor vs Video Studio Synchronization & Diagnostic Clarity
- **Type**: feat
- **Summary**: Add AsyncInferenceWorker frame_seq/lag provenance, FileDetectionReplayProvider for pre-indexed video_file cameras, #live-stream-img ROI tagger fix, source_resolution scaling, and opt-in burned annotation toggle.
- **Files** (14):
  - `.TODO/realtime_multiview_master_roadmap.md`
  - `.TODO/step_1_5_cross_platform_pipeline_hardening.md`
  - `dashboard/services/async_inference_worker.py`
  - `dashboard/services/stream_telemetry.py`
  - `dashboard/services/stream_worker.py`
  - `dashboard/static/app.js`
  - `dashboard/static/js/interactive_canvas.js`
  - `dashboard/static/js/live_player.js`
  - ... (+6 more)
- **Verification**: MPLBACKEND=Agg python -m unittest discover tests (839 passed)

## [2026-11-19] feat: Multi-View WebSocket Streaming & Grid Scalability (Milestone 4)
- **Type**: feat
- **Summary**: Added /ws/multiview frontend protocol/FrameSurface/client with canvas grid tiles, 3-failure MJPEG fallback with auto-restore, armed-paused overlay counter, static-before-wildcard WS router ordering fix, Hub/HTTP2 Sphinx docs, and Node VM + headless CDP E2E tests
- **Files** (15):
  - `AGENTS.md`
  - `dashboard/app.py`
  - `dashboard/static/css/grid_pagination.css`
  - `dashboard/static/index.html`
  - `dashboard/static/js/camera_grid.js`
  - `dashboard/static/js/live_player.js`
  - `dashboard/static/js/processing_mode.js`
  - `dashboard/static/partials/tabs/live.html`
  - ... (+7 more)
- **Verification**: MPLBACKEND=Agg python -m unittest discover tests

## [2026-11-17] fix: Cold-Boot cam_01 SSOT & Focus Reconciliation
- **Type**: fix
- **Summary**: Removed remaining hardcoded cam_01 fallbacks and eager stream attributes across Studio, Recording, Enrollment, Interactive Canvas, Gallery Timeline, Scenario Modals, and StreamPoolCoordinator. Seeded initial focused_camera_id from the first enabled camera on StreamPoolCoordinator start/restore, delegated CameraAIConfig.resolveInitialCameraId to LivePlayer.attachLiveStream(), and reconciled null server focus in ProcessingModeUI.setAvailableCameras().
- **Files** (21):
  - `AGENTS.md`
  - `dashboard/services/processing_mode_service.py`
  - `dashboard/services/stream_pool_coordinator.py`
  - `dashboard/static/js/camera_ai_config.js`
  - `dashboard/static/js/camera_recording.js`
  - `dashboard/static/js/gallery_timeline.js`
  - `dashboard/static/js/interactive_canvas.js`
  - `dashboard/static/js/live_player.js`
  - ... (+13 more)
- **Verification**: python -m unittest discover tests (779 tests OK) + diagnose.py ui --live --capture-runtime (0 exceptions, 0 networkErrors)

## [2026-11-17] fix: Unify active camera SSOT across frontend modules and eliminate cam_01 stub leakage
- **Type**: fix
- **Summary**: Initialize app.js and camera_manager.js from it_focused_camera_id/null instead of cam_01, validate syncCameraFocus against ProcessingModeUI.setAvailableCameras(), and gate LivePlayer.syncCameraFocus on resolved camera IDs.
- **Files** (7):
  - `CHANGELOG.md`
  - `dashboard/static/app.js`
  - `dashboard/static/camera_manager.js`
  - `dashboard/static/js/camera_ai_config.js`
  - `dashboard/static/js/live_player.js`
  - `dashboard/static/js/processing_mode.js`
  - `tests/test_step4_processing_mode_ui.py`
- **Verification**: .venv\\Scripts\\python.exe -m unittest tests.test_step4_processing_mode_ui tests.test_step4_e2e_performance_and_modes tests.test_processing_mode tests.test_step1_demo_mode_ui tests.test_step2_live_canvas_delegation tests.test_step2_tab_scoped_streams tests.test_camera_grid_teardown

## [2026-11-17] fix: Eliminate cam_01 stub in processing_mode.js and persist focused camera across reloads
- **Type**: fix
- **Summary**: Initialize state.focusedCameraId from localStorage (it_focused_camera_id) instead of hardcoded cam_01 in processing_mode.js, omit focused_camera_id from init() when unset, and restore the last focused camera in CameraAIConfig.resolveInitialCameraId().
- **Files** (3):
  - `dashboard/static/js/camera_ai_config.js`
  - `dashboard/static/js/processing_mode.js`
  - `tests/test_step4_processing_mode_ui.py`
- **Verification**: .venv\\Scripts\\python.exe -m unittest tests.test_step4_processing_mode_ui tests.test_step4_e2e_performance_and_modes tests.test_processing_mode tests.test_step1_demo_mode_ui tests.test_step2_live_canvas_delegation

## [2026-11-17] fix: Stop init() from clobbering focused_camera_id and add no-cache for /static
- **Type**: fix
- **Summary**: Omit default cam_01 focused_camera_id from processing_mode.js init() POST so page load never overwrites the resolved camera, remove ?v=2 from index.html, and set Cache-Control: no-cache on /static/* in dashboard/app.py.
- **Files** (5):
  - `CHANGELOG.md`
  - `dashboard/app.py`
  - `dashboard/static/index.html`
  - `dashboard/static/js/processing_mode.js`
  - `tests/test_step4_processing_mode_ui.py`
- **Verification**: .venv\\Scripts\\python.exe -m unittest tests.test_step4_processing_mode_ui tests.test_step4_e2e_performance_and_modes tests.test_processing_mode tests.test_step3_architecture_budgets tests.test_dashboard_di
