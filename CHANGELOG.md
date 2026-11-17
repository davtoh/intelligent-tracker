# Changelog

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

## [2026-11-16] fix: Fix Live Monitor Paused Black Screen, Boot cam_01 404, and Video Studio Preload
- **Type**: fix
- **Summary**: Added #live-paused-overlay with 1-click Resume in live.html/processing_mode.js/css, synced initial camera focus in camera_ai_config.js, skipped placeholder cam_01 recording status poll in camera_recording.js, and set preload=auto on #scrubber-video-player in videos.html.
- **Files** (9):
  - `.TODO/performance_and_processing_modes_master_roadma_followups.md`
  - `.TODO/step_4_frontend_reliability_and_verification.md`
  - `AGENTS.md`
  - `dashboard/static/css/processing_mode.css`
  - `dashboard/static/js/camera_ai_config.js`
  - `dashboard/static/js/camera_recording.js`
  - `dashboard/static/js/processing_mode.js`
  - `dashboard/static/partials/tabs/live.html`
  - ... (+1 more)
- **Verification**: python -m unittest discover tests

## [2026-11-16] fix: Step 4 Milestone 2: Closed-Loop Full-Suite, Modularity & Browser CDP Verification
- **Type**: fix
- **Summary**: Fixed standalone StreamManager hibernation in ProcessingModeService.should_hibernate_camera and isolated FrameProcessor.step spy in test_step5_batch_frame_processor; verified 760/760 unit tests, 0 latent defects, and headless CDP layout + 1x1/2x2/3x3 grid streaming.
- **Files** (2):
  - `dashboard/services/processing_mode_service.py`
  - `tests/test_step5_batch_frame_processor.py`
- **Verification**: MPLBACKEND=Agg python -m unittest discover tests

## [2026-11-16] feat: Step 3 Milestone 2: DirectShow Warmup Grace & Exponential-Backoff Auto-Reopen
- **Type**: feat
- **Summary**: Added 5.0s warmup grace timeout (proportional when read_timeout is overridden), pure capture_helpers.py, and interruptible exponential backoff reconnection in CaptureReadGuard/CaptureWorkerMixin/VideoSource.
- **Files** (7):
  - `.TODO/performance_and_processing_modes_master_roadma_followups.md`
  - `.TODO/step_3_pool_discovery_and_driver_resilience.md`
  - `intelligent_tracker/video/capture_guard.py`
  - `intelligent_tracker/video/capture_worker.py`
  - `intelligent_tracker/video/source.py`
  - `tests/test_camera_discovery_and_guard.py`
  - `intelligent_tracker/video/capture_helpers.py`
- **Verification**: python -m unittest tests/test_camera_discovery_and_guard.py tests/test_capture_circuit_breaker.py tests/test_camera_device.py tests/test_discovery.py

## [2026-11-16] refactor: Step 2 Milestone 2: Event-Driven MJPEG Wakeup & StreamManager Waiter Lifecycle
- **Type**: refactor
- **Summary**: Replaced 40ms polling in _stream_frame_generator with event-driven asyncio.wait on frame_event and shutdown_evt (1.5s heartbeat safety timeout), added thread-safe frame-ready waiter registry on StreamMediaMixin, notified waiters on frame encode and StreamManager.signal_stop(), and extracted build_live_step_result to keep stream_worker.py within 285L.
- **Files** (1):
  - `dashboard/services/stream_media.py,dashboard/stream_manager.py,dashboard/routers/streaming.py,dashboard/services/stream_worker.py,dashboard/services/async_inference_worker.py,tests/test_stream_manager.py`

## [2026-11-15] test: Step 4 Milestone 2: E2E Processing Mode Verification, StreamWorker __all__ & Master Sign-Off
- **Type**: test
- **Summary**: Added explicit __all__ exports in stream_worker.py (0 arch-map unused imports) and end-to-end tests in tests/test_step4_e2e_performance_and_modes.py covering mode lifecycle, worker parity, capture_only deferred badge propagation, <200ms latency, and Step 1-4 modularity budgets.
- **Files** (2):
  - `dashboard/services/stream_worker.py`
  - `tests/test_step4_e2e_performance_and_modes.py`
- **Verification**: python -m unittest discover tests

## [2026-11-15] feat: Step 4 M1: Processing Mode UI Selector & Auto-Sync
- **Type**: feat
- **Summary**: Added top-bar #processing-mode-pill CSS/JS module, localStorage persistence, tab/visibility/camera focus auto-sync, and 8 unit/VM/TestClient tests.
- **Files** (8):
  - `AGENTS.md`
  - `dashboard/static/index.html`
  - `dashboard/static/js/live_player.js`
  - `dashboard/static/js/nav_tabs_manager.js`
  - `dashboard/static/styles.css`
  - `dashboard/static/css/processing_mode.css`
  - `dashboard/static/js/processing_mode.js`
  - `tests/test_step4_processing_mode_ui.py`
- **Verification**: python -m unittest discover -s tests -p test_step4_processing_mode_ui.py

## [2026-11-15] feat: Step 3 Milestone 3: Capture-Only Raw Recording & Deferred VideoIndexer Queue
- **Type**: feat
- **Summary**: Added capture_only raw MP4 recording bypass and automatic deferred VideoIndexer job queuing in StreamRecordingController, wired StreamManager mode_service_getter, tightened StreamPoolCoordinator to 236L, and verified 719/719 tests.
- **Files** (5):
  - `dashboard/services/stream_pool_coordinator.py`
  - `dashboard/services/stream_recording.py`
  - `dashboard/stream_manager.py`
  - `tests/test_dashboard_di.py`
  - `tests/test_step3_capture_only_deferred_queue.py`
- **Verification**: python -m unittest discover tests
