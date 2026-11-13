# Step 1 Implementation Plan: Unified `PipelineEngine`, Config SSOT & Package Entrypoints

> **Parent Master Plan**: `.TODO/world_architecture_master_roadmap.md` (Step 1)  
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (ADR-01, ADR-04)  
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–4 are *Deferred to Subsequent Turns*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map`)

Measured against workspace baseline before edits:
- **Codebase Footprint**: 222 files, 45,267 lines, 94 API routes.
- **Verified Structural Duplications**:
  - `intelligent_tracker/cli/pipeline_builder.py` (291 lines) and `dashboard/services/pipeline_factory.py` (298 lines) independently assemble `VideoSource`, `DetectorFactory`, `TrackerFactory`, `AnalyticsEngine`, `TrackerDB`, `ReIDExtractorFactory`, `GalleryMatcher`, and `EventBus`.
  - Resolution parsing diverges: `cli/pipeline_builder.py` handles `"WIDTHxHEIGHT"` strings and `[w, h]` sequences, whereas `dashboard/services/pipeline_factory.py` only checks `isinstance(res, (list, tuple))` and silently falls back to `(640, 480)` for string inputs.
  - Governance subsystems (`RSACManager`, `ActiveLearningManager`, `UniversalEnrollmentManager`) are wired in `StreamPipelineFactory` but absent in `cli/pipeline_builder.py`.
  - `intelligent_tracker/cli/runner.py` (`_process_frame`) and `dashboard/services/stream_worker.py` (`_process_single_frame` / `_process_vision_pipeline`) duplicate resizing, detection, tracking, analytics stepping, Re-ID matching, event publishing, and rolling FPS math.
  - **Defect Discovered During Pre-Plan Audit**: `dashboard/services/stream_worker.py#L239` invokes `self.manager.tracker.update(detections, frame=frame)`, while `CentroidTracker.update` (`intelligent_tracker/tracker/centroid.py#L235`) and `SortTracker.update` (`intelligent_tracker/tracker/sort.py#L247`) accept `(detections, timestamp=None, confirmed_only=False)` without a `frame` parameter, causing a `TypeError` swallowed by `except Exception`.
  - **Unused Imports in `dashboard/stream_manager.py`**: `numpy`, `VideoSource`, `AnalyticsEngine`, `TrackerDB`, `GalleryMatcher`, `EventBus`, `CrossCameraTopology`, `RSACManager`, `ActiveLearningManager`, `UniversalEnrollmentManager`.
  - **Packaging Gap**: `setup.py` uses legacy `scripts=script_list`; no `pyproject.toml` or `console_scripts` entrypoints exist, and `scripts/` is not an importable package.

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts (Zero-Regression Invariants)
- **CLI & Root Entrypoint**: `main.py` and `intelligent_tracker/cli/__init__.py` continue exporting `build_argument_parser`, `parse_args`, `load_config`, `parse_resolution`, `PipelineContext`, `resolve_pipeline_params`, `build_pipeline`, `CliUiController`, `CliAppRunner`, `run_legacy_forms_gui`, `run_cli`, `main`.
- **Dashboard Pipeline & Stream Contracts**: `dashboard/services/pipeline_factory.py` preserves `StreamPipelineFactory` (including `_init_detector`, `build`), `StreamPipelineBundle`, and `load_stream_config`; `dashboard/stream_manager.py` preserves `StreamManager` attributes (`db`, `video_source`, `detector`, `tracker`, `analytics`, `reid_extractor`, `gallery_matcher`, `rsac_manager`, `active_learning`, `enrollment_manager`, `event_bus`, `event_pipeline`, `signal_stop()`, `start()`, `stop()`).
- **Launcher & Controller Scripts**: `scripts/run_dashboard.py` preserves `parse_args`, `resolve_config`, `preflight_port_check`, `main`; `scripts/stream_ctl.py` preserves all subcommands (`list`, `stats`, `evict`, `prune`, `history`, `metrics`) and `--url` behavior.
- **Layer Direction Rule**: `intelligent_tracker/` MUST NOT import from `dashboard/` or `scripts/`.

### Modularity & Modernization Guardrails
- **Python 3.10–3.12+**: Zero `from __future__ import ...`, zero `six`/`past`/`future` shims, native `X | Y` unions and built-in generics (`list[...]`, `dict[...]`).
- **File Ceiling**: Target 150–300 lines per new module (hard ceiling < 350 lines).
- **Class / Function Ceiling**: <= 10 methods per class; <= 35 lines per function/method.
- **Thread & Resource Safety**: Interruptible `threading.Event.wait()`, `PipelineBundle.close()` releasing writer, DB, `VideoSource`, `rule_engine`, `mqtt`, and `event_bus` cleanly without holding locks across I/O or thread joins.

---

## 3. Target Architecture (`intelligent_tracker/pipeline/` + Entrypoints)

| Module | Responsibility | Target Size |
| :--- | :--- | :--- |
| `intelligent_tracker/pipeline/__init__.py` | Public exports (`PipelineConfig`, `PipelineBundle`, `PipelineEngine`, `FrameProcessor`, `FrameStepResult`, `parse_resolution`, `load_pipeline_config`) | < 40 lines |
| `intelligent_tracker/pipeline/config.py` | SSOT config normalization (`"1280x720"` & `[1280, 720]`, class filters, DB Re-ID dim probe, CLI/Dashboard overrides) | ~180 lines |
| `intelligent_tracker/pipeline/bundle.py` | `PipelineBundle` dataclass, subsystem builder helpers, and deterministic `close()` resource cleanup | ~220 lines |
| `intelligent_tracker/pipeline/engine.py` | `PipelineEngine` factory/orchestrator (`build()`, `from_config()`, `from_cli_args()`) | ~140 lines |
| `intelligent_tracker/pipeline/frame_processor.py` | Canonical per-frame CV loop (`FrameProcessor.step()`), resize clamp, tracker update, analytics, topology exit hook, Re-ID + event dispatch, FPS tracking | ~200 lines |
| `intelligent_tracker/cli/ctl.py` | Package-owned terminal controller module (`intelligent-tracker-ctl` target), delegated by `scripts/stream_ctl.py` | ~220 lines |
| `dashboard/server.py` | Package-owned ASGI launcher module (`intelligent-tracker-server` target), delegated by `scripts/run_dashboard.py` | ~130 lines |
| `pyproject.toml` | Canonical PEP 621 metadata & `[project.scripts]` (`intelligent-tracker`, `intelligent-tracker-server`, `intelligent-tracker-ctl`) | ~60 lines |

---

## 4. Phased Implementation Milestones

### Milestone 1: Config SSOT, `PipelineBundle` & `PipelineEngine` Core *(Active Execution Target)*
- [x] **intelligent_tracker/pipeline/config.py**: Implement `parse_resolution`, `parse_classes`, `load_pipeline_config`, and `PipelineConfig` with `from_dict()` and `from_cli_args()` (preserving CLI DB embedding-dimension probing and Dashboard fallback flags).
- [x] **intelligent_tracker/pipeline/bundle.py**: Implement `PipelineBundle` with deterministic `close()` teardown and modular subsystem factory helpers (`build_video_source`, `build_detector`, `build_tracker`, `build_analytics`, `build_reid`, `build_events`, `build_governance`, `build_writer`).
- [x] **intelligent_tracker/pipeline/engine.py**: Implement `PipelineEngine` (`build`, `from_dict`, `from_cli_args`) enforcing clean error semantics (`raise_on_detector_error` vs `detector_fallback_mock`) without hard `sys.exit()` inside core library code.
- [x] **intelligent_tracker/pipeline/__init__.py**: Expose the public `intelligent_tracker.pipeline` API cleanly.
- [x] **tests/test_pipeline_config.py**: Add isolated unit tests (using `tempfile.TemporaryDirectory`) verifying `"1280x720"` vs `[1280, 720]` resolution parsing, comma-separated vs list `classes`, DB signature dim probing (`2560 -> dual`, `512 -> onnx`), `enable_governance=True|False` branches, `detector_fallback_mock=True|False` branches, and `PipelineBundle.close()` cleanup.

**Definition of Done (DoD)**:
- [x] `intelligent_tracker.pipeline` builds complete headless bundles (`detector=mock`, `source=synthetic`) for both CLI-style and Dashboard-style configs with zero `dashboard/` imports.
- [x] `MPLBACKEND=Agg python -m unittest tests/test_pipeline_config.py tests/test_modernization.py` passes 100%.

---

### Milestone 2: Canonical `FrameProcessor.step()` & CLI/Dashboard Parity Fixture *(Deferred to Next Turn)*
- [ ] **intelligent_tracker/pipeline/frame_processor.py**: Implement `FrameStepResult` and `FrameProcessor` (`step(frame, timestamp=None, max_dim=None, target_size=None)`) unifying frame resizing, `detector.detect(frame)`, `tracker.update(detections, timestamp=now)`, `analytics.update(...)`, optional `topology.record_zone_exit(...)`, `gallery_matcher.match_tracks(...)`, `EntityIdentifiedEvent` / `RestrictedEntityAlert` publishing, and rolling FPS calculation.
- [ ] **intelligent_tracker/pipeline/__init__.py**: Re-export `FrameProcessor` and `FrameStepResult`.
- [ ] **tests/test_pipeline_parity.py**: Add golden headless parity test (`detector=mock`, `source=synthetic`, isolated `TemporaryDirectory` DB) verifying identical detections, active tracks (`centroid` and `sort`), zone/tripwire counts, Re-ID identification events, and governance behavior when initialized via CLI config vs Dashboard config.

**Definition of Done (DoD)**:
- `FrameProcessor.step()` produces identical, non-empty track and analytics state across `centroid` and `sort` trackers without `tracker.update(..., frame=frame)` errors.
- `MPLBACKEND=Agg python -m unittest tests/test_pipeline_config.py tests/test_pipeline_parity.py` passes 100%.

---

### Milestone 3: Rewire `CliAppRunner`, `StreamWorker`, `StreamPipelineFactory` & `StreamManager` *(Deferred to Next Turn)*
- [ ] **intelligent_tracker/cli/pipeline_builder.py**: Delegate `resolve_pipeline_params` and `build_pipeline` to `PipelineConfig.from_cli_args()` and `PipelineEngine.from_cli_args()`, preserving `PipelineContext` compatibility and optional CLI governance wiring (`--governance` / config flag).
- [ ] **intelligent_tracker/cli/runner.py**: Refactor `CliAppRunner._process_frame` and `_shutdown` to invoke `FrameProcessor.step()` and `PipelineBundle.close()` while preserving interactive OpenCV UI controls and MQTT occupancy publishing.
- [ ] **dashboard/services/pipeline_factory.py**: Refactor `StreamPipelineFactory.build` and `_init_*` helpers to delegate to `PipelineConfig.from_dict()` and `PipelineEngine.build()`, preserving `StreamPipelineBundle` and `_init_detector` return contracts.
- [ ] **dashboard/services/stream_worker.py**: Refactor `StreamWorker._process_vision_pipeline` and FPS tracking to invoke `FrameProcessor.step()`, eliminating the broken `tracker.update(detections, frame=frame)` call and duplicated Re-ID/zone-exit logic.
- [ ] **dashboard/stream_manager.py**: Remove the 10 unused imports flagged by `diagnose.py arch-map` while preserving all public attributes and lifecycle behavior.
- [ ] **tests/test_cli_runner.py**: Add headless CLI integration tests (`--headless --frames 5 --detector mock --source synthetic`, isolated DB) exercising `build_pipeline`, `CliAppRunner.run()`, and `main.py` backward compatibility.

**Definition of Done (DoD)**:
- Neither `CliAppRunner` nor `StreamWorker` duplicates detection/tracking/analytics/Re-ID stepping logic.
- `MPLBACKEND=Agg python -m unittest tests/test_cli_runner.py tests/test_camera_detector_config.py tests/test_dashboard.py tests/test_hibernation.py tests/test_graceful_shutdown_perf.py tests/test_events_rules.py` passes 100% with zero leaked threads or test artifacts.

---

### Milestone 4: `pyproject.toml`, Package Entrypoints & Final Verification *(Deferred to Next Turn)*
- [ ] **intelligent_tracker/cli/ctl.py**: Extract terminal controller CLI (`cmd_list`, `cmd_stats`, `cmd_evict`, `cmd_prune`, `cmd_history`, `cmd_metrics`, `main`) using `$APP_URL` / `TRACKER_DASHBOARD_URL` env override fallback instead of hardcoding `localhost` blindly when configured.
- [ ] **scripts/stream_ctl.py**: Convert to a thin wrapper delegating to `intelligent_tracker.cli.ctl:main`.
- [ ] **dashboard/server.py**: Extract ASGI dashboard server launcher (`parse_args`, `resolve_config`, `preflight_port_check`, `main`) cleanly inside `dashboard/`.
- [ ] **scripts/run_dashboard.py**: Convert to a thin backward-compatible wrapper re-exporting and delegating to `dashboard.server` so `tests/test_run_dashboard.py` and `tests/test_process_supervisor.py` remain unbroken.
- [ ] **pyproject.toml**: Create canonical PEP 621 package configuration matching `requirements.txt` dependencies and defining `[project.scripts]` (`intelligent-tracker = "intelligent_tracker.cli:main"`, `intelligent-tracker-server = "dashboard.server:main"`, `intelligent-tracker-ctl = "intelligent_tracker.cli.ctl:main"`).
- [ ] **tests/test_entrypoints.py**: Verify `pyproject.toml` script targets resolve cleanly, `intelligent_tracker` never imports `dashboard` or `scripts`, and `--help` succeeds for all 3 entrypoints.
- [ ] **CHANGELOG.md**: Record milestone completion via `diagnose.py changelog add`.

**Definition of Done (DoD)**:
- Full regression suite (`MPLBACKEND=Agg python -m unittest discover tests`) passes 100%.
- `diagnose.py arch-map --path .` confirms zero unused imports in `dashboard/stream_manager.py`, zero new modularity warnings (>= 350L), and clean downward coupling (`intelligent_tracker` free of `dashboard`/`scripts` imports).

---

## 5. Scenario Combinations Matrix

| Scenario | Configuration / Inputs | Expected Behavior | Verification Command |
| :--- | :--- | :--- | :--- |
| **CLI Headless Mock Pipeline** | `--headless --frames 5 --detector mock --source synthetic --resolution 640x480` | Runs 5 frames cleanly, produces tracks & summary, exits 0, closes DB | `MPLBACKEND=Agg python -m unittest tests/test_cli_runner.py` |
| **String vs List Resolution SSOT** | `video.resolution: "1280x720"` vs `[1280, 720]` | Both normalize to `(1280, 720)` in CLI & Dashboard configs | `MPLBACKEND=Agg python -m unittest tests/test_pipeline_config.py` |
| **Tracker Parity (`centroid` & `sort`)** | `tracker.type: centroid` and `sort` via `FrameProcessor.step()` | Non-empty tracked IDs, zero `TypeError` on `update()`, matching zone/tripwire events | `MPLBACKEND=Agg python -m unittest tests/test_pipeline_parity.py` |
| **Detector Fallback vs Strict Mode** | Unknown detector with `fallback_mock=True` (Dashboard) vs `False` (CLI) | Dashboard falls back to `MockDetector`; CLI raises clean `ValueError` | `MPLBACKEND=Agg python -m unittest tests/test_pipeline_config.py tests/test_camera_detector_config.py` |
| **Governance & Re-ID Toggle** | `reid.model: "none"` vs `"color"`, `enable_governance=True|False` | `reid=none` skips extractor/matcher gracefully; governance wires RSAC/ActiveLearning/Enrollment | `MPLBACKEND=Agg python -m unittest tests/test_pipeline_config.py` |
| **Console Entrypoints & AST Audit** | `intelligent-tracker`, `intelligent-tracker-server`, `intelligent-tracker-ctl` + AST check | All 3 entrypoints resolve & render `--help`; zero `__future__` or legacy shims | `MPLBACKEND=Agg python -m unittest tests/test_entrypoints.py tests/test_modernization.py` |
| **Full Suite & Architecture Gate** | Entire workspace test discovery & static analyzer | 100% green tests; zero unused imports in `stream_manager.py` | `MPLBACKEND=Agg python -m unittest discover tests` |

