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
| **ADR-05** | **Frontend Component Reuse, Zero-CLS Stability & Multi-Camera AI Visibility** | **Single Reusable UI Components + Variant Parameters + Ask-First Governance** | Reuse existing `dashboard/static/js/` and `dashboard/static/partials/` components (e.g., unified `OverlayControlBar` with `live`/`scrubber` presentation variants; unified `UnifiedCanvasOverlay` across 1x1, `2x2`/`3x3`/`4x4` grid tiles, and scrubber). Keep one canonical working button per action per view; reserve stable HUD badge slots with `>= 8px` gaps, `tabular-nums`, hysteresis smoothing, and ellipsis truncation; stream throttled `/ws/multiview` JSON telemetry so AI-active grid tiles draw client-side boxes, live FPS/tracks, pool-wide alerts, and a per-tile AI toggle (`armed`). Explicitly ask the user before creating any new UI component that overlaps an existing one. |
| **ADR-06** | **Dual-Clock Domain Contract & Pool-Scoped Singleton Ownership** | **Monotonic Scheduler/Lag vs. Wall-Clock Domain Epoch + Pool Singletons** | Strictly separate `time.monotonic()` (scheduler intervals, FPS pacing, lag deltas, cooldowns, timeouts) from Unix wall-clock epoch `time.time()` (all `FrameProcessor.step()`, `RSACSchedule`, `TrackerDB` sightings, `EventFTSIndex`, `ConfidenceEngine`, `EventBus` alerts, and `ThumbnailCache.capture_ts_ms`). Offline `VideoIndexer` stamps `base_epoch + video_ts` while preserving `video_filename` and `media_offset_sec` in sightings, FTS, and `WorldQueryEngine` citations. `CameraPool` owns shared singleton `EventBus`, `WorldGraph`, `ConfidenceEngine`, and `EventFTSIndex` instances bound to `app.state` and injected into every `StreamManager`, preserving homography/scenarios across restarts. |
| **ADR-07** | **Persistent-Entity Tracking, Occlusion Coasting & WorldGraph Ownership** | **Kalman/SORT Coasting + Class/Appearance Matching + `CARRIES`/`OWNED_BY` Graph Edges** | Default to Kalman/SORT coasting (`state: confirmed | coasting | occluded`, ~1.5s grace) so short detector dropouts never purge `GalleryMatcher` Re-ID state or `WorldGraph` bindings; enforce class-consistency + appearance-assisted matching; represent person+bag associations via `WorldGraph` `CARRIES`/`OWNED_BY` edges for dropped/unattended item detection. |
| **ADR-08** | **Supervised Re-ID Learning, Negative Feedback, Badge CRUD & Collision Guard** | **Draw-Anywhere ROI + Negative Exemplars + Dynamic Badges + Similarity Guard** | Support draw-anywhere ROI teaching and click-to-correct/discourage negative exemplars; manage Semantic Category Badges dynamically via `/api/rsac/categories` across all modals/filters; run a pre-enrollment cosine-similarity collision check against `db.get_gallery_embeddings()` (Merge vs. Create New); separate YOLO COCO `Detector Classes` from `Tracked Gallery Entities/Categories`. |
| **ADR-09** | **Real-Time Analytics Flows, Calibrated Tactical Minimap & Bidirectional Active Learning** | **Time-Bucketed Flows + Reused Canvas/Scrubber + Prefix Autocomplete + Bidirectional Review** | Replace synthetic traffic-flow math with SQLite time-bucketed flow queries + pagination + "Back to Live"; reuse `UnifiedCanvasOverlay`/`OverlayControlBar` in `#alerts` and extracted `scrubber-timeline-slider` in Enrollment; wire `WorldTacticalMinimap` (`/api/topology/world-map`) + `<video>` stage in `#studio`; provide prefix `/api/entities/suggest` autocomplete in `#journey` and bidirectional Video Studio <-> Review & Learn sync. |
| **ADR-10** | **Canonical `DualModel` Re-ID, Auto-Sighting Crops & Retroactive Run Relabeling** | **Unified `DualModelFeatureExtractor` + Throttled Sighting Crops + Run/Replay Relabeling** | Enforce a single canonical embedding family (`DualModelFeatureExtractor`) across enrollment, live streams (`probe_db_reid=True`), `VideoIndexer`, and `RoiRecognitionService` (with crop-based dimension backfill) so enrolled entities match consistently everywhere. Persist throttled bounded crops for automatic live/batch sightings (with entity avatar fallback), and retroactively re-label cached `video_runs.frame_detections_json` + `CachedReplayProvider` on identity edits. |
| **ADR-11** | **Responsive Modal Ergonomics, `MediaEmptyState`, Unified Category SSOT & Two-State ROI UX** | **Wide Adaptive Resizable Dialogs + Shared `MediaEmptyState` + `custom_categories` Registry + Two-State Tag Modal** | Size complex multi-pane dialogs with adaptive fluid grids (`clamp`, `resize: both`, `@container` fallback, `min-width: 0`, `.form-row`/`.col-*`), unify Enrollment `<video>` + canvas scrubbing at true FPS with explicit source context, replace raw `alt` broken-image states via shared `MediaEmptyState`, unify all Security Categories & Badges onto `/api/rsac/categories` with clean universal defaults, and split `#modal-tag-entity` into clear Known Match vs. New Subject states with non-closing candidate `✕` suppression. |
| **ADR-12** | **End-to-End Source Traceability, Stateful Alert Lifecycle & In-Place Studio Editing** | **Paginated Source-Linked `#timeline` + Peak/Hotspot `#analytics` + Stateful `#alerts` + In-Place `#studio` Editing** | Add `offset` pagination & source deep-links to `#timeline`, X/Y scales + peak/`32x24` hotspot drill-downs to `#analytics`, `is_read` unread counters + populated facets + acknowledge/delete/export lifecycle to `#alerts` (making `configs/alert_demo.yaml` strictly opt-in), and non-destructive `PUT` in-place zone/tripwire vertex editing, interactive 2D minimap camera cones, and 0-GPU scenario re-evaluation in `#studio`. |
| **ADR-13** | **Effective Config, `ReidProfile` SSOT & Replay Signature Match** | **Deep-Merged Camera Config + Single `DualModel` Profile + Exact Replay Config Match** | Resolve Re-ID profile via one `ReidProfile` SSOT (`DualModel`), treating YAML `reid.model` as advisory with loud boot warnings, `/api/system/gallery-health`, and idempotent crop-based re-embedding at startup. Deep-merge camera configs over `default.yaml` (preserving `classes` unless explicitly cleared with `null`), enable class-agnostic NMS (`agnostic_nms=True`), and replay cached `video_runs` in `#live` only when the run's `config_json` detector signature matches the camera's active detector config. |
| **ADR-14** | **SQLite Alert SSOT & Write-Through `EventBus`** | **SQLite-Backed `/events` + Realtime Push-Only `EventBus` + Bulk Row Selection** | Persist alerts to SQLite (`world_timeline_events`) before streaming new IDs on `EventBus`. Serve `GET /events` and unread counts strictly from SQLite so bus rows never shadow ack/clear/delete mutations, and support per-row checkboxes + "Select all matching" for bulk ack, delete, and export. |
| **ADR-15** | **Canonical `SourceRef` Navigation & `ActiveSourceContext`** | **Hash-Parameterized `App.navigate(tab, SourceRef)` + Shared Source Selector** | Serialize a canonical `SourceRef` (`kind`, `camera_id`, `video_filename`, `run_id`, `media_offset_sec`, `ts`, `track_id`, `entity_id`, `zone_id`, `bbox`) into URL hash params via `App.navigate(tab, sourceRef)`. Sync `ActiveSourceContext` (hash + `localStorage`) across `#live`, `#analytics`, `#studio`, and Enrollment (with Pause/Resume `/freeze_frame` in Enrollment & Studio), rendering `MediaEmptyState` when a referenced source is unavailable. |
| **ADR-16** | **Explicit Sightings Provenance & Backfill** | **`sightings.camera_id` & `run_id` Migration + Enrollment Seed + Throttled Relabel Backfill** | Migrate `sightings` via `PRAGMA user_version` to store `camera_id` and `run_id` explicitly (backfilled from `source`/`video_filename`), emit a cropped seed sighting on every live/video/ROI enrollment, backfill throttled sightings on retroactive video-run relabeling, and list all known cameras and videos in Timeline source filters. |
| **ADR-17** | **Persistent-Entity Tracking & Identity Hysteresis Lock** | **SORT + ByteTrack 2-Stage Association + `K=3` Hysteresis Lock** | Default to `sort` with ByteTrack-style two-stage association (using low-confidence detections to bridge occlusions) and hysteresis identity locking (bind after `K=3` matches `>= 0.65`; unbind only after `M` contradicting frames or user correction) so detector votes reinforce the `WorldEntity` rather than flickering identity frame-by-frame. |
| **ADR-18** | **Multi-Box Tag Queue & Exemplar Learned Classes** | **Reused `#modal-tag-entity` Track Picker Strip + Learned Classes Registry** | Return all overlapping tracks on click and queue Quick-Tag boxes in a track picker strip inside `#modal-tag-entity` without losing untagged tracks on submit. Support exemplar-based "Learned Classes" and per-camera COCO label corrections/suppression unified with Semantic Category badges on a dedicated `Classes & Badges` page with collision checking. |
| **ADR-19** | **Reversible Review Audit & Unknown Queueing** | **`review_decisions` Audit Trail + Session Undo / "Correct..." + Recurring Unknowns** | Record prior state in `review_decisions` on every confirm/dismiss/reassign so operators can Undo within session or click "Correct..." anytime (`#modal-tag-entity` Known state), reverting embeddings/negative exemplars and relabeling runs/sightings; also queue recurring unknown tracks and timeline "Report wrong" flags. |
| **ADR-20** | **Seam-Level Verification & `INFRA_UNAVAILABLE` Gate** | **Real-Config / Deep-Link / Drag-PUT / Bus+DB Probes + Strict CDP Sign-Off** | Enforce seam-level workspace probes (`effective_config_probe`, `deep_link_navigation_probe`, `studio_drag_put_probe`, `alerts_store_probe`, `sightings_provenance_probe`) alongside `system-diagnostics` detectors (`data:image` decode, flex child-overflow matrix, silent-skip AST rule, fetch-method parity). Treat CDP bootstrap failures and empty sweeps as `INFRA_UNAVAILABLE` rather than advisory/passing results during `plan_engine verify`. |
| **ADR-21** | **Runtime Seam Resilience, Synthetic Re-ID Parity, Tripwire Directionality & Long-Fixture Overflow Containment** | **Single `window.switchTab` Path + Sync Multiview Wake + Pixel-Aligned `MockDetector` + Stateful `TagTrackQueue` + `pt1<->pt2` Flip Handle + `video:<filename>` Provenance** | Route all `.nav-tab` clicks through `window.switchTab` so `tab-changed` triggers Studio media attachment; clear `_is_hibernating` and update `.tile-status-badge` synchronously on grid wake; align `MockDetector` with `SyntheticFrameGenerator` `P1`/`P2` pixels; keep `TagTrackQueue` frozen `cropBase64` + suppressed candidate IDs across Next/Prev; support live ROI-draw collision/suggestions in Enrollment and `tracked_categories` preservation on Camera Edit; render `IN`/`OUT` tripwire arrows/labels with zero-migration `pt1<->pt2` flip handles; attribute non-scenario batch review items to `video:<filename>`; and verify long-fixture overflow containment via CDP (`OBS-001`–`OBS-019`). |
| **ADR-22** | **Handoff Kwarg Parity, Dynamic `2560D` Re-ID Profile, Centroid-Fallback SORT & 1-to-1 Per-Frame Entity Uniqueness** | **Verified Handoff Signature + Dynamic Extractor Dim + Centroid-Assisted SORT + Per-Frame Entity Exclusion** | Keep `MultiCameraHandoffCoordinator.record_zone_exit()` signature aligned with `post_detection_governance.py` (`track_id` optional); resolve canonical `DualModel` dimension dynamically (`2560D` = `512` OSNet + `2048` 4x4 color) instead of hardcoded `608D`; pair `SortTracker` IoU matching with centroid-distance fallback and suppress unconfirmed/stale coasting boxes in telemetry so moving targets never spawn trailing ghost boxes at `8 FPS`; and enforce 1-to-1 per-frame entity uniqueness in `GalleryMatcher` + `IdentityHysteresisTracker` so one person never binds two concurrent boxes on the same camera (`DBG-01`, `DBG-02`, `OBS-036`, `OBS-040`, `OBS-047`). |
| **ADR-23** | **Clean Studio Overlays, SQLite Alert Governance, Web-Playable Live Clips & Paginated Review/Filtered Heatmaps** | **`?annotated=false` Studio + Write-Through Severity/Rules + Auto-H.264 Clip Links + Paginated Review & DB Heatmaps** | Attach `#studio-live-img` with `?annotated=false`, drive `#studio-drawing-canvas` from live telemetry & exported `ScrubberOverlay.getCurrentTracks()`, open full Zone/Tripwire edit modals, derive `CameraWorldPose` + `fov_corners_global` on homography save, and normalize epoch/ISO bounds with a visible Reset control in `#timeline` (`OBS-024`–`029`, `OBS-035`). Keep `world_entity_state_changed` in-memory on `EventBus` (not SQLite), wire `EventBus.set_write_through_handler`, persist canonical `severity`, unscoped `zone_id`, and `zone_dwell` start/end/duration with DB-backed Alert Promotion Rules (`OBS-030`–`034`). Prefer web-playable H.264 / auto-transcode on recording stop with active-recording transcode guard and `(video_filename, media_offset_sec)` alert provenance (`OBS-038`–`041`). Return `total_pending`, pagination, filters, and bulk-dismiss in `/api/review/queue` and support filtered historical DB heatmaps in `/analytics/heatmap` (`OBS-023`, `OBS-043`, `OBS-048`). |

---

## 2. Verified Current Baseline vs. Target State

*Baseline captured via `diagnose.py arch-map` (432 source files, 80,711 lines, 154 FastAPI routes):*

### Current Structural Friction
1. **Legacy CLI Forms Boundary (`--gui forms`)**:
   - `intelligent_tracker/cli/pipeline_builder.py` and `dashboard/services/pipeline_factory.py` both delegate to unified `PipelineEngine`, while `intelligent_tracker/cli/runner.py` and `intelligent_tracker/interactive.py` retain legacy `--gui forms` (`high_objects.World`) for backward compatibility.
2. **Legacy `Space` / `Object` Modules & Unwired `WorldPolicy`**:
   - `intelligent_tracker/core/spaces.py` (`Space`, `MetaSpace`) and `intelligent_tracker/high_objects.py` (`World`, `Scene`, `Area`, `Line`) remain as legacy compatibility modules alongside runtime `WorldGraph`.
   - `WorldPolicy` (`intelligent_tracker/world/nodes.py`) and `EventBus.set_write_through_handler` (`events/bus.py`) remain unwired in production until `ADR-23` Step 2.
3. **Active Modularity Overruns**:
   - **Hard Ceiling (>= 500L)**: `intelligent_tracker/high_objects.py` (`523L`).
   - **Warning (350–499L) & Heavy Classes (> 12 methods)**: `dashboard/static/js/video_library.js` (`471L`), `intelligent_tracker/interactive.py` (`451L`), `scripts/cdp_inspect.py` (`436L`), `intelligent_tracker/rsac.py` (`402L`, `RSACManager` `14` methods), `high_objects.py` (`Scene` `25` methods), `core/tails.py` (`TailItem` `20` methods), `core/groups.py` (`Group` `19` methods), `forms.py` (`EventFigure` `19` methods), `core/group_mutations.py` (`GroupMutationMixin` `15` methods), `events/bus.py` (`EventBus` `13` methods).
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
| `dashboard/static/` | Modular HTML partials/templates + reusable shared components (`UnifiedCanvasOverlay`, `OverlayControlBar`, `FrameSurface`), zero-CLS HUD stability, zero duplicate/dead controls, `< 350L`/file, zero `!important` | **Decompose in Step 3; Unify per ADR-05** |

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
- **Strict Lock Acquisition Order & No Cross-Service Lock Nesting**: `PipelineEngine` / `StreamCoordinator` -> `WorldGraph._lock (RLock)` -> `EventBus` dispatch -> `DatabaseWriterQueue`. Lower layers MUST NEVER acquire locks from upper layers (zero lock-inversion deadlocks). Never acquire `StreamRecordingController._lock` while holding `ProcessingModeService._lock` (or vice versa); snapshot state under the local lock and release before cross-service calls.
- **Zero Blocking Under Lock**: Never execute SQLite writes, HTTP/webhook calls, VLM/LLM requests, `time.sleep()`, or `thread.join()` while holding `WorldGraph._lock` or `CameraPool` locks. Snapshot state under the lock, release, and perform I/O or thread joins outside.
- **Interruptible Loops, Bounded Queues & Single-Purpose Clock Boundaries**: All capture, inference, and reconnect loops use `stop_event.wait(timeout)` (defaulting `stop_event = threading.Event()`, never `None`). Frame ingestion uses bounded drop-oldest queues so slow inference or VLM queries never cause unbounded RAM growth. Never pass `time.monotonic()` into domain, DB, RSAC, or `ConfidenceEngine` timestamps (`ADR-06`).

### 6.2 Schema Migration, Deprecation & Edge-Case Guards
- **Idempotent SQLite Migrations**: Schema evolutions in `intelligent_tracker/database.py` (WAL mode, `WorldEntity` metadata, FTS5 timeline tables, global `(X, Y)` coordinates, confidence telemetry) MUST use versioned, idempotent `PRAGMA user_version` migrations that preserve existing `data/tracker.db` records cleanly.
- **Legacy `MetaSpace` / `high_objects.py` Transition Window**: During Step 2, keep a minimal compatibility shim or explicit deprecation boundary until all tests and `scenarios.py`/`topology.py` imports migrate to `intelligent_tracker/world/`. Never break `VideoSource` / DirectShow COM cleanup invariants on stream teardown.
- **Cross-Platform Path & Config Hygiene**: Resolve model weights, DB paths, and camera configs via `pathlib.Path` and environment overrides—never hardcode `localhost`, ports, or OS-specific path separators.

### 6.3 Privacy & VLM/LLM Data Egress Boundaries
- **Default Local-Only Operation**: Zero frame crops, embeddings, or sighting timelines leave the host unless a cloud `SemanticProvider` is explicitly configured and enabled.
- **Privacy Masking Hook**: Before any frame or crop is forwarded to an external `SemanticProvider` or webhook, apply the configured privacy filter (metadata-only mode or face/plate masking toggle).

### 6.4 Golden End-to-End Regression Fixture & Master Plan Continuity
- **Golden E2E Fixture & 4-Tier Diagnostic Verification Gate**: Maintain a deterministic headless multi-camera synthetic/recorded-clip fixture (`detector=mock`, isolated `TemporaryDirectory` DB) that verifies identical detections, zone/tripwire events, RSAC alerts, `WorldGraph` state transitions, and DB sightings across CLI and Dashboard. Enforce the 4-tier diagnostic verification gate:
  1. Static cross-contract + cross-module AST + typechecks (`diagnose.py surface --verify`, `scan`, `audit --typecheck`), including the repo-rollback AST rule (`*_repo.py` writes calling `self._conn.rollback()` in `except`, covering `SignatureMixin`), `[UNDEFINED_LAYOUT_CLASS]` HTML grid/form CSS verification, `CALLABLE_SIGNATURE_DRIFT` AST verification inside `try/except`, script-load-order `window.*` wrap checks (`nav_tabs_manager.js` after `app.js`), and query-param parity checks.
  2. Unmocked real-clock, deadlock, replay, seam, and Re-ID contract workspace probes (`.diagnostics/probes/`), including `effective_config_probe` (booting from real `configs/*.yaml` + `cameras.json` to assert Re-ID dim parity and non-wiped `classes`), `alerts_store_probe` (bus + SQLite seeding), `studio_drag_put_probe` (real temp DB `PUT` round-trip), `sightings_provenance_probe` (`camera_id`/`run_id`, enrollment seed + relabel backfill), `/api/enroll` -> `create_video_indexer()` -> `/api/videos/{fn}/detections`, automatic sighting crops, and mixed online/offline/recorded camera boot probes. `plan_engine verify` sign-off requires every probe to pass outright (`INFRA_UNAVAILABLE` or empty sweeps are hard non-passing gates).
  3. 9-tab headless Chrome CDP sweeps (`spa_nine_tab_cdp_probe` and `deep_link_navigation_probe` clicking Live/Studio/Timeline drill-downs and asserting camera select, stream `src`, and URL hash sync), checking zero HTTP `>= 400`, valid `data:image` XML/SVG decoding, first-frame enrollment canvas luminance, child-box-outside-parent flex overflow across `960`/`1280`/`1920` viewports with long `<option>` text, zero broken or empty-`src` `<img>` elements (`naturalWidth === 0`, `src=""`, or missing `src`), zero JS exceptions, zero CLS/layout-jitter shifts, zero squeezed modal tables/inputs (`< 140px`), `>= 4px` sibling gaps, zero dead/duplicate buttons (`--audit-layout --stability-ms 2000`), and `tile-overlay-canvas` vs `.tile-video-container` `DOMRect` parity across `2x2 <-> 3x3 <-> 4x4`.
  4. Full headless regression (`python -m unittest discover tests`) and zero-warning Sphinx build (`sphinx -W`).
- **Master Plan of Plans (`plan_engine.py`)**: Register `.TODO/world_architecture_master_roadmap.md`, `.TODO/integration_hardening_master_roadmap.md`, `.TODO/tracking_intelligence_ux_master_roadmap.md`, `.TODO/reid_unification_traceability_and_studio_ux_master_roadmap.md`, `.TODO/integration_seams_entity_persistence_master_roadmap.md`, `.TODO/runtime_ux_and_reid_parity_master_roadmap.md`, and `.TODO/tracking_studio_alerts_and_recording_parity_master_roadmap.md` as master roadmaps and bind each per-step implementation plan (`.TODO/step_<N>_<slug>.md`) as a child plan via `plan_engine.py init .TODO/step_<N>_<slug>.md --parent <master_slug> --milestone <N>` so architectural context and progress survive across conversations.


