# Implementation Plan: High-FPS Async Pipeline, Multi-Grid Streaming & Driver Resilience

## Summary of Diagnosed Root Causes
1. **~10 FPS Bottleneck**: `FrameProcessor.step()` runs YOLOv8n + Re-ID synchronously on every frame (~70–90ms CPU), blocking capture/display FPS, compounded by `StreamWorker`'s `0.01s` sleep, redundant dual JPEG encoding, and `streaming.py`'s `0.04s` MJPEG sleep.
2. **2x2 & 3x3 Grids Stuck on `"Camera Initializing..."`**: `ProcessingModeService.should_hibernate_camera()` returns `True` for any `camera_id != focused` in `focus_only` mode even when `subscriber_count > 0`, pausing `StreamWorker` capture before the initial placeholder JPEG is ever replaced.
3. **404 on `/api/cameras/cam_01/diagnostics`**: `live.html` hardcodes `<option value="cam_01">` while `configs/cameras.json` has no `cam_01`, causing `camera_diagnostics_ui.js` to poll a nonexistent camera every 3s.
4. **Headless JS Exception**: `nav_tabs_manager.js` / `app.js` accesses `.scrollLeft` on a null `wrapper` element during early initialization or missing DOM state.
5. **DirectShow Driver Timeouts & Scan Locks**: `discover_usb_cameras()` probes indices `0..5` even when `CameraPool` already holds those DirectShow handles, and `CaptureReadGuard` uses a flat `2.0s` timeout even during slow initial hardware warmup.

---

## Target Architecture & Locked Decisions
- **View-Aware Focus Mode**: In `focus_only`, unfocused cameras with `subscriber_count > 0` stream capture-only (no heavy AI) instead of hibernating; hibernation occurs only when `subscriber_count <= 0 && !is_recording` (or in `paused` mode).
- **Best-of-Both-Worlds Pipeline (Enterprise Hub Parity)**:
  - Capture & MJPEG delivery run at native FPS (30–60+ FPS) driven by frame-ready events (no fixed `0.01s`/`0.04s` blind sleeps).
  - YOLOv8/Re-ID runs asynchronously on the *latest* frame in a dedicated non-blocking worker (`AsyncInferenceWorker`), updating cached tracks/telemetry without stalling video delivery.
  - On-demand single JPEG encoding (encode `raw` or `annotated` only when subscribers request that variant).
  - Full compatibility with `GET /stream/{camera_id}` + `GET /api/cameras/{camera_id}/telemetry` Canvas overlays per `documentation/enterprise_hub_integration.rst`.
- **Pool-Aware Camera Scan & Driver Recovery**: Skip already-active `CameraPool` indices in `discover_usb_cameras()`, add a `5.0s` warmup grace timeout for first DirectShow frame reads, and auto-reopen severed drivers with exponential backoff.
- **Frontend Reliability**: Eliminate `cam_01` 404 polling, guard `scrollLeft` accesses, and add MJPEG `<img>` `onerror`/stall auto-reconnect.

---

## Atomic Milestones

### Milestone 1: View-Aware `focus_only` Hibernation & 2x2/3x3 Grid Streaming
- [x] **Files**:
  - [x] `dashboard/services/processing_mode_service.py`: Update `should_hibernate_camera()` so `focus_only` keeps cameras awake whenever `subscriber_count > 0` (or `is_recording` or `camera_id == focused and active_tab == "live"`), hibernating only when `subscriber_count <= 0` and not recording/focused-on-live. Keep `should_run_vision_step()` returning `False` for unfocused cameras in `focus_only`.
  - [x] `dashboard/static/js/camera_grid.js`: Ensure grid layout switches (`1x1`, `2x2`, `3x3`) cleanly detach/re-attach `#live-stream-img` via `window.LivePlayer`, attach tile MJPEG streams without `loading="lazy"`, and preserve active tile `<img>` streams during `refreshCameras()` metadata updates.
  - [x] `tests/test_processing_mode.py` (new) & `tests/test_step3_processing_mode_api.py`, `tests/test_step3_worker_hibernation_and_ai_gating.py`, `tests/test_step4_e2e_performance_and_modes.py`: Update/add unit & Node VM tests covering `focus_only` with `subscriber_count > 0` (awake, capture-only) vs `subscriber_count == 0` (hibernating) and `CameraGrid` 1x1/2x2/3x3 stream lifecycle.
- [x] **Verification**: `.venv\Scripts\python.exe -m unittest tests/test_processing_mode.py tests/test_step3_processing_mode_api.py tests/test_step3_worker_hibernation_and_ai_gating.py tests/test_step4_e2e_performance_and_modes.py`

### Milestone 2: Decoupled Async AI + Event-Driven MJPEG + On-Demand Single JPEG
- [x] **Files**:
  - [x] `dashboard/services/async_inference_worker.py` (new module, `<= 150` lines): Non-blocking latest-frame inference slot running `FrameProcessor.step()` on a background thread and caching the latest `FrameStepResult` / tracks.
  - [x] `dashboard/services/stream_worker.py`: Delegate AI to `AsyncInferenceWorker` when `should_run_vision` is `True`; draw latest cached tracks when `annotated` subscribers exist; encode only the subscribed JPEG variant (`raw` vs `annotated`); signal frame-ready event instead of `0.01s` blind sleep.
  - [x] `dashboard/stream_manager.py` & `dashboard/routers/streaming.py`: Track `raw` vs `annotated` subscriber counts and replace `asyncio.wait_for(..., timeout=0.04)` with event-driven frame wakeups.
  - [x] `tests/test_async_inference_worker.py` (new): Verify non-blocking latest-frame dropping, cached overlay reuse, and selective JPEG encoding.
- [x] **Verification**: `.\.venv\Scripts\python.exe -m unittest tests/test_async_inference_worker.py tests/test_stream_manager.py`

### Milestone 3: Pool-Aware Camera Discovery, DirectShow Warmup Grace & Auto-Reopen
- [x] **Files**:
  - [x] `intelligent_tracker/camera_device.py` & `dashboard/routers/cameras.py`: Pass active `CameraPool` USB indices to `discover_usb_cameras(active_indices=...)` so live DirectShow handles are reported without re-opening/contending.
  - [x] `intelligent_tracker/video/capture_guard.py` & `intelligent_tracker/video/capture_worker.py`: Apply a `5.0s` warmup timeout on the first read after `open_camera()` (falling back to `2.0s` steady-state), and support exponential-backoff auto-reopen when a driver is severed.
  - [x] `tests/test_camera_discovery_and_guard.py` (new): Test active-index skipping, warmup grace vs steady-state timeout, and backoff reconnect.
- [x] **Verification**: `.\.venv\Scripts\python.exe -m unittest tests/test_camera_discovery_and_guard.py`

### Milestone 4: Frontend Reliability, Canvas Sync & Closed-Loop Verification
- **Files**:
  - `dashboard/static/partials/tabs/live.html`: Replace hardcoded `cam_01` option with an empty/loading placeholder.
  - `dashboard/static/js/camera_diagnostics_ui.js`: Skip `/api/cameras/{id}/diagnostics` polling when `camId` is empty or not in the loaded camera list.
  - `dashboard/static/js/nav_tabs_manager.js` & `dashboard/static/app.js`: Add null-guards before reading `.scrollLeft`.
  - `dashboard/static/js/camera_grid.js` (or `dashboard/static/js/mjpeg_reconnect.js`): Add `onerror` / stall watchdog auto-reconnect on `<img>` MJPEG tiles.
- **Verification**:
  - Full test suite: `.\.venv\Scripts\python.exe -m unittest discover tests`
  - Static & modularity audit: `diagnose.py audit`
  - Live + headless browser CDP audit (`run_diagnose.py ui --headless --audit-layout` and `--live`) confirming 0 JS exceptions, 0 `404`s, working 2x2/3x3 grids, and improved FPS.
