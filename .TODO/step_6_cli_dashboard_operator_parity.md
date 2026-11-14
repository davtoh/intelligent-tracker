# Step 6 Implementation Plan: Full CLI <-> Dashboard Operator Parity & Packaging Polish

> **Parent Master Plan**: `.TODO/world_architecture_master_roadmap.md` (Step 6)  
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (ADR-01, ADR-02, ADR-04, Sections 3, 4 & 6)  
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–3 are *Deferred to Next Turn / Milestone*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map`)

Static snapshot captured via `diagnose.py arch-map --path .` prior to Step 6 design:
- **Codebase Scale**: 285 files scanned, 52,065 lines, 98 FastAPI routes.
- **Step 6 Pre-Flight Modularity Constraints ("Split-Before-You-Grow")**:
  - `dashboard/routers/cameras.py`: **326 lines** (15 routes). Appending recording routes directly would breach the 350-line soft ceiling. Recording routes MUST be placed in a dedicated router `dashboard/routers/camera_recording.py` (`< 120` lines) and mounted in `dashboard/app.py`.
  - `dashboard/dependencies.py`: **349 lines**. At the 350-line soft ceiling; do NOT append new helper functions directly into `dashboard/dependencies.py`. Reuse existing `get_camera_pool`, `get_stream_manager`, `get_db`, and `get_world_query_engine` dependencies.
  - `intelligent_tracker/pipeline/bundle.py`: **346 lines**. Near the 350-line soft ceiling; delegating `build_writer(config)` to `intelligent_tracker/video/writers.py` keeps `bundle.py` under 350 lines.
  - `intelligent_tracker/pipeline/frame_processor.py`: **279 lines** (`FrameProcessor` has 14 methods). Do NOT add new methods to `FrameProcessor`; wire live stream recording through `PipelineVideoWriter` and `StreamRecordingController` in `dashboard/services/stream_recording.py` and `dashboard/services/stream_worker.py`.
  - `intelligent_tracker/cli/ctl.py`: **280 lines** (7 subcommands). Extract `WorldGraph` and model verification CLI handlers into `intelligent_tracker/cli/ctl_world.py` (`< 220` lines) so `ctl.py` stays well below 350 lines.
- **CLI vs. Dashboard Surface Asymmetries Identified**:
  1. **Live Stream MP4 Recording**: CLI supports `--output <path>` via `build_writer(config)`, whereas Dashboard has no runtime MP4 recording control (`POST /api/cameras/{id}/record/start|stop`) or recording status telemetry.
  2. **Bounded Benchmarking & Model Verification**: CLI supports `--frames N` only when `--headless` is set, lacks structured latency/FPS benchmark telemetry (`--benchmark`), and lacks unified model verification/status commands across `intelligent-tracker`, `intelligent-tracker-ctl` (`scripts/stream_ctl.py`), and the Dashboard API (`/api/system/models`).
  3. **`WorldGraph` Live Inspection**: `WorldGraph.snapshot()` exists in `intelligent_tracker/world/graph.py`, but neither `dashboard/routers/world.py` (`GET /api/world/snapshot`, `GET /api/world/entities`) nor `intelligent-tracker-ctl` (`world` subcommand) exposes live graph topology and active `WorldEntity` inspection.
  4. **Sphinx Documentation (`documentation/`)**: Builds with 0 warnings, but `intelligent_tracker.pipeline` and `intelligent_tracker.world` are undocumented and `documentation/intelligent_tracker.rst` still references deprecated `high_objects` and `periferials` modules.

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts
1. **`PipelineConfig`, `PipelineBundle` & `PipelineEngine` (`intelligent_tracker/pipeline/`)**:
   - Preserve `PipelineConfig.output_path`, `build_writer(config)`, and `PipelineBundle.close()` deterministic release semantics.
   - `build_writer(config)` returns a `PipelineVideoWriter` compatible with `writer.write(frame)` and `writer.release()`.
2. **`StreamManager` & `CameraPool` (`dashboard/stream_manager.py`, `dashboard/camera_pool.py`)**:
   - Preserve all existing constructor signatures, MJPEG/WebSocket subscriber leases, and two-pass non-blocking shutdown (`signal_stop_all()`, `stop_all()`).
   - Active stream recording MUST prevent idle stream hibernation (`subscriber_count <= 0`) while recording is in progress and MUST flush/close the MP4 file cleanly when `stop_recording()` or `StreamManager.stop()` is invoked.
3. **`intelligent-tracker` & `intelligent-tracker-ctl` (`scripts/stream_ctl.py`)**:
   - Preserve all existing CLI flags (`--config`, `--detector`, `--tracker`, `--source`, `--headless`, `--frames`, `ask`) and `ctl` subcommands (`list`, `stats`, `evict`, `prune`, `history`, `metrics`, `ask`).
4. **Python Modernization & 12-Factor Hygiene (`AGENTS.md` §1, §4)**:
   - Zero `from __future__ import ...` imports; use Python 3.10–3.12+ native union types (`X | Y`) and built-in generics (`list[...]`, `dict[...]`).
   - Zero hardcoded hostnames, ports, or machine-local paths; resolve URLs via `--url`, `TRACKER_DASHBOARD_URL`, or `APP_URL`.

### Modularity Budgets
- Every new or modified `.py` file MUST stay **$\le 350$ lines** (hard ceiling 500L), classes **$\le 10$–$12$ methods**, functions **$\le 40$ lines**, and FastAPI route handlers **$\le 15$–$25$ lines**.

---

## 3. Target Architecture Overview

| Component | Target Files | Budget Target | Responsibility |
| :--- | :--- | :--- | :--- |
| **Shared Pipeline Video Writer** | `intelligent_tracker/video/writers.py`, `intelligent_tracker/video/__init__.py`, `intelligent_tracker/pipeline/bundle.py` | `< 180`L, $\le 8$ methods | Thread-safe `PipelineVideoWriter` with codec fallback (`mp4v`, `avc1`, `XVID`), frame/byte/duration counters, auto-resize, and atomic release |
| **Dashboard Stream Recording** | `dashboard/services/stream_recording.py`, `dashboard/stream_manager.py`, `dashboard/services/stream_worker.py` | `< 160`L, $\le 8$ methods | `StreamRecordingController` managing per-camera MP4 capture into `data/videos/`, waking hibernating streams, and preventing hibernation during recording |
| **Camera Recording API Router** | `dashboard/routers/camera_recording.py`, `dashboard/schemas.py`, `dashboard/app.py` | `< 120`L, routes 5–15L | `POST /api/cameras/{camera_id}/record/start`, `POST /api/cameras/{camera_id}/record/stop`, `GET /api/cameras/{camera_id}/record/status` |
| **CLI Bounded Benchmark & Models** | `intelligent_tracker/cli/benchmark.py`, `intelligent_tracker/cli/arguments.py`, `intelligent_tracker/cli/runner.py`, `dashboard/routers/system.py` | `< 260`L each, $\le 10$ methods | Headless/GUI `--frames N` enforcement, `--benchmark` latency/FPS report + JSON export, `--check-models` CLI flag, and `GET /api/system/models` |
| **WorldGraph API & CLI `ctl` Parity** | `dashboard/routers/world.py`, `intelligent_tracker/cli/ctl_world.py`, `intelligent_tracker/cli/ctl.py` | `< 220`L each, routes 5–15L | `GET /api/world/snapshot`, `GET /api/world/entities`, `intelligent-tracker-ctl world [summary\|entities\|snapshot]`, and `intelligent-tracker-ctl models` |
| **Sphinx Docs & Hygiene Polish** | `documentation/index.rst`, `documentation/intelligent_tracker.rst`, `documentation/deployment.rst`, `README.md` | 0 Sphinx warnings | Full code-doc sync for `pipeline`, `world`, `memory`, recording APIs, CLI parity commands, Scenario Combinations Matrix, and unused-import cleanup |

---

## 4. Phased Implementation Milestones

### Milestone 1: Shared `PipelineVideoWriter` & Dashboard Live Stream MP4 Recording (`POST /api/cameras/{id}/record/start|stop`) — *Active Execution Target*
- [x] **intelligent_tracker/video/writers.py & intelligent_tracker/video/__init__.py**: Implement thread-safe `PipelineVideoWriter` (`< 180` lines, $\le 8$ methods) wrapping `cv2.VideoWriter` with codec fallback (`mp4v` $\rightarrow$ `avc1` $\rightarrow$ `XVID`), automatic frame resize to target `(width, height)`, frame count / elapsed duration / file byte-size telemetry, optional `max_frames` / `max_duration_s` bounds, and idempotent `write()`, `release()`, and `snapshot()` methods.
- [x] **intelligent_tracker/pipeline/bundle.py & intelligent_tracker/pipeline/engine.py**: Refactor `build_writer(config)` in `bundle.py` and expose `PipelineEngine.create_writer()` to instantiate `PipelineVideoWriter` while keeping `bundle.py` $< 350$ lines.
- [x] **dashboard/services/stream_recording.py**: Create `StreamRecordingController` (`< 160` lines, $\le 8$ methods) attached to `StreamManager` to start/stop/query MP4 recording into configurable `output_dir` (default `VIDEOS_DIR`), sanitize filenames, track recording metadata (`recording_id`, `camera_id`, `filename`, `output_path`, `frames_written`, `elapsed_s`, `size_bytes`, `annotated`), and auto-finalize on stream stop.
- [x] **dashboard/stream_manager.py, dashboard/services/stream_media.py & dashboard/services/stream_worker.py**: Wire `StreamRecordingController` into `StreamManager` (`start_recording`, `stop_recording`, `get_recording_status`, `is_recording`) and `StreamWorker` (write annotated or raw frame per step, wake hibernating source on `start_recording`, prevent hibernation while `is_recording` is True, include `recording` state in telemetry, and finalize recording in `StreamManager.stop()`).
- [x] **dashboard/routers/camera_recording.py, dashboard/schemas.py & dashboard/app.py**: Create `camera_recording.py` (`< 120` lines, route handlers 5–15L) with `POST /api/cameras/{camera_id}/record/start`, `POST /api/cameras/{camera_id}/record/stop`, and `GET /api/cameras/{camera_id}/record/status` resolving streams via `CameraPool` (with fallback to primary `StreamManager`), and mount it in `dashboard/app.py`.
- [x] **tests/test_camera_recording.py**: Add unit and FastAPI `TestClient` integration tests using isolated `TemporaryDirectory()` output paths and `detector=mock` synthetic frames to verify `PipelineVideoWriter`, `StreamRecordingController`, `start`/`status`/`stop` endpoints, hibernation prevention while recording, primary-stream fallback when pool is absent, and 404/400 error branches.

**Definition of Done (DoD)**:
- [x] `POST /api/cameras/{id}/record/start`, `GET /api/cameras/{id}/record/status`, and `POST /api/cameras/{id}/record/stop` record valid MP4 files via `PipelineVideoWriter` in isolated temp directories and report accurate frame/byte counts.
- [x] All modified and new files pass `diagnose.py audit --max-lines 350 --max-fn-lines 40` and `tests/test_camera_recording.py` + `tests/test_modernization.py` pass 100%.

---

### Milestone 2: CLI Bounded Benchmarking (`--frames N` / `--benchmark`), Model Verification & `WorldGraph` Inspection Parity — *Deferred to Next Turn / Milestone*
- [x] **intelligent_tracker/cli/benchmark.py, intelligent_tracker/cli/arguments.py & intelligent_tracker/cli/runner.py**: Add `--benchmark`, `--benchmark-output <json_path>`, and `--check-models` flags; enforce `--frames N` cleanly when explicitly passed or in headless/benchmark mode; record per-frame step latency (`min_ms`, `mean_ms`, `p95_ms`, `max_ms`, `effective_fps`) in `BenchmarkCollector` (`< 160` lines) and emit structured summary / JSON report on shutdown.
- [x] **dashboard/routers/system.py**: Add `GET /api/system/models` and `POST /api/system/models/verify` (`< 25` lines added, keeping `system.py` $< 300$ lines) backed by `intelligent_tracker.detectors.model_loader.check_status()` and SHA-256 verification.
- [x] **dashboard/routers/world.py & dashboard/dependencies.py**: Add `GET /api/world/snapshot` and `GET /api/world/entities` (with optional `camera_id` and `min_confidence` query filters) to `dashboard/routers/world.py` (`< 200` lines), resolving the live `WorldGraph` from `WorldQueryEngine.world_graph` or `CameraPool.world_graph`.
- [x] **intelligent_tracker/cli/ctl_world.py & intelligent_tracker/cli/ctl.py**: Create `ctl_world.py` (`< 220` lines) implementing `world` (`summary`, `entities`, `snapshot`, `--json`, offline `--config`/`--db` or remote `--url`) and `models` (`status`, `--verify`, `--download`, `--json`, local offline or remote `--url`) subcommands, and wire them into `intelligent_tracker/cli/ctl.py` (`scripts/stream_ctl.py`).
- [x] **tests/test_cli_operator_parity.py**: Verify headless bounded benchmarking (`--frames 5 --benchmark --benchmark-output`), `--check-models`, `GET /api/system/models`, `GET /api/world/snapshot`, `GET /api/world/entities`, and `intelligent-tracker-ctl world` / `models` subcommands across local offline, remote HTTP mock, and error branches.

**Definition of Done (DoD)**:
- [x] `intelligent-tracker` and `intelligent-tracker-ctl` (`scripts/stream_ctl.py`) expose full parity for bounded benchmarking, model verification status, and `WorldGraph` inspection.
- [x] `tests/test_cli_operator_parity.py` passes 100% with isolated temporary directories and `detector=mock`.

---

### Milestone 3: Sphinx Documentation Synchronization, Unused Import Cleanup & Master Plan Sign-Off — *Deferred to Next Turn / Milestone*
- [x] **documentation/intelligent_tracker.rst, documentation/deployment.rst & documentation/index.rst**: Update Sphinx documentation to cover `intelligent_tracker.pipeline`, `intelligent_tracker.world`, `intelligent_tracker.memory`, live camera recording APIs, `WorldGraph` & model status endpoints, and `intelligent-tracker` / `intelligent-tracker-ctl` CLI commands; replace deprecated `high_objects` / `periferials` entries with `world` and `video`.
- [x] **README.md**: Synchronize CLI recipes, API endpoint summary, and the Scenario Combinations Matrix with the new `--benchmark`, `--check-models`, `intelligent-tracker-ctl world|models`, and camera recording workflows.
- [x] **intelligent_tracker/ & dashboard/**: Remove unused imports flagged by `diagnose.py arch-map --path .` across active runtime modules while preserving public `__init__.py` facade re-exports.
- [x] **tests/**: Run full regression test suite (`python -m unittest discover tests`), Sphinx strict build (`python -m sphinx -W --keep-going documentation/ documentation/_build/html/`), and `diagnose.py arch-map --path .` modularity verification.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Definition of Done (DoD)**:
- [x] Full `python -m unittest discover tests` passes 100% in headless mode (`MPLBACKEND=Agg`).
- [x] `python -m sphinx -W --keep-going documentation/ documentation/_build/html/` exits 0 with zero warnings.
- [x] `diagnose.py arch-map --path .` confirms clean modularity budgets and zero unused imports in modified files, completing Step 6 of `.TODO/world_architecture_master_roadmap.md`.

---

## 5. Scenario Combinations Matrix

| Scenario | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Live Camera MP4 Recording API** | FastAPI `TestClient` + `detector=mock` | `POST /api/cameras/cam_01/record/start` & `stop` | `python -m unittest tests/test_camera_recording.py` |
| **Headless Bounded Benchmark** | Synthetic source + mock detector | `--source synthetic --detector mock --headless --frames 10 --benchmark` | `python main.py --source synthetic --detector mock --headless --frames 10 --benchmark` |
| **Model Registry Verification (CLI)** | Local offline weights check | `--check-models` / `models --verify` | `python scripts/stream_ctl.py models --verify` |
| **WorldGraph CLI Inspection** | Remote dashboard or local config snapshot | `world summary`, `world entities`, `world snapshot --json` | `python scripts/stream_ctl.py world snapshot --json` |
| **WorldGraph & Models REST Parity** | FastAPI `TestClient` | `GET /api/world/snapshot`, `GET /api/world/entities`, `GET /api/system/models` | `python -m unittest tests/test_cli_operator_parity.py` |
| **Sphinx Documentation Build** | Strict warning-as-error HTML build | `-W --keep-going` | `python -m sphinx -W --keep-going documentation/ documentation/_build/html/` |
| **Full Regression Suite** | Headless unit + integration suite | `MPLBACKEND=Agg` | `python -m unittest discover tests` |

