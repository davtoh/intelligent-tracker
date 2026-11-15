# Step 3 Implementation Plan: Backend Processing Modes (`Focus Only`, `Full Real-Time`, `Capture-Only`, `Paused`) & Deferred Queue

> **Parent Master Plan**: `.TODO/performance_and_processing_modes_master_roadmap.md` (Step 3)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md`
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–3 are *Deferred to Subsequent Turns*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map` & `diagnose.py audit`)

Measured against workspace baseline before edits (`305` files, `56,195` lines, `108` FastAPI routes):
- `dashboard/services/stream_worker.py`: `342` lines (`OK < 350L`, `10` methods on `StreamWorker`, `0` defects). Because `342L` is only `8` lines below the `350L` soft warning ceiling, Milestone 1 first extracts telemetry formatting helpers (`_extract_recent_alerts`, `_extract_track_telemetry`, `_build_zones_data`, `_build_tripwires_data`, `_resolve_detector_telemetry`, `build_stream_telemetry`) into `dashboard/services/stream_telemetry.py` (`~105L`), reducing `stream_worker.py` to `~235L` while re-exporting helper symbols in `stream_worker.py` for backward compatibility.
- `dashboard/services/stream_recording.py`: `265` lines (`OK < 350L`, `0` defects). `StreamRecordingController` currently writes frames and persists a `live_capture` report run on `stop()`, without a `capture_only` raw-recording bypass or deferred `VideoIndexer` handoff.
- `dashboard/services/stream_pool_coordinator.py`: `230` lines (`OK < 350L`, `9` methods on `StreamPoolCoordinator`, `0` defects). Currently starts all enabled camera streams eagerly without `ProcessingModeService` focus/hibernation coordination.
- `dashboard/app.py`: `296` lines (`OK < 350L`, `0` defects). Mounts domain routers via `application.include_router(...)`.
- `intelligent_tracker/journey_segmenter.py`: Verified at `137` lines (`< 160L` cap in `tests/test_step4_preflight_budgets.py`, `6/6` tests passing following `journey_models.py` extraction).

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts (Zero-Regression Invariants)
- **REST Endpoints Added**:
  - `GET /api/system/processing-mode` $\rightarrow$ `ProcessingModeStatusResponse` (`mode`, `focused_camera_id`, `active_tab`, `valid_modes`, `deferred_jobs`, `camera_states`, `updated_at`).
  - `POST /api/system/processing-mode` $\rightarrow$ accepts `ProcessingModeUpdateRequest` (`mode`, `focused_camera_id`, `active_tab`) and returns updated `ProcessingModeStatusResponse`.
- **Recording Schema Parity (`dashboard/schemas.py`)**:
  - `CameraRecordStatusResponse` preserves all existing fields (`camera_id`, `is_recording`, `status`, `recording_id`, `filename`, `output_path`, `codec`, `fps`, `width`, `height`, `frames_written`, `elapsed_s`, `size_bytes`, `annotated`, `started_at`, `stopped_at`, `report_run_id`) and adds `processing_mode: Optional[str] = None` and `deferred_job_id: Optional[str] = None`.
- **`StreamWorker` Symbol Re-Exports (`dashboard/services/stream_worker.py`)**:
  - Re-exports `_resolve_detector_telemetry`, `_extract_recent_alerts`, `_extract_track_telemetry`, `_build_zones_data`, and `_build_tripwires_data` from `dashboard/services/stream_telemetry.py` so existing unit tests (`tests/test_step1_camera_config_healing.py`, etc.) remain unbroken.
- **Isolated `StreamWorker` Host Compatibility**:
  - When `StreamWorker` runs against a lightweight test host without `_processing_mode_service` (or outside a multi-camera pool where `_in_camera_pool` is `False` and `mode` was not explicitly restricted), default subscriber-based hibernation and vision stepping remain 100% backward-compatible with `tests/test_step1_*.py` and `tests/test_refine_async_and_cold_start.py`.

### Modularity Guardrails
- `dashboard/services/stream_telemetry.py` MUST stay `< 130` lines with all functions `<= 35` lines.
- `dashboard/services/processing_mode_service.py` MUST stay `< 200` lines (`<= 12` methods on `ProcessingModeService`) with all functions `<= 35` lines.
- `dashboard/routers/processing_mode.py` MUST stay `< 120` lines with route handlers `<= 25` lines.
- `dashboard/services/stream_worker.py` MUST stay `< 290` lines (`<= 12` methods on `StreamWorker`) with all functions `<= 40` lines.
- `dashboard/services/stream_pool_coordinator.py` MUST stay `< 270` lines (`<= 11` methods on `StreamPoolCoordinator`) with all functions `<= 35` lines.
- `dashboard/services/stream_recording.py` MUST stay `< 310` lines (`<= 12` methods on `StreamRecordingController`) with all functions `<= 40` lines.
- `dashboard/app.py` MUST stay `< 310` lines and `dashboard/schemas.py` MUST stay `< 320` lines.
- Every unit test method MUST stay `<= 40` lines (`AGENTS.md` Rule 3).

---

## 3. Phased Implementation Milestones

### Milestone 1: `ProcessingModeService`, `/api/system/processing-mode` Router & `StreamTelemetry` Extraction
- [x] **dashboard/services/stream_telemetry.py**: Extract `_extract_recent_alerts`, `_extract_track_telemetry`, `_build_zones_data`, `_build_tripwires_data`, `_resolve_detector_telemetry`, and `build_stream_telemetry` from `dashboard/services/stream_worker.py` (`< 130L`, functions `<= 35L`).
- [x] **dashboard/services/stream_worker.py**: Delegate telemetry construction to `dashboard/services/stream_telemetry.py` while re-exporting helper symbols, reducing `stream_worker.py` from `342L` to `~235L`.
- [x] **dashboard/services/processing_mode_service.py**: Create `ProcessingModeService` and `get_processing_mode_service()` (`< 200L`, `<= 12` methods, functions `<= 35L`) managing `mode` (`focus_only` default, `full_realtime`, `capture_only`, `paused`), `focused_camera_id` (`"cam_01"` default), `active_tab` (`"live"` default), `should_hibernate_camera()`, `should_run_vision_step()`, `apply_to_pool()`, and `enqueue_deferred_indexing()`.
- [x] **dashboard/schemas.py**: Add `ProcessingModeUpdateRequest` and `ProcessingModeStatusResponse`, and add `processing_mode: Optional[str] = None` and `deferred_job_id: Optional[str] = None` to `CameraRecordStatusResponse` (`< 320L`).
- [x] **dashboard/routers/processing_mode.py**: Create FastAPI router (`< 120L`, routes `<= 25L`) exposing `GET /api/system/processing-mode` and `POST /api/system/processing-mode`, and export `processing_mode_router` in `dashboard/routers/__init__.py` and mount it in `dashboard/app.py` (`< 310L`).
- [x] **tests/test_step3_processing_mode_api.py**: Add unit and FastAPI `TestClient` tests (`<= 40L` per test method) verifying `stream_telemetry.py` extraction, `ProcessingModeService` policy transitions across all 4 modes and tabs, and `GET`/`POST /api/system/processing-mode` validation and pool state reporting.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 1 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step3_processing_mode_api.py"
```

---

### Milestone 2: `StreamWorker` & `StreamPoolCoordinator` Hibernation and Tab-Scoped AI Gating *(Deferred)*
- [x] **dashboard/services/stream_pool_coordinator.py**: Attach `processing_mode_service` and `_in_camera_pool = True` to registered `StreamManager` instances and add `sync_processing_mode()` (`< 270L`, `<= 11` methods, functions `<= 35L`) so unfocused cameras hibernate in `focus_only` mode (unless recording) and wake immediately when focused or switched to `full_realtime`.
- [x] **dashboard/stream_manager.py**: Wire `_processing_mode_service` initialization in `StreamManager.__init__` (`< 260L`, functions `<= 35L`) and wake/sync processing state when `start_recording()` is invoked.
- [x] **dashboard/services/stream_worker.py**: Integrate `ProcessingModeService.should_hibernate_camera()` in `_handle_hibernation()` and `should_run_vision_step()` in `run()` / `_process_single_frame()` (`< 290L`, functions `<= 40L`) so unfocused cameras hibernate in `focus_only` mode, all cameras pause `FrameProcessor.step()` AI when `active_tab != "live"` (unless recording or in `full_realtime`), and `capture_only`/`paused` skip `FrameProcessor.step()`.
- [x] **tests/test_step3_worker_hibernation_and_ai_gating.py**: Add unit tests (`<= 40L` per test method) exercising every branch of `StreamWorker` and `StreamPoolCoordinator` across `focus_only`, `full_realtime`, `capture_only`, `paused`, focused vs. unfocused cameras, recording overrides, and `active_tab` transitions.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 2 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step3_worker_hibernation_and_ai_gating.py"
```

---

### Milestone 3: `Capture-Only` Raw MP4 Recording, Deferred `VideoIndexer` Queue & Step 3 Integration Sign-Off *(Deferred)*
- [ ] **dashboard/services/stream_recording.py**: Update `StreamRecordingController` (`< 310L`, `<= 12` methods, functions `<= 40L`) so recordings started or finalized in `capture_only` mode write raw un-annotated frames (`annotated=False`, `step_res=None`), bypass empty `live_capture` report persistence, and auto-submit a deferred `VideoIndexer` job via `ProcessingModeService.enqueue_deferred_indexing()`, populating `deferred_job_id` and `processing_mode` in the returned status snapshot.
- [ ] **tests/test_step3_capture_only_deferred_queue.py**: Add end-to-end unit and `TestClient` integration tests (`<= 40L` per test method, using lightweight mock detector fixtures) verifying `capture_only` recording skips `FrameProcessor.step()`, writes raw MP4 frames, automatically enqueues a `VideoIndexer` job on `stop_recording()` / `POST /api/cameras/{camera_id}/record/stop`, and passes all Step 3 modularity budgets.
- [ ] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 3 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step3_*.py"
```

---

## 4. Scenario Combinations Matrix

| Real-World Scenario / Objective | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Verify ProcessingModeService & REST API** | Milestone 1 Unit Tests | `test_step3_processing_mode_api.py` | `python -m unittest discover -s tests -p "test_step3_processing_mode_api.py"` |
| **Verify Worker Hibernation & Tab AI Gating** | Milestone 2 Unit Tests | `test_step3_worker_hibernation_and_ai_gating.py` | `python -m unittest discover -s tests -p "test_step3_worker_hibernation_and_ai_gating.py"` |
| **Verify Capture-Only Recording & Deferred Queue** | Milestone 3 Unit Tests | `test_step3_capture_only_deferred_queue.py` | `python -m unittest discover -s tests -p "test_step3_capture_only_deferred_queue.py"` |
| **Verify All Step 3 Suites** | Full Step 3 Regression | `test_step3_*.py` | `python -m unittest discover -s tests -p "test_step3_*.py"` |
| **Audit Step 3 Files Against Modularity Budgets** | Static Auditor | `--max-lines 350 --max-fn-lines 40` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/services/stream_telemetry.py dashboard/services/stream_worker.py dashboard/services/processing_mode_service.py dashboard/routers/processing_mode.py dashboard/services/stream_pool_coordinator.py dashboard/services/stream_recording.py dashboard/app.py dashboard/schemas.py` |
| **Inspect Step 3 Child Plan Status** | Plan Engine CLI | `status step_3_backend_processing_modes_and_hibernation` | `python "<config_dir>/skills/frontier-architect/scripts/plan_engine.py" status step_3_backend_processing_modes_and_hibernation --root .` |
