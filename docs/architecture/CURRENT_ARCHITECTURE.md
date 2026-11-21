# Intelligent Tracker — Current Architecture & Alignment Audit

> **Snapshot Basis**: Branch `feature/integration-remediations` (commit `400bc9f`, post-`integration_diagnostics_and_remediation_plan.md` Milestones 1–3 + FPS/replay hotfix).
> **Measured Static & Test Baseline**: `diagnose.py arch-map` = `336` source files, `61,571` lines, `111` FastAPI route decorators across 15 routers + `dashboard/app.py`, `0` upward imports from `intelligent_tracker/` to `dashboard/` or `scripts/`, `0` CSS `!important` across `25` stylesheets; `diagnose.py tests` = `882` unit/integration tests passing (`OK`); `sphinx -W` = `0` warnings; `diagnose.py scan` = `0` active defects (`16` resolved); `diagnose.py surface --verify` = `0` reported mismatches (blind spots documented in Section 6); `diagnose.py traces` = `18` unique issues (`8` active, `10` resolved, `662` events).
> **Reference Target**: [Ideal World Architecture & Target Blueprint](IDEAL_WORLD_ARCHITECTURE.md) (`ADRs 01–04`, Layers 1–5).

### Pre-Run Verification One-Liners

```bash
MPLBACKEND=Agg python -m unittest discover tests
python -m sphinx -W --keep-going documentation/ documentation/_build/html/
python skills/system-diagnostics/scripts/diagnose.py arch-map --path .
```

---

## 1. Executive Alignment Verdict vs. `IDEAL_WORLD_ARCHITECTURE.md`

- **Structural Convergence (~80–85%)**: All 5 target layers, ADRs 01–04, `PipelineEngine`, scoped `WorldGraph`, `ConfidenceEngine` / `EventFTSIndex` / `WorldQueryEngine`, `SQLiteConnectionCoordinator` (WAL + `RLock`), `/ws/multiview` binary tile transport, `AnalyticsScheduler`, and 15 modular FastAPI routers are implemented and pass `882` unit/integration tests.
- **Operational End-to-End Integration (~55–60%)**: Cross-layer runtime seams still exhibit silent clock-domain corruption, an AB-BA lock-order deadlock during active recording, in-place coordinate mutation across `max_dim=1280` frames, broken heatmap rendering, split-brain `WorldGraph` / `ConfidenceEngine` instances, scenario wipe on stream restart, and widespread frontend-backend JSON payload drift.

| ADR / Layer | Target Blueprint | Current Branch Status | What Is Genuinely Achieved | Remaining Drift / Gaps |
| :--- | :--- | :--- | :--- | :--- |
| **ADR-01: Unified Core Engine + Thin Adapters** | Single `PipelineEngine` + `FrameProcessor.step()` for CLI and Dashboard | **Mostly Achieved** | `PipelineConfig`, `PipelineEngine`, and `FrameProcessor.step()` unify CLI (`intelligent_tracker/cli/pipeline_builder.py:108`, `runner.py:76`) and Dashboard (`dashboard/services/pipeline_factory.py:95`, `stream_worker.py`); `pyproject.toml:59-62` defines all 3 `console_scripts`. | `intelligent_tracker/interactive.py:288-380` builds a separate manual detector/tracker/matcher loop; `VideoIndexer` (`intelligent_tracker/batch.py:153-195`) manually instantiates components instead of calling `PipelineEngine.build()`; `cli/runner.py:17-47` retains `run_legacy_forms_gui` using `high_objects.World`. |
| **ADR-02: Scoped `WorldGraph` + Reactive Rules** | Instance-scoped `WorldGraph`, `WorldEntityBridge`, `GlobalCoordinateMapper`, retiring `MetaSpace`/`high_objects.py` | **Partial / Split-Brain** | `WorldGraph`, `WorldNode` subclasses, `WorldEntityBridge`, `GlobalCoordinateMapper`, `WorldTransitionRegistry`, `WorldRuleEngine`, and `WorldTacticalMinimap` operate with `RLock` scoping; `ScenarioManager` cold-boot DB/YAML sync landed in M2. | `CameraPool.world_graph` (`dashboard/camera_pool.py:51`) passes `event_bus=None` (and `pipeline/bundle.py:304` skips attaching one), so Dashboard mutations never emit reactive events; `WorldPolicy` (`world/nodes.py:182-197`) is unused in runtime; stream restart wipes `CameraNode` homography/pose (`world/graph.py:66-71`) and skips `ScenarioManager.apply_to_stream_manager()`; `DELETE /api/scenarios/homography/{id}` leaves stale matrices in `WorldGraph`/`GlobalCoordinateMapper`; legacy `high_objects.py` (`523L`) and `core/spaces.py` remain active via `--gui forms`. |
| **ADR-03: Hybrid Local Memory + Pluggable Q&A** | `ConfidenceEngine`, `EventFTSIndex`, `WorldQueryEngine` + `SemanticProvider` | **Partial / Clock & Wiring Drift** | `ConfidenceEngine`, `EventFTSIndex` (FTS5 + `PRAGMA user_version = 1`), `WorldQueryEngine`, `PrivacyMaskingFilter`, and local/mock/Gemini providers are implemented in `intelligent_tracker/memory/` and bound onto `app.state`. | Live `dashboard/services/async_inference_worker.py:266` injects `time.monotonic()` and offline `intelligent_tracker/batch.py:254-256` injects `video_ts` (`0.0s`) as Unix epoch `timestamp` into `FrameProcessor.step()` -> instant 56-year confidence decay to `0.10` floor, `1970-01-01` sightings/FTS rows, and broken relative time queries (`"last 2 hours"`, `"today"`); `ConfidenceEngine` is instantiated per stream (`bundle.py:234`) instead of shared pool-wide; `_gallery_signals.py:153-157` drops `video_filename`/`media_offset_sec` on periodic FTS sightings; `query_engine.py:38-53` omits media fields from citations. |
| **ADR-04: `arch-map` Verification & Modularity** | Zero active files `>= 500L`; `<= 12` methods/class; `<= 40L`/fn; zero `sys.modules` DI hacks | **Largely Achieved (with Legacy Debt)** | `0` upward imports from `intelligent_tracker/`, `0` CSS `!important`, `index.html` (`<180L`), `capture_worker.py` back `<350L`, Win32 `ctypes.Structure` audit warnings fixed, `0` active `scan` defects, `dependencies.py` uses `app.state`. | `1` hard overrun (`intelligent_tracker/high_objects.py` `523L`), `9` soft warnings (`350–499L`), `8` heavy classes (`>12` methods or `>300L`), `59` functions `>40L`, unused `import time` in `dashboard/services/stream_worker.py:9`. |
| **Layer 1: SQLite Concurrency & Hardware** | `pyproject.toml` entrypoints + WAL pooled/serialized DB coordinator | **Mostly Achieved** | `SQLiteConnectionCoordinator` enforces WAL + per-path `RLock` + refcounted `TRUNCATE` checkpoint; `VideoSource` modularized with `frame_timing.py`. | Only `SignatureMixin` guards `self._conn is None` (9 other repository mixins do not); `BackupManager.restore_backup` lacks ZIP symlink rejection and SQLite WAL/SHM sidecar cleanup; `TRC-018` risk from unclosed `TrackerDB` in `ScenarioManager` / `VideoIndexer`; `CaptureReadGuard._wait_interruptible()` uses `time.time()` and `read()` mutates state outside lock; `journey.py:81-92` runs raw SQL on `db._conn`. |
| **Layer 2: Identity, Learning & RSAC** | Unified Re-ID, Active Learning, RSAC & descriptor versioning | **Partial** | Locked anchors, bounded EMA, RSAC rules/categories, pet whitelist, Active Learning triage/actions, and FTS5 indexing work locally. | `RoiRecognitionService` and `EntityTaggerService` bypass `ConfidenceEngine`, `EventFTSIndex`, `DescriptorMixin`, and `is_anchor=1`; `post_detection_governance.py:115-119` drops `zone_id` when converting `EntityIdentifiedEvent`. |
| **Layer 3 & 4: WorldGraph, Scheduler & Multiview** | Scoped graph, P0/P1/P2 scheduler, zero-GPU replay, binary `/ws/multiview` | **Partial** | `/ws/multiview` zero-extra-render leasing, `MotionGate`, `ReplayTrack`, `CachedReplayProvider` wrap-around reset, and `StreamPoolCoordinator` two-pass teardown work cleanly. | `ProcessingModeService` <-> `StreamRecordingController` AB-BA lock inversion; `FrameProcessor.step(max_dim=1280)` mutates `CentroidTracker` tracks in-place; `FrameOverlayRenderer` calls non-existent `draw_heatmap_overlay()`; `capture_only` freezes `annotated=True` MJPEG streams; `REPLAY` <-> `LIVE` transition races. |
| **Layer 5: Thin Adapters & CLI <-> Dashboard Parity** | Full operational parity and thin routers | **Partial** | 15 domain routers cleanly split under `dashboard/routers/`; `dependencies.py` uses `app.state`. | `ctl.py` covers `list/stats/evict/prune/history/metrics/ask/world/models/record`, with zero CLI parity for camera CRUD, processing modes, scenarios/topology/journeys, RSAC/active learning, or video jobs; multiple backend endpoints (`/api/world/*`, `/api/rsac/rules`, `/api/pets/whitelist`, `/api/topology/world-map`, `/api/cameras/{id}/retry`, `/api/system/{processes,metrics,events,models}`) have zero Dashboard UI callers; widespread frontend-backend JSON drift (`Section 5 P2`). |

---

## 2. Current Layered Architecture & Actual Runtime Data Flow

Dependencies flow strictly downward (`dashboard/` and `intelligent_tracker/cli/` -> `intelligent_tracker/`): `arch-map` confirms **0** upward imports from `intelligent_tracker/` into `dashboard/` or `scripts/`. Solid edges show verified operational paths; dashed edges show confirmed runtime integration seams and drift.

```mermaid
flowchart TD
    subgraph L5["Layer 5: Thin Adapters (dashboard/ & intelligent_tracker/cli/)"]
        SPA["SPA Dashboard (index.html + 9 tabs, FrameSurface, UnifiedCanvasOverlay, SchedulerHUD)"]
        Routers["15 Domain APIRouters + app.py (111 routes, /ws/multiview, /ws/{id}, /stream/{id})"]
        CLI["CLI Adapters (cli/runner.py, cli/ctl.py, cli/ask.py, cli/ctl_world.py, cli/ctl_record.py)"]
    end

    subgraph L4["Layer 4: Orchestration, Scheduling & Execution"]
        Pool["CameraPool -> CameraConfigStore + StreamPoolCoordinator + ProcessingModeService"]
        SW["StreamWorker -> AsyncInferenceWorker + StreamRecordingController + FrameOverlayRenderer"]
        Replay["CachedReplayProvider -> FileDetectionReplayProvider + evaluate_tracks_governance"]
        PE["PipelineEngine -> PipelineConfig + PipelineBundle + FrameProcessor.step()"]
        Bus["Per-Stream EventBus + AlertRuleEngine + EventFTSIndex"]
    end

    subgraph L3["Layer 3: Scoped World Graph"]
        WG["Pool WorldGraph (event_bus=None, CameraNode, ZoneNode, TripwireNode, WorldEntity, TransitionEdgeNode)"]
        Bridge["WorldEntityBridge + GlobalCoordinateMapper + MultiCameraHandoffCoordinator + WorldRuleEngine"]
    end

    subgraph L2["Layer 2: Identity, Learning & Semantic Memory"]
        ID["ReID (OSNet/Color), GalleryMatcher, UniversalEnrollment, ActiveLearning, RSACManager"]
        Mem["Per-Stream ConfidenceEngine + EventFTSIndex (FTS5) + WorldQueryEngine (Local / Gemini)"]
    end

    subgraph L1["Layer 1: Persistence & Hardware"]
        DB["TrackerDB (Repository Mixins + SQLiteConnectionCoordinator WAL/RLock)"]
        CV["VideoSource (CaptureLifecycleMixin + CaptureWorkerMixin + CaptureReadGuard + frame_timing), Detectors, SORT/Centroid"]
    end

    SPA -->|"HTTP / WS / MJPEG"| Routers
    SPA -.->|"P2: JSON key & URL mismatches (review, alerts, studio, scrubber)"| Routers
    Routers --> Pool
    Routers --> Mem
    Pool -->|"P0: AB-BA lock inversion with StreamRecordingController"| SW
    SW -->|"/ws/multiview ThumbnailCache (annotated=False)"| Routers
    SW -.->|"P0: time.monotonic() injected as Unix epoch"| PE
    SW -->|"zero-GPU replay + wrap reset"| Replay
    SW --> PE
    CLI --> PE
    PE -->|"P0: max_dim=1280 mutates CentroidTracker tracks"| CV
    PE --> Bus
    PE --> Bridge
    Replay -->|"sync_world_bridge (0 GPU)"| Bridge
    Bridge --> WG
    WG -.->|"P0: event_bus=None drops reactive events; restart wipes homography"| Bus
    PE --> ID
    ID -->|"P0: unshared per-stream ConfidenceEngine + 56yr monotonic decay"| Mem
    ID --> DB
    Mem --> DB
```

---

## 3. Measured Package Footprint, Modularity Debt & CLI <-> Dashboard Parity

### Directory Footprint (`diagnose.py arch-map`)

| Directory | Files | Lines | Primary Ownership |
| :--- | ---: | ---: | :--- |
| `.` | 2 | 161 | `main.py`, `setup.py` (`pyproject.toml` also at root) |
| `dashboard` | 149 | 30,423 | FastAPI app (`app.py`, `dependencies.py`), 15 routers (`routers/`), orchestration/replay/multiview (`services/`), modular SPA (`static/js/`, `static/css/`, `static/partials/`) |
| `documentation` | 1 | 180 | Sphinx `.rst` docs & `conf.py` |
| `intelligent_tracker` | 178 | 29,971 | Core CV (`detectors/`, `tracker/`, `reid/`, `matching/`, `geometry/`), `pipeline/`, `world/`, `memory/`, `events/`, `analytics/`, `repositories/`, `video/`, `cli/` |
| `scripts` | 6 | 836 | `run_dashboard.py`, `stream_ctl.py`, `cdp_inspect.py`, `diagnostics.py`, `download_models.py`, `camera_manager.py` |
| **Total** | **336** | **61,571** | **111 API route decorators across 16 Python modules** |

### Remaining Modularity Budget Overruns

- **Hard Ceiling (`>= 500L`) — 1 file**: `intelligent_tracker/high_objects.py` (`523` lines; legacy `Scene` `25` methods).
- **Soft Warning (`350–499L`) — 9 files**:
  - Frontend JS (5): `dashboard/static/js/video_jobs.js` (`493`), `dashboard/static/js/video_library.js` (`471`), `dashboard/static/video_scrubber.js` (`389`), `dashboard/static/app.js` (`374`), `dashboard/static/camera_manager.js` (`366`).
  - Python (4): `intelligent_tracker/interactive.py` (`451`), `scripts/cdp_inspect.py` (`436`), `intelligent_tracker/matching/gallery.py` (`425`), `intelligent_tracker/rsac.py` (`412`).
- **Heavy Classes (`> 12` methods or `> 300L`) — 8 classes**: `Scene` (`25`m, `269L`, `high_objects.py`), `TailItem` (`20`m, `172L`, `core/tails.py`), `Group` (`19`m, `149L`, `core/groups.py`), `EventFigure` (`19`m, `164L`, `forms.py`), `CaptureReadGuard` (`16`m, `251L`, `video/capture_guard.py`), `GroupMutationMixin` (`15`m, `164L`, `core/group_mutations.py`), `RSACManager` (`14`m, `210L`, `rsac.py`), `GalleryMatcher` (`10`m, `307L`, `matching/gallery.py`).
- **Functions `> 40L` — 59 functions**: Top offenders include `run_interactive_app` (`151L`, `interactive.py:274`), `FrameOverlayRenderer.render` (`134L`, `dashboard/services/frame_overlay.py:25`), `apply_windows_iocp_patch` (`129L`, `dashboard/services/windows_resilience.py:31`), `main_async` (`111L`, `scripts/cdp_inspect.py:302`), `setup_event_pipeline` (`109L`, `intelligent_tracker/events/pipeline.py:12`), `build_generic_audit_js` (`100L`, `scripts/cdp_inspect.py:143`), `enroll` (`96L`, `intelligent_tracker/enrollment.py:51`), `create_backup` (`91L`, `intelligent_tracker/backup.py:78`), `cnt_intersection` (`91L`, `intelligent_tracker/geometry/intersections.py:171`), and `transcode_to_h264_async` (`84L`, `dashboard/services/video_transcoder.py:258`), plus `49` more.
- **Unused Imports**: `dashboard/services/stream_worker.py:9` (`time` flagged by `arch-map`), plus `intelligent_tracker/video/legacy_camera.py:154` (`PiRGBArray` inside `try...except ImportError` fallback).

### CLI <-> Dashboard Operator Parity Matrix (9 Domains)

| Operational Domain | Dashboard Router(s) | CLI Surface (`ctl.py` / `runner.py` / Tools) | Remaining Parity Gaps |
| :--- | :--- | :--- | :--- |
| **Live Pipeline & Benchmark** | `streaming.py` (2), `cameras.py` | `runner.py` (`--source`, `--detector`, `--tracker`, `--reid`, `--governance`, `--headless`, `--benchmark`) | Covered locally; `interactive.py` maintains a separate non-unified loop. |
| **WorldGraph & Semantic Q&A** | `world.py` (5) | `ctl.py ask` / `ask.py`, `ctl.py world [summary\|entities\|snapshot]` | Missing CLI parity for `/api/world/confidence/{id}`, standalone `/api/world/timeline` (`start_time`/`end_time`), and REST/CLI `WorldPolicy` CRUD. |
| **Models & Diagnostics** | `system.py` (11), `camera_diagnostics.py` (5) | `ctl.py models [status\|verify\|download]`, `ctl.py stats/list/evict/prune/history/metrics`, `camera_tool.py` | Missing remote `ctl` parity for `/api/cameras/{id}/diagnostics`, `/probe`, `/release`, and `/api/cameras/diagnostics/traces/recent`. |
| **Camera Recording** | `camera_recording.py` (3) | `ctl.py record [start\|stop\|status]` (`ctl_record.py`) | Full remote parity (`ctl_record.py` still defaults `--camera-id` to `"cam_01"`). |
| **Backup & Restore** | `system.py` (`/api/backup/*`) | `intelligent_tracker/backup.py` (`--export`, `--import`, `--info`) | Local parity; no remote `ctl backup` subcommand. |
| **Batch Video Indexing** | `videos.py` (6), `video_jobs.py` (12) | `intelligent_tracker/batch.py`, `batch_reporting.py` | No CLI parity for H.264 transcoding, async job queue (`jobs`/`cancel`/`stream`), report delete, or `--scenario-camera-id` in `batch_reporting.py`. |
| **Camera Pool CRUD & Modes** | `cameras.py` (16), `processing_mode.py` (2) | `ctl.py list` (read-only), `camera_tool.py` (local HW only) | Zero CLI parity for camera `add`/`update`/`delete`/`toggle`/`retry`/`discover`/`overlays` or `processing-mode` (`focus_only`/`full_realtime`/`capture_only`/`paused`). |
| **Scenarios, Topology & Journeys** | `scenarios.py` (11), `topology.py` (7) | `interactive.py` (local draw without DB/YAML save) | Zero CLI parity for zones, tripwires, homography CRUD, topology links, `world-map`, or `/api/journey/search` & `/export`. |
| **Entities, Tagging, RSAC & AL** | `analytics.py` (9), `tagging.py` (2), `rsac.py` (18) | `interactive.py` / `display.py` (local `db.enroll_entity` only) | Zero CLI parity for review queue (`confirm`/`reassign`/`enroll-new`/`dismiss`), RSAC rules/categories/pet whitelist, descriptor rollback, ROI tagging, or entity CRUD. |

---

## 4. Verified Remediations Landed on This Branch (M1–M3 + `400bc9f`)

These fixes from `integration_diagnostics_and_remediation_plan.md` and commit `400bc9f` are verified in code and covered by `882` tests + `3` workspace probes:

1. `intelligent_tracker/video/capture_worker.py` unified its capture pacing loop on `time.monotonic()` and split helpers back under `350L` (`< 350L`).
2. `VideoSource.resume()` (`intelligent_tracker/video/hibernation.py:28`) and paused `capture_worker.py:331` clear `_last_frame_time = None` so hibernation wakeups do not depress `measured_fps`.
3. `FileDetectionReplayProvider.ensure_loaded()` (`dashboard/services/file_detection_replay.py`) adds a bounded empty-DB TTL re-check and tightens `tolerance_s` from `video_runs.config.sample_rate` (`intelligent_tracker/repositories/video_run_repo.py:166-184`, commit `400bc9f`).
4. `Track.to_dict()` (`intelligent_tracker/tracker/track.py`) emits `entity_id`, `category`, and `entity_category` via `getattr(self, ..., None)` without breaking legacy `hasattr(trk, 'entity_id') == False` invariants.
5. `sync_world_bridge()` (`intelligent_tracker/pipeline/post_detection_governance.py`) executes under `CachedReplayProvider(..., run_reid=False)` at zero GPU cost.
6. `AsyncInferenceWorker` (`dashboard/services/async_inference_worker.py:127-128,212-216`) guards `result is None` (`TRC-015` resolved) and calls `scheduler.should_schedule_frame(..., is_replay=True)` to record `PriorityTier.REPLAY`.
7. `ScenarioManager.load_scenarios()` (`intelligent_tracker/scenario_storage.py`) syncs loaded DB/YAML zones and tripwires into `WorldGraph` on boot.
8. `world_timeline_events` (`intelligent_tracker/memory/_event_formatters.py`, `fts_index.py`, `repositories/memory_repo.py`) stores `video_filename` + `media_offset_sec` on `EventBus` alerts, and `GET /events` (`dashboard/routers/analytics.py`) merges persisted timeline rows.
9. `dashboard/routers/analytics.py` switched primary entity/sighting/event routes to `Depends(get_db)` and removed the `/crops/{filename}` route shadowed by `StaticFiles`; `dashboard/routers/videos.py` resolved duplicate `operationId`.
10. `dashboard/app.py` binds `confidence_engine` and `world_query_engine` into `app.state`.
11. `dashboard/static/js/scrubber_library_bridge.js` fetches plural `/api/videos/{fn}/reports` and deep-links `/videos/{fn}`, and `dashboard/static/js/video_timeline_links.js` reads `entities` + `alerts` (removing `occurrences`).
12. `dashboard/static/partials/modals/camera_modals.html` and `camera_manager.js` expose the `armed` toggle, `StreamWorker` binds `is_armed_getter`, and `camera_ai_config.js` gates boot `#live-stream-img` attach on `active_tab === 'tab-live'`.
13. `dashboard/services/process_supervisor.py` and `dashboard/static/js/multiview/multiview_client.js` cleared all `invalid_signature` and `SILENT_BARE_EXCEPT` (`DEFECT-001`/`002`) active scan alerts.

---

## 5. Verified Remaining Integration Bugs & Missing Functionality (P0–P3)

### P0 — Critical Runtime, Data Corruption & Deadlock Bugs (5)

1. **`P0-1` Live & Offline Clock-Domain Corruption (`time.monotonic()` / `0.0s` Injected as Unix Epoch)**
   - **Evidence**: `dashboard/services/async_inference_worker.py:81,228,266` (`now = time.monotonic()` -> `FrameProcessor.step(..., timestamp=ts)` -> `post_detection_governance.py:147,164,167`); `intelligent_tracker/batch.py:254-256` (`video_ts` starting at `0.0s` passed as `timestamp`); downstream consumers `intelligent_tracker/rsac.py:60-63` (`datetime.fromtimestamp(ts)`), `intelligent_tracker/repositories/analytics_repo.py:21` (`time.gmtime(ts)`), `intelligent_tracker/memory/confidence.py:117-122,200`, `intelligent_tracker/memory/query_engine.py:244`, `dashboard/static/js/telemetry.js:144`, `dashboard/services/multiview/thumbnail_cache.py:106,111`.
   - **Impact**: Every live sighting/FTS/alert/RSAC timestamp resolves to **`1970-01-01`**, live/offline `ConfidenceEngine` confidence immediately decays ~56 years (`1.79e9 - 1e4`) to `decay_floor = 0.10`, RSAC schedules evaluate against 1970, and `WorldQueryEngine` relative time queries (`"last 2 hours"`, `"today"`) never match live events.

2. **`P0-2` AB-BA Lock-Order Deadlock (`ProcessingModeService` <-> `StreamRecordingController`)**
   - **Evidence**: `dashboard/services/processing_mode_service.py:124-147,192-202` (`get_state(pool)` holds `ProcessingModeService._lock` -> reads `sm.is_recording` -> `dashboard/services/stream_recording.py:90` acquires `StreamRecordingController._lock`) vs `dashboard/services/stream_recording.py:81-85,100,133,223,241,248` (`start`, `write_frame`, `stop`, `finalize_if_active` hold `StreamRecordingController._lock` -> call `_current_processing_mode()` / `enqueue_deferred_indexing()` -> acquire `ProcessingModeService._lock` at `processing_mode_service.py:49,188`). Also `processing_mode_service.py:126-128,156` iterates `pool.streams.items()` without `pool._lock`.
   - **Impact**: Concurrent `/api/system/processing-mode` polling and recording (`write_frame` / `/record/start|stop`) can deadlock the server worker and HTTP threads.

3. **`P0-3` `FrameProcessor.step(..., max_dim=1280)` Corrupts `CentroidTracker` Coordinate Space In-Place**
   - **Evidence**: `intelligent_tracker/pipeline/frame_processor.py:59-78,123-139`, `dashboard/services/async_inference_worker.py:26,118`, `intelligent_tracker/tracker/centroid.py:122,161,228`.
   - **Impact**: `_rescale_tracks_and_detections` mutates `trk.bbox`, `trk.centroid`, and `trk.velocity` **in-place** on live `Track` objects kept inside `CentroidTracker.tracks` from `1280x720` back to `1920x1080`, so the next frame matches `1920x1080` track boxes against `1280x720` detections (causing ID churn and velocity spikes). It also never rescales `detections` and returns downscaled `processed` as `result.frame` alongside full-res `tracks`.

4. **`P0-4` Heatmap Overlay `AttributeError` & 16:9 Shape Crash**
   - **Evidence**: `dashboard/services/frame_overlay.py:45-49` (`analytics.draw_heatmap_overlay(annotated, alpha=0.55)`) vs `intelligent_tracker/analytics/engine.py:24-204` (only `heatmap.draw(...)` and `draw(..., draw_heatmap=True)` exist); `intelligent_tracker/pipeline/bundle.py:152-160` + `intelligent_tracker/video/capture_helpers.py:55-57` + `intelligent_tracker/analytics/heatmap.py:154-160`.
   - **Impact**: Live heatmap overlay fails every frame with `AttributeError` (silently swallowed in `logger.debug`). Even with `heatmap.draw`, `OccupancyHeatmap` initializes to `640x480` before 16:9 `probe_capture_dimensions` resizes frames to `640x360`, crashing `cv2.addWeighted` on shape mismatch.

5. **`P0-5` Split-Brain `WorldGraph(event_bus=None)`, Unshared `ConfidenceEngine` & Startup `TRC-017` Crash**
   - **Evidence**: `dashboard/camera_pool.py:51` (`WorldGraph(coordinate_mapper=...)` with `event_bus=None`); `intelligent_tracker/pipeline/bundle.py:234,304` (per-stream `ConfidenceEngine`, skips attaching `event_bus` when `world_graph` passed); `dashboard/app.py:171`; `dashboard/dependencies.py:286-294` (`confidence_engine=None` fallback); `dashboard/services/camera_config_store.py:89-91` -> `dashboard/services/stream_pool_coordinator.py:93` (`TRC-017`).
   - **Impact**: Dashboard `WorldGraph` mutations never emit reactive events; multi-camera `cam_02` observations mutate an isolated `ConfidenceEngine` invisible to `WorldQueryEngine` (`app.state`); offline Active Learning feedback skips confidence updates; and `cameras.json` containing `{"cameras": [...]}` or any non-dict entry crashes boot with `AttributeError: 'list' object has no attribute 'get'`.

### P1 — Core Pipeline, Replay, Lifecycle & Persistence Bugs (8)

6. **`P1-6` `capture_only` Freezes `annotated=True` MJPEG Feeds**: `dashboard/services/stream_worker.py:166-172` skips `_encode_annotated_frame()`, while `dashboard/services/stream_media.py:77-82` keeps returning the stale `_latest_jpeg` placeholder/previous frame instead of falling back to `_latest_raw_jpeg`, freezing `/stream/{id}`, Burned-Box mode, and `2x2` MJPEG fallback tiles.
7. **`P1-7` Inference-Latency FPS Reported as Stream FPS**: `intelligent_tracker/pipeline/frame_processor.py:121,133-136` computes `1.0 / processing_s` (e.g. `2000+ FPS` on Mock or `100 FPS` while throttled to `1 FPS`), and `dashboard/services/stream_worker.py:145-146,172,180-181` prefers `step_res.fps` over `vs.measured_fps`. `VideoSource` also fails to clear `_measured_fps` on `pause()`, and `capture_worker.py:324-325` caches `effective_fps` once across reconnects.
8. **`P1-8` Stream Restart Wipes `WorldGraph` & Scenarios + Teardown/Lock Leaks**: `WorldGraph.register_camera` (`intelligent_tracker/world/graph.py:66-71`) overwrites `homography`/`world_pose`; `bundle.py:305-310` hardcodes `name=config.camera_id`; `restart_stream` and `retry_camera_connection` (`dashboard/services/stream_pool_coordinator.py:137-164`) never re-run `ScenarioManager.apply_to_stream_manager(new_mgr)`; `DELETE /api/scenarios/homography/{id}` (`dashboard/routers/scenarios.py:259-276`) leaves stale matrices in `WorldGraph` and `GlobalCoordinateMapper`; `StreamManager.stop()` (`dashboard/stream_manager.py:245-261`) never calls `self._pipeline_bundle.close()`; disabled/offline cameras are absent from `WorldGraph` and omit `is_armed`; `CameraPool._lock` is held across blocking init.
9. **`P1-9` `REPLAY` <-> `LIVE` & Mode Transition Races**: `AnalyticsScheduler.should_schedule_frame` (`intelligent_tracker/pipeline/analytics_scheduler.py:165-166`) returns early on `paused`/`capture_only` without resetting `last_tier`/`last_target_fps` (and `build_live_step_result` omits `decision` at `231-233`); `LIVE -> REPLAY` hot-swap (`async_inference_worker.py:238-239`) leaves stale async cache and allows concurrent in-flight mutation of `analytics`/`gallery_matcher`; `FileDetectionReplayProvider.ensure_loaded()` (`file_detection_replay.py:208-209`) stays stuck in `REPLAY` after run deletion; live looping files without replay never reset tracker/analytics centroids; `VideoSource.read()` (`source.py:83-84`) silently restarts `loop_video=False` files after EOF.
10. **`P1-10` Hibernation & Multiview Lifecycle Bugs**: `StreamWorker.run()` (`stream_worker.py:130-134`) runs `with vs:` (`wait_ready()` up to 3s + hardware open) before checking `_handle_hibernation()`; `StreamSubscriberRegistry` (`stream_subscribers.py:68-72,120-124`) calls `vs.resume()` even under `paused` mode; `build_camera_status_row()` (`camera_pool_queries.py:16-26`) ignores `is_hibernating`; `StreamLifecycleManager.evict_subscribers()` (`lifecycle.py:158-160`) omits `_subscriber_modes`; `FrameSurface.draw` (`frame_surface.js:82`) drops new frames after stream restart `seq` reset (`camera_grid.js:44`); `camera_grid.js:237,287` mismatches `2x2` degraded pagination vs `3x3`/`4x4` WS subscription.
11. **`P1-11` Offline Video Studio, FTS & Citation Leaks**: `_gallery_signals.py:153-157` drops `video_filename`/`media_offset_sec` in `fts_index.index_sighting()`; `query_engine.py:38-53` drops media fields from citations; `post_detection_governance.py:115-119` drops `zone_id` when converting `EntityIdentifiedEvent`; `video_analytics_service.py:193` + `batch_reporting.py:107-110` aggregate global DB sightings into per-video reports; `video_jobs.py:201-217` omits `scenario_camera_id` query param; `analytics.py:90-108` mixes `_resolve_analytics_db` and `Depends(get_db)`.
12. **`P1-12` ROI Tagging & Live Track Propagation Gaps**: `RoiRecognitionService.commit_roi_tag` (`roi_recognition_service.py:259-290`) writes `is_anchor=0, locked=0`, skips `record_descriptor_version`, `ConfidenceEngine`, `EventFTSIndex`, and live `Track`/`WorldEntityBridge` updates, and silently falls back to frame `0` on seek failure (`135-137`); `EntityTaggerService._update_live_track_identity` (`entity_tagger.py:120-122`) skips `entity_id`, `entity_category`, `identity_label`, and `WorldEntityBridge.reassign_track()` (and `94` uses 1s `int(time.time())` filenames).
13. **`P1-13` Persistence, Security & Thread-Safety**: `BackupManager.restore_backup` (`backup.py:190-261`) lacks ZIP symlink rejection, WAL/SHM cleanup, and `hot_reload` handling; 9/10 repository mixins omit `if self._conn is None` guards; `ScenarioManager` (`scenarios.py:52`) and `VideoIndexer` (`batch.py:153`) leak `TrackerDB` handles (`TRC-018`); `CaptureReadGuard` (`capture_guard.py:206-215,227-235,271-279`) mixes `time.time()` and mutates state outside lock; `lifecycle.py:35-58` holds `self._lock` across open and pins un-stopped instances in `atexit`; `stream_media.py:64-67` accesses missing `SortTracker.tracks`; `world/minimap.py:106` mixes uncalibrated pixel polygons into meter-scale bounds.

### P2 — Frontend–Backend Contracts, UI Wiring & Unwired Capabilities (10)

14. **`P2-14` Review & Learn Queue Schema Drift & 404 Assets**: `dashboard/static/review_and_rsac.js:106-149,200` reads `item.similarity_score`, `item.matched_entity_name`, `item.created_at`, `item.notes`, and `data.entity_name` while backend emits `similarity`, `suggested_name`, `timestamp`, no `notes` column (`schema_manager.py:111-118`, `learning_repo.py:60-74`), and `{status, item_id, entity_id, notes}` (`active_learning_actions.py:165`); `cropUrl` prefixes `/` onto `data/crops/...` (`app.py:240-241` has no `/data` mount) and `onerror` requests non-existent `/static/avatar-placeholder.png` (also in `gallery_timeline.js:53,58,172`).
15. **`P2-15` Video Studio Click-to-Tag `track?.id` vs `track_id`**: `dashboard/static/js/interactive_canvas.js:156,160,169` reads `track?.id` whereas `Track.to_dict()` (`intelligent_tracker/tracker/track.py:146`, served by `/api/videos/{fn}/detections`) emits `track_id`, showing `#undefined` and sending `track_id: null`.
16. **`P2-16` Security Alerts Schema Drift**: `dashboard/static/js/analytics_view.js:99-121` and `telemetry.js:151` read `ev.entity_name` instead of `ev.name` (`events/types.py:190,205`), ignore `ev.severity` in favor of substring matching (classifying `rsac_violation` as `INFO`), ignore `ev.message`/`reason`/`title`/`summary`, and show `Snapshot: None` for DB-merged `world_timeline_events`.
17. **`P2-17` Live Monitor Overlay Toolbar & BEV PiP Mismatch**: `dashboard/static/js/studio_overlays.js:35,56` posts to Scenario Studio's `state.activeCamera` (404/422 if recorded video or empty) and sends unsupported `toast_prompts` (`schemas.py:163-173`, `stream_manager.py:46-52`) while `clutter` has no toggle; `#overlay-toggle-bev_minimap` (`live.html:144-147`) has no client-side renderer (`unified_canvas_overlay.js:16-19`).
18. **`P2-18` Camera Manager CRUD & Diagnostics Drift**: `dashboard/static/js/camera_manager.js:226-234,284-296` maps `cam.type` onto vendor-only `#cam-preset-select` (clobbering `usb`/`synthetic`/`video_file` to `'rtsp'`), hardcodes `enabled: true`, sends unaccepted `device_name` (`schemas.py:49-78`), and races async `loadCapabilities()` vs synchronous `setValues()`; `camera_modals.html:189` Cancel bypasses `closeModal()`/`resetForm()`; `camera_discovery.js:188` omits `device_name`/`type`; `camera_diagnostics_ui.js:121` calls non-existent `CameraManager.getActiveCameras()`.
19. **`P2-19` Enroll & Quick-Tag Modal Failures**: `#btn-quick-tag` (empty tracks, `app.js:271-273`) and `#btn-enroll-modal` (`gallery_timeline.js:119-121`) submit `bbox: null, crop_base64: null` to `/api/tag/commit` -> HTTP 400 (`roi_recognition_service.py:171`); `#enroll-camera-select` (`entity_modals.html:124-126`) is never populated; `universal_enrollment.js:190-193,231` blocks image uploads without a camera and leaves stale `selectedCropBase64`/`selectedBbox` after reset; `app.js:159-168,304-313` opens modals directly without init callbacks.
20. **`P2-20` Scenario Studio & BEV Minimap Coordinate/Video Bugs**: `dashboard/static/js/bev_minimap.js:46-52,73-78` renders uncalibrated pixel `ground_pos` (`[320, 240]`) as meters and divides zones by hardcoded `640x480` instead of `homography_matrix`, while `studio.html:50` hardcodes `"Calibrated"`; `studio.html:40` + `studio_canvas.js:9-17` scale against hardcoded `640x480` without `computeContainBox` and never render saved shapes; `studio.js:86-93,116,188-199,291-293` omits initial live attach, silently drops 422s on empty `camera_id: null`, and `live_player.js:207-211` overwrites recorded-video selection with `/stream/<filename>` (HTTP 503) on tab re-entry.
21. **`P2-21` Dead/Broken Controls, Races & Selector Collisions**: `#fullscreen-btn` (`live.html:35`) has no click listener (`live_player.js:234,270-272`); `gallery_timeline.js:81-89,226-229` races `.btn-view-sightings` filter dropdown load and opens continuous MJPEG stream on `#btn-snapshot-save`; `journey_search.js:80,101` never sends `track_id` and triggers 422 via `isNaN("") === false`; `analytics_view.js:138,150` omits `?camera_id=`; `rsac_versions.js:41-43` reads missing `similarity_to_anchor`; `interactive_canvas.js:81-87,157` drops COCO labels on `#tag-category-select`; `camera_ai_config.js:126-133` binds global `.btn-tag-preset` across unrelated modals.
22. **`P2-22` SPA Boot, Cache, Socket & Hygiene Bugs**: `index.html:152-153` loads `app.js` before `nav_tabs_manager.js`, so initial `#videos`/`#studio` hash routes run before `window.switchTab` is wrapped; `nav_tabs_manager.js:13-49` caches `/api/cameras` and `/api/videos` for `2000ms` without invalidating on mutations; `telemetry.js:29,69-76` omits `?token=` and leaks reconnect timers after `closeWebSocket()`; `camera_grid.js:235-249,303,318` resumes paused grids on `refreshCameras()` and leaks non-live `#live-stream-img` attaches; `video_batch.js:64-75` loads scenarios from `/api/cameras` instead of `/api/scenarios`; `camera_recording.js:175-182` does not refresh `ProcessingModeUI` on deferred jobs; `scrubber_library_bridge.js:118-123` + `video_jobs.js:446` miss active-video checks; `index.html:100,103,112` drawer badges are never updated; `studio_overlays.js:79,96,122` + `gallery_timeline.js:182` interpolate unescaped inline `onclick` literals.
23. **`P2-23` Unwired Backend Capabilities**: `/api/world/*` (`query`, `confidence/{entity_id}`, `timeline`, `snapshot`, `entities`), `/api/rsac/rules`, `/api/pets/whitelist`, `/api/topology/world-map`, `/api/topology/priors`, `/api/cameras/{id}/retry`, and `/api/system/{processes,metrics,events,models}` have zero UI callers in `dashboard/static/`.

### P3 — Suspected Edge Cases for Empirical `/app-debugger` Probes (5)

1. **`MotionGate` Stale-Background False Burst (`intelligent_tracker/pipeline/motion_gate.py:80-98`)**: Hibernating/resuming an `armed` camera leaves old `bg_luma` intact, likely triggering a false 3-second P1 motion burst on wakeup.
2. **File Slow-Disk Timeout Severing (`intelligent_tracker/video/capture_worker.py:307-318`)**: A single disk read timeout (`is_severed=True`) on a `video_file` (`is_file=True`) kills the capture thread instead of reopening the file.
3. **`MultiviewSession._flush_camera` Slow-Client HOL Blocking (`dashboard/services/multiview/session.py:284-285,321`)**: Sequential per-camera `send_timeout_s=0.5` stalls other camera tiles when one WS client stalls, and `wait_for` cancellation can drop partial ASGI sends.
4. **FFmpeg Container `CAP_PROP_POS_FRAMES=0` Rewind Failure (`intelligent_tracker/video/capture_helpers.py:70`)**: Containers ignoring `POS_FRAMES=0` hit 6 failed reads and trip `CaptureReadGuard` `RECONNECTING` before reopen.
5. **1 FPS P1 Heartbeat Triggering False `AI Lag` Badge (`dashboard/static/js/live_player.js:11,53`)**: Idle `armed` 1 FPS heartbeat produces `(now - inf_ts) * 1000.0` up to `~999ms`, exceeding `LAG_THRESHOLD_MS = 120` when inspected.

---

## 6. Why Integration Bugs Slipped Past Existing Tooling — & Recommended Enhancements

### Blind-Spot & Tool Enhancement Matrix

| Blind Spot Category | Concrete Example Missed | Why Current Checks Missed It | Recommended Tool / Probe Enhancement |
| :--- | :--- | :--- | :--- |
| **False-Green Workspace Probes** | `replay_pipeline_probe.py:69-75` passed with `hd_track_x1: None` (missing `else: failures.append(...)`); `video_studio_contract_probe.py:82-90` only grepped 2 strings | Probes omitted strict assertions on skipped branches and never booted headless CDP across all 9 SPA tabs | Enforce non-empty assertion guards in `replay_pipeline_probe.py`; add a 9-tab headless CDP probe (`diagnose.py ui --capture-runtime`) exercising hash routing, tabs, modals, and live WS payloads |
| **`surface_scanners.py` & `surface_verifier.py` Gaps** | `P2-14`–`P2-22` (`similarity_score`, `track?.id`, `ev.entity_name`, `/data/crops/*`, `/static/avatar-placeholder.png`, missing `?token=`) | `walk_source_files(..., include_tests=True)` mixes test IDs/routes into production pools; verifier ignores HTTP methods, `img.src`/`video.src`/`new WebSocket`/`window.open` URLs, inline `onclick` targets, and JSON request/response keys | Filter `include_tests=False` by default in `surface --verify`; verify HTTP methods, asset/WS URLs, and inline `onclick` targets; add OpenAPI/Pydantic/SQLite-to-JS JSON key contract checks |
| **`shadow_prober.py` & `static_auditor.py` Gaps** | `P0-1` monotonic-vs-epoch leakage (`async_inference_worker.py:266` -> `FrameProcessor` -> `RSAC`/`ConfidenceEngine`), `P0-2` AB-BA lock inversion, `P0-4` `draw_heatmap_overlay()`, `P2-18` `getActiveCameras()`, `P1-13` `SortTracker.tracks` | `shadow_prober.py` is single-file AST only (`MIXED_CLOCK_DOMAIN` missed cross-module calls); no cross-module attribute/method resolver or lock-order graph checker; `ruff`/`mypy` not installed in the project virtualenv (`[typecheck] SKIPPED`) | Install `ruff` + `mypy` in project dependencies; add cross-module attribute/method checker (and JS global member checker), lock-acquisition order graph rule, and pipeline clock-domain taint rule (`monotonic` vs `epoch`) |
| **`trace_recorder.py` Test Noise & Mock Isolation** | Intentional unit-test exceptions (`TRC-012` x287, `TRC-013` x52) clutter `.diagnostics/trace_catalog.json` alongside real `TRC-017` and `TRC-018`; synthetic `now=1.0` & `SimpleNamespace` stubs masked `P0-1`, `P0-2`, `P0-3`, `P0-4` | Test runner shares workspace `.diagnostics/` without filtering intentional fault-injection tests; unit tests substitute permissive stubs for `VideoSource`, `StreamManager`, and real clocks | Exclude/isolate test-runner traces from production `trace_catalog.json`; expand `.diagnostics/probes/` with unmocked multi-camera `PipelineEngine` + `ProcessingModeService` + `StreamRecordingController` real-clock + `1920x1080` `CentroidTracker` multi-step stress probes |

### Recommended `/app-debugger` + Upgraded Tooling Workflow (Scenario Matrix)

| Phase / Objective | Target Scope | Recommended Runnable Command |
| :--- | :--- | :--- |
| **1. Pre-Fix Surface & Static Gate** | Routes, IDs, `window.*`, JSON schemas, clock/attribute/lock smells | `python skills/system-diagnostics/scripts/diagnose.py surface --verify --strict; python skills/system-diagnostics/scripts/diagnose.py scan --path intelligent_tracker dashboard scripts --strict` |
| **2. Unmocked Integration Probes** | Cold boot, `1920x1080` multi-step replay, recording AB-BA lock, real-clock memory | `python skills/system-diagnostics/scripts/diagnose.py probe run cold_boot_world_probe; python skills/system-diagnostics/scripts/diagnose.py probe run replay_pipeline_probe; python skills/system-diagnostics/scripts/diagnose.py probe run video_studio_contract_probe` |
| **3. Headless 9-Tab Runtime CDP** | Console errors, uncaught JS exceptions, HTTP >= 400, layout overflows across `#live`..`#world` | `python skills/system-diagnostics/scripts/diagnose.py ui --url "$APP_URL" --headless --capture-runtime --audit-layout --strict` |
| **4. Post-Fix Regression & Docs Gate** | Full Python/JS suite, modularity budgets, zero-warning Sphinx build | `MPLBACKEND=Agg python -m unittest discover tests; python skills/system-diagnostics/scripts/diagnose.py arch-map --path .; python -m sphinx -W --keep-going documentation/ documentation/_build/html/` |
