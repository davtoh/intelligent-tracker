# Multi-View WebSocket Streaming & Grid Socket-Leak Remediation Plan

## 1. Empirical Symptom-to-Root-Cause Matrix

| # | Observed Symptom | Failing Evidence | Root Cause Analysis | Target File & Line | Verification Check |
|---|---|---|---|---|---|
| 1 | `1x1 -> 2x2 -> 1x1` leaves `1x1` black & starves Video Studio | `repro_grid.js` (`task-46`): `after_2x2` opens `gridCount: 6, gridLoaded: 6`; `after_1x1` has `liveImg.complete: false, w: 0, h: 0` and `fetch('/api/system/processing-mode')` times out (`FETCH_TIMEOUT_3S`) | `CameraGrid.renderGrid()` removes grid `<img>` nodes via `multiGridContainer.innerHTML = ''` without calling `LivePlayer.detachGridStreams()` to reset `img.src = STANDBY_POSTER_SVG`. Blink/Chromium keeps HTTP/1.1 `multipart/x-mixed-replace` sockets draining, exhausting the 6-socket per-origin pool. | `dashboard/static/js/camera_grid.js#L108-L115` | `run_diagnose.py ui --headless --eval-file ...` |
| 2 | `2x2` grid opens 6 MJPEG connections simultaneously | `configs/cameras.json` has 6 enabled cameras; `renderGrid()` maps all `activeCameras` regardless of `2x2` vs `3x3` | `buildGridTileHtml` renders all `activeCameras` (6/6 HTTP/1.1 connections), leaving 0 sockets for `fetch()` or `/videos/*.mp4`. | `dashboard/static/js/camera_grid.js#L102-L126` | `unittest` + headless CDP probe |
| 3 | `VideoSource '2': Stream closed and reconnect exhausted` not in `.diagnostics/traces/` | Terminal stderr shows `cv::VideoCapture::open` + `VideoSource '2'` error; `.diagnostics/trace_catalog.json` has no entry | `DiagnosticTraceMiddleware` only captures unhandled Python `Exception`s; `VideoSource` / `StreamWorker` log errors via `logging` rather than `capture_runtime_exception()`. | `dashboard/services/diagnostic_bridge.py#L42-L89` | `unittest` for `DiagnosticLogHandler` |

## 2. 3-Tier Architectural Alternatives

1. **Tier 1 — Pragmatic Baseline**: Call `LivePlayer.detachGridStreams()` when returning to `1x1` and cap/paginate `2x2` to 4 tiles. Fast, zero protocol change, but `3x3` with `>= 5` cameras still hits Chrome's 6-socket HTTP/1.1 limit.
2. **Tier 2 — Frontier SOTA (Recommended Default)**: **Single-Connection WebSocket Binary Multiplexer (`/ws/multiview`) + Tactical Grid Socket Cleanup**. All multi-view grid tiles share **1 WebSocket** carrying binary frames (`[2B cam_id_len][cam_id UTF-8][JPEG bytes]`) decoded via `createImageBitmap()` onto `<canvas>` tiles (with thumbnail FPS throttling). Leaves 100% of the HTTP/1.1 socket pool free for `fetch()`, `1x1`, and Video Studio MP4s.
3. **Tier 3 — Novel Moonshot**: **WebRTC SFU (`aiortc`) / fMP4 MSE** with hardware H.264 encode. Highest complexity and native dependency footprint.

## 3. Milestones

### Milestone 1: Tactical `1x1 <-> 2x2` Socket-Leak Fix, `2x2` Tile Cap & Error Trace Bridge *(Active Execution Target)*
- [ ] **dashboard/static/js/camera_grid.js**: Call `window.LivePlayer?.detachGridStreams?.()` before clearing `multiGridContainer.innerHTML = ''` when switching to `1x1` (and before rebuilding tiles); slice `2x2` grid to max 4 cameras (`cameras.slice(0, 4)`) so `2x2` never exceeds 4 MJPEG sockets.
- [ ] **dashboard/services/diagnostic_bridge.py**: Add a lightweight `DiagnosticLogHandler(logging.Handler)` (rate-limited per `(logger, msg_prefix)`) that bridges `ERROR` logs from `intelligent_tracker` / `VideoSource` into `.diagnostics/traces/` via `capture_runtime_exception()`.
- [ ] **tests/test_multiview_grid_cleanup.py**: Add unit tests (Node VM `<= 40L` per method) verifying `detachGridStreams()` is invoked on `2x2 -> 1x1`, `2x2` caps at 4 tiles, and `DiagnosticLogHandler` records `ERROR` logs without raising.

### Milestone 2: Backend `/ws/multiview` Binary Multiplexer Endpoint *(Deferred to Next Turn)*
- [ ] **dashboard/routers/streaming.py**: Add `@router.websocket("/ws/multiview")` accepting camera subscription lists (`{action: "subscribe", cameras: [...]}`), fanning out throttled JPEG binary frames (`[2B len][cam_id][jpeg]`) over a single WebSocket with clean `remove_subscriber()` teardown.
- [ ] **tests/test_ws_multiview_backend.py**: Test `/ws/multiview` binary frame framing, subscription updates, and zero-leak subscriber cleanup.

### Milestone 3: Frontend `MultiviewWsClient` Canvas Tile Renderer & E2E Verification *(Deferred to Next Turn)*
- [ ] **dashboard/static/js/multiview_ws_client.js**: Implement `MultiviewWsClient` decoding binary `/ws/multiview` frames via `createImageBitmap` onto per-tile `<canvas>` elements with automatic fallback to `STANDBY_POSTER_SVG`.
- [ ] **dashboard/static/js/camera_grid.js**: Wire `2x2` and `3x3` grids to `MultiviewWsClient` (0 HTTP/1.1 MJPEG sockets used in multi-view) and verify `1x1 <-> 2x2 <-> 3x3 <-> Video Studio` via `diagnose.py ui --headless`.

## 4. Scenario Combinations Matrix

| Scenario | Command | Expected Result |
|---|---|---|
| Unit & JS VM Tests | `python -m unittest tests.test_multiview_grid_cleanup` | 100% pass, `<= 40L` per method |
| Modularity Audit | `python skills/system-diagnostics/scripts/diagnose.py audit --path dashboard/static/js/camera_grid.js dashboard/services/diagnostic_bridge.py` | PASS (`< 350L`) |
| Live/Headless Grid Repro | `python skills/app-debugger/scripts/run_diagnose.py ui --headless --eval-file <scratch>/repro_grid.js` | `1x1 -> 2x2 -> 1x1` restores `640x360` & `fetch` `< 2s` |
