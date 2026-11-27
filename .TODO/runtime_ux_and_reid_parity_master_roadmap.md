# Runtime UX, Synthetic Re-ID Parity & Overflow Containment Master Roadmap

> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–21`, Layers 1–5) & `docs/architecture/CURRENT_ARCHITECTURE.md` (branch `feature/ci-and-debug-session-hardening`, `OBS-001`–`OBS-022`).
> **How to use this document**: Execute one Step at a time via child plans linked in `.frontier/` (`--parent runtime_ux_and_reid_parity_master_roadmap --milestone <N>`). Only Step 1 is detailed into a child plan upfront; Steps 2–4 are deferred and planned one step at a time. Every Step enforces modularity budgets (`<= 350L` soft / `< 500L` hard, `<= 12` methods/class, `<= 40L`/fn, routes `<= 25L`) and a mandatory **Review Gate** (a fresh reviewer separate from the author inspects the diff and verify output before advancing).
> **Decision Basis (`/grill-me`, 4/4 decisions locked)**:
> 1. **Scope Split (Q1)**: `OBS-001`..`OBS-019` + Architecture Hygiene live in this 4-Step Master Roadmap; Debug HUD enhancements (`OBS-020`..`OBS-022`) live in a separate standalone plan (`.TODO/debug_hud_trace_chips_export_and_dirty_state_plan.md`) scoped to `system-diagnostics`.
> 2. **Re-ID, Enrollment & Batch/Camera Config (Q2, `ADR-21`)**: Align `MockDetector` with `SyntheticFrameGenerator` `P1`/`P2` target pixels, add live ROI-draw collision + object suggestion preview in Enrollment (`OBS-010`), fix `GET /api/cameras` omitting `tracked_categories`/`agnostic_nms` so Edit preserves them (`OBS-018`), and add gallery/learned-class pickers + clear helper labels in Batch & Camera modals (`OBS-006`).
> 3. **Tripwire Directionality & Provenance (Q3, `ADR-21`)**: Render `IN`/`OUT` normal arrows + labels in `UnifiedCanvasOverlay` with a Studio direction-flip handle (`pt1 <-> pt2` swap, zero DB schema migration; `OBS-008`, `OBS-009`), attribute non-scenario batch review items to `video:<filename>` (`OBS-016`), and leave existing `"offline_video"` rows untouched unless explicitly cleared.
> 4. **4-Step Sequencing (Q4)**: Step 1 = Studio/Multiview/4x-8x Playback/Tag Queue P0s + Clock Hygiene; Step 2 = Synthetic Re-ID/Enrollment/Batch/Camera Config; Step 3 = Tripwire IN-OUT/Discovery/Review/Hygiene; Step 4 = CSS Overflows/Popover/Long-Fixture CDP & AST Guards.

---

## Step 1: Studio Tab Lifecycle, Multiview Wake, 4x/8x Playback, Tag Queue State & Clock Hygiene *(Active)*
- [x] **Child Plan**: `.TODO/step_1_studio_multiview_playback_and_tag_queue.md` (`--parent runtime_ux_and_reid_parity_master_roadmap --milestone 1`).
- [x] **Goal**: Eliminate `OBS-014` (`#studio` black canvas when clicked after reloading another tab), `OBS-002` (`2x2`/`3x3`/`4x4` tiles stuck `HIBERNATING` until mode toggle), `OBS-001` (`#videos` `4x`/`8x` playback stall from rAF reflow + `localStorage` thrash + range buffering), `OBS-019` (`TagTrackQueue` misplaced ROI & lost candidate deletions across Next/Prev), and the residual wall-clock leak in `dashboard/services/async_inference_worker.py:264-265`, while bringing `dashboard/static/app.js` (`353L`) back `< 350L` and adding `multiview_grid_wake_probe.py` + `.nav-tab` click coverage in `deep_link_navigation_probe.py`.
- [x] **Verifier**:
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/static/app.js dashboard/static/js/nav_tabs_manager.js dashboard/static/studio.js dashboard/static/js/studio_media.js dashboard/stream_manager.py dashboard/static/js/camera_grid.js dashboard/static/js/multiview/frame_surface.js dashboard/static/js/multiview/grid_tile_overlay.js dashboard/static/js/scrubber_overlay.js dashboard/static/js/scrubber_timeline_slider.js dashboard/static/js/scrubber_playback_state.js dashboard/static/js/interactive_canvas.js dashboard/static/js/tag_track_queue.js dashboard/static/js/tag_feedback_actions.js dashboard/services/async_inference_worker.py --max-lines 350 --max-fn-lines 40`
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step1_studio_multiview_playback_and_tag_queue.py`
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run multiview_grid_wake_probe`
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run deep_link_navigation_probe`
  - [x] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify`
- [x] **Review Gate**: Fresh reviewer inspects diff, modularity audit (`app.js < 350L`), and probe/test output before resolving `OBS-001`, `OBS-002`, `OBS-014`, `OBS-019` and advancing to Step 2.

---

## Step 2: Synthetic Re-ID Parity, Live ROI-Draw Enrollment & Camera/Batch Config *(Deferred to Next Turn / Milestone)*
- [ ] **Goal**: Align `MockDetector` (`intelligent_tracker/detectors/mock_detector.py`) with `SyntheticFrameGenerator` `P1`/`P2` pixel regions so enrolled `P1` matches in `#live` (`synthetic_01`) and `#videos` batch runs (`OBS-005`, `OBS-006`, `OBS-007`), refresh `#gallery` cleanly after enrollment even with active category/search filters (`OBS-004`), trigger debounced `/api/enroll/check-collision` + object suggestions on ROI `mouseup` (`OBS-010`), preserve `tracked_categories` & `agnostic_nms` across `GET /api/cameras` -> Edit (`OBS-018`), preserve `tracked_categories` in `video_analytics_service.py` `config_meta`, and expose `#gallery`/learned-class pickers + clear COCO vs. RSAC helper copy in Batch & Camera modals (`OBS-006`, `OBS-018`).
- [ ] **Target Scope**:
  - [ ] `intelligent_tracker/detectors/mock_detector.py`, `dashboard/services/video_analytics_service.py`, `dashboard/services/camera_pool_queries.py`, `dashboard/routers/system.py`.
  - [ ] `dashboard/static/js/universal_enrollment.js` (staying `<= 349L`), `dashboard/static/js/gallery_timeline.js`, `dashboard/static/js/video_batch.js`, `dashboard/static/partials/modals/video_modals.html`, `dashboard/static/js/camera_ai_config.js`, `dashboard/static/partials/modals/detector_config_panel.html`.
- [ ] **Verifier**: `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step2_synthetic_reid_and_config.py; python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run replay_pipeline_probe; python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run video_studio_contract_probe; python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify`.
- [ ] **Review Gate**: Fresh reviewer verifies synthetic `P1` Re-ID E2E match, camera edit round-trip, modularity budgets, and probe passes before resolving `OBS-004`–`OBS-007`, `OBS-010`, `OBS-018` and advancing to Step 3.

---

## Step 3: Tripwire `IN`/`OUT` Handle, Camera Discovery Parity, Batch Provenance & Arch Hygiene *(Deferred to Next Turn / Milestone)*
- [ ] **Goal**: Render `IN`/`OUT` normal vectors and side labels in `UnifiedCanvasOverlay.drawTripwires()` (`OBS-009`) plus a Studio direction-flip handle swapping `pt1 <-> pt2` and persisting via `PUT` (`OBS-008`), fix Windows device-index / `hikvision` active-index exclusion & `/api/cameras/test` device-name parity (`OBS-017`), attribute non-scenario batch review items to `video:<filename>` instead of `"offline_video"` (`OBS-016`), wire `WorldPolicy` (`intelligent_tracker/world/nodes.py`) or explicitly clean up modularity overruns (`dashboard/dependencies.py` `351L`, `dashboard/routers/rsac.py` `353L`, unused imports in `routers/rsac.py` & `_capture_guard_worker.py`).
- [ ] **Target Scope**:
  - [ ] `dashboard/static/js/unified_canvas_overlay.js`, `dashboard/static/js/studio_shape_editor.js`, `dashboard/static/js/studio_overlays.js`.
  - [ ] `intelligent_tracker/camera_device.py`, `intelligent_tracker/camera_device_enum.py`, `dashboard/services/camera_pool_queries.py`, `dashboard/services/camera_diagnostics.py`.
  - [ ] `dashboard/services/video_analytics_service.py`, `intelligent_tracker/pipeline/post_detection_governance.py`, `dashboard/dependencies.py`, `dashboard/routers/rsac.py`, `intelligent_tracker/video/_capture_guard_worker.py`.
- [ ] **Verifier**: `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step3_tripwire_discovery_provenance.py; python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run studio_drag_put_probe; python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run video_studio_contract_probe; python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" arch-map --path .`.
- [ ] **Review Gate**: Fresh reviewer verifies tripwire flip persistence, camera test parity, `video:<filename>` provenance, and `< 350L` budgets before resolving `OBS-008`, `OBS-009`, `OBS-016`, `OBS-017` and advancing to Step 4.

---

## Step 4: Layout Overflow Containment, Status Popover Cleanup & Long-Fixture Tooling Guards *(Deferred to Next Turn / Milestone)*
- [ ] **Goal**: Fix flex/select overflow regressions on `#videos .upload-status-hint` (`OBS-011`), `#analytics #analytics-source-select` (`OBS-013`), and `#review .review-card` (`OBS-015`), clear `.truncate-trigger` / `data-full-text` in `#connection-status-text` on camera/mode changes (`OBS-012`), and add long-filename CDP fixtures + JS AST scan guards so this class of regression is caught automatically.
- [ ] **Target Scope**:
  - [ ] `dashboard/static/css/scrubber.css`, `dashboard/static/css/sidebar.css`, `dashboard/static/css/analytics_alerts.css`, `dashboard/static/css/review.css`, `dashboard/static/app.js`, `dashboard/static/js/telemetry.js`.
  - [ ] `.diagnostics/probes/spa_nine_tab_cdp_probe.py` (long-filename fixtures + child-outside-parent checks) and `system-diagnostics` JS AST rules (`syncCanvasDpr` in rAF, `localStorage` in `timeupdate`, private `switchTab` vs `window.switchTab`).
- [ ] **Verifier**: `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run spa_nine_tab_cdp_probe; python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" scan --strict; MPLBACKEND=Agg python -m unittest discover tests; python -m sphinx -W --keep-going documentation/ documentation/_build/html/`.
- [ ] **Review Gate**: Fresh reviewer validates non-mocked branch sign-off, all workspace probes non-INFRA green, full `unittest`, Sphinx `-W`, and `diagnose.py scan --strict`, and closes resolved `OBS-*` entries via `diagnose.py observations resolve`.

---

## Scenario Combinations Matrix (Master Coverage)
| Scenario | Trigger | Expected Outcome | Step / Verifier |
| :--- | :--- | :--- | :--- |
| **Reload `#live` -> Click `#studio`** | User reloads SPA on `#live`, clicks `.nav-tab` for `#studio` | `window.switchTab` emits `tab-changed`; Studio media attaches non-black frame | Step 1 (`deep_link_navigation_probe`) |
| **Multiview `focus_only` -> `2x2`/`3x3`/`4x4`** | Boot in `focus_only`, switch grid layout | `_is_hibernating` clears synchronously; `.tile-status-badge` shows `ONLINE` without mode toggle | Step 1 (`multiview_grid_wake_probe`) |
| **`#videos` `4x`/`8x` Playback** | Set `playbackRate` to `4x`/`8x` on recorded video | rAF does not thrash CSS layout, `localStorage` debounced, playback advances without stall | Step 1 (`test_step1_studio_multiview_playback_and_tag_queue.py`) |
| **Multi-Box Tag Queue Next -> Prev** | Delete candidate relation on item 1, click Next, return Prev | Frozen `cropBase64` & suppressed candidate list persist; ROI maps in `sourceRes` | Step 1 (`test_step1_studio_multiview_playback_and_tag_queue.py`) |
| **Synthetic `P1` Enroll -> `#live` & `#videos`** | Enroll `P1` on `synthetic_01`, view `#live` & run batch | `MockDetector` aligns with `P1`/`P2`, matches `P1` in live/batch, `#gallery` refreshes immediately | Step 2 (`replay_pipeline_probe`) |
| **Edit Camera Preserves Config** | Add camera with `tracked_categories`, click Edit & Save | `GET /api/cameras` returns `tracked_categories` & `agnostic_nms`; Edit retains them | Step 2 (`test_step2_synthetic_reid_and_config.py`) |
| **Tripwire `IN`/`OUT` Flip Handle** | Select tripwire in `#studio`, click/drag flip handle | `pt1 <-> pt2` swaps, `IN`/`OUT` arrow flips, `PUT` persists across reload | Step 3 (`studio_drag_put_probe`) |
| **Batch Review Provenance & Discovery Test** | Run batch w/o scenario; test discovered USB camera | Review items carry `video:<filename>`; `/api/cameras/test` checks `device_name` | Step 3 (`video_studio_contract_probe`) |
| **60+ Char Filenames & Camera Switch Popover** | Long video filename across `#videos`/`#analytics`/`#review`; switch long->`cam_01` | Zero parent-box overflow across viewports; `#connection-status-pill` popover cleared | Step 4 (`spa_nine_tab_cdp_probe`) |
