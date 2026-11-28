# Changelog

## [2026-11-27] fixed: Step 1 P0 runtime tracking, Re-ID parity, studio overlays & timeline reset
- **Type**: fixed
- **Summary**: Added track_id support to MultiCameraHandoffCoordinator.record_zone_exit, aligned CANONICAL_REID_DIM to 2560D, added SortTracker bounded centroid fallback and stream telemetry ghost filtering, enforced 1-to-1 per-frame entity uniqueness in GalleryMatcher, isolated CameraAIConfig preset chips, switched #studio live streams to ?annotated=false with ScrubberOverlay.getCurrentTracks(), normalized float Unix epoch sightings bounds, and added #timeline active window chip and Reset button.
- **Files** (25):
  - `.diagnostics/probes/deep_link_navigation_probe.py`
  - `.diagnostics/probes/effective_config_probe.py`
  - `.diagnostics/probes/replay_pipeline_probe.py`
  - `.diagnostics/probes/sightings_provenance_probe.py`
  - `dashboard/services/stream_telemetry.py`
  - `dashboard/static/js/active_source_context.js`
  - `dashboard/static/js/camera_ai_config.js`
  - `dashboard/static/js/gallery_timeline.js`
  - ... (+17 more)
- **Verification**: 67 unit tests + 5 probes + surface --verify --strict PASS

## [2026-11-27] feat: Step 4: Layout Overflow Containment, Status Popover Cleanup & Long-Fixture Tooling Guards
- **Type**: feat
- **Summary**: Fixed flex/select overflow regressions on #videos, #analytics, and #review (OBS-011, OBS-013, OBS-015), cleared stale #connection-status-text popover state on camera/mode changes (OBS-012), added 71-char filename CDP checks, added JS runtime guard rules in system-diagnostics, and resolved Step 1/3 budget and surface regressions.
- **Files** (17):
  - `dashboard/static/css/sidebar.css`
  - `dashboard/static/css/scrubber.css`
  - `dashboard/static/css/views.css`
  - `dashboard/static/css/analytics_alerts.css`
  - `dashboard/static/css/review.css`
  - `dashboard/static/js/analytics_view.js`
  - `dashboard/static/js/text_truncation_manager.js`
  - `dashboard/static/js/app_ui_helpers.js`
  - ... (+9 more)
- **Verification**: 1227/1227 unittest OK; spa_nine_tab_cdp_probe ok; scan --strict 0 active defects; surface --verify 0 mismatches; sphinx -W 0 warnings

## [2026-11-27] feat: Step 2: Synthetic Re-ID Parity, Live ROI-Draw Enrollment & Camera/Batch Config
- **Type**: feat
- **Summary**: Aligned MockDetector with SyntheticFrameGenerator P1/P2, added debounced ROI collision and recognize-roi suggestions, auto-reset #gallery filters on enrollment, preserved tracked_categories and agnostic_nms across camera edit, preserved tracked_categories in batch config_meta, and added gallery entity pickers and COCO vs RSAC helper copy.
- **Files** (16):
  - `intelligent_tracker/detectors/mock_detector.py`
  - `dashboard/schemas.py`
  - `dashboard/routers/cameras.py`
  - `dashboard/camera_pool.py`
  - `dashboard/services/camera_pool_queries.py`
  - `dashboard/services/video_analytics_service.py`
  - `dashboard/routers/system.py`
  - `dashboard/static/js/universal_enrollment.js`
  - ... (+8 more)
- **Verification**: tests/test_step2_synthetic_reid_and_config.py + 9 related suites (73 passed), replay_pipeline_probe PASS, video_studio_contract_probe PASS, surface --verify (0 mismatches), scan --strict (0 tactical defects)

## [2026-11-27] feat: Local Mini-CI Linux Parity Verification (Milestone 2)
- **Type**: feat
- **Summary**: Verified scripts/mini_ci.py --linux end-to-end via Docker (1,217 tests OK), hardened Windows-to-WSL pure-LF stdin delivery, added nodejs to Docker CI image, patched test_discovery container check, and documented WSL/Docker setup in SETUP_GUIDE.md
- **Files** (4):
  - `scripts/mini_ci.py`
  - `tests/test_mini_ci.py`
  - `tests/test_discovery.py`
  - `SETUP_GUIDE.md`
- **Verification**: scripts/mini_ci.py --linux --backend docker --skip-docs (1217 OK); scripts/mini_ci.py --fast --tests tests/test_mini_ci.py tests/test_discovery.py tests/test_diagnostics_contract.py

## [2026-11-26] feat: Debug Observation Connector Adoption (Tier A Adapted, M1-M4)
- **Type**: feat
- **Summary**: Completed Wire Contract v1 loopback-gated routes, dev-only HUD injection, X-Debug-Recording-Id trace stamping, debug_session probe open_observations_count warning status, architecture/Sphinx docs, .agents/rules/debug-observations.md, and FOR AUDITS prompt hand-off.
- **Files** (8):
  - `.TODO/debug_observation_connector_adoption_plan.md`
  - `.diagnostics/probes/debug_session.py`
  - `AGENTS.md`
  - `docs/architecture/CURRENT_ARCHITECTURE.md`
  - `documentation/dashboard.rst`
  - `tests/test_debug_observation_mode.py`
  - `tests/test_debug_session.py`
  - `.agents/rules/debug-observations.md`
- **Verification**: MPLBACKEND=Agg python -m unittest discover -s tests -p 'test_*.py' (1197 passed); verify-connector CONFORMANT; sphinx -W clean

## [2026-11-26] test: CI Parity & Batch Contract Hardening (M2)
- **Type**: test
- **Summary**: Added POSIX/Windows avatar URL & ROI propagation tests, bounded 1.0s multiview websocket close timeout test, and isolated TestVideoJobAPI DB state.
- **Files** (4):
  - `.TODO/ci_parity_and_batch_contract_hardening.md`
  - `tests/test_ci_parity_and_batch_contract.py`
  - `tests/test_multiview_session.py`
  - `tests/test_video_jobs.py`
- **Verification**: MPLBACKEND=Agg python -m unittest discover tests

## [2026-11-25] feat: Step 4: Reversible Review Audit & Studio / Analytics / Alerts UX
- **Type**: feat
- **Summary**: Complete Step 4 (review_decisions v5 audit/undo, recurring unknown queueing, Studio minimap zoom/BEV quad, Journey/Analytics/Snapshot overlay isolation) and close integration_seams_entity_persistence_master_roadmap
- **Files** (13):
  - `AGENTS.md`
  - `dashboard/services/multiview/limits.py`
  - `dashboard/static/app.js`
  - `dashboard/static/js/scrubber_timeline_slider.js`
  - `docs/architecture/CURRENT_ARCHITECTURE.md`
  - `intelligent_tracker/homography.py`
  - `intelligent_tracker/matching/gallery.py`
  - `intelligent_tracker/matching/learned_class_matcher.py`
  - ... (+5 more)

## [2026-11-25] feat: Step 3 M4: Exemplar Learned Classes & Per-Camera COCO Overrides
- **Type**: feat
- **Summary**: Added schema v4, LearnedClassMixin, LearnedClassMatcher, LearnedClassService, /api/classes/* router, and unified Classes & Badges 3-tab gallery sub-view.
- **Files** (17):
  - `dashboard/app.py`
  - `dashboard/routers/__init__.py`
  - `dashboard/static/index.html`
  - `dashboard/static/partials/tabs/gallery.html`
  - `intelligent_tracker/database.py`
  - `intelligent_tracker/pipeline/bundle.py`
  - `intelligent_tracker/pipeline/frame_processor.py`
  - `intelligent_tracker/repositories/__init__.py`
  - ... (+9 more)

## [2026-11-25] feat: Step 2: Unified SourceRef Provenance, ActiveSourceContext & Media Freeze Controls
- **Type**: feat
- **Summary**: Implemented canonical SourceRef provenance, world_timeline_events run_id migration, ActiveSourceContext cross-tab sync, #studio and Enrollment /freeze_frame controls, and #journey/#review deep-link jump buttons.
- **Files** (9):
  - `.diagnostics/probes/deep_link_navigation_probe.py`
  - `.diagnostics/probes/spa_nine_tab_sweep.js`
  - `dashboard/static/js/enrollment_stage_controller.js`
  - `dashboard/static/js/journey_search.js`
  - `dashboard/static/js/universal_enrollment.js`
  - `dashboard/static/js/video_timeline_links.js`
  - `dashboard/static/partials/modals/entity_modals.html`
  - `dashboard/static/review_and_rsac.js`
  - ... (+1 more)

## [2026-11-25] feat: Step 1: P0 Integration Seams and Probe Hardening
- **Type**: feat
- **Summary**: Upgraded probe_runner, cdp_inspect/audit_layout, cross_module_rules (SILENT_SHAPE_SKIP), and surface_contracts/surface_verifier; added 5 workspace seam probes and hardened spa_nine_tab_cdp_probe.
- **Files** (2):
  - `.diagnostics/probes/`
  - `CHANGELOG.md`

## [2026-11-24] feat: Step 4 M3: Minimap Interactions and Stale Camera Pruning
- **Type**: feat
- **Summary**: Pruned stale cameras from /api/topology/world-map via world_map_service, cleaned up camera_world_poses on CameraPool.remove_camera, and added interactive 2D minimap cone-focus and origin/yaw/range drag controls.
- **Files** (8):
  - `dashboard/services/world_map_service.py`
  - `dashboard/routers/topology.py`
  - `dashboard/camera_pool.py`
  - `dashboard/static/js/world_minimap.js`
  - `dashboard/static/js/world_minimap_interactions.js`
  - `dashboard/static/partials/scripts_studio.html`
  - `dashboard/static/studio.js`
  - `tests/test_step4_minimap_interactions.py`
