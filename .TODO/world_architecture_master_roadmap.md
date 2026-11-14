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
- [x] **Goal**: Eliminate duplicate pipeline creation and duplicated frame inference loops between `intelligent_tracker/cli/` and `dashboard/services/`.
- [x] **Why First**: Every subsequent improvement (`WorldGraph`, RSAC parity, confidence scoring, telemetry) currently has to be wired twice. Unifying this first cuts future work in half.
- [x] **Pre-Plan Evaluation Check**:
  - [x] Run `diagnose.py arch-map --path . --json` and inspect `cli/pipeline_builder.py`, `cli/runner.py`, `dashboard/services/pipeline_factory.py`, `dashboard/services/stream_worker.py`, `dashboard/stream_manager.py`.
- [x] **Target Scope**:
  - [x] Create `intelligent_tracker/pipeline/` (`config.py`, `engine.py`, `frame_processor.py`, `bundle.py`).
  - [x] Normalize resolution parsing (`"1280x720"` and `[1280, 720]`) and optional governance wiring (RSAC, ActiveLearning, Enrollment) in one shared builder.
  - [x] Refactor `CliAppRunner` and `StreamWorker` to invoke `FrameProcessor.step()`.
  - [x] Remove unused imports in `dashboard/stream_manager.py` flagged by `arch-map`.
  - [x] Add `pyproject.toml` with standardized `console_scripts` (`intelligent-tracker`, `intelligent-tracker-server`, `intelligent-tracker-ctl`) while keeping `main.py` backward compatible.
- [x] **Definition of Done**:
  - [x] CLI and Dashboard instantiate pipelines through `intelligent_tracker.pipeline`.
  - [x] Parity tests prove identical detector/tracker/matcher/zone behavior from one shared config in headless mode (`detector=mock`).

---

## Step 2: Scoped `WorldGraph` & Unified `WorldEntity` Lifecycle
- [x] **Goal**: Replace the disconnected `MetaSpace` (`core/spaces.py`) and unused `high_objects.py` with a thread-safe, reactive `WorldGraph` powering the live runtime.
- [x] **Pre-Plan Evaluation Check**:
  - [x] Check all imports of `spaces.py`, `high_objects.py`, `scenarios.py`, `topology.py`, and `detectors/objects.py`.
- [x] **Target Scope**:
  - [x] Create `intelligent_tracker/world/` (`graph.py`, `nodes.py`, `rules.py`, `entity_bridge.py`).
  - [x] Implement scoped `WorldGraph` with `CameraNode`, `ZoneNode`, `TripwireNode`, `WorldEntity`, cascading detach/delete invariants, and reactive rule propagation via `EventBus`.
  - [x] Bridge `Track` (30 FPS kinematics) $\leftrightarrow$ `WorldEntity` (live graph state) $\leftrightarrow$ `Entity` (persistent DB identity), removing ad-hoc glue from `GalleryMatcher`.
  - [x] Remove dead `Scene, Area, Line` imports in `scenarios.py` and `topology.py`; provide clean deprecation/compatibility adapter for legacy `high_objects.py` / `core/spaces.py` tests until retired.
- [x] **Definition of Done**:
  - [x] Live `CameraPool` and CLI `PipelineEngine` register cameras, zones, tripwires, and tracked entities into a `WorldGraph`.
  - [x] Cascading node removal, multi-camera entity state updates, and rule propagation are verified by isolated unit tests.

---

## Step 3: Monolith Decomposition, DI Cleanup & SQLite Concurrency Hardening
- [x] **Goal**: Bring every active Python/HTML/JS module under the `AGENTS.md` 350/500-line and 10/12-method ceilings and eliminate multi-thread SQLite contention and `sys.modules` DI hacks.
- [x] **Pre-Plan Evaluation Check**:
  - [x] Run `diagnose.py arch-map --path .` and check all `HARD (>=500L)`, `WARN (350-499L)`, and `CLASS (>12 methods)` entries.
- [x] **Target Scope**:
  - [x] Split `dashboard/camera_pool.py` (497L, 19 methods) into `CameraConfigStore`, `StreamPoolCoordinator`, and a thin `CameraPool` facade (< 250L).
  - [x] Refactor `dashboard/dependencies.py` to use FastAPI `app.state` + standard `app.dependency_overrides` instead of `sys.modules.get("dashboard.app")`.
  - [x] Split `intelligent_tracker/analytics.py` (667L) into `intelligent_tracker/analytics/` (`engine.py`, `heatmap.py`, `zone_stats.py`) with facade re-exports.
  - [x] Consolidate/split `intelligent_tracker/periferials.py` (510L) into `intelligent_tracker/video/` and decompose `dashboard/static/index.html` (1,688L) into clean template partials/components.
  - [x] Introduce thread-safe SQLite WAL pooling / serialized write coordinator in `intelligent_tracker/database.py` and remove direct `TrackerDB("data/tracker.db")` instantiations in routers (e.g., `dashboard/routers/topology.py`).
- [x] **Definition of Done**:
  - [x] Zero active runtime files >= 500 lines (except explicitly frozen/archived legacy files with deprecation notices).
  - [x] Concurrent multi-stream sighting write stress test passes with zero `database is locked` errors.

---

## Step 4: Global World Coordinates & Multi-Camera Continuity
- [x] **Goal**: Fuse per-camera 2D homography (`GroundPlaneHomography`) into a unified global `WorldGraph` coordinate plane so an object moving across cameras stays one continuous `WorldEntity`.
- [x] **Pre-Plan Evaluation Check**:
  - [x] Inspect `intelligent_tracker/homography.py`, `intelligent_tracker/topology.py`, `intelligent_tracker/journey.py`, and `dashboard/routers/topology.py`.
- [x] **Target Scope**:
  - [x] **Mandatory Pre-Flight Split (`Split-Before-You-Grow`)**: Decompose `intelligent_tracker/scenarios.py` (496L) and `intelligent_tracker/journey.py` (432L) below 350 lines before adding Global World Coordinate methods.
  - [x] Add `GlobalCoordinateMapper` inside `intelligent_tracker/world/coordinates.py` mapping camera pixel feet/centroids $\rightarrow$ global world $(X, Y)$ meters.
  - [x] Represent `CrossCameraTopology` transitions as first-class directed edges in `WorldGraph` with Bayesian transit priors.
  - [x] Unify multi-camera entity handoff, deduplication across overlapping camera FOVs, and tactical world minimap telemetry.
- [x] **Definition of Done**:
  - [x] Synthetic two-camera handoff test verifies a single `WorldEntity` maintains continuous ID, global `(X, Y)` path, and accurate journey reconstruction across cameras.

---

## Step 5: Long-Term Confidence Engine & Pluggable Semantic Q&A (`WorldQueryEngine`)
- [x] **Goal**: Transform historical sightings, Re-ID learning, and event logs into an intelligent, queryable World memory with calibrated confidence and optional VLM/LLM natural-language understanding.
- [x] **Pre-Plan Evaluation Check**:
  - [x] Inspect `intelligent_tracker/repositories/`, `intelligent_tracker/matching/adaptive_memory.py`, `intelligent_tracker/active_learning.py`, and `dashboard/routers/analytics.py`.
- [x] **Target Scope**:
  - [x] **Mandatory Pre-Flight Split (`Split-Before-You-Grow`)**: Decompose `intelligent_tracker/active_learning.py` (457L) below 350 lines before adding Long-Term Confidence Engine hooks.
  - [x] Create `intelligent_tracker/memory/` (`confidence.py`, `fts_index.py`, `query_engine.py`, `providers.py`).
  - [x] **Confidence Engine**: Track multi-modal evidence accumulation (face + body + temporal consistency + topology prior + human confirmations) vs. drift/ambiguity decay so presence confidence improves measurably over repeated sightings.
  - [x] **Semantic Timeline & FTS Index**: Index sightings, zone crossings, RSAC breaches, and optional clip captions in SQLite FTS5.
  - [x] **Pluggable `WorldQueryEngine`**: Deterministic local structured/FTS parser + optional `SemanticProvider` (Gemini / local VLM/LLM) exposed via `POST /api/world/query` and CLI `intelligent-tracker ask "..."`.
- [x] **Definition of Done**:
  - [x] Offline natural-language/structured queries (with mock/deterministic provider) accurately retrieve sightings, presence confidence, and security timelines; optional VLM provider integration is cleanly isolated behind a protocol.

---

## Step 6: Full CLI $\leftrightarrow$ Dashboard Operator Parity & Packaging Polish
- [x] **Goal**: Close remaining operational asymmetries between terminal workflows and web dashboard workflows.
- [x] **Pre-Plan Evaluation Check**:
  - [x] Run `diagnose.py arch-map --path .` to compare `cli_surfaces` vs `routes_by_file`.
- [x] **Target Scope**:
  - [x] Add live stream MP4 recording control in Dashboard (`POST /api/cameras/{id}/record/start|stop`) using shared `PipelineEngine` writer support.
  - [x] Expose headless bounded benchmarking (`--frames N`), model verification/download status, and `WorldGraph` inspection commands in `scripts/stream_ctl.py` / `intelligent-tracker` CLI.
  - [x] Update Sphinx documentation (`documentation/`) and verify zero-warning Sphinx builds.
- [x] **Definition of Done**:
  - [x] Full `python -m unittest discover tests` green, `python -m sphinx -W --keep-going documentation/ documentation/_build/html/` green, and `diagnose.py arch-map` reports clean modularity budgets.

