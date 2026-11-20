# Integration Diagnostics Upgrade & Remediation Plan

> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` & `docs/architecture/CURRENT_ARCHITECTURE.md`.
> **Decision Basis**: `/grill-me` alignment (6/6 questions resolved):
> 1. **Sequence**: Upgrade diagnostic tooling & probes first, run `/app-debugger` in **Headless Background Sandbox** to establish a full failing baseline, then execute surgical fixes with closed-loop verification.
> 2. **Tooling Split**: Add universal static/contract checks to `system-diagnostics` (`surface --verify`, mixed clock-domain AST scan) **and** repo-specific end-to-end integration probes in `.diagnostics/probes/`.
> 3. **Baseline**: Commit `c158db0` is the clean baseline; remaining `CaptureWorkerMixin` clock-mix (`353L`) and `StreamWorker` FPS reporting go into Milestone 2.
> 4. **Unified Persistence & Zero-GPU Replay**: Merge persisted offline/DB alerts into `GET /events`, persist `video_filename` + `media_offset_sec` in `EventFTSIndex`/`memory_repo`, emit `entity_id` + `category`/`entity_category` in `Track.to_dict()`/`ReplayTrack`, fix `sync_world_bridge` + `REPLAY` scheduler tier + unindexed TTL re-check, and wire configured detector/Re-ID + media offsets into Video Studio ROI tagging.
> 5. **Scope**: Remediate all 13 verified integration/wiring/DI/replay/frontend bugs in this plan; defer legacy `high_objects.py`/`interactive.py` retirement and extra `ctl.py` subcommands to a separate follow-up.

---

## Milestone 1: Upgrade `system-diagnostics`, Add `.diagnostics/probes/`, & Capture `/app-debugger` Failing Baseline *(Completed)*

- [x] **skills/system-diagnostics/scripts/surface_scanners.py** + **skills/system-diagnostics/scripts/diagnose_cli.py** + **skills/system-diagnostics/tests/**: Add `diagnose.py surface --verify` (cross-referencing JS `getElementById` vs HTML/template IDs, JS `fetch()` paths vs FastAPI/Flask route patterns, and `window.*` reader/writer symmetry) with unit tests in `skills/system-diagnostics/tests/`.
- [x] **skills/system-diagnostics/scripts/shadow_prober.py** + **skills/system-diagnostics/tests/**: Add `MIXED_CLOCK_DOMAIN` AST rule detecting mixed `time.time()` and `time.monotonic()` calls inside scheduler/worker/timing modules, plus unit tests.
- [x] **.diagnostics/probes/cold_boot_world_probe.py** *(New)*: Probe booting `create_app()` against an isolated `TemporaryDirectory` DB/config/scenarios (including `video_file` cameras, DB/YAML zones/tripwires, and zero-stream DB routes) to assert cold-start `WorldGraph` sync, `AnalyticsScheduler` tiering, and `/api/*` health.
- [x] **.diagnostics/probes/replay_pipeline_probe.py** *(New)*: Probe running real `VideoSource` -> `StreamWorker` -> `CachedReplayProvider` / `AsyncInferenceWorker` -> `FrameProcessor` (>1280px frame) -> `WorldEntityBridge` -> `EventBus` with zero `SimpleNamespace` stubs.
- [x] **.diagnostics/probes/video_studio_contract_probe.py** *(New)*: Probe running `VideoIndexer` -> `TrackerDB` (`video_runs`, `world_timeline_events`, `GET /events`) -> Video Studio ROI tagging -> headless CDP check on `#videos`, `#studio`, `#alerts`, `#live` for HTTP `>= 400`, missing `window.*` writers, and `occurrences` vs `entities` schema mismatches.
- [x] **`/app-debugger` Baseline Run**: Run `diagnose.py surface --verify`, `diagnose.py scan --path intelligent_tracker dashboard scripts`, `diagnose.py probe run` across all 3 workspace probes, and headless CDP `--capture-runtime` against an isolated ephemeral server to record the verified **Red** Symptom-to-Root-Cause Matrix before edits.

---

## Milestone 2: Pipeline, Replay, `WorldGraph`, `EventFTSIndex`, & Router DI Fixes

- [x] **intelligent_tracker/video/capture_worker.py** + **dashboard/services/stream_worker.py** + **dashboard/services/stream_recording.py**: Unify `CaptureWorkerMixin` on `time.monotonic()` (and split helper so `capture_worker.py <= 350L`), report `vs.measured_fps` in `StreamWorker` telemetry/health when `step_res.fps <= 0`, skip `_encode_annotated_frame` in `capture_only` mode, and fix `StreamRecordingMixin` to read `video_source.source_fps` / `measured_fps` instead of non-existent `.fps`.
- [x] **intelligent_tracker/tracker/track.py** + **dashboard/services/file_detection_replay.py** + **dashboard/services/cached_replay_provider.py** + **intelligent_tracker/pipeline/post_detection_governance.py**: Emit `entity_id`, `category`, and `entity_category` in `Track.to_dict()` / `ReplayTrack`; pass `run_reid` into `sync_world_bridge()` so `CachedReplayProvider` syncs `WorldEntityBridge` at 0 GPU; add bounded TTL re-check on empty `FileDetectionReplayProvider.ensure_loaded()`.
- [x] **dashboard/services/async_inference_worker.py** + **intelligent_tracker/pipeline/frame_processor.py**: Record `scheduler.should_schedule_frame(..., is_replay=True)` so active replay cameras report `PriorityTier.REPLAY`; rescale `FrameProcessor.step(..., max_dim=1280)` output `tracks` back to original `frame` coordinates (or return scale metadata) so `AsyncInferenceWorker` + `StreamWorker` overlays stay aligned on `> 1280px` feeds.
- [x] **intelligent_tracker/scenario_storage.py** + **intelligent_tracker/scenarios.py**: Sync loaded DB/YAML zones and tripwires to `WorldGraph` during `ScenarioManager.load_scenarios()` / `apply_to_stream_manager()`.
- [x] **intelligent_tracker/memory/_event_formatters.py** + **intelligent_tracker/memory/fts_index.py** + **intelligent_tracker/repositories/memory_repo.py** + **dashboard/routers/analytics.py** + **dashboard/app.py**: Persist `video_filename` and `media_offset_sec` into `world_timeline_events`; merge persisted offline/timeline alerts into `GET /events`; switch `analytics.py` DB routes to `Depends(get_db)`; remove shadowed `/crops/{filename}` route; bind `ConfidenceEngine`/`WorldQueryEngine` in `app.state`; fix `videos.py` duplicate `operation_id`.
- [x] **dashboard/services/roi_recognition_service.py** + **dashboard/routers/tagging.py** + **intelligent_tracker/batch.py**: Pass `video_filename` and `media_offset_sec=timestamp_sec` in `record_sighting()`, use configured production detector/`osnet` extractor fallback for Video Studio ROI tagging, and wire `ConfidenceEngine`/`WorldGraph` hooks in `VideoIndexer` when provided.
- [x] **tests/**: Add regression tests (`<= 40L`/method) covering every Milestone 2 fix and verify `diagnose.py probe run` + `diagnose.py tests`.

---

## Milestone 3: Frontend Integration Fixes, Static Cleanup, & Closed-Loop `/app-debugger` Sign-Off *(Deferred to Next Turn / Milestone)*

- [ ] **dashboard/static/js/scrubber_library_bridge.js** + **dashboard/static/js/video_timeline_links.js**: Fix `/api/videos/{filename}/report` -> `/api/videos/{filename}/reports` (unwrapping latest run `.report`), map `report.entities` + `report.alerts` (removing non-existent `occurrences`), and fix deep-link media path `/api/videos/{fn}` -> `/videos/{fn}`.
- [ ] **dashboard/static/js/bev_minimap.js** + **dashboard/static/app.js** + **dashboard/static/studio.js**: Feed live `active_tracks` into `BEVMinimap` (`window.latestTelemetry` or setter) and skip `/api/cameras/{id}/overlays` fetch + clear `#studio-live-img` when a recorded video is selected in Scenario Studio.
- [ ] **dashboard/static/partials/modals/camera_modals.html** + **dashboard/static/camera_manager.js** + **dashboard/static/js/camera_ai_config.js** + **dashboard/camera_pool.py**: Add `armed` toggle in Camera Manager UI, propagate `mgr.is_armed` updates to `AsyncInferenceWorker`, and gate boot `LivePlayer.attachLiveStream()` on active tab `=== 'tab-live'`.
- [ ] **dashboard/static/js/multiview/multiview_client.js** + **dashboard/services/process_supervisor.py**: Resolve active `DEFECT-001`/`DEFECT-002` (`SILENT_BARE_EXCEPT`) and Win32 `ctypes.Structure` `invalid_signature` audit warnings.
- [ ] **Closed-Loop Verification & Sign-Off**: Re-run all 3 `.diagnostics/probes/`, `diagnose.py surface --verify`, `diagnose.py scan --strict`, `diagnose.py audit`, headless CDP `--capture-runtime` across all tabs, full `unittest discover tests`, `sphinx -W`, and `diagnose.py changelog add`.

---

## Scenario Combinations Matrix

| Scenario | Verification Command | Expected Outcome |
|---|---|---|
| Global Diagnostics Self-Test | `python -m unittest discover -s skills/system-diagnostics/tests -p "test_*.py"` | 100% pass with new `surface --verify` and `MIXED_CLOCK_DOMAIN` tests |
| Cross-Contract Surface & Clock Scan | `diagnose.py surface --verify` and `diagnose.py scan --path intelligent_tracker dashboard scripts --strict` | 0 unmatched JS `fetch()` routes, 0 dead `window.*` reads, 0 mixed clock domains, 0 active defects |
| Integration Probes | `diagnose.py probe run cold_boot_world_probe` + `replay_pipeline_probe` + `video_studio_contract_probe` | Green after Milestones 2–3 (Red in Milestone 1 baseline) |
| Full Suite & Sphinx | `MPLBACKEND=Agg python -m unittest discover tests` and `python -m sphinx -W --keep-going documentation/ documentation/_build/html/` | 100% green, 0 Sphinx warnings |
