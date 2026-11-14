# Changelog

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
