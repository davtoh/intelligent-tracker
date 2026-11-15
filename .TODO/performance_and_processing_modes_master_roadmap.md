# Master Roadmap: Dashboard Performance Optimization & Hybrid Processing Modes

> **How to use this document**: This is the authoritative 4-Step Master Roadmap resolving UI throttling, HTTP/1.1 connection pool saturation, asyncio event-loop blocking, double JPEG encoding, and SQLite/disk lock contention, while introducing **Hybrid Auto-Focus + Manual Processing Modes** (`focus_only` default, `full_realtime`, `capture_only` with deferred `VideoIndexer` queue, and `paused`).
> **Rule for Planners & Agents**: Evaluate and execute **one Step at a time** via dedicated Child Implementation Plans (`.TODO/step_<N>_<slug>.md`) linked with `plan_engine.py init .TODO/step_<N>_<slug>.md --parent performance_and_processing_modes_master_roadmap --milestone <N>`. Before drafting each Child Plan, run `diagnose.py arch-map --path .` and `diagnose.py audit` on target files so every slice respects the 350-line file and 40-line function budgets.

---

## Empirical Baseline Summary (`$APP_URL`)

Measured against `$APP_URL` (`scripts/run_dashboard.py --local`) and the `main..HEAD` branch diff (`64` files):

| # | Observed Symptom | Empirical Evidence (`$APP_URL`) | Root Cause | Primary Target(s) |
|---|---|---|---|---|
| 1 | **UI & API requests stall 1.3s–3.2s despite low CPU** | `/favicon.ico` (`322 B`) took `2474 ms`; `/api/videos` (`6.7 KB`) took `1320–2848 ms`; `/api/cameras` took `1340–3189 ms` | HTTP/1.1 6-connection pool saturation: hidden tabs keep open connections on boot (`#studio-live-img`, `#static-heatmap-img`) alongside `#live-stream-img`, WebSockets (`/ws/*`), and eager `/videos/*.mp4` 206 preloads | `dashboard/static/partials/tabs/studio.html`, `dashboard/static/partials/tabs/analytics.html`, `dashboard/static/js/nav_tabs_manager.js`, `dashboard/static/js/live_player.js` |
| 2 | **Heavy startup payload & duplicate fetches** | `/api/videos`, `/api/cameras`, and `/reports` (`1.10 MB` x2) fetched twice on load; `/detections` (`833 KB` + `265 KB`) fetched while on `#live`; `4 Hz` (`250ms`) BEV minimap timer | Un-deduplicated boot `fetch()` calls, eager cross-tab report/detection loading, and unconditional `250ms` `renderBEVMinimap()` interval | `dashboard/static/studio.js`, `dashboard/static/js/scrubber_library_bridge.js` |
| 3 | **167 server threads & double JPEG encode per frame** | Server process spawned `167` threads, `771.7 MB` RAM, `276.5s` CPU in ~60s across all 3 cameras at boot | `CameraPool` starts all cameras eagerly; `StreamWorker` executes `FrameProcessor.step()` plus two `cv2.imencode(".jpg")` passes (raw + annotated) per frame even with 0 subscribers | `dashboard/services/stream_worker.py`, `dashboard/services/stream_subscribers.py`, `dashboard/services/stream_pool_coordinator.py` |
| 4 | **Event loop freezes on ROI tag & sync jobs** | WebSocket telemetry and concurrent HTTP endpoints stall during ROI click/drag | `async def` routes run synchronous OpenCV seek/decode, detector/Re-ID inference, `reload_all_galleries`, and disk writes directly on the asyncio event loop | `dashboard/routers/tagging.py`, `dashboard/routers/video_jobs.py` |
| 5 | **SQLite lock contention & repeated disk JSON reads** | `/api/active-learning/queue` took `2850 ms` | `migrate_legacy_json_for_aliases()` re-reads disk JSON on every report API call; `save_video_run()` re-queries and re-parses multi-MB `frame_detections_json` blobs | `dashboard/services/video_report_migration.py`, `intelligent_tracker/repositories/video_run_repo.py` |

---

## Step 1: Asyncio Event-Loop Offloading, On-Demand JPEG Encoding & Storage Contention Fixes
- [x] **Child Plan**: `.TODO/step_1_event_loop_and_on_demand_encoding.md`
- [x] **Goal**: Offload synchronous OpenCV/ML/DB work from FastAPI async routes via `asyncio.to_thread()`, track raw vs. annotated subscriber counts so `StreamWorker` skips unsubscribed JPEG compression, cache completed legacy JSON report migrations per file mtime, and eliminate redundant multi-MB detection re-reads in `save_video_run()`.
- [x] **Pre-Plan Evaluation Check**: Run `diagnose.py audit --path dashboard/routers/tagging.py dashboard/routers/video_jobs.py dashboard/routers/streaming.py dashboard/services/stream_subscribers.py dashboard/services/stream_worker.py dashboard/services/video_report_migration.py intelligent_tracker/repositories/video_run_repo.py`.
- [x] **Target Scope**:
  - [x] Offload `recognize_roi_endpoint`, `commit_roi_tag_endpoint`, and `reload_all_galleries` in `dashboard/routers/tagging.py` plus sync transcode/analyze branches in `dashboard/routers/video_jobs.py` via `asyncio.to_thread()`.
  - [x] Extend `StreamSubscriberRegistry` (`dashboard/services/stream_subscribers.py`) and `/stream/{camera_id}` (`dashboard/routers/streaming.py`) with annotated vs. raw subscriber tracking so `StreamWorker` (`dashboard/services/stream_worker.py`, kept `< 345L`) skips `_encode_raw_frame` and `_encode_annotated_frame` when unsubscribed.
  - [x] Add mtime-aware migration caching in `dashboard/services/video_report_migration.py` and avoid re-querying/re-parsing `frame_detections_json` inside `VideoRunRepositoryMixin.save_video_run()` (`intelligent_tracker/repositories/video_run_repo.py`).
- [x] **Definition of Done**: Zero blocking CV/DB calls on the asyncio event loop in tagging/video_jobs routes; 0-subscriber and single-mode subscriber streams skip redundant JPEG encodes; legacy report migration executes once per file mtime; all Step 1 unit tests and `diagnose.py audit` checks pass.

---

## Step 2: Tab-Scoped Streams, Lazy Tab Data & Startup Fetch Deduplication
- [x] **Child Plan**: `.TODO/step_2_tab_scoped_streams_and_lazy_loading.md`
- [x] **Goal**: Eliminate HTTP/1.1 6-connection pool saturation and multi-MB startup bottlenecks by disconnecting hidden-tab MJPEG/heatmap streams, pausing Live MJPEG when leaving the `#live` tab, gating the 250ms BEV minimap timer, deduplicating boot fetches, and deferring `/reports` and `/detections` until `#videos` is opened.
- [x] **Pre-Plan Evaluation Check**: Run `diagnose.py audit --path dashboard/static/partials/tabs/studio.html dashboard/static/partials/tabs/analytics.html dashboard/static/js/nav_tabs_manager.js dashboard/static/js/live_player.js dashboard/static/studio.js dashboard/static/js/scrubber_library_bridge.js`.
- [x] **Target Scope**:
  - [x] Remove eager `src` attributes from `#studio-live-img` (`dashboard/static/partials/tabs/studio.html`) and `#static-heatmap-img` (`dashboard/static/partials/tabs/analytics.html`), binding/unbinding stream URLs on tab activation in `dashboard/static/js/nav_tabs_manager.js` and `dashboard/static/js/live_player.js`.
  - [x] Gate the 250ms `renderBEVMinimap()` interval in `dashboard/static/studio.js` (`< 345L`) to run only when `#studio` is the active tab.
  - [x] Deduplicate concurrent `/api/videos` and `/api/cameras` boot requests and defer `/api/videos/{filename}/reports` and `/detections` fetches in `dashboard/static/js/scrubber_library_bridge.js` until the `#videos` tab is active.
- [x] **Definition of Done**: Initial load on `#live` opens at most 1 MJPEG stream (`#live-stream-img`), zero hidden-tab streams, zero `/reports` or `/detections` fetches, and API responses complete in `< 500ms`.

---

## Step 3: Backend Processing Modes (`Focus Only`, `Full Real-Time`, `Capture-Only`, `Paused`) & Deferred Queue
- [ ] **Child Plan**: `.TODO/step_3_backend_processing_modes_and_hibernation.md`
- [ ] **Goal**: Introduce `ProcessingModeService` and `/api/system/processing-mode` supporting `focus_only` (default), `full_realtime`, `capture_only`, and `paused` modes with smart camera hibernation and automatic deferred `VideoIndexer` queueing when `capture_only` recordings complete.
- [ ] **Pre-Plan Evaluation Check**: Run `diagnose.py audit --path dashboard/services/stream_worker.py dashboard/services/stream_recording.py dashboard/services/stream_pool_coordinator.py dashboard/app.py`.
- [ ] **Target Scope**:
  - [ ] Create `dashboard/services/processing_mode_service.py` (`< 200L`) and `dashboard/routers/processing_mode.py` (`< 120L`, mounted in `dashboard/app.py`) managing `mode` (`focus_only` default, `full_realtime`, `capture_only`, `paused`), `focused_camera_id`, and `active_tab`.
  - [ ] Integrate `ProcessingModeService` with `StreamWorker` and `StreamPoolCoordinator` so unfocused cameras hibernate in `focus_only` mode (unless actively recording) and all cameras pause AI when `active_tab != "live"` (unless recording or in `full_realtime`).
  - [ ] In `capture_only` mode, record raw MP4 frames in `StreamRecordingController` without per-frame `FrameProcessor.step()` and auto-submit an async `VideoIndexer` job to `VideoJobsService` when recording stops.
- [ ] **Definition of Done**: Switching between `focus_only`, `full_realtime`, `capture_only`, and `paused` deterministically controls per-camera AI/capture threads and queues deferred `VideoIndexer` jobs on `capture_only` recording completion.

---

## Step 4: Top-Bar Processing Mode Selector UI, Tab Visibility Auto-Sync & E2E Benchmark
- [ ] **Child Plan**: `.TODO/step_4_processing_mode_ui_and_e2e_verification.md`
- [ ] **Goal**: Add a compact Processing Mode selector pill in the dashboard header bar persisted in `localStorage`, wire automatic focus/tab-visibility state synchronization with the backend, and verify end-to-end responsiveness and modularity budgets.
- [ ] **Pre-Plan Evaluation Check**: Run `diagnose.py audit --path dashboard/static/index.html dashboard/static/js/nav_tabs_manager.js dashboard/static/js/live_player.js`.
- [ ] **Target Scope**:
  - [ ] Create `dashboard/static/js/processing_mode.js` (`< 220L`) and `dashboard/static/css/processing_mode.css` (`< 140L`) rendering the header Processing Mode selector (`Focus Only` [Default], `Full Real-Time`, `Capture-Only`, `Paused`) without using `!important` or exceeding `index.html`'s `< 180L` budget.
  - [ ] Persist operator mode selection in `localStorage` and sync `mode`, `focusedCameraId`, and `activeTab` transitions to `POST /api/system/processing-mode`.
  - [ ] Add end-to-end unit, Node VM, and CDP layout/responsiveness verification tests.
- [ ] **Definition of Done**: Header mode selector switches modes seamlessly, persists across reloads, passes WCAG AA touch-target and `0px` overflow checks, and full test + Sphinx suites pass.

---

## Scenario Combinations Matrix

| Real-World Scenario / Objective | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Inspect Master Roadmap Progress** | Plan Engine CLI | `status performance_and_processing_modes_master_roadmap` | `python "<config_dir>/skills/frontier-architect/scripts/plan_engine.py" status performance_and_processing_modes_master_roadmap --root .` |
| **Inspect Active Step 1 Child Plan Slice** | Plan Engine CLI | `next step_1_event_loop_and_on_demand_encoding` | `python "<config_dir>/skills/frontier-architect/scripts/plan_engine.py" next step_1_event_loop_and_on_demand_encoding --root .` |
| **Pre-Plan Architecture & Modularity Map** | Static Analyzer | `arch-map --path .` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" arch-map --path .` |
| **Static Modularity & Function Audit** | Static Auditor | `audit --path <targets>` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/routers/tagging.py dashboard/routers/video_jobs.py dashboard/services/stream_worker.py` |
| **Full Headless Regression Suite** | Unittest Runner | `MPLBACKEND=Agg` | `python -m unittest discover tests` |
