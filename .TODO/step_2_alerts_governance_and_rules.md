# Step 2: Alerts SSOT Noise Elimination, Severity/Zone Parity, Dwell Window & Alert Promotion Rules

> **Parent Master Roadmap**: `.TODO/tracking_studio_alerts_and_recording_parity_master_roadmap.md` (Milestone 2 of 4)
> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADR-14`, `ADR-23`), `docs/architecture/CURRENT_ARCHITECTURE.md`
> **Target Observations & Defects**: `OBS-030`, `OBS-031`, `OBS-032`, `OBS-033`, `OBS-034`, `DBG-04`
> **Execution Rule**: 1-Phase-Per-Turn. Only **Milestone 1** is active on initial execution; Milestones 2–3 are deferred to subsequent turns via `/frontier-architect continue step_2_alerts_governance_and_rules`.

---

## Architectural Pre-Flight & Public Surface Invariants

### 1. Root Causes & Target Contracts
1. **`world_entity_state_changed` Flood & Unwired Write-Through (`OBS-030`, `DBG-04`)**:
   - `WorldEntityBridge.sync_camera_tracks()` runs at `0.5s` intervals and emits `EntityStateChangedEvent`, which `EventFTSIndex` currently persists to SQLite `world_timeline_events` because `state_event_cooldown` defaults to `0.0`.
   - `EventBus.set_write_through_handler()` exists in `intelligent_tracker/events/bus.py` but has zero production callers; `EventFTSIndex` subscribes asynchronously instead.
   - **Contract**: Default `EventFTSIndex(index_state_events=False, use_write_through=True)` so `world_entity_state_changed` stays in-memory on `EventBus` for live `WorldGraph` reactivity (`0` SQLite rows by default) while non-state events persist synchronously via `EventBus.set_write_through_handler` *before* dispatch/broadcast (`ADR-14`, `ADR-23`). In offline `video_analytics_service.py`, stamp `video_filename`/`media_offset_sec`/`run_id` *before* write-through persistence so batch provenance is never lost.
2. **Severity & Canonical Unscoped `zone_id` Parity (`OBS-031`, `OBS-032`)**:
   - `format_zone_event`, `format_tripwire_event`, `format_entity_state_event`, `format_identified_event`, `format_generic_event`, and `index_sighting`/`index_clip_caption` omit `metadata["severity"]` and `{severity}` in `tags`, while SQL filters match `json_extract(metadata_json, '$.severity')`.
   - Scoped `WorldGraph` node IDs (`"usb_0:zone:Room_right"`) leak into `world_timeline_events.zone_id` alongside unscoped `"Room_right"`, and SQL filters only perform exact `=` comparisons.
   - **Contract**: Every formatter writes canonical `severity` (`"critical" | "warning" | "info"`) into `metadata["severity"]` and `tags`, and normalizes `zone_id` through `normalize_zone_id()` (`"<cam>:zone:<name>" -> "<name>"`). `memory_repo._hydrate_row()` hoists `severity` to top-level `row["severity"]`. Query filters (`GET /events`, `events_admin_repo`, `alerts_query_service`) support canonical unscoped matching, case-insensitive substring (`LIKE`), comma-separated multi-term `zone_id`/`event_type`, and `min_severity` (`info` < `warning` < `critical`). `get_timeline_event_facets()` deduplicates normalized zone names.
3. **Dwell Window (`entry_time`, `exit_time`, `dwell_time`) (`OBS-033`)**:
   - `ZoneROI` tracks `occ["entry_time"]` internally but neither `geometry.zone_roi.ZoneEvent` nor `events.types.ZoneEvent` exposes `entry_time` / `exit_time`. In `#alerts`, `alerts_view.js` uses `ev.title || ev.summary`, hiding `summary` dwell text behind `"Zone dwell: <zone>"`.
   - **Contract**: Add optional `entry_time: float | None = None` and `exit_time: float | None = None` to both `ZoneEvent` dataclasses, populate in `ZoneROI`, forward in `zone_stats.py`, store in `format_zone_event()` metadata & summary, and render dwell duration + start/end window visibly in `#alerts`.
4. **DB-Backed Alert Promotion Rules & Policy (`OBS-034`, `DBG-04`)**:
   - `AlertRuleEngine` (`events/rules.py`) is static-YAML-only and `WorldPolicy` (`world/nodes.py`) is in-memory-only.
   - **Contract**: Migrate SQLite to `PRAGMA user_version = 6` (`alert_promotion_rules` + `alert_policy_settings` tables), add `AlertRulesMixin` (`repositories/alert_rules_repo.py`, rollback on `except`), wire `AlertPromotionEngine` (`events/promotion_engine.py`) into `EventFTSIndex` write-through & `CameraPool`/`WorldGraph`, expose `/api/alerts/rules` CRUD + `/api/alerts/policy` (`GET`/`PUT`), and add `#alerts` min-severity selector + collapsible Promotion Rules panel in `alerts.html` + `dashboard/static/js/alert_rules.js` (reusing `.glass-panel`, `.form-input`, `.btn-sm` — zero overlapping modals).

### 2. Modularity Budgets (Hard Enforced)
- `intelligent_tracker/repositories/memory_repo.py`: currently `322L` — keep `<= 350L` (extract filter clause builder helper into `intelligent_tracker/repositories/_event_filter_sql.py` if needed).
- `intelligent_tracker/repositories/schema_manager.py`: currently `315L` — keep `<= 330L` (`_migrate_user_version <= 40L` by delegating v6 to `alert_rules_schema.py`).
- `intelligent_tracker/events/bus.py`: currently `192L`, `13` methods — fix mypy annotation on `_queue` and do **not** add methods to `EventBus`.
- `dashboard/app.py`: currently `338L` — keep `<= 350L` (`+2L` router include).
- `dashboard/static/index.html`: currently `178L` — keep strictly `< 180L` (`+1L` script tag for `alert_rules.js`, zero extra blank lines).
- `dashboard/static/js/alerts_view.js` (`275L`), `alerts_admin.js` (`253L`), new `alert_rules.js` (`<= 240L`) — all `<= 350L`, functions `<= 40L`.

---

## Milestone 1: EventBus Write-Through, `world_entity_state_changed` Noise Elimination, Severity/Zone Parity & Dwell Window *(Active Slice)*

- [x] **intelligent_tracker/events/bus.py**: Add explicit type annotation on `self._queue` (`queue.Queue[BaseEvent]`) so `diagnose.py audit` passes mypy with zero errors; keep `EventBus` method count unchanged and preserve `set_write_through_handler()` semantics (synchronous persist before `_history` / `_queue` dispatch, attaching `event.db_id`).
- [x] **intelligent_tracker/geometry/zone_roi.py**: Add optional `entry_time: float | None = None` and `exit_time: float | None = None` fields to `ZoneEvent`; populate `entry_time=occ["entry_time"]` on `enter`/`dwell`/`exit` events and `exit_time=now` on `exit` events in `_handle_occupant_update` and `_handle_departed_occupants`.
- [x] **intelligent_tracker/events/types.py**: Add optional `entry_time: float | None = None` and `exit_time: float | None = None` fields to bus `ZoneEvent`.
- [x] **intelligent_tracker/analytics/zone_stats.py**: Forward `entry_time=z_ev.entry_time` and `exit_time=z_ev.exit_time` when constructing `BusZoneEvent` from `ZoneROI` events.
- [x] **intelligent_tracker/memory/_event_formatters.py**: Add `normalize_zone_id(zone_id)` (strips `<camera>:zone:` prefix to canonical unscoped zone name) and `resolve_event_severity(event, default="info")` (normalizing `"cleared"` -> `"info"`, accepting `"critical" | "warning" | "info"`). Update `format_zone_event`, `format_tripwire_event`, `format_entity_state_event`, `format_identified_event`, `format_security_event`, `format_generic_event`, and `format_unattended_item_event` so every document sets canonical `zone_id`, `metadata["severity"]`, and `{severity}` in `tags`. In `format_zone_event`, persist `entry_time`, `exit_time`, and `dwell_time` in `metadata` and include formatted dwell duration + window in `summary`.
- [x] **intelligent_tracker/memory/fts_index.py**: Add `index_state_events: bool = False` and `use_write_through: bool = True` parameters to `EventFTSIndex.__init__`; skip persisting `world_entity_state_changed` unless `index_state_events=True`; when `auto_attach=True` and `use_write_through=True`, register `self.handle_event` via `event_bus.set_write_through_handler(...)` (falling back to `subscribe()` only when `use_write_through=False` or handler unavailable). Stamp canonical `severity="info"` + `{severity}` tag in `index_sighting()` and `index_clip_caption()`, and normalize `zone_id`.
- [x] **dashboard/services/video_analytics_service.py**: Ensure offline batch provenance (`video_filename`, `media_offset_sec`, `run_id`) is stamped on events *before* write-through SQLite persistence (e.g., via a pre-persist wrapper around `event_fts_index.handle_event` passed to `set_write_through_handler`) so offline video runs retain full provenance under synchronous write-through.
- [x] **tests/test_world_query_engine.py**: Reconcile `TestEventFTSIndex` assertions with `ADR-23` (`index_state_events=False` default keeps `world_entity_state_changed` out of SQLite while `index_state_events=True` still verifies `state_event_cooldown` behavior).
- [x] **tests/test_step2_alerts_governance_and_rules.py**: Create focused Milestone 1 unit tests verifying: (1) `CameraPool` / `PipelineEngine` wire `EventBus.set_write_through_handler`, (2) `world_entity_state_changed` stays in-memory (`0` SQLite rows) while `ZoneEvent` persists synchronously with `event.db_id`, (3) all formatters emit canonical `severity` and unscoped `zone_id`, (4) `ZoneROI -> ZoneStats -> EventFTSIndex` preserves `entry_time`, `exit_time`, `dwell_time`, and (5) offline batch write-through preserves `video_filename`/`media_offset_sec`/`run_id`.

### Verifier
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/events/bus.py intelligent_tracker/geometry/zone_roi.py intelligent_tracker/events/types.py intelligent_tracker/analytics/zone_stats.py intelligent_tracker/memory/_event_formatters.py intelligent_tracker/memory/fts_index.py dashboard/services/video_analytics_service.py --max-lines 350 --max-fn-lines 40`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step2_alerts_governance_and_rules.py tests/test_world_query_engine.py tests/test_analytics.py tests/test_step1_seams_backend.py tests/test_step2_pool_singletons_and_locks.py`

---

## Milestone 2: DB Schema v6, Alert Promotion Rules Engine, Normalized/Multi-Term Filtering & REST CRUD *(Deferred to Next Turn / Milestone 2)*

- [ ] **intelligent_tracker/repositories/alert_rules_schema.py**: Define SQLite schema v6 (`alert_promotion_rules` and `alert_policy_settings` tables) and idempotent `ensure_alert_rules_schema(conn)` migration helper.
- [ ] **intelligent_tracker/repositories/schema_manager.py**: Bump `SCHEMA_VERSION` to `6` and add `_migrate_v6_alert_rules()` delegating to `ensure_alert_rules_schema()` (keeping `_migrate_user_version <= 40L` and file `<= 330L`).
- [ ] **intelligent_tracker/repositories/alert_rules_repo.py**: Implement `AlertRulesMixin` (`list_alert_rules`, `get_alert_rule`, `create_alert_rule`, `update_alert_rule`, `delete_alert_rule`, `get_alert_policy`, `update_alert_policy`; `<= 12` methods, `self._conn.rollback()` in `except` on every write) and compose into `intelligent_tracker/database.py` (`TrackerDB`).
- [ ] **intelligent_tracker/events/promotion_engine.py**: Implement `AlertPromotionEngine` that evaluates enabled DB rules (`event_type`, normalized/substring `zone_id`, optional `camera_id`, `min_dwell_time`, optional `category`) on incoming events during `EventFTSIndex` write-through, upgrading `severity` (never downgrading) and annotating `metadata["promoted_by_rule"]` / `tags`, with `reload()` on CRUD mutations and `WorldGraph.update_policy()` sync on policy updates. Wire into `CameraPool` (`dashboard/camera_pool.py`) and `EventFTSIndex` (`intelligent_tracker/memory/fts_index.py`).
- [ ] **intelligent_tracker/repositories/_event_filter_sql.py**: Extract shared SQL filter builder for `memory_repo.py` and `events_admin_repo.py` supporting: (1) canonical unscoped + case-insensitive substring (`LIKE`) + comma-separated multi-term `zone_id` and `event_type`, (2) exact `severity` and `min_severity` (`info`/`warning`/`critical` hierarchy), and (3) normalized zone facet deduplication.
- [ ] **intelligent_tracker/repositories/memory_repo.py**: Hoist `severity` (`meta.get("severity") or "info"`) onto top-level hydrated rows in `_hydrate_row()`, wire `_event_filter_sql` + optional `min_severity` parameter into `query_timeline_events` / `count_timeline_events` while staying `<= 350L`.
- [ ] **intelligent_tracker/repositories/events_admin_repo.py**: Wire `_event_filter_sql` into `_build_admin_filter_where` and normalize/deduplicate zone values in `get_timeline_event_facets()`.
- [ ] **dashboard/services/alerts_query_service.py**: Add `min_severity` support and parity for normalized/contains/multi-term `zone_id` & `event_type` in `query_events()` and `_matches_filters()`, and expose `min_severity` query param on `GET /events` in `dashboard/routers/analytics.py`.
- [ ] **dashboard/routers/alert_rules.py**: Add thin FastAPI CRUD routes (`GET/POST /api/alerts/rules`, `PUT/DELETE /api/alerts/rules/{rule_id}`, `GET/PUT /api/alerts/policy`, `<= 25L`/route) that reload `AlertPromotionEngine` and sync `WorldGraph.update_policy()`, and register router in `dashboard/app.py`.
- [ ] **tests/test_step2_alerts_governance_and_rules.py**: Extend tests to cover SQLite v6 migration, `AlertRulesMixin` CRUD + rollback guard, `AlertPromotionEngine` live promotion (`zone_dwell >= min_dwell -> warning/critical`), normalized/substring/multi-term `zone_id`/`event_type` & `min_severity` queries, and `/api/alerts/rules` + `/api/alerts/policy` REST endpoints.

### Verifier
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/repositories/alert_rules_schema.py intelligent_tracker/repositories/schema_manager.py intelligent_tracker/repositories/alert_rules_repo.py intelligent_tracker/repositories/_event_filter_sql.py intelligent_tracker/repositories/memory_repo.py intelligent_tracker/repositories/events_admin_repo.py intelligent_tracker/events/promotion_engine.py intelligent_tracker/database.py dashboard/services/alerts_query_service.py dashboard/routers/alert_rules.py dashboard/routers/analytics.py dashboard/app.py dashboard/camera_pool.py --max-lines 350 --max-fn-lines 40`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step2_alerts_governance_and_rules.py tests/test_step4_m2_alerts_and_canvas.py tests/test_events_rules.py`

---

## Milestone 3: `#alerts` Dwell Window Display, Min-Severity & Promotion Rules UI, Probe Hardening & Sign-Off *(Deferred to Next Turn / Milestone 3)*

- [ ] **dashboard/static/partials/tabs/alerts.html**: Add `#alerts-filter-min-severity` selector (`All / Warning+ / Critical`), placeholder hints for substring/multi-term zone/type filtering, and a collapsible `#alerts-rules-panel` (`<details class="glass-panel">`) for Alert Promotion Rules CRUD (list + inline add/toggle/delete form reusing `.form-input` / `.btn-sm`).
- [ ] **dashboard/static/js/alerts_view.js**: Display `ev.summary` / formatted dwell window (`entry_time -> exit_time · Xs`) instead of letting `ev.title` shadow `ev.summary` (`OBS-033`), pass `min_severity` to `GET /events`, and keep file `<= 350L`.
- [ ] **dashboard/static/js/alerts_admin.js**: Keep facet dropdown population deduplicated on canonical unscoped zone names and sync with `#alerts-filter-min-severity` Reset.
- [ ] **dashboard/static/js/alert_rules.js**: Create dedicated frontend controller for `/api/alerts/rules` and `/api/alerts/policy` (load/render rules, create/toggle/delete promotion rules, persist default `min_severity` policy), and include `<script src="/static/js/alert_rules.js"></script>` in `dashboard/static/index.html` (keeping `index.html < 180L`).
- [ ] **.diagnostics/probes/alerts_store_probe.py**: Harden probe to verify end-to-end: (1) `0` `world_entity_state_changed` rows in SQLite while in-memory `EventBus` receives them, (2) `severity=info|warning|critical` filter parity, (3) canonical unscoped + contains + multi-term `zone_id` filtering, (4) `zone_dwell`/`zone_exit` `entry_time`/`exit_time`/`dwell_time` persistence, and (5) custom DB promotion rule upgrading a matching dwell event to `warning`/`critical`.
- [ ] **tests/test_step2_alerts_governance_and_rules.py**: Add Node VM frontend contract tests for `alerts_view.js` dwell window rendering, `min_severity` filter query params, and `alert_rules.js` CRUD + policy persistence (keeping all test functions `<= 40L`; split into `tests/test_step2_alerts_governance_frontend.py` if file approaches `350L`).
- [ ] **Changelog & Review Gate**: Record milestone via `diagnose.py changelog add`, run `diagnose.py surface --verify --strict`, `diagnose.py probe run alerts_store_probe`, `diagnose.py scan --path ...`, and full unit/mini-CI regression before resolving `OBS-030`–`OBS-034` and `DBG-04`.

### Verifier
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/static/partials/tabs/alerts.html dashboard/static/js/alerts_view.js dashboard/static/js/alerts_admin.js dashboard/static/js/alert_rules.js dashboard/static/index.html .diagnostics/probes/alerts_store_probe.py tests/test_step2_alerts_governance_and_rules.py --max-lines 350 --max-fn-lines 40`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step2_alerts_governance_and_rules.py tests/test_step3_alerts_ui.py tests/test_step4_m2_alerts_and_canvas.py tests/test_step3_architecture_budgets.py`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run alerts_store_probe`
- `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify --strict`

---

## Scenario Combinations Matrix

| Scenario | Trigger | Expected Outcome | Verifier |
| :--- | :--- | :--- | :--- |
| **State Tick In-Memory Only (`OBS-030`)** | Publish 5 `EntityStateChangedEvent` ticks + 1 `ZoneEvent` on `CameraPool.event_bus` | Subscribers receive all 6 events; SQLite `world_timeline_events` has `0` `world_entity_state_changed` rows and `1` `zone_dwell` row with `event.db_id` set synchronously | M1 (`test_step2_alerts_governance_and_rules.py`, `alerts_store_probe`) |
| **Write-Through Offline Provenance (`DBG-04`)** | Run offline `video_analytics_service` event emission with write-through enabled | Persisted SQLite row retains `video_filename`, `media_offset_sec`, and `run_id` | M1 (`test_step2_alerts_governance_and_rules.py`) |
| **Severity Filter Parity (`OBS-031`)** | Emit `ZoneEvent`, `TripwireCrossEvent`, `OccupancyThresholdEvent`, `SecurityEvent(critical)` | Every row carries explicit `metadata.severity` & tag; `GET /events?severity=info` returns all info rows; `min_severity=warning` returns warning+critical only | M1/M2 (`test_step2_alerts_governance_and_rules.py`, `alerts_store_probe`) |
| **Unscoped + Substring + Multi-Term Zone Filter (`OBS-032`)** | Index events with `"usb_0:zone:Room_right"` and `"Room_left"`; query `zone_id=room_right` and `zone_id=Room_right,Room_left` | Facets return deduplicated `"Room_right"`, `"Room_left"`; substring & comma-separated queries match cleanly | M2 (`test_step2_alerts_governance_and_rules.py`, `alerts_store_probe`) |
| **Dwell Window Display (`OBS-033`)** | Track enters `Room_right` at `t=100`, dwells at `t=112`, exits at `t=125` | `ZoneEvent` & SQLite metadata carry `entry_time=100`, `exit_time=125`, `dwell_time=25.0`; `#alerts` renders duration + start/end window instead of title-only text | M1/M3 (`test_step2_alerts_governance_and_rules.py`) |
| **Custom Alert Promotion Rule (`OBS-034`)** | Create rule `event_type=zone_dwell`, `zone_id=Room_right`, `min_dwell_time=5`, `target_severity=warning`; emit 8s dwell | Event is promoted to `warning` with `promoted_by_rule` metadata before SQLite write-through; rule survives restart and CRUD updates in `#alerts` | M2/M3 (`test_step2_alerts_governance_and_rules.py`, `alerts_store_probe`) |
