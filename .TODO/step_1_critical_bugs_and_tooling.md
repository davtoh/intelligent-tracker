# Step 1: Critical Bug Remediations (`Findings 1–7`, `BE-1..BE-4`) & Tooling/Probe Elevation

> **Parent Roadmap**: `.TODO/tracking_intelligence_ux_master_roadmap.md` (`Step 1 of 4` | `--parent tracking_intelligence_ux_master_roadmap --milestone 1`).
> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–09`, Sections 4 & 6.4) & `docs/architecture/CURRENT_ARCHITECTURE.md` (Sections 5.1 & 6).
> **Split-Before-You-Grow Rule**: Keep every modified file `< 350L` (respecting stricter test ceilings `< 180L` for `index.html`, `< 220L` for tab partials, `< 240L` for `entity_modals.html` and `interactive_canvas.js`, `< 280L` for `unified_canvas_overlay.js`, `<= 350L` for `studio.js`) and every function `<= 40L` (`<= 35L` in `unified_canvas_overlay.js`), zero CSS `!important`, and reuse existing UI components (`UnifiedCanvasOverlay`, `OverlayControlBar`, `FrameSurface`, `RoiDrawTagger`).

---

## Milestone 1: Backend Critical Seams (`BE-1`, `BE-2`, `BE-4`, `Finding 1` & `Finding 4`)

- [ ] **dashboard/dependencies.py**: Remove the `pool.primary_stream` fallback inside `resolve_stream_manager()` when an explicit `camera_id` is passed (`Finding 1`: return `None` when `pool.get_stream(camera_id)` is missing so `/stream/{id}`, `/ws/{id}`, and `/freeze_frame` fail explicitly as offline instead of aliasing another camera); fix missing `Optional` annotations flagged by `mypy`.
- [ ] **dashboard/services/roi_recognition_service.py**: Fix `extract_roi_crop()` (`Finding 4`: when `is_direct_crop=True`, return `frame` immediately without applying full-frame `bbox` coordinates onto an already-cropped `crop_base64` image; keep file `< 350L` by trimming/extracting helpers if needed).
- [ ] **intelligent_tracker/repositories/signature_repo.py**: Add `except Exception: self._conn.rollback(); raise` around writes in `add_signature()` and `update_entity_signature()` (`BE-1`) matching all sibling repository mixins.
- [ ] **dashboard/app.py**: Decouple `app.state.db` ownership from `primary_sm.db` (`BE-2`) so restarting `primary_stream` (`PipelineBundle.close()`) never closes `app.state.db`, `ScenarioManager.db`, or `WorldQueryEngine.db`; declare `scenario_manager` explicitly on `StreamPoolCoordinator.__init__` instead of dynamic attribute assignment.
- [ ] **dashboard/routers/tagging.py** + **dashboard/routers/analytics.py**: Honor `Depends(get_db)` and `Depends(get_camera_pool)` instead of bypassing `app.dependency_overrides` via `_build_service()` / `_resolve_analytics_db()` (`BE-4`).
- [ ] **dashboard/services/stream_recording.py** + **dashboard/camera_pool.py** + **dashboard/services/camera_pool_queries.py**: Snapshot state under `StreamRecordingController._lock` and `CameraPool._lock`, then execute SQLite (`save_video_run`, gallery/RSAC reloads) and `save_cameras()` JSON disk writes strictly outside locks (`BE-4`).
- [ ] **dashboard/services/async_inference_worker.py**: Fix `mono_ts` / `_inference_monotonic_ts` fallbacks at `submit()` and `_merge_cached_step_result()` to default to `time.monotonic()` rather than Unix epoch `timestamp` (`BE-4`; keep functions `<= 40L`).
- [ ] **tests/test_step1_backend_bugs.py** *(New)*: Add targeted unit/integration tests (`<= 40L`/method) covering: (1) offline `usb_2` `/stream/usb_2`, `/ws/usb_2`, and `/api/cameras/usb_2/freeze_frame` returning offline/404/503 without `primary_stream` aliasing; (2) 2-step `POST /api/tag/recognize-roi` -> `POST /api/tag/commit` preserving full `(bw, bh)` crop dimensions and pixel variance; (3) `SignatureMixin` calling `rollback()` on SQLite error; (4) `app.state.db` remaining open after `restart_stream()`; (5) `tagging.py`/`analytics.py` honoring `dependency_overrides` and `AsyncInferenceWorker` monotonic fallback.

---

## Milestone 2: Frontend & Multiview Critical Bugs (`Findings 1–7` & `window.MULTIVIEW_TOKEN`)

> *Deferred to Next Turn / Milestone 2*

- [ ] **dashboard/static/index.html** + **dashboard/static/js/telemetry.js**: Load `nav_tabs_manager.js` strictly *after* `app.js` in `index.html` (`< 180L`) so `wrapGlobalSwitchTab()` always wraps `window.switchTab` on cold boot (`Finding 6`/`7`); fix `[DEAD_WINDOW_READ] window.MULTIVIEW_TOKEN` in `telemetry.js` (`<= 40L`/fn).
- [ ] **dashboard/static/js/live_player.js** + **dashboard/static/js/camera_grid.js**: Inspect `cam.status` (`offline`/`error`/`disabled`) in `CameraGrid.focusCamera()` and `LivePlayer.attachLiveStream()` so `1x1` displays an explicit offline poster instead of attempting a live stream (`Finding 1`); ensure `LivePlayer.attachHeatmapImage()` appends `?camera_id=` (`Finding 6`).
- [ ] **dashboard/static/js/multiview/grid_tile_overlay.js** + **dashboard/static/js/unified_canvas_overlay.js**: Keep `tile-overlay-canvas` responsive across `2x2 <-> 3x3 <-> 4x4` DOM tile reuse (`Finding 2`: attach a `ResizeObserver` or clear stale inline `style.width/height` after `syncCanvasDpr` and re-measure `.tile-video-container`, plus clear stale overlay boxes when tile streams pause/stop or `seq` stalls).
- [ ] **dashboard/static/app.js** + **dashboard/static/js/interactive_canvas.js**: Prevent `#interactive-canvas` `mousemove` and `onTelemetryReceived` `syncCanvas()` -> `ctx.clearRect()` from erasing active `RoiDrawTagger` drag rectangles (`Finding 3`); avoid submitting redundant full-frame `bbox` when a direct cropped `crop_base64` from `recognize-roi` is active (`Finding 4`); invoke `LivePlayer.attachHeatmapImage()` on `tab-analytics` entry (`Finding 6`; keep `app.js < 350L`, `interactive_canvas.js < 240L`).
- [ ] **dashboard/static/partials/modals/entity_modals.html** + **dashboard/static/js/universal_enrollment.js** + **dashboard/static/css/views.css**: Preserve drawn rectangular ROI aspect ratios with `object-fit: contain` on `#tag-roi-crop-img` and gallery/timeline thumbnails (`Finding 3`); group `#enroll-camera-select` inside the Enrollment preview column, bind a `change` listener that refreshes the freeze-frame preview immediately, and stop falling back from `""` (`Image Upload Only`) to `App.getActiveCameraId()` (`Finding 5`; keep `entity_modals.html < 240L` & `universal_enrollment.js <= 40L`/fn).
- [ ] **dashboard/static/partials/tabs/analytics.html** + **dashboard/static/partials/tabs/studio.html** + **dashboard/static/studio.js**: Ensure `#analytics` `#static-heatmap-img` renders immediately with a colorbar Low -> High legend and active camera badge (`Finding 6`); ensure `#studio` attaches the initial active channel on load/deep-link and mounts a `<video>` playback stage under `studio-canvas` so `"Recorded Videos"` options load, seek, and support zone/homography drawing (`Finding 7`; keep `studio.js <= 350L`).
- [ ] **tests/test_step1_frontend_bugs.py** *(New)*: Add Node VM & contract unit tests (`<= 40L`/method) covering `Findings 1–7` (`index.html` script order, offline `1x1` state, `ResizeObserver` / stale-track clear on `grid_tile_overlay.js`, integrated `app.js` + `RoiDrawTagger` drag persistence, `object-fit: contain`, `#enroll-camera-select` `change` preview update, `#analytics` heatmap attach, `#studio` initial attach + `<video>` Recorded Videos, and `MULTIVIEW_TOKEN`).

---

## Milestone 3: Isolated Tooling & Probe Elevation

> *Deferred to Next Turn / Milestone 3*

- [ ] **.diagnostics/probes/spa_nine_tab_cdp_probe.py**: Seed a mixed camera topology (live synthetic + offline `usb_2` + recorded video), switch `1x1 <-> 2x2 <-> 3x3 <-> 4x4`, assert `tile-overlay-canvas` `getBoundingClientRect()` matches `.tile-video-container`, verify `#studio-live-img` and `#static-heatmap-img` load cleanly (`naturalWidth > 0`), test `#enroll-camera-select` change, and check `"Recorded Videos"` selection.
- [ ] **.diagnostics/probes/video_studio_contract_probe.py**: Add a 2-step `POST /api/tag/recognize-roi` -> `POST /api/tag/commit` probe payload sending both `crop_base64` and `bbox`, asserting saved crop dimensions equal `(bh, bw)` (never `1x1`) with non-uniform pixel variance (`std > 1.0`).
- [ ] **<config_dir>/skills/system-diagnostics/scripts/audit_layout.js** + **surface_verifier.py** + **shadow_prober.py**: Isolate global `system-diagnostics` SSOT upgrades: (1) extend `audit_layout.js` (`< 350L`) with broken-`<img>` detection (`visible <img>` with `naturalWidth === 0` or missing `src`); (2) extend `surface_verifier.py` with query-param parity warnings and `<script>` load-order `window.*` wrap verification; (3) extend `shadow_prober.py` with a repo-rollback AST rule flagging `*_repo.py` `cursor.execute` + `commit()` methods lacking `rollback()` in `except`.
- [ ] **<config_dir>/skills/system-diagnostics/tests/**: Add targeted unit tests (`<= 40L`/method) for the new `audit_layout.js`, `surface_verifier.py`, and `shadow_prober.py` rules, and run full skill self-tests + `diagnose.py audit` on modified skill scripts.
- [ ] **CHANGELOG.md**: Record Step 1 completion via `'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'`.

---

## Scenario Combinations Matrix

| Scenario | Verification Command | Expected Outcome |
| :--- | :--- | :--- |
| **Milestone 1 Backend Critical Seams** | `python skills/system-diagnostics/scripts/diagnose.py tests tests.test_step1_backend_bugs tests.test_dashboard tests.test_step3_roi_recognition_api` | Offline `usb_2` never aliases `primary_stream`; 2-step ROI commit preserves `(bw, bh)` crop; `SignatureMixin` rolls back on error; `app.state.db` survives `restart_stream` |
| **Milestone 2 Frontend & Multiview Contracts** | `python skills/system-diagnostics/scripts/diagnose.py tests tests.test_step1_frontend_bugs tests.test_step4_p2_frontend_contracts tests.test_step4_overlay_bar_hud_and_multiview_ai` | `0` `MULTIVIEW_TOKEN` errors; `2x2<->4x4` overlay parity; ROI dashed rect persists; Enrollment auto-refreshes; `#analytics` heatmap & `#studio` initial/recorded feeds render |
| **Milestone 3 Skill Self-Tests & Global SSOT** | `python -m unittest discover -s skills/system-diagnostics/tests -p "test_*.py"` | 100% pass for broken-`<img>`, script-order/query-param, and repo-rollback rules |
| **4 Workspace Probes Gate** | `python skills/system-diagnostics/scripts/diagnose.py probe run cold_boot_world_probe; python skills/system-diagnostics/scripts/diagnose.py probe run replay_pipeline_probe; python skills/system-diagnostics/scripts/diagnose.py probe run video_studio_contract_probe; python skills/system-diagnostics/scripts/diagnose.py probe run spa_nine_tab_cdp_probe` | All 4 probes pass including mixed-camera `1x1`/`2x2`/`3x3`/`4x4` overlay parity & 2-step ROI crop shape |
| **Full Regression, Surface & Docs Gate** | `python skills/system-diagnostics/scripts/diagnose.py surface --verify --strict; python skills/system-diagnostics/scripts/diagnose.py scan --path intelligent_tracker dashboard scripts --strict; MPLBACKEND=Agg python -m unittest discover tests; python -m sphinx -W --keep-going documentation/ documentation/_build/html/` | 0 mismatches, 0 defects, 100% `unittest` pass, 0 Sphinx warnings |
