# Re-ID Unification, Source Traceability & Studio UX Master Roadmap

> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–12`, Layers 1–5) & `docs/architecture/CURRENT_ARCHITECTURE.md` (branch `feature/integration-remediations` at commit `a0a50e2`, `1,008` passing tests).
> **How to use this document**: Execute one Step at a time via child plans linked in `.frontier/` (`--parent reid_unification_traceability_and_studio_ux_master_roadmap --milestone <N>`).
> **Decision Basis (`/grill-me`, 5/5 questions resolved)**:
> 1. **Dialogs, Enrollment Stage & `MediaEmptyState` (`Findings 1, 2, 3, 5`, `ADR-11`)**: Wide adaptive + resizable dialogs (`clamp(960px..1280px)`, CSS `resize`, `@container` `< 900px` stack, `min-width: 0`, `.form-row`/`.col-*`), `#gallery` Enrollment source context badge + single unified `<video>`/`#enroll-bbox-canvas` stage with true-FPS `±1 Frame` stepping, and one shared `MediaEmptyState` helper across `#studio`, `#analytics`, and modals.
> 2. **Canonical `DualModel` Re-ID, Auto-Sighting Crops & Two-State Tag UX (`Finding 4` & `Idea 5`, `ADR-10`/`ADR-11`)**: Canonical `DualModel` embeddings everywhere + retroactive `video_runs.frame_detections_json` & `CachedReplayProvider` relabeling + `OverlayLayers.streamCache` invalidation; throttled bounded automatic sighting crops with entity avatar fallback; Two-State `#modal-tag-entity` (Known Match vs. New Subject + non-closing candidate `✕`) and fixed `ConfidenceEngine.record_human_feedback()`.
> 3. **Dynamic Category Registry & Clean Defaults (`Idea 1`, `ADR-11`)**: Unify all `"Security Category"` selectors & filters onto `custom_categories` (`/api/rsac/categories`), replace residential demo seeds (`family_car`, `delivery_truck`, `cleaning_crew`, `guard_dog`) with clean universal defaults + JSON Preset Import/Export + inline `+ New / Manage Categories` action; make `configs/alert_demo.yaml` (`restricted_vault`) strictly opt-in.
> 4. **Source Traceability & Admin Alert Lifecycle (`Ideas 2, 3a, 3b`, `ADR-12`)**: `#timeline` `offset` pagination + Source badge/deep-link; `#analytics` X/Y scales + peak-click & `32x24` hotspot drill-down; `#alerts` `is_read` real unread badge (replacing stuck `"8"`), populated facets, Mark Seen / Delete / CSV-JSON-Snapshot Download, and source links.
> 5. **Interactive `#studio` Editing & Tooling Upgrades (`Idea 4`, `ADR-12`)**: Non-destructive `PUT` in-place zone/tripwire vertex & rename editing (preserving live counters and immutable history), interactive 2D minimap camera cones (filtering stale poses, click/drag cone editing), optional 0-GPU `video_runs` scenario re-evaluation, and upgraded `system-diagnostics` + workspace probes.

---

## Step 1: Canonical `DualModel` Re-ID Unification, Sightings Crops, Dialog Ergonomics, `MediaEmptyState` & Tooling Elevation
- [x] **Child Plan**: `.TODO/step_1_reid_unification_dialogs_and_tooling.md`
- [x] **Goal**: Fix `BUG-01`..`BUG-09` (`Findings 1–5`, `Idea 5`, residual locks/DI/signature crashes) so Gallery identities resolve everywhere in real time and on videos/replay, automatic sightings have thumbnails, Enrollment/Camera VMS dialogs are wide and responsive, `#studio` and modals never render broken `alt` images, `#modal-tag-entity` has clear 2-state feedback, and diagnostic tools/probes catch all regression classes automatically.
- [x] **Target Scope**:
  - [x] **Backend Re-ID Parity, Retroactive Relabeling & Concurrency (`BUG-01`, `BUG-02`, `BUG-06`, `BUG-08`)**: Unify Enrollment, live pipelines (`probe_db_reid=True`), `VideoIndexer`/`create_video_indexer()`, and `RoiRecognitionService` (`"onnx"`/`DualModel`) on `DualModel` with crop-based dimension backfill; relabel `video_runs.frame_detections_json` + refresh `CachedReplayProvider` on identity changes; save throttled auto-sighting crops in `emit_periodic_sighting()` with entity thumbnail fallback; fix `ConfidenceEngine.record_human_feedback("reject", camera_id=..., zone_id=...)` and `DELETE /entities/{id}` pool-wide reload; move JSON/nested locks out of `CameraPool._lock`, wire `app.state.confidence_engine`/`world_graph`, and fix `array_utils.py:134`.
  - [x] **Wide Resizable Dialogs, Unified Enrollment Stage, Two-State Tag Modal & `MediaEmptyState` (`BUG-03`, `BUG-04`, `BUG-05`, `BUG-06`, `BUG-09`)**: Add `modal_forms_grid.css` (`.form-row`, `.col-*`, `clamp` + `resize: both` + `@container`), `#gallery` Enroll context badge + unified Enrollment `<video>`/canvas stage at true FPS, Two-State `#modal-tag-entity` + non-closing candidate `✕` + `OverlayLayers.streamCache` invalidation, shared `MediaEmptyState` across `#studio`/`#analytics`/modals, and resolve all `surface --verify` mismatches & bypassed `openModal()` calls.
  - [x] **Tooling & Workspace Probe Elevation**: Add `[UNDEFINED_LAYOUT_CLASS]` (`surface_verifier.py`), `CALLABLE_SIGNATURE_DRIFT` (`cross_module_rules.py`), empty-`src`/broken-`<img>` & squeezed modal table/input checks (`audit_layout.js`) + skill self-tests, and upgrade `video_studio_contract_probe`, `replay_pipeline_probe`, and `spa_nine_tab_cdp_probe`.
- [x] **Definition of Done**: Upgraded probes, `system-diagnostics` self-tests, `surface --verify --strict`, `scan --strict`, and full `unittest` pass 100%.

---

## Step 2: Unified Dynamic Category Registry (`custom_categories` SSOT), Clean Universal Defaults & Demo Scenario Isolation *(Deferred to Step 2)*
- [x] **Goal**: Consolidate all entity, zone, filter, and RSAC categories onto `/api/rsac/categories` (`Idea 1`), replace residential demo categories with clean general-purpose defaults, add inline `+ New / Manage Categories` and JSON preset import/export, and make `configs/alert_demo.yaml` (`restricted_vault`) opt-in (`BUG-07`).
- [x] **Target Scope**:
  - [x] **Category SSOT, Universal Defaults & COCO Mapping**: Replace `family_car`/`delivery_truck`/`cleaning_crew`/`guard_dog` defaults with universal categories (`person`, `staff`, `visitor`, `vip`, `restricted`, `vehicle`, `pet`, `bag_parcel`, `asset`), map COCO classes cleanly (`car`/`truck`/`bus` -> `vehicle`, `backpack`/`suitcase` -> `bag_parcel`), migrate distinct `entities.category` values on boot, validate category slugs on entity/RSAC writes, and add `/api/rsac/categories/export` & `/import`.
  - [x] **Inline Quick-Create/Manage UI & Camera/Batch Category Pickers**: Replace static fallback `<option>` drifts across Enrollment, Tag ROI, Gallery filters, and Studio modals with unified `CategoryBadgeManager` + inline `+ New / Manage` trigger; upgrade `CameraFormHelpers` and Batch Video tracked-category pickers to consume `/api/rsac/categories`.
  - [x] **Opt-In Demo Scenarios**: Gate `configs/alert_demo.yaml` (`restricted_vault`) behind explicit `--demo` / `IT_LOAD_DEMO_SCENARIOS=1` (preserving opt-in tests and demos without polluting clean deployments).
- [x] **Definition of Done**: Dynamic categories created inline appear immediately across all modals, gallery filters, camera pickers, and RSAC rules, and fresh cold boots load zero `restricted_vault` demo alerts unless `--demo` is enabled.

---

## Step 3: `#timeline` Pagination & Source Links, `#analytics` Peak/Hotspot Drill-Down & `#alerts` Stateful Admin Lifecycle *(Deferred to Step 3)*
- [x] **Goal**: Deliver complete operational traceability across `#timeline`, `#analytics`, and `#alerts` (`Ideas 2, 3a, 3b`, `ADR-12`) and eliminate the stuck `"8"` alert badge (`BUG-07`).
- [x] **Target Scope**:
  - [x] **`#timeline` Pagination & Source Navigation**: Extend `GET /sightings` with `offset`, `source`, `video_filename`, and `{ items, total, offset, limit, has_more }` paginated mode; add Prev/Next/page controls, `Source` filter, source badges, and 1-click jump to Live Monitor or Video Studio `@ media_offset_sec`.
  - [x] **`#analytics` Peak & `32x24` Hotspot Drill-Down**: Expose explicit X/Y axes and time-bucket `[bucket_start, bucket_end]` metadata on `GET /analytics/flows`, expose `32x24` normalized grid density + scale ticks on `GET /analytics/heatmap?format=json`, and wire click-peak and click-hotspot drill-downs to filtered `#timeline`/`#alerts`/source views.
  - [x] **`#alerts` Unread State, Dynamic Facets & Admin Lifecycle**: Add `is_read` / `acknowledged_at` columns to `world_timeline_events`, compute real `unread_alert_count` in telemetry (fixing `#header-alert-badge` / `#drawer-alert-badge` stuck at `"8"`), add `GET /api/events/facets` populating `#alerts-filter-camera`/type/zone, add `PATCH /api/events/acknowledge`, `DELETE /api/events/{id}`, bulk clear, CSV/JSON/snapshot export (`dashboard/routers/events_admin.py`), and Zone/Source deep-links.
- [x] **Definition of Done**: Multi-page `#timeline` browsing, interactive chart/heatmap drill-downs, real unread badge clearing, populated `#alerts` filters, and export/delete actions pass API + headless CDP tests.

---

## Step 4: `#studio` In-Place Zone/Tripwire Vertex Editing, Interactive 2D Minimap & Zero-GPU Scenario Re-Evaluation *(Deferred to Step 4)*
- [ ] **Goal**: Upgrade `#studio` from delete-and-recreate geometry management to non-destructive in-place editing, interactive camera-cone manipulation on the 2D Tactical Minimap, and optional 0-GPU scenario re-evaluation (`Idea 4`, `ADR-12`).
- [ ] **Target Scope**:
  - [ ] **Non-Destructive `PUT` Geometry API & Zero-GPU Re-Evaluation**: Add `PUT /api/scenarios/zones/{camera_id}/{zone_id}` and `/tripwires/{camera_id}/{tripwire_id}` supporting vertex edits and rename while preserving live zone/tripwire counters and immutable `sightings`/`world_timeline_events` audit logs; add `POST /api/videos/re-evaluate-scenarios` recomputing `video_runs` alerts/zone/tripwire summaries over cached `frame_detections_json` at 0 GPU cost.
  - [ ] **Interactive `#studio` Canvas & 2D Minimap**: Extract `studio_shape_editor.js` (idle-mode polygon/tripwire hit-testing, vertex drag, shape move, inline rename) and `world_minimap_interactions.js` (prune stale/deleted cameras from `/api/topology/world-map`, click FOV cones to focus camera, drag position/yaw/range handles on `#bev-minimap-canvas`), plus `"Re-evaluate Scenarios"` action on indexed video runs.
- [ ] **Definition of Done**: Existing zones, tripwires, and minimap camera cones edit smoothly in place without wiping live counters or mutating historical audit rows, and 0-GPU video re-evaluation updates run metrics accurately.

---

## Master Verification Matrix

| Verification Gate | Command | Expected Result |
| :--- | :--- | :--- |
| **Skill Self-Tests** | `python -m unittest discover -s skills/system-diagnostics/tests -p "test_*.py"; python -m unittest discover -s skills/frontier-architect/tests -p "test_*.py"` | 100% pass after Step 1 Milestone 3 tool upgrades |
| **Cross-Contract & Static Gate** | `python skills/system-diagnostics/scripts/diagnose.py surface --verify --strict; python skills/system-diagnostics/scripts/diagnose.py scan --path intelligent_tracker dashboard scripts --strict; python skills/system-diagnostics/scripts/diagnose.py audit --path intelligent_tracker dashboard scripts` | 0 surface/layout/signature mismatches, 0 active scan defects |
| **4 Unmocked Workspace Probes** | `python skills/system-diagnostics/scripts/diagnose.py probe run cold_boot_world_probe; python skills/system-diagnostics/scripts/diagnose.py probe run replay_pipeline_probe; python skills/system-diagnostics/scripts/diagnose.py probe run video_studio_contract_probe; python skills/system-diagnostics/scripts/diagnose.py probe run spa_nine_tab_cdp_probe` | 100% pass covering `Enroll -> Index/Replay -> Overlay`, sighting crops, modal layout, and 9-tab CDP |
| **Headless CDP Layout & Media Sweep** | `python skills/system-diagnostics/scripts/diagnose.py ui --url "$APP_URL" --headless --capture-runtime --audit-layout --stability-ms 2000 --strict` | 0 HTTP >= 400, 0 broken/empty-`src` `<img>`, 0 squeezed modal tables/inputs, 0 JS errors, 0 CLS/overflows |
| **Full Regression & Docs Gate** | `MPLBACKEND=Agg python -m unittest discover tests; python skills/system-diagnostics/scripts/diagnose.py arch-map --path .; python -m sphinx -W --keep-going documentation/ documentation/_build/html/` | 100% test pass, clean budgets, 0 Sphinx warnings |
