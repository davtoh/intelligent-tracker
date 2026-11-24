# Step 4: `#studio` In-Place Zone/Tripwire Vertex Editing, Interactive 2D Minimap & Zero-GPU Scenario Re-Evaluation

> **Parent Roadmap**: `.TODO/reid_unification_traceability_and_studio_ux_master_roadmap.md` (`Step 4 of 4` | `--parent reid_unification_traceability_and_studio_ux_master_roadmap --milestone 4`).
> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–12`, `ADR-12`, Layers 1–5) & `docs/architecture/CURRENT_ARCHITECTURE.md` (`Idea 4`).
> **Execution Rule**: Strict **1-Milestone-Per-Turn**. Execute Milestone 1 first via `/frontier-architect continue step_4_studio_editing_minimap_and_reeval`; Milestones 2 and 3 are deferred to subsequent turns.

---

## Pre-Flight Architecture & Modularity Contract

### Hard Budget & Invariant Guards
- **Zero-Regression File & Method Budgets**:
  - `intelligent_tracker/scenarios.py < 230L` (`191L` currently) and `ScenarioManager <= 12` methods (`12/12` currently — do **not** add methods to `ScenarioManager`; place in-place edit/rename logic in `intelligent_tracker/scenario_edits.py`).
  - `intelligent_tracker/scenario_storage.py < 240L` (`236L` currently — do not expand).
  - `intelligent_tracker/repositories/spatial_repo.py <= 349L` and `SpatialMixin <= 12` methods (`12/12` currently — place atomic SQL `UPDATE` helpers in `intelligent_tracker/repositories/spatial_edit_helpers.py`).
  - `dashboard/routers/scenarios.py < 345L` (`301L` currently; keep `PUT` handlers `<= 20L`).
  - `dashboard/routers/video_jobs.py <= 345L` (`325L` currently; keep `POST /api/videos/re-evaluate-scenarios` `<= 20L` delegating to `dashboard/services/video_scenario_reeval_service.py`).
  - `dashboard/routers/topology.py < 240L` (`233L` currently; delegate world-map camera pruning to `dashboard/services/world_map_service.py`).
  - `dashboard/schemas.py <= 345L` (`338L` currently; place new Step 4 Pydantic request models in `dashboard/schemas_scenarios.py`).
  - `dashboard/static/studio.js <= 350L` (`349L` currently — do not expand; extract interactive editing into `dashboard/static/js/studio_shape_editor.js` and minimap interaction into `dashboard/static/js/world_minimap_interactions.js`).
  - `dashboard/static/index.html < 180L` (`177L` currently; group studio `<script>` tags into `dashboard/static/partials/scripts_studio.html` so `index.html` shrinks below `175L` while keeping `nav_tabs_manager.js` after `app.js`).
  - `dashboard/static/js/video_library.js` (`471L` — do not touch); place `"Re-evaluate Scenarios"` action in `dashboard/static/js/video_batch_reports.js` (`<= 348L`, or extract handler helper if needed).
  - All new files `<= 350L`, classes `<= 12` methods, functions `<= 40L`, zero CSS `!important`.
- **Concurrency, SQLite, Clock & Surface Invariants**:
  - Every SQLite write helper in `spatial_edit_helpers.py` MUST call `conn.rollback()` inside `except` before re-raising.
  - Offload synchronous SQLite/CPU work in `async def` FastAPI routes via `asyncio.to_thread(...)`.
  - Never hold `CameraPool._lock` across SQLite/disk I/O (`delete_world_pose` on `remove_camera` must run outside locks).
  - Historical `sightings` and `world_timeline_events` rows are **immutable**: in-place zone/tripwire vertex edits, renames, and 0-GPU video re-evaluations MUST NOT mutate or delete existing audit rows.
  - Keep `btn-` CSS variant suffixes separated from the `btn-` prefix in JS string literals so `surface --verify` does not misclassify them as missing HTML IDs.
  - Narrow `dict`-typed metadata fields before `.get()` for type safety.
  - HiDPI `<canvas>` hit-testing in `studio_shape_editor.js` and `world_minimap_interactions.js` MUST use CSS layout dimensions (`getBoundingClientRect()`), never raw backing-store dimensions.

### Public Surface Contracts
- **Milestone 1 (Backend APIs)**:
  - `PUT /api/scenarios/zones/{camera_id}/{zone_id}` (body: `ZoneUpdateRequest` with optional `name`, `polygon` `>= 3` pts in source-frame pixels, `category_filter`, `dwell_threshold`, `capacity_limit`, `color`) -> `200 {"status": "ok", "zone": {...}, "renamed_from": str | None}` (`404` if zone missing, `409` if target name collides on same camera). Preserves live `ZoneROI` counters (`current_occupants`, `total_entries`, `total_exits`, `max_occupancy`, `_threshold_breached`, `event_history`).
  - `PUT /api/scenarios/tripwires/{camera_id}/{tripwire_id}` (body: `TripwireUpdateRequest` with optional `name`, `line_segment` `>= 2` pts in source-frame pixels, `bidirectional`, `color`) -> `200 {"status": "ok", "tripwire": {...}, "renamed_from": str | None}` (`404` if missing, `409` on rename collision). Preserves live `Tripwire` counters (`total_in`, `total_out`, `last_crossed_time`, `event_history`).
  - `POST /api/videos/re-evaluate-scenarios` (body: `VideoReevalRequest` with optional `run_id`, `video_filename`, `camera_id`) -> `200 {"status": "ok", "run_id": str, "video_filename": str, "scenario_camera_id": str, "frames_evaluated": int, "zone_metrics": {...}, "tripwire_counts": {...}, "alerts_count": int, "report": {...}}` (`404` if run or cached detections missing). Runs at **0 GPU cost** (`frame=None`, `run_reid=False`) over `video_runs.frame_detections_json` and invalidates pool `CachedReplayProvider` caches.
- **Milestone 2 (`#studio` Shape Editor & Video Re-Eval UI)**:
  - `window.StudioShapeEditor` (`dashboard/static/js/studio_shape_editor.js`): idle-mode hit-testing on `#studio-drawing-canvas` (vertex drag, whole-shape drag, `Escape` cancel, `PUT` commit + rollback on error) and inline rename on `#studio-zones-list` / `#studio-tripwires-list`.
  - `#btn-reeval-report-run` in `.batch-report-actions` (`dashboard/static/js/video_batch_reports.js`): triggers `POST /api/videos/re-evaluate-scenarios` for the active run and refreshes the report card + `OverlayLayers`.
- **Milestone 3 (Stale-Camera Pruning & Interactive 2D Minimap)**:
  - `GET /api/topology/world-map`: excludes deleted/stale cameras absent from active `CameraPool.camera_configs` (while preserving standalone/test behavior when `pool is None`); `CameraPool.remove_camera()` cleans up `camera_world_poses` via `db.delete_world_pose(camera_id)`.
  - `window.WorldMinimapInteractions` (`dashboard/static/js/world_minimap_interactions.js`): click FOV cone on `#bev-minimap-canvas` to focus camera (`#studio-camera-select`), drag origin handle (`origin_x`/`origin_y`) or yaw/range tip handle (`yaw_deg`/`range_m`), suppress 250ms loop snap-back during drag, sync `#world-pose-*` inputs live, and commit `PUT /api/topology/world-pose/{camera_id}` on `mouseup`.

---

## Milestone 1: Non-Destructive `PUT` Zone/Tripwire Editing & Zero-GPU Video Scenario Re-Evaluation Backend *(Active Slice)*

- [x] **intelligent_tracker/repositories/spatial_edit_helpers.py** + **intelligent_tracker/scenario_edits.py**: Implement atomic SQLite `update_spatial_zone_sync` and `update_spatial_tripwire_sync` (with `conn.rollback()` on error and rename collision checks, never mutating `sightings`/`world_timeline_events`) in `spatial_edit_helpers.py`; implement `update_zone_in_place(...)` and `update_tripwire_in_place(...)` in `scenario_edits.py` mutating existing `ZoneROI`/`Tripwire` geometry and config in place (preserving live counters/occupants/history), re-keying on rename, updating `WorldGraph` nodes, and keeping `ScenarioManager <= 12` methods.
- [x] **dashboard/schemas_scenarios.py** + **dashboard/routers/scenarios.py**: Add `ZoneUpdateRequest`, `TripwireUpdateRequest`, and `VideoReevalRequest` in `schemas_scenarios.py`; expose thin `PUT /api/scenarios/zones/{camera_id}/{zone_id}` and `PUT /api/scenarios/tripwires/{camera_id}/{tripwire_id}` routes in `scenarios.py` (`< 345L`, `asyncio.to_thread`, `404`/`409` handling).
- [x] **dashboard/services/video_scenario_reeval_service.py** + **dashboard/routers/video_jobs.py**: Implement 0-GPU `reevaluate_video_run_scenarios(...)` hydrating `video_runs.frame_detections_json` via `FileDetectionReplayProvider._hydrate_replay_track`, running `evaluate_tracks_governance(..., frame=None, run_reid=False)` against current `ScenarioManager` + `RSACManager` rules on an isolated in-memory `EventBus`, updating `video_runs` via `db.update_video_run_payload()`, and invalidating pool replay caches; wire thin `POST /api/videos/re-evaluate-scenarios` route in `video_jobs.py` (`<= 345L`).
- [x] **tests/test_step4_scenario_edits_and_reeval.py**: Add isolated unit, SQLite rollback, and FastAPI `TestClient` tests (`<= 40L`/method) covering in-place `PUT` vertex edit & rename preserving live zone/tripwire counters, `404`/`409` responses, immutable `sightings`/`world_timeline_events`, and 0-GPU `POST /api/videos/re-evaluate-scenarios` updating `zone_metrics`, `tripwire_counts`, and `alerts` without touching GPU/video files.

---

## Milestone 2: Interactive `#studio` Shape Editor (`studio_shape_editor.js`) & Indexed Video `"Re-evaluate Scenarios"` UI *(Deferred to Next Turn / Milestone 2)*

> *Deferred to Next Turn / Milestone 2*

- [x] **dashboard/static/partials/scripts_studio.html** + **dashboard/static/index.html**: Extract the studio script group into `partials/scripts_studio.html` (including `studio_shape_editor.js` and `world_minimap_interactions.js` before `studio.js`) and include it in `index.html` so `index.html` stays `< 180L` and `nav_tabs_manager.js` remains after `app.js`.
- [x] **dashboard/static/js/studio_shape_editor.js** + **dashboard/static/js/studio_canvas.js** + **dashboard/static/js/studio_overlays.js** + **dashboard/static/studio.js**: Create `studio_shape_editor.js` (`<= 300L`) implementing idle-mode polygon/tripwire hit-testing, vertex handle drag, whole-shape drag, `Escape` cancel, `PUT` persistence with error rollback, and inline list rename; add `mousedown`/`mouseup` forwarding and overlay render hook in `studio_canvas.js` (`<= 260L`), inline Rename button in `studio_overlays.js` (`<= 250L`), and minimal hook in `studio.js` (keeping `<= 349L`).
- [x] **dashboard/static/js/video_batch_reports.js**: Add `#btn-reeval-report-run` (`"Re-evaluate Scenarios"`) in `.batch-report-actions` calling `POST /api/videos/re-evaluate-scenarios` for the active run, invalidating cached report state, and refreshing the report card + `OverlayLayers` (`<= 348L`).
- [x] **tests/test_step4_studio_shape_editor_ui.py**: Add Node VM and surface contract tests (`<= 40L`/method) covering idle-mode hit-testing, vertex drag `PUT`, shape move `PUT`, inline rename `PUT`, rollback on failed `PUT`, `#btn-reeval-report-run` trigger, and `index.html < 180L` budget.

---

## Milestone 3: Stale Camera Pruning, Interactive 2D Minimap Camera Cones & Step 4 / Master Sign-Off *(Deferred to Next Turn / Milestone 3)*

> *Deferred to Next Turn / Milestone 3*

- [ ] **dashboard/services/world_map_service.py** + **dashboard/routers/topology.py** + **dashboard/services/camera_pool.py**: Implement `build_filtered_world_map(...)` pruning deleted/stale cameras absent from active `CameraPool.camera_configs` (preserving `pool is None` test compatibility); wire into `GET /api/topology/world-map` (`topology.py < 240L`); delete persisted `camera_world_poses` row (`db.delete_world_pose(camera_id)`) outside locks when `CameraPool.remove_camera()` runs.
- [ ] **dashboard/static/js/world_minimap_interactions.js** + **dashboard/static/js/world_minimap.js**: Create `world_minimap_interactions.js` (`<= 280L`) implementing HiDPI pointer hit-testing on `#bev-minimap-canvas` (click FOV cone to focus camera in `#studio-camera-select`, drag origin handle for `origin_x`/`origin_y`, drag yaw/range tip handle for `yaw_deg`/`range_m`, suppress 250ms loop snap-back during drag, live-sync `#world-pose-*` inputs, commit `PUT /api/topology/world-pose/{camera_id}` on `mouseup`); expose bounds/drag-preview hooks in `world_minimap.js` (`<= 325L`).
- [ ] **tests/test_step4_minimap_interactions.py** + **CHANGELOG.md**: Add isolated FastAPI `TestClient` and Node VM tests (`<= 40L`/method) covering deleted-camera pruning from `/api/topology/world-map`, `remove_camera` world-pose cleanup, cone-click camera focus, and origin/yaw/range drag `PUT` persistence; record Step 4 completion via `python skills/system-diagnostics/scripts/diagnose.py changelog add`.

---

## Scenario Combinations Matrix

| Scenario | Precondition | Action | Expected Outcome |
| :--- | :--- | :--- | :--- |
| **In-place zone vertex drag** | Live zone `Lobby` has `total_entries=4`, `current_occupants={7: ...}` | `PUT /api/scenarios/zones/cam_1/Lobby` with updated `polygon` | `200`, vertices updated in DB & live `ZoneROI`, `total_entries == 4` and track `7` preserved |
| **Zone rename with historical logs** | Zone `Lobby` has prior `sightings` & `world_timeline_events` rows | `PUT /api/scenarios/zones/cam_1/Lobby` with `{"name": "Main_Lobby"}` | `200`, live `zones["Main_Lobby"]` preserves counters, `WorldGraph` node migrated, historical `sightings`/`world_timeline_events` remain untouched |
| **Zone rename collision / missing** | Zones `A` and `B` exist on `cam_1` | `PUT .../A` with `{"name": "B"}` or `PUT .../Missing` | `409 Conflict` on collision (with SQLite rollback); `404 Not Found` on missing |
| **In-place tripwire edit & rename** | Live tripwire `Gate` has `total_in=3`, `total_out=1` | `PUT /api/scenarios/tripwires/cam_1/Gate` with new `line_segment` & `name="North_Gate"` | `200`, geometry & key updated, `total_in == 3`, `total_out == 1` preserved |
| **0-GPU video scenario re-evaluation** | Indexed `video_run` has `frame_detections_json`; user edits zone in `#studio` | `POST /api/videos/re-evaluate-scenarios` (`run_id` or `video_filename`) | `200`, `zone_metrics`/`tripwire_counts`/`alerts` recomputed at 0 GPU cost (`frame=None`), `video_runs` updated, pool replay caches invalidated |
| **Deleted camera minimap pruning** | `cam_old` had a saved `camera_world_poses` row, then `remove_camera("cam_old")` ran | `GET /api/topology/world-map` | `cam_old` omitted from world map and removed from `camera_world_poses` |
| **Minimap cone click & handle drag** | 2 cameras rendered on `#bev-minimap-canvas` | Click `cam_2` cone; drag origin & yaw/range tip handles | `#studio-camera-select` focuses `cam_2`; `#world-pose-*` updates live without 250ms snap-back; `mouseup` sends `PUT /api/topology/world-pose/cam_2` |

---

## Verification Commands (OS-Agnostic)

```bash
# Targeted milestone tests (180s timeout guard)
python skills/system-diagnostics/scripts/diagnose.py tests tests/test_step4_scenario_edits_and_reeval.py tests/test_scenario_api.py tests/test_step4_preflight_budgets.py
python skills/system-diagnostics/scripts/diagnose.py tests tests/test_step4_studio_shape_editor_ui.py tests/test_step2_studio_minimap_gating.py tests/test_step3_architecture_budgets.py
python skills/system-diagnostics/scripts/diagnose.py tests tests/test_step4_minimap_interactions.py tests/test_step4_m3_world_minimap_and_journey.py

# Static contracts, modularity budgets & security scan
python skills/system-diagnostics/scripts/diagnose.py surface --verify --strict
python skills/system-diagnostics/scripts/diagnose.py scan --path intelligent_tracker dashboard scripts --strict
python skills/system-diagnostics/scripts/diagnose.py audit --path intelligent_tracker dashboard scripts

# Unmocked workspace probes & headless CDP layout sweep (pass --timeout 90 for spa_nine_tab_cdp_probe)
python skills/system-diagnostics/scripts/diagnose.py probe run cold_boot_world_probe
python skills/system-diagnostics/scripts/diagnose.py probe run replay_pipeline_probe
python skills/system-diagnostics/scripts/diagnose.py probe run video_studio_contract_probe
python skills/system-diagnostics/scripts/diagnose.py probe run spa_nine_tab_cdp_probe --timeout 90
python skills/system-diagnostics/scripts/diagnose.py ui --url "$APP_URL" --headless --capture-runtime --audit-layout --stability-ms 2000 --strict

# Full regression suite & docs sign-off (Milestone 3)
MPLBACKEND=Agg python -m unittest discover tests
python -m sphinx -W --keep-going documentation/ documentation/_build/html/
```
