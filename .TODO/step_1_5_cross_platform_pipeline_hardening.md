# Step 1.5: Cross-Platform Pipeline Hardening & Live/Studio Sync (Child Plan)

> Parent: `.TODO/realtime_multiview_master_roadmap.md` (Milestone 2 / Step 1.5).
> Sources: `stream_pipeline_failure_and_process_termination_rca.md` + `live_monitor_vs_video_studio_sync_rca.md` (commit `d5271cd`, audited against current `HEAD`).
> Goal: Eliminate silent stream worker deaths, 181s missing-file reconnect stalls, `/app/` vs Windows/macOS path mismatches, heavy AI init for dead/missing sources, open trace catalog defects (`TRC-001`, `TRC-004`, `TRC-007`), and Live Monitor vs Video Studio bounding-box desynchronization—without breaking any existing modularity budget or `annotated=false` interactive canvas contracts.

---

## 1. Empirical Baseline & Current HEAD Audit

| # | Symptom / Gap | Evidence in Current HEAD | Root Cause | Target Location |
|---|---|---|---|---|
| 1 | `StreamWorker` thread dies permanently on transient frame/overlay errors | `run()` only wraps `try ... finally: async_worker.stop()`; `_running` stays `True` so `start()` becomes a no-op | Zero frame-level exception isolation in `StreamWorker.run()` and `vs.__enter__()`; `_latest_raw_jpeg` also lacks error cards | `dashboard/services/stream_worker.py#L110-L176`, `#L202-L227` |
| 2 | `/app/data/videos/...` & Windows `\` paths fail cross-platform | `configs/cameras.json` stores `/app/...`; `Path(raw).name` on POSIX fails on `C:\...\foo.mp4` | `CameraConfigStore` persists raw container/host paths; `resolve_file_source()` calls `Path(raw).name` instead of `Path(normalized).name` | `intelligent_tracker/camera_resolver.py#L36-L98`, `dashboard/services/camera_config_store.py#L65-L160` |
| 3 | Missing video files spin ~181s; unavailable USB cameras load full YOLOv8 + block boot | `_capture_worker()` lacks `not self.is_file` at `#L299-L303`; `resolve_camera_source("1")` blindly returns `status="ok"`; macOS returns `[]` | Heavy `StreamManager(...)` (YOLO/DB/EventBus) is eagerly constructed before source probing; `StreamManager(...)` lacks `try/except` in coordinator | `intelligent_tracker/video/capture_worker.py#L299-L303`, `dashboard/services/stream_pool_coordinator.py#L116-L142` |
| 4 | Open runtime traces (`TRC-001`, `TRC-004`, `TRC-007`) | `signature_repo.py#L49,96,147,181` dereferences `self._conn.cursor()` unguarded; `delete_video` skips `CameraPool` handles; `video_jobs` leaks `RuntimeError` | Missing `_conn is None` guard (`TRC-007`), active camera handle release/409 (`TRC-001`), and shutdown `503`/reset (`TRC-004`). Note: `TRC-002/003/005/006/008..010` are already fixed in HEAD and need catalog reconciliation | `intelligent_tracker/repositories/signature_repo.py`, `dashboard/routers/videos.py#L128-L138`, `dashboard/routers/video_jobs.py` |
| 5 | Live Monitor bounding boxes lag/drift vs frame-perfect Video Studio | 1x1 uses decoupled MJPEG (`?annotated=false`) + WS telemetry; `build_live_step_result()` stamps `now`/`frame_seq` onto stale `AsyncInferenceWorker` boxes | No `frame_seq`/age provenance; `video_file` cameras ignore pre-indexed `TrackerDB` runs; `interactive_canvas.js#L214` queries nonexistent `#video-stream`; no `annotated=true` HUD toggle | `dashboard/services/async_inference_worker.py#L53-L114`, `dashboard/static/interactive_canvas.js#L214`, `dashboard/static/js/live_player.js#L102` |

---

## 2. Modularity Budgets & Placement ("Split-Before-You-Grow")

Enforced test budgets in `tests/test_dashboard_di.py`, `tests/test_step3_architecture_budgets.py`, `tests/test_step3_tag_modal_integration.py`, and `tests/test_step4_e2e_performance_and_modes.py`:

| Module | Current | Enforced Cap | Strategy for Step 1.5 |
|---|---:|---:|---|
| `dashboard/services/stream_pool_coordinator.py` | 237 L | `< 240 L` | Extract probing & deferred-retry registration into new `dashboard/services/camera_source_bootstrap.py` |
| `dashboard/services/stream_worker.py` | 276 L / 12 methods | `<= 285 L` / `<= 12` methods | Extract exception-isolation & warning-card helper into new `dashboard/services/stream_worker_recovery.py` |
| `dashboard/services/camera_config_store.py` | 165 L | `< 180 L` | Keep normalization helper concise or delegate to `CameraPathResolver` |
| `dashboard/static/partials/tabs/live.html` | 207 L | `< 220 L` | Add at most 2–4 lines for the HUD toggle (or mount dynamically from `live_player.js`) |
| `dashboard/static/interactive_canvas.js` | `< 240 L` | `< 240 L` | 1-line ID fix (`video-stream` -> `live-stream-img`) + clean guard |
| `dashboard/services/file_detection_replay.py` *(New)* | 0 L | `<= 250 L` | Pre-indexed `TrackerDB` detection lookup for `video_file` cameras |

---

## 3. Milestones

### Milestone 1: Cross-Platform Path/Device Resilience, Worker Fault Isolation & Open Trace Fixes
Addresses all open items from `stream_pipeline_failure_and_process_termination_rca.md` and `.diagnostics/trace_catalog.json` while keeping `stream_pool_coordinator.py < 240 L` and `stream_worker.py <= 285 L`.

- [x] **intelligent_tracker/camera_resolver.py** + **intelligent_tracker/camera_device.py** + **intelligent_tracker/pipeline/config.py**: Fix `resolve_file_source()` (`#L69`) to use `Path(normalized).name` (fixing Windows `\` paths on POSIX/Docker); normalize workspace `/app/data/videos/...` and host-absolute `data/videos/...` paths to portable `data/videos/<name>` in `normalize_source_path()`; add bounded macOS (`darwin`) camera enumeration fallback in `camera_device.py`; extend `_is_video_file()` (`config.py#L98-L102`) with `.wmv/.flv/.webm/.m4v` and surface resolver unavailability metadata cleanly.
- [x] **dashboard/services/camera_config_store.py** + **dashboard/routers/videos.py#L180**: Normalize container/host workspace video paths on `load_cameras()`, `build_and_store_entry()`, `update_entry()`, and `add_video_as_camera()` so `configs/cameras.json` remains portable across Docker, Windows, macOS, and Linux (`< 180 L` cap).
- [x] **intelligent_tracker/video/capture_worker.py#L299-L303**: Add `and not self.is_file` guard to the initial `_open_capture()` failure branch (matching `#L312` and `#L320`) so missing local video files fail fast instead of spinning ~181s through exponential backoff reconnects.
- [x] **dashboard/services/camera_source_bootstrap.py** *(New)* + **dashboard/services/stream_pool_coordinator.py#L116-L166** + **dashboard/routers/cameras.py**: Extract source pre-flight probe (`FILE_NOT_FOUND` / `DEVICE_UNAVAILABLE` check for numeric indices) and safe `StreamManager` initialization wrapper (`try/except`) so dead/missing cameras register cleanly offline in `CameraHealthManager` without loading heavy YOLOv8/`TrackerDB`/`EventBus` pipelines or crashing `load_cameras()` / `add_camera()`, and expose a retry endpoint (`POST /api/cameras/{camera_id}/retry`) to re-probe and start recovery on demand.
- [x] **dashboard/services/stream_worker_recovery.py** *(New)* + **dashboard/services/stream_worker.py#L110-L176,#L202-L227**: Isolate `vs.__enter__()`, `build_live_step_result()`, and `_process_single_frame()` inside localized `try/except Exception` handling using `capture_runtime_exception(exc)`, consecutive error counter, interruptible `_stop_event.wait(0.05)`, and non-fatal error-card fallback after >10 consecutive errors; ensure `_latest_raw_jpeg` (not only `_latest_jpeg`) receives error placeholders on failure.
- [x] **intelligent_tracker/repositories/signature_repo.py#L49,96,147,181** + **dashboard/routers/videos.py#L128-L138** + **dashboard/services/video_jobs_service.py** + **dashboard/routers/video_jobs.py** + **.diagnostics/trace_catalog.json**: Guard `self._conn is None` in `SignatureRepo` (`TRC-007`); release/stop active `CameraPool` file streams before `os.remove()` or return HTTP `409` on Windows file lock in `delete_video()` (`TRC-001`); handle shut-down `VideoJobManager` cleanly with `503`/reset (`TRC-004`); reconcile `TRC-001`..`TRC-010` statuses in `.diagnostics/trace_catalog.json`.
- [x] **tests/test_cross_platform_pipeline_hardening.py** *(New)*: Unit tests covering Windows/POSIX path normalization, `CaptureWorker` fast-fail on missing files (`not self.is_file`), unavailable USB device skipping heavy YOLO init + retry endpoint, `StreamWorker` transient exception recovery without thread death, `SignatureRepo` closed-DB guard, `delete_video` active camera release, and `video_jobs` shutdown `503` handling.

### Milestone 2: Live Monitor vs Video Studio Synchronization & Diagnostic Clarity *(Deferred to Next Milestone)*
Addresses all 3 phases of `live_monitor_vs_video_studio_sync_rca.md` while keeping `annotated=false` as the 1x1 default (`tests/test_step2_live_canvas_delegation.py`) and preserving all HTML/JS line budgets.

- [ ] **dashboard/services/async_inference_worker.py#L53-L114** + **dashboard/services/stream_telemetry.py#L119**: Pass `frame_seq` into `AsyncInferenceWorker.submit(frame, timestamp, frame_seq=...)`, record `inference_frame_seq` and `inference_timestamp` on cached results, clear stale `_latest_result` when `run_vision` is `False`, and emit `frame_seq`, `inference_frame_seq`, `inference_lag_ms`, and `source_resolution: [w, h]` in telemetry payloads.
- [ ] **dashboard/services/file_detection_replay.py** *(New)* + **dashboard/services/stream_worker.py** / **dashboard/services/async_inference_worker.py**: Implement Option B (Pre-Indexed File-Camera Detection Replay Provider) so `video_file` cameras with a completed `TrackerDB` run replay timestamp/frame-aligned `video_detections` without redundant live YOLOv8 inference, falling back seamlessly to live inference when no matching run exists.
- [ ] **dashboard/static/interactive_canvas.js#L214** + **dashboard/static/app.js#L179-L228**: Fix `el('video-stream')` -> `el('live-stream-img')` in `initTagModal()` so `RoiDrawTagger` receives live media dimensions, and pass `source_resolution` into `InteractiveCanvas.drawOverlay()` for accurate coordinate scaling.
- [ ] **dashboard/static/js/live_player.js#L68-L108** + **dashboard/static/partials/tabs/live.html** + **dashboard/static/js/multiview/frame_surface.js**: Add an opt-in 1x1 Live HUD toggle (`Interactive Canvas` [`annotated=false`, default] vs `Burned Annotations` [`annotated=true`, persisted in `localStorage`]) that suppresses stale client boxes when `annotated=true` is active, surfaces a lightweight inference-lag indicator when `inference_lag_ms` exceeds threshold, and correlates `seq` metadata cleanly on canvas surfaces.
- [ ] **tests/test_live_studio_sync.py** *(New, Python + Node VM <= 40 L/method)*: Verify `AsyncInferenceWorker` `frame_seq`/lag provenance and mode-switch cache clearing, `FileDetectionReplayProvider` frame lookup + fallback, `interactive_canvas.js` `#live-stream-img` binding, and `live_player.js` `annotated` toggle preserving default `annotated=false`.
- [ ] **documentation/** + **CHANGELOG.md**: Update pipeline resilience and sync documentation (`sphinx -W` clean) and record milestone completion via `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add`.

---

## 4. Scenario Combinations Matrix

| Scenario | Command | Expected |
|---|---|---|
| Full test suite (headless) | `MPLBACKEND=Agg python -m unittest discover tests` | 100% green |
| Milestone 1 targeted suite | `MPLBACKEND=Agg python -m unittest tests.test_cross_platform_pipeline_hardening tests.test_camera_diagnostics tests.test_capture_circuit_breaker` | Green; fast-fail missing file (< 2 s), zero worker thread death |
| Milestone 2 targeted suite | `MPLBACKEND=Agg python -m unittest tests.test_live_studio_sync tests.test_step2_live_canvas_delegation tests.test_step4_e2e_performance_and_modes` | Green; `annotated=false` default preserved, `#live-stream-img` bound |
| Modularity budget audit | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path <touched files>` | PASS (`stream_pool_coordinator.py < 240 L`, `stream_worker.py <= 285 L`, `live.html < 220 L`) |
| Sphinx documentation build | `python -m sphinx -W --keep-going documentation/ documentation/_build/html/` | 0 warnings |

---

## 5. Definition of Done

- **Milestone 1**: Portable path resolution across Docker/Windows/macOS/Linux; missing files and unavailable USB cameras fail fast into non-blocking offline states with retry support; `StreamWorker` survives transient frame/overlay errors without thread exit; `TRC-001/004/007` fixed and `.diagnostics/trace_catalog.json` reconciled; all Milestone 1 & full regression tests pass within modularity budgets.
- **Milestone 2**: Telemetry carries `frame_seq`/`inference_lag_ms`/`source_resolution`; indexed `video_file` cameras replay cached `TrackerDB` detections without redundant YOLO load; `#live-stream-img` tagger bug fixed; opt-in `annotated=true` toggle works without breaking `annotated=false` default; Sphinx `-W` clean; changelog updated.
