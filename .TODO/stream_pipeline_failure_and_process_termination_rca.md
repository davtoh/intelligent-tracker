# Root Cause Analysis: Video Pipeline Failure & Background Process Termination

**Date:** 2026-11-18  
**Status:** Completed / Ready for Plan Creation  
**Scope:** Stream Worker Concurrency, Camera Pool, FastAPI Server Lifecycle, Exception Tracing, Device Management  
**Target Entities:** `StreamWorker`, `StreamManagerWorker`, `StreamLifecycleManager`, `CameraConfigStore`, `CameraPool`, `shutdown_handler`

---

## 1. Problem Statement & Observed Symptoms

The user reported:
1. **Video Feeds Stopped Showing:** The dashboard web page stopped rendering video frames; streams froze or failed to display images.
2. **Suspected Process Termination:** Background Python processes appeared to have died or stopped processing tasks.
3. **Objective:** Collect all diagnostic traces, determine exact root causes, document the failure mechanisms, and provide a concrete remediation plan for subsequent implementation.

---

## 2. Executive Summary & Diagnostic Findings

Empirical investigation of runtime database metrics (`data/tracker.db`), trace logs (`.diagnostics/trace_catalog.json`), camera configuration (`configs/cameras.json`), and worker thread lifecycles revealed four interacting issues:

| # | Investigated Area | State / Evidence | Impact |
| :--- | :--- | :--- | :--- |
| **1** | **Process Lifecycle** | Telemetry sampler in `system_resource_metrics` recorded continuous 15s samples up to timestamp `1795046245.78` (2026-11-18 23:57:25 UTC / 18:57:25 EST), after which all activity abruptly halted. No Python processes remained active. | The FastAPI/Uvicorn server process terminated (via terminal exit, SIGINT/SIGTERM, or unhandled crash). |
| **2** | **Stream Worker Thread Crashes** | Trace `TRC-006` in `.diagnostics/trace_catalog.json` (10 occurrences in `StreamManagerWorker`): `AttributeError: 'Track' object has no attribute 'entity_name'` inside `frame_overlay.py:115`. | `StreamWorker.run()`'s continuous processing loop lacks localized try/except protection. An unhandled exception during frame encoding permanently killed the worker thread for that camera. |
| **3** | **Host vs Container Configuration** | `configs/cameras.json` configures video files using Docker container paths (`/app/data/videos/...`) which do not exist when executed on native host systems (macOS/Windows). | Native execution triggers `FILE_NOT_FOUND` and `NO_FRAMES_DECODED`, generating persistent error placeholder frames. |
| **4** | **Hibernation & Hardware Locks** | Final telemetry sample (row 10960) recorded: `active_streams: 1, hibernating_streams: 5, total_subscribers: 1`. USB cameras 1 and 2 were missing or locked. | Unfocused or detached camera feeds automatically pause frame decoding via `_should_hibernate()` to preserve CPU/GPU resources. |

---

## 3. Symptom-to-Root-Cause Matrix

| # | Observed Symptom | Failing Evidence / Traceback | Root Cause Analysis | Target File & Line | Verification Check |
|---|---|---|---|---|---|
| 1 | **Video streams freeze on page / stream thread dies** | `TRC-006`: `AttributeError: 'Track' object has no attribute 'entity_name'` in `StreamManagerWorker` thread | `StreamWorker.run()`'s continuous loop lacks exception containment around frame drawing/stepping. Any transient exception crashes the thread permanently, freezing `/stream/{camera_id}` for the client. | `dashboard/services/stream_worker.py:133-154` | `python skills/system-diagnostics/scripts/diagnose.py traces` |
| 2 | **Python backend process died / vanished** | `tracker.db` table `system_resource_metrics` row 10960 logged at `2026-11-18 23:57:25 UTC` (18:57:25 EST), after which all telemetry sampling abruptly halted. No running process found. | The Uvicorn / dashboard server process received a termination signal (CTRL+C / SIGINT / SIGTERM / terminal close) or crashed at 18:57:25 EST, invoking `shutdown_handler` and ending all background threads. | `dashboard/services/shutdown_handler.py:121-148` | `.venv/bin/python scripts/camera_manager.py --status` |
| 3 | **Camera feeds show errors / placeholders on native host** | `configs/cameras.json` lines 5 & 16: `source: "/app/data/videos/..."` | Docker container path prefix (`/app/`) hardcoded in `configs/cameras.json`. Outside Docker (e.g. running locally on macOS/Windows), `/app/...` does not exist, triggering `FILE_NOT_FOUND`. | `configs/cameras.json:5,16` | `.venv/bin/python -m unittest tests/test_camera_diagnostics.py` |
| 4 | **5 of 6 streams showing 0 FPS / Hibernating** | `system_resource_metrics` row 10960: `hibernating_streams: 5, active_streams: 1, subscribers: 1` | In `focus_only` mode or when browser tabs blur/disconnect (`subscriber_count <= 0`), `StreamWorker._should_hibernate()` pauses capture to conserve CPU/GPU. | `dashboard/services/stream_worker.py:102-119` | `GET /api/cameras/diagnostics/system/resource_metrics` |

---

## 4. Deep-Dive Root Cause Analysis

### Root Cause 1: Lack of Frame-Level Exception Isolation in `StreamWorker.run()`

In `dashboard/services/stream_worker.py`:
```python
def run(self) -> None:
    if not self.manager.video_source:
        return
    processor = self._get_processor()
    async_worker = AsyncInferenceWorker(processor)
    async_worker.start()
    try:
        with self.manager.video_source as vs:
            while self.manager._running and not self.manager._stop_event.is_set():
                if self._handle_hibernation(vs, max(processor.frame_count, frame_seq)):
                    continue
                ret, frame = vs.read(timeout=1.0)
                ...
                step_res = build_live_step_result(...)
                self._process_single_frame(step_res)  # <-- UNPROTECTED CALL
    finally:
        async_worker.stop()
```

**The Failure Chain:**
1. If an unexpected attribute error (such as `TRC-006` in `frame_overlay.py:115`), an OpenCV dimension mismatch, or a tracking math exception occurs during `_process_single_frame()`, the exception escapes the `while` loop.
2. The loop breaks immediately and enters `finally: async_worker.stop()`.
3. The `StreamManagerWorker` thread terminates.
4. However, `self.manager._running` remains `True` in `StreamManager`. Because `StreamManager.start()` checks `if self._running: return`, the dead worker thread is never restarted.
5. In the user's browser, `/stream/{camera_id}` stops sending multipart boundaries, freezing the last rendered frame indefinitely.

---

### Root Cause 2: Process Termination at 18:57:25 EST

Investigation of `system_resource_metrics` records in `data/tracker.db`:
- Samples were recorded every 15 seconds by `StreamLifecycleManager`:
  - `(10956, 1795046185.75, 0.0, 293.22, 1, 5, 2)` (23:56:25 UTC)
  - `(10957, 1795046200.76, 0.0, 288.28, 1, 5, 1)` (23:56:40 UTC)
  - `(10958, 1795046215.76, 0.0, 288.31, 1, 5, 1)` (23:56:55 UTC)
  - `(10959, 1795046230.77, 0.0, 288.20, 1, 5, 1)` (23:57:10 UTC)
  - `(10960, 1795046245.78, 0.0, 288.36, 1, 5, 1)` (23:57:25 UTC / 18:57:25 EST)
- No further samples exist after timestamp `1795046245.78`.
- No operating system `uvicorn` or `scripts/run_dashboard.py` process was active.
- When the parent process exited, all active streams, background samplers, and HTTP sockets closed, disconnecting the dashboard.

---

### Root Cause 3: Path Incompatibility in `configs/cameras.json`

In `configs/cameras.json`:
```json
{
  "id": "vid_Video_vecino_mudanza_14",
  "source": "/app/data/videos/Video vecino mudanza 14.mp4",
  "type": "video_file"
},
{
  "id": "vid_20260912132121211_92c53f9523ac476689854669f9750d9e_G94106186",
  "source": "/app/data/videos/20260912132121211_92c53f9523ac476689854669f9750d9e_G94106186.mp4",
  "type": "video_file"
}
```
- `/app/` is the container working directory defined in Docker.
- When the application runs natively outside Docker (e.g. macOS / Windows), `/app/...` does not exist on disk.
- `_diagnose_source_error(vs)` identifies `not os.path.exists(str(vs.source))`, returning `FILE_NOT_FOUND` and substituting an error card JPEG.
- The actual video files reside at `data/videos/Video vecino mudanza 14.mp4`.

---

### Root Cause 4: Hardware USB Device Availability

In `configs/cameras.json`:
- `usb_0` (source: `"0"`)
- `usb_1` (source: `"1"`)
- `usb_2` (source: `"2"`)
When running on laptops or workstations with only a built-in FaceTime/webcam (index 0) or no connected USB webcams, indexes 1 and 2 fail during `cv2.VideoCapture(index).isOpened()`, causing consecutive empty frames and triggering `DEVICE_LOCKED` error states.

---

## 5. Historical Diagnostic Trace Catalog Breakdown

Extracted from `.diagnostics/trace_catalog.json` (managed via `system-diagnostics`):

```
Total Events: 26 | Unique Issues: 7 | Active: 7 | Resolved: 0
```

1. **`TRC-006` (Stream Thread Killer — 10 occurrences)**
   - **Exception:** `AttributeError: 'Track' object has no attribute 'entity_name'`
   - **Culprit:** `dashboard/services/frame_overlay.py:115` in `render()`
   - **Thread:** `StreamManagerWorker`
   - **Trace:**
     ```
     File 'dashboard/stream_manager.py', line 214, in _worker_loop: self._worker.run()
     File 'dashboard/services/stream_worker.py', line 169, in run: self._process_single_frame(step_res)
     File 'dashboard/services/stream_worker.py', line 176, in _process_single_frame: self._encode_annotated_frame(...)
     File 'dashboard/services/stream_worker.py', line 252, in _encode_annotated_frame: annotated = self.manager._overlay_renderer.render(...)
     File 'dashboard/services/frame_overlay.py', line 115, in render: name_disp = trk.entity_name or ...
     ```
   - **Status:** Line 115 was recently patched with `getattr(trk, "entity_name", None)`, but general worker loop resilience remains required to prevent other transient bugs from terminating the worker thread.

2. **`TRC-007` (Gallery Embedding DB Crash — 4 occurrences)**
   - **Exception:** `AttributeError: 'NoneType' object has no attribute 'cursor'`
   - **Culprit:** `intelligent_tracker/repositories/signature_repo.py:181` in `get_gallery_embeddings()`
   - **Context:** `POST /api/videos/test_job_api_clip.mp4/analyze`

3. **`TRC-004` (Job Manager Shutdown Panic — 5 occurrences)**
   - **Exception:** `RuntimeError: VideoJobManager is shut down`
   - **Culprit:** `dashboard/services/video_jobs_service.py:77` in `submit_job()`

4. **`TRC-001` (Windows File Lock Collision — 3 occurrences)**
   - **Exception:** `PermissionError: [WinError 32] El proceso no tiene acceso al archivo porque está siendo utilizado por otro proceso`
   - **Culprit:** `dashboard/routers/videos.py:167` in `delete_video()`

5. **`TRC-003` (API Argument Mismatch — 2 occurrences)**
   - **Exception:** `TypeError: CameraPool.add_camera() missing 2 required positional arguments: 'name' and 'source'`
   - **Culprit:** `dashboard/routers/videos.py:172` in `add_video_as_camera()`

6. **`TRC-002` (SortTracker Keyword Error — 1 occurrence)**
   - **Exception:** `TypeError: SortTracker.__init__() got an unexpected keyword argument 'max_disappeared'`
   - **Culprit:** `intelligent_tracker/tracker/factory.py:30` in `create()`

7. **`TRC-005` (Test Mock Operator Error — 1 occurrence)**
   - **Exception:** `TypeError: unsupported operand type(s) for |: 'builtin_function_or_method' and 'NoneType'`
   - **Culprit:** `tests/test_transcode_atomic_rollback.py:27` in `_FakeStdout()`

---

## 6. Recommended Remediation & Architecture Plan

### Phase 1: Worker Loop Fault Isolation & Self-Healing (`StreamWorker`)
- **Action:** In `dashboard/services/stream_worker.py`, wrap the frame stepping and encoding inside `while self.manager._running:` with a dedicated `try...except Exception as exc:` block.
- **Behavior:**
  - Log the error via `capture_runtime_exception(exc)` so it is cataloged in `.diagnostics/traces/`.
  - Increment consecutive failure counters.
  - Sleep for 50ms before fetching the next frame rather than terminating the worker thread.
  - Set `self.manager._latest_jpeg` to a non-fatal warning card if errors persist for $> 10$ consecutive frames.

### Phase 2: Environment-Agnostic File Path Resolution (`CameraConfigStore`)
- **Action:** In `dashboard/services/camera_config_store.py` and `intelligent_tracker/pipeline/config.py`:
  - When loading video files, inspect if path begins with `/app/` and `/app` does not exist on the current host filesystem.
  - Automatically resolve to relative path `./data/...` or absolute `<repo_root>/data/...`.
  - Maintain the existing string when saving back if running in Docker, or normalize to relative paths (`data/videos/...`) across both environments.

### Phase 3: Missing Device Auto-Degradation (`CameraPool`)
- **Action:** In `dashboard/camera_pool.py`:
  - During `load_cameras()`, if a USB camera index cannot be opened, mark its runtime status as `device_unavailable` rather than launching an unconstrained reconnection loop.
  - Provide a single-click "Retry Connection" in the UI rather than holding hardware locks.

### Phase 4: Server Launch & Verification Protocol
- **Action:** Execute the server using the designated virtual environment:
  ```bash
  .venv/bin/python scripts/run_dashboard.py --local
  ```
- Verify the 5 standard test suites and trace catalog:
  ```bash
  MPLBACKEND=Agg .venv/bin/python -m unittest tests/test_camera_diagnostics.py
  python skills/system-diagnostics/scripts/diagnose.py traces --recent 5
  ```
