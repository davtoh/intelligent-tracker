# Intelligent Tracker — Ideal World Architecture & Target Blueprint

> **Purpose**: Authoritative architectural reference for all future planning (`/plan`, `/frontier-architect`) and implementation sessions. Every new feature, refactor, or milestone plan MUST align with the layer boundaries, folder ownership, and invariants defined here.

---

## 1. Architectural Decisions (ADRs)

| ID | Decision | Chosen Direction | Rationale |
| :--- | :--- | :--- | :--- |
| **ADR-01** | **CLI & Dashboard Topology** | **Unified Core Engine + Thin Adapters** | Both the CLI (`intelligent_tracker/cli/`) and the Web Dashboard (`dashboard/`) wrap a single headless `PipelineEngine` and `WorldGraph` inside `intelligent_tracker/`. Eliminates dual pipeline builders and duplicated 30 FPS frame loops while keeping tests fast and UI-free. |
| **ADR-02** | **World & Spatial Representation** | **Scoped `WorldGraph` + Reactive Rules** *(retiring `MetaSpace`)* | Replaces global, unlocked `MetaSpace` weakref dictionaries (`core/spaces.py`) and unused wrappers (`high_objects.py`) with a thread-safe, instance-scoped `WorldGraph` (`intelligent_tracker/world/`). Supports multi-parent graph edges (camera, zone, entity, transition), cascading deletes/updates, and lightweight 30 FPS `Track` fast paths. |
| **ADR-03** | **Memory, Learning & Q&A** | **Hybrid Local Memory + Pluggable VLM/LLM Layer** | Core 30 FPS tracking, Re-ID (`DualModelFeatureExtractor`), bounded EMA with Locked Anchor drift guard, Active Learning, and SQLite/vector persistence remain 100% local and offline-capable. A pluggable `WorldQueryEngine` (`intelligent_tracker/memory/`) adds SQLite FTS + optional local/cloud VLM/LLM natural-language Q&A and clip understanding. |
| **ADR-04** | **Architecture Verification Gate** | **`arch-map` Static Snapshot** | Before spawning any step plan, run `diagnose.py arch-map` to verify live modularity budgets, route/CLI parity, cross-package coupling, and unused imports. |

---

## 2. Verified Current Baseline vs. Target State

*Baseline captured via `diagnose.py arch-map` (222 source files, 45,267 lines, 93 FastAPI routes):*

### Current Structural Friction
1. **Dual Pipeline Builders & Frame Loops**:
   - `intelligent_tracker/cli/pipeline_builder.py:build_pipeline()` and `dashboard/services/pipeline_factory.py:StreamPipelineFactory.build()` duplicate detector, tracker, geometry, and analytics initialization with divergent resolution parsing and missing governance (`RSACManager`, `ActiveLearningManager`, `UniversalEnrollmentManager`) in the CLI.
   - `intelligent_tracker/cli/runner.py:CliAppRunner._process_frame()` and `dashboard/services/stream_worker.py:StreamWorker._process_single_frame()` duplicate frame capture, resizing, detection, tracking, matching, and analytics stepping.
2. **Disconnected `Space` Hierarchy**:
   - `intelligent_tracker/core/spaces.py` (`Space`, `MetaSpace`) and `intelligent_tracker/high_objects.py` (`World`, `Scene`, `Area`, `Line`) are bypassed by `CameraPool`, `StreamManager`, `ScenarioManager`, `SortTracker`, `ZoneROI`, and `Tripwire`.
   - `intelligent_tracker/scenarios.py` and `intelligent_tracker/topology.py` import `Scene`, `Area`, `Line` without using them.
   - Tracked subjects are split across three uncoordinated models: `Track` (`tracker/track.py`), `Entity` (`database.py` / `SessionEntity`), and legacy `Object` (`detectors/objects.py`).
3. **Active Modularity Overruns**:
   - **Hard Ceiling (>= 500L)**: `dashboard/static/index.html` (1,688L), `intelligent_tracker/analytics.py` (667L), `intelligent_tracker/high_objects.py` (518L), `intelligent_tracker/periferials.py` (510L).
   - **Warning (350–499L) & Heavy Classes (> 12 methods)**: `dashboard/camera_pool.py` (497L, `CameraPool` 19 methods), `dashboard/static/js/video_jobs.js` (493L), `intelligent_tracker/batch.py` (486L), `dashboard/static/js/video_library.js` (471L), `intelligent_tracker/active_learning.py` (457L, 13 methods), `intelligent_tracker/scenarios.py` (438L, 12 methods), `intelligent_tracker/rsac.py` (412L, 14 methods), `intelligent_tracker/video/capture_guard.py` (`CaptureReadGuard` 16 methods), `intelligent_tracker/camera_device.py` (`CameraDeviceHandler` 15 methods).
4. **Coupling, Concurrency & Packaging Gaps**:
   - `dashboard/dependencies.py` relies on mutable module globals and `sys.modules.get("dashboard.app")` inspection for test overrides.
   - Multiple threads and routers open independent `TrackerDB` connections, risking SQLite write-lock contention under multi-camera load.
   - No `pyproject.toml` or standardized `console_scripts` entrypoints (`setup.py` uses `scripts=['main.py']`).

---

## 3. Target Layered Architecture & Dependency Flow

Dependencies MUST flow strictly downward (Adapters $\rightarrow$ Pipeline/World $\rightarrow$ Domain/Memory $\rightarrow$ Infrastructure). Lower layers NEVER import upper layers (`intelligent_tracker/` MUST NOT import `dashboard/` or `scripts/`).

```text
+-------------------------------------------------------------------------+
| Layer 5: Thin Adapters (UI, HTTP, Terminal)                             |
|  - dashboard/ (FastAPI routers -> services -> WorldEngine / Pool)       |
|  - intelligent_tracker/cli/ (local OpenCV runner + remote stream_ctl)   |
+------------------------------------+------------------------------------+
                                     | invokes
                                     v
+-------------------------------------------------------------------------+
| Layer 4: Unified Execution & Event Bus                                  |
|  - intelligent_tracker/pipeline/ (PipelineConfig, PipelineEngine,       |
|    FrameProcessor, StreamBundle)                                        |
|  - intelligent_tracker/events/ (EventBus, AlertRuleEngine, RSAC hooks)  |
+------------------------------------+------------------------------------+
                                     | updates / queries
                                     v
+-------------------------------------------------------------------------+
| Layer 3: Scoped World Graph ("Universe Physics")                        |
|  - intelligent_tracker/world/ (WorldGraph, CameraNode, ZoneNode,        |
|    TripwireNode, WorldEntity, WorldRuleEngine, GlobalCoordinateMapper)  |
+------------------------------------+------------------------------------+
                                     | persists & learns via
                                     v
+-------------------------------------------------------------------------+
| Layer 2: Identity, Learning & Semantic Memory                           |
|  - intelligent_tracker/reid/, matching/, enrollment.py,                 |
|    active_learning.py, topology.py, rsac.py                             |
|  - intelligent_tracker/memory/ (ConfidenceScorer, EventFTSIndex,        |
|    WorldQueryEngine [pluggable VLM/LLM + local fallback])               |
+------------------------------------+------------------------------------+
                                     | reads / writes via
                                     v
+-------------------------------------------------------------------------+
| Layer 1: Persistence & Hardware Abstraction                             |
|  - intelligent_tracker/repositories/ + database.py (WAL connection pool |
|    / serialized writer queue)                                           |
|  - intelligent_tracker/video/, detectors/, tracker/, geometry/          |
+-------------------------------------------------------------------------+
```

---

## 4. Target Folder Ownership & File Map

| Package / Path | Responsibility | Status / Target Rule |
| :--- | :--- | :--- |
| `pyproject.toml` | Canonical packaging & `console_scripts` (`intelligent-tracker`, `intelligent-tracker-server`, `intelligent-tracker-ctl`) | **Create in Step 1** |
| `intelligent_tracker/pipeline/` | Single SSOT `PipelineConfig`, `PipelineEngine`, `FrameProcessor`, shared FPS/backoff telemetry | **Create in Step 1** (replaces duplicate logic in `cli/pipeline_builder.py` & `dashboard/services/pipeline_factory.py`) |
| `intelligent_tracker/world/` | `WorldGraph`, `WorldNode` subclasses (`CameraNode`, `ZoneNode`, `TripwireNode`, `WorldEntity`), cascading edge lifecycle, reactive rules, global $(X, Y)$ coordinate projection | **Create in Step 2** (replaces `core/spaces.py` `MetaSpace` & `high_objects.py` in runtime) |
| `intelligent_tracker/memory/` | Long-term confidence reinforcement/decay, SQLite FTS timeline index, `WorldQueryEngine` (natural-language Q&A + pluggable VLM/LLM provider interface) | **Create in Step 5** |
| `intelligent_tracker/analytics/` | Split from `analytics.py` (667L) into `engine.py`, `heatmap.py`, `zone_stats.py` | **Refactor in Step 3** |
| `intelligent_tracker/video/` | Absorb active hardware wrappers from `periferials.py` (510L); keep `capture_guard.py` / `capture_worker.py` <= 12 methods/class | **Refactor in Step 3** |
| `intelligent_tracker/repositories/` | 10 domain mixins + pooled WAL connection/writer coordinator in `database.py` | **Harden in Step 3** |
| `intelligent_tracker/cli/` | Thin local CLI adapter (`arguments.py`, `runner.py`, `display.py`, `ctl.py`) calling `PipelineEngine` or Dashboard HTTP client | **Simplify in Step 1 & 6** |
| `dashboard/routers/` | Thin FastAPI endpoints (5–15L per handler); zero direct `TrackerDB("...")` instantiation | **Existing (enforce DI)** |
| `dashboard/services/` | Multi-camera orchestration (`stream_coordinator.py`, `camera_config_store.py` split from `camera_pool.py`), `pipeline_factory.py` delegating to `intelligent_tracker.pipeline` | **Decompose in Step 1 & 3** |
| `dashboard/dependencies.py` | FastAPI `app.state` + `dependency_overrides` container (no `sys.modules` monkeypatch lookups) | **Refactor in Step 3** |
| `dashboard/static/` | Modular HTML partials/templates + `js/` + `css/` components (< 350L/file, zero `!important`) | **Decompose in Step 3** |

---

## 5. Key Design Invariants for World Representation

1. **Scoped `WorldGraph` (No Global Mutable State)**:
   - Every `WorldGraph` instance owns its node registry, adjacency edges, and lock (`threading.RLock`). Tests create isolated `WorldGraph()` instances with zero cross-test leakage.
2. **Automatic Cascading & Reactive Propagation ("Universe Physics")**:
   - Removing a `CameraNode` automatically detaches its child `ZoneNode`s, `TripwireNode`s, and active camera-bound `WorldEntity` observations, publishing `NodeRemovedEvent` to subscribers.
   - Updating a global `WorldPolicy` (e.g., quiet hours, RSAC rule, alert sensitivity, homography matrix) propagates immediately to subscribed nodes without restarting streams.
3. **30 FPS Fast-Path Separation**:
   - `SortTracker` / `Track` operates purely on lightweight numeric arrays and bounding boxes at frame rate.
   - `WorldEntity` nodes in `WorldGraph` receive throttled/state-change updates (identification, zone entry/exit, global coordinate projection, occlusion status) so graph locking never blocks inference.
4. **Unified Track $\leftrightarrow$ WorldEntity $\leftrightarrow$ Persistent Entity Contract**:
   - `Track` = ephemeral per-camera kinematic state (`track_id`, Kalman box, velocity).
   - `WorldEntity` = live cross-camera graph node (`world_entity_id`, active `camera_id -> track_id` map, global `(X, Y)`, current zones, confidence score).
   - `Entity` (`entities` table) = durable identity record (name, category, locked anchor + bounded EMA embeddings, versioned descriptors, sightings).
5. **Offline-First Memory, Optional Semantic Intelligence**:
   - All detection, Re-ID, Active Learning, RSAC enforcement, and SQL/FTS querying MUST work offline with zero external API keys.
   - VLM/LLM providers attach behind an explicit `SemanticProvider` protocol so local models, Gemini API, or mocked test doubles swap cleanly.

---

## 6. Runtime Invariants, Migration, Privacy & Cross-Step Continuity

### 6.1 Threading, Lock Hierarchy & 30 FPS Backpressure
- **Strict Lock Acquisition Order**: `PipelineEngine` / `StreamCoordinator` -> `WorldGraph._lock (RLock)` -> `EventBus` dispatch -> `DatabaseWriterQueue`. Lower layers MUST NEVER acquire locks from upper layers (zero lock-inversion deadlocks).
- **Zero Blocking Under Lock**: Never execute SQLite writes, HTTP/webhook calls, VLM/LLM requests, `time.sleep()`, or `thread.join()` while holding `WorldGraph._lock` or `CameraPool` locks. Snapshot state under the lock, release, and perform I/O or thread joins outside.
- **Interruptible Loops & Bounded Queues**: All capture, inference, and reconnect loops use `stop_event.wait(timeout)` (defaulting `stop_event = threading.Event()`, never `None`). Frame ingestion uses bounded drop-oldest queues so slow inference or VLM queries never cause unbounded RAM growth.

### 6.2 Schema Migration, Deprecation & Edge-Case Guards
- **Idempotent SQLite Migrations**: Schema evolutions in `intelligent_tracker/database.py` (WAL mode, `WorldEntity` metadata, FTS5 timeline tables, global `(X, Y)` coordinates, confidence telemetry) MUST use versioned, idempotent `PRAGMA user_version` migrations that preserve existing `data/tracker.db` records cleanly.
- **Legacy `MetaSpace` / `high_objects.py` Transition Window**: During Step 2, keep a minimal compatibility shim or explicit deprecation boundary until all tests and `scenarios.py`/`topology.py` imports migrate to `intelligent_tracker/world/`. Never break `VideoSource` / DirectShow COM cleanup invariants on stream teardown.
- **Cross-Platform Path & Config Hygiene**: Resolve model weights, DB paths, and camera configs via `pathlib.Path` and environment overrides—never hardcode `localhost`, ports, or OS-specific path separators.

### 6.3 Privacy & VLM/LLM Data Egress Boundaries
- **Default Local-Only Operation**: Zero frame crops, embeddings, or sighting timelines leave the host unless a cloud `SemanticProvider` is explicitly configured and enabled.
- **Privacy Masking Hook**: Before any frame or crop is forwarded to an external `SemanticProvider` or webhook, apply the configured privacy filter (metadata-only mode or face/plate masking toggle).

### 6.4 Golden End-to-End Regression Fixture & Master Plan Continuity
- **Golden E2E Fixture**: Maintain a deterministic headless multi-camera synthetic/recorded-clip fixture (`detector=mock`, isolated `TemporaryDirectory` DB) that verifies identical detections, zone/tripwire events, RSAC alerts, `WorldGraph` state transitions, and DB sightings across CLI and Dashboard from Step 1 through Step 6.
- **Master Plan of Plans (`plan_engine.py`)**: Register `.TODO/world_architecture_master_roadmap.md` as the master roadmap and bind each per-step implementation plan (`.TODO/step_<N>_<slug>.md`) as a child plan via `plan_engine.py init .TODO/step_<N>_<slug>.md --parent .TODO/world_architecture_master_roadmap.md --milestone <N>` so architectural context and progress survive across conversations.


