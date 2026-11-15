# Step 2 Implementation Plan: Tab-Scoped Streams, Lazy Tab Data & Startup Fetch Deduplication

> **Parent Master Plan**: `.TODO/performance_and_processing_modes_master_roadmap.md` (Step 2)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md`
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–4 are *Deferred to Subsequent Turns*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map` & `diagnose.py audit`)

Measured against workspace baseline before edits (305 files, 55,962 lines, 108 FastAPI routes):
- `dashboard/static/partials/tabs/studio.html`: 94 lines (`OK < 350L`, 0 defects). Currently hardcodes `src="/stream/cam_01"` on `#studio-live-img`, opening a background MJPEG stream on boot while `#tab-studio` is hidden.
- `dashboard/static/partials/tabs/analytics.html`: 30 lines (`OK < 350L`, 0 defects). Currently hardcodes `src="/analytics/heatmap"` on `#static-heatmap-img`, triggering an eager heatmap image request on boot while `#tab-analytics` is hidden.
- `dashboard/static/js/nav_tabs_manager.js`: 200 lines (`OK < 350L`, 0 defects). Handles `.nav-tab` switching and scroll controls, delegating to `window.switchTab(tabId)` without dispatching a `tab-changed` event or syncing hidden-tab media streams.
- `dashboard/static/js/live_player.js`: 121 lines (`OK < 350L`, 0 defects). Provides `STANDBY_POSTER_SVG`, `detachLiveStream`, and `attachLiveStream` for `#live-stream-img`, but does not manage `#studio-live-img` or `#static-heatmap-img` lifecycle transitions.
- `dashboard/static/studio.js`: 320 lines (`OK < 350L`, 0 defects — keep `< 345L`, all functions `<= 40L`). Runs an unconditional 250ms (4 Hz) `setInterval` checking DOM state even when `#tab-studio` is inactive, and sets `#studio-live-img.src` regardless of tab visibility.
- `dashboard/static/js/scrubber_library_bridge.js`: 218 lines (`OK < 350L`, 0 defects). Eagerly fetches `/api/videos` on boot, auto-loads the preferred video into `<video id="scrubber-video-player">`, and triggers multi-MB `/api/videos/{filename}/report` and `/detections` fetches while the operator is on `#tab-live`.

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts (Zero-Regression Invariants)
- **DOM Element IDs Preserved**: `#live-stream-img`, `#studio-live-img`, `#static-heatmap-img`, `#studio-camera-select`, `#scrubber-video-player`, and `#scrubber-timeline-ticks` MUST remain in the rendered HTML (`tests/test_refactor_contract.py`).
- **LivePlayer API Contract**: `window.LivePlayer` (`dashboard/static/js/live_player.js`) preserves `STANDBY_POSTER_SVG`, `detachLiveStream(videoImg)`, `attachLiveStream(videoImg, activeCameraId, forceReconnect)`, `setStreamStatus(status)`, `toggleFullscreen(videoImg)`, `bindHudButtons(videoImg, getActiveCameraId)`, and `isPaused()` (`tests/test_step2_live_canvas_delegation.py`, `tests/test_dashboard_ui.py`), while adding `attachStudioStream(studioImg, targetId)`, `detachStudioStream(studioImg)`, `attachHeatmapImage(heatmapImg)`, and `syncTabStreams(previousTabId, targetTabId)`.
- **NavTabsManager Contract**: `window.NavTabsManager` (`dashboard/static/js/nav_tabs_manager.js`) preserves `scrollNext()`, `scrollPrev()`, `isAtStart()`, `isAtEnd()`, `updateScrollButtons()`, and `switchTab(tabId)` without calling `.scrollIntoView` (`tests/test_responsive_navigation.py`), while coordinating `window.LivePlayer.syncTabStreams(previousTabId, targetTabId)`, dispatching `CustomEvent('tab-changed', { detail: { previousTab, activeTab } })`, and providing an in-flight/boot GET request coalescer (`fetchJsonDeduplicated` / `installBootFetchDeduplicator`) for `/api/cameras` and `/api/videos`.
- **Studio Contract**: `dashboard/static/studio.js` preserves `"studio-camera-select"` and `"/api/videos"` references (`tests/test_step5_video_spatial_and_rsac.py`) and `window.Studio = { init: initStudio, loadScenario: loadCameraScenario, renderBEV: renderBEVMinimap }` while adding `startMinimapLoop()`, `stopMinimapLoop()`, and `syncTabVisibility(isActive)`.
- **ScrubberLibraryBridge Contract**: `window.ScrubberLibraryBridge` (`dashboard/static/js/scrubber_library_bridge.js`) preserves `updateLoadedTitle`, `handlePlayerError`, `syncLoadedVideoUI`, `bindCardSelectionEvents`, `bindVideoCardActions`, `loadVideosList`, `refreshTimelineTicks`, `applyPendingSeek`, and `handleSeekRequest` (`tests/test_scrubber_ux_fixes.py`, `tests/test_step5_timeline_ticks_and_deeplinks.py`). When `#tab-videos` exists in the DOM and is NOT `.active`, `loadVideosList` and `syncLoadedVideoUI` defer `<video>` selection and `/report` + `/detections` network fetches until `flushDeferredVideoLoad()` runs on `#tab-videos` activation (while continuing to execute immediately in isolated unit test DOMs where `#tab-videos` is absent).

### Modularity Guardrails
- `dashboard/static/partials/tabs/studio.html` MUST stay `< 110` lines.
- `dashboard/static/partials/tabs/analytics.html` MUST stay `< 45` lines.
- `dashboard/static/js/live_player.js` MUST stay `< 190` lines with all functions `<= 35` lines.
- `dashboard/static/js/nav_tabs_manager.js` MUST stay `< 280` lines (`<= 12` methods on `NavTabsManager`) with all functions `<= 35` lines.
- `dashboard/static/studio.js` MUST stay `< 345` lines (`< 350L` budget) with all functions `<= 40` lines.
- `dashboard/static/js/scrubber_library_bridge.js` MUST stay `< 295` lines (`< 350L` budget) with all functions `<= 40` lines.
- Every unit test method MUST stay `<= 40` lines (`AGENTS.md` Rule 3).

---

## 3. Phased Implementation Milestones

### Milestone 1: Hidden-Tab Stream Disconnection & Tab-Scoped Stream Lifecycle
- [x] **dashboard/static/partials/tabs/studio.html**: Replace eager `src="/stream/cam_01"` on `#studio-live-img` with `data-src="/stream/cam_01"` (omitting eager `/stream/` `src`) so hidden `#tab-studio` does not open an MJPEG stream on initial page load.
- [x] **dashboard/static/partials/tabs/analytics.html**: Replace eager `src="/analytics/heatmap"` on `#static-heatmap-img` with `data-src="/analytics/heatmap"` so hidden `#tab-analytics` does not fetch `/analytics/heatmap` on initial page load.
- [x] **dashboard/static/js/live_player.js**: Add `attachStudioStream(studioImg, cameraId)`, `detachStudioStream(studioImg)`, `attachHeatmapImage(heatmapImg)`, and `syncTabStreams(previousTabId, targetTabId)` on `window.LivePlayer` (`< 190L`, functions `<= 35L`) to bind/unbind `#live-stream-img`, `#studio-live-img`, and `#static-heatmap-img` on tab transitions.
- [x] **dashboard/static/js/nav_tabs_manager.js**: Update `switchTab(tabId)` and wrap `window.switchTab` via a lightweight lifecycle hook (`< 280L`, `<= 12` class methods, functions `<= 35L`) so any tab switch invokes `window.LivePlayer?.syncTabStreams?.(prevTab, tabId)` and dispatches `CustomEvent('tab-changed', { detail: { previousTab: prevTab, activeTab: tabId } })`.
- [x] **tests/test_step2_tab_scoped_streams.py**: Add isolated unit and Node VM tests (`<= 40L` per test method) verifying `studio.html` and `analytics.html` omit eager `src="/stream/..."` and `src="/analytics/..."`, `LivePlayer.syncTabStreams` attaches/detaches `#live-stream-img`, `#studio-live-img`, and `#static-heatmap-img` across tab transitions, and `NavTabsManager` emits `tab-changed`.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 1 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step2_tab_scoped_streams.py"
```

---

### Milestone 2: Tab-Scoped Studio BEV Minimap Timer & Studio Stream Gating *(Deferred)*
- [x] **dashboard/static/studio.js**: Replace the unconditional 250ms `setInterval` with `startMinimapLoop()`, `stopMinimapLoop()`, and `syncStudioTabState(isActive)` bound to `tab-changed` (`< 345L`, functions `<= 40L`) so the 250ms `renderBEVMinimap()` timer runs only when `#tab-studio` is active (`classList.contains('active')`), and guard `#studio-live-img.src` updates in `bindStudioUI()` when `#tab-studio` is inactive (updating `dataset.activeStreamSrc` instead).
- [x] **tests/test_step2_studio_minimap_gating.py**: Add Node VM unit tests (`<= 40L` per test method) verifying `studio.js` does not run `renderBEVMinimap()` on the 250ms interval while `#tab-studio` is inactive, starts/stops the timer deterministically on `tab-changed`, and updates `dataset.activeStreamSrc` without opening `/stream/` when `#tab-studio` is hidden.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 2 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step2_studio_minimap_gating.py"
```

---

### Milestone 3: Boot Fetch Deduplication & Deferred `#videos` Report/Detection Loading *(Deferred)*
- [x] **dashboard/static/js/nav_tabs_manager.js**: Add an idempotent boot GET fetch coalescer (`installBootFetchDeduplicator` / `window.fetchWithDedup` with `clearFetchDedupCache()`) that deduplicates concurrent/back-to-back GET requests to `/api/cameras` and `/api/videos` within a short coalescing window (`2000ms`), keeping `nav_tabs_manager.js` `< 280L` and functions `<= 35L`.
- [x] **dashboard/static/js/scrubber_library_bridge.js**: Gate auto-selection and heavy `/api/videos/{filename}/report` + `/detections` fetches behind `isVideosTabActive()` (`< 295L`, functions `<= 40L`), storing pending video/report state while `#tab-videos` is hidden and flushing via `flushDeferredVideoLoad()` when `#tab-videos` becomes active (`tab-changed` / `onTabEnter`).
- [x] **tests/test_step2_lazy_video_and_fetch_dedup.py**: Add Node VM unit tests (`<= 40L` per test method) verifying concurrent `fetch('/api/cameras')` and `fetch('/api/videos')` calls coalesce into 1 underlying HTTP call, `/report` and `/detections` fetches are deferred while `#tab-videos` is inactive and flushed on tab entry, and isolated test DOMs without `#tab-videos` remain 100% backward-compatible.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 3 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step2_lazy_video_and_fetch_dedup.py"
```

---

### Milestone 4: Step 2 End-to-End Verification, Modularity Audit & Master Roadmap Sign-Off *(Deferred)*
- [ ] **tests/test_step2_tab_scoped_perf_integration.py**: Add end-to-end integration tests (`<= 40L` per test method) verifying initial `#tab-live` boot opens only `#live-stream-img`, zero hidden-tab streams or `/report`/`/detections` fetches, coalesced `/api/cameras` + `/api/videos` boot fetches, and clean tab transitions across `#tab-live`, `#tab-studio`, `#tab-analytics`, and `#tab-videos`.
- [ ] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 4 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step2_*.py"
```

---

## 4. Scenario Combinations Matrix

| Real-World Scenario / Objective | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Verify Hidden-Tab Stream Disconnection & Lifecycle** | Milestone 1 Unit Tests | `test_step2_tab_scoped_streams.py` | `python -m unittest discover -s tests -p "test_step2_tab_scoped_streams.py"` |
| **Verify Studio 250ms BEV Timer Tab Gating** | Milestone 2 Unit Tests | `test_step2_studio_minimap_gating.py` | `python -m unittest discover -s tests -p "test_step2_studio_minimap_gating.py"` |
| **Verify Boot Fetch Dedup & Lazy Video Reports** | Milestone 3 Unit Tests | `test_step2_lazy_video_and_fetch_dedup.py` | `python -m unittest discover -s tests -p "test_step2_lazy_video_and_fetch_dedup.py"` |
| **Verify Full Step 2 Integration** | All Step 2 Tests | `test_step2_*.py` | `python -m unittest discover -s tests -p "test_step2_*.py"` |
| **Audit Modified Files Against Modularity Budgets** | Static Auditor | `--max-lines 350 --max-fn-lines 40` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/static/partials/tabs/studio.html dashboard/static/partials/tabs/analytics.html dashboard/static/js/nav_tabs_manager.js dashboard/static/js/live_player.js dashboard/static/studio.js dashboard/static/js/scrubber_library_bridge.js` |
| **Inspect Step 2 Child Plan Status** | Plan Engine CLI | `status step_2_tab_scoped_streams_and_lazy_loading` | `python "<config_dir>/skills/frontier-architect/scripts/plan_engine.py" status step_2_tab_scoped_streams_and_lazy_loading --root .` |
