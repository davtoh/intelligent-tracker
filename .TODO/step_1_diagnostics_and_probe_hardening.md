# Step 1: Diagnostics Tooling Upgrades, Visual/CLS Checks, Unmocked Workspace Probes & `/app-debugger` Headless Baseline

> **Parent Roadmap**: `.TODO/integration_hardening_master_roadmap.md` (`Step 1 of 4` | `--parent integration_hardening_master_roadmap --milestone 1`).
> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–06`) & `docs/architecture/CURRENT_ARCHITECTURE.md` (Section 6).
> **Pre-Flight Modularity Audit (`diagnose.py audit`)**:
> - `skills/system-diagnostics/scripts/surface_scanners.py` (`361L`, `WARN >= 350L`; `cmd_surface` `52L`)
> - `skills/system-diagnostics/scripts/shadow_prober.py` (`411L`, `WARN >= 350L`)
> - `skills/system-diagnostics/scripts/trace_recorder.py` (`373L`, `WARN >= 350L`; 4 functions `45–60L`)
> - `skills/system-diagnostics/scripts/audit_layout.js` (`176L`, `OK`)
> - `.diagnostics/probes/cold_boot_world_probe.py` (`109L`; `run_probe` `63L`)
> - `.diagnostics/probes/replay_pipeline_probe.py` (`143L`; 2 helpers `42L`)
> - **Split-Before-You-Grow Rule**: Keep every modified script/probe `< 350L` and every function `<= 40L` by extracting cohesive sibling helpers (`surface_contracts.py`, `cross_module_rules.py`, `trace_cli.py`, `spa_nine_tab_cdp_probe.py`).

---

## Milestone 1: Global `system-diagnostics` & `frontier-architect` Upgrades + `ruff`/`mypy` Dev Tooling

- [x] **skills/system-diagnostics/scripts/surface_scanners.py** + **skills/system-diagnostics/scripts/surface_verifier.py** + **skills/system-diagnostics/scripts/surface_contracts.py** *(New)*: Extract CLI/contract helpers into `surface_contracts.py` so `surface_scanners.py < 350L` and `cmd_surface <= 40L`; default `surface --verify` to `include_tests=False`; verify HTTP methods (`GET`/`POST`/`PUT`/`DELETE`/`PATCH`), non-`fetch()` URLs (`img.src`, `video.src`, `new WebSocket`, `window.open`), inline HTML `onclick="..."` targets, `window.<Obj>.<method>()` calls, **unwired/dead HTML `<button id="...">` elements**, **same-view duplicate button labels**, and OpenAPI/JSON response-key contract checks.
- [x] **skills/system-diagnostics/scripts/audit_layout.js** + **skills/system-diagnostics/scripts/cdp_inspect.py**: Extend `audit_layout.js` (keeping `< 350L`) with (1) multi-frame layout-stability / CLS jitter sampling (`--stability-ms`, flagging `DOMRect` shifts on HUD/headers/cards during live updates), (2) flex/toolbar adjacent-sibling gap (`< 4px`) flush-control audit, and (3) visible duplicate-control label detection within active views.
- [x] **skills/system-diagnostics/scripts/cross_module_rules.py** *(New)* + **skills/system-diagnostics/scripts/shadow_prober.py**: Add cross-module Python attribute/method resolution rule (catching missing members like `AnalyticsEngine.draw_heatmap_overlay` and `SortTracker.tracks`), cross-module `time.monotonic()` -> Unix-epoch clock-domain taint rule, and AB-BA lock-order inversion rule, keeping functions `<= 40L`.
- [x] **skills/system-diagnostics/scripts/trace_recorder.py** + **skills/system-diagnostics/scripts/trace_cli.py** *(New)*: Extract trace CLI formatting and `traces resolve --id <TRC-ID>` into `trace_cli.py` (`trace_recorder.py < 350L`, all functions `<= 40L`); isolate/skip `unittest`/`pytest` runs from polluting `.diagnostics/trace_catalog.json` unless explicitly enabled via env var.
- [x] **skills/frontier-architect/SKILL.md** + **skills/frontier-architect/references/plan-contracts.md**: Codify the **UI Component Reuse & Ask-Before-Creating-New-Component Gate** in Phase 5 (inspect existing UI components/partials first, prefer presentation variants, and invoke `ask_question` before introducing any overlapping UI control/component).
- [x] **skills/system-diagnostics/tests/** + **skills/frontier-architect/tests/** + **skills/app-debugger/tests/**: Add targeted unit tests (`<= 40L`/method) for all new `surface`, `audit_layout.js`, `cross_module_rules`, and `trace_recorder` checks; run full pre-commit skill self-audit across all 3 skill test suites + `diagnose.py audit` on every modified skill file.
- [x] **pyproject.toml**: Add `[project.optional-dependencies] dev = ["ruff>=0.6.0", "mypy>=1.11.0"]` plus concise `[tool.ruff]` / `[tool.mypy]` configuration, install dev dependencies into the project environment, and verify `diagnose.py audit --typecheck` runs live without `SKIPPED`.

---

## Milestone 2: Unmocked Workspace Probes & `/app-debugger` Headless Failing Baseline

- [x] **.diagnostics/probes/replay_pipeline_probe.py**: Refactor helpers `<= 40L`, fail loud on empty `res.tracks` (fixing false-green `hd_track_x1: None`), and add unmocked checks for multi-frame `1920x1080` `CentroidTracker` persistence (`P0-3`), real-clock `AsyncInferenceWorker`/`StreamWorker` epoch vs. monotonic stamping (`P0-1`), `FrameOverlayRenderer` heatmap + 16:9 shape check (`P0-4`), and `capture_only` MJPEG non-freeze (`P1-6`).
- [x] **.diagnostics/probes/cold_boot_world_probe.py**: Refactor `run_probe <= 40L` and add assertions for `WorldGraph` reactive event emission (`P0-5`), multi-camera shared `ConfidenceEngine` (`P0-5`), `TRC-017` `cameras.json` `{"cameras": [...]}` boot resilience (`P0-5`), stream restart scenario/homography preservation (`P1-8`), and concurrent `ProcessingModeService.get_state()` <-> `StreamRecordingController` lock-order stress (`P0-2`).
- [x] **.diagnostics/probes/video_studio_contract_probe.py**: Add assertions for offline `VideoIndexer` wall-clock + `media_offset_sec` persistence in sightings/FTS/`WorldQueryEngine` citations (`P0-1`, `P1-11`), per-video occurrence report isolation (`P1-11`), `RoiRecognitionService` locked anchor + confidence wiring (`P1-12`), and backend-to-JS JSON payload key parity (`review_queue`, `events`, `detections`).
- [x] **.diagnostics/probes/spa_nine_tab_cdp_probe.py** *(New)*: Boot an isolated ephemeral FastAPI server (`port=0`, `TemporaryDirectory` DB/videos/cameras/scenarios) and run headless Chrome CDP (`--capture-runtime --audit-layout --stability-ms 2000`) sweeping all 9 SPA tabs, `1x1` vs `2x2` multiview grid, camera title switches (short vs. long names), and modals, asserting `0` HTTP `>= 400`, `0` missing assets, `0` JS exceptions, `0` CLS/HUD layout shifts, `0` `<4px` sibling gaps, `0` dead/duplicate buttons, and `0` layout overflows.
- [x] **`/app-debugger` Headless Baseline & Retrospective**: Run upgraded `diagnose.py surface --verify`, `diagnose.py scan --path intelligent_tracker dashboard scripts`, `diagnose.py audit --typecheck`, and all 4 workspace probes to capture the verified **Red** Symptom-to-Root-Cause Matrix (including `P3` edge cases), triage/resolve stale test traces, and log `diagnose.py debug-retro --plan step_1_diagnostics_and_probe_hardening`.
- [x] **CHANGELOG.md**: Record Step 1 completion via `'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'`.

---

## Scenario Combinations Matrix

| Scenario | Verification Command | Expected Outcome |
| :--- | :--- | :--- |
| **Skill Self-Tests** | `python -m unittest discover -s skills/system-diagnostics/tests -p "test_*.py"; python -m unittest discover -s skills/frontier-architect/tests -p "test_*.py"; python -m unittest discover -s skills/app-debugger/tests -p "test_*.py"` | 100% pass across all 3 skill suites |
| **Skill Budget Audit** | `python skills/system-diagnostics/scripts/diagnose.py audit --path skills/system-diagnostics/scripts/surface_scanners.py skills/system-diagnostics/scripts/surface_verifier.py skills/system-diagnostics/scripts/surface_contracts.py skills/system-diagnostics/scripts/cross_module_rules.py skills/system-diagnostics/scripts/shadow_prober.py skills/system-diagnostics/scripts/trace_recorder.py skills/system-diagnostics/scripts/trace_cli.py --max-lines 350 --max-fn-lines 40` | 0 budget overruns on touched files |
| **Live Typecheck & Cross-Module Gate** | `python skills/system-diagnostics/scripts/diagnose.py audit --path intelligent_tracker dashboard scripts --typecheck; python skills/system-diagnostics/scripts/diagnose.py surface --verify; python skills/system-diagnostics/scripts/diagnose.py scan --path intelligent_tracker dashboard scripts` | `ruff`/`mypy` execute live; new surface & cross-module rules surface exact Step 2–4 targets |
| **Workspace Probes Red Baseline** | `python skills/system-diagnostics/scripts/diagnose.py probe run cold_boot_world_probe; python skills/system-diagnostics/scripts/diagnose.py probe run replay_pipeline_probe; python skills/system-diagnostics/scripts/diagnose.py probe run video_studio_contract_probe; python skills/system-diagnostics/scripts/diagnose.py probe run spa_nine_tab_cdp_probe` | Deterministic **Red** baseline isolating P0–P3 & CLS/duplicate-UI bugs |
| **Product Regression Suite** | `MPLBACKEND=Agg python -m unittest discover tests` | 100% green (`>= 882` passing tests) |
