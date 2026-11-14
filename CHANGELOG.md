# Changelog

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
