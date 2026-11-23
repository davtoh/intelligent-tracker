# Implementation Plan: CaptureReadGuard Concurrency & COM Apartment Hardening

## Executive Summary
Forensic analysis of `commit 0804174` (`CaptureReadGuard`) revealed two subtle concurrency and Windows driver-affinity edge cases when a camera stalls after hibernation:
1. **Multi-Thread Read/Release Cascade**: On read timeout #1, `CaptureReadGuard.read()` resets `self._current_job = None` and fires `safe_driver_unbind(cap)` in a background thread. However, `CaptureWorkerMixin._capture_worker()` only clears `self._cap` once `guard.is_reconnecting` is `True` (`reconnect_threshold = 5`). On iterations 2–4, `_capture_worker()` calls `guard.read(self._cap)` again, spawning **new** `_CaptureReadJob` threads calling `cap.read()` concurrently with the stalled thread and the background `cap.release()` thread—violating OpenCV `VideoCapture` single-thread access invariants.
2. **DirectShow COM Apartment Affinity**: On Windows (`cv2.CAP_DSHOW`), `CaptureReadJobWorker` executes `cap.read()` on a separate daemon thread without initializing COM (`CoInitializeEx`), risking silent driver enumeration/frame-grabber stalls during sleep/wake recovery.

---

## 1. Architectural Surface Invariants & Quantitative Modularity Budgets

| Target File | Current Lines | Planned Net Change | Projected Lines | Status | Action |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `intelligent_tracker/video/capture_guard.py` | 320 | +20 | ~340 | Healthy ($\le 350$) | Add COM initialization to `SafeDriverUnbindWorker` |
| `intelligent_tracker/video/capture_worker.py` | 342 | -5 | ~337 | Healthy ($\le 350$) | Remove unguarded direct `self._cap.read()` in `_handle_empty_frame` |
| `dashboard/camera_pool.py` | 483 | +5 | ~488 | Warning (< 500 ceiling) | Move `mgr.stop()` and `mgr.start()` outside `self._lock` in `remove_camera` / `update_camera` |
| `tests/test_capture_circuit_breaker.py` | 358 | +65 | ~423 | Warning (< 500 ceiling) | Add tests for unbind COM init and lock-free pool removal/updates |

---

## 2. Multi-Phase Roadmap

### Milestone 1: Atomic Driver Severing & Single-Flight Read Affinity (Completed)
**Scope**: Guarantee at most one thread ever touches a given `VideoCapture` instance at any time, even across timeouts and reconnection transitions.

- [x] **intelligent_tracker/video/capture_guard.py**:
  - [x] Initialize Windows COM (`ctypes.windll.ole32.CoInitializeEx(None, 0)`) inside `_CaptureReadJob._run()` (with matching `CoUninitialize()` in `finally:`) when `sys.platform == "win32"`.
  - [x] Add `self._timed_out_caps: set[int]` or `last_read_timed_out: bool` property on `CaptureReadGuard` so callers know immediately when `safe_driver_unbind(cap)` has already been dispatched.
  - [x] Prevent `_ensure_job(cap)` from spawning a new `_CaptureReadJob` for a `cap` object whose previous job is still blocked inside `cap.read()` (`is_reading == True`).
- [x] **intelligent_tracker/video/capture_worker.py**:
  - [x] In `_capture_worker()`, when `guard.read()` returns `(False, None)` due to a **timeout** (or `guard.last_read_timed_out` is `True`), immediately set `self._cap = None` and `self._is_connected = False` without waiting for `reconnect_threshold = 5`, entering `_handle_reconnection()` cleanly instead of re-polling the severed handle.
- [x] **tests/test_capture_circuit_breaker.py**:
  - [x] Add `test_timeout_severs_cap_without_spawning_concurrent_readers` verifying that a stalled `DummyHangingCap` receives at most 1 `read()` call before `release()` is invoked and `self._cap` is cleared.
  - [x] Add `test_com_initialization_on_win32_worker` (mocked `ole32`) verifying `CoInitializeEx` / `CoUninitialize` lifecycle on Windows.

### Milestone 2: CameraPool Teardown Concurrency & Driver Unbind COM Hardening
**Scope**: Eliminate lock contention during dynamic stream lifecycle changes (`remove_camera`, `update_camera`) and ensure COM apartment safety on background unbind worker threads.

- [x] **intelligent_tracker/video/capture_guard.py**:
  - [x] Initialize and uninitialize Windows COM apartment (`CoInitializeEx` / `CoUninitialize`) inside `safe_driver_unbind()`'s `SafeDriverUnbindWorker` thread.
- [x] **intelligent_tracker/video/capture_worker.py**:
  - [x] Protect looping video rewind in `_handle_empty_frame()` from issuing un-guarded `self._cap.read()` calls.
- [x] **dashboard/camera_pool.py**:
  - [x] Refactor `remove_camera(camera_id)` to invoke `mgr.stop()` outside `self._lock` to prevent blocking concurrent API access during hardware release.
  - [x] Refactor `update_camera()` to stop previous stream and start replacement stream outside `self._lock`.
- [x] **tests/test_capture_circuit_breaker.py**:
  - [x] Add `test_com_initialization_on_win32_unbind_worker` verifying Windows COM lifecycle on `safe_driver_unbind` background worker.
  - [x] Add `test_remove_camera_releases_lock_during_teardown` verifying `CameraPool._lock` remains unblocked while `remove_camera` stops streams.
  - [x] Add `test_update_camera_releases_lock_during_teardown` verifying `CameraPool._lock` remains unblocked while `update_camera` restarts streams.

---

## 3. Scenario Combinations Matrix

| Real-World Scenario / Objective | Mode / Platform | Key Mechanism | Exact Runnable Command | Expected Outcome |
| :--- | :--- | :--- | :--- | :--- |
| **Verify Circuit-Breaker Concurrency** | Cross-platform | `unittest` | `.venv\Scripts\python.exe -m unittest tests/test_capture_circuit_breaker.py` | 100% pass; zero concurrent `read()`/`release()` overlap |
| **Run Full Regression Suite** | Headless (`MPLBACKEND=Agg`) | `unittest discover` | `$env:MPLBACKEND='Agg'; .venv\Scripts\python.exe -m unittest discover tests` | All tests pass green |

---

## 4. Definition of Done (DoD)
- `tests/test_capture_circuit_breaker.py` passes 100% green including the concurrent-read regression test.
- Full test suite passes with zero regressions.
- `capture_guard.py` and `capture_worker.py` remain below the 350-line soft ceiling.
