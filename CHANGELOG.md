# Changelog

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

## [2026-11-15] feat: Step 2 M1: Hidden-Tab Stream Disconnection & Tab-Scoped Stream Lifecycle
- **Type**: feat
- **Summary**: Replaced eager studio/analytics img src with data-src, added LivePlayer.syncTabStreams/attachStudioStream/detachStudioStream/attachHeatmapImage, and hooked NavTabsManager switchTab + window.switchTab to emit tab-changed.
- **Files** (6):
  - `.TODO/step_2_tab_scoped_streams_and_lazy_loading.md`
  - `dashboard/static/js/live_player.js`
  - `dashboard/static/js/nav_tabs_manager.js`
  - `dashboard/static/partials/tabs/analytics.html`
  - `dashboard/static/partials/tabs/studio.html`
  - `tests/test_step2_tab_scoped_streams.py`
- **Verification**: python -m unittest discover -s tests -p test_step2_tab_scoped_streams.py

## [2026-11-15] test: Step 1 Milestone 4: End-to-End Integration, Modularity Audit & Sign-Off
- **Type**: test
- **Summary**: Added tests/test_step1_perf_integration.py verifying concurrent ROI offloading, MJPEG raw/annotated/WS mode switching, and mtime-cached report migration; verified 47 Step 1 tests and 672 full-suite tests pass with zero audit/scan defects.
- **Files** (1):
  - `tests/test_step1_perf_integration.py`
- **Verification**: python -m unittest discover tests

## [2026-11-15] perf: Step 1 M3: Legacy Report Migration Mtime Cache & save_video_run Hydration Optimization
- **Type**: perf
- **Summary**: Added thread-safe mtime-aware _MIGRATED_REPORT_FILES cache and clear_migration_cache() to video_report_migration.py, and optimized VideoRunRepositoryMixin.save_video_run() to attach in-memory frame_detections without re-parsing SQLite JSON blobs.
- **Files** (3):
  - `dashboard/services/video_report_migration.py`
  - `intelligent_tracker/repositories/video_run_repo.py`
  - `tests/test_step1_report_migration_and_repo_perf.py`
- **Verification**: python -m unittest discover -s tests -p test_step1_report_migration_and_repo_perf.py

## [2026-11-15] feat: Subscriber-Aware On-Demand Raw & Annotated JPEG Encoding
- **Type**: feat
- **Summary**: Track per-subscriber annotated/raw MJPEG mode in StreamSubscriberRegistry/Mixin, forward annotated flag in streaming router, and skip redundant JPEG encodes in StreamWorker when no matching subscriber or active recorder needs them.
- **Files** (4):
  - `dashboard/routers/streaming.py`
  - `dashboard/services/stream_subscribers.py`
  - `dashboard/services/stream_worker.py`
  - `tests/test_step1_on_demand_jpeg_encoding.py`
- **Verification**: python -m unittest discover -s tests -p test_step1_on_demand_jpeg_encoding.py

## [2026-11-15] perf: Step 1 M1: Asyncio Event-Loop Offloading for Tagging & Sync Video Jobs
- **Type**: perf
- **Summary**: Offloaded blocking ROI recognition/commit/gallery reload in dashboard/routers/tagging.py and sync transcode/analytics in dashboard/routers/video_jobs.py via asyncio.to_thread, with 9 isolated unit tests.
- **Files** (3):
  - `dashboard/routers/tagging.py`
  - `dashboard/routers/video_jobs.py`
  - `tests/test_step1_event_loop_offload.py`
- **Verification**: python -m unittest discover -s tests -p test_step1_event_loop_offload.py

## [2026-11-15] fix: Fix CI failures in camera config healing and journey_segmenter modularity budget
- **Type**: fix
- **Summary**: Guard test_repo_cameras_json_has_no_non_synthetic_mock_or_docker_notice with skipTest when gitignored configs/cameras.json is absent, and extract JourneyHop/EntityJourney dataclasses into intelligent_tracker/journey_models.py so journey_segmenter.py is 137 lines (< 160 budget).
- **Files** (5):
  - `.TODO/performance_and_processing_modes_master_roadmap.md`
  - `.TODO/step_1_event_loop_and_on_demand_encoding.md`
  - `intelligent_tracker/journey_segmenter.py`
  - `tests/test_step1_camera_config_healing.py`
  - `intelligent_tracker/journey_models.py`
- **Verification**: python -m unittest discover -s tests -p test_*.py

## [2026-11-15] test: Step 5 Milestone 4: End-to-End Closed-Loop Video Ecosystem Verification
- **Type**: test
- **Summary**: Added E2E integration tests covering FrameProcessor.step() offline indexing, 4-endpoint API parity (/sightings, /events, /api/active-learning/queue, /api/journey/search), and non-mocked fallback branches.
- **Files** (1):
  - `tests/test_step5_e2e_closed_loop_ecosystem.py`
- **Verification**: python -m unittest discover -s tests -p test_step5_*.py

## [2026-11-15] feat: Step 5 M3: Timeline Tick-Marks & Seek in Studio Deep-Links
- **Type**: feat
- **Summary**: Added VideoTimelineLinks tick-mark rendering, video-seek-request bridge, JourneyHop media fields, and 1-click Seek in Studio buttons across #timeline, #alerts, #journey, and #review.
- **Files** (12):
  - `dashboard/static/css/scrubber_overlays.css`
  - `dashboard/static/index.html`
  - `dashboard/static/js/analytics_view.js`
  - `dashboard/static/js/gallery_timeline.js`
  - `dashboard/static/js/journey_search.js`
  - `dashboard/static/js/scrubber_library_bridge.js`
  - `dashboard/static/partials/tabs/videos.html`
  - `dashboard/static/review_and_rsac.js`
  - ... (+4 more)
- **Verification**: python -m unittest discover -s tests -p test_step5_timeline_ticks_and_deeplinks.py
