# Step 1: Studio Tab Lifecycle, Multiview Wake, 4x/8x Playback, Tag Queue State & Clock Hygiene

> **Parent Master Roadmap**: `.TODO/runtime_ux_and_reid_parity_master_roadmap.md` (`--parent runtime_ux_and_reid_parity_master_roadmap --milestone 1`)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 05, 06, 15, 18, 20, 21`), `docs/architecture/CURRENT_ARCHITECTURE.md` (`OBS-001`, `OBS-002`, `OBS-014`, `OBS-019`)
> **Goal**: Fix the four P0 runtime/UI seam regressions (`OBS-014` `#studio` black canvas on tab click, `OBS-002` multiview tiles stuck `HIBERNATING`, `OBS-001` `#videos` 4x/8x playback stall, `OBS-019` `TagTrackQueue` misplaced ROI & lost candidate deletions) and close the residual monotonic->wall clock leak (`dashboard/services/async_inference_worker.py:264-265`), while reducing `dashboard/static/app.js` (`353L`) strictly `< 350L` and adding workspace probe coverage (`multiview_grid_wake_probe.py` + `.nav-tab` click sweep in `deep_link_navigation_probe.py`).

---

## Public Surface, Modularity Budgets & Contracts

### 1. Modularity Budget Guardrails (Strict Enforcement)
- Global soft ceiling `<= 350L`/file (hard `< 500L`), `<= 12` methods/class, `<= 40L`/function, zero CSS `!important`.
- **Critical Tight-Cap Files (Verified Pre-Flight)**:
  - `dashboard/static/app.js`: **currently `353L` (WARN)** — MUST shrink `< 350L` (extract status/popover helpers or trim redundant bindings; do NOT add net lines).
  - `dashboard/static/studio.js`: `<= 349L`; `dashboard/static/js/studio_media.js`: `<= 200L`; `dashboard/static/js/interactive_canvas.js`: `< 240L`; `dashboard/static/js/tag_track_queue.js`: `< 250L`; `dashboard/static/js/camera_grid.js`: `< 350L`; `dashboard/stream_manager.py`: `< 350L`.

### 2. Scenario Combinations Matrix
| Scenario | Input / Trigger | Expected Outcome | Verification |
| :--- | :--- | :--- | :--- |
| **Reload `#live` -> Click `#studio` tab** | Boot SPA on `#live`, click `.nav-tab[data-tab="tab-studio"]` | `window.switchTab` runs, `'tab-changed'` fires, `StudioMedia.attachStudioMedia` attaches non-black stream/video | `deep_link_navigation_probe.py` |
| **`focus_only` Boot -> `2x2`/`3x3`/`4x4` Grid** | Start pool in `focus_only`, subscribe grid via `CameraGrid.setGridMode(2)` | `StreamManager._resume_video_source` clears `_is_hibernating`, `MultiviewSession` emits `source_status: "online"`, `.tile-status-badge` renders `ONLINE` | `multiview_grid_wake_probe.py` + Node VM test |
| **`#videos` `4x`/`8x` Playback** | Set speed `4x`/`8x` on recorded `<video>` with overlay + telemetry active | `scrubber_overlay.js` throttles/skips idle rAF and uses `{ responsive: true }`; `scrubber_playback_state.js` debounces `localStorage`; video range responses avoid `BaseHTTPMiddleware` stall | `test_step1_studio_multiview_playback_and_tag_queue.py` |
| **Multi-Box Tag Queue Next -> Prev** | Open queue, delete candidate chip on item 0, click Next, return Prev | Per-item frozen `cropBase64` + `suppressedEntityIds` retained in `TagTrackQueue`; `RoiDrawTagger` maps clicks in `sourceRes` matching `InteractiveCanvas` | `test_step1_studio_multiview_playback_and_tag_queue.py` |
| **`build_live_step_result` Clock Domain** | Call `build_live_step_result(..., now=time.monotonic(), wall_now=None)` | `wall_ts` resolves via `_wall_now()` (`time.time()`), never monotonic uptime | `test_step1_studio_multiview_playback_and_tag_queue.py` |

---

## Milestone 1: Studio Tab Lifecycle, Multiview Wake, 4x/8x Playback, Tag Queue & Probes *(Active)*

- [ ] **dashboard/static/app.js**: Bind `.nav-tab` clicks (`line 293`) and programmatic tab switches (`lines 153, 296, 328`) through `window.switchTab(...)` so `nav_tabs_manager.js` always emits `'tab-changed'` and syncs streams; call `window.Studio?.syncStudioTabState?.(tabId === 'tab-studio')` inside `handleTabLifecycle()`, and extract or compact helper code so `dashboard/static/app.js` drops from `353L` to `<= 340L` (`OBS-014`).
- [ ] **dashboard/static/js/studio_media.js**: Ensure `syncStudioTabState(true)` in `dashboard/static/studio.js` + `StudioMedia.attachStudioMedia()` clears stale hidden state on `#studio-live-img` / `#studio-video-player`, triggers a canvas redraw once media loads (`onload` / `loadeddata`), and shows `MediaEmptyState` only when genuinely offline (`OBS-014`).
- [ ] **dashboard/stream_manager.py**: Clear `self._is_hibernating = False` and reset `_latest_telemetry["status"] = "online"` synchronously inside `_resume_video_source()` when a subscriber wakes a hibernating stream so `MultiviewSession` immediately sees `"online"` (`OBS-002`).
- [ ] **dashboard/static/js/camera_grid.js**: Update `.tile-status-badge` to `online` inside `FrameSurface.pushFrame()` (`dashboard/static/js/multiview/frame_surface.js`), `GridTileOverlay.handleTelemetry()` (`dashboard/static/js/multiview/grid_tile_overlay.js`), and MJPEG `<img>` `onload` fallback; refresh camera statuses or reconcile stale `hibernating` cache when switching to `2x2`/`3x3`/`4x4` (`OBS-002`).
- [ ] **dashboard/static/js/scrubber_overlay.js**: Guard the `requestAnimationFrame` loop in `scrubber_overlay.js:250-313` to skip redraws when `activeLayers.size === 0` and `currentTime` + viewport size are unchanged, and pass `{ responsive: true }` to `UnifiedCanvasOverlay.syncCanvasDpr(...)` (plus `ResizeObserver` on resize) to eliminate per-frame style/layout thrash (`OBS-001`).
- [ ] **dashboard/static/js/scrubber_playback_state.js**: Debounce `localStorage.setItem()` persistence (`>= 500ms` trailing debounce + flush on `pause`/`ended`/`beforeunload`) in `saveFromPlayer()` / `scrubber_timeline_slider.js`, and add `waiting`/`stalled` recovery + direct range-stream bypass (`dashboard/app.py` / `dashboard/services/diagnostic_bridge.py` / `dashboard/routers/videos.py`) so `4x`/`8x` `<video>` range chunks are not buffered through `BaseHTTPMiddleware` (`OBS-001`).
- [ ] **dashboard/static/js/tag_track_queue.js**: Store per-item `{ frozenCropBase64, suppressedEntityIds, cachedCandidates, selectedEntityId, notes }` on each `TagTrackQueue` entry so navigating Next -> Prev restores edited suppressions and uses the frozen crop instead of re-cropping advancing live frames (`OBS-019`).
- [ ] **dashboard/static/js/interactive_canvas.js**: Pass `sourceRes` dimensions (falling back to `naturalWidth/Height` only when `sourceRes` is unavailable) into `RoiDrawTagger` `getSourceContext` (`line 219`), preserve per-layer `sourceResolution` when aggregating tracks in `scrubber_overlay.js`, and wire `TagFeedbackActions.discourageCandidate` (`dashboard/static/js/tag_feedback_actions.js`) to record suppressions into `TagTrackQueue` (`OBS-019`).
- [ ] **dashboard/services/async_inference_worker.py**: Fix `build_live_step_result()` (`lines 264-265`) so `wall_ts` always uses `_wall_now()` unless `wall_now` is explicitly passed (never assigning monotonic `now` into `wall_ts`).
- [ ] **tests/test_step1_studio_multiview_playback_and_tag_queue.py**: Add isolated unit + Node VM tests (`< 340L`) verifying `window.switchTab` `.nav-tab` lifecycle & `app.js < 350L`, `StreamManager._resume_video_source` + grid tile badge `online` transitions, debounced `scrubber_playback_state` & `scrubber_overlay` `{ responsive: true }` behavior, `TagTrackQueue` Next->Prev crop/suppression retention + `sourceRes` alignment, and `build_live_step_result` wall-clock isolation.
- [ ] **.diagnostics/probes/multiview_grid_wake_probe.py**: Add workspace probe booting `CameraPool` in `focus_only`, subscribing a `MultiviewSession` for `2x2`, and asserting `_is_hibernating is False` and `source_status == "online"`; extend `.diagnostics/probes/deep_link_navigation_probe.py` to reload on `#live`, click the `#studio` `.nav-tab` element in DOM, and assert Studio media/canvas attaches non-black content.
- [ ] **Verifier (Step 1)**:
  - [ ] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/static/app.js dashboard/static/js/nav_tabs_manager.js dashboard/static/studio.js dashboard/static/js/studio_media.js dashboard/stream_manager.py dashboard/static/js/camera_grid.js dashboard/static/js/multiview/frame_surface.js dashboard/static/js/multiview/grid_tile_overlay.js dashboard/static/js/scrubber_overlay.js dashboard/static/js/scrubber_timeline_slider.js dashboard/static/js/scrubber_playback_state.js dashboard/static/js/interactive_canvas.js dashboard/static/js/tag_track_queue.js dashboard/static/js/tag_feedback_actions.js dashboard/services/async_inference_worker.py tests/test_step1_studio_multiview_playback_and_tag_queue.py --max-lines 350 --max-fn-lines 40`
  - [ ] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step1_studio_multiview_playback_and_tag_queue.py tests/test_live_studio_sync.py tests/test_step3_tag_modal_integration.py`
  - [ ] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run multiview_grid_wake_probe`
  - [ ] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run deep_link_navigation_probe`
  - [ ] `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify`
