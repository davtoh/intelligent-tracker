# Step 1: Canonical `DualModel` Re-ID, Sighting Crops, Responsive Dialogs, `MediaEmptyState` & Tooling Elevation

> **Parent Roadmap**: `.TODO/reid_unification_traceability_and_studio_ux_master_roadmap.md` (`Step 1 of 4` | `--parent reid_unification_traceability_and_studio_ux_master_roadmap --milestone 1`).
> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–12`, Sections 4 & 6.4) & `docs/architecture/CURRENT_ARCHITECTURE.md` (`BUG-01`..`BUG-09`).
> **Execution Rule**: Strict **1-Milestone-Per-Turn**. Execute Milestone 1 first via `/frontier-architect continue step_1_reid_unification_dialogs_and_tooling`; Milestones 2 and 3 are deferred to subsequent turns.

---

## Pre-Flight Architecture & Modularity Contract

### Hard Budget & Invariant Guards (Verified via `diagnose.py arch-map` & `audit`)
- **Zero-Regression File & Method Budgets**:
  - `dashboard/static/index.html < 180L` (add `modal_forms_grid.css` + split JS helpers cleanly within budget or load via `@import` in modular CSS).
  - `dashboard/static/partials/modals/entity_modals.html < 240L` (currently `237L` -> extract/keep DOM lean or delegate state banners to `tag_modal_state.js`).
  - `dashboard/static/partials/modals/camera_modals.html < 250L` (currently `238L`).
  - `dashboard/static/js/interactive_canvas.js < 240L` (currently `239L` -> extract Two-State modal orchestration into `dashboard/static/js/tag_modal_state.js`).
  - `dashboard/static/studio.js <= 350L` (currently `349L` -> keep media fallback state inside `dashboard/static/js/media_empty_state.js`).
  - `dashboard/static/js/universal_enrollment.js <= 350L` (currently `345L` -> extract single-stage video/FPS scrubber sync into `dashboard/static/js/enrollment_stage_controller.js`).
  - `dashboard/services/camera_config_store.py < 180L` (`tests/test_dashboard_di.py`).
  - Keep all new and modified files `<= 350L`, classes `<= 12` methods, functions `<= 40L`, routes `<= 25L`, and zero CSS `!important`.
- **Backend & Concurrency Invariants**:
  - Canonical `DualModel` embeddings (`probe_db_reid=True`, `"onnx"`/`DualModel` — never unregistered `"osnet"`) across Enrollment, live streams, `VideoIndexer`, and `RoiRecognitionService`, with crop-based backfill when DB signatures differ in dimension.
  - Every `*_repo.py` write method keeps `self._conn.rollback()` in `except` before re-raising.
  - Inject shared `app.state.confidence_engine` and `app.state.world_graph` into `create_video_indexer()`; never hold `CameraPool._lock` across disk JSON I/O or nested `CameraHealthManager._lock`/`StreamManager._lock`.
  - Keep `ConfidenceEngine.record_human_feedback()` compatible with `"reject"` and optional `camera_id`/`zone_id`.
- **Frontend Invariants**:
  - Reuse `OverlayControlBar`, `UnifiedCanvasOverlay`, `ScrubberTimelineSlider`, and single shared `MediaEmptyState` (`media_empty_state.js`, approved per `ADR-05`).
  - Preserve standalone fallbacks in parent JS modules (`UniversalEnrollment`, `InteractiveCanvas`, `OverlayLayers`) for Node VM (`vm.runInNewContext`) test suites.

### Public Surface Contracts
- **Backend Re-ID, Feedback & Relabeling**:
  - `POST /api/tag/recognize-roi`: returns `candidates` (filtered against `negative_exemplars`), thresholded `is_known: bool`, `best_match` (only populated or flagged with `is_known`), and `classification` (`detector_label`, `detector_confidence`).
  - `POST /api/enroll`, `POST /api/tag/commit`, `POST /api/tag/discourage`, `DELETE /entities/{entity_id}`: trigger pool-wide `reload_all_galleries()` + `VideoRunRelabelService` (`video_runs.frame_detections_json` + `CachedReplayProvider` refresh).
  - `ConfidenceEngine.record_human_feedback(entity_id, action, *, camera_id="", zone_id="", ...)`: supports `"confirm" | "reassign" | "enroll_new" | "dismiss" | "reject"`.
- **Frontend UI & CSS Surfaces**:
  - `dashboard/static/css/modal_forms_grid.css`: defines `.form-row`, `.col-4`..`.col-8`, `.modal-left-col, .modal-right-col { min-width: 0; }`, wide adaptive resizable `.modal-lg` (`width: min(94dvw, 1240px); max-width: 1280px; resize: both; overscroll-behavior: contain;`), and `@container (inline-size < 900px)` collapse.
  - `dashboard/static/js/media_empty_state.js`: shared `MediaEmptyState.attach(img, opts)` / `showEmpty()` / `clearEmpty()` helper bound to `#studio-live-img`, `#static-heatmap-img`, `#tag-roi-crop-img`, `#snapshot-modal-img`, `#enroll-crop-preview-img`, and `#test-preview-img`.
  - `#modal-tag-entity`: Two-State UI (*Known Match* pre-filled banner + `"✅ Confirm Match"` + in-place `"🚫 Not <Name> / False Positive"` vs. *New Subject* hiding `"Not This"` + in-place candidate `✕` chip suppression without `closeTagModal()`).

---

## Milestone 1: Canonical `DualModel` Re-ID Parity, Retroactive Run Relabeling, Auto-Sighting Crops & Backend Concurrency/DI Fixes *(Active Slice)*

- [x] **intelligent_tracker/pipeline/config.py** + **dashboard/services/pipeline_factory.py** + **intelligent_tracker/batch.py** + **dashboard/services/video_analytics_service.py**: Default live (`probe_db_reid=True`) and batch pipelines (`VideoIndexer`) to canonical `DualModel` extraction matching `UniversalEnrollmentManager`, wire shared `app.state.confidence_engine` and `app.state.world_graph` into `create_video_indexer()`, and auto-recompute mismatched signature dimensions from stored `crop_path` on gallery load (`intelligent_tracker/repositories/signature_repo.py` / `intelligent_tracker/matching/gallery.py`).
- [x] **dashboard/services/roi_recognition_service.py** + **intelligent_tracker/memory/confidence.py** + **dashboard/services/negative_exemplar_service.py**: Fix `"osnet"` -> `"onnx"`/`DualModel` extractor resolution in `_resolve_roi_models()`, add thresholded `is_known` + negative-exemplar suppression in `match_crop_to_gallery()`, and update `ConfidenceEngine.record_human_feedback()` to accept `"reject"` and optional `camera_id`/`zone_id` metadata without raising `TypeError`/`ValueError`.
- [x] **dashboard/services/video_run_relabel_service.py** + **dashboard/services/cached_replay_provider.py** + **dashboard/routers/analytics.py**: Create `VideoRunRelabelService` to retroactively re-match/update `video_runs.frame_detections_json` and refresh `CachedReplayProvider` when entities are enrolled, tagged, discouraged, or deleted; update `DELETE /entities/{entity_id}` (`dashboard/routers/analytics.py`) to call `reload_all_galleries()`.
- [x] **intelligent_tracker/matching/_gallery_signals.py** + **dashboard/routers/analytics.py**: Write throttled bounded JPEG crops (`<= 1` per track/cooldown window, off-lock) in `emit_periodic_sighting()` (`Finding 4`) and fall back to the entity's primary signature thumbnail in `_enrich_sighting()` when `snapshot_path` is empty.
- [x] **dashboard/services/camera_config_store.py** + **dashboard/services/camera_source_bootstrap.py** + **dashboard/services/camera_pool_queries.py** + **dashboard/dependencies.py** + **dashboard/routers/system.py** + **intelligent_tracker/array_utils.py**: Move JSON file I/O (`load_cameras`, `retry_camera_connection`) and nested health/stream lock acquisitions (`list_cameras`) outside `CameraPool._lock` (keeping `camera_config_store.py < 180L`), pass shared DB into `get_scenario_mgr` fallback and `BackupManager`, and fix undefined `overlay` (`F821`) in `array_utils.py`.
- [x] **tests/test_step1_reid_sightings_and_locks.py**: Add isolated unit and integration tests (`<= 40L`/method) covering `Enroll -> VideoIndexer -> /detections` and post-index retroactive relabeling, automatic sighting crop generation + entity avatar fallback, `ConfidenceEngine.record_human_feedback("reject", ...)`, pool-wide gallery reload on delete, and lock-free JSON/status snapshots.

---

## Milestone 2: Wide/Resizable Dialogs, Unified Enrollment Stage, Two-State `#modal-tag-entity` & Shared `MediaEmptyState`

> *Deferred to Next Turn / Milestone 2*

- [x] **dashboard/static/css/modal_forms_grid.css** + **dashboard/static/css/modals.css** + **dashboard/static/index.html**: Define `.form-row`, `.col-4`..`.col-8`, `.modal-left-col, .modal-right-col { min-width: 0; }`, wide adaptive resizable `.modal-lg` (`width: min(94dvw, 1240px); max-width: 1280px; resize: both; overscroll-behavior: contain;`), and `@container (inline-size < 900px)` collapse (`Findings 2 & 3`, zero CSS `!important`, keeping `index.html < 180L`, `entity_modals.html < 240L`, `camera_modals.html < 250L`).
- [x] **dashboard/static/js/enrollment_stage_controller.js** + **dashboard/static/js/universal_enrollment.js** + **dashboard/static/js/scrubber_timeline_slider.js** + **dashboard/static/partials/tabs/gallery.html**: Add an explicit source context badge on `#gallery`'s `"➕ Enroll New Identity"` (preferring `#tab-videos` active video when opened from Video Studio), unify `<video>` + `#enroll-bbox-canvas` onto one single stage without a stacked duplicate `<video>`, sync canvas during Play (`timeupdate`), step `< -1 Frame` / `> +1 Frame` using real video FPS metadata, and preserve `video_filename` + `media_offset_sec` on submit (`Finding 1`, keeping `universal_enrollment.js <= 350L`).
- [x] **dashboard/static/js/tag_modal_state.js** + **dashboard/static/js/interactive_canvas.js** + **dashboard/static/js/tag_feedback_actions.js** + **dashboard/static/js/overlay_layers.js** + **dashboard/static/js/camera_ai_config.js** + **dashboard/static/js/app_ui_helpers.js** + **dashboard/static/app.js**: Implement Two-State `#modal-tag-entity` (*Known Match* pre-fill + `"✅ Confirm Match"` + in-place `"🚫 Not <Name> / False Positive"` vs. *New Subject* hiding `"Not This"` + in-place candidate `✕` suppression without calling `closeTagModal()`), invalidate `OverlayLayers.streamCache` on `{ force: true }`, fix `#btn-outline`/`#btn-primary`/`#candidate-discourage-btn` class-vs-ID selector bugs, and route drawer/hash modal triggers through `openModal()` (`Idea 5`, keeping `interactive_canvas.js < 240L`).
- [x] **dashboard/static/js/media_empty_state.js** + **dashboard/static/studio.js** + **dashboard/static/js/studio_canvas.js** + **dashboard/static/js/live_player.js** + **dashboard/static/js/analytics_view.js**: Create and wire shared `MediaEmptyState` across `#studio-live-img`, `#static-heatmap-img`, `#tag-roi-crop-img`, `#snapshot-modal-img`, `#enroll-crop-preview-img`, and `#test-preview-img`; eliminate duplicate `#tab-studio` stream attaches, `img.src = ''` root-HTML fetches, and raw broken `alt="Studio Feed"` icons on cold-boot/offline/0-camera states (`Finding 5`, keeping `studio.js <= 350L`).
- [x] **tests/test_step1_dialogs_enrollment_and_media_ui.py**: Add Node VM & surface contract tests (`<= 40L`/method) covering `.form-row`/`.col-*` layout rules, unified Enrollment video stage & true-FPS frame step, Two-State `#modal-tag-entity` + non-closing candidate `✕`, `OverlayLayers.streamCache` invalidation, `MediaEmptyState` on `#studio`/modals, and `0` `surface --verify` mismatches.

---

## Milestone 3: Isolated `system-diagnostics` & Workspace Probe Elevation

> *Deferred to Next Turn / Milestone 3*

- [ ] **<config_dir>/skills/system-diagnostics/scripts/surface_verifier.py** + **<config_dir>/skills/system-diagnostics/scripts/cross_module_rules.py** + **<config_dir>/skills/system-diagnostics/scripts/audit_layout.js**: Add `[UNDEFINED_LAYOUT_CLASS]` HTML-to-CSS layout class verification, `CALLABLE_SIGNATURE_DRIFT` AST rule inside `try/except`, and `audit_layout.js` checks for empty-`src`/broken `<img>` elements and horizontally squeezed modal `.data-table`/form controls (`< 350L`/file, `<= 40L`/fn).
- [ ] **<config_dir>/skills/system-diagnostics/tests/**: Add unit tests (`<= 40L`/method) for `[UNDEFINED_LAYOUT_CLASS]`, `CALLABLE_SIGNATURE_DRIFT`, and modal/media `audit_layout.js` checks, and run full skill self-tests.
- [ ] **.diagnostics/probes/video_studio_contract_probe.py** + **.diagnostics/probes/replay_pipeline_probe.py** + **.diagnostics/probes/spa_nine_tab_cdp_probe.py**: Upgrade probes to test `/api/enroll` -> `create_video_indexer()` -> `/detections` + retroactive relabeling, automatic sighting crop persistence, cold-hash/offline/0-camera `#studio` media surfaces, modal column ergonomics, and non-closing candidate `✕`.
- [ ] **CHANGELOG.md**: Record Step 1 completion via `'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'`.

---

## Scenario Combinations Matrix

| Scenario | Verification Command | Expected Outcome |
| :--- | :--- | :--- |
| **Milestone 1 Backend Re-ID, Relabeling & Locks** | `python skills/system-diagnostics/scripts/diagnose.py tests tests.test_step1_reid_sightings_and_locks tests.test_step3_roi_recognition_api tests.test_dashboard` | `DualModel` matches enrolled identities in live/video/replay; retroactive relabel updates `video_runs`; auto-sightings write crops; `record_human_feedback("reject")` succeeds; zero lock-over-I/O |
| **Milestone 2 Modal Ergonomics, Enrollment & Media Surfaces** | `python skills/system-diagnostics/scripts/diagnose.py tests tests.test_step1_dialogs_enrollment_and_media_ui tests.test_step1_frontend_bugs tests.test_step4_p2_frontend_contracts` | `.form-row`/`.col-*` active; single-stage Enrollment scrubs true FPS; Two-State tag modal & candidate `✕` work without closing; `MediaEmptyState` prevents raw `alt` icons; `0` `surface --verify` mismatches |
| **Milestone 3 Skill Self-Tests & Probes** | `python -m unittest discover -s skills/system-diagnostics/tests -p "test_*.py"; python skills/system-diagnostics/scripts/diagnose.py probe run video_studio_contract_probe; python skills/system-diagnostics/scripts/diagnose.py probe run replay_pipeline_probe; python skills/system-diagnostics/scripts/diagnose.py probe run spa_nine_tab_cdp_probe` | 100% pass across upgraded SSOT diagnostic rules & workspace probes |
| **Full Regression, Surface, Layout & Docs Gate** | `python skills/system-diagnostics/scripts/diagnose.py surface --verify --strict; python skills/system-diagnostics/scripts/diagnose.py scan --path intelligent_tracker dashboard scripts --strict; python skills/system-diagnostics/scripts/diagnose.py ui --url "$APP_URL" --headless --capture-runtime --audit-layout --strict; MPLBACKEND=Agg python -m unittest discover tests; python -m sphinx -W --keep-going documentation/ documentation/_build/html/` | 0 surface/layout/scan defects, 0 broken/empty-`src` `<img>`, 100% `unittest` pass, 0 Sphinx warnings |
