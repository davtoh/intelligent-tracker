# Master Roadmap: Live Monitor (`#live`) & Video Studio (`#videos`) Unification

> **How to use this document**: This is the authoritative 5-Step Master Roadmap unifying **Live Monitor (`#live`)**, **Video Studio (`#videos`)**, and the surrounding intelligence tabs (`#studio`, `#gallery`, `#timeline`, `#alerts`, `#review`, `#analytics`, `#journey`).
> **Rule for Planners & Agents**: Evaluate and execute **one Step at a time** via dedicated Child Implementation Plans (`.TODO/step_<N>_<slug>.md`) linked with `plan_engine.py init .TODO/step_<N>_<slug>.md --parent live_video_studio_master_roadmap --milestone <N>`. Before drafting each Child Plan, run `diagnose.py arch-map --path .` and `diagnose.py audit` on target files so every slice respects the 350-line file and 40-line function budgets.

---

## Step 1: Production Detection Defaults, Demo Mode Isolation & Tagger Decomposition
- [x] **Child Plan**: `.TODO/step_1_production_detection_and_demo_isolation.md`
- [x] **Goal**: Eliminate `mock_person` hallucinations from real/video camera feeds, enforce production detector (`yolov8`) + deterministic Re-ID descriptor defaults, isolate `MockDetector` behind an explicit "Demo Simulation Mode" toggle, and decompose `EntityTaggerService.tag_entity` (110L) below the 40-line function budget.
- [x] **Pre-Plan Evaluation Check**:
  - [x] Run `diagnose.py audit --path intelligent_tracker/pipeline/config.py intelligent_tracker/pipeline/bundle.py dashboard/services/camera_config_store.py dashboard/services/entity_tagger.py`.
- [x] **Target Scope**:
  - [x] Set `detector_fallback_mock=False` for non-synthetic sources in `PipelineConfig` and report explicit `detector_status` (`ready` | `simulation` | `unavailable`) from `build_detector()` without exceeding `bundle.py`'s 350L ceiling.
  - [x] Add `heal_non_synthetic_mock_cameras()` in `CameraConfigStore` to upgrade non-synthetic entries (`usb`, `rtsp`, `video_file`) in `configs/cameras.json` from legacy `"detector": "mock"` to `"yolov8"`.
  - [x] Decompose `EntityTaggerService.tag_entity` (110L) into `<= 30L` helpers (`_resolve_target_bbox`, `_crop_frame_region`, `_extract_deterministic_embedding`, `_save_crop_and_record_sighting`), removing blind center-50% crops and `np.random.randn(128)` noise vectors.
  - [x] Gate `mock` in `camera_ai_config.js` as `Synthetic Mock (Demo Simulation Only)` and sync initial `activeCameraId` / `focusedCameraId` with the first configured camera when `cam_01` is absent.
- [x] **Definition of Done**:
  - [x] Zero non-synthetic cameras run `MockDetector`; `EntityTaggerService` passes `diagnose.py audit` (`<= 40L` functions) and produces deterministic embeddings; all Step 1 unit tests pass.

---

## Step 2: Unified 100% Client-Side `<canvas>` Overlay Engine (`#live` & `#videos` Parity)
- [x] **Child Plan**: `.TODO/step_2_unified_client_canvas_overlay.md`
- [x] **Goal**: Replace the forked server-side OpenCV pixel burn-in (`frame_overlay.py`) and basic video scrubber canvas (`scrubber_overlay_renderer.js`) with one shared 100% Client-Side HTML5 `<canvas>` Overlay Engine across both `#live` and `#videos`.
- [x] **Pre-Plan Evaluation Check**:
  - [x] Run `diagnose.py audit --path dashboard/static/js/interactive_canvas.js dashboard/static/js/scrubber_overlay_renderer.js dashboard/static/js/scrubber_overlay.js dashboard/routers/streaming.py`.
- [x] **Target Scope**:
  - [x] Create `dashboard/static/js/unified_canvas_overlay.js` (`< 280L`, functions `<= 35L`) rendering `BBoxes`, `Track IDs`, `Dwell Timers`, `Velocity Vectors`, `Zones`, `Tripwires`, and translucent `Heatmap` compositing at native `devicePixelRatio` over both `<img id="live-stream-img">` and `<video id="scrubber-video-player">`.
  - [x] Add `?annotated=false|true` support to `/stream/{camera_id}` (`dashboard/routers/streaming.py`) so `#live`'s primary viewport streams clean un-burned video frames (preventing bounding-box pixel pollution during freeze-frame crops) while retaining `?annotated=true` for lightweight `2x2`/`3x3` multi-grid tiles and external alert snapshots.
  - [x] Refactor `interactive_canvas.js` and `scrubber_overlay_renderer.js` to delegate to `UnifiedCanvasOverlay` and unify the overlay layer toggle bar across `#live` and `#videos`.
- [x] **Definition of Done**:
  - [x] Both `#live` and `#videos` render identical vector overlays (`BBoxes`, `Track IDs`, `Dwell`, `Velocity`, `Zones`, `Tripwires`, `Heatmap`) via `UnifiedCanvasOverlay` with zero server-side burn-in on the primary stream and `0px` layout overflow.

---

## Step 3: Interactive Click-to-Tag & Freehand Draw-to-Tag with On-Demand AI Recognition
- **Child Plan**: `.TODO/step_3_interactive_roi_tagging_and_recognition.md`
- [ ] **Goal**: Enable operators to either click an existing tracked bounding box OR manually drag-draw a freehand ROI box on any live (`#live`) or paused recorded (`#videos`) frame, run on-demand AI recognition + Re-ID matching on that crop, preview the recognized object, and enroll/tag it into `TrackerDB`.
- [ ] **Pre-Plan Evaluation Check**:
  - [ ] Run `diagnose.py audit --path dashboard/routers/rsac.py dashboard/routers/analytics.py dashboard/static/js/interactive_canvas.js`.
- [ ] **Target Scope**:
  - [ ] Create `dashboard/routers/tagging.py` (`< 200L`, route handlers `<= 25L`) with `POST /api/tag/recognize-roi` (accepts `camera_id` or `video_filename` + `timestamp_sec` + `bbox` or `crop_base64`, runs detector classification + `GalleryMatcher` similarity search on the crop, returns predicted class, confidence, top identity candidates, and base64 crop thumbnail) and `POST /api/tag/commit`.
  - [ ] Create `dashboard/static/js/roi_draw_tagger.js` (`< 260L`) supporting pointer drag-to-draw ROI selection and track click selection on both `#interactive-canvas` (`#live`) and `#scrubber-overlay-canvas` (`#videos`).
  - [ ] Upgrade the Tag/Enrollment Modal to display the live cropped image preview, AI-recognized category/class badge, and 1-click identity confirmation or new entity creation.
- [ ] **Definition of Done**:
  - [ ] Operators can click-to-tag or drag-draw a box on both `#live` and `#videos`, receive instant AI class/identity recognition on the selected region, and persist the entity signature into `TrackerDB` with immediate gallery reload.

---

## Step 4: 100% SQLite `TrackerDB` Video Run SSOT, JSON Auto-Migration & Instant Live-Record Metadata Handoff
- **Child Plan**: `.TODO/step_4_trackerdb_video_ssot_and_live_handoff.md`
- [ ] **Goal**: Make SQLite `TrackerDB` the 100% Primary Single Source of Truth for all video analysis runs and time-indexed frame detection streams (with automatic migration of legacy `data/reports/*.json` files and 1-click portable JSON export), and automatically save live `FrameStepResult` detections during `#live` MP4 recording so "Open in Video Studio" has instant overlays with zero re-indexing wait.
- [ ] **Pre-Plan Evaluation Check**:
  - [ ] Run `diagnose.py audit --path intelligent_tracker/repositories/schema_manager.py dashboard/services/video_report_store.py dashboard/services/stream_recording.py dashboard/routers/video_jobs.py`.
- [ ] **Target Scope**:
  - [ ] Create `intelligent_tracker/repositories/video_run_repo.py` (`VideoRunRepositoryMixin`, `< 250L`, `<= 10` methods) and add `video_runs` table + `sightings`/`events` `video_filename` and `media_offset_sec` columns in `schema_manager.py`.
  - [ ] Refactor `dashboard/services/video_report_store.py` (splitting the 61L `save_report_run` into `<= 30L` helpers) to read/write through `TrackerDB`, transparently auto-migrating any legacy `data/reports/*.json` files on first access and exposing `GET /api/videos/{filename}/reports/{run_id}/export` for portable JSON downloads.
  - [ ] Upgrade `StreamRecordingController` (`dashboard/services/stream_recording.py`) and `StreamWorker` (`dashboard/services/stream_worker.py`) to record time-indexed `FrameStepResult` track/detection metadata alongside MP4 frames and commit a `live_capture` run to `TrackerDB` when recording stops.
- [ ] **Definition of Done**:
  - [ ] Stopping a live MP4 recording and clicking "Open in Video Studio" immediately renders the recorded detection/track layers on the video scrubber without running a batch job; all runs live in `TrackerDB` and survive single-file DB backup/restore.

---

## Step 5: Closed-Loop Ecosystem (`FrameProcessor` Batch Unification, Video Zones/Alerts/Active Learning & Deep-Link Seeking)
- **Child Plan**: `.TODO/step_5_closed_loop_video_ecosystem.md`
- [ ] **Goal**: Decompose `intelligent_tracker/batch.py` (485L) below 350 lines by routing `VideoIndexer` through `FrameProcessor.step()`, enabling Scenario Studio zones/tripwires, RSAC security alerts, and Active Learning (`#review`) on offline videos, and adding timeline event tick-marks plus 1-click `📼 Seek in Studio` deep-links from `#timeline`, `#alerts`, and `#journey`.
- [ ] **Pre-Plan Evaluation Check**:
  - [ ] Run `diagnose.py audit --path intelligent_tracker/batch.py dashboard/services/video_analytics_service.py dashboard/static/video_scrubber.js dashboard/static/js/gallery_timeline.js`.
- [ ] **Target Scope**:
  - [ ] Decompose `intelligent_tracker/batch.py` (485L -> `< 300L`, `process_video` 240L -> `<= 35L` helpers) by delegating per-frame execution to `FrameProcessor.step()` with `AnalyticsEngine`, `RSACManager`, and `ActiveLearningManager` wired in `video_analytics_service.py`.
  - [ ] Allow selecting a camera/scenario spatial profile (`scenario_camera_id`) in the Video Studio Batch Analyze modal (and Scenario Studio `#studio` source selector) so zones, tripwires, and heatmaps apply to recorded videos.
  - [ ] Create `dashboard/static/js/video_timeline_links.js` (`< 240L`) rendering color-coded sighting/alert tick-marks along `#scrubber-timeline-slider` and enabling 1-click `📼 Seek in Studio` deep-links from `#timeline`, `#alerts`, and `#journey` rows (`video_filename` + `media_offset_sec`).
- [ ] **Definition of Done**:
  - [ ] `batch.py` is `< 350L` with all functions `<= 40L`; offline video analysis populates zone/tripwire metrics, RSAC `#alerts`, and Active Learning `#review`; clicking any video-backed sighting or alert jumps to `#videos` and seeks to the exact timestamp.

---

## Scenario Combinations Matrix

| Real-World Scenario / Objective | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Inspect Master Roadmap Progress** | Plan Engine CLI | `status live_video_studio_master_roadmap` | `python "<config_dir>/skills/frontier-architect/scripts/plan_engine.py" status live_video_studio_master_roadmap --root .` |
| **Inspect Active Step 1 Child Plan Slice** | Plan Engine CLI | `next step_1_production_detection_and_demo_isolation` | `python "<config_dir>/skills/frontier-architect/scripts/plan_engine.py" next step_1_production_detection_and_demo_isolation --root .` |
| **Pre-Plan Architecture & Modularity Map** | Static Analyzer | `arch-map --path .` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" arch-map --path .` |
| **Full Headless Regression Suite** | Unittest Runner | `MPLBACKEND=Agg` | `python -m unittest discover tests` |
