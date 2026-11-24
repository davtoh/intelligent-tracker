# Step 3: `#timeline` Pagination & Source Links, `#analytics` Peak/Hotspot Drill-Down & `#alerts` Stateful Admin Lifecycle

> **Parent Roadmap**: `.TODO/reid_unification_traceability_and_studio_ux_master_roadmap.md` (`Step 3 of 4` | `--parent reid_unification_traceability_and_studio_ux_master_roadmap --milestone 3`).
> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–12`, `ADR-12`, Layers 1–5) & `docs/architecture/CURRENT_ARCHITECTURE.md` (`BUG-07`, `Ideas 2, 3a, 3b`).
> **Execution Rule**: Strict **1-Milestone-Per-Turn**. Execute Milestone 1 first via `/frontier-architect continue step_3_traceability_analytics_and_alerts`; Milestones 2, 3, and 4 are deferred to subsequent turns.

---

## Pre-Flight Architecture & Modularity Contract

### Hard Budget & Invariant Guards
- **Zero-Regression File & Method Budgets**:
  - `dashboard/routers/analytics.py <= 345L` (`331L` currently; keep route handlers `<= 25L` and delegate query/pagination helpers to `dashboard/services/analytics_query_service.py`).
  - `intelligent_tracker/repositories/analytics_repo.py <= 345L` (`341L` currently; extract sightings pagination/count/source helpers into `intelligent_tracker/repositories/sightings_query_helpers.py` so `AnalyticsMixin` stays `<= 12` methods).
  - `intelligent_tracker/repositories/memory_repo.py <= 325L` (`313L` currently; place new alert unread/facets/acknowledge/bulk-clear/export queries in a dedicated `intelligent_tracker/repositories/events_admin_repo.py` `EventsAdminMixin` composed into `TrackerDB` in `intelligent_tracker/database.py` `<= 135L`).
  - `dashboard/static/index.html < 180L` (`179L` currently; load new Step 3 scripts via a Jinja2 partial `dashboard/static/partials/scripts_traceability.html` replacing a blank/comment line so `index.html` stays `<= 179L` while preserving all existing `<script>` tags).
  - `dashboard/static/js/gallery_timeline.js <= 330L`, `dashboard/static/js/analytics_view.js <= 330L`, `dashboard/static/js/alerts_view.js <= 330L`, all new files (`events_admin.py`, `events_admin_service.py`, `events_admin_repo.py`, `analytics_drilldown.js`, `alerts_admin.js`) `<= 350L`, classes `<= 12` methods, functions `<= 40L`, zero CSS `!important`.
- **SQLite, Concurrency & Backward-Compatibility Invariants**:
  - Every SQLite write method in `events_admin_repo.py` MUST call `self._conn.rollback()` inside `except` before re-raising.
  - Apply `is_read` / `acknowledged_at` columns to `world_timeline_events` via idempotent `PRAGMA table_info` migration in `intelligent_tracker/repositories/memory_schema.py` without breaking `PRAGMA user_version = 1` assertions in `tests/test_memory_repository.py`.
  - Offload synchronous SQLite operations in `async def` FastAPI routes via `asyncio.to_thread(...)`.
  - Keep `GET /sightings` backward-compatible: return flat `list[dict]` when `paginated=False` and `offset == 0`; return `{"items", "total", "offset", "limit", "has_more"}` when `paginated=True` or `offset > 0` (matching `GET /events`).
  - Preserve lazy `#static-heatmap-img` `data-src` loading in `analytics.html` (no eager `src="/analytics/heatmap"` on cold boot) and `MediaEmptyState` fallback.
  - Keep `stream_telemetry.py` dual-clock safe: use `time.monotonic()` strictly for optional short unread-count query caching, never mixing wall-clock timestamps into monotonic deltas.

### Public Surface Contracts
- **Milestone 1 (`#timeline`)**:
  - `GET /sightings` query params: `entity_id`, `entity_name`, `zone_id`, `source`, `video_filename`, `start_time`, `end_time`, `limit` (`1..500`, default `50`), `offset` (`>= 0`, default `0`), `paginated` (`bool`, default `False`).
  - `GET /sightings/sources` -> `{"sources": [str, ...]}` (distinct non-empty sighting `source` values for `#timeline-source-select`).
  - Timeline UI IDs: `#timeline-source-select`, `#timeline-pagination-bar`, `#timeline-prev-btn`, `#timeline-page-info`, `#timeline-next-btn`, plus source badges and 1-click Live Monitor (`window.App.switchCamera` + `window.switchTab('tab-live')`) or Video Studio (`window.VideoTimelineLinks.seekToVideoTimestamp`) buttons on sighting cards.
- **Milestone 2 (`#analytics`)**:
  - `GET /analytics/flows` adds `bucket_end` to each bucket item plus `axes: {"x": {"label": "Time", "unit": "timestamp", "bucket_sec": int}, "y": {"label": "Crossings / Events", "unit": "count"}}`.
  - `GET /analytics/heatmap?format=json` adds `grid_size: [32, 24]`, `grid: list[list[float]]` (24 rows x 32 cols normalized `0.0..1.0`), `x_ticks: [0, 0.25, 0.5, 0.75, 1.0]`, and `y_ticks: [0, 0.25, 0.5, 0.75, 1.0]`.
  - Analytics UI: Chart.js explicit X/Y axis titles + peak click handler (`#trafficChart`) drilling down into filtered `#timeline`/`#alerts` for `[bucket_start, bucket_end]`; interactive `#heatmap-hotspot-canvas` overlay + `#heatmap-axis-x` / `#heatmap-axis-y` ticks clicking a `32x24` cell to drill down into the camera's filtered `#timeline` / `#alerts` / Live Monitor view.
- **Milestones 3 & 4 (`#alerts`)**:
  - `world_timeline_events` columns: `is_read INTEGER NOT NULL DEFAULT 0`, `acknowledged_at REAL DEFAULT NULL`.
  - Telemetry payload (`build_stream_telemetry` & `GET /api/events/facets`): includes real SQLite `unread_alert_count: int`.
  - `dashboard/routers/events_admin.py` (registered in `dashboard/app.py`):
    - `GET /api/events/facets` -> `{"cameras": [...], "event_types": [...], "zones": [...], "severities": ["critical", "warning", "info"], "unread_alert_count": int}`.
    - `PATCH /api/events/acknowledge` (`{"event_ids": list[int] | None, "mark_all": bool, "is_read": bool}`) -> `{"updated": int, "unread_alert_count": int}`.
    - `DELETE /api/events/{event_id}` -> `{"deleted": bool, "event_id": int, "unread_alert_count": int}` (`404` if missing).
    - `POST /api/events/clear` (`{"camera_id": ..., "severity": ..., "event_type": ..., "zone_id": ..., "read_only": bool}`) -> `{"deleted": int, "unread_alert_count": int}`.
    - `GET /api/events/export` (`format=csv|json` + optional filters) -> downloadable CSV/JSON response (`Content-Disposition: attachment`).
  - Alerts UI: `#alerts-filter-camera` populated from `/api/events/facets` (+ `/api/cameras` union), `#alerts-type-options` / `#alerts-zone-options` datalists, toolbar `#btn-alerts-mark-all-read`, `#btn-alerts-bulk-clear`, `#btn-alerts-export-csv`, `#btn-alerts-export-json`, per-row Mark Seen / Delete / Zone & Source deep-links, snapshot download in `#modal-snapshot-view`, and real `unread_alert_count` driving `#header-alert-badge` & `#drawer-alert-badge`.

---

## Milestone 1: `#timeline` Pagination, Source Filtering & Live/Studio Navigation *(Active Slice)*

- [x] **intelligent_tracker/repositories/sightings_query_helpers.py** + **intelligent_tracker/repositories/analytics_repo.py**: Extract sightings SQL builder (`build_sightings_query` with `offset`, `source`, `video_filename`), `count_sightings_sync`, and `list_sighting_sources_sync` into `sightings_query_helpers.py`; wire `get_sightings(..., offset=0)`, `count_sightings(...)`, and `list_sighting_sources()` on `AnalyticsMixin` while keeping `analytics_repo.py <= 345L` and `<= 12` methods.
- [x] **dashboard/services/analytics_query_service.py** + **dashboard/routers/analytics.py**: Add `query_sightings_page(...)` in `analytics_query_service.py` supporting `offset`, `source`, `video_filename`, and `paginated=True` (`{items, total, offset, limit, has_more}` while preserving flat `list[dict]` default when `paginated=False and offset == 0`); update `GET /sightings` and add `GET /sightings/sources` in `dashboard/routers/analytics.py` (`<= 345L`, `asyncio.to_thread`).
- [x] **dashboard/static/partials/tabs/timeline.html** + **dashboard/static/js/gallery_timeline.js**: Add `#timeline-source-select` filter and `#timeline-pagination-bar` (`#timeline-prev-btn`, `#timeline-page-info`, `#timeline-next-btn`) to `timeline.html`; update `gallery_timeline.js` to paginate via `GET /sightings?paginated=true&offset=...&source=...`, populate `#timeline-source-select` from `/sightings/sources`, render explicit Source badges, and provide 1-click jump buttons to Live Monitor (`switchTab('tab-live')` + `App.switchCamera(source)`) or Video Studio (`seekToVideoTimestamp(video_filename, media_offset_sec)`), plus expose `window.TimelineView.applyFilter(...)` for cross-tab drill-down.
- [x] **tests/test_step3_timeline_pagination.py**: Add isolated unit, FastAPI `TestClient`, and Node VM tests (`<= 40L`/method) covering `offset`/`source`/`video_filename`/`paginated=true` mode, legacy flat-list default, `/sightings/sources`, Prev/Next page state transitions, and Live/Video Studio jump actions.

---

## Milestone 2: `#analytics` Explicit X/Y Axes, `32x24` Heatmap Grid & Peak/Hotspot Drill-Down *(Deferred to Next Turn / Milestone 2)*

> *Deferred to Next Turn / Milestone 2*

- [x] **intelligent_tracker/repositories/analytics_flow_helpers.py** + **dashboard/services/analytics_query_service.py**: Add `bucket_end` to every flow bucket and `axes` (`x`/`y` labels & units) to `query_traffic_flows_sync()`; extend `build_heatmap_json()` to compute normalized `32x24` grid density (`grid_size`, `grid`, `x_ticks`, `y_ticks`) from `hm.density` safely when initialized or empty.
- [x] **dashboard/static/partials/tabs/analytics.html** + **dashboard/static/partials/scripts_traceability.html** + **dashboard/static/index.html**: Add `#heatmap-stage-wrap` with `#heatmap-hotspot-canvas` overlay and `#heatmap-axis-x` / `#heatmap-axis-y` scale ticks around `#static-heatmap-img` (preserving lazy `data-src` and `MediaEmptyState`); include `partials/scripts_traceability.html` in `index.html` while keeping `index.html < 180L`.
- [x] **dashboard/static/js/analytics_drilldown.js** + **dashboard/static/js/analytics_view.js**: Create `analytics_drilldown.js` (`<= 250L`) implementing `#trafficChart` peak click -> filtered `#timeline`/`#alerts` drill-down for `[bucket_start, bucket_end]` and `#heatmap-hotspot-canvas` `32x24` hover tooltip + cell click drill-down (HiDPI CSS-dimension hit-testing); wire explicit Chart.js X/Y axis titles and drill-down callbacks in `analytics_view.js` (`<= 330L`).
- [x] **tests/test_step3_analytics_drilldown.py**: Add isolated unit, FastAPI `TestClient`, and Node VM tests (`<= 40L`/method) verifying `bucket_end`/`axes` on `/analytics/flows`, `32x24` normalized `grid` + ticks on `/analytics/heatmap?format=json`, lazy `data-src` invariant, and Chart.js peak + heatmap hotspot click drill-downs.

---

## Milestone 3: `#alerts` Unread State (`is_read`/`acknowledged_at`), Real Telemetry Count & Admin API *(Deferred to Next Turn / Milestone 3)*

> *Deferred to Next Turn / Milestone 3*

- [x] **intelligent_tracker/repositories/memory_schema.py** + **intelligent_tracker/repositories/memory_repo.py**: Add idempotent `PRAGMA table_info(world_timeline_events)` migration adding `is_read INTEGER NOT NULL DEFAULT 0` and `acknowledged_at REAL DEFAULT NULL` plus `idx_world_timeline_unread ON world_timeline_events(is_read, timestamp)` (preserving `PRAGMA user_version = 1`); include `is_read` and `acknowledged_at` in `search_timeline_events` / `get_timeline_event` row dicts.
- [x] **intelligent_tracker/repositories/events_admin_repo.py** + **intelligent_tracker/repositories/__init__.py** + **intelligent_tracker/database.py**: Create `EventsAdminMixin` (`<= 12` methods, `self._conn.rollback()` on every write error) implementing `count_unread_timeline_events()`, `get_timeline_event_facets()`, `acknowledge_timeline_events(event_ids=None, mark_all=False, is_read=True)`, `clear_timeline_events(camera_id=None, severity=None, event_type=None, zone_id=None, read_only=False)`, and `export_timeline_events(...)`; compose into `TrackerDB` (`database.py <= 135L`).
- [x] **dashboard/services/events_admin_service.py** + **dashboard/routers/events_admin.py** + **dashboard/routers/__init__.py** + **dashboard/app.py**: Implement `events_admin_service.py` (CSV/JSON formatting, camera-pool union for facets, safe rollback/error handling) and `events_admin.py` (`GET /api/events/facets`, `PATCH /api/events/acknowledge`, `DELETE /api/events/{event_id}`, `POST /api/events/clear`, `GET /api/events/export`); register `events_admin_router` in `dashboard/app.py`.
- [x] **dashboard/services/stream_telemetry.py** + **dashboard/services/alerts_query_service.py**: Emit real SQLite `unread_alert_count` in `build_stream_telemetry()` (using a short `time.monotonic()` cache TTL with safe `0` fallback when `db` is absent/closed) and include `unread_alert_count` in paginated `GET /events` responses.
- [x] **tests/test_step3_alerts_backend.py**: Add isolated SQLite, concurrency/rollback, and FastAPI `TestClient` tests (`<= 40L`/method) covering `is_read`/`acknowledged_at` migration, `unread_alert_count` in telemetry, `/api/events/facets`, `/api/events/acknowledge` (single/batch/mark_all/toggle), `DELETE /api/events/{id}` (`200`/`404`), `/api/events/clear`, and `/api/events/export` (CSV & JSON).

---

## Milestone 4: `#alerts` Frontend Lifecycle, Real Badge Sync, Deep-Links & Step 3 Sign-Off *(Deferred to Next Turn / Milestone 4)*

> *Deferred to Next Turn / Milestone 4*

- [x] **dashboard/static/partials/tabs/alerts.html** + **dashboard/static/partials/scripts_traceability.html**: Add `#alerts-type-options` / `#alerts-zone-options` datalists, admin toolbar (`#btn-alerts-mark-all-read`, `#btn-alerts-bulk-clear`, `#btn-alerts-export-csv`, `#btn-alerts-export-json`), Actions table column, and load `alerts_admin.js` via `partials/scripts_traceability.html`.
- [x] **dashboard/static/js/alerts_admin.js** + **dashboard/static/js/alerts_view.js**: Create `alerts_admin.js` (`<= 260L`) handling `/api/events/facets` population (`#alerts-filter-camera`, type/zone datalists), Mark Seen / Mark All Seen (`PATCH /api/events/acknowledge`), Delete (`DELETE /api/events/{id}`), Bulk Clear (`POST /api/events/clear`), CSV/JSON export downloads, snapshot download button in `#modal-snapshot-view`, and Zone/Source deep-links (Live Monitor, Video Studio `@ media_offset_sec`, Scenario Studio); integrate into `alerts_view.js` (`<= 330L`) with unread row styling and `window.AlertsView.applyFilter(...)`.
- [x] **dashboard/static/app.js** + **dashboard/static/js/multiview/grid_tile_overlay.js** + **dashboard/static/js/app_ui_helpers.js**: Update `onTelemetryReceived()` and `refreshPoolAlerts()` to drive `#header-alert-badge` and `#drawer-alert-badge` from real `unread_alert_count` (falling back to unread items count only when legacy mock payloads omit `unread_alert_count`), eliminating the stuck `"8"` badge.
- [x] **tests/test_step3_alerts_ui.py** + **CHANGELOG.md**: Add Node VM and surface contract tests (`<= 40L`/method) verifying dynamic `#alerts-filter-camera` population, real unread badge sync (clearing to `0` on acknowledge, never stuck at `8`), delete/bulk-clear/export triggers, Zone/Source deep-links, and `0` `surface --verify` mismatches; record Step 3 completion via `python skills/system-diagnostics/scripts/diagnose.py changelog add`.

---

## Scenario Combinations Matrix

| Scenario | Verification Command | Expected Outcome |
| :--- | :--- | :--- |
| **Milestone 1 `#timeline` Pagination & Source Links** | `python skills/system-diagnostics/scripts/diagnose.py tests tests.test_step3_timeline_pagination tests.test_step1_reid_sightings_and_locks tests.test_step5_timeline_ticks_and_deeplinks tests.test_database` | `GET /sightings` returns paginated envelope on `paginated=true`/`offset>0` and flat list by default; source filter, Prev/Next paging, and Live/Video Studio jumps pass |
| **Milestone 2 `#analytics` Peak & `32x24` Hotspot Drill-Down** | `python skills/system-diagnostics/scripts/diagnose.py tests tests.test_step3_analytics_drilldown tests.test_step4_m1_analytics_flows tests.test_step2_tab_scoped_streams` | `/analytics/flows` includes `bucket_end` + `axes`; `/analytics/heatmap?format=json` includes `32x24` `grid` + ticks; peak & hotspot clicks drill down cleanly with lazy `data-src` intact |
| **Milestone 3 `#alerts` Backend Unread State & Admin API** | `python skills/system-diagnostics/scripts/diagnose.py tests tests.test_step3_alerts_backend tests.test_step4_m2_alerts_and_canvas tests.test_memory_repository tests.test_dashboard` | `is_read`/`acknowledged_at` migrate cleanly at `user_version=1`; telemetry emits real `unread_alert_count`; facets, acknowledge, delete, bulk clear, and CSV/JSON export pass |
| **Milestone 4 `#alerts` UI, Badge Fix & Full Step 3 Gate** | `python skills/system-diagnostics/scripts/diagnose.py tests tests.test_step3_alerts_ui tests.test_step4_m3_spa_and_video_contracts tests.test_step3_architecture_budgets; python skills/system-diagnostics/scripts/diagnose.py surface --verify --strict; python skills/system-diagnostics/scripts/diagnose.py scan --path intelligent_tracker dashboard scripts --strict; python skills/system-diagnostics/scripts/diagnose.py audit --path intelligent_tracker dashboard scripts; MPLBACKEND=Agg python -m unittest discover tests` | `#header-alert-badge`/`#drawer-alert-badge` reflect real unread count (0 when acknowledged), `#alerts-filter-camera` populated, `0` surface/scan defects, `index.html < 180L`, `100%` `unittest` pass |