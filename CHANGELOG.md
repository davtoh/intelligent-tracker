# Changelog

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

## [2026-11-15] feat: Step 5 M2: Offline Video Spatial Profile, RSAC Alerts & Active Learning
- **Type**: feat
- **Summary**: Added scenario_camera_id to VideoAnalyzeRequest, wired ScenarioManager/AnalyticsEngine/RSACManager/ActiveLearningManager/EventBus into VideoIndexer offline analysis with media_offset_sec event tagging, added #batch-scenario-select modal control, and wired #studio-camera-select in Scenario Studio.
- **Files** (6):
  - `dashboard/schemas.py`
  - `dashboard/services/video_analytics_service.py`
  - `dashboard/static/js/video_batch.js`
  - `dashboard/static/partials/modals/video_modals.html`
  - `dashboard/static/studio.js`
  - `tests/test_step5_video_spatial_and_rsac.py`
- **Verification**: python -m unittest discover -s tests -p test_step5_video_spatial_and_rsac.py

## [2026-11-14] feat: Step 5 M1: FrameProcessor Batch Unification & Media Offset Persistence
- **Type**: feat
- **Summary**: Decomposed batch.py via batch_reporting.py and FrameProcessor.step(), added review_queue media offset columns, and persisted video_filename/media_offset_sec across sightings and active learning.
- **Files** (11):
  - `.TODO/step_5_closed_loop_video_ecosystem.md`
  - `.agents/rules/pipeline_and_db_invariants.md`
  - `intelligent_tracker/active_learning.py`
  - `intelligent_tracker/active_learning_triage.py`
  - `intelligent_tracker/batch.py`
  - `intelligent_tracker/matching/_gallery_signals.py`
  - `intelligent_tracker/repositories/analytics_repo.py`
  - `intelligent_tracker/repositories/learning_repo.py`
  - ... (+3 more)
- **Verification**: python -m unittest discover -s tests -p test_step5_batch_frame_processor.py

## [2026-11-14] feat: Step 4 Milestone 4: E2E Video SSOT, Backup/Restore & Live Handoff Sign-Off
- **Type**: feat
- **Summary**: Added E2E integration tests for live-record-to-Studio handoff, single-file SQLite TrackerDB backup/restore, and non-mocked fallback branches; exposed report_run_id in CameraRecordStatusResponse; verified 628/628 tests green.
- **Files** (2):
  - `dashboard/schemas.py`
  - `tests/test_step4_e2e_video_ssot.py`
- **Verification**: python -m unittest discover tests

## [2026-11-14] feat: Step 4 M3: Live-Record FrameStepResult Handoff & Export UI
- **Type**: feat
- **Summary**: Buffered time-indexed tracks in StreamRecordingController for instant live_capture TrackerDB persistence on stop(), wired step_res and db_getter in StreamWorker/StreamManager, and added Export JSON button and Live Capture badge to video_batch_reports.js.
- **Files** (5):
  - `dashboard/services/stream_recording.py`
  - `dashboard/services/stream_worker.py`
  - `dashboard/static/js/video_batch_reports.js`
  - `dashboard/stream_manager.py`
  - `tests/test_step4_live_recording_handoff.py`
- **Verification**: python -m unittest discover -s tests -p test_step4_*.py

## [2026-11-14] feat: Step 4 M2: TrackerDB Video Report SSOT & Export API
- **Type**: feat
- **Summary**: Refactored video_report_store.py to persist runs and detection streams in TrackerDB with transparent legacy JSON auto-migration (video_report_migration.py) and added GET /api/videos/{filename}/reports/{run_id}/export.
- **Files** (4):
  - `dashboard/routers/video_jobs.py`
  - `dashboard/services/video_report_store.py`
  - `dashboard/services/video_report_migration.py`
  - `tests/test_step4_report_ssot_and_export.py`
- **Verification**: python -m unittest discover -s tests -p test_step4_report_ssot_and_export.py

## [2026-11-14] feat: Step 4 M1: TrackerDB Video Run Schema & VideoRunRepositoryMixin
- **Type**: feat
- **Summary**: Added video_runs table, media offset migrations on sightings/world_timeline_events, VideoRunRepositoryMixin, and compacted schema_manager.py below 240L
- **Files** (7):
  - `.TODO/step_4_trackerdb_video_ssot_and_live_handoff.md`
  - `intelligent_tracker/database.py`
  - `intelligent_tracker/repositories/__init__.py`
  - `intelligent_tracker/repositories/schema_manager.py`
  - `intelligent_tracker/repositories/video_run_repo.py`
  - `intelligent_tracker/repositories/video_schema.py`
  - `tests/test_step4_video_run_repo.py`
- **Verification**: python -m unittest discover -s tests -p test_step4_video_run_repo.py
