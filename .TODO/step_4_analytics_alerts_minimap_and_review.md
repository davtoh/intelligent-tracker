# Step 4: Real-Time Analytics Flows, Alerts Canvas & BEV Minimap, Journey Autocomplete & Review Loop

> **Parent Master Roadmap**: `.TODO/tracking_intelligence_ux_master_roadmap.md` (Step 4 of 4, `Ideas 5–8`, `ADR-09`)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` & `docs/architecture/CURRENT_ARCHITECTURE.md`
> **Execution Rule**: Strict **1-Milestone-Per-Turn**. Execute Milestone 1 first via `/frontier-architect continue step_4_analytics_alerts_minimap_and_review`; Milestones 2, 3, and 4 are deferred to subsequent turns.

---

## Pre-Flight Architecture & Modularity Contract

### Hard Budget & Invariant Guards (Verified via `diagnose.py arch-map`)
- **Zero-Regression Budgets** (`tests/test_step3_architecture_budgets.py`, `tests/test_refactor_contract.py`):
  - `dashboard/static/index.html < 180L` (currently `176L` -> add at most 2 `<script>` tags: `alerts_view.js` in M2 and `world_minimap.js` in M3 -> `<= 178L`; import new CSS via `dashboard/static/styles.css` or place in `dashboard/static/css/topology.css` / `dashboard/static/css/review.css`).
  - `dashboard/static/partials/modals/video_modals.html < 240L` (currently `233L` -> add `<= 3L` for `#snapshot-modal-canvas` + `#snapshot-modal-controls` -> `<= 236L`).
  - `dashboard/static/partials/tabs/*.html < 220L` (`analytics.html` `36L`, `alerts.html` `29L`, `studio.html` `93L`, `journey.html` `26L`, `review.html` `29L`).
  - `dashboard/static/studio.js <= 350L` (currently `347L` -> delegate world-map & pose controls to `dashboard/static/js/world_minimap.js`, `<= 2L` net change).
  - `dashboard/static/js/video_library.js` (`471L` WARN), `dashboard/routers/rsac.py` (`352L` WARN), `intelligent_tracker/repositories/spatial_repo.py` (`302L`, `12` methods) -> **do NOT grow**; place new code in dedicated submodules (`world_pose_repo.py`, `alerts_query_service.py`, `review_sync_service.py`, `dashboard/routers/review.py`).
  - Keep all new and modified files `<= 350L`, classes `<= 12` methods, functions `<= 40L`, routes `<= 25L`, and zero `!important` in CSS.
- **Database, Runtime & UI Invariants**:
  - Every write method in `intelligent_tracker/repositories/*_repo.py` MUST call `self._conn.rollback()` inside `except` before re-raising.
  - Offload sync SQLite calls in `async def` FastAPI routes via `asyncio.to_thread`; keep `HTTPConnection = None  # type: ignore[assignment]` for FastAPI connection injection and handle `DependsParam` in router helpers called directly by unit tests.
  - Keep `dashboard/static/partials/tabs/analytics.html` free of eager `src="/analytics/heatmap"` (`data-src` only, attached on `#tab-analytics` entry).
  - Preserve backward compatibility on `GET /events`: return flat `list[dict]` by default when `paginated=false` and `offset == 0`; return `{ items, total, offset, limit, has_more }` when `paginated=true` or `offset > 0`.
  - Reuse existing `UnifiedCanvasOverlay` and `OverlayControlBar` (`variant: 'scrubber'` feature pills with `descriptors: []` to avoid `#overlay-toggle-*` DOM ID collisions) inside existing `#modal-snapshot-view` without introducing overlapping UI controls.
  - Preserve standalone fallbacks in parent JS modules (`AnalyticsView.loadAlerts`, `BEVMinimap`) so legacy Node VM (`vm.runInNewContext`) tests remain green.

### Public Surface Contracts
- **Milestone 1 (`#analytics` Flows & Heatmap Legend)**:
  - `GET /analytics/flows?camera_id=&range_sec=3600&end_time=&bucket_sec=`: returns `{ camera_id, start_time, end_time, bucket_sec, buckets: [{ bucket_start, label, inflow, outflow, total, sightings }], totals: { inflow, outflow, total, sightings }, is_live }`.
  - `GET /analytics/heatmap?camera_id=&format=json`: preserves `{ density: [] }` when uninitialized while enriching metadata `{ initialized, camera_id, resolution: [w, h], max_value, mean_value, colormap, decay_rate, radius, stops: [{ ratio, color, label }] }`.
  - DOM IDs (`analytics.html`): `#analytics-range-select` (`15m|1h|6h|24h|7d`), `#btn-analytics-prev`, `#btn-analytics-next`, `#btn-analytics-live`, `#analytics-window-label`, `#heatmap-legend-min`, `#heatmap-legend-mid`, `#heatmap-legend-max`, `#heatmap-meta-summary`.
- **Milestone 2 (`#alerts` Filters/Pagination & Reused Canvas)**:
  - `GET /events?camera_id=&severity=&event_type=&zone_id=&start_time=&end_time=&limit=50&offset=0&paginated=false`: returns flat `list[dict]` when `paginated=false` and `offset == 0`; returns `{ items, total, offset, limit, has_more }` when `paginated=true` or `offset > 0`.
  - `ZoneEvent` formatter (`intelligent_tracker/memory/_event_formatters.py`): preserves `bbox` inside `metadata_json` alongside `UnattendedItemAlert` so `#alerts` snapshot previews can draw normalized/pixel boxes on `#snapshot-modal-canvas`.
  - DOM IDs (`alerts.html` + `video_modals.html`): `#alerts-filter-camera`, `#alerts-filter-severity`, `#alerts-filter-type`, `#alerts-filter-zone`, `#alerts-filter-start`, `#alerts-filter-end`, `#btn-alerts-apply`, `#btn-alerts-reset`, `#btn-alerts-prev`, `#btn-alerts-next`, `#alerts-page-indicator`, `#snapshot-modal-canvas`, `#snapshot-modal-controls`.
- **Milestone 3 (`WorldTacticalMinimap` & `#journey` Autocomplete)**:
  - Table `camera_world_poses(camera_id TEXT PK, origin_x REAL, origin_y REAL, yaw_deg REAL, scale REAL, updated_at TIMESTAMP)` in `world_pose_repo.py`.
  - `GET /api/topology/world-pose`: returns all persisted/live camera world poses `{ poses: [...] }`.
  - `PUT /api/topology/world-pose/{camera_id}`: validates and persists `{ origin_x, origin_y, yaw_deg, scale }`, updates `GlobalCoordinateMapper` + `CameraNode`, and returns `{ status: "updated", pose }`.
  - `GET /api/topology/world-map`: `entities[]` adds velocity vectors `{ vx, vy, speed_mps, heading_deg }` derived from trajectory/track kinematics.
  - `GET /api/entities/suggest?q=&limit=8`: returns `{ query, suggestions: [{ entity_id, name, category, match_type, thumbnail_url }] }` ranked prefix-first then substring.
  - DOM IDs (`studio.html` + `journey.html`): `#world-pose-camera-select`, `#world-pose-origin-x`, `#world-pose-origin-y`, `#world-pose-yaw-deg`, `#world-pose-scale`, `#btn-save-world-pose`, `#journey-suggest-list`.
- **Milestone 4 (Bidirectional `#review` <-> Video Studio Sync)**:
  - `review_queue` migration: adds `bbox_json TEXT`, `frame_width INTEGER`, `frame_height INTEGER`, `run_id TEXT`.
  - `GET /api/review/queue` + `POST /api/review/{item_id}/{confirm|reassign|enroll-new|dismiss}` (clean `/api/review` router alongside `/api/active-learning/*` compatibility) returning `{ ..., synced_runs: [...] }`.
  - Video Studio tag commit (`POST /api/tag/commit`) and discourage (`POST /api/tag/discourage`) auto-resolve matching `review_queue` items (`auto_resolved_review_ids`); `#review` resolution updates matching `video_runs` track labels so Studio reports and caches stay synchronized.

---

## Milestone 1: `#analytics` Time-Bucketed Flows, Range Navigation & Rich Heatmap Legend *(Active Slice)*

- [x] **intelligent_tracker/repositories/analytics_repo.py**: Add `get_traffic_flows(start_time, end_time, bucket_sec, camera_id=None)` aggregating SQLite `world_timeline_events` (`tripwire_cross`, `zone_enter`, `zone_exit`) and `sightings` into integer time buckets with real `inflow`, `outflow`, `total`, `sightings`, and summary `totals` (keeping `analytics_repo.py <= 350L` and `<= 10` methods).
- [x] **dashboard/routers/analytics.py**: Add thin `GET /analytics/flows` (`camera_id`, `range_sec`, `end_time`, `bucket_sec`, offloaded via `asyncio.to_thread`) and enrich `GET /analytics/heatmap?format=json` with `camera_id`, `colormap`, `decay_rate`, `radius`, `initialized`, and `stops` (preserving `density: []` fallback).
- [x] **dashboard/static/partials/tabs/analytics.html, dashboard/static/css/analytics_alerts.css & dashboard/static/styles.css**: Add `#analytics-range-select` (`15m|1h|6h|24h|7d`), `#btn-analytics-prev`, `#btn-analytics-next`, `#btn-analytics-live`, `#analytics-window-label`, `#heatmap-legend-min`, `#heatmap-legend-mid`, `#heatmap-legend-max`, and `#heatmap-meta-summary` (keeping `#static-heatmap-img` using `data-src`, zero `!important`, `>= 8px` gaps, `tabular-nums`).
- [x] **dashboard/static/js/analytics_view.js**: Remove synthetic `0.6x`/`0.4x` math and static seed arrays; implement `loadTrafficFlows()` fetching `/analytics/flows`, time-window stepping, `"Back to Live"` mode toggle, and heatmap JSON metadata legend hydration.
- [x] **tests/test_step4_m1_analytics_flows.py**: Add isolated `TrackerDB` unit tests, FastAPI `TestClient` API tests, and Node VM tests verifying real time-bucketed flow counts, range pagination, `"Back to Live"` toggle, and heatmap legend rendering.

---

## Milestone 2: `#alerts` Server-Side Filters/Pagination & Reused `UnifiedCanvasOverlay` Preview

- [x] **intelligent_tracker/repositories/memory_repo.py & intelligent_tracker/memory/_event_formatters.py**: Add `severity` filter, `offset` pagination, and `count_timeline_events(...)` to `MemoryMixin`, and preserve `ZoneEvent.bbox` inside `metadata_json` in `format_zone_event()`.
- [x] **dashboard/services/alerts_query_service.py & dashboard/routers/analytics.py**: Create `alerts_query_service.py` (`<= 140L`) and extend `GET /events` with `camera_id`, `severity`, `event_type`, `zone_id`, `start_time`, `end_time`, `limit`, `offset`, `paginated` (keeping flat list default for legacy callers and `{ items, total, offset, limit, has_more }` when `paginated=true` or `offset > 0`).
- [x] **dashboard/static/partials/tabs/alerts.html & dashboard/static/partials/modals/video_modals.html**: Add `#alerts` filter bar and pagination controls, and layer `#snapshot-modal-canvas` + `#snapshot-modal-controls` inside existing `#modal-snapshot-view` (`video_modals.html <= 236L`).
- [x] **dashboard/static/js/alerts_view.js, dashboard/static/js/analytics_view.js & dashboard/static/index.html**: Extract `#alerts` filter/pagination controller into `window.AlertsView` (keeping `AnalyticsView.loadAlerts` delegating fallback), reuse `UnifiedCanvasOverlay` + `OverlayControlBar` (`variant: 'scrubber'`, `descriptors: []`) in `#modal-snapshot-view`, and load `alerts_view.js` in `index.html` (`<= 177L`).
- [x] **tests/test_step4_m2_alerts_and_canvas.py**: Add unit, FastAPI `TestClient`, and Node VM tests covering all `GET /events` filters, pagination envelope vs. legacy list compatibility, and `UnifiedCanvasOverlay` + `OverlayControlBar` reuse.

---

## Milestone 3: Calibrated `WorldTacticalMinimap` (`/api/topology/world-map`) & `#journey` Prefix Autocomplete

- [x] **intelligent_tracker/repositories/schema_manager.py, intelligent_tracker/repositories/world_pose_repo.py & intelligent_tracker/database.py**: Add `camera_world_poses` table and `WorldPoseMixin` (`<= 120L`, `<= 4` methods with `self._conn.rollback()` in `except`), composed into `TrackerDB` (leaving `spatial_repo.py` untouched).
- [x] **intelligent_tracker/world/minimap.py, intelligent_tracker/repositories/entity_repo.py & dashboard/routers/topology.py**: Emit velocity vectors (`vx`, `vy`, `speed_mps`) in `WorldTacticalMinimap`, add `EntityMixin.suggest_entities(query, limit)` (prefix-first ranking), and expose `GET /api/topology/world-pose`, `PUT /api/topology/world-pose/{camera_id}` (hydrated into `/api/topology/world-map`), and `GET /api/entities/suggest`.
- [x] **dashboard/static/js/world_minimap.js, dashboard/static/partials/tabs/studio.html, dashboard/static/studio.js, dashboard/static/css/topology.css & dashboard/static/index.html**: Implement `window.WorldTacticalMinimapView` consuming `/api/topology/world-map` (calibrated grid, FOV cones, zones, transitions, trajectories, velocity vectors, and pose editor controls) with `BEVMinimap` fallback, keeping `studio.js <= 349L` and `index.html <= 178L`.
- [x] **dashboard/static/partials/tabs/journey.html & dashboard/static/js/journey_search.js**: Add `#journey-suggest-list` autocomplete dropdown wired to `/api/entities/suggest` with debounced input, keyboard navigation (`ArrowUp`/`ArrowDown`/`Escape`/`Enter`), and direct `Enter`-key search submission on `#journey-search-query`.
- [x] **tests/test_step4_m3_world_minimap_and_journey.py**: Add unit, FastAPI `TestClient`, and Node VM tests for world pose persistence, velocity vectors, `/api/entities/suggest` prefix ranking, `WorldTacticalMinimapView`, and `#journey` autocomplete + `Enter` submit.

---

## Milestone 4: Bidirectional `#review` <-> Video Studio Loop, 9-Tab CDP E2E & Full Sign-Off

- [x] **intelligent_tracker/repositories/schema_manager.py, intelligent_tracker/repositories/learning_repo.py, intelligent_tracker/active_learning_triage.py & intelligent_tracker/active_learning.py**: Migrate `review_queue` with `bbox_json`, `frame_width`, `frame_height`, `run_id`; preserve `bbox` & frame dimensions during triage; add `auto_resolve_matching_review_items(...)` with `rollback()` in `except`.
- [x] **dashboard/services/review_sync_service.py, dashboard/routers/review.py, dashboard/routers/rsac.py, dashboard/routers/tagging.py, dashboard/services/roi_recognition_service.py, dashboard/services/negative_exemplar_service.py & dashboard/app.py**: Wire bidirectional sync (Video Studio tag/discourage auto-resolves matching `review_queue` items; `#review` confirm/reassign/enroll-new/dismiss updates matching `video_runs` track labels and returns sync metadata), keeping `rsac.py` frozen at `<= 352L`.
- [x] **dashboard/static/review_and_rsac.js, dashboard/static/js/review_modals.js, dashboard/static/js/interactive_canvas.js, dashboard/static/js/tag_feedback_actions.js & dashboard/static/css/review.css**: Render `object-fit: contain` thumbnails with bbox context & source provenance on `#review` cards, invalidate `VideoBatchReports` cache + refresh Studio/Gallery on resolution, and refresh `#review` badge/queue on Video Studio tag commit.
- [x] **tests/test_step4_m4_review_studio_sync.py & .diagnostics/probes/spa_nine_tab_cdp_probe.py**: Add unit/API/Node VM tests for bidirectional sync and extend `spa_nine_tab_cdp_probe.py` (keeping `<= 350L`) to exercise all Step 4 tabs (`#analytics`, `#alerts`, `#studio`, `#journey`, `#review`) end-to-end in headless Chrome.
- [x] **Full Master Roadmap Sign-Off**: Run `surface --verify --strict`, `scan --strict`, `audit`, all 4 workspace probes, full `unittest`, `arch-map`, `sphinx -W`, `diagnose.py changelog add`, and `plan_engine.py digest tracking_intelligence_ux_master_roadmap --backfill --write-scaffold`.

---

## Scenario Combinations Matrix

| Scenario | Precondition | Action | Expected Outcome |
| :--- | :--- | :--- | :--- |
| **`#analytics` Real Time-Bucketed Flows & Back to Live** | SQLite contains `tripwire_cross`, `zone_enter`, `zone_exit`, and `sightings` across multiple timestamps | Open `#analytics`, select `1h` range, click `Prev` (`#btn-analytics-prev`), then click `Back to Live` (`#btn-analytics-live`) | Chart renders SQLite bucket counts (zero `0.6x`/`0.4x` synthetic math), steps cleanly across historical windows, and resumes live polling when `Back to Live` is clicked |
| **`#analytics` Cold Boot & Heatmap Legend** | App boots on `#live` | Load SPA on `#live`, then switch to `#analytics` | Cold boot performs 0 eager heatmap fetches; entering `#analytics` loads `#static-heatmap-img` and hydrates `#heatmap-legend-min/mid/max` + camera metadata from `format=json` |
| **`#alerts` Multi-Filter & Snapshot Canvas** | DB holds events across cameras, severities, zones, and `ZoneEvent` with `bbox` | Filter by `severity=warning` + `camera_id`, click `Next` page, open snapshot preview modal | `GET /events` returns filtered page slice (`paginated=true`) while unpaginated legacy callers still receive a flat list; `#modal-snapshot-view` overlays bbox/metadata on `#snapshot-modal-canvas` controlled by reused `OverlayControlBar` pills |
| **Calibrated `WorldTacticalMinimap` & Pose Save** | Two cameras configured with homography and world poses | Open `#studio`, edit `origin_x`/`yaw_deg`, click Save Pose (`PUT /api/topology/world-pose/{id}`) | Pose persists in SQLite `camera_world_poses`, `/api/topology/world-map` emits calibrated polygons + velocity vectors, and `WorldTacticalMinimapView` renders unified world coordinates |
| **`#journey` Prefix Autocomplete & Enter Submit** | Gallery contains `Alice Vance` and `Alicia Keys` | Type `Al` in `#journey-search-query`, press `ArrowDown` + `Enter` (or press `Enter` directly) | `/api/entities/suggest?q=Al` returns ranked prefix matches in `#journey-suggest-list`; selection or `Enter` executes `/api/journey/search` immediately |
| **Bidirectional Video Studio <-> `#review` Sync** | Video analysis queued low-confidence track `T7` on `clip.mp4`; operator tags `T7` in Video Studio (or resolves item in `#review`) | Commit tag in Video Studio OR click Confirm/Reassign in `#review` | Video Studio tag commit auto-resolves matching pending `review_queue` item; `#review` resolution updates matching `video_runs` track labels and invalidates `VideoBatchReports` cache |

---

## Verification Commands (OS-Agnostic)

```bash
# Milestone 1 targeted audit & tests
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/repositories/analytics_repo.py dashboard/routers/analytics.py dashboard/static/partials/tabs/analytics.html dashboard/static/css/analytics_alerts.css dashboard/static/styles.css dashboard/static/js/analytics_view.js
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests.test_step4_m1_analytics_flows tests.test_dashboard tests.test_analytics tests.test_step1_event_loop_offload tests.test_step3_architecture_budgets

# Milestone 2 targeted tests
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests.test_step4_m2_alerts_and_canvas tests.test_dashboard tests.test_milestone2_integration_fixes tests.test_step2_unified_canvas_engine tests.test_step4_overlay_bar_hud_and_multiview_ai tests.test_step3_architecture_budgets

# Milestone 3 targeted tests
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests.test_step4_m3_world_minimap_and_journey tests.test_world_transitions tests.test_global_coordinates tests.test_journey tests.test_scenario_api tests.test_step2_studio_minimap_gating tests.test_step3_architecture_budgets

# Milestone 4 & Final Master Verification Gate
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests.test_step4_m4_review_studio_sync tests.test_active_learning tests.test_m9_api tests.test_step3_roi_recognition_api tests.test_step4_spa_nine_tab_e2e
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify --strict
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" scan --path intelligent_tracker dashboard scripts --strict
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker dashboard scripts --typecheck
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run cold_boot_world_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run replay_pipeline_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run video_studio_contract_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run spa_nine_tab_cdp_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" ui --url "$APP_URL" --headless --capture-runtime --audit-layout --stability-ms 2000 --strict
MPLBACKEND=Agg python -m unittest discover tests
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" arch-map --path .
python -m sphinx -W --keep-going documentation/ documentation/_build/html/
```
