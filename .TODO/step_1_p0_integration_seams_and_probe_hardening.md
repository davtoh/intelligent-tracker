# Step 1: P0 Integration Seams, High-Visibility Fixes & Probe Hardening

> **Parent Roadmap**: `.TODO/integration_seams_entity_persistence_master_roadmap.md` (`Step 1 of 4` | `--parent integration_seams_entity_persistence_master_roadmap --milestone 1`).
> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–20`) & `docs/architecture/CURRENT_ARCHITECTURE.md` (`BUG-10`..`BUG-21`, `BUG-27`..`BUG-29`).
> **Execution Rule**: Strict **1-Milestone-Per-Turn**. Execute Milestone 1 first via `/frontier-architect continue step_1_p0_integration_seams_and_probe_hardening`; Milestones 2 and 3 are deferred to subsequent turns. Every milestone passes a fresh **Review Gate** before advancing.

---

## Pre-Flight Architecture & Modularity Contract

### Hard Budget & Invariant Guards (Measured Baseline)
- **Strict File & Method Ceilings (DO NOT EXCEED)**:
  - `dashboard/services/roi_recognition_service.py`: currently `354L` (`12` methods) — extract helpers into dedicated service modules instead of adding lines/methods.
  - `dashboard/routers/rsac.py`: currently `360L` — extract enrollment-sighting orchestration into a service helper instead of expanding `rsac.py`.
  - `dashboard/dependencies.py`: currently `348L` (`< 350L`) — keep under `350L` when wiring `resolve_reid_profile` / gallery re-embed.
  - `dashboard/stream_manager.py`: currently `310L` (`12` methods) — call module-level `deep_merge` in `_init_manager_config`, adding `0` methods to `StreamManager`.
  - `intelligent_tracker/batch.py`: currently `305L` (`12` methods) — keep `VideoIndexer <= 12` methods; extract helpers.
  - `intelligent_tracker/events/bus.py`: currently `174L` (`11` methods) — keep `EventBus <= 12` methods.
  - `intelligent_tracker/scenario_storage.py`: currently `236L` (`< 240L` enforced by `tests/test_step4_preflight_budgets.py`) — extract per-shape upsert sync helper if `> 3L`.
  - `dashboard/services/camera_config_store.py`: `< 180L` (`<= 8` methods, enforced by `tests/test_dashboard_di.py`).
  - `dashboard/static/index.html`: currently `171L` (`< 180L` enforced by `tests/test_step3_architecture_budgets.py`) — load `app_navigation.js` / `detector_config_panel.js` via `partials/scripts_traceability.html` (after `app.js` and before `nav_tabs_manager.js` — note `app.js` / `nav_tabs_manager.js` order in `index.html`!).
  - `dashboard/static/partials/modals/camera_modals.html`: currently `238L` (`< 240L` enforced by `tests/test_step3_architecture_budgets.py`) — extract inline detector block into `partials/modals/detector_config_panel.html` and replace with `{% include %}`.
  - `dashboard/static/partials/modals/entity_modals.html`: currently `219L` (`< 240L`).
  - `dashboard/static/js/camera_ai_config.js`: currently `279L` (`< 280L`) — place new COCO multi-select / `agnostic_nms` panel logic in `detector_config_panel.js`.
  - `dashboard/static/js/live_player.js` (`347L`), `dashboard/static/js/gallery_timeline.js` (`343L`), `dashboard/static/js/universal_enrollment.js` (`347L`), `dashboard/static/studio.js` (`347L`) — all `<= 350L`.
  - `<config_dir>/skills/system-diagnostics/scripts/cdp_inspect.py` (`346L`), `surface_contracts.py` (`328L`), `cross_module_rules.py` (`320L`), `audit_layout.js` (`307L`), `probe_runner.py` (`267L`) — extract helpers to keep every script `< 350L` and every function `<= 40L`.
- **Invariants**:
  - `app.js` loads before `app_navigation.js` and `nav_tabs_manager.js`.
  - All `*_repo.py` writes call `self._conn.rollback()` in `except` before re-raising.
  - All tests use `tempfile.TemporaryDirectory()`, `detector=mock`, reverse-order `addCleanup()`, and zero live `configs/cameras.json` or `data/*.db` mutations.

---

## Milestone 1: Backend P0 Integration Seams (`BUG-10`..`BUG-13`, `BUG-15`, `BUG-16`, `BUG-18`, `BUG-29`) *(Active Slice)*

- [x] **intelligent_tracker/reid/profile.py** + **configs/default.yaml** + **configs/demo.yaml** + **intelligent_tracker/pipeline/config.py** + **dashboard/services/pipeline_factory.py** + **intelligent_tracker/batch.py** + **dashboard/services/roi_recognition_service.py** + **dashboard/dependencies.py**: Create canonical `resolve_reid_profile(cfg)` SSOT defaulting to `DualModel` (`dual`), treat YAML `reid.model` as advisory with a loud boot warning on mismatch, set `configs/default.yaml` & `configs/demo.yaml` `reid.model: "dual"`, and wire `resolve_reid_profile` across pipeline, `VideoIndexer`, `RoiRecognitionService` (via extracted helper keeping `<= 350L` / `<= 12` methods), and `dependencies.py` (`< 350L`).
- [x] **intelligent_tracker/repositories/signature_repo.py** + **intelligent_tracker/reid/gallery_reembed.py** + **dashboard/services/gallery_health_service.py** + **dashboard/routers/gallery_health.py** + **dashboard/app.py**: Log loud warnings once and increment a skip counter on dimension mismatch in `SignatureMixin._build_gallery_matrix` (`:180-181`), add idempotent startup re-embedding of wrong-dim gallery signatures from stored `crop_path`/avatars in `gallery_reembed.py`, and expose `GET /api/system/gallery-health` (`<= 25L` route) wired at lifespan.
- [x] **dashboard/services/stream_telemetry.py**: Include `entity_id` and `entity_name` in `_extract_track_telemetry()` (`:61-77`) so live bounding boxes and `#modal-tag-entity` receive enrolled identities.
- [x] **intelligent_tracker/config_merge.py** + **dashboard/stream_manager.py** + **dashboard/services/camera_config_store.py** + **intelligent_tracker/detectors/onnx_detector.py** + **intelligent_tracker/pipeline/config.py**: Add `deep_merge(base, override)` and wire it into `dashboard/stream_manager.py:_init_manager_config` (`:91`) so `classes: ["person"]` survives partial camera overrides; update `CameraConfigStore.update_entry()` (`:160-161`) so explicit `"classes": None` clears classes instead of being skipped; add `agnostic_nms: bool = True` option through `PipelineConfig` into `OnnxDetector._build_detections` (`:255-256`).
- [x] **intelligent_tracker/repositories/video_run_repo.py** + **dashboard/services/file_detection_replay.py** + **dashboard/services/async_inference_worker.py**: Add `get_latest_run_matching(video_filename, detector_signature)` on `VideoRunRepositoryMixin` (`< 12` methods) and fall back to live inference in `FileDetectionReplayProvider` / `build_live_step_result` (`:273-279`) when no cached run matches the camera's active detector config (`detector`, `confidence`, `classes`, `agnostic_nms`); fix monotonic fallback `mono_ts = time.monotonic()` at `async_inference_worker.py:151-155`.
- [x] **intelligent_tracker/events/bus.py** + **dashboard/services/alerts_query_service.py** + **dashboard/services/events_admin_service.py** + **dashboard/routers/events_admin.py**: Convert `EventBus` into a write-through producer persisting alerts to SQLite first and streaming new IDs only; query SQLite strictly in `query_merged_events` (`:98-125`) so `EventBus` items never shadow SQLite `is_read`/delete state; add bulk `acknowledge`, `delete`, and `export` by explicit `event_ids` list or filter (`events_admin.py`).
- [x] **intelligent_tracker/repositories/schema_manager.py** + **intelligent_tracker/repositories/analytics_repo.py** + **intelligent_tracker/enrollment.py** + **dashboard/routers/rsac.py** + **intelligent_tracker/active_learning_actions.py** + **dashboard/services/video_run_relabel_service.py** + **dashboard/services/analytics_query_service.py**: Add idempotent `PRAGMA user_version` migration adding `sightings.camera_id` and `sightings.run_id` (backfilled from `source`/`video_filename`), write cropped seed sightings on live/video/ROI enrollment (`enrollment.py`, service helper called by `routers/rsac.py` keeping `<= 360L` -> `< 350L`, `active_learning_actions.py`), backfill throttled sightings (`1` per track per `N` s) on `VideoRunRelabelService`, and populate `/sightings/sources` with all known cameras + videos.
- [x] **intelligent_tracker/scenario_storage.py**: Add per-shape upsert synchronization on scenario load (via extracted helper keeping `scenario_storage.py < 240L`) so YAML/memory zones & tripwires always have SQLite rows for non-destructive `PUT` edits.
- [x] **tests/test_step1_seams_backend.py**: Add isolated unit and integration tests (`tempfile.TemporaryDirectory()`, `detector=mock`, reverse `addCleanup()`, `<= 40L`/method) verifying `resolve_reid_profile` over `configs/default.yaml`, gallery-health & re-embed, `deep_merge` + explicit `null` class clearing + `agnostic_nms`, detector-signature replay matching, write-through SQLite alerts + bulk IDs, `sightings.camera_id`/`run_id` + enrollment seeds + relabel backfill, scenario per-shape DB upsert, and `async_inference_worker` monotonic tuple fallback.

**Milestone 1 Verifier**:
```bash
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step1_seams_backend.py tests/test_camera_detector_config.py tests/test_step3_alerts_backend.py tests/test_step1_reid_sightings_and_locks.py
```

---

## Milestone 2: Frontend P0/P1 Seams, Deep-Link Navigation & Detector Panel (`BUG-14`, `BUG-15`, `BUG-17`, `BUG-19`..`BUG-21`, `BUG-27`, `BUG-28`)

> *Deferred to Next Turn / Milestone 2*

- [x] **dashboard/static/js/app_navigation.js** + **dashboard/static/app.js** + **dashboard/static/index.html** + **dashboard/static/partials/scripts_traceability.html** + **dashboard/static/js/gallery_timeline.js** + **dashboard/static/js/alerts_admin.js** + **dashboard/static/js/analytics_drilldown.js**: Create `app_navigation.js` (`App.navigate(tab, SourceRef)`, hash parameter parser `#tab?k=v`, full `App.switchCamera` syncing `#live-stream-img`, `#active-camera-select`, `#video-stream-title`, and `CameraManager.focusCamera`), keep `nav_tabs_manager.js` loaded after `app.js`/`app_navigation.js` (`index.html < 180L`), update `jumpToLiveSource`, `jumpToLiveMonitor`, `jumpToScenarioStudio` (`await loadStudioChannels()`, pass `zoneId`), and heatmap/flow drill-downs to call `App.navigate`, and await `loadTimelineFilters()` + wire `start_time`/`end_time` (`from`/`to`) in `gallery_timeline.js` (`<= 350L`) & `/sightings`.
- [x] **dashboard/static/js/studio_shape_editor.js** + **dashboard/static/js/studio_canvas.js** + **dashboard/static/partials/tabs/studio.html** + **dashboard/static/studio.js**: Fix `pointsChanged` typo (`b[1][1]` -> `b[i][1]`) at `studio_shape_editor.js:18`, bind `setPointerCapture` / window-level `pointerup` (`mouseup`) in `studio_canvas.js` so outside-canvas drag releases commit cleanly, and hide `#studio-status-banner` except on warnings or errors.
- [x] **dashboard/static/js/live_player.js** + **dashboard/static/js/telemetry.js** + **dashboard/static/app.js**: Replace `&bull;` with `%E2%80%A2` in `STANDBY_POSTER_SVG` (`live_player.js:9`, `<= 350L`) and allow MJPEG reattach on resume; update `#connection-status-pill` and `#drawer-connection-status-pill` from telemetry `status`/`detector_status` (`online` / `hibernating` / `simulation` / `offline`).
- [x] **dashboard/static/css/modals.css** + **dashboard/static/partials/modals/entity_modals.html** + **dashboard/static/js/scrubber_timeline_slider.js** + **dashboard/static/js/enrollment_stage_controller.js**: Replace cramped `1fr 1fr` `.modal-lg` layout with wide adaptive `width: min(96dvw, 1400px)` + auto-fit `minmax(min(100%, 440px), 1fr)` grid (`modals.css`), add `min-width: 0` & `flex-wrap: wrap` around `#enroll-camera-select` & `.section-subhead` (`entity_modals.html`), and update Enrollment scrubber to grab on `loadeddata`/`seeked` and seek to `#tab-videos` Video Studio `currentTime`.
- [x] **dashboard/static/partials/modals/detector_config_panel.html** + **dashboard/static/js/detector_config_panel.js** + **dashboard/static/partials/modals/camera_modals.html** + **dashboard/static/js/camera_ai_config.js**: Extract inline detector controls from `camera_modals.html` (`< 240L`) into `detector_config_panel.html` + `detector_config_panel.js` (COCO multi-select hydrated from `/api/system/capabilities` `coco_classes`, confidence slider, and `agnostic_nms` toggle default ON, keeping `camera_ai_config.js < 280L`).
- [x] **dashboard/static/partials/tabs/alerts.html** + **dashboard/static/js/alerts_view.js**: Add per-row selection checkboxes and `"Select All Matching"` wired to bulk acknowledge, delete, and export actions.
- [x] **tests/test_step1_seams_frontend.py**: Add Node VM (`vm.runInNewContext`) & contract tests (`<= 40L`/method) covering `App.navigate` hash routing & full `switchCamera` sync, `await loadTimelineFilters()` + time params, `pointsChanged` vertical drag + window pointer release, percent-encoded `STANDBY_POSTER_SVG`, enrollment `loadeddata` + playhead seek, connection pill status states, detector panel payload (`classes: null`, `agnostic_nms`), and alerts row selection.

**Milestone 2 Verifier**:
```bash
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step1_seams_frontend.py tests/test_step3_alerts_ui.py tests/test_step3_timeline_pagination.py tests/test_step4_studio_shape_editor_ui.py
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify --strict
```

---

## Milestone 3: Shared `system-diagnostics` Upgrades & Seam-Level Workspace Probes *(Deferred to Next Turn / Milestone 3)*

> *Deferred to Next Turn / Milestone 3*

- [x] **<config_dir>/skills/system-diagnostics/scripts/probe_runner.py**: Add explicit `INFRA_UNAVAILABLE` status and reject empty CDP sweeps (`sweep == {}` or `0` tabs) so browser/port failures never masquerade as feature assertions or passes.
- [x] **<config_dir>/skills/system-diagnostics/scripts/audit_layout.js** + **<config_dir>/skills/system-diagnostics/scripts/cdp_inspect.py**: Extract helper modules as needed to keep `< 350L`/file and `<= 40L`/fn; add `data:image` XML/SVG decode verification, flex child-box-outside-parent overflow checks across `960`/`1280`/`1920` viewports with long `<option>` strings, and first-frame enrollment canvas luminance check.
- [x] **<config_dir>/skills/system-diagnostics/scripts/cross_module_rules.py** + **<config_dir>/skills/system-diagnostics/scripts/static_auditor.py** + **<config_dir>/skills/system-diagnostics/scripts/surface_contracts.py**: Add AST rule flagging silent shape/dimension-guarded `continue` loops without logging/metric, plus `fetch` HTTP method parity & `App.navigate` jump-button verification.
- [x] **<config_dir>/skills/system-diagnostics/tests/**: Add unit tests (`<= 40L`/method) covering `INFRA_UNAVAILABLE`, empty-sweep rejection, `data:image` decode, flex child-overflow, silent-skip AST rule, and fetch-method parity.
- [x] **.diagnostics/probes/effective_config_probe.py** + **.diagnostics/probes/deep_link_navigation_probe.py** + **.diagnostics/probes/studio_drag_put_probe.py** + **.diagnostics/probes/alerts_store_probe.py** + **.diagnostics/probes/sightings_provenance_probe.py** + **.diagnostics/probes/spa_nine_tab_cdp_probe.py**: Create the 5 seam probes and update `spa_nine_tab_cdp_probe.py` to emit `INFRA_UNAVAILABLE` on Chrome/sweep failure instead of 16 cascading fakes.
- [x] **CHANGELOG.md**: Record Step 1 completion via `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add`.

**Milestone 3 Verifier**:
```bash
python -m unittest discover -s "<config_dir>/skills/system-diagnostics/tests" -p "test_*.py"
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run effective_config_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run deep_link_navigation_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run studio_drag_put_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run alerts_store_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run sightings_provenance_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run spa_nine_tab_cdp_probe
```

---

## Scenario Combinations Matrix

| Scenario Dimension | Test / Probe Matrix Covered | Expected Outcome |
| :--- | :--- | :--- |
| **Camera Type (`usb` x `synthetic` x `video`)** | USB live (`agnostic_nms=True`), `synthetic_01` (`simulation`/`hibernating` pill), `video` camera (`replay` matching signature vs. mismatch -> live inference) | Correct connection pill states; no stacked `person`/`dog`/`cat` duplicates; video camera replays only matching detector config |
| **Re-ID Profile (`DualModel` vs. wrong-dim DB)** | Enrolled `DualModel` vs. legacy `384D` DB row + `configs/default.yaml` boot | `resolve_reid_profile` stays `dual`, `/api/system/gallery-health` reports parity, startup re-embeds stale dims, live/tag match succeeds |
| **Detector Classes (`["person"]` preserved vs. `null` cleared)** | Partial camera update (`{"detector":{"model":"yolov8"}}`) vs. explicit clear (`{"classes": null}`) | `deep_merge` preserves `default.yaml` `classes: ["person"]` on partial updates and clears to all COCO only on explicit `null` |
| **Alerts Store (`EventBus` + SQLite seeded)** | `EventBus` emits alert -> SQLite persists -> `acknowledge` / `clear` / `delete` / `export` | `GET /events` reflects SQLite mutations immediately with zero `EventBus` shadowing |

---

## Final Step Sign-Off Verifier (After Milestone 3)

```bash
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify --strict
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" scan --path intelligent_tracker dashboard scripts --strict
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker dashboard scripts
MPLBACKEND=Agg python -m unittest discover tests
python -m sphinx -W --keep-going documentation/ documentation/_build/html/
```
