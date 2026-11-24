# Step 2: Unified Dynamic Category Registry (`custom_categories` SSOT), Clean Universal Defaults & Opt-In Demo Scenarios

> **Parent Roadmap**: `.TODO/reid_unification_traceability_and_studio_ux_master_roadmap.md` (`Step 2 of 4` | `--parent reid_unification_traceability_and_studio_ux_master_roadmap --milestone 2`).
> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–12`, `ADR-11`, Layer 1–5) & `docs/architecture/CURRENT_ARCHITECTURE.md` (`BUG-07`, `Idea 1`).
> **Execution Rule**: Strict **1-Milestone-Per-Turn**. Execute Milestone 1 first via `/frontier-architect continue step_2_category_registry_and_demo_isolation`; Milestones 2 and 3 are deferred to subsequent turns.

---

## Pre-Flight Architecture & Modularity Contract

### Hard Budget & Invariant Guards
- **Zero-Regression File & Method Budgets**:
  - `intelligent_tracker/category_registry.py <= 200L` (pure domain module; zero imports from `dashboard/` or `cli/`).
  - `intelligent_tracker/rsac.py < 380L` (down from `412L` by extracting `CustomCategory` and `DEFAULT_CUSTOM_CATEGORIES` into `category_registry.py` while re-exporting them for backward compatibility).
  - `intelligent_tracker/database.py <= 135L` (compose `CategoryRepoMixin` in `<= 2` added lines).
  - `dashboard/routers/rsac.py < 360L` (net line delta negative after moving category endpoints to `dashboard/routers/categories.py`).
  - `dashboard/routers/analytics.py < 350L` (`324L` currently), `dashboard/static/partials/modals/entity_modals.html < 240L`, `dashboard/static/index.html < 180L`.
  - All new and modified files `<= 350L`, classes `<= 12` methods, functions `<= 40L`, routes `<= 25L`, zero CSS `!important`.
- **SQLite, Concurrency & Dependency Invariants**:
  - Every SQLite repository write method (`*_repo.py`) MUST call `self._conn.rollback()` inside `except` before re-raising.
  - Offload synchronous SQLite/gallery operations in `async def` FastAPI routes via `asyncio.to_thread(...)`.
  - Domain `RSACManager.set_rule()` remains permissive so arbitrary domain rule categories stay valid; HTTP route writes enforce `custom_categories` SSOT validation (`422`).
  - Keep `dashboard/routers/rsac.py` re-exporting `create_custom_category` and honor patched `dashboard.routers.rsac.reload_all_galleries` for test compatibility.

### Public Surface Contracts
- **Backend Category Registry & SSOT API**:
  - Universal defaults (`9` IDs): `person`, `staff`, `visitor`, `vip`, `restricted`, `vehicle`, `pet`, `bag_parcel`, `asset`.
  - Slug regex: `^[a-z0-9][a-z0-9_-]{0,47}$` via `normalize_category_slug()` and `is_valid_category_slug()`.
  - `GET /api/rsac/categories`, `POST /api/rsac/categories` (`422` on invalid slug), `DELETE /api/rsac/categories/{category_id}` (`409` if `"person"` or referenced by entities/RSAC rules).
  - `GET /api/rsac/categories/export` -> `{"format": "intelligent-tracker.categories", "version": 1, "exported_at": "...", "categories": [...]}`.
  - `POST /api/rsac/categories/import` (`{"categories": [...], "mode": "merge" | "replace"}`, max `200` items -> `422`) -> returns imported/deleted/skipped counts and reloads galleries.
  - Entity/RSAC HTTP writes (`POST /entities`, `POST /tag`, `POST /api/tag/commit`, `POST /api/review/{item_id}/enroll-new`, `POST /api/enroll`, `POST /api/active-learning/{item_id}/enroll-new`, `POST /api/rsac/rules`) validate categories against `custom_categories` (`422` on unknown).
- **Opt-In Demo Config (`Milestone 2`) & Unified UI Pickers (`Milestone 3`)**:
  - `resolve_base_config_path()` prioritizes `TRACKER_CONFIG` -> `configs/alert_demo.yaml` (only when `IT_LOAD_DEMO_SCENARIOS` is truthy or `--demo` passed) -> `configs/default.yaml`.
  - Frontend selectors `[data-category-select]` and chip pickers (`cam-tracked-categories-input`, `batch-tracked-categories-input`, `feed-tracked-categories-input`) stay synced with `/api/rsac/categories`.

---

## Milestone 1: Backend Category SSOT, Universal Defaults, Boot Migration, Validation, Preset Export/Import & COCO Mapping *(Active Slice)*

- [x] **intelligent_tracker/category_registry.py**: Create pure domain module (`<= 200L`) containing moved `CustomCategory` dataclass, universal `DEFAULT_CUSTOM_CATEGORIES` (`9` entries without residential demos), `LEGACY_DEMO_CATEGORY_IDS`, `LEGACY_DEFAULT_OVERRIDES`, `CATEGORY_SLUG_RE` + `normalize_category_slug()` / `is_valid_category_slug()`, `COCO_CATEGORY_MAP` + `map_detector_label_to_category()`, and idempotent `migrate_category_registry(cursor)` (seeds defaults, upgrades untouched legacy names/icons, prunes unreferenced legacy demo categories & `guard_dog` pet entry, auto-registers distinct valid `entities.category` values).
- [x] **intelligent_tracker/repositories/schema_manager.py**: Replace inline residential seed tuples in `_seed_default_data()` with `DEFAULT_CUSTOM_CATEGORIES`, drop `guard_dog` from `default_pets` (`dog`, `cat`, `pet`), and invoke `migrate_category_registry(cursor)` on boot.
- [x] **intelligent_tracker/rsac.py**: Remove moved `CustomCategory` and `DEFAULT_CUSTOM_CATEGORIES` (re-exporting both from `intelligent_tracker/category_registry.py` for compatibility), set `DEFAULT_PET_WHITELIST = {"dog", "cat", "pet"}`, and clear `self.categories` before DB reload when `self.db` is attached; preserve permissive domain `RSACManager.set_rule()`.
- [x] **intelligent_tracker/repositories/category_repo.py** + **intelligent_tracker/repositories/__init__.py** + **intelligent_tracker/database.py**: Add `CategoryRepoMixin` with `count_category_references(cat_id)` returning `{"entities": n, "rules": m}` and compose into `TrackerDB` (`<= 2` lines added to `database.py`).
- [x] **dashboard/services/category_service.py**: Implement `ensure_known_category()`, `ensure_known_categories()`, `resolve_rsac_for_request()`, `export_categories()`, `import_categories()` (`merge` / `replace`, max `200` items -> `422`, `skipped` reporting), and `delete_category_guarded()` (`409` on `"person"` or referenced category).
- [x] **dashboard/routers/categories.py** + **dashboard/schemas.py** + **dashboard/routers/__init__.py** + **dashboard/routers/rsac.py** + **dashboard/app.py**: Move `GET/POST /api/rsac/categories` and `DELETE /api/rsac/categories/{category_id}` out of `dashboard/routers/rsac.py` into `dashboard/routers/categories.py` with slug validation and guarded deletes, add `GET /api/rsac/categories/export` and `POST /api/rsac/categories/import` (`CategoryImportRequest` in `dashboard/schemas.py`), register `categories_router` in `dashboard/app.py` before `rsac_router`, and keep `create_custom_category` re-export in `dashboard/routers/rsac.py` (net negative line delta on `rsac.py`).
- [x] **dashboard/routers/rsac.py** + **dashboard/routers/analytics.py** + **dashboard/routers/review.py** + **dashboard/routers/tagging.py**: Enforce `ensure_known_category()` / `ensure_known_categories()` on all entity, ROI tag, review enroll-new, universal enroll, and RSAC rule HTTP writes (`422` on unknown category), keeping `analytics.py < 350L`.
- [x] **intelligent_tracker/analytics/zone_stats.py**: Wire `map_detector_label_to_category(getattr(trk, "label", ""))` at line `82` when `trk` has no truthy `entity_category`, leaving explicit `entity_category` untouched.
- [x] **tests/test_step2_category_registry.py** + **tests/test_rsac.py**: Add isolated unit and FastAPI `TestClient` tests (`<= 40L`/method) covering fresh `9`-category defaults, legacy pruning vs. referenced preservation, distinct entity category auto-migration, idempotency, untouched vs. user-edited upgrades, slug normalization/validation, COCO mapping, export/import (`merge`/`replace`/invalid/`>200`), guarded delete `409`, and route category validation (`422`); update `tests/test_rsac.py` expected defaults to the `9` universal IDs.

---

## Milestone 2: Opt-In Demo Scenarios *(Deferred to Next Turn / Milestone 2)*

> *Deferred to Next Turn / Milestone 2*

- [ ] **configs/default.yaml**: Create clean non-demo base configuration copied from `configs/alert_demo.yaml` without `analytics.zones` (`restricted_vault`), `analytics.tripwires`, or the `alerting:` block.
- [ ] **dashboard/services/base_config_resolver.py** + **dashboard/camera_pool.py** + **dashboard/stream_manager.py**: Implement `resolve_base_config_path()` (`TRACKER_CONFIG` -> `configs/alert_demo.yaml` when `IT_LOAD_DEMO_SCENARIOS` in `1`/`true`/`yes` -> `configs/default.yaml`) and wire `CameraPool(base_config_path: str | None = None)` and `stream_manager._init_manager_config()` through the resolver.
- [ ] **dashboard/server.py**: Add `--demo` CLI flag setting `os.environ["IT_LOAD_DEMO_SCENARIOS"] = "1"` before `uvicorn.run()` so reload worker children inherit opt-in demo mode.
- [ ] **tests/test_step2_demo_isolation.py** + **documentation/events.rst**: Add isolated tests verifying `resolve_base_config_path()` precedence, zero `restricted_vault` demo alerts on default cold boot, and `--demo` flag propagation; update docs where default config is referenced.

---

## Milestone 3: Frontend Inline Quick-Create/Manage & Category Pickers *(Deferred to Next Turn / Milestone 3)*

> *Deferred to Next Turn / Milestone 3*
> *Note*: Switch the JS fallback in `dashboard/static/js/interactive_canvas.js` (`'object'` / `'other'` / `'custom'`) to `'asset'` when removing legacy static category fallbacks.

- [ ] **dashboard/static/partials/modals/entity_modals.html** + **dashboard/static/partials/modals/studio_modals.html** + **dashboard/static/css/badges.css**: Strip static residential `<option>` lists down to a single `<option value="person">Person</option>` fallback (`data-category-select`) and remove legacy `.badge-category.family_car|delivery_truck|cleaning_crew|guard_dog` CSS rules, keeping `entity_modals.html < 240L`.
- [ ] **dashboard/static/js/category_quick_create.js** + **dashboard/static/js/category_chip_picker.js** + **dashboard/static/js/category_badge_manager.js** + **dashboard/static/index.html**: Add inline `+ New / Manage` quick-create controls beneath `[data-category-select]` dropdowns, chip toggles synced to `cam-tracked-categories-input`, `batch-tracked-categories-input`, and `feed-tracked-categories-input`, preset Export/Import UI controls in `#gallery-category-crud-panel`, and `categories:changed` cross-view dispatch, keeping `index.html < 180L`.
- [ ] **tests/test_step2_category_ui.py**: Add Node VM and surface verification tests (`<= 40L`/method) validating inline quick-create, chip picker synchronization, preset import/export triggers, zero legacy residential option strings, and `0` `surface --verify` mismatches.

---

## Scenario Combinations Matrix

| Scenario | Verification Command | Expected Outcome |
| :--- | :--- | :--- |
| **Milestone 1 Category SSOT, Boot Migration & API** | `python skills/system-diagnostics/scripts/diagnose.py tests tests.test_step2_category_registry tests.test_rsac tests.test_enrollment tests.test_refine_async_and_cold_start tests.test_dashboard tests.test_step3_roi_recognition_api tests.test_step3_badges_and_collision tests.test_m9_api tests.test_dashboard_di` | Fresh DB seeds `9` universal categories; unreferenced legacy IDs pruned; referenced/custom IDs preserved; HTTP writes enforce `custom_categories` (`422`); export/import (`merge`/`replace`) & guarded delete (`409`) pass |
| **Milestone 2 Opt-In Demo Config Isolation** | `python skills/system-diagnostics/scripts/diagnose.py tests tests.test_step2_demo_isolation tests.test_graceful_shutdown_perf tests.test_processing_mode` | Default cold boot resolves `configs/default.yaml` with zero `restricted_vault` alerts; `--demo` / `IT_LOAD_DEMO_SCENARIOS=1` loads `configs/alert_demo.yaml` |
| **Milestone 3 Inline Category Quick-Create & Pickers** | `python skills/system-diagnostics/scripts/diagnose.py tests tests.test_step2_category_ui tests.test_step3_badges_and_collision tests.test_step1_dialogs_enrollment_and_media_ui` | Inline `+ New` categories appear immediately in all modal selects, gallery filters, chip pickers, and RSAC rules without static fallback drift |
| **Full Regression & Static Gate** | `python skills/system-diagnostics/scripts/diagnose.py surface --verify --strict; python skills/system-diagnostics/scripts/diagnose.py scan --path intelligent_tracker dashboard scripts --strict; python skills/system-diagnostics/scripts/diagnose.py audit --path intelligent_tracker dashboard scripts; MPLBACKEND=Agg python -m unittest discover tests` | `0` surface mismatches, `0` active scan defects, clean modularity budgets, `100%` `unittest` pass |
