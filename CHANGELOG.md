# Changelog

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

## [2026-11-17] fix: Fix stale hidden active_tab and browser-cache recovery in processing_mode.js
- **Type**: fix
- **Summary**: Unconditionally sync active_tab on visible setMode/syncCameraFocus/window-focus and cache-bust processing_mode.js?v=2 so background/other-tab hidden state never blocks vision overlays.
- **Files** (4):
  - `CHANGELOG.md`
  - `dashboard/static/index.html`
  - `dashboard/static/js/processing_mode.js`
  - `tests/test_step4_processing_mode_ui.py`
- **Verification**: MPLBACKEND=Agg .venv\\Scripts\\python.exe -m unittest discover tests

## [2026-11-17] fix: Fix stale hidden active_tab blocking vision overlays on mode/grid switch
- **Type**: fix
- **Summary**: Track serverActiveTab/serverFocusedCameraId in processing_mode.js so visible tabs recover from stale server active_tab=hidden on init, setMode, and syncCameraFocus without requiring tab bounce.
- **Files** (1):
  - `dashboard/static/js/processing_mode.js`
- **Verification**: python -m unittest tests.test_step4_processing_mode_ui tests.test_step4_e2e_performance_and_modes tests.test_processing_mode

## [2026-11-17] fix: Fix 1x1 camera mismatch, black stream recovery, and 4x4 grid CSS
- **Type**: fix
- **Summary**: Prioritize activeCameraId over stale dataset.activeStreamSrc in LivePlayer.attachLiveStream, attach MjpegReconnect to #live-stream-img, and enforce 4x4 grid minmax(0, 1fr) rules in grid_pagination.css.
- **Files** (13):
  - `.TODO/multiview_ws_streaming_plan.md`
  - `dashboard/app.py`
  - `dashboard/services/diagnostic_log_handler.py`
  - `dashboard/static/css/grid_pagination.css`
  - `dashboard/static/css/vms_grid.css`
  - `dashboard/static/index.html`
  - `dashboard/static/js/camera_grid.js`
  - `dashboard/static/js/grid_pagination.js`
  - ... (+5 more)
- **Verification**: python -m unittest tests.test_grid_pagination tests.test_camera_grid_teardown tests.test_processing_mode tests.test_step2_live_canvas_delegation tests.test_refactor_contract

## [2026-11-16] fix: Detach Multi-Grid MJPEG Streams on Tab Leave and Refresh on Mode Change
- **Type**: fix
- **Summary**: Added detachGridStreams/attachGridStreams in live_player.js so 2x2/3x3 grid tiles detach on tab leave and #live-stream-img stays detached in grid mode; refreshed active streams in processing_mode.js setMode().
- **Files** (11):
  - `.TODO/performance_and_processing_modes_master_roadma_followups.md`
  - `.TODO/step_4_frontend_reliability_and_verification.md`
  - `AGENTS.md`
  - `CHANGELOG.md`
  - `dashboard/static/css/processing_mode.css`
  - `dashboard/static/js/camera_ai_config.js`
  - `dashboard/static/js/camera_recording.js`
  - `dashboard/static/js/live_player.js`
  - ... (+3 more)
- **Verification**: python -m unittest tests/test_step2_tab_scoped_streams.py tests/test_step2_tab_scoped_perf_integration.py tests/test_step2_live_canvas_delegation.py tests/test_step4_processing_mode_ui.py

## [2026-11-16] fix: Step 4 Milestone 2: Closed-Loop Full-Suite, Modularity & Browser CDP Verification
- **Type**: fix
- **Summary**: Fixed standalone StreamManager hibernation in ProcessingModeService.should_hibernate_camera and isolated FrameProcessor.step spy in test_step5_batch_frame_processor; verified 760/760 unit tests, 0 latent defects, and headless CDP layout + 1x1/2x2/3x3 grid streaming.
- **Files** (2):
  - `dashboard/services/processing_mode_service.py`
  - `tests/test_step5_batch_frame_processor.py`
- **Verification**: MPLBACKEND=Agg python -m unittest discover tests
