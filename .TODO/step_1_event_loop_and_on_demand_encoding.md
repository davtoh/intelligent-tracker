# Step 1 Implementation Plan: Asyncio Event-Loop Offloading, On-Demand JPEG Encoding & Storage Contention Fixes

> **Parent Master Plan**: `.TODO/performance_and_processing_modes_master_roadmap.md` (Step 1)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md`
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–4 are *Deferred to Subsequent Turns*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map` & `diagnose.py audit`)

Measured against workspace baseline before edits (304 files, 55,890 lines, 108 FastAPI routes):
- `dashboard/routers/tagging.py`: 119 lines (`OK < 350L`, 0 defects).
- `dashboard/routers/video_jobs.py`: 306 lines (`OK < 350L`, 0 defects).
- `dashboard/routers/streaming.py`: 136 lines (`OK < 350L`, 0 defects).
- `dashboard/services/stream_subscribers.py`: 172 lines (`OK < 350L`, 0 defects).
- `dashboard/services/stream_worker.py`: 339 lines (`OK < 350L`, 0 defects — keep `< 345L`, all functions `<= 40L`).
- `dashboard/services/video_report_migration.py`: 137 lines (`OK < 350L`, 0 defects).
- `intelligent_tracker/repositories/video_run_repo.py`: 237 lines (`OK < 350L`, 0 defects).

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts (Zero-Regression Invariants)
- `POST /api/tag/recognize-roi` and `POST /api/tag/commit` in `dashboard/routers/tagging.py` preserve their request/response Pydantic schemas (`RoiRecognizeRequest`, `TagCommitRequest`) and HTTP status codes (`400`, `404`, `503`).
- `POST /api/videos/{filename}/transcode` and `POST /api/videos/{filename}/analyze` in `dashboard/routers/video_jobs.py` preserve both `async_mode=True` and `async_mode=False` response payloads and error statuses (`404`, `409`, `500`, `504`).
- `StreamSubscriberRegistry` (`dashboard/services/stream_subscribers.py`) preserves `_subscribers: Dict[str, float]`, `subscriber_count`, `add_subscriber(sub_id: Optional[str] = None, annotated: bool = True) -> str`, `heartbeat_subscriber`, and `remove_subscriber` backward compatibility when `annotated` is omitted.
- `VideoRunRepositoryMixin.save_video_run()` (`intelligent_tracker/repositories/video_run_repo.py`) preserves its exact return dictionary shape (including `frame_detections` and `has_detections`) while skipping redundant SQLite `SELECT` + `json.loads()` deserialization of `frame_detections_json`.

### Modularity Guardrails
- `dashboard/routers/tagging.py` MUST stay `< 150` lines with route handlers `<= 25` lines.
- `dashboard/routers/video_jobs.py` MUST stay `< 325` lines with all functions `<= 40` lines.
- `dashboard/routers/streaming.py` MUST stay `< 150` lines with all functions `<= 35` lines.
- `dashboard/services/stream_subscribers.py` MUST stay `< 220` lines with all functions `<= 35` lines.
- `dashboard/services/stream_worker.py` MUST stay `< 345` lines (`< 350L` budget) with all functions `<= 40` lines.
- `dashboard/services/video_report_migration.py` MUST stay `< 180` lines with all functions `<= 35` lines.
- `intelligent_tracker/repositories/video_run_repo.py` MUST stay `< 245` lines with all functions `<= 35` lines.
- Every unit test method MUST stay `<= 40` lines (`AGENTS.md` Rule 3).

---

## 3. Phased Implementation Milestones

### Milestone 1: Asyncio Event-Loop Offloading for Tagging & Sync Video Jobs *(Active Execution Target)*
- [ ] **dashboard/routers/tagging.py**: Offload synchronous `svc.recognize_roi()`, `svc.commit_roi_tag()`, and `reload_all_galleries()` calls in `recognize_roi_endpoint` and `commit_roi_tag_endpoint` using `await asyncio.to_thread(...)` while keeping route handlers `<= 25L` and file `< 150L`.
- [ ] **dashboard/routers/video_jobs.py**: Offload synchronous `_run_sync_transcode()` in `transcode_video` and `run_sync_analytics()` in `analyze_video` using `await asyncio.to_thread(...)` when `async_mode` is `False` while keeping file `< 325L` and functions `<= 40L`.
- [ ] **tests/test_step1_event_loop_offload.py**: Add isolated unit tests (`tempfile.TemporaryDirectory()`, `<= 40L` per test method) verifying `recognize_roi_endpoint`, `commit_roi_tag_endpoint`, `transcode_video(async_mode=False)`, and `analyze_video(async_mode=False)` offload blocking execution via `asyncio.to_thread` without blocking concurrent event-loop tasks, including error branch coverage (`400`/`404`/`503`/`504`).
- [ ] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 1 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step1_event_loop_offload.py"
```

---

### Milestone 2: Subscriber-Aware On-Demand Raw & Annotated JPEG Encoding *(Deferred)*
- [ ] **dashboard/services/stream_subscribers.py**: Extend `StreamSubscriberRegistry` and `StreamSubscriberMixin` (`< 220L`, functions `<= 35L`) so `add_subscriber(sub_id=None, annotated=True)` records per-subscriber annotation mode alongside `_subscribers` lease timestamps and exposes `has_raw_subscribers` and `has_annotated_subscribers` properties.
- [ ] **dashboard/routers/streaming.py**: Pass `annotated=annotated` into `mgr.add_subscriber(sub_id, annotated=annotated)` inside `_stream_frame_generator` (`< 150L`, functions `<= 35L`).
- [ ] **dashboard/services/stream_worker.py**: Update `_process_single_frame` (`< 345L`, functions `<= 35L`) to encode raw JPEG only when `has_raw_subscribers` is `True` (or `_latest_raw_jpeg is None`) and render/encode annotated JPEG only when `has_annotated_subscribers` is `True`, `recorder.is_recording` is `True`, or `_latest_jpeg is None`.
- [ ] **tests/test_step1_on_demand_jpeg_encoding.py**: Add unit tests (`<= 40L` per test method) verifying `StreamSubscriberRegistry` raw/annotated lease tracking, TTL expiration, and `StreamWorker` skipping redundant `cv2.imencode` calls when only raw, only annotated, or only WebSocket subscribers are connected.
- [ ] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 2 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step1_on_demand_jpeg_encoding.py"
```

---

### Milestone 3: Legacy Report Migration Mtime Cache & `save_video_run` Hydration Optimization *(Deferred)*
- [ ] **dashboard/services/video_report_migration.py**: Add thread-safe mtime-aware migration cache (`_MIGRATED_REPORT_FILES` keyed by `(db_path, rep_path, mtime_ns)` plus `clear_migration_cache()` helper) so `migrate_legacy_json_for_aliases()` skips disk JSON parsing and DB lookups on repeated API requests when the file is unchanged (`< 180L`, functions `<= 35L`).
- [ ] **intelligent_tracker/repositories/video_run_repo.py**: Optimize `VideoRunRepositoryMixin.save_video_run()` (`< 245L`, functions `<= 35L`) to fetch metadata with `include_detections=False` and attach the in-memory `frame_detections` list directly instead of re-reading and `json.loads()`-parsing multi-MB `frame_detections_json` blobs from SQLite.
- [ ] **tests/test_step1_report_migration_and_repo_perf.py**: Add isolated unit tests (`tempfile.TemporaryDirectory()`, `<= 40L` per test method) verifying `migrate_legacy_json_for_aliases()` hits disk once across repeated calls, re-migrates when file mtime changes or a new DB is used, and `save_video_run()` returns hydrated `frame_detections` without redundant JSON deserialization.
- [ ] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 3 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step1_report_migration_and_repo_perf.py"
```

---

### Milestone 4: Step 1 End-to-End Verification, Modularity Audit & Master Roadmap Sign-Off *(Deferred)*
- [ ] **tests/test_step1_perf_integration.py**: Add end-to-end integration tests verifying concurrent ROI recognition + MJPEG subscriber mode switching + cached report listing under `diagnose.py audit` (all modified files `< 350L`, functions `<= 40L`).
- [ ] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 4 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step1_*.py"
```

---

## 4. Scenario Combinations Matrix

| Real-World Scenario / Objective | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Verify Asyncio Event-Loop Offload** | Milestone 1 Unit Tests | `test_step1_event_loop_offload.py` | `python -m unittest discover -s tests -p "test_step1_event_loop_offload.py"` |
| **Verify On-Demand Raw/Annotated JPEG Skip** | Milestone 2 Unit Tests | `test_step1_on_demand_jpeg_encoding.py` | `python -m unittest discover -s tests -p "test_step1_on_demand_jpeg_encoding.py"` |
| **Verify Migration Cache & Repo Save Speed** | Milestone 3 Unit Tests | `test_step1_report_migration_and_repo_perf.py` | `python -m unittest discover -s tests -p "test_step1_report_migration_and_repo_perf.py"` |
| **Verify Full Step 1 Integration** | All Step 1 Tests | `test_step1_*.py` | `python -m unittest discover -s tests -p "test_step1_*.py"` |
| **Audit Modified Files Against Modularity Budgets** | Static Auditor | `--max-lines 350 --max-fn-lines 40` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/routers/tagging.py dashboard/routers/video_jobs.py dashboard/routers/streaming.py dashboard/services/stream_subscribers.py dashboard/services/stream_worker.py dashboard/services/video_report_migration.py intelligent_tracker/repositories/video_run_repo.py` |
| **Inspect Step 1 Status** | Plan Engine CLI | `status step_1_event_loop_and_on_demand_encoding` | `python "<config_dir>/skills/frontier-architect/scripts/plan_engine.py" status step_1_event_loop_and_on_demand_encoding --root .` |
