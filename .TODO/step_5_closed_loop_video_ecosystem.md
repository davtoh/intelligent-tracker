# Step 5 Implementation Plan: Closed-Loop Ecosystem (`FrameProcessor` Batch Unification, Video Zones/Alerts/Active Learning & Deep-Link Seeking)

> **Parent Master Plan**: `.TODO/live_video_studio_master_roadmap.md` (Step 5)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md`
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–4 are *Deferred to Subsequent Turns*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map` & `diagnose.py audit`)

Measured against workspace baseline before edits (302 files, 55,462 lines, 108 FastAPI routes):
- `intelligent_tracker/batch.py`: 485 lines (`WARN >= 350L`; `diagnose.py audit` flags 3 defects: file budget overrun 485L >= 350L, `process_video` 240L > 40L ceiling, `print_report` 42L > 40L ceiling — must be decomposed below 300 lines with all functions `<= 35L`).
- `intelligent_tracker/pipeline/frame_processor.py`: 340 lines (`OK < 350L`, 14 methods on `FrameProcessor`, `step()` is 37L `<= 40L`).
- `dashboard/services/video_analytics_service.py`: 161 lines (`OK < 350L`, 0 defects; currently instantiates `VideoIndexer` with `analytics=None` and does not wire `ScenarioManager`, `RSACManager`, or `ActiveLearningManager`).
- `dashboard/static/video_scrubber.js`: 388 lines (`WARN >= 350L`, 0 function defects — under Monolith Freeze; keep new timeline tick-mark and deep-link seek logic in `dashboard/static/js/video_timeline_links.js` and `dashboard/static/js/scrubber_library_bridge.js`).
- `dashboard/static/js/gallery_timeline.js`: 240 lines (`OK < 350L`, 0 defects).
- `dashboard/static/js/analytics_view.js`: 158 lines (`OK < 350L`, 0 defects).
- `dashboard/static/js/journey_search.js`: 155 lines (`OK < 350L`, 0 defects).
- `dashboard/static/review_and_rsac.js`: 293 lines (`OK < 350L`, 0 defects).
- `dashboard/static/studio.js`: 328 lines (`OK < 350L`, 0 defects; `#studio-camera-select` is currently hardcoded to `cam_01`).
- `dashboard/static/index.html`: 179 lines (1 line below `< 180L` ceiling enforced by `tests/test_step3_architecture_budgets.py` — condense adjacent script tags when registering `video_timeline_links.js` so `index.html` stays `<= 178L`).

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts (Zero-Regression Invariants)
- `VideoIndexer` in `intelligent_tracker/batch.py` preserves its constructor signature (`db`, `db_path`, `detector_name`, `reid_name`, `reid_threshold`, `tracker_type`, `sample_rate`, `conf_threshold`, `classes`, `analytics`, plus optional `rsac_manager`, `active_learning`, `event_bus`, `video_filename`) and public methods (`process_video`, `generate_occurrence_report`, `print_report`, `export_report`) plus CLI entrypoint `main()`.
- `VideoIndexer.process_video()` return payload preserves all existing top-level keys (`video_path`, `source`, `generated_at`, `config`, `video_info`, `processing_stats`, `summary`, `entities`, `timeline`, `frame_detections`) while enriching `summary` and `analytics` with `zones`, `tripwires`, `zone_metrics`, `tripwire_counts`, `alerts`, and `review_candidates_queued`.
- `TrackerDB.add_sighting()`, `TrackerDB.add_review_item()`, and `TrackerDB.index_timeline_event()` remain 100% backward-compatible via default arguments (`video_filename: str = ""`, `media_offset_sec: float = 0.0`).
- `POST /api/videos/{filename}/analyze` preserves backward compatibility when `scenario_camera_id` is omitted or `None`.
- `intelligent_tracker/` never imports from `dashboard/` or `scripts/`.

### Modularity Guardrails
- `intelligent_tracker/batch.py` MUST be reduced below `300` lines (`< 350L` budget) with `<= 10` methods on `VideoIndexer` and every function/method `<= 35` lines.
- `intelligent_tracker/batch_reporting.py` MUST remain `< 220` lines with all functions `<= 35` lines.
- `dashboard/services/video_analytics_service.py` MUST remain `< 260` lines with all functions `<= 35` lines.
- `dashboard/static/js/video_timeline_links.js` MUST remain `< 240` lines with all functions `<= 35` lines.
- `dashboard/static/index.html` MUST remain `< 180` lines, tab partials `< 220` lines, and modal partials `< 240` lines (`tests/test_step3_architecture_budgets.py`).

---

## 3. Phased Implementation Milestones

### Milestone 1: `batch.py` Decomposition via `FrameProcessor.step()` & `TrackerDB` Video Offset Persistence
- [x] **intelligent_tracker/batch_reporting.py**: Extract report formatting, CLI argument parsing, `format_occurrence_report`, `print_occurrence_report` (splitting the 42L `print_report` into `<= 30L` helpers), `export_occurrence_report`, and `run_batch_cli` into `intelligent_tracker/batch_reporting.py` (`< 220L`, all functions `<= 35L`).
- [x] **intelligent_tracker/batch.py**: Decompose `VideoIndexer` (`< 280L`, `<= 10` methods, all functions `<= 35L`) to build or accept a `FrameProcessor` / `PipelineBundle` and split the 240L `process_video` into `<= 35L` helpers (`_open_video_capture`, `_build_frame_processor`, `_step_video_frame`, `_record_step_occurrences`, `_build_final_report`) that delegate per-frame detection, tracking, spatial analytics, Re-ID, RSAC, and Active Learning to `FrameProcessor.step(frame, timestamp=video_time_sec)`.
- [x] **intelligent_tracker/repositories/video_schema.py**: Add idempotent schema migration columns `("review_queue", "video_filename", "TEXT DEFAULT ''")` and `("review_queue", "media_offset_sec", "REAL DEFAULT 0.0")` while keeping `video_schema.py` `< 140L`.
- [x] **intelligent_tracker/repositories/analytics_repo.py**: Update `add_sighting` to accept optional `video_filename: str = ""` and `media_offset_sec: float = 0.0` and persist them in `sightings` (`< 280L`, methods `<= 40L`).
- [x] **intelligent_tracker/repositories/learning_repo.py**: Update `add_review_item` to accept optional `video_filename: str = ""` and `media_offset_sec: float = 0.0` and persist them in `review_queue`, and update `intelligent_tracker/active_learning.py` (`consider_candidate`) and `intelligent_tracker/matching/_gallery_signals.py` (`emit_periodic_sighting`) to forward `video_filename` and `media_offset_sec` (`< 300L`, methods `<= 40L`).
- [x] **tests/test_step5_batch_frame_processor.py**: Add isolated unit tests (`tempfile.TemporaryDirectory()`, `detector_name="mock"`) verifying `VideoIndexer.process_video()` executes through `FrameProcessor.step()`, writes `video_filename` and `media_offset_sec` to `sightings` and `review_queue`, preserves backward compatibility with `tests/test_batch.py` and `tests/test_progressive_stream.py`, and passes `diagnose.py audit` (`batch.py < 300L`, 0 defects).
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 1 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step5_batch_frame_processor.py"
```

---

### Milestone 2: Spatial Profile (`scenario_camera_id`), RSAC Alerts & Active Learning Wiring for Offline Videos
- [x] **dashboard/schemas.py**: Add optional `scenario_camera_id: Optional[str] = None` to `VideoAnalyzeRequest` while keeping `schemas.py` `< 260L`.
- [x] **dashboard/services/video_analytics_service.py**: Update `parse_analyze_options()` and `create_video_indexer()` (`< 260L`, functions `<= 35L`) to resolve `scenario_camera_id` zones/tripwires via `ScenarioManager`, wire `AnalyticsEngine`, `RSACManager`, `ActiveLearningManager`, and `EventBus` (tagging emitted offline events with `video_filename` and `media_offset_sec`), and persist spatial `zones`, `tripwires`, `zone_metrics`, `tripwire_counts`, and `alerts` in the saved video report run.
- [x] **dashboard/static/partials/modals/video_modals.html**: Add `#batch-scenario-select` (`Spatial Scenario Profile`) to `#modal-video-batch-analyze` while keeping `video_modals.html` `< 235L`.
- [x] **dashboard/static/js/video_batch.js**: Populate `#batch-scenario-select` from `/api/cameras` and pass `scenario_camera_id` in `handleBatchFormSubmit()` while keeping `video_batch.js` `< 320L` and functions `<= 35L`.
- [x] **dashboard/static/studio.js**: Wire `#studio-camera-select` (`< 345L`, functions `<= 35L`) to dynamically load configured camera profiles and recorded video files so operators can author and preview zones/tripwires for offline video analysis.
- [x] **tests/test_step5_video_spatial_and_rsac.py**: Add unit and FastAPI `TestClient` tests (`tempfile.TemporaryDirectory()`, synthetic video fixture, `detector="mock"`) verifying offline analysis with `scenario_camera_id` computes zone/tripwire metrics, emits RSAC alerts with `video_filename` + `media_offset_sec`, queues Active Learning items, and passes `diagnose.py audit` + `tests/test_step3_architecture_budgets.py`.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 2 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step5_video_spatial_and_rsac.py"
```

---

### Milestone 3: Timeline Event Tick-Marks & 1-Click `📼 Seek in Studio` Deep-Links (`#timeline`, `#alerts`, `#journey`, `#review`)
- [ ] **dashboard/static/js/video_timeline_links.js**: Create `VideoTimelineLinks` (`< 240L`, functions `<= 35L`) rendering color-coded sighting and alert tick-marks along `#scrubber-timeline-slider` (`#scrubber-timeline-ticks`), implementing click-to-seek on tick-marks, and providing `buildSeekInStudioButtonHtml(videoFilename, offsetSec)` + `seekToVideoTimestamp(videoFilename, offsetSec)` to jump to `#videos` and seek `#scrubber-video-player`.
- [ ] **dashboard/static/partials/tabs/videos.html**: Add `<div id="scrubber-timeline-ticks" class="scrubber-timeline-ticks"></div>` inside the scrubber timeline container (`< 100L`), and register `/static/js/video_timeline_links.js` in `dashboard/static/index.html` while keeping `index.html` `<= 178L` (`< 180L`).
- [ ] **dashboard/static/js/scrubber_library_bridge.js**: Wire `video-seek-request` handling and `VideoTimelineLinks.renderTimelineTicks` refresh on report/detection stream load (`< 220L`, functions `<= 35L`) with a 1-line hook in `dashboard/static/video_scrubber.js` (`<= 388L`).
- [ ] **intelligent_tracker/journey.py**: Preserve `video_filename` and `media_offset_sec` on `JourneyHop` and serialized journey search results (`< 220L`, functions `<= 35L`).
- [ ] **dashboard/static/js/gallery_timeline.js**: Render 1-click `📼 Seek in Studio` buttons on video-backed sighting rows in `#timeline`, and wire the same deep-link button into `dashboard/static/js/analytics_view.js` (`#alerts`), `dashboard/static/js/journey_search.js` (`#journey`), and `dashboard/static/review_and_rsac.js` (`#review`) while keeping all modified files `< 340L` and functions `<= 35L`.
- [ ] **tests/test_step5_timeline_ticks_and_deeplinks.py**: Add Python and Node VM unit tests (`<= 40L` per test method) verifying timeline tick-mark rendering, click-to-seek offset calculation, `📼 Seek in Studio` button generation across `#timeline`, `#alerts`, `#journey`, and `#review`, and `video-seek-request` player seeking.
- [ ] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 3 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step5_timeline_ticks_and_deeplinks.py"
```

---

### Milestone 4: End-to-End Closed-Loop Ecosystem Verification, Architecture Budgets & Master Roadmap Sign-Off
- [ ] **tests/test_step5_e2e_closed_loop_ecosystem.py**: Add end-to-end integration tests verifying offline video indexing with `FrameProcessor.step()` + spatial profile -> sighting, alert, review item, and journey hop persistence with `video_filename` and `media_offset_sec` -> API response parity across `/sightings`, `/events`, `/api/active-learning/queue`, and `/api/journey/search` -> non-mocked fallback branch coverage (`scenario_camera_id=None`, missing profile, empty detections).
- [ ] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 4 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step5_*.py"
```

---

## 4. Scenario Combinations Matrix

| Real-World Scenario / Objective | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Verify Milestone 1 (`batch.py` `FrameProcessor` Unification & Offsets)** | Headless unit suite | `test_step5_batch_frame_processor.py` | `python -m unittest discover -s tests -p "test_step5_batch_frame_processor.py"` |
| **Verify Milestone 2 (Spatial Profile, RSAC Alerts & Active Learning)** | Headless unit suite | `test_step5_video_spatial_and_rsac.py` | `python -m unittest discover -s tests -p "test_step5_video_spatial_and_rsac.py"` |
| **Verify Milestone 3 (Timeline Ticks & `📼 Seek in Studio` Deep-Links)** | Headless unit suite | `test_step5_timeline_ticks_and_deeplinks.py` | `python -m unittest discover -s tests -p "test_step5_timeline_ticks_and_deeplinks.py"` |
| **Verify Milestone 4 (Full Step 5 Closed-Loop E2E Suite)** | Headless unit suite | `test_step5_*.py` | `python -m unittest discover -s tests -p "test_step5_*.py"` |
| **Verify HTML/JS Architecture & Partial Line Budgets** | Budget test suite | `test_step3_architecture_budgets.py` | `python -m unittest discover -s tests -p "test_step3_architecture_budgets.py"` |
| **Static Modularity & Function Budget Audit on Step 5 Files** | AST Auditor | `--max-lines 350 --max-fn-lines 40` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/batch.py intelligent_tracker/batch_reporting.py dashboard/services/video_analytics_service.py dashboard/static/js/video_timeline_links.js dashboard/static/js/gallery_timeline.js dashboard/static/js/analytics_view.js dashboard/static/js/journey_search.js dashboard/static/review_and_rsac.js --max-lines 350 --max-fn-lines 40` |
