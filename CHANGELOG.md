# Changelog

## [2026-11-23] feat: Step 2 Milestone 3: Person+Bag WorldGraph Ownership and Unattended-Item Alerts
- **Type**: feat
- **Summary**: Added WorldEdge/WorldEdgeRegistry, OwnershipAssociationEngine, UnattendedItemAlert with EventFTSIndex formatting, and live governance/telemetry wiring.
- **Files** (13):
  - `dashboard/services/stream_telemetry.py`
  - `intelligent_tracker/events/__init__.py`
  - `intelligent_tracker/events/types.py`
  - `intelligent_tracker/memory/_event_formatters.py`
  - `intelligent_tracker/pipeline/bundle.py`
  - `intelligent_tracker/pipeline/post_detection_governance.py`
  - `intelligent_tracker/world/__init__.py`
  - `intelligent_tracker/world/_lifecycle.py`
  - ... (+5 more)
- **Verification**: .venv/Scripts/python.exe -m unittest discover tests

## [2026-11-23] fix: Step 1: Critical Bug Remediations & Tooling Elevation
- **Type**: fix
- **Summary**: Resolved Findings 1-7 and BE-1..BE-4 across backend/frontend, elevated SPA 9-tab CDP and Video Studio probes, and added broken-img, script wrap-order, query-param, and repo-rollback rules to system-diagnostics.
- **Files** (8):
  - `.diagnostics/probes/spa_nine_tab_cdp_probe.py`
  - `.diagnostics/probes/video_studio_contract_probe.py`
  - `tests/test_database_concurrency.py`
  - `tests/test_live_studio_sync.py`
  - `tests/test_step2_studio_minimap_gating.py`
  - `tests/test_step2_tab_scoped_perf_integration.py`
  - `tests/test_step3_e2e_tagging_flow.py`
  - `tests/test_step4_m3_spa_and_video_contracts.py`
- **Verification**: MPLBACKEND=Agg python -m unittest discover tests

## [2026-11-21] feat: Step 4 & Integration Hardening Master Roadmap Complete (P0-P3)
- **Type**: feat
- **Summary**: Hardened 9-tab headless CDP probe + Chrome-gated E2E test, aligned legacy Node VM suites with GridTileOverlay & Zero-CLS HUD hysteresis, and refreshed CURRENT_ARCHITECTURE.md.
- **Files** (11):
  - `.diagnostics/probes/video_studio_contract_probe.py`
  - `dashboard/static/js/bev_minimap.js`
  - `dashboard/static/js/telemetry.js`
  - `dashboard/static/studio.js`
  - `docs/architecture/CURRENT_ARCHITECTURE.md`
  - `tests/test_camera_grid_teardown.py`
  - `tests/test_camera_recording_ui.py`
  - `tests/test_dashboard_ui.py`
  - ... (+3 more)
- **Verification**: MPLBACKEND=Agg python -m unittest discover tests

## [2026-11-21] feat: Step 3: P1 Pipeline, Multiview Telemetry, Video Studio & Persistence Hardening
- **Type**: feat
- **Summary**: Completed P1-6..P1-13, /ws/multiview JSON telemetry, P3 edge cases, and TRC-018
- **Files** (32):
  - `.diagnostics/probes/video_studio_contract_probe.py`
  - `dashboard/routers/analytics.py`
  - `dashboard/routers/tagging.py`
  - `dashboard/routers/video_jobs.py`
  - `dashboard/services/entity_tagger.py`
  - `dashboard/services/roi_recognition_service.py`
  - `dashboard/services/video_analytics_service.py`
  - `dashboard/static/review_and_rsac.js`
  - ... (+24 more)

## [2026-11-21] fix: Step 2 M2: Lock-Order Deadlock Elimination, Pool-Scoped Singletons & CameraConfigStore Hardening
- **Type**: fix
- **Summary**: Eliminated ProcessingModeService<->StreamRecordingController AB-BA deadlock (P0-2), guarded all pool.streams accesses with snapshot_pool_streams/_snapshot_pool_streams, hardened CameraConfigStore.load_cameras() for {'cameras': ...} payloads (TRC-017), wired pool-scoped EventBus/WorldGraph/ConfidenceEngine/EventFTSIndex singletons into CameraPool/PipelineEngine/app.state (P0-5), added SQLite rollback-on-error in memory_repo.py, and upgraded cold_boot_world_probe.py + test_step2_pool_singletons_and_locks.py.
- **Files** (24):
  - `.diagnostics/probes/cold_boot_world_probe.py`
  - `dashboard/app.py`
  - `dashboard/camera_pool.py`
  - `dashboard/dependencies.py`
  - `dashboard/routers/camera_recording.py`
  - `dashboard/routers/cameras.py`
  - `dashboard/routers/system.py`
  - `dashboard/routers/videos.py`
  - ... (+16 more)
- **Verification**: 893/893 unittest discover tests OK; cold_boot_world_probe PASS; test_step2_pool_singletons_and_locks + test_dashboard_di + test_step3_architecture_budgets 18/18 OK

## [2026-11-21] feat: Step 1: Diagnostics Upgrades, Unmocked Probes & Red Baseline
- **Type**: feat
- **Summary**: Upgraded system-diagnostics/frontier-architect tooling, added ruff/mypy dev tooling, hardened 4 unmocked workspace probes (including spa_nine_tab_cdp_probe), resolved stale test traces, and captured verified Red baseline.
- **Files** (3):
  - `.diagnostics/probes/cold_boot_world_probe.py`
  - `.diagnostics/probes/replay_pipeline_probe.py`
  - `.diagnostics/probes/video_studio_contract_probe.py`
- **Verification**: python -m unittest discover tests

## [2026-11-20] fix: Integration Diagnostics Remediation Milestone 3
- **Type**: fix
- **Summary**: Fixed scrubber reports/media URLs, entities+alerts timeline extraction, BEV telemetry wiring, Studio video overlay gating, armed UI/AsyncInferenceWorker sync, boot stream gating, and zero active scan/surface defects
- **Files** (22):
  - `.TODO/integration_diagnostics_and_remediation_plan.md`
  - `dashboard/camera_pool.py`
  - `dashboard/services/async_inference_worker.py`
  - `dashboard/services/process_supervisor.py`
  - `dashboard/services/stream_worker.py`
  - `dashboard/static/app.js`
  - `dashboard/static/camera_manager.js`
  - `dashboard/static/js/bev_minimap.js`
  - ... (+14 more)
- **Verification**: MPLBACKEND=Agg python -m unittest discover tests

## [2026-11-19] feat: Step 2 Milestone 3: Scheduler HUD, Schema Telemetry & Docs
- **Type**: feat
- **Summary**: Extended ProcessingModeStatusResponse with scheduler telemetry, fixed data.camera_states lookup in processing_mode.js, added scheduler_hud.js tier and load-shed pills, documented scheduler and CachedReplayProvider in dashboard.rst and AGENTS.md, and verified 858 tests plus Sphinx -W.
- **Files** (10):
  - `AGENTS.md`
  - `dashboard/schemas.py`
  - `dashboard/services/processing_mode_service.py`
  - `dashboard/static/css/processing_mode.css`
  - `dashboard/static/index.html`
  - `dashboard/static/js/live_player.js`
  - `dashboard/static/js/processing_mode.js`
  - `documentation/dashboard.rst`
  - ... (+2 more)
- **Verification**: python -m unittest discover tests

## [2026-11-19] feat: Step 2 Milestone 2: Zero-GPU CachedReplayProvider & Runtime Pool Scheduler Wiring
- **Type**: feat
- **Summary**: Extracted shared post_detection_governance.py (FrameProcessor 14->7 methods), implemented zero-GPU CachedReplayProvider with live zone/tripwire/RSAC governance and loop wrap-around resets, wired AnalyticsScheduler & armed P1 gating into StreamWorker/AsyncInferenceWorker, and exposed scheduler/armed telemetry.
- **Files** (9):
  - `dashboard/services/async_inference_worker.py`
  - `dashboard/services/cached_replay_provider.py`
  - `dashboard/services/camera_pool_queries.py`
  - `dashboard/services/file_detection_replay.py`
  - `dashboard/services/stream_telemetry.py`
  - `dashboard/services/stream_worker.py`
  - `intelligent_tracker/pipeline/frame_processor.py`
  - `intelligent_tracker/pipeline/post_detection_governance.py`
  - ... (+1 more)
- **Verification**: python -m unittest tests.test_cached_replay_and_pool_scheduler tests.test_live_studio_sync tests.test_step3_worker_hibernation_and_ai_gating tests.test_dashboard_di tests.test_step3_architecture_budgets tests.test_cross_platform_pipeline_hardening tests.test_analytics_scheduler

## [2026-11-19] feat: Step 2 Milestone 1: Core AnalyticsScheduler, 64x36 MotionGate, dt-Aware Trackers & Armed P1
- **Type**: feat
- **Summary**: Implemented 64x36 luma MotionGate, P0/P1/P2 AnalyticsScheduler with 3-stage load shedding and IdleRefinementHook, dt-aware persistence in SortTracker/CentroidTracker, and armed P1 vision gating in ProcessingModeService.
- **Files** (6):
  - `dashboard/services/processing_mode_service.py`
  - `intelligent_tracker/tracker/centroid.py`
  - `intelligent_tracker/tracker/sort.py`
  - `intelligent_tracker/pipeline/analytics_scheduler.py`
  - `intelligent_tracker/pipeline/motion_gate.py`
  - `tests/test_analytics_scheduler.py`
- **Verification**: MPLBACKEND=Agg python -m unittest tests.test_analytics_scheduler tests.test_tracker tests.test_processing_mode tests.test_processing_mode_invariants tests.test_step3_processing_mode_api tests.test_modernization

## [2026-11-17] fix: Eliminate cam_01 stub in processing_mode.js and persist focused camera across reloads
- **Type**: fix
- **Summary**: Initialize state.focusedCameraId from localStorage (it_focused_camera_id) instead of hardcoded cam_01 in processing_mode.js, omit focused_camera_id from init() when unset, and restore the last focused camera in CameraAIConfig.resolveInitialCameraId().
- **Files** (3):
  - `dashboard/static/js/camera_ai_config.js`
  - `dashboard/static/js/processing_mode.js`
  - `tests/test_step4_processing_mode_ui.py`
- **Verification**: .venv\\Scripts\\python.exe -m unittest tests.test_step4_processing_mode_ui tests.test_step4_e2e_performance_and_modes tests.test_processing_mode tests.test_step1_demo_mode_ui tests.test_step2_live_canvas_delegation
