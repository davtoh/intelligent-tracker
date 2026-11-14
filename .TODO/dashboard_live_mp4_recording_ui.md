# Implementation Plan: Dashboard Live MP4 Recording UI

> **Scope**: Per-camera Live MP4 Recording controls, optional parameters, live frame/byte/elapsed telemetry sync, multi-camera grid tile actions, mismatch guards, and Video Studio handoff.  
> **Architecture Constraints**: `AGENTS.md` §5–§7 (Split-Before-You-Grow, Monolith Freeze on `dashboard/static/app.js` and `dashboard/static/styles.css`, zero `!important`, WCAG AA `>= 32px` touch targets, zero horizontal overflow).

---

## 1. Pre-Plan Diagnostic Baseline & Surface Contracts

- **`diagnose.py arch-map --path .`**: 291 files, 53,179 lines, 105 API routes (`dashboard/routers/camera_recording.py` exposes 3 routes).
- **Monolith Freeze Targets (DO NOT MODIFY)**: `dashboard/static/app.js` (355L), `dashboard/static/camera_manager.js` (366L), `dashboard/static/js/video_library.js` (471L), `dashboard/static/js/video_jobs.js` (493L), `dashboard/static/styles.css`.
- **Modularity Safe Targets**: `dashboard/dependencies.py` (343L -> 345L), `dashboard/app.py` (293L), `dashboard/services/camera_pool_queries.py` (151L), `dashboard/static/index.html` (176L), `dashboard/static/partials/tabs/live.html` (189L), `dashboard/static/js/telemetry.js` (182L), `dashboard/static/js/camera_grid.js` (107L).
- **Backend Endpoints (`dashboard/routers/camera_recording.py`, `dashboard/schemas.py`)**:
  - `POST /api/cameras/{camera_id}/record/start` -> accepts optional `CameraRecordStartRequest` (`filename`, `fps`, `annotated`, `max_frames`, `max_duration_s`), returns `CameraRecordStatusResponse` and saves MP4 clips into `data/videos/`.
  - `POST /api/cameras/{camera_id}/record/stop` -> returns finalized `CameraRecordStatusResponse`.
  - `GET /api/cameras/{camera_id}/record/status` -> returns `CameraRecordStatusResponse` (`camera_id`, `is_recording`, `status`, `recording_id`, `filename`, `output_path`, `codec`, `fps`, `width`, `height`, `frames_written`, `elapsed_s`, `size_bytes`, `annotated`, `started_at`, `stopped_at`).
- **Preserved Critical IDs (`tests/test_refactor_contract.py`)**: All baseline HTML IDs preserved; CSS `!important` count strictly `0`.

---

## 2. Milestones

### Milestone 1: Jinja2 Recording Partial, Template Loader & Camera Pool Status Wiring
- [x] **dashboard/dependencies.py & dashboard/app.py**: Define `TEMPLATES_DIR` (`dashboard/templates`) in `dashboard/dependencies.py` and configure `jinja2.FileSystemLoader([STATIC_DIR, TEMPLATES_DIR])` in `dashboard/app.py` so partials under `dashboard/templates/` render alongside `dashboard/static/`.
- [x] **dashboard/services/camera_pool_queries.py**: Include `"recording"` in `build_camera_status_row` from `telemetry.get("recording")` (with idle fallback) so `GET /api/cameras` reports live per-camera recording state.
- [x] **dashboard/templates/partials/camera_recording_bar.html**: Create Jinja2 partial containing `#camera-recording-bar` with status pill (`#rec-status-pill`, `#rec-status-text`), camera badge (`#rec-camera-badge`), live counters (`#rec-elapsed-val`, `#rec-frames-val`, `#rec-bytes-val`, `#rec-filename-val`), Start/Stop/Options/Studio action buttons (`#btn-record-start`, `#btn-record-stop`, `#btn-record-options-toggle`, `#btn-record-open-studio`), and collapsible `#rec-options-panel` (`#rec-filename-input`, `#rec-fps-input`, `#rec-max-duration-input`, `#rec-max-frames-input`, `#rec-annotated-toggle`).
- [x] **dashboard/static/partials/tabs/live.html & dashboard/static/index.html**: Include `partials/camera_recording_bar.html` inside the Live Monitor video card and link `/static/css/camera_recording.css` + `/static/js/camera_recording.js`.

**Definition of Done (DoD)**:
- [x] `GET /` renders `#camera-recording-bar` and all recording inputs/buttons without disturbing any baseline DOM IDs in `tests/test_refactor_contract.py`.

---

### Milestone 2: Scoped Responsive CSS & Live Recording Frontend Module (`camera_recording.js`)
- [x] **dashboard/static/css/camera_recording.css**: Style `#camera-recording-bar`, `.rec-status-pill`, `.rec-metrics-group`, `.rec-options-panel`, and `.btn-tile-record` with `min-width: 0`, ellipsis truncation on `.rec-filename-chip`, WCAG AA `>= 32px` touch targets, `overflow-x: clip`, and zero `!important` rules.
- [x] **dashboard/static/js/camera_recording.js**: Implement `window.CameraRecording` (< 300 lines, every function <= 35 lines) handling `startRecording`, `stopRecording`, `syncStatus` (`GET /api/cameras/{id}/record/status`), optional request payload serialization, `1500ms` polling while active, tab-switch and page-reload synchronization, per-camera mismatch guards (`status.camera_id !== getActiveCameraId()`), multi-grid tile badges/toggles, and Video Studio handoff (`VideoScrubber.loadVideosList()` + `tab-videos` + `video-select-request`).
- [x] **dashboard/static/js/telemetry.js & dashboard/static/js/camera_grid.js**: Forward WebSocket `data.recording` telemetry updates to `CameraRecording.onTelemetryUpdate`, hydrate recording states from `CameraGrid.renderGrid`, render per-tile `.btn-tile-record` buttons with `e.stopPropagation()`, and invoke `CameraRecording.onCameraFocused` on camera switch.

**Definition of Done (DoD)**:
- [x] Recording state syncs across camera switches, tab switches, and page reloads without leaking updates from background cameras into the focused camera bar.

---

### Milestone 3: Unit Tests, Node `vm` Mock-DOM Verification, Live Layout Audit & Changelog
- [x] **tests/test_camera_recording_ui.py**: Add FastAPI `TestClient` tests for rendered partial/pool status and Node `vm` mock-DOM tests for start/stop/options serialization, tab-switch & reload sync, Video Studio handoff, and `camera_id` mismatch protection.
- [x] **Static Audit & Test Suite**: Pass `diagnose.py audit --max-lines 350 --max-fn-lines 40` across all modified/new files and pass `python -m unittest discover tests` with `MPLBACKEND=Agg`.
- [x] **Live Headless Browser Audit**: Run `diagnose.py ui --url "$APP_URL" --headless --audit-layout` against a temporary `scripts/run_dashboard.py` server using `STREAM_SOURCE=synthetic` and verify zero overflow/JS errors, then stop active recordings and terminate the server daemon.
- [x] **CHANGELOG.md**: Record milestone completion via `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add`.

**Definition of Done (DoD)**:
- [x] `diagnose.py audit` exits 0, full `python -m unittest discover tests` passes 100%, `diagnose.py ui` reports zero layout/overflow/console violations, and no background server process or active recording remains running.

---

## 3. Scenario Combinations Matrix

| Scenario | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Static Modularity & Line Budget Audit** | AST + line-count audit | `--max-lines 350 --max-fn-lines 40` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/app.py dashboard/dependencies.py dashboard/services/camera_pool_queries.py dashboard/static/js/camera_recording.js dashboard/static/css/camera_recording.css dashboard/static/js/telemetry.js dashboard/static/js/camera_grid.js tests/test_camera_recording_ui.py --max-lines 350 --max-fn-lines 40` |
| **Targeted Recording UI & Node VM Tests** | `TestClient` + Node `vm` | `tests/test_camera_recording_ui.py` | `python -m unittest tests.test_camera_recording_ui` |
| **Full Headless Regression Suite** | All unit + contract + UI suites | `MPLBACKEND=Agg` | `python -m unittest discover tests` |
| **Live Headless Layout & Touch Target Check** | Synthetic feed (`detector=mock`) | `--headless --audit-layout` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" ui --url "$APP_URL" --headless --audit-layout --selectors "#camera-recording-bar,#btn-record-start,#btn-record-stop,#btn-record-options-toggle,#rec-status-pill"` |
