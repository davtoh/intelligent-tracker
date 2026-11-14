# Step 2 Implementation Plan: Unified 100% Client-Side `<canvas>` Overlay Engine (`#live` & `#videos` Parity)

> **Parent Master Plan**: `.TODO/live_video_studio_master_roadmap.md` (Step 2)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md`
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–4 are *Deferred to Subsequent Turns*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map` & `diagnose.py audit`)

Measured against workspace baseline before edits:
- `dashboard/routers/streaming.py`: 137 lines (OK `< 350L`), **DEFECT FLAGGED**: `get_live_stream()` at line 29 is **44 lines** (`> 40L` function budget ceiling) and lacks an `annotated: bool = True` query parameter to serve clean un-burned frames for `#live`'s primary viewport.
- `dashboard/services/stream_worker.py`: 331 lines (OK `< 350L`). `_process_single_frame()` stores `_latest_raw_frame` and encodes OpenCV-burned `_latest_jpeg` via `FrameOverlayRenderer.render()`, but does not cache a pre-compressed clean `_latest_raw_jpeg` buffer for `annotated=False` streaming.
- `dashboard/services/stream_media.py`: 89 lines (OK `< 350L`). `get_latest_frame_jpeg()` returns `self._latest_jpeg` unconditionally without an `annotated: bool = True` switch.
- `dashboard/static/js/interactive_canvas.js`: 205 lines (OK `< 350L`, 0 defects). Currently draws only a cyan hover box (`drawInteractiveOverlay`) without `window.devicePixelRatio` scaling, relying on server-side pixel burn-in for bounding boxes, track IDs, dwell timers, velocity vectors, zones, and tripwires.
- `dashboard/static/js/scrubber_overlay_renderer.js`: 146 lines (OK `< 350L`, 0 defects). Renders basic track boxes in `#videos`, lacking dwell timers, kinematic velocity vectors, spatial zones, tripwires, and heatmap compositing.
- `dashboard/static/js/scrubber_overlay.js`: 372 lines (`WARN >= 350L`). Contains duplicate fallback palette constants and a 49-line `render()` loop that should delegate to `UnifiedCanvasOverlay` so `scrubber_overlay.js` drops below `340L`.
- `dashboard/static/js/overlay_layers.js`: 362 lines (`WARN >= 350L`). Contains duplicate palette definitions (`getPalettes()`) that should delegate to `UnifiedCanvasOverlay.PALETTES` so `overlay_layers.js` drops below `345L`.

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts (Zero-Regression Invariants)
- `GET /stream/{camera_id}` defaults to `annotated: bool = True` so existing `<img>` tags, multi-grid `2x2`/`3x3` tiles (`camera_grid.js`), external snapshot consumers, and existing stream unit tests (`test_09_stream_endpoint`) remain 100% backward-compatible.
- Passing `GET /stream/{camera_id}?annotated=false` streams clean un-annotated MJPEG frames (`_latest_raw_jpeg`) so `#live`'s primary `<img id="live-stream-img">` never suffers from burned-in bounding box pixels during freeze-frame ROI crops (`EntityTaggerService.tag_entity`).
- `StreamManager.get_latest_frame_jpeg(camera_id: str | None = None, annotated: bool = True) -> bytes` preserves its default signature while supporting `annotated=False`.
- `window.ScrubberOverlayRenderer` and `window.ScrubberOverlay` preserve all existing global methods (`PALETTES`, `findClosestDetections`, `computeVideoRenderBox`, `resolveScaleFactors`, `drawTrackBox`, `init`, `loadDetections`, `setDetections`, `appendDetections`, `setLayer`, `removeLayer`, `clearLayers`, `hasLayer`, `getActiveLayers`, `getActiveLayerIds`, `fetchProgressiveStream`, `render`, `clear`, `startLoop`, `stopLoop`).
- Critical DOM IDs remain intact: `#live-stream-img`, `#interactive-canvas`, `#video-wrapper`, `#track-tooltip`, `#scrubber-video-player`, `#scrubber-overlay-canvas`, `#scrubber-overlay-layers`, and `#overlay-toggle-*`.

### Modularity Guardrails
- `dashboard/static/js/unified_canvas_overlay.js` MUST remain `< 280` lines with every function `<= 35` lines (hard audit ceiling `<= 40` lines).
- `dashboard/routers/streaming.py` MUST remain `< 160` lines with `get_live_stream` `<= 15` lines and `_stream_frame_generator` `<= 25` lines.
- `dashboard/services/stream_worker.py` MUST remain `< 350` lines with all modified functions `<= 35` lines.
- `dashboard/static/js/scrubber_overlay.js` (currently 372L) and `dashboard/static/js/overlay_layers.js` (currently 362L) MUST both be reduced to `< 350` lines by delegating shared palettes and canvas rendering to `UnifiedCanvasOverlay`.

---

## 3. Phased Implementation Milestones

### Milestone 1: Clean Un-Burned MJPEG Streaming (`?annotated=false|true`) & `streaming.py` Function Budget Fix *(Active Execution Target)*
- [x] **dashboard/services/stream_worker.py**: Add `_encode_raw_frame(self, frame: Any) -> None` (`<= 15L`) and invoke it in `_process_single_frame()` so `self.manager._latest_raw_jpeg` caches clean un-annotated JPEG bytes alongside `_latest_jpeg`, keeping `stream_worker.py` `< 345` lines.
- [x] **dashboard/services/stream_media.py**: Update `get_latest_frame_jpeg(self, camera_id: Optional[str] = None, annotated: bool = True) -> bytes` (`<= 20L`) to return `self._latest_raw_jpeg` (falling back to `self._latest_jpeg` or placeholder if not yet populated) when `annotated=False`, and initialize `self._latest_raw_jpeg: Optional[bytes] = None` in `dashboard/stream_manager.py`.
- [x] **dashboard/routers/streaming.py**: Extract top-level `_stream_frame_generator(mgr: Any, sub_id: str, request: Request, annotated: bool = True)` (`<= 25L`) and reduce `get_live_stream(camera_id: str, request: Request, annotated: bool = True)` from 44 lines to `<= 15` lines, resolving the `diagnose.py audit` function budget overrun.
- [x] **tests/test_step2_clean_streaming.py**: Add isolated unit tests covering `annotated=True` vs `annotated=False` branches in `get_latest_frame_jpeg`, `_encode_raw_frame` pixel cleanliness vs annotated burn-in, `get_live_stream` query flag forwarding, and `diagnose.py audit` compliance on `streaming.py`, `stream_worker.py`, and `stream_media.py`.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 1 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step2_clean_streaming.py"
```

---

### Milestone 2: Shared `UnifiedCanvasOverlay` Engine (`dashboard/static/js/unified_canvas_overlay.js`) *(Deferred to Next Turn)*
- [x] **dashboard/static/js/unified_canvas_overlay.js**: Create the shared 100% client-side HTML5 `<canvas>` overlay engine (`< 280L`, all functions `<= 35L`) exposing `window.UnifiedCanvasOverlay` with `PALETTES`, `DEFAULT_VISIBILITY`, `computeContainBox()`, `syncCanvasDpr()`, `resolveScaleFactors()`, `drawTrackBox()`, `drawVelocityVector()`, `drawZones()`, `drawTripwires()`, `drawHeatmapLayer()`, and `renderScene()` at native `window.devicePixelRatio`.
- [x] **dashboard/static/index.html**: Load `<script src="/static/js/unified_canvas_overlay.js"></script>` immediately before `interactive_canvas.js` so both `#live` and `#videos` modules consume `window.UnifiedCanvasOverlay`.
- [x] **tests/test_step2_unified_canvas_engine.py**: Add unit/VM tests verifying `computeContainBox` (pillarbox and letterbox branches), `syncCanvasDpr` HiDPI transform scaling, and `renderScene` canvas drawing primitives (`bboxes`, `track_ids`, `dwell_timers`, `velocity`, `zones`, `tripwires`, `heatmap`), plus `diagnose.py audit` `< 280L` / `<= 40L` function compliance.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 2 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step2_unified_canvas_engine.py"
```

---

### Milestone 3: `#live` Client-Side Vector Overlay Delegation & Un-Burned Primary Stream Wiring *(Deferred to Next Turn)*
- [x] **dashboard/static/partials/tabs/live.html**: Update primary `<img id="live-stream-img">` default `src` to `/stream/cam_01?annotated=false`.
- [x] **dashboard/static/js/camera_grid.js**: Update `focusCamera()` primary stream URL assignment to `/stream/${encodeURIComponent(cam.id)}?annotated=false` while keeping `buildGridTileHtml()` multi-grid tiles on `/stream/${encodeURIComponent(cam.id)}?annotated=true`.
- [x] **dashboard/static/js/live_player.js**: Preserve `annotated=false` query parameter when reconnecting/resuming `#live-stream-img` in `resumeLiveStream()` and `camera_ai_config.js` initial focus sync.
- [x] **dashboard/static/js/interactive_canvas.js**: Refactor `syncCanvasSize()` and `drawInteractiveOverlay()` (`<= 30L` each) to use `UnifiedCanvasOverlay.computeContainBox()`, `UnifiedCanvasOverlay.syncCanvasDpr()`, and `UnifiedCanvasOverlay.renderScene()` to render `BBoxes`, `Track IDs`, `Dwell Timers`, `Velocity Vectors`, `Zones`, `Tripwires`, and `Heatmap` client-side according to `#overlay-toggle-*` states while preserving hover tooltips and click-to-tag.
- [x] **tests/test_step2_live_canvas_delegation.py**: Add unit tests verifying `#live` primary stream URL `?annotated=false` vs multi-grid `?annotated=true`, `interactive_canvas.js` HiDPI delegation to `UnifiedCanvasOverlay.renderScene`, and `diagnose.py audit` compliance.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 3 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step2_live_canvas_delegation.py"
```

---

### Milestone 4: `#videos` Scrubber Overlay Parity, `scrubber_overlay.js` / `overlay_layers.js` `< 350L` Reduction & Step 2 Sign-Off *(Deferred to Next Turn)*
- [ ] **dashboard/static/js/scrubber_overlay_renderer.js**: Delegate `PALETTES`, `computeVideoRenderBox`, `resolveScaleFactors`, and `drawTrackBox` to `window.UnifiedCanvasOverlay` while adding `renderLayerRecord(ctx, record, transform, palette, labelPrefix, visibility)` (`<= 30L`) that renders tracks, dwell timers, velocity vectors, zones, and tripwires for video detection frames.
- [ ] **dashboard/static/js/scrubber_overlay.js**: Delegate duplicate palette constants, DPR canvas setup, and the multi-layer `render()` loop to `UnifiedCanvasOverlay` and `ScrubberOverlayRenderer.renderLayerRecord()`, reducing `scrubber_overlay.js` from 372 lines (`WARN`) to `< 335` lines (`OK < 350L`) and exposing `setFeatureVisibility(key, enabled)` / `getFeatureVisibility()` for layer feature parity.
- [ ] **dashboard/static/js/overlay_layers.js**: Remove duplicate `getPalettes()` definition by referencing `UnifiedCanvasOverlay.PALETTES` and streamline layer descriptor helpers, reducing `overlay_layers.js` from 362 lines (`WARN`) to `< 340` lines (`OK < 350L`).
- [ ] **dashboard/static/js/overlay_layer_toolbar.js**: Add feature pill toggles (`BBoxes`, `IDs`, `Dwell`, `Velocity`, `Zones`, `Tripwires`) to `#scrubber-overlay-layers` so `#videos` operators can toggle vector overlay features identically to `#live`.
- [ ] **tests/test_step2_video_scrubber_parity.py**: Add unit tests verifying `#videos` `ScrubberOverlay` delegation to `UnifiedCanvasOverlay`, feature toggle filtering (`bboxes`, `track_ids`, `dwell_timers`, `velocity`, `zones`, `tripwires`), `< 350L` modularity budget compliance on both `scrubber_overlay.js` and `overlay_layers.js`, and full Step 2 regression pass (`test_step2_*.py`).
- [ ] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 4 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step2_*.py"
```

---

## 4. Scenario Combinations Matrix

| Real-World Scenario / Objective | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Verify Milestone 1 (Clean `?annotated=false` Stream & `streaming.py` Budget)** | Headless unit suite | `test_step2_clean_streaming.py` | `python -m unittest discover -s tests -p "test_step2_clean_streaming.py"` |
| **Verify Milestone 2 (`UnifiedCanvasOverlay` Engine & HiDPI Transform)** | Headless unit suite | `test_step2_unified_canvas_engine.py` | `python -m unittest discover -s tests -p "test_step2_unified_canvas_engine.py"` |
| **Verify Milestone 3 (`#live` Client-Side Vector Canvas & URL Wiring)** | Headless unit suite | `test_step2_live_canvas_delegation.py` | `python -m unittest discover -s tests -p "test_step2_live_canvas_delegation.py"` |
| **Verify Milestone 4 (`#videos` Scrubber Parity & `< 350L` De-Warning)** | Headless unit suite | `test_step2_*.py` | `python -m unittest discover -s tests -p "test_step2_*.py"` |
| **Static Modularity & Function Budget Audit on All Step 2 Files** | AST Auditor | `--max-lines 350 --max-fn-lines 40` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/routers/streaming.py dashboard/services/stream_worker.py dashboard/services/stream_media.py dashboard/static/js/unified_canvas_overlay.js dashboard/static/js/interactive_canvas.js dashboard/static/js/scrubber_overlay_renderer.js dashboard/static/js/scrubber_overlay.js dashboard/static/js/overlay_layers.js dashboard/static/js/overlay_layer_toolbar.js --max-lines 350 --max-fn-lines 40` |
| **Live Browser Layout & Zero-Overflow Check** | CDP UI Inspector | `--audit-layout` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" ui --url $APP_URL --headless --audit-layout --selectors "#video-wrapper,#interactive-canvas,.scrubber-viewport,#scrubber-overlay-canvas,#scrubber-overlay-layers"` |
