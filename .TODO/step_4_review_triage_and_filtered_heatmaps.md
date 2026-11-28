# Step 4: Review Queue Pagination/Triage, Filtered Historical Heatmaps & Tooling Guards

> **Parent Roadmap**: `.TODO/tracking_studio_alerts_and_recording_parity_master_roadmap.md` (`Milestone 4 of 4`, `ADR-23`)
> **Observations Addressed**: `OBS-043` (review pagination, matched/reason filters, confidence sort, bulk-dismiss, toast deep-link), `OBS-048` (review badge/counter pinned at 50 + toast HUD collision), `OBS-023` (filtered historical DB heatmap mode on `#analytics`), `DBG-01` prevention (AST method-kwarg parity guard in `system-diagnostics`).
> **Architecture & Modularity Guardrails**: All modified/new files must remain `<= 350L` soft / `< 500L` hard, classes `<= 12` methods, functions `<= 40L`, routes `<= 25L`. Near-limit files (`review_and_rsac.js` `339L`, `analytics_view.js` `337L`, `live_player.js` `347L`, `analytics_query_service.py` `299L`, `cross_module_rules.py` `323L`) must delegate new logic into focused sibling modules while preserving standalone fallbacks for legacy Node VM tests.

---

## Pre-Flight Architectural Summary

1. **Review Queue Contract (`OBS-043`, `OBS-048`)**:
   - `GET /api/review/queue` gains optional `offset` (`>= 0`), `matched` (`all|matched|unknown`), `reason` (e.g., `borderline`, `recurring_unknown`, `timeline_flag`, `tag_correction`), and `sort` (`newest|confidence_desc|confidence_asc`), returning `total_pending`, `total`, `offset`, `limit`, `count`, and `items`.
   - `POST /api/review/bulk-dismiss` (mounted *before* `/api/review/{item_id}`) dismisses either explicit `item_ids` or all matching pending rows for the active filter slice, recording `reviewed_by` and `reviewed_at` inside a rollback-guarded SQLite transaction.
   - `#header-review-badge`, `#drawer-review-badge`, and `#review-inbox-counter` display `data.total_pending ?? data.total ?? items.length` (backward-compatible with legacy `{ items }` test mocks).
   - `review_item_queued` toasts route clicks through `App.navigate('tab-review', { reviewId: ev.review_id })`, avoiding double-load via `skipReviewAutoLoad`, scrolling/highlighting `.review-card[data-item-id="<id>"]` (with single-item fetch fallback if off-page), and repositioning `.toast-container` to top-right clear of `#__frontier_hud__`.
2. **Filtered Historical Heatmaps (`OBS-023`)**:
   - `GET /analytics/heatmap` gains `mode=all|filtered` (default `all` preserves exact existing live `StreamManager` behavior & URL shape), plus `zone_id`, `event_type`, `range_sec`, `end_time`, and `entity_id`.
   - In `mode=filtered`, `dashboard/services/heatmap_history_service.py` queries `sightings` (top-level `bbox` JSON `[x, y, w, h]`) and `world_timeline_events` (`metadata_json.bbox`) matching the active filters (with normalized zone matching), projects bottom-center footpoints `(x + w/2, y + h)` onto a fresh `OccupancyHeatmap(decay_rate=None)`, and renders either JPEG (`format=image`) or grid/hotspot JSON (`format=json`) even when the live stream is idle/offline.
   - `analytics.html` keeps lazy `data-src="/analytics/heatmap"` (zero eager `src=`).
3. **AST Method-Kwarg Parity Guard (`DBG-01` Prevention)**:
   - Extend `<config_dir>/skills/system-diagnostics/scripts/signature_drift_rules.py` (`117L`) with `METHOD_KWARG_MISMATCH` checking calls both inside and outside `try/except`, flagging unexpected kwargs when receiver type is known or when zero repo-defined methods of that name accept the kwarg or `**kwargs` (verified at 0 false positives on `diagnose.py scan --strict`).

---

## Milestone 1: Review Queue Pagination, Filtering, Bulk-Dismiss & Toast Deep-Link (`OBS-043`, `OBS-048`) *(Active)*

- [x] **intelligent_tracker/repositories/learning_repo.py**: Add `_build_review_filter_sql(...)` helper (`<= 40L`), `count_review_items(status=None, matched=None, reason=None) -> int`, extend `list_review_items(status=None, limit=50, offset=0, matched=None, reason=None, sort="newest")` preserving backward-compatible defaults, and add `bulk_dismiss_review_items(item_ids=None, status="pending", matched=None, reason=None, reviewed_by="operator") -> int` with `self._conn.rollback()` on `sqlite3.Error`. Keep `LearningMixin <= 12` methods and file `<= 350L`.
- [x] **dashboard/routers/review.py**: Extend `GET /api/review/queue` (`<= 25L`) with `offset`, `matched`, `reason`, `sort` query params returning `{"status": "success", "count": len(items), "total": total, "total_pending": total_pending, "offset": offset, "limit": limit, "items": items}`. Add `BulkDismissRequest` schema and `POST /api/review/bulk-dismiss` mounted *before* `/api/review/{item_id}`.
- [x] **dashboard/static/partials/tabs/review.html**: Add compact triage filter controls (`#review-filter-matched`, `#review-filter-reason`, `#review-sort-select`), bulk-dismiss action (`#btn-review-bulk-dismiss`), and pagination footer (`#review-pagination-bar`, `#review-page-prev`, `#review-page-info`, `#review-page-next`) inside `#tab-review` without adding any overlapping modal/card component.
- [x] **dashboard/static/js/review_queue_controls.js**: Create focused helper module (`<= 180L`) managing review filter state (`status`, `matched`, `reason`, `sort`, `offset`, `limit`), pagination rendering/buttons, bulk-dismiss confirmation/POST, and `highlightReviewItem(reviewId)` card focus/scroll (with single-item fallback fetch if not on the current page). Load via `<script>` in `dashboard/static/index.html` before `review_and_rsac.js`.
- [x] **dashboard/static/review_and_rsac.js**: Wire `loadReviewQueue` to `ReviewQueueControls` (preserving standalone fallback for legacy Node VM tests), update `#header-review-badge`, `#drawer-review-badge`, and `#review-inbox-counter` using `data.total_pending ?? data.total ?? items.length`, and wire `review_item_queued` toast `"Review Candidate"` action to `App.navigate('tab-review', { reviewId: ev.review_id })`. Keep file `<= 350L`.
- [x] **dashboard/static/js/app_navigation.js**: Serialize/parse `review_id` (`reviewId`) in `buildHash()` / `paramsToSourceRef()`, add `tab-review` branch in `applySourceRef()` invoking `ReviewAndRSAC.openReviewItem(ref.reviewId)`, and pass `skipReviewAutoLoad: true` when navigating with a `reviewId`.
- [x] **dashboard/static/app.js**: Respect `opts.skipReviewAutoLoad` in `handleTabLifecycle()` for `tab-review` (matching `skipTimelineAutoLoad`) so deep-linked review navigation never double-fetches.
- [x] **dashboard/static/css/toast.css**: Reposition `.toast-container` to top-right (`top: 72px; right: 24px; bottom: auto; z-index: 1050;`) and add `.review-card-highlight` accent styling so `"Review Candidate"` toasts stay clear of `#__frontier_hud__` (`bottom: 16px; right: 16px`).
- [x] **tests/test_step4_review_triage_and_filtered_heatmaps.py**: Add Part 1 unit + FastAPI TestClient + Node VM tests covering `> 50` pending items (`total_pending=65`), `offset`/`matched`/`reason`/`sort` filtering, `POST /api/review/bulk-dismiss`, toast `ev.review_id` deep-link + highlight, and top-right toast positioning.

### Verifier (Milestone 1)
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/repositories/learning_repo.py dashboard/routers/review.py dashboard/static/partials/tabs/review.html dashboard/static/js/review_queue_controls.js dashboard/static/review_and_rsac.js dashboard/static/js/app_navigation.js dashboard/static/app.js dashboard/static/css/toast.css tests/test_step4_review_triage_and_filtered_heatmaps.py --max-lines 350 --max-fn-lines 40`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step4_review_triage_and_filtered_heatmaps.py tests/test_step4_p2_frontend_contracts.py tests/test_step4_m4_review_studio_sync.py tests/test_step4_reversible_review.py tests/test_step2_sourceref_and_context.py`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify --strict`

---

## Milestone 2: Filtered Historical DB Heatmaps (`OBS-023`) *(Deferred to Next Turn / Milestone)*

- [ ] **dashboard/services/heatmap_history_service.py**: Create focused service (`<= 250L`) querying `sightings` (`bbox` JSON `[x, y, w, h]`) and `world_timeline_events` (`metadata_json.bbox`) with `camera_id`, normalized `zone_id`, `event_type`, `range_sec`/`end_time`, and `entity_id` filters; project bottom-center footpoints onto `OccupancyHeatmap(width, height, decay_rate=None)` to return JPEG bytes (`build_filtered_heatmap_jpeg`) and JSON metadata (`build_filtered_heatmap_json` reusing `_downsample_heatmap_grid` / `_build_heatmap_hotspots`).
- [ ] **dashboard/services/analytics_query_service.py**: Expose shared grid/hotspot builders cleanly for `heatmap_history_service.py` while keeping `build_heatmap_json(mgr, camera_id)` backward-compatible and file `<= 350L`.
- [ ] **dashboard/routers/analytics.py**: Extend `GET /analytics/heatmap` (`<= 25L`) with `mode: str = Query("all")`, `zone_id`, `event_type`, `range_sec`, `end_time`, `entity_id`, and `db: TrackerDB = Depends(get_db)`. Preserve exact `mode="all"` live `StreamManager` behavior; dispatch `mode="filtered"` to `heatmap_history_service` (working even if the live stream is offline).
- [ ] **dashboard/static/partials/tabs/analytics.html**: Add `#analytics-heatmap-mode-select` (`All (Live)` / `Filtered (History)`) inside `.heatmap-actions` while preserving lazy `data-src="/analytics/heatmap"` with zero eager `src=`.
- [ ] **dashboard/static/js/analytics_view.js**: Add `buildHeatmapQueryParams()` / `getHeatmapMode()` helpers (extracting helper if approaching `350L`), propagate `mode`, `zone_id`, `event_type`, `range_sec`, `end_time` into `loadHeatmapMetadata()` and `#btn-download-heatmap`, and refresh the heatmap when flow filters change in `filtered` mode.
- [ ] **dashboard/static/js/live_player.js**: Update `attachHeatmapImage()` (`<= 350L` total) to use `AnalyticsView.buildHeatmapUrl(baseSrc)` when available, falling back to `camera_id` for legacy Node VM tests.
- [ ] **tests/test_step4_review_triage_and_filtered_heatmaps.py**: Add Part 2 backend + API + Node VM tests covering `mode=filtered` footpoint aggregation by `zone_id`/`event_type`/`range_sec`/`entity_id`, offline-camera fallback, `mode=all` backward compatibility, and `#analytics` UI filter propagation.

### Verifier (Milestone 2)
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/services/heatmap_history_service.py dashboard/services/analytics_query_service.py dashboard/routers/analytics.py dashboard/static/partials/tabs/analytics.html dashboard/static/js/analytics_view.js dashboard/static/js/live_player.js tests/test_step4_review_triage_and_filtered_heatmaps.py --max-lines 350 --max-fn-lines 40`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step4_review_triage_and_filtered_heatmaps.py tests/test_step4_m1_analytics_flows.py tests/test_step3_analytics_drilldown.py tests/test_dashboard.py tests/test_step2_sourceref_backend.py tests/test_step2_tab_scoped_streams.py`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify --strict`

---

## Milestone 3: `system-diagnostics` AST Method-Kwarg Guard & Master Roadmap Sign-Off *(Deferred to Next Turn / Milestone)*

- [ ] **<config_dir>/skills/system-diagnostics/scripts/signature_drift_rules.py**: Add `METHOD_KWARG_MISMATCH` AST guard inspecting method calls across all scopes (not only inside `try/except`), flagging unknown keyword arguments when receiver type is resolved OR when zero repo-defined methods with that name accept the kwarg or `**kwargs`, while avoiding false positives on dynamic/stdlib/mock receivers.
- [ ] **<config_dir>/skills/system-diagnostics/tests/test_cross_module_rules.py**: Add unit tests verifying `METHOD_KWARG_MISMATCH` catches `DBG-01`-style `record_zone_exit(..., track_id=tid)` drift, permits valid kwargs/`**kwargs`, and preserves existing `CALLABLE_SIGNATURE_DRIFT` checks.
- [ ] **docs/architecture/CURRENT_ARCHITECTURE.md**: Record Step 4 completed contracts (`#review` pagination/triage/bulk-dismiss/toast deep-link, `#analytics` filtered historical DB heatmaps, `METHOD_KWARG_MISMATCH` guard) and update changelog via `diagnose.py changelog add`.
- [ ] **Final Verification & Review Gate**: Run `diagnose.py scan --strict`, `diagnose.py probe run spa_nine_tab_cdp_probe`, `scripts/mini_ci.py --fast` (full `unittest` suite), `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`, and resolve `OBS-023`, `OBS-043`, `OBS-048` after fresh reviewer sign-off.

### Verifier (Milestone 3)
- `python -m unittest discover -s "<config_dir>/skills/system-diagnostics/tests" -p "test_*.py"`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" scan --strict`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run spa_nine_tab_cdp_probe`
- `python scripts/mini_ci.py --fast`
- `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`

---

## Scenario Combinations Matrix

| Scenario | Trigger | Expected Outcome | Verifier |
| :--- | :--- | :--- | :--- |
| **`> 50` Pending Review Items (`OBS-048`)** | Seed 65 pending review items; load `#review` page 1 (`limit=50, offset=0`) and click Next (`offset=50`) | Badges (`#header-review-badge`, `#drawer-review-badge`, `#review-inbox-counter`) display `65`; page 1 shows 50 items, page 2 shows 15 items | M1 (`test_step4_review_triage_and_filtered_heatmaps.py`) |
| **Review Filter, Sort & Bulk-Dismiss (`OBS-043`)** | Filter `matched=unknown`, `reason=recurring_unknown`, `sort=confidence_desc`; click Bulk Dismiss | Only matching unknown candidates render ordered by similarity; bulk-dismiss updates SQLite rows to `dismissed` and decrements `total_pending` | M1 (`test_step4_review_triage_and_filtered_heatmaps.py`) |
| **Toast `"Review Candidate"` Deep-Link & HUD Clearance (`OBS-043`, `OBS-048`)** | Receive `review_item_queued` event with `review_id=62`; click toast action | Toast renders top-right clear of `#__frontier_hud__`; click navigates via `App.navigate('tab-review', { reviewId: 62 })` without double-fetch and highlights card `62` | M1 (`test_step4_review_triage_and_filtered_heatmaps.py`) |
| **Filtered Historical DB Heatmap (`OBS-023`)** | Seed sightings in `zone_a` (left) and `zone_b` (right); switch `#analytics` heatmap to `Filtered (History)` with `zone_id=zone_b` | `/analytics/heatmap?mode=filtered&zone_id=zone_b` returns JPEG & JSON hotspot concentrated in `zone_b` (even if live stream is offline); `mode=all` preserves live heatmap | M2 (`test_step4_review_triage_and_filtered_heatmaps.py`) |
| **AST Method-Kwarg Parity Guard (`DBG-01`)** | Run `diagnose.py scan --strict` on synthetic `record_zone_exit(..., track_id=1)` mismatch and on live repo | Synthetic mismatch flags `METHOD_KWARG_MISMATCH`; live `intelligent_tracker` repo passes with `0` false positives | M3 (`test_cross_module_rules.py`, `diagnose.py scan --strict`) |
| **Full Regression & Docs Sign-Off** | Run `spa_nine_tab_cdp_probe`, `scripts/mini_ci.py --fast`, and Sphinx `-W` | All probes, full `unittest` suite, surface verification, and Sphinx docs build pass with 0 errors/warnings | M3 (Final Verifier) |
