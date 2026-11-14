# Step 4 Implementation Plan: 100% SQLite `TrackerDB` Video Run SSOT, JSON Auto-Migration & Instant Live-Record Metadata Handoff

> **Parent Master Plan**: `.TODO/live_video_studio_master_roadmap.md` (Step 4)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md`
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–4 are *Deferred to Subsequent Turns*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map` & `diagnose.py audit`)

Measured against workspace baseline before edits (299 files, 54,991 lines, 107 FastAPI routes):
- `intelligent_tracker/database.py`: 123 lines (`OK < 350L`, `TrackerDB` composes 11 repository mixins).
- `intelligent_tracker/repositories/schema_manager.py`: 326 lines (`OK < 350L`, 9 methods, but `diagnose.py audit` flags 3 function-budget overruns: `_init_core_tables` [53L], `_init_spatial_tables` [58L], `_init_security_tables` [66L] `> 40L` — must be decomposed via SQL constants + `video_schema.py`).
- `dashboard/services/video_report_store.py`: 321 lines (`OK < 350L`, `save_report_run` is 61L `> 40L` budget; currently stores runs and detection streams as loose JSON files in `data/reports/`).
- `dashboard/routers/video_jobs.py`: 269 lines (`OK < 350L`, `transcode_video` is 100L `> 40L` budget — extract helper when adding `/export` route so `diagnose.py audit` passes with 0 defects).
- `dashboard/services/stream_recording.py`: 176 lines (`OK < 350L`, `StreamRecordingController` writes MP4 frames without capturing `FrameStepResult` track/detection metadata).
- `dashboard/services/stream_worker.py`: 339 lines (`OK < 350L`, 11 lines below warning ceiling — keep live-recording step hook to a 1-line `step_res` parameter pass).
- `dashboard/static/js/video_batch_reports.js`: 348 lines (`OK < 350L`, 2 lines below warning ceiling — condense template strings when adding `📥 Export JSON` action so file remains `<= 345L`).

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts (Zero-Regression Invariants)
- Existing `video_report_store` public functions (`save_report_run`, `list_report_runs`, `get_detection_stream`, `delete_report_run`, `clear_report_runs`, `resolve_base_recording_name`, `is_same_recording_alias`) preserve their exact call signatures and return payload schemas across parent and `_h264.mp4` alias filenames.
- Existing endpoints (`GET /api/videos/{filename}/reports`, `DELETE /api/videos/{filename}/reports/{run_id}`, `DELETE /api/videos/{filename}/reports`, `GET /api/videos/{filename}/reports/{run_id}/detections`, `GET /api/videos/{filename}/detections`, `POST /api/cameras/{camera_id}/record/start`, `POST /api/cameras/{camera_id}/record/stop`, `GET /api/cameras/{camera_id}/record/status`) remain 100% backward-compatible.
- Unit tests that monkeypatch `video_report_store.REPORTS_DIR` (`tests/test_video_report_store.py`, `tests/test_video_report_deletion.py`, `tests/test_progressive_stream.py`) remain 100% isolated from `data/tracker.db` via a scoped fallback DB in `os.path.dirname(os.path.abspath(REPORTS_DIR))` when no explicit `db` or test `app.state.db` is injected, leaving `os.listdir(REPORTS_DIR)` clean on `delete_report_run` / `clear_report_runs`.
- `intelligent_tracker/` never imports from `dashboard/` or `scripts/`.

### Modularity Guardrails
- `intelligent_tracker/repositories/video_schema.py` MUST remain `< 140` lines with all functions `<= 35` lines.
- `intelligent_tracker/repositories/video_run_repo.py` MUST remain `< 240` lines with `<= 10` methods on `VideoRunRepositoryMixin` and all methods `<= 35` lines.
- `intelligent_tracker/repositories/schema_manager.py` MUST be reduced below `240` lines with all methods `<= 40` lines (0 `diagnose.py audit` defects).
- `dashboard/services/video_report_store.py`, `dashboard/routers/video_jobs.py`, `dashboard/services/stream_recording.py`, `dashboard/services/stream_worker.py`, and `dashboard/static/js/video_batch_reports.js` MUST all remain `< 350` lines with every function/method `<= 40` lines.

---

## 3. Phased Implementation Milestones

### Milestone 1: `TrackerDB` Video Run Schema, `VideoRunRepositoryMixin` & `schema_manager.py` Budget Cleanup
- [x] **intelligent_tracker/repositories/video_schema.py**: Create video persistence schema module (`< 140L`, functions `<= 35L`) defining `video_runs` DDL (`run_id`, `video_filename`, `base_filename`, `run_type`, `generated_at`, `timestamp`, `source_resolution`, `source_fps`, `config_json`, `metrics_json`, `report_json`, `frame_detections_json`, indexes on `video_filename` and `base_filename`) and idempotent `apply_video_schema_migrations(cursor)` adding `video_filename TEXT DEFAULT ''` and `media_offset_sec REAL DEFAULT 0.0` to `sightings` and `world_timeline_events`.
- [x] **intelligent_tracker/repositories/schema_manager.py**: Wire `apply_video_schema_migrations(cursor)` into `_apply_schema_migrations` and extract multiline table DDL strings from `_init_core_tables`, `_init_spatial_tables`, and `_init_security_tables` into module-level SQL constants so `schema_manager.py` drops below `240L` with all methods `<= 40L`.
- [x] **intelligent_tracker/repositories/video_run_repo.py**: Create `VideoRunRepositoryMixin` (`< 240L`, `<= 10` methods, all `<= 35L`) implementing `save_video_run`, `get_video_run`, `list_video_runs`, `get_video_detection_stream`, `update_video_run_resolution`, `delete_video_run`, and `clear_video_runs` across canonical `base_filename` and alias filenames.
- [x] **intelligent_tracker/database.py**: Compose `VideoRunRepositoryMixin` into `TrackerDB` and export it in `intelligent_tracker/repositories/__init__.py` while keeping `database.py` `< 140L`.
- [x] **tests/test_step4_video_run_repo.py**: Add isolated unit tests (using `tempfile.TemporaryDirectory()`) verifying `video_runs` CRUD, alias consolidation (`clip.mp4` vs `clip_h264.mp4`), `sightings`/`world_timeline_events` `video_filename` and `media_offset_sec` columns, idempotent migrations, and `diagnose.py audit` compliance.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 1 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step4_video_run_repo.py"
```

---

### Milestone 2: `video_report_store.py` SQLite SSOT Refactor, Legacy JSON Auto-Migration & Portable JSON Export API
- [x] **dashboard/services/video_report_store.py**: Refactor `save_report_run` (splitting the 61L function into `<= 30L` helpers), `list_report_runs`, `get_detection_stream`, `delete_report_run`, and `clear_report_runs` to use `TrackerDB` as the primary SSOT, transparently auto-migrating any legacy `*_reports.json` / `*_detections.json` files in `REPORTS_DIR` into `TrackerDB` on access and adding `export_report_run_bundle(filename, run_id, db=None)` while keeping `video_report_store.py` `< 340L` and all functions `<= 40L`.
- [x] **dashboard/routers/video_jobs.py**: Add `GET /api/videos/{filename}/reports/{run_id}/export` returning a downloadable JSON attachment (`Content-Disposition: attachment`) with the run envelope + `frame_detections`, and extract `transcode_video`'s inner worker helper so `video_jobs.py` passes `diagnose.py audit` (`< 300L`, all functions `<= 40L`).
- [x] **tests/test_step4_report_ssot_and_export.py**: Add unit and FastAPI `TestClient` tests (with `tempfile.TemporaryDirectory()` isolation) verifying 100% SQLite `TrackerDB` storage, automatic migration of legacy `data/reports/*.json` files on first read, `GET /api/videos/{filename}/reports/{run_id}/export` portable JSON download, and backward compatibility with `tests/test_video_report_store.py` and `tests/test_video_report_deletion.py`.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 2 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step4_report_ssot_and_export.py"
```

---

### Milestone 3: Instant Live-Record `FrameStepResult` Metadata Handoff & Video Studio Export UI *(Deferred to Next Turn)*
- [ ] **dashboard/services/stream_recording.py**: Upgrade `StreamRecordingController` (`< 290L`, methods `<= 35L`) to accept optional `step_res` in `write_frame`, buffer time-indexed track/detection snapshots (`frame`, `time`, `source_resolution`, `tracks`, `detections`, entity sighting tallies) during recording, and automatically commit a `run_type="live_capture"` video run to `TrackerDB` via `save_report_run` when `stop()` finalizes the MP4.
- [ ] **dashboard/services/stream_worker.py**: Pass `step_res=step_res` to `recorder.write_frame(step_res.frame, annotated, step_res=step_res)` inside `_process_single_frame` and pass `db_getter` / `manager.db` into `StreamRecordingController` in `dashboard/services/stream_manager.py` while keeping `stream_worker.py` `< 345L`.
- [ ] **dashboard/static/js/video_batch_reports.js**: Add the `📥 Export JSON` download button (`#btn-export-report-run`) to `buildHistorySwitcherHtml` pointing to `/api/videos/{filename}/reports/{run_id}/export` and display a `🔴 Live Capture` badge for `run_type === 'live_capture'` runs while keeping `video_batch_reports.js` `<= 345L` (`< 350L`).
- [ ] **tests/test_step4_live_recording_handoff.py**: Add unit tests verifying that recording live frames with `FrameStepResult` tracks/detections and calling `stop()` immediately persists a `live_capture` run and detection stream in `TrackerDB`, and that `video_batch_reports.js` renders `#btn-export-report-run` and passes `diagnose.py audit`.
- [ ] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 3 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step4_live_recording_handoff.py"
```

---

### Milestone 4: End-to-End Backup/Restore Survival, Full Regression Suite & Step 4 Sign-Off *(Deferred to Next Turn)*
- [ ] **tests/test_step4_e2e_video_ssot.py**: Add end-to-end integration tests verifying: (1) live camera recording -> stop -> immediate `GET /api/videos/{filename}/reports` & `GET /api/videos/{filename}/detections` availability for "Open in Video Studio" with zero batch job run, (2) single-file SQLite `TrackerDB` backup/restore preserving all video analysis runs and detection streams without loose JSON files, and (3) non-mocked fallback branch coverage.
- [ ] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 4 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step4_*.py"
```

---

## 4. Scenario Combinations Matrix

| Real-World Scenario / Objective | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Verify Milestone 1 (`TrackerDB` Video Run Repo & Schema)** | Headless unit suite | `test_step4_video_run_repo.py` | `python -m unittest discover -s tests -p "test_step4_video_run_repo.py"` |
| **Verify Milestone 2 (SQLite SSOT, Legacy JSON Migration & Export)** | Headless unit suite | `test_step4_report_ssot_and_export.py` | `python -m unittest discover -s tests -p "test_step4_report_ssot_and_export.py"` |
| **Verify Milestone 3 (Live Recording Metadata Handoff & Export UI)** | Headless unit suite | `test_step4_live_recording_handoff.py` | `python -m unittest discover -s tests -p "test_step4_live_recording_handoff.py"` |
| **Verify Milestone 4 (Full Step 4 E2E & Backup Survival Suite)** | Headless unit suite | `test_step4_*.py` | `python -m unittest discover -s tests -p "test_step4_*.py"` |
| **Verify Legacy Report Store & Deletion Regression Suites** | Headless unit suite | `test_video_report_*.py` | `python -m unittest discover -s tests -p "test_video_report_*.py"` |
| **Static Modularity & Function Budget Audit on All Step 4 Files** | AST Auditor | `--max-lines 350 --max-fn-lines 40` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/repositories/video_schema.py intelligent_tracker/repositories/schema_manager.py intelligent_tracker/repositories/video_run_repo.py intelligent_tracker/database.py dashboard/services/video_report_store.py dashboard/routers/video_jobs.py dashboard/services/stream_recording.py dashboard/services/stream_worker.py dashboard/static/js/video_batch_reports.js --max-lines 350 --max-fn-lines 40` |
