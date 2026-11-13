# Master Architecture & World Roadmap

> **How to use this document**: This is the ordered, dependency-aware roadmap from the current codebase to the architecture defined in `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md`.
> **Rule for Planners & Agents**: Evaluate and execute **one Step at a time**. Before creating a Step's implementation plan (`.TODO/step_<N>_<slug>.md`), run the Step's **Pre-Plan Check** (`diagnose.py arch-map`) so the plan uses live file metrics and never drifts from the target architecture.

---

## Step 0: Architecture & Integration Mapping Tool *(Completed)*
- **Goal**: Give agents and planners a deterministic, low-token static analyzer to measure modularity budgets, route/CLI parity, package coupling, and unused imports.
- **Deliverable**: `arch-map` subcommand in `system-diagnostics` (`diagnose.py arch-map --path .`).
- **Verification**:
  ```bash
  python -m unittest discover -s tests -p "test_*.py"
  ```

---

## Step 1: Unified `PipelineEngine`, Config SSOT & Package Entrypoints
- **Goal**: Eliminate duplicate pipeline creation and duplicated frame inference loops between `intelligent_tracker/cli/` and `dashboard/services/`.
- **Why First**: Every subsequent improvement (`WorldGraph`, RSAC parity, confidence scoring, telemetry) currently has to be wired twice. Unifying this first cuts future work in half.
- **Pre-Plan Evaluation Check**:
  - Run `diagnose.py arch-map --path . --json` and inspect `cli/pipeline_builder.py`, `cli/runner.py`, `dashboard/services/pipeline_factory.py`, `dashboard/services/stream_worker.py`, `dashboard/stream_manager.py`.
- **Target Scope**:
  - Create `intelligent_tracker/pipeline/` (`config.py`, `engine.py`, `frame_processor.py`, `bundle.py`).
  - Normalize resolution parsing (`"1280x720"` and `[1280, 720]`) and optional governance wiring (RSAC, ActiveLearning, Enrollment) in one shared builder.
  - Refactor `CliAppRunner` and `StreamWorker` to invoke `FrameProcessor.step()`.
  - Remove unused imports in `dashboard/stream_manager.py` flagged by `arch-map`.
  - Add `pyproject.toml` with standardized `console_scripts` (`intelligent-tracker`, `intelligent-tracker-server`, `intelligent-tracker-ctl`) while keeping `main.py` backward compatible.
- **Definition of Done**:
  - CLI and Dashboard instantiate pipelines through `intelligent_tracker.pipeline`.
  - Parity tests prove identical detector/tracker/matcher/zone behavior from one shared config in headless mode (`detector=mock`).

---

## Step 2: Scoped `WorldGraph` & Unified `WorldEntity` Lifecycle
- **Goal**: Replace the disconnected `MetaSpace` (`core/spaces.py`) and unused `high_objects.py` with a thread-safe, reactive `WorldGraph` powering the live runtime.
- **Pre-Plan Evaluation Check**:
  - Check all imports of `spaces.py`, `high_objects.py`, `scenarios.py`, `topology.py`, and `detectors/objects.py`.
- **Target Scope**:
  - Create `intelligent_tracker/world/` (`graph.py`, `nodes.py`, `rules.py`, `entity_bridge.py`).
  - Implement scoped `WorldGraph` with `CameraNode`, `ZoneNode`, `TripwireNode`, `WorldEntity`, cascading detach/delete invariants, and reactive rule propagation via `EventBus`.
  - Bridge `Track` (30 FPS kinematics) $\leftrightarrow$ `WorldEntity` (live graph state) $\leftrightarrow$ `Entity` (persistent DB identity), removing ad-hoc glue from `GalleryMatcher`.
  - Remove dead `Scene, Area, Line` imports in `scenarios.py` and `topology.py`; provide clean deprecation/compatibility adapter for legacy `high_objects.py` / `core/spaces.py` tests until retired.
- **Definition of Done**:
  - Live `CameraPool` and CLI `PipelineEngine` register cameras, zones, tripwires, and tracked entities into a `WorldGraph`.
  - Cascading node removal, multi-camera entity state updates, and rule propagation are verified by isolated unit tests.

---

## Step 3: Monolith Decomposition, DI Cleanup & SQLite Concurrency Hardening
- **Goal**: Bring every active Python/HTML/JS module under the `AGENTS.md` 350/500-line and 10/12-method ceilings and eliminate multi-thread SQLite contention and `sys.modules` DI hacks.
- **Pre-Plan Evaluation Check**:
  - Run `diagnose.py arch-map --path .` and check all `HARD (>=500L)`, `WARN (350-499L)`, and `CLASS (>12 methods)` entries.
- **Target Scope**:
  - Split `dashboard/camera_pool.py` (497L, 19 methods) into `CameraConfigStore`, `StreamPoolCoordinator`, and a thin `CameraPool` facade (< 250L).
  - Refactor `dashboard/dependencies.py` to use FastAPI `app.state` + standard `app.dependency_overrides` instead of `sys.modules.get("dashboard.app")`.
  - Split `intelligent_tracker/analytics.py` (667L) into `intelligent_tracker/analytics/` (`engine.py`, `heatmap.py`, `zone_stats.py`) with facade re-exports.
  - Consolidate/split `intelligent_tracker/periferials.py` (510L) into `intelligent_tracker/video/` and decompose `dashboard/static/index.html` (1,688L) into clean template partials/components.
  - Introduce thread-safe SQLite WAL pooling / serialized write coordinator in `intelligent_tracker/database.py` and remove direct `TrackerDB("data/tracker.db")` instantiations in routers (e.g., `dashboard/routers/topology.py`).
- **Definition of Done**:
  - Zero active runtime files >= 500 lines (except explicitly frozen/archived legacy files with deprecation notices).
  - Concurrent multi-stream sighting write stress test passes with zero `database is locked` errors.

---

## Step 4: Global World Coordinates & Multi-Camera Continuity
- **Goal**: Fuse per-camera 2D homography (`GroundPlaneHomography`) into a unified global `WorldGraph` coordinate plane so an object moving across cameras stays one continuous `WorldEntity`.
- **Pre-Plan Evaluation Check**:
  - Inspect `intelligent_tracker/homography.py`, `intelligent_tracker/topology.py`, `intelligent_tracker/journey.py`, and `dashboard/routers/topology.py`.
- **Target Scope**:
  - Add `GlobalCoordinateMapper` inside `intelligent_tracker/world/coordinates.py` mapping camera pixel feet/centroids $\rightarrow$ global world $(X, Y)$ meters.
  - Represent `CrossCameraTopology` transitions as first-class directed edges in `WorldGraph` with Bayesian transit priors.
  - Unify multi-camera entity handoff, deduplication across overlapping camera FOVs, and tactical world minimap telemetry.
- **Definition of Done**:
  - Synthetic two-camera handoff test verifies a single `WorldEntity` maintains continuous ID, global `(X, Y)` path, and accurate journey reconstruction across cameras.

---

## Step 5: Long-Term Confidence Engine & Pluggable Semantic Q&A (`WorldQueryEngine`)
- **Goal**: Transform historical sightings, Re-ID learning, and event logs into an intelligent, queryable World memory with calibrated confidence and optional VLM/LLM natural-language understanding.
- **Pre-Plan Evaluation Check**:
  - Inspect `intelligent_tracker/repositories/`, `intelligent_tracker/matching/adaptive_memory.py`, `intelligent_tracker/active_learning.py`, and `dashboard/routers/analytics.py`.
- **Target Scope**:
  - Create `intelligent_tracker/memory/` (`confidence.py`, `fts_index.py`, `query_engine.py`, `providers.py`).
  - **Confidence Engine**: Track multi-modal evidence accumulation (face + body + temporal consistency + topology prior + human confirmations) vs. drift/ambiguity decay so presence confidence improves measurably over repeated sightings.
  - **Semantic Timeline & FTS Index**: Index sightings, zone crossings, RSAC breaches, and optional clip captions in SQLite FTS5.
  - **Pluggable `WorldQueryEngine`**: Deterministic local structured/FTS parser + optional `SemanticProvider` (Gemini / local VLM/LLM) exposed via `POST /api/world/query` and CLI `intelligent-tracker ask "..."`.
- **Definition of Done**:
  - Offline natural-language/structured queries (with mock/deterministic provider) accurately retrieve sightings, presence confidence, and security timelines; optional VLM provider integration is cleanly isolated behind a protocol.

---

## Step 6: Full CLI $\leftrightarrow$ Dashboard Operator Parity & Packaging Polish
- **Goal**: Close remaining operational asymmetries between terminal workflows and web dashboard workflows.
- **Pre-Plan Evaluation Check**:
  - Run `diagnose.py arch-map --path .` to compare `cli_surfaces` vs `routes_by_file`.
- **Target Scope**:
  - Add live stream MP4 recording control in Dashboard (`POST /api/cameras/{id}/record/start|stop`) using shared `PipelineEngine` writer support.
  - Expose headless bounded benchmarking (`--frames N`), model verification/download status, and `WorldGraph` inspection commands in `scripts/stream_ctl.py` / `intelligent-tracker` CLI.
  - Update Sphinx documentation (`documentation/`) and verify zero-warning Sphinx builds.
- **Definition of Done**:
  - Full `python -m unittest discover tests` green, `python -m sphinx -W --keep-going documentation/ documentation/_build/html/` green, and `diagnose.py arch-map` reports clean modularity budgets.

