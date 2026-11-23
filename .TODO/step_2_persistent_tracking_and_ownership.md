# Step 2: Hybrid Persistent-Entity Tracking, Occlusion Coasting & Person+Bag Ownership

> **Parent Roadmap**: `.TODO/tracking_intelligence_ux_master_roadmap.md` (`Step 2 of 4` | `--parent tracking_intelligence_ux_master_roadmap --milestone 2`).
> **Architecture Reference**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md` (`ADR-07`, Layers 1–4) & `docs/architecture/CURRENT_ARCHITECTURE.md` (`BE-3`).
> **Scope & Modularity Budgets**: 3 cohesive milestones (`<= 7` modified/new production files per milestone), strict modularity limits (`< 350L` soft / `< 500L` hard per file, `<= 12` methods/class, `<= 40L`/function). Enforce **Split-Before-You-Grow** for `intelligent_tracker/matching/gallery.py` (425L), `CentroidTracker` (12 methods), `SortTracker` (10 methods), and `WorldEntityBridge` (324L).

---

## Pre-Flight Architecture & Contract Invariants

1. **`Track` `entity_id` Invariant**: Unidentified `Track` instances must NOT define an `entity_id` attribute (`hasattr(trk, "entity_id") == False`); `Track.to_dict()` continues to read `getattr(self, "entity_id", None)`.
2. **`P0-3` Non-Destructive Coordinate Rescaling**: `FrameProcessor._rescale_tracks_and_detections()` must continue returning coordinate-rescaled copies without mutating internal tracker bbox/centroid state, while syncing non-coordinate governance metadata (`is_cluttered`, `clutter_partner_id`, `clutter_start_time`, `entity_id`, `entity_name`, `entity_category`, `identity_label`, `session_id`, `reid_score`) back onto `bundle.tracker.tracks[tid]`.
3. **`P0-1` Dual-Clock Domain Boundary**: All domain timestamps passed into `FrameProcessor.step()`, `GalleryMatcher`, `WorldEntityBridge`, `OwnershipAssociationEngine`, `EventBus`, and `EventFTSIndex` must remain Unix wall-clock epoch `time.time()` (never `time.monotonic()`).
4. **Lock Hierarchy & Zero I/O Under Lock**: Never dispatch `EventBus` events, perform SQLite writes, or run blocking I/O while holding `WorldGraph._lock`.
5. **Legacy Test Compatibility**: Preserve compatibility with `tests/test_tracker.py`, `tests/test_matcher.py`, `tests/test_occlusion_and_ema.py`, and `tests/test_cached_replay_and_pool_scheduler.py` (including `test_detection_stream_exposes_config_and_tightens_sample_rate_tolerance`).

---

## Milestone 1: Persistent Coasting, Track Attribute Preservation & Re-ID Retention

- [x] **intelligent_tracker/tracker/track.py**: Support canonical states (`tentative`, `confirmed`, `coasting`, `occluded`, `deleted`), accept configurable `min_hits` in `Track.update(..., min_hits=2)`, and include `is_cluttered` and `clutter_partner_id` in `Track.to_dict()` while preserving the `entity_id` omission invariant.
- [x] **intelligent_tracker/tracker/occlusion.py**: Evaluate occlusion/clutter for both active and coasting tracks (`missed_frames >= 0`) and transition overlapping coasting tracks (`missed_frames > 0`) to `state="occluded"` until re-detected.
- [x] **intelligent_tracker/tracker/sort.py**: Persist `Track` instances per `KalmanBoxTracker.id` (`self._active_tracks`) instead of reinstantiating fresh `Track` objects each frame; add configurable coasting (`coast_frames` / `coast_seconds`, ~1.5s grace) emitting `coasting`/`occluded` tracks with predicted Kalman boxes; prune `track_metadata` and `_active_tracks` on expiration; fix `ruff` E741 (`I` -> `eye`) and `mypy` annotations on `matched_trks`/`matched_dets`.
- [x] **intelligent_tracker/tracker/centroid.py**: Add `coast_seconds` support alongside `coast_frames`, pass `min_hits=self.min_hits` into `trk.update(...)`, set `coasting`/`occluded` states on missed coast frames (keeping compatibility with existing `tests/test_tracker.py` assertions), and fix `mypy` annotations on `compute_iou_matrix` / `matched_tracks` / `matched_dets`.
- [x] **intelligent_tracker/pipeline/config.py**, **intelligent_tracker/pipeline/bundle.py**, **intelligent_tracker/pipeline/frame_processor.py**: Add `tracker_coast_seconds: float = 1.5` and `tracker_coast_frames: int = 15` to `PipelineConfig` and wire into `build_tracker()`; extract `_sync_governance_attrs_to_tracker()` in `frame_processor.py` so `step()` stays `<= 40L` and governance attributes (`is_cluttered`, `clutter_partner_id`, `entity_id`, `session_id`, `reid_score`) persist back to `bundle.tracker.tracks` without mutating internal tracker coordinates (`P0-3`).
- [x] **intelligent_tracker/matching/feature_buffer.py** *(New)* & **intelligent_tracker/matching/gallery.py**: Extract `TrackFeatureBuffer` (feature deques, grace-period TTL pruning with `coast_grace_seconds=2.0`, `_identified_tracks`, `_last_sighting_time`) to shrink `gallery.py` toward `< 350L`; guard `match_track()` so coasting/occluded tracks (`missed_frames > 0` or `state in ("coasting", "occluded", "predicting")`) skip `extractor.extract()` (zero background pixel pollution) while retaining cached features and identity bindings across short dropouts.
- [x] **intelligent_tracker/world/entity_bridge.py**: Update `prune_stale_tracks()` to retain `WorldEntity` bindings for coasting/occluded tracks within `coasting_grace_seconds` (default `2.0s`) and fix the `mypy` type error at `sync_session_track`.
- [x] **tests/test_persistent_coasting.py** *(New)*: Add unit/integration tests covering `SortTracker` & `CentroidTracker` `confirmed -> coasting -> confirmed` and `occluded` transitions, `Track` attribute preservation across frames & rescaled `FrameProcessor.step()`, zero feature pollution + Re-ID retention in `GalleryMatcher`, and `WorldEntityBridge` coasting retention.

---

## Milestone 2: Class-Consistency, Appearance-Assisted Association & Replay Gap Continuity

> *Deferred to Next Turn / Milestone 2*

- [x] **intelligent_tracker/tracker/association.py** *(New)*: Create pure association helpers (`classes_compatible`, `compute_appearance_similarity`, `build_fused_cost_matrix`) enforcing class-consistency (blocking `person <-> chair` swaps while allowing generic `"object"` fallback) and fusing IoU with optional appearance cosine similarity.
- [x] **intelligent_tracker/tracker/sort.py** & **intelligent_tracker/tracker/centroid.py**: Delegate association scoring to `intelligent_tracker/tracker/association.py` so incompatible classes cannot swap IDs and appearance embeddings assist re-association across occlusion cross-overs (keeping `CentroidTracker <= 12` methods and `SortTracker <= 10` methods).
- [x] **intelligent_tracker/matching/_gallery_matching.py** *(New)*, **intelligent_tracker/matching/gallery.py**, **intelligent_tracker/matching/session_gallery.py**: Extract persistent matching helpers so `gallery.py < 350L` and all functions `<= 40L`; enforce class/category compatibility in `_match_persistent_gallery`; attach `track.last_embedding` on matched tracks for tracker appearance feedback; ensure `SessionGalleryManager` re-links cleanly across `VideoIndexer` sampling gaps.
- [x] **dashboard/services/cached_replay_provider.py**: Add configurable short-gap coasting (`replay_coast_seconds: float = 0.5`) inside `CachedReplayProvider.build_step_result()` so brief `sample_rate > 1` / VFR gaps emit coasting tracks instead of `{}` (preventing false zone exits & box flicker), reset coast cache on loop wrap-around or seek jumps (`abs(dt) > 2.0s`), keep `FileDetectionReplayProvider.lookup_tracks()` strict for existing tests, and fix `mypy` annotations on `analytics_res`/`identifications`.
- [x] **tests/test_class_and_appearance_association.py** *(New)*: Add regression tests for zero `person <-> chair` swaps in `SortTracker` & `CentroidTracker`, occlusion cross-over recovery with appearance embeddings, persistent gallery class guard, and `CachedReplayProvider` short-gap coasting without false zone exits.

---

## Milestone 3: Person+Bag WorldGraph Ownership (`CARRIES`/`OWNED_BY`), Unattended-Item Alerts & Full Sign-Off

> *Deferred to Next Turn / Milestone 3*

- [ ] **intelligent_tracker/world/edges.py** *(New)*, **intelligent_tracker/world/graph.py**, **intelligent_tracker/world/_lifecycle.py**: Add `WorldEdge` dataclass and `WorldEdgeRegistry` supporting typed entity-to-entity edges (`CARRIES`, `OWNED_BY`); compose into `WorldGraph` (`upsert_edge`, `remove_edge`, `get_edges`, `snapshot()["edges"]`) with automatic cascade-pruning when entities or cameras are removed.
- [ ] **intelligent_tracker/world/ownership.py** *(New)*: Implement `OwnershipAssociationEngine` (wall-clock Unix epoch `timestamp`, configurable `carry_labels=("backpack", "handbag", "suitcase")`, `proximity_px`, `min_carry_seconds`, `unattended_seconds`, `separation_px`, `alert_cooldown_seconds`) to establish `CARRIES`/`OWNED_BY` edges and emit `UnattendedItemAlert` when a carried bag is left behind beyond threshold (clearing when owner returns).
- [ ] **intelligent_tracker/events/types.py**, **intelligent_tracker/events/__init__.py**, **intelligent_tracker/memory/_event_formatters.py**: Add `UnattendedItemAlert(BaseEvent)` (`event_type="unattended_item"`, location, `global_xy`, `bbox`, `owner_entity_id`, `owner_name`, `bag_track_id`, `item_label`, `unattended_duration_s`, `timestamp`) and register an explicit FTS formatter in `_event_formatters.py`.
- [ ] **intelligent_tracker/pipeline/bundle.py**, **intelligent_tracker/pipeline/post_detection_governance.py**, **dashboard/services/stream_telemetry.py**: Wire `OwnershipAssociationEngine` into `build_world()` (`PipelineEngine` / `CameraPool` / `StreamManager`), invoke it in `evaluate_tracks_governance()`, publish `UnattendedItemAlert` on `EventBus` outside `WorldGraph._lock`, and expose `carrying`/`carried_by` metadata in stream telemetry.
- [ ] **tests/test_world_ownership.py** *(New)*: Add end-to-end tests covering `WorldEdge` CRUD & cascade removal, `CARRIES`/`OWNED_BY` person+bag association, unattended/dropped-item alert emission with location & timestamp, owner-return cancellation, `EventFTSIndex` indexing, and live `PipelineEngine` / `FrameProcessor` wiring.
- [ ] **CHANGELOG.md**: Record Step 2 milestone completion via `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add` after passing full `unittest`, `diagnose.py audit/scan/surface`, workspace probes, and `sphinx -W`.

---

## Scenario Combinations Matrix

| Milestone | Scenario | Expected Behavior | Verifier Command |
| :--- | :--- | :--- | :--- |
| **Milestone 1** | Multi-frame dropout & occlusion (`confirmed -> coasting -> occluded -> confirmed`), rescaled `FrameProcessor.step()`, `GalleryMatcher` Re-ID retention | Track attributes (`is_cluttered`, `entity_id`, `session_id`) persist across frames; coasting skips `extractor.extract()`; `WorldEntity` stays bound within `coasting_grace_seconds` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests.test_persistent_coasting tests.test_tracker tests.test_matcher tests.test_occlusion_and_ema tests.test_world_entity_bridge tests.test_step2_clock_and_coordinates` |
| **Milestone 2** | `person` vs `chair` bounding-box overlap, crossing occlusion swap, `GalleryMatcher` class guard, `CachedReplayProvider` `sample_rate > 1` gap | Zero `person <-> chair` ID swaps; appearance similarity re-links crossing tracks; persistent gallery rejects incompatible classes; replay gap emits coasting tracks without false zone exits | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests.test_class_and_appearance_association tests.test_cached_replay_and_pool_scheduler tests.test_pipeline_parity tests.test_step5_batch_frame_processor` |
| **Milestone 3** | Person carries `backpack`/`handbag`/`suitcase`, separates past `separation_px` and `unattended_seconds`, then returns or entity removed | `CARRIES` / `OWNED_BY` edges created in `WorldGraph`; `UnattendedItemAlert` emitted with location + timestamp + FTS index entry; owner return clears alert; cascade deletes prune edges | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" tests tests.test_world_ownership tests.test_world_graph tests.test_world_pipeline_integration tests.test_events_bus tests.test_step3_architecture_budgets` |
| **Final Sign-Off** | Cross-contract, modularity budgets, workspace probes, full regression & docs build | All budgets `< 350L` soft / `< 500L` hard (except untouched legacy waivers), 0 scan/surface defects, 4 probes pass, 100% `unittest` pass, 0 Sphinx warnings | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path intelligent_tracker dashboard && python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" scan --path intelligent_tracker dashboard scripts --strict && python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" surface --verify --strict && python -m unittest discover tests && python -m sphinx -W --keep-going documentation/ documentation/_build/html/` |
