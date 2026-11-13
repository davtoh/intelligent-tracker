# Step 2 Implementation Plan: Scoped `WorldGraph` & Unified `WorldEntity` Lifecycle

> **Parent Master Plan**: `.TODO/world_architecture_master_roadmap.md` (Step 2)  
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (ADR-02, ADR-04, Sections 5 & 6)  
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–4 are *Deferred to Next Turn / Milestone*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map`)

Measured against workspace baseline before edits (`230` files, `45,956` lines, `94` API routes):
- **Disconnected Legacy Spatial Model**:
  - `intelligent_tracker/core/spaces.py` (`MetaSpace`, `Space`, global `WeakValueDictionary` `_space_entities`) and `intelligent_tracker/high_objects.py` (`World`, `Scene`, `Area`, `Line`, 518 lines — over the 500-line hard ceiling) are bypassed by `CameraPool`, `StreamManager`, `ScenarioManager`, `SortTracker`, `ZoneROI`, and `Tripwire`.
  - `intelligent_tracker/scenarios.py#L30` and `intelligent_tracker/topology.py#L23` import `Scene, Area, Line` from `intelligent_tracker.high_objects` without using them (flagged by `diagnose.py arch-map`).
  - `intelligent_tracker/high_objects.py` is imported in production only by `intelligent_tracker/cli/runner.py#L25` (`run_legacy_forms_gui`); `tests/test_core_spaces.py` and `tests/test_core_groups.py` still test `Space`, `MetaSpace`, `Agent`, and `Group` directly.
- **Fragmented Identity Lifecycle (`Track` ↔ `SessionEntity` ↔ `Entity`)**:
  - `Track` (`intelligent_tracker/tracker/track.py`) holds ephemeral 30 FPS per-camera kinematics (`track_id`, `bbox`, `centroid`, `velocity`).
  - `GalleryMatcher` (`intelligent_tracker/matching/gallery.py`, 423 lines) dynamically monkeypatches `track.entity_id`, `track.entity_name`, `track.entity_category`, `track.reid_score`, `track.identity_label` and coordinates ad-hoc sighting debouncing alongside `SessionGalleryManager` (`SessionEntity`).
  - `TrackerDB` (`entities`, `entity_signatures`, `sightings`) holds durable DB identities without a live cross-camera `WorldEntity` node unifying active camera-to-track bindings.
- **No Shared Live World Graph**:
  - `dashboard/camera_pool.py` (497 lines, `CameraPool` 19 methods — near 500L ceiling) owns `streams` and `camera_configs` with no scoped `WorldGraph` tracking cameras, zones, tripwires, or live cross-camera entities.

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts (Zero-Regression Invariants)
- **Legacy `core.spaces` & `high_objects` Compatibility**: `intelligent_tracker/core/spaces.py` (`MetaSpace`, `Space`, `deco_name`), `intelligent_tracker/core/agents.py` (`Agent`), `intelligent_tracker/core/groups.py` (`Group`), and `intelligent_tracker/high_objects.py` (`World`, `Scene`, `Area`, `Line`) remain functional until retired so `tests/test_core_spaces.py`, `tests/test_core_groups.py`, `tests/test_core_efficiency.py`, and `CliAppRunner` legacy GUI fallback stay unbroken.
- **GalleryMatcher & Tracker Contracts**: `GalleryMatcher.match_track`, `match_tracks`, `reassign_track`, `_identified_tracks`, and `Track` attributes (`entity_id`, `entity_name`, `entity_category`, `reid_score`, `identity_label`) continue working identically whether a `WorldEntityBridge` is attached or omitted (`world_bridge=None`).
- **Pipeline, CLI & Dashboard Contracts**: `PipelineEngine.build`, `PipelineBundle`, `FrameProcessor.step`, `StreamPipelineFactory.build`, `StreamManager`, and `CameraPool` preserve all existing signatures and attributes; `world_graph` parameters are optional with safe scoped defaults.
- **Layer Direction Rule**: `intelligent_tracker/world/` MUST NOT import from `dashboard/` or `scripts/`.

### Modularity, Threading & Modernization Guardrails
- **Python 3.10–3.12+**: Zero `from __future__ import ...`, zero `six`/`past`/`future` shims, native `X | Y` unions and built-in generics (`list[...]`, `dict[...]`).
- **File & Class Budgets**: New files under `intelligent_tracker/world/` MUST stay under **350 lines** (target 150–300 lines), `<= 10` methods per class, `<= 35–40` lines per function. Do NOT grow `dashboard/camera_pool.py` (currently 497L) or `intelligent_tracker/matching/gallery.py` (currently 423L) toward 500 lines—delegate via thin hooks.
- **Strict Lock Hierarchy & Zero I/O Under Lock**: `PipelineEngine / StreamCoordinator -> WorldGraph._lock (RLock) -> EventBus dispatch`. Never execute `EventBus.publish()`, SQLite writes, HTTP calls, `time.sleep()`, or `thread.join()` while holding `WorldGraph._lock`; collect event snapshots under lock and publish after releasing it.
- **30 FPS Fast-Path Separation**: `SortTracker` / `CentroidTracker` remain lock-free on numeric arrays; `FrameProcessor.step()` pushes state-change or throttled updates to `WorldGraph` so inference never stalls.

---

## 3. Target Architecture (`intelligent_tracker/world/`)

| Module | Responsibility | Target Size |
| :--- | :--- | :--- |
| `intelligent_tracker/world/__init__.py` | Public exports (`WorldGraph`, `WorldNode`, `CameraNode`, `ZoneNode`, `TripwireNode`, `WorldEntity`, `WorldPolicy`, `WorldRuleEngine`, `WorldEntityBridge`, world events) | < 60 lines |
| `intelligent_tracker/world/nodes.py` | Typed immutable-id graph node dataclasses (`WorldNode`, `CameraNode`, `ZoneNode`, `TripwireNode`, `WorldEntity`, `WorldPolicy`) and snapshot serialization | ~220 lines |
| `intelligent_tracker/world/events.py` | Typed `BaseEvent` subclasses (`NodeAddedEvent`, `NodeRemovedEvent`, `EntityStateChangedEvent`, `WorldPolicyUpdatedEvent`) | ~100 lines |
| `intelligent_tracker/world/graph.py` | Scoped, `RLock`-protected `WorldGraph` registry, parent-child adjacency, cascading `remove_camera()`, policy state, and outside-lock `EventBus` emission | ~290 lines |
| `intelligent_tracker/world/rules.py` | `WorldRuleEngine` subscribing to `EventBus` (`ZoneEvent`, `TripwireCrossEvent`, `EntityIdentifiedEvent`, `RestrictedEntityAlert`, `WorldPolicyUpdatedEvent`) to propagate reactive state without stream restarts | ~170 lines |
| `intelligent_tracker/world/entity_bridge.py` | `WorldEntityBridge` unifying `Track` (30 FPS kinematics) ↔ `WorldEntity` (live graph node) ↔ `Entity` (persistent `TrackerDB` identity), deduplicating `GalleryMatcher` ad-hoc glue | ~210 lines |

---

## 4. Phased Implementation Milestones

### Milestone 1: Scoped `WorldGraph`, Typed `WorldNode`s & Cascading Lifecycle *(Active Execution Target)*
- [x] **intelligent_tracker/world/nodes.py**: Define `WorldNode`, `CameraNode`, `ZoneNode`, `TripwireNode`, `WorldEntity` (tracking `world_entity_id`, `entity_id`, `session_id`, `name`, `category`, `confidence`, `camera_tracks: dict[str, int]`, `active_zones: dict[str, set[str]]`, `global_xy`, `last_seen`), and `WorldPolicy` (`quiet_hours`, `dwell_override`, `alert_sensitivity`, `extra`), with clean `to_dict()` snapshots.
- [x] **intelligent_tracker/world/events.py**: Define typed `BaseEvent` subclasses (`NodeAddedEvent`, `NodeRemovedEvent`, `EntityStateChangedEvent`, `WorldPolicyUpdatedEvent`) cleanly inheriting `intelligent_tracker.events.types.BaseEvent`.
- [x] **intelligent_tracker/world/graph.py**: Implement instance-scoped, `threading.RLock`-guarded `WorldGraph(event_bus=None)` supporting camera/zone/tripwire/entity registration, parent-child edge lookup, cascading `remove_camera()` (detaching child zones, tripwires, and camera-bound entity tracks/zones), `set_policy()` / `get_policy()`, thread-safe `snapshot()`, and strictly outside-lock `EventBus` dispatch.
- [x] **intelligent_tracker/world/__init__.py**: Export Milestone 1 world contracts cleanly.
- [x] **tests/test_world_graph.py**: Add isolated unit tests verifying multi-instance `WorldGraph` isolation (zero global `MetaSpace` state leakage), cascading `remove_camera()` detachment of zones/tripwires/entity camera bindings, `WorldPolicy` propagation events, concurrent multi-thread read/write safety, and outside-lock `EventBus` publishing (handler re-entering `WorldGraph` without deadlock).

**Definition of Done (DoD)**:
- [x] Two independent `WorldGraph()` instances operate concurrently with zero shared global state.
- [x] `MPLBACKEND=Agg python -m unittest tests/test_world_graph.py tests/test_modernization.py` passes 100%, with all new files `< 350` lines and zero `dashboard`/`scripts` imports.

---

### Milestone 2: `WorldRuleEngine` & `WorldEntityBridge` (`Track` ↔ `WorldEntity` ↔ `Entity`) *(Deferred to Next Turn / Milestone)*
- [ ] **intelligent_tracker/world/rules.py**: Implement `WorldRuleEngine(world_graph, event_bus)` subscribing to `ZoneEvent`, `TripwireCrossEvent`, `EntityIdentifiedEvent`, `RestrictedEntityAlert`, and `WorldPolicyUpdatedEvent` to reactively update zone occupancy, entity restriction flags, and policy parameters in `WorldGraph`, with an explicit `start()`/`stop()` lifecycle.
- [ ] **intelligent_tracker/world/entity_bridge.py**: Implement `WorldEntityBridge(world_graph, db=None)` providing `sync_track_identification()`, `sync_session_track()`, `sync_camera_tracks()` (state-change/throttled updates for 30 FPS efficiency), `reassign_track()`, and `prune_stale_tracks()` so `Track` ↔ `WorldEntity` ↔ `Entity` mapping has one SSOT.
- [ ] **intelligent_tracker/matching/gallery.py**: Add optional `world_bridge: WorldEntityBridge | None = None` support to `GalleryMatcher`, delegating track identification, session fallback linkage, and manual reassignment through `WorldEntityBridge` when attached while preserving 100% existing behavior when `world_bridge=None` (net line delta `<= 0` or `< 430` lines).
- [ ] **intelligent_tracker/world/__init__.py**: Re-export `WorldRuleEngine` and `WorldEntityBridge`.
- [ ] **tests/test_world_entity_bridge.py**: Add isolated unit tests (with `tempfile.TemporaryDirectory` `TrackerDB`) verifying `Track` ↔ `WorldEntity` ↔ `Entity` convergence across two cameras for the same `entity_id`, session-to-persistent promotion, `GalleryMatcher.reassign_track()` sync, stale track cleanup, and `WorldRuleEngine` reactive policy/occupancy updates via `EventBus`.

**Definition of Done (DoD)**:
- [ ] Cross-camera detections for the same persistent `Entity` converge onto one `WorldEntity` node with accurate per-camera `camera_tracks` and `active_zones` bindings.
- [ ] `MPLBACKEND=Agg python -m unittest tests/test_world_graph.py tests/test_world_entity_bridge.py tests/test_reid_matcher.py` passes 100%.

---

### Milestone 3: Live `PipelineEngine`, `FrameProcessor`, `CliAppRunner` & `CameraPool` Integration *(Deferred to Next Turn / Milestone)*
- [ ] **intelligent_tracker/pipeline/bundle.py**: Add `world_graph`, `world_bridge`, and `world_rule_engine` fields to `PipelineBundle`, register camera/zones/tripwires via `build_world()`, and stop `world_rule_engine` cleanly in `PipelineBundle.close()`.
- [ ] **intelligent_tracker/pipeline/engine.py**: Accept optional `world_graph: WorldGraph | None = None` in `PipelineEngine.build()`, `from_dict()`, and `from_cli_args()` (instantiating a scoped `WorldGraph` when omitted) and wire `world_bridge` into `GalleryMatcher` and `FrameProcessor`.
- [ ] **intelligent_tracker/pipeline/frame_processor.py**: Push state-change / throttled track & zone updates into `world_bridge` inside `FrameProcessor.step()` without blocking 30 FPS detection/tracking.
- [ ] **dashboard/services/pipeline_factory.py**: Thread optional `world_graph` through `StreamPipelineFactory.build()` and `StreamPipelineBundle` into `PipelineEngine.build()`.
- [ ] **dashboard/stream_manager.py**: Accept optional `world_graph: WorldGraph | None = None`, forward it to `StreamPipelineFactory.build()`, and store `self.world_graph` / `self.world_bridge`.
- [ ] **dashboard/camera_pool.py**: Own a scoped `self.world_graph = WorldGraph()` on `CameraPool` (keeping net line count `< 500` via concise delegation), pass it to `StreamManager`, and invoke `self.world_graph.remove_camera(camera_id)` outside `self._lock` in `remove_camera()`.
- [ ] **tests/test_world_pipeline_integration.py**: Add headless end-to-end tests (`detector=mock`, `source=synthetic`, isolated `TemporaryDirectory` DB & `CameraPool(autostart=False)`) verifying CLI `PipelineEngine` and Dashboard `CameraPool` register cameras, zones, tripwires, and tracked `WorldEntity` nodes into scoped `WorldGraph`s, and `CameraPool.remove_camera()` triggers cascading removal.

**Definition of Done (DoD)**:
- [ ] Both CLI (`PipelineEngine`) and Dashboard (`CameraPool` + `StreamManager`) run against live scoped `WorldGraph` instances with cascading node teardown on camera removal.
- [ ] `MPLBACKEND=Agg python -m unittest tests/test_world_pipeline_integration.py tests/test_pipeline_parity.py tests/test_cli_runner.py tests/test_dashboard.py tests/test_graceful_shutdown_perf.py` passes 100%.

---

### Milestone 4: Dead Import Cleanup, Legacy Compatibility & Final Sign-Off *(Deferred to Next Turn / Milestone)*
- [ ] **intelligent_tracker/scenarios.py**: Remove dead `from intelligent_tracker.high_objects import Scene, Area, Line` import (and any verified unused imports such as `cv2`, `json`, `numpy`), and add optional `world_graph` sync hooks in `save_zone`, `delete_zone`, `save_tripwire`, `delete_tripwire`.
- [ ] **intelligent_tracker/topology.py**: Remove dead `from intelligent_tracker.high_objects import Scene, Area, Line` import.
- [ ] **intelligent_tracker/core/spaces.py**: Document legacy compatibility boundary (`MetaSpace`, `Space`) pointing new code to `intelligent_tracker.world.WorldGraph` while preserving existing tests (`tests/test_core_spaces.py`, `tests/test_core_groups.py`, `tests/test_core_efficiency.py`).
- [ ] **intelligent_tracker/high_objects.py**: Add deprecation notice marking `World`, `Scene`, `Area`, `Line` as legacy Matplotlib compatibility adapters until `run_legacy_forms_gui` is retired.
- [ ] **tests/test_world_legacy_compat.py**: Verify via AST parsing that `scenarios.py` and `topology.py` no longer import `high_objects`, `intelligent_tracker.world` has zero `dashboard`/`scripts` imports, and legacy `Space`/`World` compatibility remains intact.
- [ ] **CHANGELOG.md**: Record milestone completion via `diagnose.py changelog add`.

**Definition of Done (DoD)**:
- [ ] Full test suite (`MPLBACKEND=Agg python -m unittest discover tests`) passes 100% with zero leaked threads or test artifacts.
- [ ] `diagnose.py arch-map --path .` confirms dead `high_objects` imports removed from `scenarios.py` and `topology.py`, all new `world/` modules `< 350` lines, and `dashboard/camera_pool.py` `< 500` lines.

---

## 5. Scenario Combinations Matrix

| Scenario | Configuration / Inputs | Expected Behavior | Verification Command |
| :--- | :--- | :--- | :--- |
| **Scoped Graph Isolation** | Two separate `WorldGraph()` instances registering identical camera/zone IDs (`cam_01`, `entry`) | Zero naming collisions or cross-graph state leakage | `MPLBACKEND=Agg python -m unittest tests/test_world_graph.py` |
| **Cascading Camera Removal** | `cam_01` owns `ZoneNode` + `TripwireNode` + `WorldEntity` binding; call `remove_camera("cam_01")` | Child zone/tripwire detached, `cam_01` stripped from `WorldEntity`, `NodeRemovedEvent` emitted outside lock | `MPLBACKEND=Agg python -m unittest tests/test_world_graph.py` |
| **Reentrant EventBus Safety** | Subscriber queries `world_graph.snapshot()` inside `NodeAddedEvent` callback on another thread | Zero `RLock` deadlock or missed event dispatch | `MPLBACKEND=Agg python -m unittest tests/test_world_graph.py` |
| **Multi-Camera Entity Convergence** | Same DB `entity_id=7` matched on `cam_01` (`track 1`) and `cam_02` (`track 4`) via `WorldEntityBridge` | Single `WorldEntity` holds `camera_tracks={"cam_01": 1, "cam_02": 4}` | `MPLBACKEND=Agg python -m unittest tests/test_world_entity_bridge.py` |
| **Pipeline & CameraPool Parity** | Headless `PipelineEngine.build(detector="mock")` and `CameraPool(autostart=False)` | Both register camera, zones, tripwires, and tracked `WorldEntity` nodes into `WorldGraph` | `MPLBACKEND=Agg python -m unittest tests/test_world_pipeline_integration.py` |
| **Dead Import & Legacy Compat** | AST scan of `scenarios.py` & `topology.py` + `test_core_spaces.py` + `test_core_groups.py` | Zero `high_objects` imports in `scenarios`/`topology`; legacy tests pass 100% | `MPLBACKEND=Agg python -m unittest tests/test_world_legacy_compat.py tests/test_core_spaces.py tests/test_core_groups.py` |
| **Full Suite & Architecture Gate** | Entire workspace test discovery + static analyzer | 100% green tests; zero `__future__` imports; clean modularity budgets | `MPLBACKEND=Agg python -m unittest discover tests` |

