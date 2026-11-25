# Step 2: Unified `SourceRef` Provenance, `ActiveSourceContext` & Media Freeze Controls

> **Parent Roadmap**: `.TODO/integration_seams_entity_persistence_master_roadmap.md` (`Step 2 of 4` | `--parent integration_seams_entity_persistence_master_roadmap --milestone 2`).
> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADRs 01–20`, specifically `ADR-15` & `ADR-16`) & `docs/architecture/CURRENT_ARCHITECTURE.md` (`BUG-21`, `BUG-26`, `BUG-30`).
> **Execution Rule**: Strict **1-Milestone-Per-Turn**. Execute Milestone 1 first via `/frontier-architect continue step_2_sourceref_and_active_source_context`; Milestones 2–4 are deferred to subsequent turns. Every milestone enforces `<= 8` modified production files and passes a fresh **Review Gate** before advancing.

---

## Pre-Flight Architecture & Modularity Contract

### Hard Budget & Invariant Guards (Measured Baseline)
- **Strict File & Method Ceilings (DO NOT EXCEED)**:
  - `dashboard/static/app.js`: currently `359L` (WARN) — do **not** expand; place shared source state in `dashboard/static/js/active_source_context.js` and hash routing in `dashboard/static/js/app_navigation.js` (`119L`).
  - `dashboard/static/studio.js`: currently `348L` (`<= 350L` enforced by `tests/test_step3_architecture_budgets.py`) — place `#studio` freeze-frame Pause/Resume, `selectZoneById`, and `ActiveSourceContext` hooks in `dashboard/static/js/studio_canvas.js` (`252L`), adding at most a 1-line export reference on `window.Studio`.
  - `dashboard/static/js/universal_enrollment.js`: currently `347L` (`<= 350L`) — place Enrollment live/freeze toggle and `ActiveSourceContext` sync in `dashboard/static/js/enrollment_stage_controller.js` (`97L`).
  - `dashboard/static/js/gallery_timeline.js` (`349L`), `dashboard/static/js/alerts_view.js` (`349L`), `dashboard/static/js/live_player.js` (`348L`), `dashboard/routers/cameras.py` (`342L`, `< 350L` test cap) — do **not** expand.
  - `intelligent_tracker/matching/gallery.py` (`321L`, `GalleryMatcher: 12` methods) & `intelligent_tracker/batch.py` (`308L`, `VideoIndexer: 12` methods) — at the `12`-method ceiling; attach `run_id` as an instance attribute via `video_analytics_service.py` without adding methods to either class.
  - `intelligent_tracker/repositories/analytics_repo.py` (`335L`, `AnalyticsMixin: 11` methods) — place `/analytics/flows` media-ref enrichment in `intelligent_tracker/repositories/analytics_flow_helpers.py` (`152L`).
  - `intelligent_tracker/journey_segmenter.py` (`137L`, `< 160L` enforced by `tests/test_step4_preflight_budgets.py`) & `intelligent_tracker/journey.py` (`151L`, `< 170L` enforced by `tests/test_step4_preflight_budgets.py`) — keep strictly below `160L` and `170L` respectively, and resolve the `mypy` `union-attr` warning at `journey.py:82` (`conn = self._db._conn; if conn is None: return []`).
  - `dashboard/static/index.html` (`172L`, `< 180L` enforced) — include `active_source_context.js` via `dashboard/static/partials/scripts_traceability.html` (`6L`), preserving `app.js` before `nav_tabs_manager.js`.
  - `dashboard/static/partials/modals/entity_modals.html` (`219L`, `< 240L` enforced), `dashboard/static/partials/tabs/analytics.html` (`59L`, `< 220L`, zero eager `src="/analytics/heatmap"`), `dashboard/static/partials/tabs/studio.html` (`103L`, `< 220L`).
- **Component Reuse & Runtime Invariants**:
  - Reuse existing `MediaEmptyState` (`dashboard/static/js/media_empty_state.js`), `VideoTimelineLinks` (`dashboard/static/js/video_timeline_links.js`), and standard `.form-control-sm` / `.btn-outline` toolbar controls — zero new overlapping UI components.
  - Preserve `#btn-capture-freeze`, `#heatmap-camera-badge`, `#heatmap-colorbar-legend`, and `data-src="/analytics/heatmap"` for legacy contract tests (`test_refactor_contract.py`, `test_step2_tab_scoped_streams.py`).
  - Every `*_repo.py` write method calls `self._conn.rollback()` in `except` before re-raising.
  - All tests use `tempfile.TemporaryDirectory()`, `detector=mock`, reverse-order `addCleanup()`, and `<= 40L`/method.

---

## Milestone 1: `SourceRef` Backend SSOT, `world_timeline_events` Migration & Pipeline `run_id` Wiring *(Active Slice)*

- [x] **intelligent_tracker/source_ref.py**: Create canonical `SourceRef` builder and normalizer (`build_source_ref`, `snapshot_path_to_url`) serializing `{ kind, camera_id, video_filename, run_id, media_offset_sec, ts, track_id, entity_id, zone_id, bbox, snapshot_url }` with clean empty-value omission and safe `/api/crops/<name>` URL mapping (`<= 40L`/fn).
- [x] **intelligent_tracker/repositories/schema_manager.py**: Add idempotent `PRAGMA user_version = 3` migration adding `run_id TEXT DEFAULT ''` and `idx_timeline_run_id` on `world_timeline_events` (with `self._conn.rollback()` on error).
- [x] **intelligent_tracker/repositories/sightings_query_helpers.py**: Match `source` filter against `(s.camera_id = ? OR s.source = ?)` and support explicit `camera_id` and `run_id` filter parameters in `build_sightings_where_clause`.
- [x] **intelligent_tracker/memory/_event_formatters.py** + **intelligent_tracker/repositories/memory_repo.py**: Propagate `run_id` and `source_ref` (`build_source_ref`) through timeline event normalization, `MemoryMixin.index_timeline_event` (`self._conn.rollback()` in `except`), and timeline event read payloads.
- [x] **intelligent_tracker/matching/_gallery_matching.py** + **intelligent_tracker/matching/_gallery_signals.py**: Forward `run_id=getattr(matcher, "run_id", "")`, `video_filename=getattr(matcher, "video_filename", "")`, and `media_offset_sec=float(getattr(matcher, "current_media_offset_sec", 0.0) or 0.0)` in `_notify_active_learning()` so `review_queue` rows persist `run_id`; pass explicit `camera_id` and `run_id` in `emit_periodic_sighting()`.
- [x] **dashboard/services/video_analytics_service.py**: Pre-generate `run_id = f"run_{uuid.uuid4().hex[:8]}"` before `indexer.process_video()`, attach `run_id` onto `indexer`, `gallery_matcher`, and `active_learning` (zero new methods on `VideoIndexer` or `GalleryMatcher`), and pass the same `run_id` into `finalize_analytics_report()` / `save_report_run()`.
- [x] **tests/test_step2_sourceref_and_context.py**: Add isolated backend unit & integration tests (`tempfile.TemporaryDirectory()`, `detector=mock`, reverse `addCleanup()`, `<= 40L`/method) covering `build_source_ref`, `PRAGMA user_version = 3` migration, `sightings` `(camera_id OR source)` + `run_id` queries, `world_timeline_events.run_id` + `source_ref`, and `video_analytics_service` -> `_gallery_matching` -> `review_queue.run_id` + `_gallery_signals` `sightings.camera_id`/`run_id`.

**Milestone 1 Verifier**:
```bash
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/source_ref.py intelligent_tracker/repositories/schema_manager.py intelligent_tracker/repositories/sightings_query_helpers.py intelligent_tracker/memory/_event_formatters.py intelligent_tracker/repositories/memory_repo.py intelligent_tracker/matching/_gallery_matching.py intelligent_tracker/matching/_gallery_signals.py dashboard/services/video_analytics_service.py tests/test_step2_sourceref_and_context.py --max-lines 350 --max-fn-lines 40
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step2_sourceref_and_context.py tests/test_step1_seams_backend.py
```

---

## Milestone 2: `JourneyHop` Track Provenance & Analytics Flow/Heatmap Media References *(Deferred to Next Turn / Milestone 2)*

> *Deferred to Next Turn / Milestone 2*

- [ ] **intelligent_tracker/journey_models.py**: Extend `JourneyHop` with `track_id: Optional[int] = None`, `run_id: str = ""`, `snapshot_url: str = ""`, and `source_ref: dict[str, Any] = field(default_factory=dict)` serialized in `to_dict()`.
- [ ] **intelligent_tracker/journey_segmenter.py** + **intelligent_tracker/journey.py**: Resolve `camera_id` ahead of `source` in `segment_sightings_into_hops`, populate `track_id`, `run_id`, `snapshot_url`, and `source_ref` (`build_source_ref`) in `build_journey_hop` (keeping `journey_segmenter.py < 160L`), and guard `conn = self._db._conn; if conn is None: return []` in `TrajectoryJourneySearcher._fetch_sightings` while selecting `camera_id` & `run_id` (keeping `journey.py < 170L` and `mypy`-clean).
- [ ] **intelligent_tracker/repositories/analytics_flow_helpers.py**: Match `(camera_id = ? OR source = ?)` in `_accumulate_timeline_events` and `_accumulate_sightings`, attach top-level `source_ref`, and include bounded `media_refs` (`camera_id`, `video_filename`, `media_offset_sec`, `run_id`, `snapshot_url`, `zone_id`, `source_ref`) per bucket on `GET /analytics/flows`.
- [ ] **dashboard/services/analytics_query_service.py**: Enrich `build_heatmap_json` (`GET /analytics/heatmap?format=json`) with `source_ref`, `image_url`, `freeze_frame_url`, and hotspot `peak_media_ref` / cell `source_ref` drill-down metadata, and attach `source_ref` to `/sightings` response records.
- [ ] **tests/test_step2_sourceref_and_context.py**: Expand backend test suite (`<= 40L`/method) verifying `JourneyHop.track_id`/`run_id`/`source_ref` round-trips on `/api/journey/search`, `journey.py` closed-DB guard, `/analytics/flows` per-bucket `media_refs`, and `/analytics/heatmap?format=json` media reference fields.

**Milestone 2 Verifier**:
```bash
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker/journey_models.py intelligent_tracker/journey_segmenter.py intelligent_tracker/journey.py intelligent_tracker/repositories/analytics_flow_helpers.py dashboard/services/analytics_query_service.py tests/test_step2_sourceref_and_context.py --max-lines 350 --max-fn-lines 40
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step2_sourceref_and_context.py tests/test_step4_m1_analytics_flows.py tests/test_step4_preflight_budgets.py
```

---

## Milestone 3: Shared `ActiveSourceContext`, Hash `SourceRef` Routing & `#studio` Freeze Controls *(Deferred to Next Turn / Milestone 3)*

> *Deferred to Next Turn / Milestone 3*

- [ ] **dashboard/static/js/active_source_context.js** + **dashboard/static/partials/scripts_traceability.html**: Create `window.ActiveSourceContext` (`localStorage['it_active_source_ref']` synced with `it_focused_camera_id`, URL hash pin override, camera + `video:<fn>` `<select>` population from `/api/cameras` + `/api/videos`, source-availability check + `MediaEmptyState.showEmpty` helper, and reusable `bindFreezeToggle` calling `GET /api/cameras/{id}/freeze_frame` for Pause/Resume), loaded via `scripts_traceability.html` (`index.html < 180L`).
- [ ] **dashboard/static/js/app_navigation.js**: Extend `parseHash`, `buildHash`, `paramsToSourceRef`, and `applySourceRef` with full `ADR-15` `SourceRef` fields (`kind`, `cameraId`, `videoFilename`, `runId`, `mediaOffsetSec`, `ts`, `trackId`, `entityId`, `zoneId`, `bbox`), add `tab-analytics` and `tab-videos` routing, sync `ActiveSourceContext`, and render `MediaEmptyState` with a clear message when a deep-linked camera or video does not exist.
- [ ] **dashboard/static/partials/tabs/analytics.html** + **dashboard/static/js/analytics_view.js** + **dashboard/static/js/analytics_drilldown.js**: Add `<select id="analytics-source-select">` to `analytics.html` (`< 220L`, preserving `data-src="/analytics/heatmap"`, `#heatmap-camera-badge`, `#heatmap-colorbar-legend`), bind `#analytics` to `ActiveSourceContext` (including unavailable-source `MediaEmptyState`), and route all `analytics_drilldown.js` flow/hotspot jumps through `App.navigate` with `SourceRef` media refs (`BUG-26`).
- [ ] **dashboard/static/partials/tabs/studio.html** + **dashboard/static/js/studio_canvas.js**: Add `#btn-studio-freeze-toggle` (`⏸ Freeze Frame` / `▶ Resume Live`) to `studio.html` (`< 220L`), sync `#studio-camera-select` with `ActiveSourceContext`, implement `/freeze_frame` Pause/Resume on `#studio-live-img` and `selectZoneById(zoneId)` in `studio_canvas.js` (`< 350L`, keeping `studio.js <= 350L`) (`BUG-21`).
- [ ] **tests/test_step2_sourceref_and_context.py**: Add Node VM (`vm.runInNewContext`) frontend tests (`<= 40L`/method) covering `ActiveSourceContext` `localStorage` + hash pin override, full `SourceRef` hash serialization, unavailable-source `MediaEmptyState` across `#live`/`#analytics`/`#studio`, `#analytics-source-select` sync + drilldown `App.navigate`, and `#studio` `/freeze_frame` Pause/Resume + `selectZoneById`.

**Milestone 3 Verifier**:
```bash
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/static/js/active_source_context.js dashboard/static/js/app_navigation.js dashboard/static/js/analytics_view.js dashboard/static/js/analytics_drilldown.js dashboard/static/js/studio_canvas.js tests/test_step2_sourceref_and_context.py --max-lines 350 --max-fn-lines 40
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step2_sourceref_and_context.py tests/test_step1_seams_frontend.py tests/test_step3_analytics_drilldown.py tests/test_step2_tab_scoped_streams.py
```

---

## Milestone 4: Enrollment Freeze Controls, `#journey` / `#review` Deep Links & Seam Probes *(Deferred to Next Turn / Milestone 4)*

> *Deferred to Next Turn / Milestone 4*

- [ ] **dashboard/static/partials/modals/entity_modals.html** + **dashboard/static/js/enrollment_stage_controller.js**: Add `#btn-enroll-live-toggle` (`▶ Live` / `⏸ Freeze`) alongside `#btn-capture-freeze` in `entity_modals.html` (`< 240L`), sync `#enroll-camera-select` with `ActiveSourceContext`, and wire camera live-preview <-> `/freeze_frame` Pause/Resume in `enrollment_stage_controller.js` (`< 350L`, keeping `universal_enrollment.js <= 350L`) (`BUG-30`).
- [ ] **dashboard/static/js/video_timeline_links.js**: Add `buildSourceJumpButtonsHtml(sourceRef)` and delegated click handlers routing Live Monitor (`App.navigate('tab-live', ref)`), Scenario Studio (`App.navigate('tab-studio', ref)`), and Video Studio (`App.navigate('tab-videos', ref)` / `seekInVideoStudio`) jumps.
- [ ] **dashboard/static/js/journey_search.js** + **dashboard/static/review_and_rsac.js**: Guard `.hop-thumb img` in `journey_search.js` (`< 350L`) with `onerror` fallback + `MediaEmptyState`, render `track_id` badge when present, and add Live/Studio/Video deep-link jump buttons via `VideoTimelineLinks.buildSourceJumpButtonsHtml` on both `#journey` hop cards and `#review` queue cards (`review_and_rsac.js < 350L`) (`BUG-30`).
- [ ] **.diagnostics/probes/deep_link_navigation_probe.py** + **.diagnostics/probes/spa_nine_tab_sweep.js**: Expand `deep_link_navigation_probe` and `spa_nine_tab_cdp_probe` sweep assertions to verify `tab-analytics` & `tab-videos` hash `SourceRef` round-trips, `ActiveSourceContext` sync across `#live`/`#analytics`/`#studio`/Enrollment, unavailable-source `MediaEmptyState`, `/freeze_frame` buttons, and `#journey`/`#review` jump buttons (passing outright, zero `INFRA_UNAVAILABLE`).
- [ ] **tests/test_step2_sourceref_and_context.py**: Add Node VM & contract tests (`<= 40L`/method) covering Enrollment `ActiveSourceContext` + live/freeze toggle, `journey_search.js` `onerror`/`MediaEmptyState` fallback + `track_id` + Live/Studio jump buttons, and `review_and_rsac.js` `run_id` + Live/Studio jump buttons.
- [ ] **CHANGELOG.md**: Record Step 2 completion via `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add`.

**Milestone 4 Verifier**:
```bash
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests/test_step2_sourceref_and_context.py tests/test_step4_m3_world_minimap_and_journey.py tests/test_step4_m4_review_studio_sync.py tests/test_step3_architecture_budgets.py
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify --strict
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run deep_link_navigation_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run spa_nine_tab_cdp_probe
```

---

## Scenario Combinations Matrix

| Scenario Dimension | Test / Probe Matrix Covered | Expected Outcome |
| :--- | :--- | :--- |
| **Source Type (`camera` vs. `video:<fn>` vs. missing ID)** | Deep link `#live?camera=ghost`, `#analytics?camera=cam_short`, `#studio?video=recorded_clip.mp4&zone=z1`, Enrollment open from `#videos` vs. `#live` | Valid sources sync across `ActiveSourceContext` selectors; missing source renders `MediaEmptyState` cleanly with zero broken `<img>` or `'cam_01'` fallback |
| **Provenance Chain (`sightings` x `world_timeline_events` x `review_queue`)** | `VideoIndexer` run (`run_id`) + live `emit_periodic_sighting` (`camera_id`) -> `/api/journey/search`, `/analytics/flows`, `/analytics/heatmap?format=json`, `/review` | `JourneyHop` carries `track_id`/`run_id`/`source_ref`; flow buckets & heatmap JSON expose `media_refs`; `review_queue` stores exact `run_id` |
| **Preview State (`Live Stream` <-> `Paused /freeze_frame`)** | Toggle `#btn-studio-freeze-toggle` in `#studio` and `#btn-enroll-live-toggle` in `#modal-universal-enrollment` (online `200` vs. offline `503`) | Pause fetches `/api/cameras/{id}/freeze_frame` and freezes frame for clean vertex/bbox drawing; Resume restores live feed; `503` shows `MediaEmptyState` |
| **Cross-Tab Drill-Downs (`#journey`, `#review`, `#analytics`)** | Click Live/Studio/Video jump on camera hop, video hop (with broken crop `onerror`), review card, and flow/hotspot bucket | Routes via `App.navigate(tab, sourceRef)`, updates URL hash, awaits channel/filter loaders, and renders fallback thumbnail without console/network errors |

---

## Final Step Sign-Off Verifier (After Milestone 4)

```bash
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify --strict
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" scan --path intelligent_tracker dashboard scripts --strict
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker dashboard scripts
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run deep_link_navigation_probe
python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" probe run spa_nine_tab_cdp_probe
MPLBACKEND=Agg python -m unittest discover tests
python -m sphinx -W --keep-going documentation/ documentation/_build/html/
```