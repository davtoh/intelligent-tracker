# Step 2: Resource-Aware Analytics Scheduler (Child Plan)

> Parent: `.TODO/realtime_multiview_master_roadmap.md` (Milestone 3 / Step 2).
> Architecture Blueprint: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` & `AGENTS.md`.
> Goal: Guarantee continuous security-grade analytics across every `armed` camera within a bounded CPU/GPU budget (`motion -> alarm <= 2.0 s` SLA) using P0/P1/P2 priority scheduling, a `< 0.2 ms` `64x36` luma `MotionGate`, `dt`-aware time-sliced tracker persistence, 3-stage load shedding, and a zero-GPU `CachedReplayProvider` with live rule evaluation for pre-indexed `video_file` cameras.

---

## 1. Empirical Baseline, `AGENTS.md` Alignment & Architecture Audit

| # | Gap / Bottleneck in Current HEAD | Evidence (`arch-map` & Research Audit) | Root Cause | Target Resolution |
|---|---|---|---|---|
| 1 | Unfocused `armed` cameras stay awake for capture in `focus_only` but skip AI vision | `dashboard/services/processing_mode_service.py#L102-L114` checks `focused_camera_id` & `is_recording`, ignoring `is_armed` | `should_run_vision_step()` lacks `is_armed` awareness and has no background P1 cadence tier | Pass `is_armed` into `should_run_vision_step(camera_id, is_recording=False, is_armed=False)` (preserving `False` default for legacy invariant tests) and schedule unfocused `armed` cameras at P1 motion-gated cadence |
| 2 | `full_realtime` runs unthrottled per-camera inference with zero CPU/GPU budget or load shedding | `dashboard/services/stream_worker.py#L118` & `dashboard/services/async_inference_worker.py#L19-L104` run independent worker loops at full frame rate | No priority arbiter, motion gate, or global concurrency/FPS budget across pooled streams | Introduce `AnalyticsScheduler` (`P0`/`P1`/`P2` arbiter, global FPS & latency budget, 3-stage load shedding) + `64x36` luma `MotionGate` (`1 FPS` idle floor -> `8 FPS` motion burst, 15 s P1->P0 alarm promotion) |
| 3 | Sparse `1 FPS` P1 heartbeats delay track confirmation or drop tracks | `intelligent_tracker/tracker/sort.py#L135,#L264` & `intelligent_tracker/tracker/centroid.py#L42,#L77` use fixed frame counts (`min_hits=2..3`, `max_age`) | Frame-count retirement assumes contiguous 15–30 FPS capture rather than variable `dt` time-slicing | Add elapsed-time (`dt = now - last_seen`) persistence guard and adaptive burst confirmation so time-sliced P1 cameras satisfy `motion -> alarm <= 2.0 s` |
| 4 | Pre-indexed `video_file` replay bypasses GPU but skips all zones, tripwires, RSAC rules, and alarms | `dashboard/services/async_inference_worker.py#L144-L147` returns `FileDetectionReplayProvider.build_step_result()` with `analytics={}` before `FrameProcessor.step()` | `FileDetectionReplayProvider` (`dashboard/services/file_detection_replay.py#L262-L285`) only hydrates `ReplayTrack` bboxes and never invokes `AnalyticsEngine`, `RSACManager`, `EventBus`, or `WorldEntityBridge` | Extract `intelligent_tracker/pipeline/post_detection_governance.py` and upgrade replay via `CachedReplayProvider` so pre-indexed `video_file` cameras consume **0 GPU/scheduler slots** while running full live rule/alarm evaluation with loop wrap-around reset |
| 5 | `FrameProcessor` exceeds class/function modularity budgets; `processing_mode.js:83` reads wrong key | `intelligent_tracker/pipeline/frame_processor.py` has 14 methods (`<= 12` cap) and `_publish_id_events` is 54 L (`<= 40 L` cap); `dashboard/static/js/processing_mode.js#L83` reads `data.cameras` instead of `data.camera_states` | Monolith accumulation in `FrameProcessor`; schema key mismatch in `processing_mode.js` (`218 L / < 220 L` cap) | Extract post-detection governance out of `FrameProcessor` (`<= 12` methods, functions `<= 40 L`), fix `data.camera_states` in `processing_mode.js`, and place scheduler HUD logic in `dashboard/static/js/scheduler_hud.js` |

---

## 2. 3-Tier Architectural Options & `/grill-me` Decision Summary

1. **Tier 1 — Pragmatic Baseline**: Keep isolated per-camera `AsyncInferenceWorker` loops and add a static per-camera FPS token-bucket limiter without motion gating, tracker `dt` adaptation, or replay rule governance. *(Rejected: wastes GPU/CPU on static scenes and misses `<= 2.0 s` alarm SLA under load.)*
2. **Tier 2 — Frontier SOTA (Selected Direction)**:
   - **Integrated Mode Upgrade (Q1)**: `focus_only` runs the focused camera (and any recording or active-alarm camera) at **P0** (`12–15 FPS`) while automatically scheduling unfocused `armed` cameras at **P1** (`1.0 FPS` idle heartbeat -> `8.0 FPS` motion burst). `full_realtime` schedules all pooled cameras across **P0 / P1 / P2** under the shared CPU/GPU budget.
   - **64x36 Luma `MotionGate` + `dt`-Aware Tracker + 15 s P0 Alarm Hold (Q2)**: Downscaled `64x36` grayscale frame-differencing (`< 0.2 ms`) triggers immediate first-frame submission on motion and bursts P1 to `8.0 FPS`; any detection or rule hit promotes the camera to **P0** for `15.0 s`; elapsed-time (`dt`) tracker persistence prevents track loss across `1.0 FPS` heartbeats (`motion -> alarm <= 2.0 s` SLA).
   - **Zero-GPU `CachedReplayProvider` with Live Rule Governance + Multi-Pass Idle Refinement Hook (Q3)**: Pre-indexed `video_file` cameras consume **0 scheduler/GPU slots** while running replayed tracks through live post-detection governance (`AnalyticsEngine` zones/tripwires/RSAC/pet whitelist + `EventBus` alarms + `WorldEntityBridge`) with video-loop wrap-around state reset. Unindexed `video_file` cameras fall back to normal P0/P1/P2 scheduling. Exposes an extensible `IdleRefinementHook` interface (Pass 1 live/replay vs future Pass 2/3 idle descriptor reinforcement & false-positive pruning).
   - **Central Budgeted Arbiter + 3-Stage Load Shedding + `scheduler_hud.js` (Q4)**: Keeps `AsyncInferenceWorker` as the per-camera facade delegating to `AnalyticsScheduler`. Enforces a 3-stage shedding cascade (`Stage 1 Normal` -> `Stage 2 Elevated`: shed P2 to `0 FPS`, step P1 burst `8 -> 4 FPS` -> `Stage 3 Critical`: cap P0 at `8–10 FPS` while guaranteeing P1 `>= 1.0 FPS` floor + optional deferred-indexing hook) and surfaces scheduler telemetry in `/api/system/processing-mode` and `dashboard/static/js/scheduler_hud.js`.
3. **Tier 3 — Novel Moonshot**: Dynamic cross-camera `$B \times 3 \times 640 \times 640$` ONNX tensor micro-batching + `WorldGraph` topological pre-warming. *(Deferred: local ONNX exports use fixed batch dimension `1` and would require model re-export).*

---

## 3. Modularity Budgets & Placement ("Split-Before-You-Grow")

| Module | Current | Enforced Cap | Step 2 Placement & Budget Strategy |
|---|---:|---:|---|
| `intelligent_tracker/pipeline/motion_gate.py` *(New)* | 0 L | `< 160 L` / `<= 8` methods | Pure CPU `64x36` luma `MotionGate` + per-camera motion burst state |
| `intelligent_tracker/pipeline/analytics_scheduler.py` *(New)* | 0 L | `< 280 L` / `<= 10` methods | `AnalyticsScheduler` P0/P1/P2 arbiter, 3-stage load shedding, SLA tracker, `IdleRefinementHook` protocol |
| `intelligent_tracker/pipeline/post_detection_governance.py` *(New)* | 0 L | `< 180 L` / `<= 6` functions | Extracted post-detection governance (`AnalyticsEngine`, RSAC, `EventBus`, `WorldEntityBridge`) shared by `FrameProcessor` and `CachedReplayProvider` |
| `intelligent_tracker/pipeline/frame_processor.py` | 340 L / 14 methods | `< 350 L` / `<= 12` methods / `<= 40 L` fn | Delegate post-detection governance & `_publish_id_events` to `post_detection_governance.py` (reducing methods to `<= 12` and max function length to `<= 40 L`) |
| `dashboard/services/cached_replay_provider.py` *(New)* | 0 L | `< 220 L` / `<= 8` methods | Zero-GPU `CachedReplayProvider` wrapping `FileDetectionReplayProvider` + live `evaluate_tracks_governance()` + loop wrap-around reset |
| `dashboard/services/processing_mode_service.py` | 209 L / 11 methods | `< 260 L` / `<= 12` methods | Add `is_armed: bool = False` to `should_run_vision_step()` and delegate scheduler state summary to `AnalyticsScheduler` |
| `dashboard/services/stream_worker.py` | 269 L / 12 methods | `<= 285 L` / `<= 12` methods | Pass `is_armed` in `_should_run_vision_step()` and delegate scheduling/replay orchestration to `async_inference_worker.py` (zero new methods on `StreamWorker`) |
| `dashboard/services/stream_pool_coordinator.py` | 224 L / 11 methods | `< 240 L` / `<= 12` methods | Share `AnalyticsScheduler` instance across pooled streams via `camera_source_bootstrap.py` |
| `dashboard/static/js/processing_mode.js` | 218 L | `< 220 L` | Fix `data.camera_states` lookup at `#L83` and delegate scheduler HUD rendering to `dashboard/static/js/scheduler_hud.js` |
| `dashboard/static/js/scheduler_hud.js` *(New)* | 0 L | `< 180 L` | Render P0/P1/P2/REPLAY badge, motion indicator, budget utilization, and load-shed stage |
| `dashboard/static/partials/tabs/live.html` | 210 L | `< 220 L` | Mount scheduler HUD pill dynamically via `scheduler_hud.js` (0–2 lines added to `live.html`) |

---

## 4. Milestones

### Milestone 1: Core `AnalyticsScheduler`, `64x36` `MotionGate`, `dt`-Aware Tracker & `ProcessingModeService` Armed P1 Integration

- [x] **intelligent_tracker/pipeline/motion_gate.py** *(New)*: Implement `MotionGate` (`< 160 L`, functions `<= 40 L`) using `64x36` luma resize (`cv2.cvtColor` + `cv2.resize` + `cv2.absdiff` / running EMA background delta, `< 0.2 ms` per frame), configurable pixel-change threshold and motion hold window (`default 3.0 s`), returning `MotionSample(motion_active, score, changed_ratio, first_trigger)` so the first motion frame schedules immediately without waiting for the next `1.0 FPS` heartbeat.
- [x] **intelligent_tracker/pipeline/analytics_scheduler.py** *(New)*: Implement `AnalyticsScheduler`, `PriorityTier` (`P0`, `P1`, `P2`, `REPLAY`), `LoadShedStage` (`NORMAL`, `ELEVATED`, `CRITICAL`), `ScheduleDecision`, and `IdleRefinementHook` protocol (`< 280 L`, `<= 10` methods, functions `<= 40 L`). Support:
  - [x] **P0 (`12–15 FPS`)**: Focused camera on `live` tab, active recording camera, or any camera inside its `15.0 s` active-alarm follow-up hold (`promote_alarm(camera_id, duration_s=15.0)`).
  - [x] **P1 (`1.0 FPS` idle floor -> `8.0 FPS` motion burst)**: Armed cameras (`is_armed=True`) with zones/tripwires/RSAC rules; immediate slot grant on `first_trigger` motion to satisfy `motion -> alarm <= 2.0 s` SLA.
  - [x] **P2 (`1.0 FPS` in `full_realtime`, `0 FPS` in `focus_only`)**: Unarmed background cameras.
  - [x] **Global Budget & 3-Stage Load Shedding**: Track rolling inference FPS, active concurrency (`SCHEDULER_MAX_CONCURRENT_INFERENCES`), and EWMA inference latency (`ms`). Under `ELEVATED` pressure (`latency > 100 ms` or `utilization > 80%`), shed `P2 -> 0 FPS` and step P1 motion burst `8.0 -> 4.0 FPS`; under `CRITICAL` pressure (`latency > 250 ms`), cap `P0` at `8.0 FPS` while guaranteeing `P1 >= 1.0 FPS` floor, and notify optional deferred-indexing callback on sustained P1 motion shedding. When budget utilization `< 40%`, expose `maybe_run_idle_refinement()` hook for future Pass-2/3 descriptor refinement.
- [x] **intelligent_tracker/tracker/sort.py#L135-L270** + **intelligent_tracker/tracker/centroid.py#L40-L170**: Add elapsed-time (`dt = timestamp - track.last_seen`) persistence guard (`max_age_seconds: float = 2.5`) so tracks on time-sliced `1.0 FPS` P1 cameras are not prematurely deleted between heartbeats, and allow immediate track emission on time-sliced steps (`dt >= 0.4 s`) so `min_hits` does not stall P1 alarm detection beyond `<= 2.0 s`.
- [x] **dashboard/services/processing_mode_service.py#L23-L195**: Add `is_armed: bool = False` to `should_run_vision_step(self, camera_id: str, is_recording: bool = False, is_armed: bool = False) -> bool` so `is_armed=True` returns `True` in `focus_only` (while preserving `is_armed=False` default behavior for existing invariant tests); attach an `AnalyticsScheduler` instance and include `scheduler` summary + per-camera scheduler state (`priority_tier`, `target_fps`, `motion_active`, `alarm_hold_s`, `load_shed_stage`) in `_build_camera_states()` and `get_state()`.
- [x] **tests/test_analytics_scheduler.py** *(New)*: Unit tests (`<= 40 L` per test method) verifying `MotionGate` `< 1 ms` luma delta and immediate first-frame trigger, P0/P1/P2 cadence decisions across `focus_only` and `full_realtime`, 15 s P1->P0 alarm promotion, `motion -> alarm <= 2.0 s` SLA bound, 3-stage load shedding cascade (P2 shed first, P1 floor never starved to 0), `SortTracker`/`CentroidTracker` `dt`-aware persistence across `1.0 FPS` intervals, `IdleRefinementHook` invocation under spare budget, and `ProcessingModeService.should_run_vision_step(..., is_armed=True)`.
- [x] **CHANGELOG.md**: Record milestone completion via `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add`.

### Milestone 2: Zero-GPU `CachedReplayProvider` with Live Rule Governance & Runtime Pool Wiring *(Deferred to Next Turn / Milestone)*

- [ ] **intelligent_tracker/pipeline/post_detection_governance.py** *(New)* + **intelligent_tracker/pipeline/frame_processor.py#L61-L339**: Extract post-detection governance (`evaluate_tracks_governance(bundle, frame, tracks, timestamp)` running `AnalyticsEngine.update` for zones/tripwires/RSAC/pet whitelist, topology zone exits, Re-ID `_publish_id_events`, and `WorldEntityBridge` sync) into `post_detection_governance.py` (`< 180 L`, functions `<= 40 L`), reducing `FrameProcessor` from 14 methods to `<= 12` methods and eliminating the 54-line `_publish_id_events` audit overrun.
- [ ] **dashboard/services/cached_replay_provider.py** *(New)* + **dashboard/services/file_detection_replay.py#L174-L285**: Implement zero-GPU `CachedReplayProvider` (`< 220 L`, `<= 8` methods) wrapping `FileDetectionReplayProvider` and `bundle` governance:
  - When a `video_file` camera has a completed `TrackerDB` detection stream (`video_runs`), bypass `AnalyticsScheduler` GPU/YOLO budget completely (`0` inference slots consumed, `priority_tier="REPLAY"`).
  - Detect video loop wrap-around (`media_time_s` regression or `frame_idx == 0` wrap) and reset per-track zone dwell / tripwire crossing state cleanly so looping clips do not corrupt dwell timers or trigger duplicate wrap-around alert storms.
  - Execute `evaluate_tracks_governance()` on hydrated `ReplayTrack`s at live cadence so zones, tripwires, RSAC rules, pet whitelist, `EventBus` alerts, and `WorldEntityBridge` fire live without loading or running YOLO.
  - When no completed `TrackerDB` indexing run exists for the file, return `None` so the camera falls back seamlessly to standard P0/P1/P2 scheduled live inference.
- [ ] **dashboard/services/async_inference_worker.py#L19-L163** + **dashboard/services/stream_worker.py#L86-L149** + **dashboard/services/camera_source_bootstrap.py** + **dashboard/services/stream_pool_coordinator.py** + **dashboard/services/stream_telemetry.py** + **dashboard/camera_pool_queries.py#L46-L66**:
  - Update `StreamWorker._should_run_vision_step()` to pass `is_armed=bool(getattr(self.manager, "is_armed", False))`.
  - Wire shared `AnalyticsScheduler` and per-stream `CachedReplayProvider` into `AsyncInferenceWorker` / `build_live_step_result()`: if `CachedReplayProvider` is active, return zero-GPU governed `FrameStepResult`; otherwise consult `AnalyticsScheduler.should_schedule_frame(camera_id, frame, now, ...)` before `async_worker.submit()`, and automatically call `scheduler.promote_alarm(camera_id)` for `15.0 s` whenever detections or rule violations occur on an armed camera.
  - Expose `"armed": bool(getattr(stream, "is_armed", cfg.get("armed", False)))` in `build_camera_status_row()` and add `priority_tier`, `target_fps`, `motion_active`, `load_shed_stage`, and `replay_active` to `build_stream_telemetry()`.
  - Keep `stream_worker.py <= 285 L` (`<= 12` methods) and `stream_pool_coordinator.py < 240 L`.
- [ ] **tests/test_cached_replay_and_pool_scheduler.py** *(New)*: Unit & integration tests (`<= 40 L` per test method) verifying:
  - Pre-indexed `video_file` camera with `CachedReplayProvider` emits live `ZoneEvent`, `TripwireCrossEvent`, and `RSACViolationEvent` on `EventBus` with `0` calls to `detector.detect()` and `0` scheduler budget slots used.
  - Video loop wrap-around resets zone/tripwire state cleanly.
  - Unindexed `video_file` camera falls back to P0/P1/P2 `AnalyticsScheduler` live inference.
  - Multi-camera `CameraPool` in `focus_only` runs P0 on focused camera and motion-gated P1 on unfocused `armed=True` camera, promoting P1->P0 on intrusion within `<= 2.0 s`.
- [ ] **CHANGELOG.md**: Record milestone completion via `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add`.

### Milestone 3: Scheduler HUD, Schema/API Telemetry, Documentation & Final Sign-Off *(Deferred to Next Turn / Milestone)*

- [ ] **dashboard/schemas.py#L284-L300** + **dashboard/static/js/scheduler_hud.js** *(New, `< 180 L`)* + **dashboard/static/js/processing_mode.js#L75-L185** (`< 220 L`) + **dashboard/static/partials/tabs/live.html** (`< 220 L`) + **dashboard/static/index.html** (`< 180 L`):
  - Extend `ProcessingModeStatusResponse` in `dashboard/schemas.py` with optional `scheduler: dict[str, Any] | None = None`.
  - Fix `dashboard/static/js/processing_mode.js#L83` (`data.camera_states` fallback alongside `data.cameras`) so `armedPausedCount` and per-camera states resolve accurately, keeping `processing_mode.js < 220 L`.
  - Create `dashboard/static/js/scheduler_hud.js` rendering the live scheduler tier pill (`P0 LIVE`, `P1 MOTION`, `P1 IDLE 1FPS`, `P2 BG`, `ZERO-GPU REPLAY`) and load-shedding backpressure warning indicator into `#stream-telemetry-hud` without breaching `live.html < 220 L` or `index.html < 180 L`.
- [ ] **tests/test_scheduler_hud_and_e2e.py** *(New, Python + Node VM `<= 40 L` per method)*: Verify `processing_mode.js` `data.camera_states` armed count fix, `scheduler_hud.js` DOM badge states across P0/P1/P2/REPLAY and load-shed stages, `/api/system/processing-mode` scheduler payload contract, and HTML/JS file line budgets (`index.html < 180 L`, `live.html < 220 L`, `processing_mode.js < 220 L`).
- [ ] **documentation/** + **AGENTS.md**: Document the Resource-Aware Analytics Scheduler (`P0/P1/P2`, `MotionGate`, 3-stage load shedding, `<= 2.0 s` alarm SLA) and zero-GPU `CachedReplayProvider` in `documentation/` (`python -m sphinx -W --keep-going documentation/ documentation/_build/html/` with 0 warnings) and update `AGENTS.md` invariants.
- [ ] **CHANGELOG.md**: Record final milestone completion via `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add`.

---

## 5. Scenario Combinations Matrix

| Scenario | Verification Command | Expected Outcome |
|---|---|---|
| Milestone 1: Scheduler, MotionGate, `dt` Tracker & P1 `focus_only` | `MPLBACKEND=Agg python -m unittest tests.test_analytics_scheduler tests.test_processing_mode tests.test_processing_mode_invariants tests.test_step3_processing_mode_api` | 100% green; `MotionGate < 1 ms`, P1 idle `1 FPS` -> burst `8 FPS`, `<= 2.0 s` SLA, E4/E5/E6 invariants preserved |
| Milestone 2: Zero-GPU `CachedReplayProvider` & Pool Scheduling | `MPLBACKEND=Agg python -m unittest tests.test_cached_replay_and_pool_scheduler tests.test_live_studio_sync tests.test_step3_worker_hibernation_and_ai_gating tests.test_dashboard_di tests.test_step3_architecture_budgets` | 100% green; zero-GPU replay fires live zone/tripwire/RSAC alarms, `frame_processor.py <= 12` methods, `stream_worker.py <= 285 L`, `stream_pool_coordinator.py < 240 L` |
| Milestone 3: Scheduler HUD, E2E & Modularity Budgets | `MPLBACKEND=Agg python -m unittest tests.test_scheduler_hud_and_e2e tests.test_step4_e2e_performance_and_modes` | 100% green; `processing_mode.js < 220 L`, `live.html < 220 L`, `index.html < 180 L` |
| Static Modularity & Defect Audit | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/pipeline/motion_gate.py intelligent_tracker/pipeline/analytics_scheduler.py intelligent_tracker/pipeline/post_detection_governance.py intelligent_tracker/pipeline/frame_processor.py dashboard/services/cached_replay_provider.py dashboard/services/processing_mode_service.py dashboard/services/stream_worker.py dashboard/services/stream_pool_coordinator.py dashboard/static/js/processing_mode.js dashboard/static/js/scheduler_hud.js` | `Audit Result: PASS` on every touched and created file |
| Full Regression Suite & Sphinx Docs | `MPLBACKEND=Agg python -m unittest discover tests` and `python -m sphinx -W --keep-going documentation/ documentation/_build/html/` | 100% unit/integration test pass; 0 Sphinx warnings |

---

## 6. Definition of Done

1. **Always-On Armed Security (`P0/P1/P2`)**: In `focus_only`, focused/recording/alarm cameras run at **P0** (`12–15 FPS`) while unfocused `armed=True` cameras automatically run at motion-gated **P1** (`1.0 FPS` floor -> `8.0 FPS` motion burst, promoting to P0 for `15 s` on detection/alert); in `full_realtime`, all cameras run across P0/P1/P2 under the global inference budget.
2. **Alarm Latency SLA (`<= 2.0 s`) & Rule Completeness**: `64x36` luma `MotionGate` triggers immediate first-frame submission and `dt`-aware tracker persistence preserves track continuity across `1.0 FPS` heartbeats so zones, tripwires, RSAC rules, and pet whitelist are evaluated on every scheduled frame within `<= 2.0 s` of motion onset.
3. **Zero-GPU `CachedReplayProvider`**: Pre-indexed `video_file` cameras consume `0` GPU/YOLO budget slots while evaluating live `AnalyticsEngine` zones, tripwires, RSAC rules, `EventBus` alarms, and `WorldEntityBridge` updates with clean video-loop wrap-around resets (falling back to live P0/P1/P2 scheduling when unindexed).
4. **Shared Budget & 3-Stage Load Shedding**: Under elevated/critical inference latency, P2 sheds to `0 FPS` first, then P1 motion burst steps down while P0 and the P1 `>= 1.0 FPS` armed floor remain protected.
5. **Modularity & Regression Compliance**: All custom file/class budgets (`frame_processor.py <= 12` methods, `stream_worker.py <= 285 L`, `stream_pool_coordinator.py < 240 L`, `processing_mode.js < 220 L`, `live.html < 220 L`, `index.html < 180 L`), full unittest discovery, and `sphinx -W` pass with zero warnings.
