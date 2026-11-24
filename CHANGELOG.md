# Changelog

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

## [2026-11-23] feat: Step 3 Milestone 3: Target Class Filter Split, Enrollment Scrubber & Sign-Off
- **Type**: feat
- **Summary**: Split COCO detector_classes vs gallery tracked_categories across API/pipeline/UI and extracted ScrubberTimelineSlider for video_scrubber and Universal Enrollment.
- **Files** (26):
  - `dashboard/camera_pool.py`
  - `dashboard/routers/cameras.py`
  - `dashboard/routers/system.py`
  - `dashboard/routers/video_jobs.py`
  - `dashboard/routers/videos.py`
  - `dashboard/schemas.py`
  - `dashboard/services/camera_config_store.py`
  - `dashboard/services/stream_pool_coordinator.py`
  - ... (+18 more)
- **Verification**: python -m unittest discover tests

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
