# Tracking, Intelligence & Dashboard UX Master Roadmap

> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–09`, Layers 1–5) & `docs/architecture/CURRENT_ARCHITECTURE.md` (branch `feature/integration-remediations`, `939` passing tests).
> **How to use this document**: Execute one Step at a time via child plans linked in `.frontier/` (`--parent tracking_intelligence_ux_master_roadmap --milestone <N>`).
> **Decision Basis (`/grill-me`, 6/6 questions resolved)**:
> 1. **Roadmap Structure**: 4-Step Master Roadmap: Step 1 Critical Bug Remediations (`Findings 1–7`, `BE-1..BE-4`) & Tooling/Probe Elevation -> Step 2 Hybrid Persistent-Entity Tracking, Occlusion & Person+Bag Ownership (`Ideas 2–4`, `ADR-07`) -> Step 3 Custom Object Learning, Negative Feedback, Dynamic Badges & Enrollment Scrubber (`Idea 1`, `Finding 5`, `ADR-08`) -> Step 4 Analytics Flows, Alerts Canvas & Calibrated BEV Minimap, Journey Autocomplete & Bidirectional Review Sync (`Ideas 5–8`, `ADR-09`).
> 2. **Tracking, Occlusion & Person+Bag (`Step 2` / `ADR-07`)**: Hybrid Persistent-Entity Tracking defaulting to SORT/Kalman coasting (`confirmed | coasting | occluded`, ~1.5s grace) so short dropouts retain Re-ID and `WorldGraph` state, class-consistency + appearance-assisted matching, and `WorldGraph` `CARRIES`/`OWNED_BY` edges for person+bag and dropped-item alerts.
> 3. **Custom Object Learning & Collision Guard (`Step 3` / `ADR-08`)**: Full Re-ID learning with draw-anywhere ROI teaching + click-to-correct/discourage negative exemplars, dynamic Semantic Category Badge CRUD across modals/filters, pre-enrollment cosine-similarity collision check (`Merge vs. Create New`), and split `Detector Classes (COCO)` vs. `Tracked Gallery Entities/Categories` filters.
> 4. **UI Component Reuse (`Step 1` & `Step 3` / `ADR-05`)**: Preserve drawn rectangular ROI aspect ratios (`object-fit: contain`) in Tag/Gallery/Timeline previews; group Camera/Video Source selector with Enrollment preview + auto-refresh + extracted `scrubber-timeline-slider`; mount a `<video>` stage inside `#studio` for `"Recorded Videos"`.
> 5. **Analytics, Alerts/BEV, Journey & Review (`Step 4` / `ADR-09`)**: Real SQLite time-bucketed traffic flows + pagination + "Back to Live" + heatmap legend; server-side `#alerts` filters/pagination + reused `UnifiedCanvasOverlay` preview; calibrated `WorldTacticalMinimap` (`/api/topology/world-map`); `#journey` `/api/entities/suggest` prefix autocomplete; bidirectional Video Studio <-> Review & Learn sync.
> 6. **Tooling & Probe Elevation (`Step 1`, Milestone 3)**: Elevate BOTH workspace probes (`.diagnostics/probes/`) AND global `system-diagnostics` SSOT (`audit_layout.js`, `surface_verifier.py`, `shadow_prober.py`) in an isolated Milestone 3 with skill self-tests.

---

## Step 1: Critical Bug Remediations (Findings 1–7, `BE-1..BE-4`) & Tooling/Probe Elevation
- [x] **Child Plan**: `.TODO/step_1_critical_bugs_and_tooling.md`
- [x] **Goal**: Resolve all 7 user-observed visual/functional defects (`Findings 1–7`), close critical backend runtime/persistence/lock seams (`BE-1..BE-4`), fix `window.MULTIVIEW_TOKEN` surface mismatch, and upgrade workspace probes + global `system-diagnostics` SSOT so this entire class of regression is caught automatically.
- [x] **Target Scope**:
  - [x] **Backend Critical Seams (`BE-1`, `BE-2`, `BE-4`, `Finding 1`, `Finding 4`)**: Eliminate `primary_stream` aliasing on explicit `camera_id` in `resolve_stream_manager`; stop double-cropping `crop_base64` with full-frame `bbox` in `RoiRecognitionService.extract_roi_crop`; add `self._conn.rollback()` to `SignatureMixin`; decouple `app.state.db` lifecycle from `PipelineBundle.close()`; remove I/O from `StreamRecordingController._lock`/`CameraPool._lock`; fix DI bypasses in `tagging.py`/`analytics.py` and `AsyncInferenceWorker` clock fallback.
  - [x] **Frontend & Multiview Fixes (`Findings 1–7`, `MULTIVIEW_TOKEN`)**: Show offline `1x1` poster on failed/offline cameras; add `ResizeObserver` / clear stale inline dimensions and stale tracks on `tile-overlay-canvas` across `2x2 <-> 3x3 <-> 4x4`; keep `RoiDrawTagger` dashed drag box visible across `mousemove`/telemetry and switch ROI previews/thumbs to `object-fit: contain`; move & wire `#enroll-camera-select` inside Enrollment preview column; fix `nav_tabs_manager.js` script load order after `app.js`, `#analytics` cold-boot heatmap + legend, `#studio` initial stream attach + `<video>` player for `"Recorded Videos"`, and `window.MULTIVIEW_TOKEN` read.
  - [x] **Isolated Tooling & Probe Elevation**: Upgrade `spa_nine_tab_cdp_probe.py` (mixed online/offline/recorded cameras + `tile-overlay-canvas` `DOMRect` parity) and `video_studio_contract_probe.py` (2-step `recognize-roi -> commit` crop shape & variance); upgrade global `system-diagnostics` SSOT (`audit_layout.js` broken-`<img>` audit, `surface_verifier.py` query-param & script-order rules, `shadow_prober.py` repo-rollback AST rule) + skill tests.
- [x] **Definition of Done**: Upgraded probes, `system-diagnostics` skill tests, `surface --verify --strict`, `scan --strict`, and full `unittest` pass 100% with Findings 1–7 & `BE-1..BE-4` resolved.

---

## Step 2: Hybrid Persistent-Entity Tracking, Occlusion Coasting & Person+Bag Ownership (`Ideas 2–4`, `BE-3`, `ADR-07`)
- [x] **Goal**: Eliminate detection/identity flickering during brief misses and occlusions, enforce class & appearance consistency during track association, and track person+bag ownership and dropped/left-behind items in `WorldGraph`.
- [x] **Target Scope**:
  - [x] **Persistent Coasting & Re-ID Retention**: Enable configurable Kalman/SORT coasting (`confirmed | coasting | occluded`, ~1.5s grace) in `SortTracker`/`CentroidTracker`; preserve `Track` attributes (`is_cluttered`, `clutter_partner_id`) across frames instead of reinstantiating fresh `Track` objects; keep `GalleryMatcher._track_features` and `WorldEntityBridge` bindings alive while coasting/occluded.
  - [x] **Class-Consistency & Appearance-Assisted Association**: Prevent class swaps (`person` <-> `chair`) and integrate lightweight appearance similarity + `SessionGalleryManager` re-linking across frames and `VideoIndexer` / `CachedReplayProvider` sampling gaps.
  - [x] **Person+Bag `WorldGraph` Associations**: Add `CARRIES` / `OWNED_BY` edges in `WorldGraph` linking person tracks to carry-on items (`backpack`, `handbag`, `suitcase`) and emit unattended/dropped-item events with location & timestamp when separated beyond threshold.
- [x] **Definition of Done**: Multi-frame dropout, occlusion cross-over, and person+bag drop regression tests + probes pass without premature Re-ID purges or ID swaps.

---

## Step 3: Supervised Re-ID Learning, Negative Feedback, Dynamic Semantic Badges & Unified Enrollment (`Idea 1`, `Finding 5`, `ADR-08`)
- [ ] **Goal**: Enable draw-anywhere ROI teaching and click-to-discourage/correct false detections, provide full Semantic Category Badge CRUD with pre-enrollment descriptor collision warnings, split COCO vs. gallery filters, and reuse Video Studio's scrubber inside Enrollment.
- [ ] **Target Scope**:
  - [ ] **Negative/Correction Exemplars & Draw-Anywhere Tagging**: Allow arbitrary ROI draw-to-teach in Live Monitor & Video Studio plus click-to-correct/discourage false labels on tracked/detected objects (persisting negative/override exemplars in SQLite + `GalleryMatcher` suppression).
  - [ ] **Dynamic Semantic Category Badges & Collision Guard**: Add `/api/rsac/categories` CRUD synced across Enrollment, Tag, Quick-Enroll, and Gallery filters; add pre-enrollment cosine-similarity collision check against `db.get_gallery_embeddings()` surfacing `Merge vs. Create New` before commit.
  - [ ] **Target Class Filter Split & Extracted Enrollment Scrubber**: Separate `Detector Classes (COCO)` from `Tracked Gallery Entities/Categories` in UI config/filters; extract reusable `scrubber-timeline-slider` component and mount it in Universal Enrollment when a recorded video source is chosen.
- [ ] **Definition of Done**: End-to-end tests verify negative-exemplar suppression, pre-enrollment collision detection, badge CRUD sync, and Enrollment video-frame scrubbing.

---

## Step 4: Real-Time Analytics Flows, Alerts Canvas & BEV Minimap, Journey Autocomplete & Review Loop (`Ideas 5–8`, `ADR-09`)
- [ ] **Goal**: Replace synthetic analytics and flat alert tables with filterable historical insights, reusable overlay/BEV visualizers, prefix entity autocomplete, and a bidirectional Video Studio <-> Review & Learn workflow.
- [ ] **Target Scope**:
  - [ ] **`#analytics` Time-Bucketed Flows & Heatmap Legend**: Add SQLite time-bucketed traffic-flow aggregation endpoint + time-range navigation + "Back to Live" toggle (`analytics_view.js` removes `0.6x/0.4x` synthetic math) and rich heatmap colorbar/camera metadata legend.
  - [ ] **`#alerts` Filters/Pagination, Reused Canvas & Calibrated `WorldTacticalMinimap`**: Extend `GET /events` with `camera_id`, `severity`, `event_type`, `zone_id`, `start_time`, `end_time`, and `offset` pagination; reuse `UnifiedCanvasOverlay` + `OverlayControlBar` in alert snapshot previews; wire `/api/topology/world-map` (`WorldTacticalMinimap`: calibrated grid, zones, FOV cones, velocity vectors, pose controls).
  - [ ] **`#journey` Autocomplete & Bidirectional `#review` Loop**: Add `/api/entities/suggest` prefix/substring autocomplete (`#journey-search-query` + `Enter` submit); surface Video Studio tags & proactive low-confidence candidates cleanly in `#review` with bbox context and auto-resolution sync back to studio reports/galleries.
- [ ] **Definition of Done**: All 9 SPA tabs pass end-to-end API + headless CDP runtime verification, full `unittest`, `arch-map`, and `sphinx -W`.

---

## Master Verification Matrix

| Verification Gate | Command | Expected Result |
| :--- | :--- | :--- |
| **Skill Self-Tests** | `python -m unittest discover -s skills/system-diagnostics/tests -p "test_*.py"; python -m unittest discover -s skills/frontier-architect/tests -p "test_*.py"; python -m unittest discover -s skills/app-debugger/tests -p "test_*.py"` | 100% pass after Step 1 Milestone 3 tool upgrades |
| **Cross-Contract & Static Gate** | `python skills/system-diagnostics/scripts/diagnose.py surface --verify --strict; python skills/system-diagnostics/scripts/diagnose.py scan --path intelligent_tracker dashboard scripts --strict; python skills/system-diagnostics/scripts/diagnose.py audit --path intelligent_tracker dashboard scripts --typecheck` | 0 unmatched routes/IDs/query-params/scripts, 0 active scan defects |
| **4 Unmocked Workspace Probes** | `python skills/system-diagnostics/scripts/diagnose.py probe run cold_boot_world_probe; python skills/system-diagnostics/scripts/diagnose.py probe run replay_pipeline_probe; python skills/system-diagnostics/scripts/diagnose.py probe run video_studio_contract_probe; python skills/system-diagnostics/scripts/diagnose.py probe run spa_nine_tab_cdp_probe` | 100% pass with Findings 1–7 & mixed-camera checks covered |
| **Headless CDP Layout & Media Sweep** | `python skills/system-diagnostics/scripts/diagnose.py ui --url "$APP_URL" --headless --capture-runtime --audit-layout --stability-ms 2000 --strict` | 0 HTTP >= 400, 0 broken `<img>`, 0 JS errors, 0 CLS/overflows |
| **Full Regression & Docs Gate** | `MPLBACKEND=Agg python -m unittest discover tests; python skills/system-diagnostics/scripts/diagnose.py arch-map --path .; python -m sphinx -W --keep-going documentation/ documentation/_build/html/` | 100% test pass, clean budgets, 0 Sphinx warnings |
