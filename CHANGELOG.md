# Changelog

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

## [2026-11-14] test: Step 3 Milestone 4: End-to-End ROI Tagging Verification & Sign-Off
- **Type**: test
- **Summary**: Added E2E ROI tagging integration tests covering live camera, recorded video timestamp seek, gallery reload, and single-stream/detector fallback branches; verified 610/610 repository tests pass.
- **Files** (1):
  - `tests/test_step3_e2e_tagging_flow.py`
- **Verification**: python -m unittest discover tests

## [2026-11-14] feat: Step 3 Milestone 3: ROI Tag Modal Preview, AI Auto-Select & Scrubber Wiring
- **Type**: feat
- **Summary**: Upgraded #modal-tag-entity with live ROI crop preview, AI class badge, and 1-click Re-ID candidate chips; wired InteractiveCanvas and ScrubberOverlay to RoiDrawTagger.openWithRecognition() and POST /api/tag/commit with gallery refresh.
- **Files** (6):
  - `dashboard/static/css/scrubber.css`
  - `dashboard/static/index.html`
  - `dashboard/static/js/interactive_canvas.js`
  - `dashboard/static/js/scrubber_overlay.js`
  - `dashboard/static/partials/modals/entity_modals.html`
  - `tests/test_step3_tag_modal_integration.py`
- **Verification**: python -m unittest discover -s tests -p test_step3_*.py

## [2026-11-14] feat: Step 3 Milestone 2: Unified RoiDrawTagger Canvas Controller
- **Type**: feat
- **Summary**: Added dashboard/static/js/roi_draw_tagger.js (233L) for pointer click-to-tag (<6px) and freehand drag-to-draw (>=6px) ROI selection mapped via UnifiedCanvasOverlay.computeContainBox, registered in index.html, and verified with 6 Node VM unit tests.
- **Files** (3):
  - `dashboard/static/index.html`
  - `dashboard/static/js/roi_draw_tagger.js`
  - `tests/test_step3_roi_draw_tagger.py`
- **Verification**: python -m unittest discover -s tests -p test_step3_roi_draw_tagger.py

## [2026-11-14] feat: Step 3 Milestone 1: On-Demand ROI Recognition & Tag Commit Backend
- **Type**: feat
- **Summary**: Added RoiRecognitionService and /api/tag/recognize-roi + /api/tag/commit endpoints with isolated unit tests
- **Files** (6):
  - `.agents/rules/pipeline_and_db_invariants.md`
  - `dashboard/app.py`
  - `dashboard/routers/__init__.py`
  - `dashboard/routers/tagging.py`
  - `dashboard/services/roi_recognition_service.py`
  - `tests/test_step3_roi_recognition_api.py`
- **Verification**: python -m unittest discover -s tests -p test_step3_roi_recognition_api.py

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
