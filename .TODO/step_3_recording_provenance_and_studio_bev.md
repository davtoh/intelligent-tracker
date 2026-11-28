# Step 3: Web-Playable Live Recording, Alert-to-Clip Provenance & Studio Edit/BEV Calibration

> **Parent Roadmap**: `.TODO/tracking_studio_alerts_and_recording_parity_master_roadmap.md` (`Milestone 3`)
> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADR-23`), `docs/architecture/CURRENT_ARCHITECTURE.md`
> **Observations Addressed**: `OBS-024`, `OBS-025`, `OBS-026`, `OBS-027`, `OBS-038`, `OBS-039`, `OBS-041`, `DBG-03`
> **Execution Contract**: 1 Milestone per turn. Milestone 1 is active now; Milestones 2–3 are *Deferred to Next Turn / Milestone*. Every modified file must stay within modularity budgets (`<= 350L` soft, `<= 40L`/fn, routes `<= 25L`, plus strict test caps: `studio.js <= 349L`, `world_minimap.js <= 345L`, `studio_shape_editor.js <= 300L`, `index.html < 180L`). Zero new overlapping UI components (reuses `#modal-studio-zone`, `#modal-studio-tripwire`, `#btn-studio-bev-quad-toggle`, and `VideoTimelineLinks`).

---

## Architectural Pre-Flight & Invariants

1. **Lock Order & Non-Blocking I/O (`P0-2`, `DBG-03`)**:
   - Never acquire `VideoJobManager._lock`, `CameraPool._lock`, or run FFmpeg/SQLite I/O while holding `StreamRecordingController._lock`. Auto-transcode queuing runs strictly in `_post_finalize_outside_lock()`.
   - Active-recording checks in `POST /api/videos/{filename}/transcode` snapshot pool streams via `snapshot_pool_streams(pool)` and query `get_recording_status()` without nesting locks.
   - All `VideoTranscodeService.probe_video(...)` and synchronous transcode calls inside `async def` FastAPI routes (`dashboard/routers/videos.py`) execute via `await asyncio.to_thread(...)`.
2. **Modularity & Split-Before-You-Grow**:
   - Extract `dashboard/services/recording_transcode_helper.py` so `dashboard/services/stream_recording.py` (`334L`) and `dashboard/routers/video_jobs.py` (`344L`) remain strictly `<= 350L`.
   - Extract `dashboard/static/js/world_minimap_fov_helper.js` (loaded via `dashboard/static/partials/scripts_studio.html`, never touching `index.html` at `179L`) with a safe fallback in `world_minimap.js` (`344L`, capped `<= 345L` in tests).
   - Keep `intelligent_tracker/memory/_event_formatters.py` (`351L`) untouched—its `_attach_media_provenance()` already reads `video_filename` and `media_offset_sec` from event attributes and `metadata`.
3. **Backward Compatibility**:
   - `PipelineVideoWriter` preserves explicit caller-supplied `codecs=(...)` tuples (required by `tests/test_camera_recording.py`).
   - `StudioShapeEditor.renameShape(type, cameraId, oldName, providedName)` preserves direct rename when `providedName` is supplied (`tests/test_step4_studio_shape_editor_ui.py`), and opens the full Edit modal when invoked without `providedName`.
   - `VideoTimelineLinks.buildSeekInStudioButtonHtml(videoFilename, offsetSec)` preserves its export name, `.btn-seek-studio` class, and `data-video-filename` / `data-offset-sec` attributes (`tests/test_step5_timeline_ticks_and_deeplinks.py`).

---

## Milestone 1: Web-Playable H.264 Recording, Active-Recording `409` Guard & Non-Blocking `ffprobe` *(Active)*

- [x] **intelligent_tracker/video/writers.py**: Update `DEFAULT_CODEC_FALLBACKS` to `("avc1", "mp4v", "MJPG", "XVID")` so web-playable H.264 is preferred first, and include `started_at` in `PipelineVideoWriter.snapshot()`.
- [x] **dashboard/services/recording_transcode_helper.py**: Create focused helper module (`<= 140L`) providing:
  - [x] `is_web_playable_codec(codec: str) -> bool` (`avc1`, `h264`, `x264`, `avc3`).
  - [x] `find_active_recording_for_file(filename: str, pool: Any, stream_manager: Any) -> dict[str, Any] | None` inspecting `snapshot_pool_streams(pool)` and primary `stream_manager` for active recordings matching basename or resolved path.
  - [x] `maybe_queue_h264_transcode(meta: dict[str, Any], job_mgr: Any = None, *, enabled: bool = True) -> str | None` queuing an async H.264 transcode job via `VideoJobManager` + `VideoTranscodeService.transcode_to_h264_async` when `meta` uses a non-H.264 codec and wrote `> 0` frames (graceful no-op when disabled, already H.264, or FFmpeg/job manager unavailable).
- [x] **dashboard/services/stream_recording.py**: Wire `maybe_queue_h264_transcode` inside `_post_finalize_outside_lock()` (outside `self._lock`), add optional `auto_transcode: bool = True` and `job_mgr_getter` constructor params, and record `transcode_job_id` in finalized metadata (`<= 350L`).
- [x] **dashboard/routers/video_jobs.py**: In `POST /api/videos/{filename}/transcode`, check `find_active_recording_for_file(safe_name, pool, sm)` and return HTTP `409 Conflict` before FFmpeg runs if the target file is actively recording (`OBS-038`); keep file `<= 350L` and `analyze_video <= 40L`.
- [x] **dashboard/routers/videos.py**: Offload `VideoTranscodeService.probe_video(...)` in `list_videos()` and `upload_video()` (plus `_handle_auto_transcode(...)` in `upload_video()`) using `await asyncio.to_thread(...)` (`DBG-03`).
- [x] **tests/test_step3_recording_provenance_and_studio_bev.py**: Add Milestone 1 unit tests covering `avc1`-first codec fallback, `stop()` auto-transcode queuing outside lock, `409` active-recording transcode guard, and non-blocking `asyncio.to_thread` `ffprobe` execution.

**Milestone 1 Verifier**:
- [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/video/writers.py dashboard/services/recording_transcode_helper.py dashboard/services/stream_recording.py dashboard/routers/video_jobs.py dashboard/routers/videos.py --max-lines 350 --max-fn-lines 40`
- [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step3_recording_provenance_and_studio_bev.py tests/test_camera_recording.py tests/test_video_pairing_and_layers.py tests/test_transcode_atomic_rollback.py tests/test_video_jobs.py`

---

## Milestone 2: Live Recording -> Alert & Sighting Clip Provenance + `#alerts` Clip Jump

- [x] **dashboard/services/recording_transcode_helper.py**: Add `get_active_recording_provenance(controller) -> tuple[str | None, float | None]` returning `(filename, started_at)` safely when actively recording.
- [x] **dashboard/services/stream_worker.py** & **intelligent_tracker/pipeline/frame_processor.py**: Propagate active recording `(filename, started_at)` from `StreamRecordingController` into `FrameProcessor` before `step()` so live ticks compute `media_offset_sec = max(0.0, now - started_at)` and populate `gallery_matcher.video_filename` / `current_media_offset_sec` (clearing them when recording stops; never disturbing offline `VideoIndexer` provenance).
- [x] **intelligent_tracker/analytics/zone_stats.py**, **intelligent_tracker/matching/_gallery_signals.py**, & **intelligent_tracker/pipeline/post_detection_governance.py**: Stamp `video_filename` and `media_offset_sec` into `metadata` of live zone, tripwire, occupancy, pet, entity-identified, and restricted-entity events and periodic sightings during active recording (`OBS-039`, `OBS-041`).
- [x] **dashboard/services/alerts_query_service.py**: Surface top-level `video_filename` and `media_offset_sec` from `event.metadata` in `_event_to_dict()` for EventBus fallback consistency.
- [x] **dashboard/static/js/video_timeline_links.js** & **dashboard/static/js/alerts_view.js**: Update `buildSeekInStudioButtonHtml(videoFilename, offsetSec)` to render `"▶ Clip @ MM:SS"` (preserving `.btn-seek-studio`, `data-video-filename`, `data-offset-sec`) and resolve paired `_h264.mp4` playback seamlessly when available (`OBS-039`, `OBS-041`).
- [x] **tests/test_step3_recording_provenance_and_studio_bev.py** & **tests/test_step3_studio_bev_frontend.py**: Add backend + Node VM tests verifying live alert/sighting clip provenance persistence and `#alerts` `"▶ Clip @ MM:SS"` deep-link rendering.

**Milestone 2 Verifier**:
- [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/services/recording_transcode_helper.py intelligent_tracker/pipeline/frame_processor.py intelligent_tracker/analytics/zone_stats.py intelligent_tracker/matching/_gallery_signals.py intelligent_tracker/pipeline/post_detection_governance.py dashboard/services/alerts_query_service.py dashboard/static/js/video_timeline_links.js dashboard/static/js/alerts_view.js --max-lines 350 --max-fn-lines 40`
- [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step3_recording_provenance_and_studio_bev.py tests/test_step3_studio_bev_frontend.py tests/test_step5_timeline_ticks_and_deeplinks.py tests/test_step2_alerts_governance_and_rules.py`
- [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run video_studio_contract_probe`

---

## Milestone 3: Studio Full Modal Editing, Calibrated BEV Cone Placement & `BEV Quad` Filtering *(Deferred to Next Turn / Milestone)*

- [ ] **dashboard/static/js/scenario_modals.js**: Add `openEditZoneModal(zone, cameraId, onUpdate)` and `openEditTripwireModal(tripwire, cameraId, onUpdate)` reusing `#modal-studio-zone` and `#modal-studio-tripwire` in edit mode (pre-filling name, category, dwell threshold, capacity limit, or bidirectional toggle and submitting `PUT` payloads) (`OBS-024`).
- [ ] **dashboard/static/js/studio_shape_editor.js** & **dashboard/static/studio.js**: Route `✏️` zone/tripwire edit clicks through `ScenarioModals.openEditZoneModal` / `openEditTripwireModal` (keeping `renameShape(..., providedName)` backward-compatible for legacy tests), wire `setBevQuadMode` to filter `#bev-minimap-canvas` by selected camera/mode, and bypass the `750ms` minimap throttle immediately after `saveHomographyCalibration()` (`OBS-024`, `OBS-027`). Keep `studio_shape_editor.js <= 300L` and `studio.js <= 349L`.
- [ ] **intelligent_tracker/world/minimap.py**, **intelligent_tracker/world/_minimap_render.py**, & **intelligent_tracker/world/_bridge_helpers.py**: Stagger uncalibrated cameras into deterministic non-overlapping slots instead of `(0, 0)`, tag entity telemetry with `calibrated: bool`, and exclude uncalibrated raw-pixel entities from `compute_world_bounds` (`OBS-025`).
- [ ] **intelligent_tracker/world/coordinates.py** & **dashboard/routers/scenarios.py**: Derive a default `CameraWorldPose` from the saved 4-point homography (`derive_pose_from_homography`) in `sync_homography_to_world()` and persist it on `POST /api/scenarios/homography` when no custom pose exists (`OBS-026`).
- [ ] **dashboard/static/js/world_minimap_fov_helper.js**, **dashboard/static/js/world_minimap.js**, & **dashboard/static/partials/scripts_studio.html**: Render `cam.fov_corners_global` polygons when calibrated (falling back to idealized cone arcs when uncalibrated) and support `bevQuadMode` (`'all' | 'selected' | 'off'`) filtering on `#bev-minimap-canvas` (`OBS-026`, `OBS-027`). Keep `world_minimap.js <= 345L` and `index.html < 180L`.
- [ ] **tests/test_step3_recording_provenance_and_studio_bev.py** & **tests/test_step3_studio_bev_frontend.py**: Add backend + Node VM tests for full Studio modal `PUT` editing, staggered uncalibrated cameras, raw-pixel entity exclusion from world bounds, homography-derived `CameraWorldPose`, `fov_corners_global` rendering, and `#btn-studio-bev-quad-toggle` minimap filtering.
- [ ] **CHANGELOG.md**: Record milestone completion via `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add`

**Milestone 3 Verifier**:
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/world/minimap.py intelligent_tracker/world/_minimap_render.py intelligent_tracker/world/_bridge_helpers.py intelligent_tracker/world/coordinates.py dashboard/routers/scenarios.py dashboard/static/js/scenario_modals.js dashboard/static/js/studio_shape_editor.js dashboard/static/studio.js dashboard/static/js/world_minimap_fov_helper.js dashboard/static/js/world_minimap.js --max-lines 350 --max-fn-lines 40`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step3_recording_provenance_and_studio_bev.py tests/test_step3_studio_bev_frontend.py tests/test_step4_studio_shape_editor_ui.py tests/test_step4_studio_ux_and_minimap.py tests/test_step4_minimap_interactions.py tests/test_step4_m3_world_minimap_and_journey.py`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run studio_drag_put_probe`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run video_studio_contract_probe`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run reversible_review_and_minimap_probe`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify --strict`

---

## Scenario Combinations Matrix

| Scenario | Trigger | Expected Outcome | Verifier |
| :--- | :--- | :--- | :--- |
| **H.264-First Writer + Auto-Transcode** | Record live frames where `avc1` falls back to `mp4v`, then call `stop()` | `DEFAULT_CODEC_FALLBACKS` tries `avc1` first; `stop()` queues async `_h264.mp4` job outside `_lock` and sets `transcode_job_id` | M1 (`test_step3_recording_provenance_and_studio_bev.py`) |
| **Active-Recording Transcode Guard** | Call `POST /api/videos/{active_clip}/transcode` while camera is recording | Returns HTTP `409 Conflict` immediately without invoking FFmpeg | M1 (`test_step3_recording_provenance_and_studio_bev.py`) |
| **Non-Blocking `ffprobe` in Videos API** | Call `GET /api/videos` and `POST /api/videos/upload` | `probe_video` executes via `asyncio.to_thread`, never blocking the event loop | M1 (`test_step3_recording_provenance_and_studio_bev.py`) |
| **Live Alert & Sighting Clip Provenance** | Trigger tripwire/zone alert & sighting during active recording, then open `#alerts` | Alert & sighting persist `(video_filename, media_offset_sec)`; `#alerts` renders `"▶ Clip @ MM:SS"` jump link | M2 (`video_studio_contract_probe`, `test_step3_studio_bev_frontend.py`) |
| **Studio Full Zone/Tripwire Modal Edit** | Click `✏️` on a zone or tripwire card in `#studio` | Opens `#modal-studio-zone` / `#modal-studio-tripwire` pre-populated; Save sends `PUT` with all fields | M3 (`studio_drag_put_probe`, `test_step3_studio_bev_frontend.py`) |
| **Uncalibrated Camera Stagger & Bounds** | Render minimap with 2 uncalibrated cameras + 1 calibrated camera + raw-pixel track | Uncalibrated cameras render at staggered slots (not `(0, 0)`); raw-pixel track excluded from world-meter bounds | M3 (`test_step3_recording_provenance_and_studio_bev.py`) |
| **Homography Pose Derivation & BEV Quad Toggle** | Save 4-point homography; cycle `#btn-studio-bev-quad-toggle` (`all -> selected -> off`) | Pose derived + persisted from `H`; `fov_corners_global` polygon rendered; minimap filters to selected camera / hides quads | M3 (`reversible_review_and_minimap_probe`, `test_step3_studio_bev_frontend.py`) |
