# Changelog

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

## [2026-11-15] feat: Step 3 Milestone 2: StreamWorker & StreamPoolCoordinator Hibernation and Tab-Scoped AI Gating
- **Type**: feat
- **Summary**: Integrated ProcessingModeService hibernation and vision-step gating into StreamWorker, StreamPoolCoordinator, and StreamManager with 9 unit tests.
- **Files** (4):
  - `dashboard/services/stream_pool_coordinator.py`
  - `dashboard/services/stream_worker.py`
  - `dashboard/stream_manager.py`
  - `tests/test_step3_worker_hibernation_and_ai_gating.py`
- **Verification**: python -m unittest discover -s tests -p test_step3_worker_hibernation_and_ai_gating.py

## [2026-11-15] feat: Step 3 M1: ProcessingModeService, /api/system/processing-mode Router & StreamTelemetry Extraction
- **Type**: feat
- **Summary**: Extracted stream_telemetry.py from stream_worker.py, added ProcessingModeService and /api/system/processing-mode endpoints, and updated schemas.
- **Files** (9):
  - `.TODO/step_3_backend_processing_modes_and_hibernation.md`
  - `dashboard/app.py`
  - `dashboard/routers/__init__.py`
  - `dashboard/schemas.py`
  - `dashboard/services/stream_worker.py`
  - `dashboard/routers/processing_mode.py`
  - `dashboard/services/processing_mode_service.py`
  - `dashboard/services/stream_telemetry.py`
  - ... (+1 more)
- **Verification**: python -m unittest discover -s tests -p test_step3_processing_mode_api.py

## [2026-11-15] test: Step 2 M4: Tab-Scoped Streams & Lazy Loading Integration Sign-Off
- **Type**: test
- **Summary**: Added end-to-end Node VM integration tests in tests/test_step2_tab_scoped_perf_integration.py verifying boot stream isolation, coalesced /api/cameras + /api/videos fetches, 250ms BEV minimap gating, and lazy #tab-videos loading; verified all 38 Step 2 tests and 697 total tests pass.
- **Files** (1):
  - `tests/test_step2_tab_scoped_perf_integration.py`
- **Verification**: python -m unittest discover -s tests -p test_step2_*.py

## [2026-11-15] feat: Step 2 M3: Boot Fetch Deduplication & Lazy Video Report Loading
- **Type**: feat
- **Summary**: Added 2000ms boot GET fetch coalescing for /api/cameras and /api/videos in nav_tabs_manager.js and deferred #tab-videos player selection, /report, and /detections fetches until tab activation in scrubber_library_bridge.js.
- **Files** (3):
  - `dashboard/static/js/nav_tabs_manager.js`
  - `dashboard/static/js/scrubber_library_bridge.js`
  - `tests/test_step2_lazy_video_and_fetch_dedup.py`
- **Verification**: python -m unittest discover -s tests -p test_step2_lazy_video_and_fetch_dedup.py

## [2026-11-15] feat: Step 2 M2: Tab-Scoped Studio BEV Minimap Timer & Stream Gating
- **Type**: feat
- **Summary**: Replaced unconditional 250ms BEV minimap interval in studio.js with tab-scoped startMinimapLoop/stopMinimapLoop/syncStudioTabState bound to tab-changed and gated studio-live-img.src updates when #tab-studio is hidden.
- **Files** (2):
  - `dashboard/static/studio.js`
  - `tests/test_step2_studio_minimap_gating.py`
- **Verification**: python -m unittest discover -s tests -p test_step2_studio_minimap_gating.py

## [2026-11-15] test: Step 1 Milestone 4: End-to-End Integration, Modularity Audit & Sign-Off
- **Type**: test
- **Summary**: Added tests/test_step1_perf_integration.py verifying concurrent ROI offloading, MJPEG raw/annotated/WS mode switching, and mtime-cached report migration; verified 47 Step 1 tests and 672 full-suite tests pass with zero audit/scan defects.
- **Files** (1):
  - `tests/test_step1_perf_integration.py`
- **Verification**: python -m unittest discover tests
