# Changelog

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

## [2026-11-24] feat: Step 3: Traceability, Analytics Drill-Down & Stateful Alerts Lifecycle
- **Type**: feat
- **Summary**: Added #timeline pagination and Live/Studio jump links, #analytics explicit X/Y axes and 32x24 peak/hotspot drill-down, #alerts unread state (is_read/acknowledged_at) and /api/events/* admin endpoints, and #alerts frontend lifecycle (alerts_admin.js, facets datalists, mark-read/delete/clear/export, snapshot download, Live/Studio deep-links, real unread_alert_count badge sync).
- **Files** (10):
  - `dashboard/static/partials/tabs/alerts.html`
  - `dashboard/static/partials/scripts_traceability.html`
  - `dashboard/static/partials/modals/video_modals.html`
  - `dashboard/static/css/analytics_alerts.css`
  - `dashboard/static/js/alerts_admin.js`
  - `dashboard/static/js/alerts_view.js`
  - `dashboard/static/app.js`
  - `dashboard/static/js/multiview/grid_tile_overlay.js`
  - ... (+2 more)
- **Verification**: diagnose.py audit/surface/scan PASS; 37 targeted Step 3 M4 tests OK

## [2026-11-24] feat: Step 2 M1: Unified Category SSOT, Universal Defaults & COCO Mapping
- **Type**: feat
- **Summary**: Added intelligent_tracker/category_registry.py with 9 universal defaults, legacy migration/pruning, slug validation, and COCO label mapping; wired CategoryRepoMixin into TrackerDB; moved /api/rsac/categories CRUD + export/import + guarded delete to dashboard/routers/categories.py; enforced category SSOT validation across entity/tag/review/enroll/RSAC routes.
- **Files** (16):
  - `intelligent_tracker/category_registry.py`
  - `intelligent_tracker/repositories/category_repo.py`
  - `intelligent_tracker/repositories/schema_manager.py`
  - `intelligent_tracker/rsac.py`
  - `intelligent_tracker/database.py`
  - `intelligent_tracker/analytics/zone_stats.py`
  - `dashboard/services/category_service.py`
  - `dashboard/routers/categories.py`
  - ... (+8 more)
- **Verification**: plan_engine verify: 53/53 OK; targeted 14 modules: 88/88 OK; audit: 0 new issues; surface --verify --strict: 0 mismatches; discover tests: 1024/1027 (3 unrelated timing races pass standalone)

## [2026-11-24] feat: Step 1: Re-ID unification, sighting crops, responsive dialogs, and diagnostics elevation
- **Type**: feat
- **Summary**: Unified DualModel Re-ID, sighting crop persistence, wide/resizable dialogs, MediaEmptyState, and upgraded system-diagnostics rules and workspace probes.
- **Files** (4):
  - `.diagnostics/probes/replay_pipeline_probe.py`
  - `.diagnostics/probes/spa_nine_tab_cdp_probe.py`
  - `.diagnostics/probes/spa_nine_tab_sweep.js`
  - `.diagnostics/probes/video_studio_contract_probe.py`

## [2026-11-23] feat: Step 4 M4: Bidirectional #review <-> Video Studio Sync & Full Sign-Off
- **Type**: feat
- **Summary**: Migrated review_queue with bbox/frame/run_id provenance, added ReviewSyncService + /api/review/* router, wired frontend VideoBatchReports/Gallery/Review sync, and verified 1008 tests + 4 probes.
- **Files** (20):
  - `.diagnostics/probes/spa_nine_tab_cdp_probe.py`
  - `dashboard/app.py`
  - `dashboard/routers/__init__.py`
  - `dashboard/routers/topology.py`
  - `dashboard/services/negative_exemplar_service.py`
  - `dashboard/services/roi_recognition_service.py`
  - `dashboard/static/css/review.css`
  - `dashboard/static/js/interactive_canvas.js`
  - ... (+12 more)
- **Verification**: MPLBACKEND=Agg python -m unittest discover tests
