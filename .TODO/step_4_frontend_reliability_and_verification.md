# Implementation Plan: Step 4 — Frontend Reliability, Canvas Sync & Closed-Loop Verification

> **Parent Master Plan**: `performance_and_processing_modes_master_roadma_followups` (Milestone 4)  
> **Scope**: Eliminate hardcoded `cam_01` 404 polling, guard `.scrollLeft` null-wrapper accesses, add MJPEG `onerror`/stall auto-reconnect for multi-grid tiles and live player, and execute closed-loop full-suite + CDP browser verification.

---

## Surface Baseline & Modularity Constraints

| Target File | Current Lines | Class / Method Budget | Constraint for Step 4 |
| :--- | :--- | :--- | :--- |
| `dashboard/static/partials/tabs/live.html` | 191 L | HTML partial | Remove hardcoded `cam_01` `<option>` and eager `cam_01` `src` on `#live-stream-img`. |
| `dashboard/static/js/camera_diagnostics_ui.js` | 241 L | Module functions (`bindEvents` 79L, `openDiagnosticModal` 59L) | Keep `< 350L`; keep new/modified helpers `<= 40L`. |
| `dashboard/static/js/nav_tabs_manager.js` | 276 L | `NavTabsManager`: 12 methods (Hard ceiling) | **0 new methods** on `NavTabsManager`; guard `.scrollLeft` accesses in-place. |
| `dashboard/static/app.js` | 365 L | Monolith Freeze (`>= 350L`) | **No new feature blocks**; only minimal null-guard fix if needed. |
| `dashboard/static/js/camera_grid.js` | 160 L | Module functions | Delegate tile `onerror`/stall reconnect to `MjpegReconnect`; keep `< 350L`. |
| `dashboard/static/js/mjpeg_reconnect.js` | 0 L (New) | Module functions | New focused module `<= 150L`, functions `<= 40L`. |
| `dashboard/static/index.html` | 176 L | Script loader | Load `/static/js/mjpeg_reconnect.js` before `camera_grid.js`. |

---

## Scenario Combinations Matrix

| Scenario | Input / State | Expected Behavior | Verifier |
| :--- | :--- | :--- | :--- |
| **No `cam_01` in `cameras.json`** | Initial page load before/after `GET /api/cameras` returns e.g. `cam_usb_0` | `#active-camera-select` starts with empty placeholder `""`; `camera_diagnostics_ui.js` skips polling when `camId` is empty or absent from loaded camera list (`0` 404s) | `tests/test_step4_frontend_reliability.py` + CDP |
| **Loaded Camera Diagnostics** | `#active-camera-select` has loaded camera `cam_usb_0` | `checkActiveCameraHealth()` polls `/api/cameras/cam_usb_0/diagnostics` | `tests/test_step4_frontend_reliability.py` |
| **Null `#nav-tabs-wrapper`** | Early init or headless DOM missing `#nav-tabs-wrapper` | `nav_tabs_manager.js` and `app.js` never throw `TypeError` reading `.scrollLeft` | `tests/test_step4_frontend_reliability.py` |
| **MJPEG Tile Error / Stall** | Multi-grid tile `<img>` fires `onerror` or stalls | `MjpegReconnect` schedules bounded exponential-backoff reconnect (`_r=<ts>`) and cancels timer on `detach()` | `tests/test_step4_frontend_reliability.py` |
| **Closed-Loop Verification** | Full test suite + `diagnose.py audit` + headless/live CDP | 100% unit tests pass, `audit` PASS, 0 JS exceptions, 0 404s, 1x1/2x2/3x3 grids verified | `unittest`, `diagnose.py` |

---

## Atomic Milestones

### Milestone 1: Frontend Reliability, `cam_01` 404 Removal & MJPEG Reconnect
- [x] **Files**:
  - [x] `dashboard/static/partials/tabs/live.html`: Replace hardcoded `<option value="cam_01">Main Entrance (cam_01)</option>` with `<option value="">Loading cameras...</option>` and remove hardcoded `/stream/cam_01?annotated=false` `src` on `#live-stream-img`.
  - [x] `dashboard/static/js/camera_diagnostics_ui.js`: Skip `/api/cameras/{id}/diagnostics` polling when `camId` is empty or not present in loaded camera options / `CameraManager` inventory.
  - [x] `dashboard/static/js/nav_tabs_manager.js` & `dashboard/static/app.js`: Audit and guard all `.scrollLeft` / `wrapper` reads against null elements without adding methods to `NavTabsManager` or growing `app.js`.
  - [x] `dashboard/static/js/mjpeg_reconnect.js` (new, `<= 150L`), `dashboard/static/index.html`, & `dashboard/static/js/camera_grid.js`: Add exponential-backoff `onerror` and stall watchdog auto-reconnect for `<img>` MJPEG tiles (and detach cleanup on grid teardown/switch).
  - [x] `tests/test_step4_frontend_reliability.py` (new, test methods `<= 40L`): Add FastAPI partial & Node VM tests covering `live.html` placeholder, diagnostics polling guard, null `.scrollLeft` safety, and `MjpegReconnect` backoff/detach lifecycle.
- [x] **Verification**:
  - [x] `diagnose.py audit --path dashboard/static/partials/tabs/live.html dashboard/static/js/camera_diagnostics_ui.js dashboard/static/js/nav_tabs_manager.js dashboard/static/app.js dashboard/static/js/camera_grid.js dashboard/static/js/mjpeg_reconnect.js tests/test_step4_frontend_reliability.py --max-lines 350 --max-fn-lines 40`
  - [x] `python -m unittest tests/test_step4_frontend_reliability.py tests/test_step2_live_canvas_delegation.py tests/test_responsive_navigation.py tests/test_dashboard_ui.py`

### Milestone 2: Closed-Loop Full-Suite, Modularity & Browser CDP Verification
- [ ] **Files**:
  - [ ] Fix any regressions surfaced by full-suite discovery or CDP browser inspection.
- [ ] **Verification**:
  - [ ] `python -m unittest discover tests` (with `MPLBACKEND=Agg`)
  - [ ] `diagnose.py scan --path .`
  - [ ] Headless & live browser CDP audit (`diagnose.py ui --headless --audit-layout` and `--live` if available) confirming 0 JS exceptions, 0 `404`s, and working 1x1/2x2/3x3 grid streaming.
  - [ ] Record milestone in `CHANGELOG.md` via `diagnose.py changelog add` and run `plan_engine.py digest`.
