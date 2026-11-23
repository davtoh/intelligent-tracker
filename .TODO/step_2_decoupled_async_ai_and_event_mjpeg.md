# Child Plan (Step 2): Decoupled Async AI, Event-Driven MJPEG & On-Demand Single JPEG

> **Parent Roadmap**: `.TODO/performance_and_processing_modes_master_roadma_followups.md` (Milestone 2)

## Architecture & Modularity Contracts
- **Zero `__future__` Imports**: Strictly target Python 3.10–3.12+ idioms (`|`, built-in generics).
- **Modularity Budgets**:
  - `dashboard/services/async_inference_worker.py`: `<= 150` lines, `<= 10` methods, `<= 40` lines/method.
  - `dashboard/services/stream_worker.py`: `< 350` lines (currently 282L), `<= 40` lines/method.
  - `dashboard/services/stream_media.py` & `dashboard/stream_manager.py`: `< 350` lines each.
  - `dashboard/routers/streaming.py`: `< 200` lines, route handlers `<= 25` lines, helpers `<= 40` lines.
- **Public Surface Invariants**:
  - Preserve `StreamWorker._process_single_frame(step_res: FrameStepResult)` signature and on-demand `has_raw_subscribers` / `has_annotated_subscribers` JPEG encoding behavior.
  - Preserve `GET /stream/{camera_id}?annotated=true|false` and `GET /api/cameras/{camera_id}/telemetry` contracts per `documentation/enterprise_hub_integration.rst`.
- **Thread Safety & Shutdown**:
  - `AsyncInferenceWorker` uses `threading.Event` (`_work_event`, `_stop_event`) — zero uninterruptible `time.sleep()`.
  - Never hold locks across `thread.join()`.
  - `StreamWorker.run()` `finally` block and `StreamManager.stop()` cleanly stop `AsyncInferenceWorker`.

## Scenario Combinations Matrix
| Scenario | Vision Gating | Capture & MJPEG Behavior | Expected Outcome |
| :--- | :--- | :--- | :--- |
| `full_realtime` (or focused in `focus_only`) + `annotated=true` | `should_run_vision=True` | `StreamWorker` submits latest frame to `AsyncInferenceWorker`, draws cached tracks on live frame, encodes `_latest_jpeg` only | Native 30–60+ FPS MJPEG; slow AI drops intermediate frames without stalling video |
| `focus_only` unfocused tile + `annotated=false` | `should_run_vision=False` | `StreamWorker` skips AI submission, encodes `_latest_raw_jpeg` only, signals frame-ready | Zero AI CPU overhead; immediate raw MJPEG delivery |
| `paused` / `hibernating` (0 subscribers) | `should_run_vision=False` | `StreamWorker` pauses capture; `_stream_frame_generator` wakes on `1.5s` heartbeat or `shutdown_evt` | Clean lease maintenance & instant shutdown |
| Rapid `StreamManager.stop()` | N/A | `stop()` sets `_stop_event`, stops `AsyncInferenceWorker`, joins threads outside locks | Teardown completes in `< 0.5s` with zero orphaned threads |

---

## Milestones

### Milestone 1: `AsyncInferenceWorker` & Non-Blocking `StreamWorker` Integration
- [x] **Create `dashboard/services/async_inference_worker.py`** (`<= 150` lines):
  - [x] Implement `AsyncInferenceWorker(processor, max_dim=1280)` with a single-slot latest-frame buffer protected by `threading.Lock`, `_work_event = threading.Event()`, and `_stop_event = threading.Event()`.
  - [x] Provide `start()`, `stop(timeout=1.0)`, `submit(frame, timestamp)` (non-blocking; overwrites any pending unconsumed frame), and `get_latest_result() -> FrameStepResult | None`.
  - [x] Background loop copies the pending slot under lock, releases lock before calling `processor.step(frame, timestamp=ts, max_dim=self._max_dim)`, and atomically updates `_latest_result`.
- [x] **Update `dashboard/services/stream_worker.py`**:
  - [x] Instantiate and start `AsyncInferenceWorker(processor)` in `StreamWorker.run()` (with `try ... finally: worker.stop()`).
  - [x] When `_should_run_vision_step(is_rec)` is `True`, call `async_worker.submit(frame, now)` instead of blocking on `processor.step()`, and merge `async_worker.get_latest_result()` (`tracks`, `analytics`, `identifications`, `fps`) into the live `FrameStepResult`.
  - [x] Remove the blind `self.manager._stop_event.wait(timeout=0.01)` at the end of `_process_single_frame()`.
- [x] **Create `tests/test_async_inference_worker.py`**:
  - [x] Verify non-blocking `submit()` drops stale intermediate frames when `processor.step()` is slow.
  - [x] Verify `get_latest_result()` returns cached `tracks`/`analytics` and `stop()` terminates cleanly in `< 0.2s`.
  - [x] Verify `StreamWorker` reuses cached tracks on live frames without blocking capture.
- [x] **Verification**:
  - [x] `.\.venv\Scripts\python.exe "C:\Users\User\.gemini\config\skills\system-diagnostics\scripts\diagnose.py" audit --path dashboard/services/async_inference_worker.py dashboard/services/stream_worker.py tests/test_async_inference_worker.py --max-lines 350 --max-fn-lines 40`
  - [x] `.\.venv\Scripts\python.exe -m unittest tests/test_async_inference_worker.py tests/test_step1_on_demand_jpeg_encoding.py tests/test_step2_clean_streaming.py tests/test_step1_perf_integration.py`

### Milestone 2: Event-Driven MJPEG Wakeup, On-Demand Single JPEG & `StreamManager` Lifecycle
- [x] **Update `dashboard/services/stream_media.py` & `dashboard/stream_manager.py`**:
  - [x] Add thread-safe frame-ready waiter registry (`register_frame_waiter(loop, event)`, `unregister_frame_waiter(loop, event)`, `notify_frame_ready()`) and monotonic `_frame_seq` counter on `StreamMediaMixin`.
  - [x] Call `self.manager.notify_frame_ready()` at the end of `StreamWorker._process_single_frame()` after JPEG encoding.
  - [x] Ensure `StreamManager.stop()` wakes all frame waiters so streaming generators exit immediately on shutdown.
- [x] **Update `dashboard/routers/streaming.py`**:
  - [x] Replace `await asyncio.wait_for(shutdown_evt.wait(), timeout=0.04)` in `_stream_frame_generator()` with event-driven `asyncio.wait` on `frame_event.wait()` and `shutdown_evt.wait()` (with a `1.5s` safety timeout for `heartbeat_subscriber`), clearing `frame_event` before reading `get_latest_frame_jpeg(annotated=annotated)`.
- [x] **Create `tests/test_stream_manager.py`**:
  - [x] Verify event-driven frame wakeup fires immediately on `notify_frame_ready()` (`< 50ms`), `annotated=False` vs `annotated=True` on-demand JPEG selection, and clean `StreamManager.stop()` waiter wakeup.
- [x] **Verification**:
  - [x] `.\.venv\Scripts\python.exe "C:\Users\User\.gemini\config\skills\system-diagnostics\scripts\diagnose.py" audit --path dashboard/services/stream_media.py dashboard/stream_manager.py dashboard/routers/streaming.py tests/test_stream_manager.py --max-lines 350 --max-fn-lines 40`
  - [x] `.\.venv\Scripts\python.exe -m unittest tests/test_async_inference_worker.py tests/test_stream_manager.py tests/test_hibernation.py tests/test_graceful_shutdown_perf.py`
