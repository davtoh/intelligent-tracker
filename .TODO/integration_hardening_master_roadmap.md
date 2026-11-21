# Integration Hardening & UI Unification Master Roadmap

> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–06`, Layers 1–5) & `docs/architecture/CURRENT_ARCHITECTURE.md` (branch `feature/integration-remediations`, commit `400bc9f`, `882` passing tests).
> **How to use this document**: Execute one Step at a time via child plans linked in `.frontier/` (`--parent integration_hardening_master_roadmap --milestone <N>`).
> **Decision Basis (`/grill-me`, 8/8 questions resolved)**:
> 1. **Sequence**: Upgrade diagnostics tooling & workspace probes first -> run `/app-debugger` Headless Background Sandbox sweep -> execute phased P0 -> P1 -> P2 remediation.
> 2. **Tooling Upgrade**: Full 3-layer upgrade — harden global `skills/system-diagnostics/` (cross-contract `surface`, `audit_layout.js` CLS/jitter/gap/duplicate checks, cross-module `shadow_prober` rules, trace test isolation) + `skills/frontier-architect/` component-reuse gate + install `ruff`/`mypy` dev dependencies in `pyproject.toml` + build 4 unmocked workspace probes in `.diagnostics/probes/` (including 9-tab headless CDP).
> 3. **Clock Domain (`P0-1`)**: Dual-clock separation everywhere — `time.monotonic()` strictly for scheduler intervals, FPS pacing, lag deltas, and cooldowns; Unix wall-clock epoch `time.time()` for `FrameProcessor.step()`, `RSACSchedule`, `TrackerDB`, `EventFTSIndex`, `ConfidenceEngine`, `EventBus` alerts, and `ThumbnailCache.capture_ts_ms`. Offline `VideoIndexer` uses `base_epoch + video_ts` while preserving `video_filename` and `media_offset_sec` in sightings, FTS, and `WorldQueryEngine` citations.
> 4. **Pool Ownership (`P0-5`)**: Pool-scoped singletons for `EventBus`, `WorldGraph`, `ConfidenceEngine`, and `EventFTSIndex` shared across `CameraPool`, all `StreamManager` instances, and `app.state`, preserving `CameraNode` homography/pose and `ScenarioManager` overlays across camera restarts.
> 5. **Frontend Scope**: Remediate all broken existing UI/contract flows (`P2-14`..`P2-26`); defer unwired backend UI surfaces (`P2-23`: `/api/world/*`, `/api/rsac/rules`, `/api/pets/whitelist`) and extra CLI `ctl.py` parity to a dedicated follow-up.
> 6. **`/app-debugger` Mode**: Headless Background Sandbox (ephemeral server `port=0` + isolated temp DB) for automated sweeps, with optional Live Chrome Tab confirmation at final sign-off.
> 7. **Multiview (`2x2`/`3x3`/`4x4`) AI Visibility (`P2-25`)**: Server `/ws/multiview` remains zero-extra-render (`annotated=False` JPEGs) while streaming throttled JSON telemetry (`tracks`, `fps`, `priority_tier`, `armed`, `ai_active`) so AI-active grid tiles draw client-side boxes via `UnifiedCanvasOverlay`, show live FPS/tracks + pool-wide `Recent Alerts`, and expose a per-tile AI activation toggle (`armed`).
> 8. **Component Reuse & Consolidation (`P2-26`)**: Unify Live Monitor & Video Studio `"Video Overlays"` toolbars into one reusable `OverlayControlBar` (`variant: 'live'` & `variant: 'scrubber'`), remove the broken duplicate header `#fullscreen-btn` (keep single HUD `#btn-fullscreen-toggle`), and enforce component reuse + ask-before-creating-new-UI rules (`ADR-05`, `AGENTS.md`).

---

## Step 1: Diagnostics Tooling Upgrades, Visual/CLS Checks, Unmocked Workspace Probes & `/app-debugger` Headless Baseline
- [ ] **Child Plan**: `.TODO/step_1_diagnostics_and_probe_hardening.md`
- [ ] **Goal**: Close every static, surface, cross-module, trace, and visual layout blind spot that let `P0–P2` integration bugs slip past `882` green tests, and establish a verified failing **Red** `/app-debugger` baseline.
- [ ] **Target Scope**:
  - [ ] Upgrade `skills/system-diagnostics/` (`surface_scanners.py`, `surface_verifier.py`, `surface_contracts.py`, `audit_layout.js`, `cdp_inspect.py`, `cross_module_rules.py`, `shadow_prober.py`, `trace_recorder.py`, `trace_cli.py`) + unit tests.
  - [ ] Add `UI Component Reuse & Ask-Before-Creating-New-Component` gate to `skills/frontier-architect/`.
  - [ ] Add optional `[project.optional-dependencies] dev` (`ruff`, `mypy`) in `pyproject.toml` and verify live `diagnose.py audit --typecheck`.
  - [ ] Harden `.diagnostics/probes/` (`replay_pipeline_probe.py`, `cold_boot_world_probe.py`, `video_studio_contract_probe.py`, new `spa_nine_tab_cdp_probe.py`) and record the verified Red Symptom-to-Root-Cause Matrix + `debug-retro`.
- [ ] **Definition of Done**: Skill test suites (`system-diagnostics`, `app-debugger`, `frontier-architect`) 100% pass; `diagnose.py audit --typecheck` active; all 4 probes reproducibly expose target bugs against baseline.

---

## Step 2: P0 Runtime Stabilization & Pool-Scoped Ownership (`P0-1`..`P0-5`)
- [ ] **Goal**: Eliminate live/offline epoch corruption, active-recording deadlocks, `1280px` tracker box drift, heatmap runtime crashes, split-brain `WorldGraph`/`ConfidenceEngine`/`EventBus`, and `TRC-017` startup crash.
- [ ] **Target Scope**:
  - [ ] **Dual-Clock Separation (`P0-1`)**: Keep `time.monotonic()` in scheduler/lag/FPS/cooldown paths; pass Unix epoch `time.time()` into `FrameProcessor.step()` and `CachedReplayProvider` (`async_inference_worker.py`, `thumbnail_cache.py`), and `base_epoch + video_ts` in `VideoIndexer` (`batch.py`) while preserving `video_filename` + `media_offset_sec`.
  - [ ] **Deadlock Elimination (`P0-2`)**: Break `ProcessingModeService._lock` <-> `StreamRecordingController._lock` AB-BA cycle and guard `pool.streams` iteration with `pool._lock`.
  - [ ] **Coordinate & Heatmap Fixes (`P0-3`, `P0-4`)**: Clone/rescale output `tracks` and `detections` non-destructively outside `CentroidTracker`'s internal state; fix `FrameOverlayRenderer` to use `analytics.heatmap.draw()` with dynamic frame-shape alignment.
  - [ ] **Pool Singletons & Boot Validation (`P0-5`)**: Wire pool-scoped `EventBus`, `WorldGraph`, `ConfidenceEngine`, and `EventFTSIndex` across `CameraPool`, `StreamManager`, `dependencies.py`, and `app.state`; validate `CameraConfigStore.load_cameras()` dict entries (`TRC-017`).
- [ ] **Definition of Done**: Real-clock `replay_pipeline_probe`, `cold_boot_world_probe` deadlock/singleton checks, and full `unittest` pass with zero regressions.

---

## Step 3: P1 Pipeline, Multiview Telemetry, Lifecycle, Video Studio & Persistence Hardening (`P1-6`..`P1-13` + `/ws/multiview` JSON + P3 Edge Cases)
- [ ] **Goal**: Stabilize capture/FPS/replay state machines, stream restarts, multiview JSON telemetry, offline Video Studio indexing/ROI tagging, and persistence/security invariants.
- [ ] **Target Scope**:
  - [ ] **Streaming, FPS & Replay (`P1-6`, `P1-7`, `P1-9`, `P1-10`, P3)**: Fallback to `_latest_raw_jpeg` in `capture_only`; prefer `vs.measured_fps` over inference-compute FPS and reset `_measured_fps` on pause/reconnect; fix `REPLAY` <-> `LIVE` races, `loop_video=False` EOF restart, `MotionGate` stale-bg burst on resume, `video_file` slow-disk reopen, and hibernation/paused wake fights.
  - [ ] **Multiview JSON Telemetry & Pool Alerts**: Extend `/ws/multiview` to stream throttled JSON telemetry (`tracks`, `fps`, `priority_tier`, `armed`, `ai_active`) alongside binary JPEG frames, and fix slow-client HOL blocking (`MultiviewSession._flush_camera`) and `FrameSurface.resetSeq()` on restart.
  - [ ] **Restarts, Video Studio, ROI & Persistence (`P1-8`, `P1-11`, `P1-12`, `P1-13`)**: Preserve `CameraNode` homography/pose and reapply `ScenarioManager` on camera restart/retry; close `PipelineBundle` in `StreamManager.stop()`; fix `_gallery_signals` FTS `video_filename`/`media_offset_sec`, `WorldQueryEngine` citations, `EntityIdentifiedEvent.zone_id`, and per-video report filtering; lock ROI anchors (`is_anchor=1, locked=1`) and sync `WorldEntityBridge`; harden `BackupManager` symlink/WAL restore, guard `_conn is None` across repository mixins, and add `.close()` cleanup (`TRC-018`).
- [ ] **Definition of Done**: All backend/pipeline probes pass; `TRC-017` & `TRC-018` absent; full `unittest` 100% green.

---

## Step 4: P2 Frontend Contracts, Unified `OverlayControlBar`, Zero-CLS HUD, Multiview AI Boxes/Toggle & Final `/app-debugger` Sign-Off (`P2-14`..`P2-26`)
- [ ] **Goal**: Resolve every broken frontend-backend contract, eliminate HUD jitter/duplicate controls, unify `"Video Overlays"`, enable multi-camera grid AI boxes/alerts/toggles, and pass full headless (and optional live) `/app-debugger` sign-off.
- [ ] **Target Scope**:
  - [ ] **Schema & Wiring Contracts (`P2-14`..`P2-22`)**: Fix Review Queue (`similarity`, `suggested_name`, `timestamp`, `/crops/*`, placeholder asset), Video Studio click-to-tag (`track_id`), Alerts (`name`, `severity`, `message`), Live overlay target channel, Camera Manager preset/`enabled`/capabilities race/Cancel/`getActiveCameras`, Enroll & Quick-Tag modals, Scenario Studio/BEV Minimap coordinates & recorded-video re-entry, `#btn-snapshot-save` freeze-frame, `journey_search.js`, `rsac_versions.js`, scoped `.btn-tag-preset`, and SPA hash-boot/cache/`?token=`/WS cleanup.
  - [ ] **Unified `OverlayControlBar` & Consolidation (`P2-26`)**: Replace duplicated Live Monitor checkboxes and Video Studio `overlay_layer_toolbar.js` with one reusable `OverlayControlBar` (`variant: 'live'` & `variant: 'scrubber'`) and remove duplicate broken header `#fullscreen-btn`.
  - [ ] **Zero-CLS HUD & Multiview AI (`P2-24`, `P2-25`)**: Add `>= 8px` `.hud-center` gaps, `tabular-nums`, smoothing/hysteresis + reserved slot on `#stream-lag-badge`, fixed `#video-stream-title` truncation containment; mount `UnifiedCanvasOverlay` on `2x2`/`3x3`/`4x4` grid tiles with live FPS/tracks, pool-wide `Recent Alerts`, and per-tile AI toggle (`armed`).
  - [ ] **Final Verification & Docs**: Pass `spa_nine_tab_cdp_probe.py` (0 CLS/gaps/dead buttons/duplicate labels/JS errors/HTTP>=400), full `unittest`, `sphinx -W`, refresh `docs/architecture/CURRENT_ARCHITECTURE.md`, and run `diagnose.py changelog add`.
- [ ] **Definition of Done**: All 4 workspace probes + `surface --verify --strict` + `scan --strict` + `audit --typecheck` + `unittest` + `sphinx -W` 100% green.

---

## Explicitly Deferred Follow-Up Scope
- Retiring legacy `intelligent_tracker/high_objects.py` (`523L`), `intelligent_tracker/core/spaces.py`, and `--gui forms` (`cli/runner.py`).
- Unifying `intelligent_tracker/interactive.py` and `VideoIndexer` (`batch.py`) onto `PipelineEngine.build()`.
- Wiring `WorldPolicy` (`world/nodes.py`) runtime enforcement into `AlertRuleEngine` / `ZoneROI`.
- Building new frontend UI views for unwired backend capabilities (`P2-23`: `/api/world/*` NL Q&A panel, `/api/rsac/rules`, `/api/pets/whitelist`, `/api/topology/world-map`) and expanding CLI `ctl.py` CRUD parity.

---

## Master Verification Matrix

| Verification Gate | Command | Expected Result |
| :--- | :--- | :--- |
| **Skill Self-Tests** | `python -m unittest discover -s skills/system-diagnostics/tests -p "test_*.py"; python -m unittest discover -s skills/frontier-architect/tests -p "test_*.py"; python -m unittest discover -s skills/app-debugger/tests -p "test_*.py"` | 100% pass after Step 1 tool upgrades |
| **Cross-Contract & Static Gate** | `python skills/system-diagnostics/scripts/diagnose.py surface --verify --strict; python skills/system-diagnostics/scripts/diagnose.py scan --path intelligent_tracker dashboard scripts --strict; python skills/system-diagnostics/scripts/diagnose.py audit --path intelligent_tracker dashboard scripts --typecheck` | 0 unmatched routes/IDs/keys/dead buttons, 0 defects, `ruff`/`mypy` active |
| **4 Unmocked Workspace Probes** | `python skills/system-diagnostics/scripts/diagnose.py probe run cold_boot_world_probe; python skills/system-diagnostics/scripts/diagnose.py probe run replay_pipeline_probe; python skills/system-diagnostics/scripts/diagnose.py probe run video_studio_contract_probe; python skills/system-diagnostics/scripts/diagnose.py probe run spa_nine_tab_cdp_probe` | Red in Step 1 baseline; 100% Green at Step 4 sign-off |
| **Headless CDP Layout & CLS Sweep** | `python skills/system-diagnostics/scripts/diagnose.py ui --url "$APP_URL" --headless --capture-runtime --audit-layout --stability-ms 2000 --strict` | 0 HTTP >= 400, 0 JS exceptions, 0 CLS shifts, 0 `<4px` sibling gaps, 0 duplicate controls |
| **Full Regression & Docs Gate** | `MPLBACKEND=Agg python -m unittest discover tests; python skills/system-diagnostics/scripts/diagnose.py arch-map --path .; python -m sphinx -W --keep-going documentation/ documentation/_build/html/` | 100% test pass, clean budgets, 0 Sphinx warnings |
