# Step 3 Implementation Plan: Monolith Decomposition, DI Cleanup & SQLite Concurrency Hardening

> **Parent Master Plan**: `.TODO/world_architecture_master_roadmap.md` (Step 3)  
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (ADR-01, ADR-04, Sections 2, 3, 4 & 6)  
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–4 are *Deferred to Next Turn / Milestone*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map`)

Measured against live workspace baseline (`238` files, `47,718` lines, `94` API routes):
- **Active Hard-Ceiling Files (`>= 500` lines)**:
  - `dashboard/static/index.html` (`1,688` lines) — monolithic SPA shell containing header, 9 tab panes, 15 modals, mobile drawer, and 36 script imports; currently served via raw file read in `dashboard/app.py#L205-L212`.
  - `intelligent_tracker/analytics.py` (`667` lines) — `OccupancyHeatmap` (9 methods) + `AnalyticsEngine` (`update()` is `223` lines, exceeding the 40L function ceiling) + unused imports (`TripwireEvent`, `ZoneEvent`).
  - `intelligent_tracker/periferials.py` (`510` lines) — legacy `UnifiedCamera`, `VideoStream` (15 methods), `SyncCameras` (14 methods); only imported in production by `intelligent_tracker/high_objects.py#L22`.
  - *(Frozen Legacy Exception)*: `intelligent_tracker/high_objects.py` (`527` lines) carries an explicit Step 2 `.. deprecated::` notice for `run_legacy_forms_gui` compatibility and qualifies under the Step 3 DoD frozen-legacy exception.
- **Warning / Heavy-Class Target**:
  - `dashboard/camera_pool.py` (`497` lines, `CameraPool` `19` methods/properties) — mixes JSON config persistence, stream lifecycle orchestration, and public pool facade.
- **FastAPI DI & `TrackerDB` Concurrency Gaps**:
  - `dashboard/dependencies.py` (`284` lines) relies on 8 `sys.modules.get("dashboard.app")` inspections and mutable module globals instead of FastAPI `app.state` and `app.dependency_overrides`; `app.state` and `app.dependency_overrides` have `0` usages across `dashboard/` and `tests/`.
  - Each `StreamManager` instantiates an independent `TrackerDB(db_path)` with its own `sqlite3.Connection` and per-instance `self._lock = threading.RLock()`, so multi-camera writes to the same SQLite file are not serialized across instances (`database is locked` risk).
  - `dashboard/routers/topology.py#L123,L139` directly calls `TrackerDB()` (`data/tracker.db`) instead of `get_db()`, and `dashboard/routers/analytics.py#L78-L79` reaches directly into `mgr.db._lock` and `mgr.db._conn.cursor()` for raw SQL.

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts (Zero-Regression Invariants)
- **Database & Repository Surface**: `TrackerDB(db_path)` preserves all 10 repository mixin contracts (`EntityMixin`, `SignatureMixin`, `DescriptorMixin`, `AnalyticsMixin`, `SpatialMixin`, `LearningMixin`, `RsacMixin`, `WhitelistMixin`, `TelemetryMixin`, `SchemaMixin`), `self._lock`, `self._conn`, context manager semantics, and `PRAGMA` WAL/foreign-key guarantees.
- **CameraPool & Dependency Providers**: `CameraPool` preserves `config_file`, `db_path`, `base_config_path`, `camera_configs`, `streams`, `world_graph`, `_lock`, `primary_stream`, `rsac_manager`, `active_learning`, `enrollment_manager`, and all existing public methods. `dashboard/dependencies.py` getters (`get_camera_pool`, `get_stream_manager`, `get_scenario_manager`, `get_lifecycle_manager`, `get_db`, etc.) work both as FastAPI `Depends(...)` callables (resolving `request.app.state` / `websocket.app.state`) and as fallback standalone helpers.
- **Analytics & Periferials Compatibility**: `from intelligent_tracker.analytics import AnalyticsEngine, OccupancyHeatmap` and Sphinx `.. automodule:: intelligent_tracker.analytics` remain 100% compatible. `intelligent_tracker/periferials.py` remains importable as a thin deprecated re-export shim until `high_objects.py` / `run_legacy_forms_gui` is retired.
- **Dashboard HTML & Scrubber Contracts**:
  - `GET /` continues returning full HTML containing all 9 `id="tab-<name>"` panes, 15 `<select>` controls, 180+ contracted DOM IDs (`tests/test_refactor_contract.py`), and responsive nav controls (`tests/test_dashboard_ui.py`, `tests/test_responsive_navigation.py`).
  - `dashboard/static/index.html` retains its `<script>` tags in exact load order (`video_batch_reports.js < video_batch.js`, `scrubber_playback_state.js < scrubber_library_bridge.js < video_scrubber.js`) so `tests/test_scrubber_ux_fixes.py` direct file checks remain valid.

### Modularity, Threading & Modernization Guardrails
- **Python 3.10–3.12+**: Zero `from __future__ import ...`, zero `six`/`past`/`future` shims, native `X | Y` unions and built-in generics (`list[...]`, `dict[...]`).
- **File, Class & Function Budgets**: All new/refactored Python and HTML files stay `< 350` lines (target 150–300L), `<= 10–12` methods per class, `<= 40` lines per function, and `<= 15–25` lines per FastAPI route handler.
- **Lock Hierarchy**: Never perform `thread.join()`, `time.sleep()`, or network calls while holding `CameraPool` or `WorldGraph` locks. Coordinate SQLite path locks cleanly without cross-lock deadlocks.

---

## 3. Target Architecture Overview

| Area | Target Structure | Budget Target |
| :--- | :--- | :--- |
| **SQLite Concurrency** | `intelligent_tracker/repositories/connection.py` (shared path-keyed `RLock` registry + WAL/busy-timeout connection coordinator) + `TrackerDB` facade + `AnalyticsMixin` helper | `connection.py` < 160L; `database.py` < 150L |
| **CameraPool Split** | `dashboard/services/camera_config_store.py` + `dashboard/services/stream_pool_coordinator.py` + thin `dashboard/camera_pool.py` facade | Each file < 250L; `<= 10` methods/class |
| **FastAPI DI Cleanup** | `dashboard/dependencies.py` (`app.state` + `Depends` without `sys.modules.get("dashboard.app")`) + `dashboard/app.py` `lifespan` `app.state` binding | `dependencies.py` < 240L |
| **Analytics Package** | `intelligent_tracker/analytics/` (`__init__.py`, `heatmap.py`, `zone_stats.py`, `engine.py`) | Each file < 260L; `update()` <= 40L |
| **Video Legacy Consolidation** | `intelligent_tracker/video/legacy_camera.py` + `intelligent_tracker/video/legacy_sync.py` + thin deprecated `intelligent_tracker/periferials.py` shim | Each file < 240L; `<= 12` methods/class |
| **HTML Modularization** | `dashboard/static/index.html` Jinja2 shell + `dashboard/static/partials/tabs/*.html` & `modals/*.html` rendered by `dashboard/app.py` on `GET /` | Every `.html` file < 250L |

---

## 4. Phased Implementation Milestones

### Milestone 1: SQLite Concurrency Hardening & Router DB Encapsulation *(Active Execution Target)*
- [x] **intelligent_tracker/repositories/connection.py**: Implement a thread-safe `SQLiteConnectionCoordinator` / path-keyed lock registry (`get_path_lock(db_path)` using normalized absolute paths for file DBs and isolated locks for `:memory:`, plus WAL `busy_timeout=10000`, `synchronous=NORMAL`, `foreign_keys=ON`, and reference-counted `wal_checkpoint(TRUNCATE)` on last close).
- [x] **intelligent_tracker/database.py**: Wire `TrackerDB` to use `SQLiteConnectionCoordinator` for shared per-path `self._lock` serialization across independent `TrackerDB(same_path)` instances, remove unused `Optional` import, and ensure safe `close()` / `__del__()` idempotency.
- [x] **intelligent_tracker/repositories/analytics_repo.py**: Add a clean `get_analytics_summary()` / `query_sighting_counts()` repository method so routers do not touch `db._lock` or `db._conn` directly.
- [x] **dashboard/routers/topology.py**: Replace direct `TrackerDB()` instantiations (`L123`, `L139`) with injected `get_db()` resolution.
- [x] **dashboard/routers/analytics.py**: Replace direct `with mgr.db._lock: cur = mgr.db._conn.cursor()` raw SQL (`L78-L79`) with the repository method on `TrackerDB`.
- [x] **tests/test_database_concurrency.py**: Add isolated multi-instance SQLite stress tests (4+ concurrent `TrackerDB(temp_db_path)` instances performing simultaneous sighting inserts, entity updates, and analytics reads) verifying zero `database is locked` errors, plus `topology`/`analytics` router DB encapsulation assertions.

**Definition of Done (DoD)**:
- [x] Zero direct `TrackerDB()` calls remain in `dashboard/routers/` and zero raw `db._conn` SQL blocks remain in `dashboard/routers/analytics.py`.
- [x] `MPLBACKEND=Agg python -m unittest tests/test_database_concurrency.py tests/test_database.py tests/test_modernization.py` passes 100% with zero `database is locked` failures.

---

### Milestone 2: `CameraPool` Decomposition & FastAPI `app.state` DI Refactor *(Deferred to Next Turn / Milestone)*
- [x] **dashboard/services/camera_config_store.py**: Extract `CameraConfigStore` owning `load_cameras()`, `save_cameras()`, legacy `STREAM_SOURCE` env bootstrapping, and thread-safe config mutations (`< 180` lines, `<= 8` methods).
- [x] **dashboard/services/stream_pool_coordinator.py**: Extract `StreamPoolCoordinator` owning `StreamManager` instantiation with `WorldGraph`, `add/update/remove/toggle` stream transitions, `start_all()`, `signal_stop_all()`, and lock-free parallel `stop_all()` (`< 240` lines, `<= 10` methods).
- [x] **dashboard/camera_pool.py**: Refactor `CameraPool` into a thin facade (`< 200` lines, `<= 10` methods) delegating to `CameraConfigStore` and `StreamPoolCoordinator` while preserving 100% of existing public properties and methods.
- [x] **dashboard/dependencies.py**: Remove all `sys.modules.get("dashboard.app")` lookups; resolve dependencies via FastAPI `HTTPConnection` / `Request` (`app.state`) with safe standalone fallback for non-request helpers, and support `app.dependency_overrides`.
- [x] **dashboard/app.py**: Bind `app.state.camera_pool`, `app.state.stream_manager`, `app.state.scenario_manager`, `app.state.lifecycle_manager`, and `app.state.db` cleanly inside `lifespan`, and remove unused `get_scenario_manager` import.
- [x] **dashboard/routers/cameras.py**: Wire FastAPI `Depends(get_camera_pool)` / `Depends(get_db)` cleanly across routes and remove direct fallback `CameraPool()` instantiations in routers (`cameras.py`, `camera_diagnostics.py`, `videos.py`) where dependency injection applies.
- [x] **tests/test_dashboard_di.py**: Add isolated tests verifying `app.state` lifespan population, `app.dependency_overrides` substitution, zero `sys.modules.get("dashboard.app")` usage via AST check, and update any existing router tests that relied on mutating `dashboard.app` module globals.

**Definition of Done (DoD)**:
- [x] `dashboard/camera_pool.py` is `< 250` lines with `<= 10` methods; `dashboard/dependencies.py` contains zero `sys.modules` lookups.
- [x] `MPLBACKEND=Agg python -m unittest tests/test_dashboard_di.py tests/test_camera_pool.py tests/test_graceful_shutdown_perf.py tests/test_world_pipeline_integration.py tests/test_scenario_api.py tests/test_vms_api.py` passes 100%.

---

### Milestone 3: `analytics` Package Split & `periferials` Consolidation into `video/` *(Deferred to Next Turn / Milestone)*
- [x] **intelligent_tracker/analytics/heatmap.py**: Extract `OccupancyHeatmap` into its own focused module (`< 230` lines, `<= 9` methods) preserving all Gaussian kernel, draw, and CSV/image export behavior.
- [x] **intelligent_tracker/analytics/zone_stats.py**: Extract tripwire crossing evaluation, zone dwell/capacity tracking, and RSAC/event dispatch helpers (`<= 40` lines per function) out of `AnalyticsEngine.update()`.
- [x] **intelligent_tracker/analytics/engine.py**: Extract `AnalyticsEngine` (`< 250` lines, `<= 10` methods, `update()` `<= 40` lines) delegating to `zone_stats.py`, with zero unused imports (`TripwireEvent`, `ZoneEvent` removed).
- [x] **intelligent_tracker/analytics/__init__.py**: Re-export `OccupancyHeatmap` and `AnalyticsEngine` cleanly and delete the old monolithic `intelligent_tracker/analytics.py` file.
- [x] **intelligent_tracker/video/legacy_camera.py**: Move `CameraError`, `MockVideoCapture`, `UnifiedCamera`, `PiRGBArray`, and `PiCamera` from `periferials.py` (`< 210` lines, `<= 10` methods/class).
- [x] **intelligent_tracker/video/legacy_sync.py**: Move `VideoStream` and `SyncCameras` from `periferials.py`, refactoring repeated property/lifecycle boilerplate so each class is `<= 12` methods (`< 260` lines).
- [x] **intelligent_tracker/periferials.py**: Replace the 510-line monolith with a thin deprecated compatibility re-export shim (`< 50` lines) pointing to `intelligent_tracker.video.legacy_camera` and `intelligent_tracker.video.legacy_sync`, and update `intelligent_tracker/high_objects.py` import if needed.
- [x] **tests/test_analytics.py**: Verify full compatibility of `intelligent_tracker.analytics` and add unit tests covering `zone_stats` helpers and `periferials` shim compatibility in `tests/test_world_legacy_compat.py`.

**Definition of Done (DoD)**:
- [x] `intelligent_tracker/analytics.py` (667L) is replaced by `intelligent_tracker/analytics/` with every file `< 260` lines and `AnalyticsEngine.update()` `<= 40` lines.
- [x] `intelligent_tracker/periferials.py` is `< 50` lines, and `legacy_camera.py` / `legacy_sync.py` satisfy `<= 350` lines and `<= 12` methods/class.
- [x] `MPLBACKEND=Agg python -m unittest tests/test_analytics.py tests/test_world_legacy_compat.py tests/test_events_dispatchers.py tests/test_events_rules.py tests/test_interactive.py` passes 100%.

---

### Milestone 4: `index.html` Template Partial Decomposition & Final Step 3 Sign-Off *(Deferred to Next Turn / Milestone)*
- [x] **dashboard/static/partials/tabs/*.html**: Split the 9 tab panes (`live`, `videos`, `gallery`, `timeline`, `analytics`, `alerts`, `studio`, `journey`, `review`) from `dashboard/static/index.html` into focused HTML partials (`< 220` lines each).
- [x] **dashboard/static/partials/modals/*.html**: Group the 15 modals into domain partials (`entity_modals.html`, `camera_modals.html`, `studio_modals.html`, `video_modals.html`, `< 240` lines each).
- [x] **dashboard/static/index.html**: Reduce `index.html` to a clean Jinja2 shell (`< 180` lines) including the tab and modal partials while preserving header, mobile drawer, toast container, `<link>` tags, and exact `<script>` load order required by `tests/test_scrubber_ux_fixes.py`.
- [x] **dashboard/app.py**: Render `index.html` in `serve_index()` via `jinja2.Environment(loader=FileSystemLoader(STATIC_DIR))` so `GET /` returns the complete assembled HTML synchronously.
- [x] **tests/test_step3_architecture_budgets.py**: Add automated modularity/DI/HTML assertions verifying zero non-frozen runtime files `>= 500` lines, zero `sys.modules.get("dashboard.app")` calls, and clean `GET /` partial assembly.
- [x] **CHANGELOG.md**: Record milestone completion via `diagnose.py changelog add`.

**Definition of Done (DoD)**:
- [x] Every active `.py` and `.html` file in Step 3 scope is `< 350` lines (zero active runtime files `>= 500` lines).
- [x] Full test suite (`MPLBACKEND=Agg python -m unittest discover tests`) passes 100% including `test_refactor_contract.py`, `test_dashboard_ui.py`, `test_responsive_navigation.py`, and `test_scrubber_ux_fixes.py`.
- [x] `diagnose.py arch-map --path .` confirms modularity budget targets met.

---

## 5. Scenario Combinations Matrix

| Scenario | Configuration / Inputs | Expected Behavior | Verification Command |
| :--- | :--- | :--- | :--- |
| **Multi-Instance SQLite Write Stress** | 4 threads each using an independent `TrackerDB(temp_db_path)` writing entities + sightings simultaneously | Shared path lock serializes writes cleanly; zero `database is locked` errors | `MPLBACKEND=Agg python -m unittest tests/test_database_concurrency.py` |
| **Router DB Encapsulation** | AST & functional test on `dashboard/routers/topology.py` and `analytics.py` | Zero direct `TrackerDB()` calls and zero raw `db._conn` access | `MPLBACKEND=Agg python -m unittest tests/test_database_concurrency.py` |
| **FastAPI `app.state` & Override DI** | `TestClient(app)` with `app.dependency_overrides[get_camera_pool]` and `app.state` bindings | Routes resolve overridden pool/DB cleanly without `sys.modules.get("dashboard.app")` | `MPLBACKEND=Agg python -m unittest tests/test_dashboard_di.py tests/test_scenario_api.py tests/test_vms_api.py` |
| **CameraPool Facade Lifecycle** | `CameraPool(config_file=tmp, db_path=tmp_db, autostart=False)` add/toggle/remove + `stop_all()` | Config persisted, `StreamManager` orchestrated, parallel stop completes without holding lock | `MPLBACKEND=Agg python -m unittest tests/test_camera_pool.py tests/test_graceful_shutdown_perf.py` |
| **Analytics & Periferials Facades** | `AnalyticsEngine` + `OccupancyHeatmap` + `periferials` legacy imports | Identical zone/tripwire/heatmap outputs; `periferials` re-exports work cleanly | `MPLBACKEND=Agg python -m unittest tests/test_analytics.py tests/test_world_legacy_compat.py` |
| **Assembled SPA HTML & Contracts** | `GET /` via `TestClient(app)` + `test_refactor_contract.py` + `test_scrubber_ux_fixes.py` | All 9 tabs, 15 `<select>`s, 180+ DOM IDs, and exact `<script>` order preserved | `MPLBACKEND=Agg python -m unittest tests/test_refactor_contract.py tests/test_dashboard_ui.py tests/test_responsive_navigation.py tests/test_scrubber_ux_fixes.py` |
| **Full Suite & Architecture Gate** | Entire workspace test suite + `diagnose.py arch-map --path .` | 100% green tests; zero active runtime files `>= 500` lines | `MPLBACKEND=Agg python -m unittest discover tests` |

