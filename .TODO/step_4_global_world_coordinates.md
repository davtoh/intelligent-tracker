# Step 4 Implementation Plan: Global World Coordinates & Multi-Camera Continuity

> **Parent Master Plan**: `.TODO/world_architecture_master_roadmap.md` (Step 4)  
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (ADR-02, Sections 3, 4, 5 & 6)  
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; Milestones 2–4 are *Deferred to Next Turn / Milestone*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map`)

Measured against live workspace baseline (`260` files, `48,150` lines, `94` API routes, `474/474` tests passing):
- **Mandatory Pre-Flight Split Targets (`Split-Before-You-Grow` >= 350 lines / > 40L functions)**:
  - `intelligent_tracker/scenarios.py` (`496` lines, `ScenarioManager` has `12` methods — at the 12-method hard ceiling; `load_from_yaml` is `90` lines and `save_to_yaml` is `46` lines, exceeding the 40L function ceiling).
  - `intelligent_tracker/journey.py` (`432` lines; `TrajectoryJourneySearcher.search_journey` is `145` lines, `_build_hop` is `68` lines, and `JourneyVideoExporter.export_journey_video` is `104` lines, exceeding the 40L function ceiling; unused `typing.Union` import).
  - `intelligent_tracker/homography.py` (`347` lines, `GroundPlaneHomography` has `10` methods; `render_bev_minimap` is `136` lines, exceeding the 40L function ceiling; unused `json`, `os`, `typing.Union` imports).
- **World Graph & Multi-Camera Continuity Baseline**:
  - `intelligent_tracker/world/graph.py` (`265` lines, `WorldGraph` has `12` methods — at the 12-method ceiling; new topology transition and coordinate features must compose via focused collaborators rather than adding methods to `WorldGraph`).
  - `intelligent_tracker/world/entity_bridge.py` (`288` lines, `WorldEntityBridge` has `10` methods) and `intelligent_tracker/world/nodes.py` (`172` lines, `WorldEntity.global_xy` is currently a placeholder `tuple[float, float] | None = None`).
  - `intelligent_tracker/topology.py` (`322` lines, `CrossCameraTopology` has `10` methods) operates as a standalone table/link helper disconnected from `WorldGraph` nodes/edges and lacks global metric `(X, Y)` kinematic consistency checks or overlapping FOV deduplication.

---

## 2. Public Surface Invariants & Modularity Budgets

### Preserved Public Contracts (Zero-Regression Invariants)
- **Scenarios Contract & AST Boundary**:
  - `from intelligent_tracker.scenarios import ScenarioManager, GroundPlaneHomography, DEFAULT_SCENARIOS_PATH` remains 100% backward compatible.
  - `intelligent_tracker/scenarios.py` MUST remain a standalone module file (not shadowed by a `scenarios/` package directory) so `tests/test_world_legacy_compat.py#L35-L54` (`_collect_imported_modules(ROOT_DIR / "intelligent_tracker" / "scenarios.py")`) continues passing without modification.
- **Journey Reconstruction & Video Export Contract**:
  - `from intelligent_tracker.journey import JourneyHop, EntityJourney, TrajectoryJourneySearcher, JourneyVideoExporter` preserves all dataclass fields, `to_dict()` keys, `search_journey()`, and `export_journey_video()` signatures consumed by `dashboard/routers/topology.py`, `tests/test_journey.py`, and `tests/test_scenario_api.py`.
- **Homography & Topology Contracts**:
  - `GroundPlaneHomography` (`camera_to_ground`, `ground_to_camera`, `track_to_ground`, `transform_polygon`, `render_bev_minimap`, `to_dict`, `from_dict`) and `CrossCameraTopology` (`SpatialTransitionLink`, `ActiveSpatialPrior`, `add_link`, `remove_link`, `list_links`, `record_zone_exit`, `get_active_priors`, `compute_weighted_similarity`, `consume_prior`) preserve 100% of existing signatures and behavior.
- **Layer Direction & Lock Hierarchy**:
  - `intelligent_tracker/world/` MUST NOT import `dashboard/` or `scripts/` (`tests/test_world_legacy_compat.py#L56-L68`).
  - Lock acquisition strictly follows `PipelineEngine` $\rightarrow$ `WorldGraph._lock` $\rightarrow$ `EventBus` $\rightarrow$ `TrackerDB._lock` with zero I/O or sleeps under lock.

### Modularity & Modernization Guardrails
- **Python 3.10–3.12+**: Zero `from __future__ import ...`, native `X | Y` unions and built-in generics (`list[...]`, `dict[...]`, `tuple[...]`).
- **Quantitative Budgets**: Every new or modified `.py` file stays `< 350` lines (target `150–260` lines), `<= 10–12` methods per class, `<= 40` lines per function/method, and `<= 15–25` lines per FastAPI route handler.
- **Mathematical Annotation Preservation**: Preserve all perspective homography matrix ($3 \times 3$ $H$ and $H^{-1}$), rigid 2D transformation, and Bayesian transit prior formulas in docstrings and comments.

---

## 3. Target Architecture Overview

| Component | Target Files | Budget Target | Responsibility |
| :--- | :--- | :--- | :--- |
| **Scenarios Split** | `intelligent_tracker/scenario_storage.py` + `intelligent_tracker/scenarios.py` | Each `< 240`L; `<= 10` methods/class; `<= 35`L/fn | Decompose DB/YAML persistence & WorldGraph sync helpers out of `ScenarioManager` while keeping `scenarios.py` as canonical module. |
| **Journey Split** | `intelligent_tracker/journey_segmenter.py` + `intelligent_tracker/journey_exporter.py` + `intelligent_tracker/journey.py` | Each `< 210`L; `<= 8` methods/class; `<= 35`L/fn | Split hop segmentation, narrative building, and OpenCV MP4 synthesis out of `journey.py`; add global `(X, Y)` path support. |
| **Homography Cleanup** | `intelligent_tracker/homography.py` | `< 330`L; `<= 11` methods; `<= 35`L/fn | Remove unused imports (`json`, `os`, `Union`) and split `render_bev_minimap` (136L) into `< 35`L canvas/grid/track helpers. |
| **Global Coordinate Mapper** | `intelligent_tracker/world/coordinates.py` | `< 240`L; `<= 10` methods; `<= 35`L/fn | Fuse per-camera `GroundPlaneHomography` with camera world pose $(X_0, Y_0, \theta_{\text{yaw}})$ into unified global world $(X, Y)$ meters. |
| **World Topology Edges** | `intelligent_tracker/world/transitions.py` + `intelligent_tracker/world/nodes.py` | `< 230`L; `<= 10` methods; `<= 35`L/fn | Represent `CrossCameraTopology` links & active priors as first-class `TransitionEdgeNode`s in `WorldGraph` with Bayesian transit priors. |
| **Multi-Camera Handoff & Minimap** | `intelligent_tracker/world/handoff.py` + `intelligent_tracker/world/minimap.py` | Each `< 240`L; `<= 9` methods; `<= 35`L/fn | Unify overlapping FOV deduplication, cross-camera entity handoff, and multi-camera tactical world minimap telemetry. |

---

## 4. Phased Implementation Milestones

### Milestone 1: Mandatory Pre-Flight Split (`scenarios` & `journey` Decomposition) & Homography Cleanup *(Active Execution Target)*
- [x] **intelligent_tracker/scenario_storage.py**: Extract `WorldGraph` sync helpers (`sync_zone_to_world`, `sync_tripwire_to_world`, `remove_child_from_world`) and DB/YAML storage helpers (`load_scenarios_from_db`, `load_scenarios_from_yaml`, `save_scenarios_to_yaml` decomposed into `< 30`L section parsers for zones, tripwires, homographies, and topology) (`< 240` lines, `<= 35` lines/function).
- [x] **intelligent_tracker/scenarios.py**: Refactor `ScenarioManager` to delegate persistence and WorldGraph node sync to `scenario_storage.py`, reducing `intelligent_tracker/scenarios.py` from `496` lines to `< 230` lines (`<= 10` methods on `ScenarioManager`, every method `<= 35` lines) while preserving `ScenarioManager`, `GroundPlaneHomography`, `DEFAULT_SCENARIOS_PATH`, and AST import invariants.
- [x] **intelligent_tracker/journey_segmenter.py**: Extract pure journey segmentation helpers (`parse_sighting_timestamp`, `segment_sightings_into_hops`, `build_journey_hop`, `build_journey_narrative`) out of `intelligent_tracker/journey.py` (`< 160` lines, `<= 35` lines/function).
- [x] **intelligent_tracker/journey_exporter.py**: Extract `JourneyVideoExporter` from `intelligent_tracker/journey.py`, decomposing `export_journey_video` (104L) into focused helpers (`_write_title_segment`, `_write_transit_segment`, `_write_hop_clip_frames`, `_render_title_card`, `_render_transit_card`, `_draw_hop_hud`) so every method is `<= 35` lines (`< 210` lines total).
- [x] **intelligent_tracker/journey.py**: Reduce `intelligent_tracker/journey.py` from `432` lines to `< 170` lines (`JourneyHop`, `EntityJourney`, `TrajectoryJourneySearcher` with `search_journey` `<= 35` lines, and re-exported `JourneyVideoExporter`), and remove the unused `typing.Union` import.
- [x] **intelligent_tracker/homography.py**: Remove unused `json`, `os`, and `typing.Union` imports, and decompose `render_bev_minimap` (136L) into private helpers (`_draw_bev_grid`, `_draw_bev_zones`, `_draw_bev_tracks`, `<= 35` lines each) while preserving all perspective transform math annotations.
- [x] **tests/test_step4_preflight_budgets.py**: Add unit tests verifying line counts (`< 350`L), class method counts (`<= 12`), and function lengths (`<= 40`L) across `scenarios.py`, `scenario_storage.py`, `journey.py`, `journey_segmenter.py`, `journey_exporter.py`, and `homography.py`, plus full backward compatibility of all public exports.

**Definition of Done (DoD)**:
- [x] `intelligent_tracker/scenarios.py` (`< 230`L) and `intelligent_tracker/journey.py` (`< 170`L) are both well below the 350-line budget with zero functions `> 40` lines, and `homography.py` has zero unused imports or `> 40`L functions.
- [x] `MPLBACKEND=Agg python -m unittest tests/test_step4_preflight_budgets.py tests/test_scenarios.py tests/test_journey.py tests/test_scenario_api.py tests/test_world_legacy_compat.py` passes 100%.

---

### Milestone 2: `GlobalCoordinateMapper` & Unified `WorldEntity` Ground Plane Projection *(Deferred to Next Turn / Milestone)*
- [x] **intelligent_tracker/world/coordinates.py**: Implement `CameraWorldPose` (`camera_id`, `origin_x`, `origin_y`, `yaw_deg`, `scale`) and thread-safe `GlobalCoordinateMapper` transforming camera pixel contact points $(u, v)$ $\rightarrow$ local metric $(X_{\text{local}}, Y_{\text{local}})$ via `GroundPlaneHomography` $\rightarrow$ global world $(X_{\text{global}}, Y_{\text{global}})$ meters via 2D rigid rotation/translation:
  $$\begin{pmatrix} X_{\text{global}} \\ Y_{\text{global}} \end{pmatrix} = \begin{pmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{pmatrix} \begin{pmatrix} X_{\text{local}} \\ Y_{\text{local}} \end{pmatrix} + \begin{pmatrix} X_0 \\ Y_0 \end{pmatrix}$$
  including inverse `global_to_camera()`, `project_track_bbox()`, and `project_polygon()` (`< 240` lines, `<= 10` methods, `<= 35` lines/method).
- [x] **intelligent_tracker/world/nodes.py**: Add `global_trajectory: list[tuple[float, float, float]]` (bounded history of `(X, Y, timestamp)`) to `WorldEntity` and optional `world_pose: tuple[float, float, float] = (0.0, 0.0, 0.0)` to `CameraNode`.
- [x] **intelligent_tracker/world/_bridge_helpers.py**: Add `compute_global_track_xy()` and `append_bounded_trajectory()` helpers so `WorldEntityBridge` updates `WorldEntity.global_xy` and `WorldEntity.global_trajectory` cleanly without bloating `entity_bridge.py`.
- [x] **intelligent_tracker/world/entity_bridge.py**: Accept optional `coordinate_mapper: GlobalCoordinateMapper | None = None` (or resolve from `world_graph`) to project track bounding boxes into global `(X, Y)` coordinates on every entity sync (`< 310` lines, `<= 10` methods).
- [x] **intelligent_tracker/world/__init__.py**: Export `CameraWorldPose` and `GlobalCoordinateMapper`.
- [x] **intelligent_tracker/scenarios.py**: Register/update camera homographies on `world_graph` / `GlobalCoordinateMapper` when `save_homography` or `load_scenarios` runs.
- [x] **intelligent_tracker/journey.py** & **intelligent_tracker/journey_segmenter.py**: Add optional `global_start_xy`, `global_end_xy`, and `global_path` fields to `JourneyHop` and `EntityJourney`, computed when a `coordinate_mapper` or camera homography is available.
- [x] **tests/test_global_coordinates.py**: Add unit tests covering `GlobalCoordinateMapper` forward/inverse rigid transforms across multiple translated/rotated cameras, `WorldEntityBridge` live `global_xy` & trajectory updates, and `TrajectoryJourneySearcher` global path projection.

**Definition of Done (DoD)**:
- [x] `GlobalCoordinateMapper` accurately projects pixel tracks and polygons into unified global `(X, Y)` meters and updates `WorldEntity.global_xy` and `global_trajectory`.
- [x] `MPLBACKEND=Agg python -m unittest tests/test_global_coordinates.py tests/test_world_entity_bridge.py tests/test_journey.py` passes 100%.

---

### Milestone 3: Directed `CrossCameraTopology` Edges in `WorldGraph` & Bayesian Transit Priors *(Deferred to Next Turn / Milestone)*
- [x] **intelligent_tracker/world/nodes.py**: Add `TransitionEdgeNode(WorldNode)` representing a directed cross-camera transition link (`link_id`, `source_camera`, `source_zone`, `target_camera`, `target_zone`, `t_min`, `t_max`, `prior_boost`, `bidirectional`, `active`).
- [x] **intelligent_tracker/world/transitions.py**: Implement `WorldTransitionRegistry` managing `TransitionEdgeNode` lifecycle in `WorldGraph` (registering directed camera-to-camera edges, cascading removal when a `CameraNode` is removed, and querying active transit priors with global `(X, Y)` kinematic speed plausibility) without adding methods to `WorldGraph` (`< 230` lines, `<= 10` methods).
- [x] **intelligent_tracker/topology.py**: Integrate optional `world_transitions: WorldTransitionRegistry | None = None` into `CrossCameraTopology` so `add_link`, `remove_link`, and `record_zone_exit` synchronize with `WorldGraph`, and add kinematic speed gating when global coordinates are present (`< 340` lines, `<= 11` methods).
- [x] **intelligent_tracker/scenarios.py** & **intelligent_tracker/scenario_storage.py**: Bind `ScenarioManager.topology` to `WorldTransitionRegistry(world_graph)` when `world_graph` is provided so loaded/saved topology links materialize as `TransitionEdgeNode`s in `WorldGraph`.
- [x] **tests/test_world_transitions.py**: Add unit tests verifying `TransitionEdgeNode` creation in `WorldGraph`, bidirectional edge resolution, cascading cleanup on camera deletion, and kinematic-aware Bayesian prior boosting.

**Definition of Done (DoD)**:
- [x] `CrossCameraTopology` transitions are represented as first-class `TransitionEdgeNode`s in `WorldGraph` with Bayesian transit priors and clean cascading lifecycle.
- [x] `MPLBACKEND=Agg python -m unittest tests/test_world_transitions.py tests/test_scenarios.py tests/test_scenario_api.py` passes 100%.

---

### Milestone 4: Multi-Camera Entity Handoff, FOV Overlap Deduplication & Tactical World Minimap *(Deferred to Next Turn / Milestone)*
- [ ] **intelligent_tracker/world/handoff.py**: Implement `MultiCameraHandoffCoordinator` (`< 240` lines, `<= 9` methods) providing:
  1. **Overlapping FOV Deduplication**: Merge concurrent session `WorldEntity` nodes across overlapping cameras when global Euclidean distance $d(E_1, E_2) \le R_{\text{overlap}}$ (default `1.2` meters) and category/Re-ID similarity match, maintaining a single `WorldEntity` with multi-camera `camera_tracks`.
  2. **Cross-Camera Transit Handoff**: Match newly appearing camera tracks against active `CrossCameraTopology` priors and global `(X, Y)` velocity projections so an entity transitioning across non-overlapping or adjacent cameras preserves a single continuous `WorldEntity` ID and `global_trajectory`.
- [ ] **intelligent_tracker/world/minimap.py**: Implement `WorldTacticalMinimap` (`< 230` lines, `<= 8` methods) generating both a structured JSON telemetry payload (`build_world_minimap_telemetry`) and a top-down multi-camera OpenCV BEV canvas (`render_world_minimap`) showing calibrated camera origins, projected zones, directed transition edges, and live `WorldEntity` global `(X, Y)` positions and trails.
- [ ] **intelligent_tracker/world/__init__.py**: Export `TransitionEdgeNode`, `WorldTransitionRegistry`, `MultiCameraHandoffCoordinator`, and `WorldTacticalMinimap`.
- [ ] **dashboard/routers/topology.py**: Add `GET /api/topology/world-map` endpoint (`<= 20` lines) returning the unified global world minimap telemetry (active `WorldEntity` global `(X, Y)` coordinates, trajectories, calibrated camera poses, and directed transition links).
- [ ] **tests/test_multi_camera_handoff.py**: Add the Step 4 Golden Synthetic Two-Camera Handoff & Overlap Deduplication test suite verifying that a subject moving from `cam_01` to `cam_02` maintains one continuous `WorldEntity` ID, a continuous global `(X, Y)` path, accurate `/api/topology/world-map` telemetry, and multi-hop `TrajectoryJourneySearcher` reconstruction.
- [ ] **CHANGELOG.md**: Record milestone completion via `diagnose.py changelog add`.

**Definition of Done (DoD)**:
- [ ] Synthetic two-camera handoff and overlapping FOV tests verify a single `WorldEntity` maintains continuous ID, global `(X, Y)` path, tactical world minimap telemetry, and accurate journey reconstruction across cameras.
- [ ] Every modified/created file in Step 4 complies with the `< 350`L file, `<= 12` methods/class, and `<= 40`L function budgets (`diagnose.py arch-map --path .`).
- [ ] Full test suite (`MPLBACKEND=Agg python -m unittest discover tests`) and Sphinx docs (`python -m sphinx -W --keep-going documentation/ documentation/_build/html/`) pass with zero warnings.

---

## 5. Scenario Combinations Matrix

| Scenario | Configuration / Inputs | Expected Behavior | Verification Command |
| :--- | :--- | :--- | :--- |
| **Pre-Flight Modularity Split (`scenarios` & `journey`)** | `ScenarioManager` YAML/DB round-trip + `TrajectoryJourneySearcher` + `JourneyVideoExporter` + AST budget checks | `scenarios.py` & `journey.py` `< 240`L, all functions `<= 40`L, 100% public contract parity | `MPLBACKEND=Agg python -m unittest tests/test_step4_preflight_budgets.py tests/test_scenarios.py tests/test_journey.py tests/test_world_legacy_compat.py` |
| **Global Coordinate Projection (`GlobalCoordinateMapper`)** | 2 calibrated cameras with distinct world poses `(origin_x, origin_y, yaw_deg)` + `WorldEntityBridge` | Track bounding box bottom-centers map to unified global `(X, Y)` meters and populate `WorldEntity.global_trajectory` | `MPLBACKEND=Agg python -m unittest tests/test_global_coordinates.py` |
| **Directed Topology Edges & Bayesian Transit Priors** | `CrossCameraTopology` link `cam_01:exit_zone -> cam_02:entry_zone` synced to `WorldGraph` | `TransitionEdgeNode` registered in `WorldGraph`; zone exit spawns prior; cascading camera removal cleans edges | `MPLBACKEND=Agg python -m unittest tests/test_world_transitions.py` |
| **Overlapping FOV Multi-Camera Deduplication** | Subject simultaneously visible in `cam_01` and `cam_02` projecting to global $(X, Y)$ within `1.2m` | Both camera tracks bind to one unified `WorldEntity` (`camera_tracks={"cam_01": t1, "cam_02": t2}`) without duplicate nodes | `MPLBACKEND=Agg python -m unittest tests/test_multi_camera_handoff.py` |
| **Two-Camera Transit Handoff & Journey Continuity** | Subject exits `cam_01`, traverses transit link within $[t_{\min}, t_{\max}]$, enters `cam_02` | Continuous `WorldEntity` ID, continuous `global_trajectory`, `/api/topology/world-map` telemetry, and 2-hop `EntityJourney` with `global_path` | `MPLBACKEND=Agg python -m unittest tests/test_multi_camera_handoff.py tests/test_scenario_api.py` |
| **Full Regression & Sphinx Documentation Gate** | Complete unit/integration test suite + Sphinx HTML build | 100% tests pass; zero Sphinx warnings; clean `arch-map` budgets | `MPLBACKEND=Agg python -m unittest discover tests` |

