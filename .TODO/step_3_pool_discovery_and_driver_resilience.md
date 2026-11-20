# Implementation Plan: Step 3 — Pool-Aware Camera Discovery, DirectShow Warmup Grace & Auto-Reopen

> **Parent Master Plan**: `performance_and_processing_modes_master_roadma_followups` (Milestone 3)  
> **Scope**: Eliminate DirectShow COM graph contention during `/api/cameras/discover` and harden `CaptureReadGuard` / `CaptureWorkerMixin` against slow hardware warmups and severed drivers.

---

## Surface Baseline & Modularity Constraints

| Target File | Current Lines | Class / Method Budget | Constraint for Step 3 |
| :--- | :--- | :--- | :--- |
| `intelligent_tracker/camera_device.py` | 335 L | `CameraDeviceHandler`: 15 methods (Monolith Freeze) | Keep `< 350L`; **0 new methods** on `CameraDeviceHandler`. Parameterize `discover_usb_cameras`. |
| `intelligent_tracker/discovery/usb.py` | 47 L | Module functions | Pass `active_indices` through `find_physical_cameras`. |
| `intelligent_tracker/discovery/scanner.py` | 83 L | Module functions | Pass `active_indices` through `discover_all_cameras`. |
| `dashboard/services/camera_pool_queries.py` | 161 L | `CameraPoolQueryMixin`: 8 methods | Add `get_active_usb_indices()` ($\le 20L$). |
| `dashboard/routers/cameras.py` | 326 L | Router endpoints | Inject `CameraPool` into `GET /api/cameras/discover`; keep `< 350L`. |
| `intelligent_tracker/video/capture_guard.py` | 342 L | `CaptureReadGuard`: 16 methods (Monolith Freeze) | Keep `< 350L`; **0 new methods** on `CaptureReadGuard`. |
| `intelligent_tracker/video/capture_worker.py` | 347 L | `CaptureWorkerMixin`: 11 methods | Keep `< 350L` & `<= 12` methods; extract pure backoff/warmup helper if needed to avoid `>= 350L`. |

---

## Scenario Combinations Matrix

| Scenario | Input / State | Expected Behavior | Verifier |
| :--- | :--- | :--- | :--- |
| **Pool-Aware USB Discovery (Active)** | `CameraPool` has running USB camera at index `0`; `GET /api/cameras/discover` | Index `0` is NOT re-opened via `probe_device(0)`; reported directly from active metadata without DirectShow contention | `tests/test_camera_discovery_and_guard.py` |
| **Pool-Aware USB Discovery (Idle)** | `active_indices=None` or `{}` | Probes `0..max_devices-1` via `probe_device(idx)` as before (100% backward compatible) | `tests/test_camera_discovery_and_guard.py` + `tests/test_camera_device.py` |
| **Warmup Grace Timeout** | First `read()` after `_open_capture()` on slow DirectShow driver (takes e.g. `2.5s`) | Uses `5.0s` warmup timeout (`warmup_timeout=5.0`), succeeds without tripping circuit breaker | `tests/test_camera_discovery_and_guard.py` |
| **Steady-State Timeout** | Subsequent `read()` calls after first successful frame | Reverts to `2.0s` steady-state timeout (`read_timeout=2.0`) | `tests/test_camera_discovery_and_guard.py` |
| **Severed Driver Exponential Backoff** | Consecutive failed `_open_capture()` / severed read attempts (`attempt = 1, 2, 3...`) | Waits `min(max_backoff, base_delay * (2 ** (attempt - 1)))` via interruptible `_stop_event.wait(timeout=...)`, waking immediately on stop | `tests/test_camera_discovery_and_guard.py` |

---

## Atomic Milestones

### Milestone 1: Pool-Aware USB Camera Discovery
- [x] **Files**:
  - [x] `intelligent_tracker/camera_device.py`: Update `CameraDeviceHandler.discover_usb_cameras(cls, max_devices: int = 6, active_indices: Optional[Collection[int]] = None, active_devices: Optional[Dict[int, Dict[str, Any]]] = None)` (or accept `active_indices: Optional[Collection[int]] = None`) so active indices are skipped during `probe_device()` and synthesized/reported cleanly without re-opening DirectShow handles.
  - [x] `intelligent_tracker/discovery/usb.py` & `intelligent_tracker/discovery/scanner.py`: Thread `active_indices: Optional[Collection[int]] = None` through `find_physical_cameras()` and `discover_all_cameras()` to `discover_usb_cameras()`.
  - [x] `dashboard/services/camera_pool_queries.py`: Add `get_active_usb_indices(self) -> set[int]` to `CameraPoolQueryMixin` (inspecting running streams with integer/`isdigit()` USB sources or `type == "usb"`).
  - [x] `dashboard/routers/cameras.py`: Inject `pool: Optional[CameraPool] = Depends(get_camera_pool)` into `discover_cameras_route()` and pass `active_indices=pool.get_active_usb_indices()` (and merge active USB camera metadata if needed) when `pool` is present.
  - [x] `tests/test_camera_discovery_and_guard.py`: Add unit tests verifying `discover_usb_cameras(active_indices={0})` skips `probe_device(0)`, `CameraPool.get_active_usb_indices()` extracts active USB indices, and `GET /api/cameras/discover` passes active indices without contention.
- [x] **Verification**:
  - [x] `.venv\Scripts\python.exe -m unittest tests/test_camera_discovery_and_guard.py tests/test_camera_device.py tests/test_discovery.py`

### Milestone 2: DirectShow Warmup Grace & Exponential-Backoff Auto-Reopen
- [x] **Files**:
  - [x] `intelligent_tracker/video/capture_guard.py`: Support `warmup_timeout: float = 5.0` (or per-call `timeout` override / warmup tracking without adding new methods to `CaptureReadGuard`), keeping file `< 350` lines.
  - [x] `intelligent_tracker/video/capture_worker.py` (and `intelligent_tracker/video/capture_helpers.py` if needed to keep `capture_worker.py < 350` lines):
    - [x] Track `_needs_warmup: bool = True` on `_open_capture()` success, passing `warmup_timeout` (`5.0s` default) on the first `guard.read()` and clearing `_needs_warmup = False` once a frame is read.
    - [x] Replace fixed `self.reconnect_delay` wait in `_handle_reconnection()` with exponential backoff (`min(max_backoff, base_delay * (2 ** min(attempt, 5)))`) using interruptible `self._stop_event.wait(timeout=delay)`.
  - [x] `tests/test_camera_discovery_and_guard.py`: Add unit tests for `5.0s` warmup grace vs `2.0s` steady-state timeout, severed-driver auto-reopen, exponential backoff progression, and `< 10ms` interruptible stop wakeups.
- [x] **Verification**:
  - [x] `diagnose.py audit --path intelligent_tracker/camera_device.py dashboard/routers/cameras.py intelligent_tracker/video/capture_guard.py intelligent_tracker/video/capture_worker.py --max-lines 350 --max-fn-lines 40`
  - [x] `.venv\Scripts\python.exe -m unittest tests/test_camera_discovery_and_guard.py tests/test_capture_circuit_breaker.py tests/test_camera_device.py tests/test_discovery.py`
